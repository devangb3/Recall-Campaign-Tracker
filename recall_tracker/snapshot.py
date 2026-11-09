"""Read the accepted rows of one ingest into the shared check contract.

Ingest owns CSV parsing, safe fixes, quarantine and duplicate handling.
This adapter only reads its SQLite output. It constructs the affected
list once; both existing checks receive that same list. Good notice or
repair rows outside the list remain in ``facts``, including their same-ingest
vehicle/campaign metadata for the independent unaffected-repair check.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from dataclasses import dataclass
from datetime import date

from .affected import AffectedList
from .contract import AffectedVehicle, DataIssue, Facts, NoticeSent, RepairDone
from .contract.facts import Campaign, Vehicle


class SnapshotError(ValueError):
    """No complete ingest can supply the requested check inputs."""


@dataclass(frozen=True, slots=True)
class IngestSnapshot:
    """Immutable check inputs from one complete ingest, in source order."""

    ingest_id: int
    as_of: date
    affected: AffectedList
    facts: tuple[Facts, ...]
    data_issues: tuple[DataIssue, ...]


def read_snapshot(con: sqlite3.Connection,
                  ingest_id: int | None = None) -> IngestSnapshot:
    """Read the latest complete ingest, or an explicit historical ingest.

    Every query is constrained to the chosen ID. Reading a historical
    ingest never uses current views, which may already point at a newer
    upload. This function does not create tables or change the connection's
    transaction or row factory.
    """
    if ingest_id is not None and (
            type(ingest_id) is not int or ingest_id < 1):
        raise SnapshotError("ingest_id must be a positive whole number")
    try:
        return _read_snapshot(con, ingest_id)
    except sqlite3.Error as exc:
        raise SnapshotError(
            "Cannot read the ingest database; load the five dealership "
            "CSVs successfully before running checks.") from exc


def _read_snapshot(con: sqlite3.Connection,
                   ingest_id: int | None) -> IngestSnapshot:
    if ingest_id is None:
        row = con.execute(
            "SELECT ingest_id, as_of_date FROM ingests "
            "WHERE status = 'complete' ORDER BY ingest_id DESC LIMIT 1"
        ).fetchone()
    else:
        row = con.execute(
            "SELECT ingest_id, as_of_date FROM ingests "
            "WHERE ingest_id = ? AND status = 'complete'", (ingest_id,)
        ).fetchone()
    if row is None:
        if ingest_id is None:
            raise SnapshotError("No complete ingest is available for checking")
        raise SnapshotError(f"Complete ingest {ingest_id} was not found")
    chosen_id, as_of_text = row

    affected_rows = tuple(
        AffectedVehicle(vin, campaign_id)
        for vin, campaign_id in con.execute(
            "SELECT vin, campaign_id FROM affected_vehicles "
            "WHERE ingest_id = ? ORDER BY src_row", (chosen_id,)))
    affected = AffectedList(affected_rows)
    notices = tuple(
        NoticeSent(vin, campaign_id, date.fromisoformat(notice_date))
        for vin, campaign_id, notice_date in con.execute(
            "SELECT vin, campaign_id, notice_date FROM notices_sent "
            "WHERE ingest_id = ? ORDER BY src_row", (chosen_id,)))
    repairs = tuple(
        RepairDone(vin, campaign_id, date.fromisoformat(repair_date))
        for vin, campaign_id, repair_date in con.execute(
            "SELECT vin, campaign_id, repair_date FROM repairs_done "
            "WHERE ingest_id = ? ORDER BY src_row", (chosen_id,)))

    # The quarantine's raw_json is the original whole row for quarantined
    # issues. Kept and duplicate rows carry the same shape in raw_row.
    issues = tuple(
        DataIssue(file=file, src_row=src_row, issue_code=code, action=action,
                  reason=reason, raw_row=raw_row, vin=vin,
                  campaign_id=campaign_id)
        for file, src_row, code, action, reason, raw_row, vin, campaign_id in
        con.execute(
            "SELECT i.file, i.src_row, i.issue_code, i.action, i.reason, "
            "COALESCE(q.raw_json, i.raw_row), i.vin, i.campaign_id "
            "FROM data_issues AS i LEFT JOIN quarantine AS q "
            "ON q.ingest_id = i.ingest_id AND q.file = i.file "
            "AND q.src_row = i.src_row WHERE i.ingest_id = ? "
            "ORDER BY CASE i.file WHEN 'affected_vehicles.csv' THEN 0 "
            "WHEN 'notices_sent.csv' THEN 1 ELSE 2 END, i.src_row, i.issue_id",
            (chosen_id,)))

    # Historical three-file ingests have no master rows. Their metadata
    # remains unknown; never join them against a later upload's masters.
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    vehicles = ({vin: Vehicle(vin, model, date.fromisoformat(built))
                 for vin, model, built in con.execute(
                     "SELECT vin, model, build_date FROM vehicles WHERE ingest_id=?",
                     (chosen_id,))} if "vehicles" in tables else {})
    campaigns = ({cid: Campaign(cid, model, date.fromisoformat(start), date.fromisoformat(end))
                  for cid, model, start, end in con.execute(
                      "SELECT campaign_id, model, start_date, end_date FROM campaigns WHERE ingest_id=?",
                      (chosen_id,))} if "campaigns" in tables else {})
    facts = tuple(replace(f, vehicle=vehicles.get(f.vin), campaign=campaigns.get(f.campaign_id))
                  for f in _facts(affected_rows, notices, repairs))
    return IngestSnapshot(
        ingest_id=chosen_id, as_of=date.fromisoformat(as_of_text),
        affected=affected, facts=facts,
        data_issues=issues)


def _facts(affected: tuple[AffectedVehicle, ...],
           notices: tuple[NoticeSent, ...],
           repairs: tuple[RepairDone, ...]) -> tuple[Facts, ...]:
    # Dict insertion order preserves affected-file order first, then any
    # extra pairs in notice-file order, then repair-file order.
    groups: dict[tuple[str, str], dict[str, list]] = {}
    for name, rows in (("affected", affected), ("notices", notices),
                       ("repairs", repairs)):
        for record in rows:
            key = (record.vin, record.campaign_id)
            if key not in groups:
                groups[key] = {"affected": [], "notices": [], "repairs": []}
            groups[key][name].append(record)
    return tuple(
        Facts(vin, campaign_id, affected=tuple(rows["affected"]),
              notices=tuple(rows["notices"]), repairs=tuple(rows["repairs"]))
        for (vin, campaign_id), rows in groups.items())
