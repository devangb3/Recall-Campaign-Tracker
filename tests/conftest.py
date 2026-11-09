"""Shared fixtures and an independent reference checker for the tests.

The reference checker (find_issues) is written separately from the
generator on purpose: the generator says what it planted, and this module
works out what is actually in the files. The tests compare the two.
"""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

import pytest

from recall_tracker import generate as gen

AS_OF = date(2026, 11, 1)
SMALL = {"seed": 7, "n_vehicles": 60}
FULL = {"seed": 42, "n_vehicles": 500}
CAMPAIGNS = {"RC-2025-007", "RC-2026-001", "RC-2026-002"}


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_dataset(out: Path, seed: int, n_vehicles: int,
                  as_of: date = AS_OF) -> Path:
    by_file = gen.generate(seed, as_of, n_vehicles)
    gen.write_outputs(by_file, out, seed, as_of)
    return out


@pytest.fixture(scope="session")
def small_dir(tmp_path_factory) -> Path:
    return write_dataset(tmp_path_factory.mktemp("seed7"), **SMALL)


@pytest.fixture(scope="session")
def full_dir(tmp_path_factory) -> Path:
    return write_dataset(tmp_path_factory.mktemp("seed42"), **FULL)


@pytest.fixture(scope="session", params=["small", "full"])
def data_dir(request, small_dir, full_dir) -> Path:
    return small_dir if request.param == "small" else full_dir


@pytest.fixture(scope="session")
def files(data_dir) -> dict[str, list[dict]]:
    return {name: read_csv(data_dir / name)
            for name in (*gen.COLUMNS, gen.MESS_LOG_FILE)}


@pytest.fixture(scope="session")
def mess_log(files) -> list[dict]:
    return files[gen.MESS_LOG_FILE]


# ---- reference checker -------------------------------------------------
_VIN_ALLOWED = set("ABCDEFGHJKLMNPRSTUVWXYZ0123456789")
_VALUES = dict(zip("0123456789", range(10)))
_VALUES.update(dict(zip("ABCDEFGH", range(1, 9))))
_VALUES.update(dict(zip("JKLMN", range(1, 6))))
_VALUES.update({"P": 7, "R": 9})
_VALUES.update(dict(zip("STUVWXYZ", range(2, 10))))
_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]


def ref_vin(raw: str) -> str | None:
    """Fix a VIN the safe way, or return None if it is not valid."""
    vin = raw.strip().upper().replace(" ", "").replace("-", "")
    if len(vin) != 17 or not set(vin) <= _VIN_ALLOWED:
        return None
    rem = sum(_VALUES[c] * w for c, w in zip(vin, _WEIGHTS)) % 11
    return vin if vin[8] == ("X" if rem == 10 else str(rem)) else None


def ref_campaign(raw: str) -> str | None:
    m = re.fullmatch(r"RC[\s_-]*(\d{4})[\s_-]*(\d{1,3})", raw.strip(),
                     re.IGNORECASE)
    return f"RC-{m.group(1)}-{int(m.group(2)):03d}" if m else None


def ref_date(raw: str) -> date | None:
    raw = raw.strip()
    try:
        if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw):
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw):
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return None


DATE_COL = {gen.NOTICES_FILE: "notice_date", gen.REPAIRS_FILE: "repair_date"}


def find_issues(files: dict, as_of: date = AS_OF):
    """Return (issues, clean) found by the reference checker.

    issues: set of (file, row_num, issue_code, action).
    clean: file -> list of (vin, campaign_id, date or None, row_num).
    """
    issues = set()
    clean = {}
    for name in (gen.AFFECTED_FILE, gen.NOTICES_FILE, gen.REPAIRS_FILE):
        clean[name] = []
        for num, row in enumerate(files[name], start=2):
            codes = []
            vin = cid = d = None
            for col in ("vin", "campaign_id", DATE_COL.get(name)):
                if col is None:
                    continue
                raw = row[col]
                if not raw.strip():
                    codes.append("MISSING_VALUE")
                elif col == "vin":
                    vin = ref_vin(raw) or codes.append("BAD_VIN")
                elif col == "campaign_id":
                    cid = ref_campaign(raw) or codes.append("BAD_CAMPAIGN")
                else:
                    d = ref_date(raw)
                    if d is None:
                        codes.append("BAD_DATE")
                    elif d > as_of:
                        codes.append("FUTURE_DATE")
            for code in codes:
                issues.add((name, num, code, "quarantined"))
            if not codes:
                clean[name].append((vin, cid, d, num))

    # Exact duplicates, then date conflicts, within each file.
    for name in (gen.AFFECTED_FILE, gen.NOTICES_FILE, gen.REPAIRS_FILE):
        seen, kept = set(), []
        for rec in clean[name]:
            key = rec[:3]
            if key in seen:
                issues.add((name, rec[3], "DUPLICATE_ROW", "dropped_duplicate"))
            else:
                seen.add(key)
                kept.append(rec)
        clean[name] = kept
        if name in DATE_COL:
            first_date = {}
            for vin, cid, d, num in kept:
                if (vin, cid) in first_date and first_date[(vin, cid)] != d:
                    issues.add((name, num, "DATE_CONFLICT", "kept"))
                first_date.setdefault((vin, cid), d)

    affected = {(v, c) for v, c, _, _ in clean[gen.AFFECTED_FILE]}
    earliest = {}
    for v, c, d, _ in clean[gen.NOTICES_FILE]:
        earliest[(v, c)] = min(d, earliest.get((v, c), d))
    for name in DATE_COL:
        for v, c, d, num in clean[name]:
            if (v, c) not in affected:
                issues.add((name, num, "NOT_IN_AFFECTED", "kept"))
    for v, c, d, num in clean[gen.REPAIRS_FILE]:
        if (v, c) in earliest and d < earliest[(v, c)]:
            issues.add((gen.REPAIRS_FILE, num, "REPAIR_BEFORE_NOTICE", "kept"))
    return issues, clean


def write_master_data(folder, rows):
    """Complete legacy test scenarios with independent, eligible masters."""
    vins = sorted({v for row in rows if row and (v := ref_vin(row[0]))})
    campaigns = sorted({c for row in rows if len(row) > 1 and (c := ref_campaign(row[1]))})
    for name, header, values in (
        ("vehicles.csv", ["vin", "model", "build_date"],
         [[v, "SEDAN", "2024-01-01"] for v in vins]),
        ("campaigns.csv", ["campaign_id", "model", "start_date", "end_date"],
         [[c, "SEDAN", "2020-01-01", "2030-12-31"] for c in campaigns]),
    ):
        with (folder / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(values)
