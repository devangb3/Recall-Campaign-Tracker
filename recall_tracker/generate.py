"""Generate synthetic dealership CSVs for the recall campaign tracker.

One fictional dealership, three files:

* affected_vehicles.csv: vin, campaign_id
* notices_sent.csv:      vin, campaign_id, notice_date
* repairs_done.csv:      vin, campaign_id, repair_date, tech_note

Everything is made up by this script. VINs start with SYN (no real maker
uses it) and carry a valid check digit. Dates are written MM/DD/YYYY, the
dealership's US format. The same seed and as-of date always give
byte-identical files.

Usage:
    python -m recall_tracker.generate --seed 42 --as-of 2026-11-01 --out data/raw
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .vin import VIN_CHARS, with_check_digit

GENERATOR_VERSION = "0.1.0"
DEFAULT_SEED = 42
DEFAULT_AS_OF = date(2026, 11, 1)
DEFAULT_VEHICLES = 500

AFFECTED_FILE = "affected_vehicles.csv"
NOTICES_FILE = "notices_sent.csv"
REPAIRS_FILE = "repairs_done.csv"

COLUMNS = {
    AFFECTED_FILE: ["vin", "campaign_id"],
    NOTICES_FILE: ["vin", "campaign_id", "notice_date"],
    REPAIRS_FILE: ["vin", "campaign_id", "repair_date", "tech_note"],
}

# Campaign id -> (first notice date, last notice date). Notices for each
# campaign are mailed inside its window, never after the as-of date.
CAMPAIGNS = {
    "RC-2025-007": (date(2025, 9, 1), date(2025, 12, 31)),
    "RC-2026-001": (date(2026, 1, 1), date(2026, 4, 30)),
    "RC-2026-002": (date(2026, 8, 15), date(2026, 10, 25)),
}

# Plain technician notes. Free text: the checks never read them.
TECH_NOTES = [
    "Replaced airbag inflator module per bulletin.",
    "Reflashed ECU software, test drive OK.",
    "Replaced fuel pump relay. No leaks found.",
    "Inspected and replaced brake hose, both sides.",
    'Customer reports "rattle" gone after fix.',
    "Replaced seat belt pretensioner, driver side.",
    "Updated software, cleared stored codes.",
    "Parts on hand, completed same day.",
    "",
]

# Background rates.
P_SECOND_CAMPAIGN = 0.15   # vehicle is in two campaigns
P_NOT_NOTIFIED = 0.08      # affected, but no notice row
P_NEVER_REPAIRED = 0.20    # notified, but no repair row
MAX_REPAIR_DELAY = 150     # days from notice to repair


@dataclass
class Row:
    """One data row of one file, before it is written out."""

    file: str
    values: dict
    tag: str = "background"


def fmt_us(d: date) -> str:
    """Write a date the way the dealership does: MM/DD/YYYY."""
    return d.strftime("%m/%d/%Y")


def random_date(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


class VinFactory:
    """Make unique fake VINs: SYN + 5 chars + check digit + 8 chars."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.used: set[str] = set()

    def new(self) -> str:
        while True:
            body = "SYN" + "".join(self.rng.choice(VIN_CHARS) for _ in range(5))
            tail = self.rng.choice("RSTV") + self.rng.choice("ABC")
            tail += "".join(self.rng.choice("0123456789") for _ in range(6))
            vin = with_check_digit(body + "0" + tail)
            if vin not in self.used:
                self.used.add(vin)
                return vin


def background_rows(rng: random.Random, vins: VinFactory, n: int,
                    as_of: date) -> list[Row]:
    """Clean rows for n vehicles: affected, mostly notified, mostly repaired."""
    rows: list[Row] = []
    campaign_ids = list(CAMPAIGNS)
    for _ in range(n):
        vin = vins.new()
        campaigns = [rng.choice(campaign_ids)]
        if rng.random() < P_SECOND_CAMPAIGN:
            other = rng.choice([c for c in campaign_ids if c != campaigns[0]])
            campaigns.append(other)
        for cid in sorted(campaigns):
            rows.append(Row(AFFECTED_FILE, {"vin": vin, "campaign_id": cid}))
            if rng.random() < P_NOT_NOTIFIED:
                continue
            start, end = CAMPAIGNS[cid]
            end = min(end, as_of - timedelta(days=1))
            if start > end:
                continue  # campaign has not mailed yet at this as-of date
            notice = random_date(rng, start, end)
            rows.append(Row(NOTICES_FILE, {
                "vin": vin, "campaign_id": cid, "notice_date": fmt_us(notice)}))
            if rng.random() < P_NEVER_REPAIRED:
                continue
            repair = notice + timedelta(days=rng.randint(0, MAX_REPAIR_DELAY))
            if repair > as_of:
                continue  # not repaired yet
            rows.append(Row(REPAIRS_FILE, {
                "vin": vin, "campaign_id": cid, "repair_date": fmt_us(repair),
                "tech_note": rng.choice(TECH_NOTES)}))
    return rows


def render_csv(columns: list[str], rows: list[Row]) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row.values.get(c, "") for c in columns])
    return buf.getvalue().encode("utf-8")


def generate(seed: int = DEFAULT_SEED, as_of: date = DEFAULT_AS_OF,
             n_vehicles: int = DEFAULT_VEHICLES) -> dict[str, list[Row]]:
    """Build all rows, grouped by file, in final file order."""
    rng = random.Random(seed)
    vins = VinFactory(rng)
    rows = background_rows(rng, vins, n_vehicles, as_of)
    by_file: dict[str, list[Row]] = {f: [] for f in COLUMNS}
    for row in rows:
        by_file[row.file].append(row)
    for name in COLUMNS:
        rng.shuffle(by_file[name])
    return by_file


def write_outputs(by_file: dict[str, list[Row]], out_dir: Path, seed: int,
                  as_of: date) -> dict:
    """Write the three CSVs and manifest.json. Return the manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, columns in COLUMNS.items():
        data = render_csv(columns, by_file[name])
        (out_dir / name).write_bytes(data)
        files[name] = {"rows": len(by_file[name]),
                       "sha256": hashlib.sha256(data).hexdigest()}
    manifest = {
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "as_of": as_of.isoformat(),
        "files": files,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--as-of", type=date.fromisoformat, default=DEFAULT_AS_OF,
                        help="as-of date, YYYY-MM-DD (default 2026-11-01)")
    parser.add_argument("--vehicles", type=int, default=DEFAULT_VEHICLES)
    parser.add_argument("--out", type=Path, default=Path("data/raw"))
    args = parser.parse_args(argv)
    by_file = generate(args.seed, args.as_of, args.vehicles)
    manifest = write_outputs(by_file, args.out, args.seed, args.as_of)
    for name, info in manifest["files"].items():
        print(f"{name}: {info['rows']} rows")
    print(f"Wrote files to {args.out}/")


if __name__ == "__main__":
    main()
