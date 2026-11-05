"""Generate synthetic dealership CSVs for the recall campaign tracker.

One fictional dealership, three files:

* affected_vehicles.csv: vin, campaign_id
* notices_sent.csv:      vin, campaign_id, notice_date
* repairs_done.csv:      vin, campaign_id, repair_date, tech_note

Everything is made up by this script. VINs start with SYN (no real maker
uses it) and carry a valid check digit. Dates are written MM/DD/YYYY, the
dealership's US format. The same seed and as-of date always give
byte-identical files.

Planted cases and safe mess are added by plant.py. Each planted data issue
is listed in planted_issues.csv, the mess log the tests compare against.

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

from . import plant
from .vin import VIN_CHARS, with_check_digit

GENERATOR_VERSION = "0.2.0"
DEFAULT_SEED = 42
DEFAULT_AS_OF = date(2026, 11, 1)
DEFAULT_VEHICLES = 500

AFFECTED_FILE = "affected_vehicles.csv"
NOTICES_FILE = "notices_sent.csv"
REPAIRS_FILE = "repairs_done.csv"
MESS_LOG_FILE = "planted_issues.csv"
MESS_LOG_COLUMNS = ["file", "row_num", "column", "issue_code", "action",
                    "reason"]
MIN_BACKGROUND = 10

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
    issue: dict | None = None   # planted data issue, if any
    link: tuple | None = None   # ties a duplicate or date conflict pair


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


def render_dicts(columns: list[str], rows: list[dict]) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def generate(seed: int = DEFAULT_SEED, as_of: date = DEFAULT_AS_OF,
             n_vehicles: int = DEFAULT_VEHICLES) -> dict[str, list[Row]]:
    """Build all rows, grouped by file, in final file order.

    n_vehicles counts every VIN in the affected file: planted vehicles
    first, then background vehicles to make up the total.
    """
    if as_of < plant.DAY61_REPAIR + timedelta(days=60):
        raise ValueError("as-of date must be on or after 2026-05-01")
    rng = random.Random(seed)
    vins = VinFactory(rng)
    planted = (plant.business_case_rows(rng, vins, as_of)
               + plant.data_issue_rows(rng, vins, as_of))
    planted_affected = {r.values["vin"] for r in planted
                        if r.file == AFFECTED_FILE}
    n_background = max(n_vehicles - len(planted_affected), MIN_BACKGROUND)
    background = background_rows(rng, vins, n_background, as_of)
    plant.apply_safe_mess(rng, background)

    by_file: dict[str, list[Row]] = {f: [] for f in COLUMNS}
    for row in background + planted:
        by_file[row.file].append(row)
    for name in COLUMNS:
        by_file[name] = plant.order_rows(rng, by_file[name])
        plant.attach_linked_issues(name, by_file[name])
    return by_file


def write_outputs(by_file: dict[str, list[Row]], out_dir: Path, seed: int,
                  as_of: date) -> dict:
    """Write the three CSVs, planted_issues.csv and manifest.json.

    Return the manifest.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, columns in COLUMNS.items():
        data = render_csv(columns, by_file[name])
        (out_dir / name).write_bytes(data)
        files[name] = {"rows": len(by_file[name]),
                       "sha256": hashlib.sha256(data).hexdigest()}
    log = plant.mess_log(by_file)
    log_bytes = render_dicts(MESS_LOG_COLUMNS, log)
    (out_dir / MESS_LOG_FILE).write_bytes(log_bytes)
    files[MESS_LOG_FILE] = {"rows": len(log),
                            "sha256": hashlib.sha256(log_bytes).hexdigest()}
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
    for name in COLUMNS:
        info = manifest["files"][name]
        print(f"{name}: {info['rows']} rows")
    print(f"{MESS_LOG_FILE}: {manifest['files'][MESS_LOG_FILE]['rows']} planted data issues")
    print(f"Wrote files to {args.out}/")


if __name__ == "__main__":
    main()
