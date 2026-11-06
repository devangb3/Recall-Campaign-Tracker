"""Append-only check results and coordinator decisions in SQLite.

The ingest tables belong to part 1. These tables keep the checks, report
snapshots and coordinator settings separately. A caller supplies the
connection and owns its transaction; no method commits or rolls it back.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from .contract import (
    DEFAULT_DAY_LIMIT, AffectedVehicle, CheckHistoryRow, ContractError,
    DataIssue, Decision, DecisionStatus, Facts, Finding, FindingKind,
    NoticeSent, RepairDone, ReportPayload, VehicleView, history_row, to_dict,
)
from .contract.validate import require_day_limit


_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS tracker_settings (
        setting_key TEXT PRIMARY KEY CHECK (setting_key = 'day_limit'),
        setting_value INTEGER NOT NULL CHECK (setting_value > 0)
    )""",
    """CREATE TABLE IF NOT EXISTS check_runs (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        ingest_id INTEGER NOT NULL REFERENCES ingests(ingest_id),
        check_date TEXT NOT NULL,
        day_limit INTEGER NOT NULL CHECK (day_limit > 0),
        saved_at TEXT NOT NULL,
        report_json TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS check_history (
        history_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL REFERENCES check_runs(run_id),
        vin TEXT NOT NULL,
        campaign_id TEXT NOT NULL,
        check_date TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (
            kind IN ('notification', 'repair', 'data quality')),
        reason TEXT NOT NULL,
        day_limit INTEGER NOT NULL CHECK (day_limit > 0)
    )""",
    """CREATE TABLE IF NOT EXISTS coordinator_decisions (
        decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
        vin TEXT NOT NULL,
        campaign_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK (
            status IN ('reviewed', 'follow up', 'no action')),
        note TEXT,
        decided_on TEXT NOT NULL,
        saved_at TEXT NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS check_history_pair
        ON check_history(vin, campaign_id, history_id)""",
    """CREATE INDEX IF NOT EXISTS check_runs_ingest
        ON check_runs(ingest_id, run_id)""",
    """CREATE INDEX IF NOT EXISTS coordinator_decisions_pair
        ON coordinator_decisions(vin, campaign_id, decision_id)""",
)


@dataclass(frozen=True, slots=True)
class RunSummary:
    """Small run metadata for listings, without loading report snapshots."""

    run_id: int
    ingest_id: int
    check_date: date
    day_limit: int


@dataclass(frozen=True, slots=True)
class SavedRun:
    """An original report snapshot and the ingest it was checked against."""

    run_id: int
    ingest_id: int
    check_date: date
    day_limit: int
    report: ReportPayload


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _positive_id(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ContractError(f"{name} must be a positive whole number")
    return value


def _date(value: Any) -> date:
    if type(value) is not str:
        raise ContractError("stored date must be an ISO YYYY-MM-DD string")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ContractError("stored date must be an ISO YYYY-MM-DD string")
    return parsed


def _facts(value: Mapping[str, Any], vin: str, campaign: str) -> Facts:
    return Facts(
        vin, campaign,
        affected=tuple(AffectedVehicle(**row) for row in value["affected"]),
        notices=tuple(NoticeSent(
            row["vin"], row["campaign_id"], _date(row["notice_date"]))
            for row in value["notices"]),
        repairs=tuple(RepairDone(
            row["vin"], row["campaign_id"], _date(row["repair_date"]))
            for row in value["repairs"]),
    )


def _finding(value: Mapping[str, Any]) -> Finding:
    return Finding(
        value["vin"], value["campaign_id"], FindingKind(value["kind"]),
        value["reason"], _date(value["check_date"]),
        _facts(value["facts"], value["vin"], value["campaign_id"]),
    )


def _decision(value: Mapping[str, Any]) -> Decision:
    return Decision(
        value["vin"], value["campaign_id"], DecisionStatus(value["status"]),
        value["note"], _date(value["decided_on"]),
    )


def _history(value: Mapping[str, Any]) -> CheckHistoryRow:
    return CheckHistoryRow(
        value["vin"], value["campaign_id"], _date(value["check_date"]),
        FindingKind(value["kind"]), value["reason"], value["day_limit"],
    )


def report_from_dict(value: Mapping[str, Any]) -> ReportPayload:
    """Restore a JSON report through the same validators used by checks.

    Snapshot text is data, including notes and raw rows. It is never
    evaluated or interpreted as an instruction.
    """
    try:
        vehicles = tuple(VehicleView(
            vin=row["vin"], campaign_id=row["campaign_id"],
            in_notices=row["in_notices"],
            notice_date_used=(None if row["notice_date_used"] is None
                              else _date(row["notice_date_used"])),
            repair_date_used=(None if row["repair_date_used"] is None
                              else _date(row["repair_date_used"])),
            inclusive_days=row["inclusive_days"], day_limit=row["day_limit"],
            on_time=row["on_time"],
            decision=(None if row["decision"] is None
                      else _decision(row["decision"])),
            data_quality_reasons=tuple(row["data_quality_reasons"]),
            facts=_facts(row["facts"], row["vin"], row["campaign_id"]),
        ) for row in value["vehicles"])
        return ReportPayload(
            check_date=_date(value["check_date"]),
            day_limit=value["day_limit"],
            findings=tuple(_finding(row) for row in value["findings"]),
            data_quality=tuple(_finding(row) for row in value["data_quality"]),
            decisions=tuple(_decision(row) for row in value["decisions"]),
            history=tuple(_history(row) for row in value["history"]),
            vehicles=vehicles,
            data_issues=tuple(DataIssue(**row) for row in value["data_issues"]),
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ContractError(f"Stored report is invalid: {exc}") from exc


class CheckStore:
    """Storage on a caller-owned connection; call initialize() once.

    Use ``with connection:`` or an explicit transaction around mutations.
    ``save_run`` records the supplied report exactly. Updating the chosen
    setting is explicit via ``set_day_limit`` so reading historical runs
    never changes the current setting.
    """

    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def initialize(self) -> None:
        # executescript would implicitly commit the caller's transaction.
        for statement in _SCHEMA:
            self.con.execute(statement)

    def get_day_limit(self) -> int:
        row = self.con.execute(
            "SELECT setting_value FROM tracker_settings "
            "WHERE setting_key = 'day_limit'").fetchone()
        return DEFAULT_DAY_LIMIT if row is None else require_day_limit(row[0])

    def set_day_limit(self, day_limit: int) -> None:
        day_limit = require_day_limit(day_limit)
        self.con.execute(
            "INSERT INTO tracker_settings(setting_key, setting_value) "
            "VALUES ('day_limit', ?) ON CONFLICT(setting_key) "
            "DO UPDATE SET setting_value = excluded.setting_value",
            (day_limit,),
        )

    def save_decision(self, decision: Decision) -> int:
        if type(decision) is not Decision:
            raise ContractError("decision must be a Decision")
        cursor = self.con.execute(
            "INSERT INTO coordinator_decisions "
            "(vin, campaign_id, status, note, decided_on, saved_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (decision.vin, decision.campaign_id, decision.status.value,
             decision.note, decision.decided_on.isoformat(), _now()),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def decisions(self) -> tuple[Decision, ...]:
        rows = self.con.execute(
            "SELECT vin, campaign_id, status, note, decided_on "
            "FROM coordinator_decisions ORDER BY decision_id").fetchall()
        return tuple(Decision(vin, campaign, DecisionStatus(status), note,
                              _date(decided_on))
                     for vin, campaign, status, note, decided_on in rows)

    def history(self) -> tuple[CheckHistoryRow, ...]:
        rows = self.con.execute(
            "SELECT vin, campaign_id, check_date, kind, reason, day_limit "
            "FROM check_history ORDER BY history_id").fetchall()
        return tuple(CheckHistoryRow(vin, campaign, _date(checked_on),
                                     FindingKind(kind), reason, limit)
                     for vin, campaign, checked_on, kind, reason, limit in rows)

    def save_run(self, ingest_id: int, report: ReportPayload) -> int:
        ingest_id = _positive_id(ingest_id, "ingest_id")
        if type(report) is not ReportPayload:
            raise ContractError("report must be a ReportPayload")
        ingest = self.con.execute(
            "SELECT 1 FROM ingests WHERE ingest_id = ? AND status = 'complete'",
            (ingest_id,),
        ).fetchone()
        if ingest is None:
            raise ContractError(f"ingest {ingest_id} is not a completed ingest")
        snapshot = json.dumps(to_dict(report), ensure_ascii=False,
                              separators=(",", ":"))
        cursor = self.con.execute(
            "INSERT INTO check_runs "
            "(ingest_id, check_date, day_limit, saved_at, report_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (ingest_id, report.check_date.isoformat(), report.day_limit,
             _now(), snapshot),
        )
        assert cursor.lastrowid is not None
        run_id = cursor.lastrowid
        # report.history can contain earlier runs. Only this run's findings
        # are new rows; repeated checks are kept under their own run_id.
        for finding in report.findings + report.data_quality:
            row = history_row(finding, report.day_limit)
            self.con.execute(
                "INSERT INTO check_history "
                "(run_id, vin, campaign_id, check_date, kind, reason, day_limit) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, row.vin, row.campaign_id, row.check_date.isoformat(),
                 row.kind.value, row.reason, row.day_limit),
            )
        return run_id

    def _saved_run(self, row: tuple) -> SavedRun:
        run_id, ingest_id, checked_on, limit, snapshot = row
        try:
            report = report_from_dict(json.loads(snapshot))
        except (TypeError, ValueError) as exc:
            raise ContractError(f"Stored run {run_id} is invalid: {exc}") from exc
        if (report.check_date.isoformat(), report.day_limit) != (checked_on, limit):
            raise ContractError(f"Stored run {run_id} metadata differs from its report")
        return SavedRun(run_id, ingest_id, report.check_date, report.day_limit,
                        report)

    def get_run(self, run_id: int) -> SavedRun:
        run_id = _positive_id(run_id, "run_id")
        row = self.con.execute(
            "SELECT run_id, ingest_id, check_date, day_limit, report_json "
            "FROM check_runs WHERE run_id = ?", (run_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"Check run {run_id} was not found")
        return self._saved_run(row)

    def latest_run(self) -> SavedRun | None:
        """Read just the newest snapshot, without decoding earlier runs."""
        row = self.con.execute(
            "SELECT run_id, ingest_id, check_date, day_limit, report_json "
            "FROM check_runs ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
        return None if row is None else self._saved_run(row)

    def run_summaries(self) -> tuple[RunSummary, ...]:
        """List run metadata oldest first without decoding report snapshots."""
        rows = self.con.execute(
            "SELECT run_id, ingest_id, check_date, day_limit "
            "FROM check_runs ORDER BY run_id"
        ).fetchall()
        return tuple(RunSummary(run_id, ingest_id, _date(checked_on),
                                require_day_limit(limit))
                     for run_id, ingest_id, checked_on, limit in rows)

    def runs(self) -> tuple[SavedRun, ...]:
        rows = self.con.execute(
            "SELECT run_id, ingest_id, check_date, day_limit, report_json "
            "FROM check_runs ORDER BY run_id").fetchall()
        return tuple(self._saved_run(row) for row in rows)
