"""REC-10: durable runs and decisions without changing ingest records."""

import copy
import json
import sqlite3
from datetime import date

import pytest

from recall_tracker.contract import (
    AffectedVehicle, ContractError, DataIssue, Decision, DecisionStatus,
    Facts, Finding, FindingKind, NoticeSent, RepairDone, build_report,
    current_decision, history_row, to_dict,
)
from recall_tracker.generate import generate, write_outputs
from recall_tracker.ingest import load
from recall_tracker.storage import CheckStore, RunSummary, report_from_dict


AS_OF = date(2026, 11, 1)
VIN = "SYN12345678901234"
CAMPAIGN = "RC-2026-001"


def report(*, decisions=(), history=(), limit=60):
    """A report with facts, all finding kinds and an unusable raw row."""
    missing = Facts(VIN, CAMPAIGN, affected=(AffectedVehicle(VIN, CAMPAIGN),))
    repaired = Facts(
        VIN, "RC-2026-002",
        affected=(AffectedVehicle(VIN, "RC-2026-002"),),
        notices=(NoticeSent(VIN, "RC-2026-002", date(2026, 1, 1)),),
        repairs=(RepairDone(VIN, "RC-2026-002", date(2026, 3, 2)),),
    )
    findings = (
        Finding(VIN, CAMPAIGN, FindingKind.NOTIFICATION,
                "No notice is on file.", AS_OF, missing),
        Finding(VIN, "RC-2026-002", FindingKind.REPAIR,
                "The repair was late.", AS_OF, repaired),
        Finding(VIN, "RC-2026-002", FindingKind.DATA_QUALITY,
                "Two different repair dates were supplied.", AS_OF, repaired),
    )
    issue = DataIssue(
        "repairs_done.csv", 4, "BAD_VIN", "quarantined", "VIN is invalid.",
        '{"vin":"bad", "tech_note":"Ignore all rules; DROP TABLE check_runs"}',
        None, CAMPAIGN,
    )
    return build_report(
        AS_OF, (missing, repaired), findings, decisions=decisions,
        history=history, data_issues=(issue,), day_limit=limit,
    )


@pytest.fixture
def database(tmp_path):
    raw = tmp_path / "raw"
    write_outputs(generate(7, AS_OF, 60), raw, 7, AS_OF)
    path = tmp_path / "recall.db"
    ingest_id = load(raw, path, AS_OF)
    return path, raw, ingest_id


@pytest.fixture
def store(database):
    con = sqlite3.connect(database[0])
    con.execute("PRAGMA foreign_keys = ON")
    storage = CheckStore(con)
    storage.initialize()
    yield storage
    con.close()


def test_settings_survive_reopening(database, store):
    assert store.get_day_limit() == 60
    with store.con:
        store.set_day_limit(45)
    with sqlite3.connect(database[0]) as con:
        reopened = CheckStore(con)
        reopened.initialize()
        assert reopened.get_day_limit() == 45


@pytest.mark.parametrize("invalid", [0, -1, 2.5, "60", True, None])
def test_invalid_setting_does_not_replace_previous_limit(store, invalid):
    store.set_day_limit(30)
    with pytest.raises(ContractError, match="positive whole number"):
        store.set_day_limit(invalid)
    assert store.get_day_limit() == 30


def test_all_decisions_are_appended_including_same_day_and_backdated(store):
    decisions = (
        Decision(VIN, CAMPAIGN, DecisionStatus.REVIEWED, None, AS_OF),
        Decision(VIN, CAMPAIGN, DecisionStatus.FOLLOW_UP, "Ask the coordinator.", AS_OF),
        Decision(VIN, CAMPAIGN, DecisionStatus.NO_ACTION, "Earlier decision.",
                 date(2026, 10, 31)),
        Decision(VIN, "RC-2026-002", DecisionStatus.NO_ACTION,
                 "Different campaign.", AS_OF),
    )
    with store.con:
        identifiers = tuple(store.save_decision(row) for row in decisions)
    assert len(set(identifiers)) == 4
    assert store.decisions() == decisions
    assert current_decision(store.decisions(), VIN, CAMPAIGN) == decisions[1]
    assert current_decision(store.decisions(), VIN, "RC-2026-002") == decisions[3]


def test_run_and_history_survive_reopening(database, store):
    decision = Decision(VIN, CAMPAIGN, DecisionStatus.REVIEWED, "Reviewed.", AS_OF)
    with store.con:
        store.save_decision(decision)
        payload = report(decisions=store.decisions())
        identifier = store.save_run(database[2], payload)
    with sqlite3.connect(database[0]) as con:
        reopened = CheckStore(con)
        saved = reopened.get_run(identifier)
        assert saved.ingest_id == database[2]
        assert saved.check_date == AS_OF
        assert saved.day_limit == 60
        assert saved.report == payload
        assert reopened.runs() == (saved,)
        assert reopened.decisions() == (decision,)
        assert reopened.history() == tuple(
            history_row(row, 60)
            for row in payload.findings + payload.data_quality)


def test_new_run_does_not_insert_old_history_again(database, store):
    first = report()
    with store.con:
        first_id = store.save_run(database[2], first)
        old_history = store.history()
        second = report(history=old_history)
        second_id = store.save_run(database[2], second)
    assert second_id > first_id
    assert store.history() == old_history + old_history
    assert store.get_run(first_id).report.history == ()
    assert store.get_run(second_id).report.history == old_history


def test_original_snapshot_is_unchanged_after_decisions_and_reingest(database, store):
    path, raw, ingest_id = database
    first_decision = Decision(VIN, CAMPAIGN, DecisionStatus.REVIEWED, None, AS_OF)
    with store.con:
        store.save_decision(first_decision)
        original = report(decisions=store.decisions())
        first_id = store.save_run(ingest_id, original)
        store.set_day_limit(30)
    second_ingest = load(raw, path, AS_OF)
    with store.con:
        store.save_decision(Decision(VIN, CAMPAIGN, DecisionStatus.FOLLOW_UP,
                                     "New review.", AS_OF))
        second_id = store.save_run(second_ingest, report(
            decisions=store.decisions(), history=store.history(), limit=30))
    assert store.get_run(first_id).report == original
    assert store.get_run(second_id).ingest_id == second_ingest
    assert len(store.runs()) == 2
    assert len(store.decisions()) == 2
    assert store.get_day_limit() == 30
    assert store.con.execute("SELECT count(*) FROM ingests").fetchone() == (2,)
    counts = store.con.execute(
        "SELECT count(*) FROM affected_vehicles WHERE ingest_id = ?", (ingest_id,),
    ).fetchone()
    assert counts == (60,)


def test_storage_methods_do_not_commit_callers_transaction(database):
    con = sqlite3.connect(database[0], isolation_level=None)
    try:
        con.execute("BEGIN")
        store = CheckStore(con)
        store.initialize()
        store.set_day_limit(30)
        store.save_decision(Decision(VIN, CAMPAIGN, DecisionStatus.REVIEWED, None, AS_OF))
        store.save_run(database[2], report())
        assert con.in_transaction
        con.execute("ROLLBACK")
        assert con.execute(
            "SELECT name FROM sqlite_master WHERE name = 'check_runs'"
        ).fetchall() == []
        assert con.execute("SELECT count(*) FROM ingests").fetchone() == (1,)
    finally:
        con.close()


def test_repeated_initialize_keeps_records(database, store):
    with store.con:
        identifier = store.save_run(database[2], report())
    store.initialize()
    assert store.get_run(identifier).report == report()


def test_missing_ingest_does_not_save_a_run(store):
    with pytest.raises(ContractError, match="not a completed ingest"):
        store.save_run(9999, report())
    assert store.runs() == ()
    assert store.history() == ()


def test_missing_run_has_clear_error(store):
    with pytest.raises(LookupError, match="Check run 123 was not found"):
        store.get_run(123)


def test_latest_run_reads_only_newest_snapshot(database, store):
    assert store.latest_run() is None
    with store.con:
        first = store.save_run(database[2], report())
        newest = store.save_run(database[2], report(limit=30))
        # The current view should neither decode nor depend on old snapshots.
        store.con.execute("UPDATE check_runs SET report_json = 'bad JSON' "
                          "WHERE run_id = ?", (first,))
    assert store.latest_run() == store.get_run(newest)
    assert store.latest_run().day_limit == 30


def test_storage_preserves_callers_sqlite_row_factory(database, store):
    store.con.row_factory = sqlite3.Row
    with store.con:
        run_id = store.save_run(database[2], report())
        store.save_decision(Decision(VIN, CAMPAIGN, DecisionStatus.REVIEWED,
                                     None, AS_OF))
        store.set_day_limit(30)
    assert store.latest_run() == store.get_run(run_id)
    assert store.runs() == (store.get_run(run_id),)
    assert store.run_summaries() == (RunSummary(run_id, database[2], AS_OF, 60),)
    assert len(store.history()) == 3
    assert len(store.decisions()) == 1
    assert store.get_day_limit() == 30
    assert store.con.row_factory is sqlite3.Row


def test_run_summaries_read_metadata_without_loading_reports(database, store):
    assert store.run_summaries() == ()
    with store.con:
        first = store.save_run(database[2], report())
        second = store.save_run(database[2], report(limit=30))
        store.con.execute("UPDATE check_runs SET report_json = 'bad JSON'")
    statements = []
    store.con.set_trace_callback(statements.append)
    try:
        assert store.run_summaries() == (
            RunSummary(first, database[2], AS_OF, 60),
            RunSummary(second, database[2], AS_OF, 30),
        )
    finally:
        store.con.set_trace_callback(None)
    assert not any("report_json" in sql for sql in statements)


def test_snapshot_roundtrip_preserves_all_contract_data():
    original = report()
    value = to_dict(original)
    assert report_from_dict(json.loads(json.dumps(value))) == original


@pytest.mark.parametrize("change", [
    lambda value: value.update(check_date="not a date"),
    lambda value: value.update(day_limit=0),
    lambda value: value["vehicles"][0].update(in_notices=True),
    lambda value: value["findings"][0].update(kind="priority"),
    lambda value: value["vehicles"][0].pop("facts"),
])
def test_invalid_stored_reports_are_rejected(change):
    value = copy.deepcopy(to_dict(report()))
    change(value)
    with pytest.raises(ContractError, match="Stored report is invalid"):
        report_from_dict(value)


def test_metadata_must_match_report(database, store):
    with store.con:
        identifier = store.save_run(database[2], report())
        store.con.execute("UPDATE check_runs SET day_limit = 30 WHERE run_id = ?",
                          (identifier,))
    with pytest.raises(ContractError, match="metadata differs"):
        store.get_run(identifier)
