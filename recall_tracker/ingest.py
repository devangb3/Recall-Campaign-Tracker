"""Read, check and load the five dealership CSVs into recall.db.

Order of work:

1. Read all five files. If any file is missing, cannot be read, is
   empty, or lacks a required column, stop straight away with a clear
   error naming the file and the problem. Nothing is written and
   recall.db is left as it was (client decision, 4 Nov 2026).
2. Check every row (validate). Safe fixes come from normalize.py. A row
   with a bad or blank value is quarantined with an issue code and a
   reason. Then, on the rows that are left: repeated rows are dropped,
   and date conflicts, repairs before the notice, and notices or repairs for
   vehicles absent from the affected file are flagged but kept. Vehicle/campaign
   masters also supply the independent unaffected-repair eligibility check.
3. Load everything in one SQLite transaction (load). Before commit, the
   row balance must hold for every file:
   raw rows = clean rows + quarantined rows + dropped duplicates.
   Otherwise, or on any unexpected error, roll back.

Row numbers (src_row) are spreadsheet row numbers: the header is row 1.
A completely blank row (every cell empty) is skipped and not counted.

tech_note is free text. It is stored exactly as written and never read.

Usage:
    python -m recall_tracker.ingest --raw data/raw --db data/recall.db \\
        --as-of 2026-11-01
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from .normalize import (Result, normalize_campaign, normalize_header,
                        normalize_model, normalize_note, normalize_vin, parse_date)

AFFECTED_FILE = "affected_vehicles.csv"
NOTICES_FILE = "notices_sent.csv"
REPAIRS_FILE = "repairs_done.csv"
VEHICLES_FILE = "vehicles.csv"
CAMPAIGNS_FILE = "campaigns.csv"
MASTER_FILES = (VEHICLES_FILE, CAMPAIGNS_FILE)
FILES = (AFFECTED_FILE, NOTICES_FILE, REPAIRS_FILE, *MASTER_FILES)

# Columns each file must have. tech_note is optional: if the column is
# missing, every note is stored as empty text.
REQUIRED = {
    AFFECTED_FILE: ("vin", "campaign_id"),
    NOTICES_FILE: ("vin", "campaign_id", "notice_date"),
    REPAIRS_FILE: ("vin", "campaign_id", "repair_date"),
    VEHICLES_FILE: ("vin", "model", "build_date"),
    CAMPAIGNS_FILE: ("campaign_id", "model", "start_date", "end_date"),
}
OPTIONAL = {REPAIRS_FILE: ("tech_note",)}
DATE_COLUMN = {NOTICES_FILE: "notice_date", REPAIRS_FILE: "repair_date"}
DATE_LABEL = {NOTICES_FILE: "Notice date", REPAIRS_FILE: "Repair date"}

# REC-18: the one list of issue codes and the action each one takes.
ACTION_FOR = {
    "MISSING_VALUE": "quarantined",
    "BAD_VIN": "quarantined",
    "BAD_DATE": "quarantined",
    "BAD_CAMPAIGN": "quarantined",
    "FUTURE_DATE": "quarantined",
    "DUPLICATE_ROW": "dropped_duplicate",
    "DATE_CONFLICT": "kept",
    "REPAIR_BEFORE_NOTICE": "kept",
    "NOT_IN_AFFECTED": "kept",
    "BAD_DATE_RANGE": "quarantined",
    "CONFLICTING_MASTER": "quarantined",
    "ELIGIBILITY_UNAVAILABLE": "kept",
}


class IngestStopError(Exception):
    """A whole file is unusable. Nothing was loaded."""


class RowBalanceError(Exception):
    """Rows went missing between reading and loading. Rolled back."""


# ---- results -------------------------------------------------------------
@dataclass
class RawFile:
    name: str
    sha256: str
    headers: list[str]          # headers exactly as written
    columns: dict[str, int]     # contract column -> cell position
    rows: list[tuple[int, list[str]]]  # (src_row, cells), blank rows skipped


@dataclass
class Issue:
    file: str
    src_row: int
    column: str
    raw_value: str
    issue_code: str
    reason: str
    raw_row: str
    vin: str | None = None
    campaign_id: str | None = None

    @property
    def action(self) -> str:
        return ACTION_FOR[self.issue_code]


@dataclass
class CleanRow:
    """Accepted row. Masters carry model/build metadata instead of an event date."""

    file: str
    src_row: int
    vin: str
    campaign_id: str
    date: date | None = None
    tech_note: str | None = None
    model: str | None = None
    build_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None


@dataclass
class IngestResult:
    as_of: date
    files: dict[str, RawFile]
    clean: dict[str, list[CleanRow]] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    quarantined: dict[str, list[tuple[int, str, list[str]]]] = field(
        default_factory=dict)   # file -> [(src_row, raw_json, codes)]
    dropped: dict[str, int] = field(default_factory=dict)

    def row_counts(self) -> dict[str, dict[str, int]]:
        return {name: {
            "raw": len(self.files[name].rows),
            "clean": len(self.clean[name]),
            "quarantined": len(self.quarantined[name]),
            "dropped_duplicate": self.dropped[name],
        } for name in FILES}

    def check_row_balance(self) -> None:
        for name, c in self.row_counts().items():
            if c["raw"] != c["clean"] + c["quarantined"] + c["dropped_duplicate"]:
                raise RowBalanceError(
                    f"Row counts for {name} do not balance: {c}. "
                    "Nothing was changed.")


# ---- step 1: read the files ---------------------------------------------
def _stop(name: str, raw_dir: Path, problem: str) -> IngestStopError:
    return IngestStopError(
        f"Cannot run check: {name} {problem} in {raw_dir}/. "
        "Nothing was changed." if problem == "was not found" else
        f"Cannot run check: {name} {problem}. Nothing was changed.")


def read_file(raw_dir: Path, name: str) -> RawFile:
    """Read one CSV as text. Raise IngestStopError if it is unusable."""
    path = raw_dir / name
    if not path.exists():
        raise _stop(name, raw_dir, "was not found")
    if not path.is_file():
        raise _stop(name, raw_dir, "is a folder, not a file")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise _stop(name, raw_dir,
                    f"could not be opened ({exc.strerror})") from exc
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _stop(name, raw_dir,
                    "could not be read because it is not UTF-8 text") from exc
    if not text.strip():
        raise _stop(name, raw_dir, "is empty")
    try:
        records = list(csv.reader(text.splitlines(keepends=True), strict=True))
    except csv.Error as exc:
        raise _stop(name, raw_dir,
                    f"could not be read as CSV ({exc})") from exc

    # The header is the first record that is not blank.
    start = next(i for i, r in enumerate(records) if any(c.strip() for c in r))
    headers = records[start]
    columns: dict[str, int] = {}
    for pos, raw_header in enumerate(headers):
        col = normalize_header(raw_header)
        if col is None:
            continue  # extra columns are ignored, but kept in the raw row
        if col in columns:
            raise _stop(name, raw_dir,
                        f"has two columns that both mean {col}")
        columns[col] = pos
    for col in REQUIRED[name]:
        if col not in columns:
            raise _stop(name, raw_dir, f"has no {col} column")

    rows = []
    for offset, cells in enumerate(records[start + 1:], start=start + 2):
        if any(c.strip() for c in cells):
            rows.append((offset, cells))
    return RawFile(name, hashlib.sha256(data).hexdigest(), headers, columns,
                   rows)


def read_all(raw_dir: Path) -> dict[str, RawFile]:
    """Read the five files, in order. Stop at the first unusable one."""
    return {name: read_file(Path(raw_dir), name) for name in FILES}


# ---- step 2: check the rows ---------------------------------------------
def _cell(raw: RawFile, cells: list[str], col: str) -> str | None:
    pos = raw.columns.get(col)
    if pos is None or pos >= len(cells):
        return None
    return cells[pos]


def _raw_json(raw: RawFile, cells: list[str]) -> str:
    """The whole raw row as JSON, keyed by the headers as written."""
    width = max(len(raw.headers), len(cells))
    headers = raw.headers + [f"extra_{i}" for i in range(len(raw.headers),
                                                         width)]
    values = cells + [""] * (width - len(cells))
    return json.dumps(dict(zip(headers, values)), ensure_ascii=False)


def validate(files: dict[str, RawFile], as_of: date) -> IngestResult:
    """Check every row of the five files. Writes nothing."""
    result = IngestResult(as_of, files)
    for name in FILES:
        _check_rows(result, files[name], as_of)
    for name in MASTER_FILES:
        _quarantine_master_conflicts(result, name)
    for name in FILES:
        _drop_duplicates(result, name)
    for name in DATE_COLUMN:
        _flag_date_conflicts(result, name)
    _flag_not_in_affected(result)
    _flag_repair_before_notice(result)
    _flag_missing_eligibility(result)
    result.issues.sort(key=lambda i: (FILES.index(i.file), i.src_row,
                                      list(ACTION_FOR).index(i.issue_code)))
    return result


def _check_rows(result: IngestResult, raw: RawFile, as_of: date) -> None:
    name = raw.name
    result.clean[name] = []
    result.quarantined[name] = []
    result.dropped[name] = 0
    for src_row, cells in raw.rows:
        raw_json = _raw_json(raw, cells)
        vin_raw = _cell(raw, cells, "vin")
        cid_raw = _cell(raw, cells, "campaign_id")
        vin_res = normalize_vin(vin_raw) if name != CAMPAIGNS_FILE else Result("")
        cid_res = normalize_campaign(cid_raw) if name != VEHICLES_FILE else Result("")
        checks = []
        if name != CAMPAIGNS_FILE:
            checks.append(("vin", vin_raw, vin_res))
        if name != VEHICLES_FILE:
            checks.append(("campaign_id", cid_raw, cid_res))
        metadata = {}
        if name in MASTER_FILES:
            model_raw = _cell(raw, cells, "model")
            model_res = normalize_model(model_raw)
            checks.append(("model", model_raw, model_res))
            metadata["model"] = model_res.value
            for col in (("build_date",) if name == VEHICLES_FILE
                        else ("start_date", "end_date")):
                value = _cell(raw, cells, col)
                # Campaign boundaries describe vehicle production, not
                # event dates; future boundaries are allowed.
                res = parse_date(value, col.replace("_", " ").capitalize(),
                                 as_of if name == VEHICLES_FILE else None)
                checks.append((col, value, res))
                metadata[col] = res.value
            if (name == CAMPAIGNS_FILE and metadata["start_date"] is not None
                    and metadata["end_date"] is not None
                    and metadata["start_date"] > metadata["end_date"]):
                checks.append(("end_date", _cell(raw, cells, "end_date"), Result(
                    issue_code="BAD_DATE_RANGE",
                    reason="Campaign start date is after its end date.")))
        date_res = None
        if name in DATE_COLUMN:
            col = DATE_COLUMN[name]
            date_raw = _cell(raw, cells, col)
            date_res = parse_date(date_raw, DATE_LABEL[name], as_of)
            checks.append((col, date_raw, date_res))
        bad = [(col, raw_value, res) for col, raw_value, res in checks
               if not res.ok]
        if bad:
            for col, raw_value, res in bad:
                result.issues.append(Issue(
                    name, src_row, col, raw_value or "", res.issue_code,
                    res.reason, raw_json, vin_res.value or None, cid_res.value or None))
            result.quarantined[name].append(
                (src_row, raw_json, [res.issue_code for _, _, res in bad]))
            continue
        note = None
        if name == REPAIRS_FILE:
            note = normalize_note(_cell(raw, cells, "tech_note"))
        result.clean[name].append(CleanRow(
            name, src_row, vin_res.value, cid_res.value,
            date_res.value if date_res else None, note, **metadata))


def _quarantine_master_conflicts(result: IngestResult, name: str) -> None:
    """Block ambiguous identifiers, including malformed duplicate records."""
    identifier = "vin" if name == VEHICLES_FILE else "campaign_id"
    normalize = normalize_vin if name == VEHICLES_FILE else normalize_campaign
    groups = {}
    for row in result.clean[name]:
        groups.setdefault(getattr(row, identifier), []).append(row)
    invalid = set()
    raw = result.files[name]
    quarantined = {n for n, _, _ in result.quarantined[name]}
    for src_row, cells in raw.rows:
        if src_row in quarantined:
            key = normalize(_cell(raw, cells, identifier))
            if key.ok:
                invalid.add(key.value)
    keep = []
    for key, rows in groups.items():
        values = {(r.model, r.build_date, r.start_date, r.end_date) for r in rows}
        if len(values) > 1 or key in invalid:
            for row in rows:
                _row_issue(result, row, "CONFLICTING_MASTER", identifier,
                            f"Conflicting records for {identifier} {key}; "
                            "campaign eligibility cannot be determined.")
                result.quarantined[name].append((
                    row.src_row, _raw_row_text(result, row), ["CONFLICTING_MASTER"]))
        else:
            keep.extend(rows)
    result.clean[name] = sorted(keep, key=lambda r: r.src_row)


def _raw_row_text(result: IngestResult, row: CleanRow) -> str:
    raw = result.files[row.file]
    cells = next(c for r, c in raw.rows if r == row.src_row)
    return _raw_json(raw, cells)


def _raw_cell(result: IngestResult, row: CleanRow, col: str) -> str:
    raw = result.files[row.file]
    cells = next(c for r, c in raw.rows if r == row.src_row)
    return _cell(raw, cells, col) or ""


def _row_issue(result, row: CleanRow, code: str, column: str,
                reason: str) -> None:
    result.issues.append(Issue(
        row.file, row.src_row, column,
        _raw_cell(result, row, column) if column else "", code, reason,
        _raw_row_text(result, row), row.vin or None, row.campaign_id or None))


def _drop_duplicates(result: IngestResult, name: str) -> None:
    """Same vin, campaign_id and date as an earlier row: keep the first.

    The tech_note is not compared, so two repairs on the same day with
    different notes count as one repair (the contract allows one repair
    per date for a vehicle). Master duplicates use their identifier after
    conflicting model/date records have already been quarantined.
    """
    first: dict[tuple, CleanRow] = {}
    kept = []
    for row in result.clean[name]:
        key = (row.vin, row.campaign_id, row.date)
        if key in first:
            earlier = first[key]
            same = (_raw_row_text(result, row)
                    == _raw_row_text(result, earlier))
            what = ("an exact copy of" if same else
                    "the same normalized master record as" if name in MASTER_FILES else
                    "the same vehicle, campaign and date as")
            _row_issue(result, row, "DUPLICATE_ROW", "",
                        f"Row is {what} row {earlier.src_row}.")
            result.dropped[name] += 1
        else:
            first[key] = row
            kept.append(row)
    result.clean[name] = kept


def _flag_date_conflicts(result: IngestResult, name: str) -> None:
    col = DATE_COLUMN[name]
    first: dict[tuple, CleanRow] = {}
    for row in result.clean[name]:
        pair = (row.vin, row.campaign_id)
        earlier = first.setdefault(pair, row)
        if earlier.date != row.date:
            label = DATE_LABEL[name].split()[0]
            _row_issue(
                result, row, "DATE_CONFLICT", col,
                f"{label} dates conflict for this vehicle and campaign: "
                f"{_raw_cell(result, earlier, col).strip()} (row "
                f"{earlier.src_row}) and {_raw_cell(result, row, col).strip()}"
                f" (row {row.src_row}).")


def _flag_not_in_affected(result: IngestResult) -> None:
    affected = {(r.vin, r.campaign_id) for r in result.clean[AFFECTED_FILE]}
    for name in DATE_COLUMN:
        for row in result.clean[name]:
            if (row.vin, row.campaign_id) not in affected:
                _row_issue(
                    result, row, "NOT_IN_AFFECTED", "",
                    f"VIN {row.vin} is not listed as affected by campaign "
                    f"{row.campaign_id}.")


def _flag_missing_eligibility(result: IngestResult) -> None:
    vehicles = {r.vin for r in result.clean[VEHICLES_FILE]}
    campaigns = {r.campaign_id for r in result.clean[CAMPAIGNS_FILE]}
    for row in result.clean[REPAIRS_FILE]:
        missing = []
        if row.vin not in vehicles:
            missing.append(f"vehicle {row.vin} in vehicles.csv")
        if row.campaign_id not in campaigns:
            missing.append(f"campaign {row.campaign_id} in campaigns.csv")
        if missing:
            _row_issue(result, row, "ELIGIBILITY_UNAVAILABLE", "",
                        "Cannot determine campaign eligibility: no unambiguous "
                        "valid record for " + " and ".join(missing) + ".")


def _flag_repair_before_notice(result: IngestResult) -> None:
    earliest: dict[tuple, CleanRow] = {}
    for row in result.clean[NOTICES_FILE]:
        pair = (row.vin, row.campaign_id)
        if pair not in earliest or row.date < earliest[pair].date:
            earliest[pair] = row
    for row in result.clean[REPAIRS_FILE]:
        notice = earliest.get((row.vin, row.campaign_id))
        if notice and row.date < notice.date:
            _row_issue(
                result, row, "REPAIR_BEFORE_NOTICE", "repair_date",
                f"Repair date {_raw_cell(result, row, 'repair_date').strip()}"
                f" is before the first notice date "
                f"{_raw_cell(result, notice, 'notice_date').strip()}.")


# ---- step 3: load recall.db ---------------------------------------------
_CODES_SQL = ", ".join(f"'{c}'" for c in ACTION_FOR)
_ACTIONS_SQL = ", ".join(f"'{a}'" for a in sorted(set(ACTION_FOR.values())))

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS ingests (
    ingest_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    as_of_date  TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status = 'complete'),
    files       TEXT NOT NULL,   -- JSON: name -> {{sha256, rows}}
    row_counts  TEXT NOT NULL    -- JSON: name -> raw/clean/quarantined/...
);
CREATE TABLE IF NOT EXISTS affected_vehicles (
    ingest_id   INTEGER NOT NULL REFERENCES ingests(ingest_id),
    src_file    TEXT NOT NULL,
    src_row     INTEGER NOT NULL,
    vin         TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    UNIQUE (ingest_id, vin, campaign_id),
    PRIMARY KEY (ingest_id, src_file, src_row)
);
CREATE TABLE IF NOT EXISTS notices_sent (
    ingest_id   INTEGER NOT NULL REFERENCES ingests(ingest_id),
    src_file    TEXT NOT NULL,
    src_row     INTEGER NOT NULL,
    vin         TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    notice_date TEXT NOT NULL,
    PRIMARY KEY (ingest_id, src_file, src_row)
);
CREATE TABLE IF NOT EXISTS repairs_done (
    ingest_id   INTEGER NOT NULL REFERENCES ingests(ingest_id),
    src_file    TEXT NOT NULL,
    src_row     INTEGER NOT NULL,
    vin         TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    repair_date TEXT NOT NULL,
    tech_note   TEXT NOT NULL,
    PRIMARY KEY (ingest_id, src_file, src_row)
);
CREATE TABLE IF NOT EXISTS vehicles (
    ingest_id INTEGER NOT NULL REFERENCES ingests(ingest_id),
    src_file TEXT NOT NULL,
    src_row INTEGER NOT NULL,
    vin TEXT NOT NULL,
    model TEXT NOT NULL,
    build_date TEXT NOT NULL,
    UNIQUE (ingest_id, vin),
    PRIMARY KEY (ingest_id, src_file, src_row)
);
CREATE TABLE IF NOT EXISTS campaigns (
    ingest_id INTEGER NOT NULL REFERENCES ingests(ingest_id),
    src_file TEXT NOT NULL,
    src_row INTEGER NOT NULL,
    campaign_id TEXT NOT NULL,
    model TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    CHECK (start_date <= end_date),
    UNIQUE (ingest_id, campaign_id),
    PRIMARY KEY (ingest_id, src_file, src_row)
);
CREATE TABLE IF NOT EXISTS data_issues (
    issue_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ingest_id   INTEGER NOT NULL REFERENCES ingests(ingest_id),
    file        TEXT NOT NULL,
    src_row     INTEGER NOT NULL,
    "column"    TEXT NOT NULL,
    raw_value   TEXT NOT NULL,
    issue_code  TEXT NOT NULL CHECK (issue_code IN ({_CODES_SQL})),
    action      TEXT NOT NULL CHECK (action IN ({_ACTIONS_SQL})),
    reason      TEXT NOT NULL,
    vin         TEXT,
    campaign_id TEXT,
    raw_row     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quarantine (
    ingest_id   INTEGER NOT NULL REFERENCES ingests(ingest_id),
    file        TEXT NOT NULL,
    src_row     INTEGER NOT NULL,
    raw_json    TEXT NOT NULL,
    issue_codes TEXT NOT NULL,
    PRIMARY KEY (ingest_id, file, src_row)
);
"""

CURRENT_TABLES = ("affected_vehicles", "notices_sent", "repairs_done",
                  "data_issues", "quarantine", "vehicles", "campaigns")
VIEWS = "\n".join(
    f"CREATE VIEW IF NOT EXISTS cur_{t} AS SELECT * FROM {t} WHERE ingest_id "
    f"= (SELECT MAX(ingest_id) FROM ingests WHERE status = 'complete');"
    for t in CURRENT_TABLES)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write(con: sqlite3.Connection, result: IngestResult,
          started_at: str) -> int:
    """Insert one ingest. The caller owns the transaction."""
    from .migrations import expand_check
    issue_schema = next(s for s in SCHEMA.split(";")
                        if "CREATE TABLE IF NOT EXISTS data_issues" in s)
    expand_check(con, "data_issues", "ELIGIBILITY_UNAVAILABLE", issue_schema,
                 current_view=True)
    for stmt in (SCHEMA + VIEWS).split(";"):
        if stmt.strip():
            con.execute(stmt)
    files_json = json.dumps({n: {"sha256": f.sha256, "rows": len(f.rows)}
                             for n, f in result.files.items()}, sort_keys=True)
    cur = con.execute(
        "INSERT INTO ingests (started_at, finished_at, as_of_date, status, "
        "files, row_counts) VALUES (?, ?, ?, 'complete', ?, ?)",
        (started_at, _now(), result.as_of.isoformat(), files_json,
         json.dumps(result.row_counts(), sort_keys=True)))
    ingest_id = cur.lastrowid
    con.executemany(
        "INSERT INTO affected_vehicles VALUES (?, ?, ?, ?, ?)",
        [(ingest_id, r.file, r.src_row, r.vin, r.campaign_id)
         for r in result.clean[AFFECTED_FILE]])
    con.executemany(
        "INSERT INTO notices_sent VALUES (?, ?, ?, ?, ?, ?)",
        [(ingest_id, r.file, r.src_row, r.vin, r.campaign_id,
          r.date.isoformat()) for r in result.clean[NOTICES_FILE]])
    con.executemany(
        "INSERT INTO repairs_done VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(ingest_id, r.file, r.src_row, r.vin, r.campaign_id,
          r.date.isoformat(), r.tech_note) for r in result.clean[REPAIRS_FILE]])
    con.executemany(
        "INSERT INTO vehicles VALUES (?, ?, ?, ?, ?, ?)",
        [(ingest_id, r.file, r.src_row, r.vin, r.model, r.build_date.isoformat())
         for r in result.clean[VEHICLES_FILE]])
    con.executemany(
        "INSERT INTO campaigns VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(ingest_id, r.file, r.src_row, r.campaign_id, r.model,
          r.start_date.isoformat(), r.end_date.isoformat())
         for r in result.clean[CAMPAIGNS_FILE]])
    con.executemany(
        'INSERT INTO data_issues (ingest_id, file, src_row, "column", '
        "raw_value, issue_code, action, reason, vin, campaign_id, raw_row) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(ingest_id, i.file, i.src_row, i.column, i.raw_value, i.issue_code,
          i.action, i.reason, i.vin, i.campaign_id, i.raw_row)
         for i in result.issues])
    con.executemany(
        "INSERT INTO quarantine VALUES (?, ?, ?, ?, ?)",
        [(ingest_id, name, src_row, raw_json, ",".join(codes))
         for name in FILES
         for src_row, raw_json, codes in result.quarantined[name]])
    return ingest_id


def prepare(raw_dir: Path, as_of: date | None = None) -> IngestResult:
    """Read and validate every file without opening or changing a database."""
    result = validate(read_all(Path(raw_dir)), as_of or date.today())
    result.check_row_balance()
    return result


def load_prepared(con: sqlite3.Connection, result: IngestResult,
                  started_at: str | None = None) -> int:
    """Load validated rows inside the caller's transaction.

    The tool pipeline uses this to save an ingest and its check results in
    one transaction. The CSV parser, safe fixes, issue codes and row-balance
    checks are the same as the standalone ingest command.
    """
    if not con.in_transaction:
        raise ValueError("loading prepared rows requires a transaction")
    result.check_row_balance()
    ingest_id = write(con, result, started_at or _now())
    _check_db_balance(con, ingest_id, result)
    return ingest_id


def load(raw_dir: Path, db_path: Path, as_of: date | None = None) -> int:
    """Read, check and load the five files. Return the new ingest_id.

    Raises IngestStopError (a file is unusable) before touching the
    database, so recall.db is not even created. Raises RowBalanceError or
    any unexpected error after rolling back, leaving recall.db as it was.
    """
    as_of = as_of or date.today()
    started_at = _now()
    result = prepare(raw_dir, as_of)
    con = sqlite3.connect(db_path, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        ingest_id = load_prepared(con, result, started_at)
        con.execute("COMMIT")
        return ingest_id
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def _check_db_balance(con, ingest_id: int, result: IngestResult) -> None:
    """Count what actually landed in the database for this ingest."""
    tables = {AFFECTED_FILE: "affected_vehicles",
              NOTICES_FILE: "notices_sent", REPAIRS_FILE: "repairs_done",
              VEHICLES_FILE: "vehicles", CAMPAIGNS_FILE: "campaigns"}
    for name, table in tables.items():
        clean = con.execute(f"SELECT COUNT(*) FROM {table} WHERE ingest_id=?",
                            (ingest_id,)).fetchone()[0]
        quarantined = con.execute(
            "SELECT COUNT(*) FROM quarantine WHERE ingest_id=? AND file=?",
            (ingest_id, name)).fetchone()[0]
        dropped = con.execute(
            "SELECT COUNT(*) FROM data_issues WHERE ingest_id=? AND file=? "
            "AND action='dropped_duplicate'", (ingest_id, name)).fetchone()[0]
        if clean + quarantined + dropped != len(result.files[name].rows):
            raise RowBalanceError(
                f"Row counts for {name} do not balance in recall.db. "
                "Nothing was changed.")


# ---- hand-off to part 2 ---------------------------------------------------
def to_contract_data_issues(result: IngestResult) -> list:
    """The issues as contract DataIssue records, in file and row order."""
    from .contract.data_issue import DataIssue
    return [DataIssue(file=i.file, src_row=i.src_row, issue_code=i.issue_code,
                      action=i.action, reason=i.reason, raw_row=i.raw_row,
                      vin=i.vin, campaign_id=i.campaign_id)
            for i in result.issues]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--db", type=Path, default=Path("data/recall.db"))
    parser.add_argument("--as-of", type=date.fromisoformat, default=None,
                        help="as-of date, YYYY-MM-DD (default: today)")
    args = parser.parse_args(argv)
    try:
        ingest_id = load(args.raw, args.db, args.as_of)
    except (IngestStopError, RowBalanceError) as exc:
        print(exc, file=sys.stderr)
        return 2
    con = sqlite3.connect(args.db)
    counts = json.loads(con.execute(
        "SELECT row_counts FROM ingests WHERE ingest_id=?",
        (ingest_id,)).fetchone()[0])
    issues = con.execute("SELECT COUNT(*) FROM cur_data_issues").fetchone()[0]
    con.close()
    print(f"Ingest {ingest_id} loaded into {args.db}")
    for name, c in counts.items():
        print(f"  {name}: {c['raw']} rows, {c['clean']} clean, "
              f"{c['quarantined']} quarantined, "
              f"{c['dropped_duplicate']} duplicates dropped")
    print(f"  {issues} data issues recorded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
