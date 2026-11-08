"""The dealership tool: ingest, check, save, and return the report contract.

All writes for a run share one SQLite transaction. The CSVs are Julian's
inputs; his ingest is the only parser and normalizer used by the tool.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from pathlib import Path

from . import ingest
from .checks import check_notifications, check_repairs
from .contract import (
    DEFAULT_DAY_LIMIT, Decision, Finding, FindingKind, build_report, history_row,
)
from .contract.validate import require_date, require_day_limit
from .snapshot import IngestSnapshot, read_snapshot
from .storage import CheckStore, RunSummary, SavedRun


class PipelineError(ValueError):
    """A requested tool action has no loaded data or saved run to use."""


@contextmanager
def _transaction(db_path: Path | str, *, create: bool = False):
    path = Path(db_path)
    if not create and not path.is_file():
        raise PipelineError("No recall database exists; load the three CSVs first.")
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, isolation_level=None, timeout=30)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("BEGIN IMMEDIATE")
        yield con
        con.execute("COMMIT")
    except BaseException:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


@contextmanager
def _read(db_path: Path | str):
    path = Path(db_path)
    if not path.is_file():
        raise PipelineError("No recall database exists; load the three CSVs first.")
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        # One snapshot for the run, history and decisions even while another
        # request saves a new run. Reading never creates tables or settings.
        con.execute("BEGIN")
        yield con
    finally:
        con.close()


def _has_checks(con: sqlite3.Connection) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='check_runs'"
    ).fetchone() is not None


def _quality_findings(snapshot: IngestSnapshot, check_date: date
                      ) -> tuple[Finding, ...]:
    """Kept bad-data cases have good facts; quarantined rows stay DataIssues."""
    by_pair = {(facts.vin, facts.campaign_id): facts for facts in snapshot.facts}
    findings: list[Finding] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in snapshot.data_issues:
        facts = by_pair.get((issue.vin, issue.campaign_id))
        if issue.action != "kept" or facts is None:
            continue
        key = (facts.vin, facts.campaign_id, issue.reason)
        if key in seen:
            continue
        seen.add(key)
        findings.append(Finding(
            facts.vin, facts.campaign_id, FindingKind.DATA_QUALITY,
            issue.reason, check_date, facts,
        ))
    return tuple(findings)


def _save_check(con: sqlite3.Connection, snapshot: IngestSnapshot,
                check_date: date, day_limit: int | None) -> SavedRun:
    check_date = require_date(check_date, "check date")
    if check_date < snapshot.as_of:
        raise PipelineError(
            f"Check date cannot precede the loaded data's as-of date "
            f"{snapshot.as_of.isoformat()}; load the CSVs for that date first.")
    store = CheckStore(con)
    store.initialize()
    if day_limit is not None:
        store.set_day_limit(day_limit)
    limit = store.get_day_limit()
    notifications = check_notifications(
        snapshot.affected, snapshot.facts, check_date,
        data_issues=snapshot.data_issues)
    repairs = check_repairs(
        snapshot.affected, snapshot.facts, check_date, day_limit=limit)
    # Both findings have equal standing. Keep source vehicle order rather
    # than grouping or sorting by finding kind.
    by_pair = {(finding.vin, finding.campaign_id): finding
               for finding in notifications + repairs}
    business = tuple(by_pair[(pair.vin, pair.campaign_id)]
                     for pair in snapshot.affected
                     if (pair.vin, pair.campaign_id) in by_pair)
    findings = business + _quality_findings(snapshot, check_date)
    report = build_report(
        check_date, snapshot.facts, findings,
        decisions=store.decisions(),
        history=store.history() + tuple(history_row(f, limit) for f in findings),
        data_issues=snapshot.data_issues, day_limit=limit)
    run_id = store.save_run(snapshot.ingest_id, report)
    return store.get_run(run_id)


def run_check(raw_dir: Path | str, db_path: Path | str, *,
              check_date: date | None = None,
              day_limit: int | None = None) -> SavedRun:
    """Load all three CSVs, check their accepted rows and save one whole run.

    Unusable input stops before a database is opened. An unexpected error
    rolls back the ingest, settings and run together; no partial result is
    published. A saved day limit is reused unless explicitly changed.
    """
    check_date = require_date(
        date.today() if check_date is None else check_date, "check date")
    if day_limit is not None:
        require_day_limit(day_limit)
    prepared = ingest.prepare(Path(raw_dir), check_date)
    with _transaction(db_path, create=True) as con:
        ingest_id = ingest.load_prepared(con, prepared)
        return _save_check(con, read_snapshot(con, ingest_id),
                           check_date, day_limit)


def recheck(db_path: Path | str, *, check_date: date | None = None,
            day_limit: int | None = None) -> SavedRun:
    """Recalculate loaded data, including a changed limit, without reading CSVs.

    Keep the displayed run's check date when recalculating its data; for
    an ingest that has not been checked yet, use its as-of date. Every
    recalculation is a new run; earlier results remain.
    """
    if check_date is not None:
        require_date(check_date, "check date")
    if day_limit is not None:
        require_day_limit(day_limit)
    with _transaction(db_path) as con:
        snapshot = read_snapshot(con)
        latest = CheckStore(con).latest_run() if _has_checks(con) else None
        default_date = (latest.check_date if latest is not None
                        and latest.ingest_id == snapshot.ingest_id
                        else snapshot.as_of)
        return _save_check(con, snapshot,
                           default_date if check_date is None else check_date,
                           day_limit)


def saved_runs(db_path: Path | str) -> tuple[SavedRun, ...]:
    """Every original saved run, oldest first."""
    with _read(db_path) as con:
        return CheckStore(con).runs() if _has_checks(con) else ()


def run_summaries(db_path: Path | str) -> tuple[RunSummary, ...]:
    """List saved-run metadata without decoding historical report snapshots."""
    with _read(db_path) as con:
        return CheckStore(con).run_summaries() if _has_checks(con) else ()


def saved_run(db_path: Path | str, run_id: int) -> SavedRun:
    """Read an original run, without applying later coordinator decisions."""
    with _read(db_path) as con:
        if not _has_checks(con):
            raise PipelineError("No checks have been saved; run a check first.")
        return CheckStore(con).get_run(run_id)


def ingest_loaded_at(db_path: Path | str, ingest_id: int) -> str:
    """When the CSV files behind an ingest finished loading (UTC, ISO text)."""
    with _read(db_path) as con:
        row = con.execute("SELECT finished_at FROM ingests WHERE ingest_id = ?",
                          (ingest_id,)).fetchone()
    if row is None:
        raise PipelineError(f"Ingest {ingest_id} was not found.")
    return row[0]


def input_check(db_path: Path | str, raw_dir: Path | str, ingest_id: int) -> dict:
    """Do the CSV files in ``raw_dir`` still match the data behind a run?

    Reads the files and writes nothing. ``ok``: same bytes as when loaded.
    ``changed``: readable, but edited or replaced since. ``unusable``: a file
    is missing or unreadable now, so a new check would stop. A reload or a
    day-limit change reuses the loaded data and never looks at the files, so
    this is how the screen and the PDF learn that the data may be old.
    """
    try:
        files = ingest.read_all(Path(raw_dir))
    except ingest.IngestStopError as exc:
        return {"state": "unusable", "message": str(exc)}
    with _read(db_path) as con:
        row = con.execute("SELECT files FROM ingests WHERE ingest_id = ?",
                          (ingest_id,)).fetchone()
    loaded = json.loads(row[0]) if row else {}
    differ = [name for name, raw in files.items()
              if loaded.get(name, {}).get("sha256") != raw.sha256]
    if differ:
        return {"state": "changed", "message":
                f"{', '.join(differ)} changed after the data was loaded."}
    return {"state": "ok", "message": None}


def current_report(db_path: Path | str) -> SavedRun:
    """Latest saved check results with current decisions and complete history."""
    with _read(db_path) as con:
        if not _has_checks(con):
            raise PipelineError("No checks have been saved; run a check first.")
        store = CheckStore(con)
        latest = store.latest_run()
        if latest is None:
            raise PipelineError("No checks have been saved; run a check first.")
        original = latest.report
        report = build_report(
            original.check_date, tuple(view.facts for view in original.vehicles),
            original.findings + original.data_quality,
            decisions=store.decisions(), history=store.history(),
            data_issues=original.data_issues, day_limit=original.day_limit)
        return replace(latest, report=report)


def record_decision(db_path: Path | str, decision: Decision) -> int:
    """Append a coordinator decision for a pair present in the loaded history."""
    if type(decision) is not Decision:
        raise PipelineError("A decision must use the shared Decision record.")
    with _transaction(db_path) as con:
        # This also gives a clear error if the database has no complete ingest.
        read_snapshot(con)
        known = any(con.execute(
            f"SELECT 1 FROM {table} WHERE vin=? AND campaign_id=? LIMIT 1",
            (decision.vin, decision.campaign_id)).fetchone()
            for table in ("affected_vehicles", "notices_sent", "repairs_done"))
        if not known:
            raise PipelineError("This vehicle and campaign are not in the loaded records.")
        store = CheckStore(con)
        store.initialize()
        return store.save_decision(decision)


def settings(db_path: Path | str) -> dict[str, int]:
    """The coordinator's persisted preferences; read-only and safe before a run."""
    if not Path(db_path).is_file():
        return {"day_limit": DEFAULT_DAY_LIMIT}
    with _read(db_path) as con:
        return {"day_limit": CheckStore(con).get_day_limit()
                if _has_checks(con) else DEFAULT_DAY_LIMIT}
