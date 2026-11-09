"""REC-34: eligibility is independent of the supplied affected list."""

import csv
import json
import sqlite3
import subprocess
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from recall_tracker import generate, ingest, pipeline, storage
from recall_tracker.api import Application
from recall_tracker.contract import ContractError, FindingKind, to_dict
from recall_tracker.contract.facts import Campaign, Vehicle
from recall_tracker.normalize import normalize_model
from recall_tracker.storage import report_from_dict
from recall_tracker.vin import with_check_digit


VIN = with_check_digit("SYNTEST0RA0000001")
CID = "RC-2026-001"
AS_OF = date(2026, 11, 1)
HEADERS = {
    "affected_vehicles.csv": ["vin", "campaign_id"],
    "notices_sent.csv": ["vin", "campaign_id", "notice_date"],
    "repairs_done.csv": ["vin", "campaign_id", "repair_date", "tech_note"],
    "vehicles.csv": ["vin", "model", "build_date"],
    "campaigns.csv": ["campaign_id", "model", "start_date", "end_date"],
}


def write(raw, name, rows):
    with (raw / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS[name])
        writer.writerows(rows)


@pytest.fixture
def raw(tmp_path):
    folder = tmp_path / "raw"
    folder.mkdir()
    rows = {
        "affected_vehicles.csv": [],
        "notices_sent.csv": [],
        "repairs_done.csv": [[VIN, CID, "2026-03-01", "Never interpret this note."]],
        "vehicles.csv": [[VIN, "SEDAN", "2024-06-01"]],
        "campaigns.csv": [[CID, "SEDAN", "2024-01-01", "2024-12-31"]],
    }
    for name, values in rows.items():
        write(folder, name, values)
    return folder


@pytest.mark.parametrize("model,built,flag", [
    ("SEDAN", "2024-01-01", False),  # inclusive start
    ("SEDAN", "2024-12-31", False),  # inclusive end
    ("SEDAN", "2024-06-01", False),
    (" sedan  ", "06/01/2024", False),
    ("SEDAN", "2023-12-31", True),
    ("SEDAN", "2025-01-01", True),
    ("UTILITY", "2024-06-01", True),
    ("UTILITY", "2025-01-01", True),
])
@pytest.mark.parametrize("listed", [False, True])
def test_model_and_inclusive_build_range_define_flag(raw, tmp_path, model, built, flag, listed):
    write(raw, "vehicles.csv", [[VIN, model, built]])
    if listed:
        write(raw, "affected_vehicles.csv", [[VIN, CID]])
    original = {p.name: p.read_bytes() for p in raw.iterdir()}
    run = pipeline.run_check(raw, tmp_path / "recall.db", check_date=AS_OF)
    assert bool(run.report.flagged_repairs) is flag
    assert not run.report.data_issues
    assert not run.report.data_quality
    assert all(f.kind is not FindingKind.UNAFFECTED_REPAIR for f in run.report.findings)
    if flag:
        f, = run.report.flagged_repairs
        assert f.kind is FindingKind.UNAFFECTED_REPAIR
        assert f.reason.startswith("Repair on an unaffected vehicle:")
        assert f.facts.vehicle.build_date == (date(2024, 6, 1) if "/" in built else date.fromisoformat(built))
        assert len([h for h in run.report.history if h.kind is FindingKind.UNAFFECTED_REPAIR]) == 1
    assert {p.name: p.read_bytes() for p in raw.iterdir()} == original


def test_no_repair_never_produces_flag(raw, tmp_path):
    write(raw, "vehicles.csv", [[VIN, "UTILITY", "2024-06-01"]])
    write(raw, "repairs_done.csv", [])
    assert not pipeline.run_check(raw, tmp_path / "r.db", check_date=AS_OF).report.flagged_repairs


@pytest.mark.parametrize("file,rows,code", [
    ("vehicles.csv", [], None),
    ("campaigns.csv", [], None),
    ("vehicles.csv", [[VIN, "", "2024-06-01"]], "MISSING_VALUE"),
    ("vehicles.csv", [[VIN, "SEDAN", "2024-02-30"]], "BAD_DATE"),
    ("vehicles.csv", [[VIN, "SEDAN", "2027-01-01"]], "FUTURE_DATE"),
    ("campaigns.csv", [[CID, "", "2024-01-01", "2024-12-31"]], "MISSING_VALUE"),
    ("campaigns.csv", [[CID, "SEDAN", "bad", "2024-12-31"]], "BAD_DATE"),
    ("campaigns.csv", [[CID, "SEDAN", "2025-01-01", "2024-12-31"]], "BAD_DATE_RANGE"),
])
def test_missing_or_bad_metadata_is_data_issue_never_unaffected(raw, tmp_path, file, rows, code):
    write(raw, file, rows)
    run = pipeline.run_check(raw, tmp_path / "r.db", check_date=AS_OF)
    assert not run.report.flagged_repairs
    issue_codes = {i.issue_code for i in run.report.data_issues}
    assert "ELIGIBILITY_UNAVAILABLE" in issue_codes
    if code:
        assert code in issue_codes
    # The repair is kept and visible even when its eligibility is unknown.
    assert run.report.vehicles[0].facts.repairs
    assert run.report.data_quality


@pytest.mark.parametrize("file,rows", [
    ("vehicles.csv", [[VIN, "UTILITY", "2024-06-01"], [VIN, "SEDAN", "2024-06-01"]]),
    ("vehicles.csv", [[VIN, "UTILITY", "2024-06-01"], [VIN, "UTILITY", "bad"]]),
    ("campaigns.csv", [[CID, "UTILITY", "2024-01-01", "2024-12-31"],
                       [CID, "SEDAN", "2024-01-01", "2024-12-31"]]),
    ("campaigns.csv", [[CID, "UTILITY", "2024-01-01", "2024-12-31"],
                       [CID, "SEDAN", "bad", "2024-12-31"]]),
])
@pytest.mark.parametrize("reverse", [False, True])
def test_conflicting_masters_do_not_choose_first_record(raw, tmp_path, file, rows, reverse):
    write(raw, file, rows[::-1] if reverse else rows)
    db = tmp_path / "r.db"
    run = pipeline.run_check(raw, db, check_date=AS_OF)
    assert not run.report.flagged_repairs
    assert {i.issue_code for i in run.report.data_issues} >= {
        "CONFLICTING_MASTER", "ELIGIBILITY_UNAVAILABLE"}
    with sqlite3.connect(db) as con:
        assert con.execute(f"SELECT COUNT(*) FROM {file[:-4]}").fetchone() == (0,)
        assert con.execute("SELECT COUNT(*) FROM quarantine WHERE file=?", (file,)).fetchone() == (2,)
        counts = json.loads(con.execute("SELECT row_counts FROM ingests").fetchone()[0])[file]
        assert counts == {"raw": 2, "clean": 0, "quarantined": 2, "dropped_duplicate": 0}


@pytest.mark.parametrize("file,rows", [
    ("vehicles.csv", [[VIN, "SEDAN", "2024-06-01"], [VIN.lower(), " sedan  ", "06/01/2024"]]),
    ("campaigns.csv", [[CID, "SEDAN", "2024-01-01", "2024-12-31"],
                       ["rc2026-1", " sedan ", "01/01/2024", "12/31/2024"]]),
])
def test_equivalent_master_duplicates_are_safe(raw, tmp_path, file, rows):
    write(raw, file, rows)
    run = pipeline.run_check(raw, tmp_path / "r.db", check_date=AS_OF)
    assert not run.report.flagged_repairs
    assert [i.issue_code for i in run.report.data_issues] == ["DUPLICATE_ROW"]


def test_future_campaign_boundary_and_single_day_range_are_supported(raw, tmp_path):
    write(raw, "campaigns.csv", [[CID, "SEDAN", "2024-06-01", "2027-01-01"]])
    db = tmp_path / "r.db"
    assert not pipeline.run_check(raw, db, check_date=AS_OF).report.flagged_repairs
    write(raw, "campaigns.csv", [[CID, "SEDAN", "2024-06-01", "2024-06-01"]])
    assert not pipeline.run_check(raw, db, check_date=AS_OF).report.flagged_repairs


def test_flags_are_per_vin_campaign_and_use_all_accepted_repair_dates(raw, tmp_path):
    other = "RC-2026-002"
    write(raw, "campaigns.csv", [[CID, "UTILITY", "2024-01-01", "2024-12-31"],
                                  [other, "SEDAN", "2024-01-01", "2024-12-31"]])
    write(raw, "repairs_done.csv", [[VIN, CID, "2026-03-01", "a"],
                                    [VIN, CID, "2026-03-02", "b"],
                                    [VIN, CID, "2026-03-02", "duplicate"],
                                    [VIN, other, "2026-03-01", "eligible"]])
    run = pipeline.run_check(raw, tmp_path / "r.db", check_date=AS_OF)
    flag, = run.report.flagged_repairs
    assert flag.campaign_id == CID
    assert len(flag.facts.repairs) == 2
    assert {i.issue_code for i in run.report.data_issues} == {"DATE_CONFLICT", "DUPLICATE_ROW"}


def test_invalid_repair_is_not_evidence_of_repair(raw, tmp_path):
    write(raw, "vehicles.csv", [[VIN, "UTILITY", "2024-06-01"]])
    write(raw, "repairs_done.csv", [[VIN, CID, "bad", ""]])
    report = pipeline.run_check(raw, tmp_path / "r.db", check_date=AS_OF).report
    assert not report.flagged_repairs
    assert [i.issue_code for i in report.data_issues] == ["BAD_DATE"]


def test_reload_recheck_and_new_upload_preserve_original_evidence(raw, tmp_path):
    write(raw, "vehicles.csv", [[VIN, "UTILITY", "2024-06-01"]])
    db = tmp_path / "r.db"
    first = pipeline.run_check(raw, db, check_date=AS_OF)
    assert pipeline.current_report(db) == first
    assert report_from_dict(to_dict(first.report)) == first.report
    write(raw, "vehicles.csv", [[VIN, "SEDAN", "2024-06-01"]])
    assert pipeline.input_check(db, raw, first.ingest_id)["state"] == "changed"
    second = pipeline.recheck(db, day_limit=61)
    assert second.report.flagged_repairs == first.report.flagged_repairs
    third = pipeline.run_check(raw, db, check_date=AS_OF)
    assert not third.report.flagged_repairs
    assert len([h for h in third.report.history if h.kind is FindingKind.UNAFFECTED_REPAIR]) == 2
    assert pipeline.saved_run(db, first.run_id) == first


def test_api_exposes_separate_flags_evidence_and_history(raw, tmp_path):
    write(raw, "vehicles.csv", [[VIN, "UTILITY", "2024-06-01"]])
    app = Application(tmp_path / "r.db", raw)
    status, body = app.request("POST", "/api/checks", {"check_date": AS_OF.isoformat()})
    assert status == 201
    report = body["report"]
    flag, = report["flagged_repairs"]
    assert flag["kind"] == "unaffected repair"
    assert flag["facts"]["vehicle"]["model"] == "UTILITY"
    assert flag["facts"]["campaign"]["start_date"] == "2024-01-01"
    assert report["data_quality"] == report["data_issues"] == []
    assert app.request("GET", "/api/report")[1]["report"] == report
    assert app.request("GET", "/api/history")[1]["history"][-1]["kind"] == "unaffected repair"


def test_cli_round_trip_includes_flag(raw, tmp_path):
    write(raw, "vehicles.csv", [[VIN, "UTILITY", "2024-06-01"]])
    import sys
    args = [sys.executable, "-m", "recall_tracker", "check", "--raw", str(raw),
            "--db", str(tmp_path / "r.db"), "--as-of", AS_OF.isoformat()]
    output = subprocess.run(args, check=True, capture_output=True, text=True)
    assert len(json.loads(output.stdout)["report"]["flagged_repairs"]) == 1


def test_report_validator_rejects_unsupported_or_forged_flags(raw, tmp_path):
    write(raw, "vehicles.csv", [[VIN, "UTILITY", "2024-06-01"]])
    report = pipeline.run_check(raw, tmp_path / "r.db", check_date=AS_OF).report
    flag, = report.flagged_repairs
    for facts in (replace(flag.facts, vehicle=None),
                  replace(flag.facts, vehicle=Vehicle(VIN, "SEDAN", date(2024, 6, 1)))):
        with pytest.raises(ContractError):
            replace(report, flagged_repairs=(replace(flag, facts=facts),),
                    vehicles=(replace(report.vehicles[0], facts=facts),))
    with pytest.raises(ContractError):
        replace(report, flagged_repairs=(flag, flag))


@pytest.mark.parametrize("raw_value,expected", [(" Syn  Sedan ", "SYN SEDAN"), ("CX-5", "CX-5")])
def test_model_normalization_only_changes_case_and_whitespace(raw_value, expected):
    assert normalize_model(raw_value).value == expected


def test_campaign_contract_rejects_inverted_range():
    with pytest.raises(ContractError):
        Campaign(CID, "SEDAN", date(2025, 1, 1), date(2024, 1, 1))


def test_demo_contains_flagged_repair_and_inventory_without_repairs(tmp_path):
    rows = generate.generate(7, AS_OF, 60)
    generate.write_outputs(rows, tmp_path / "raw", 7, AS_OF)
    report = pipeline.run_check(tmp_path / "raw", tmp_path / "r.db", check_date=AS_OF).report
    assert len(report.flagged_repairs) == 1
    assert len(rows["vehicles.csv"]) > len({v.vin for v in report.vehicles})


@pytest.fixture
def legacy_db(tmp_path):
    db = tmp_path / "legacy.db"
    fixture = Path(__file__).parent / "fixtures" / "rec34_legacy.sql"
    with sqlite3.connect(db) as con:
        con.executescript(fixture.read_text())
    return db


def database_dump(db):
    with sqlite3.connect(db) as con:
        return tuple(con.iterdump())


def test_old_reports_read_without_migration_or_writes(legacy_db):
    before = database_dump(legacy_db)
    run = pipeline.saved_run(legacy_db, 1)
    assert not run.report.flagged_repairs
    assert all(v.facts.vehicle is None and v.facts.campaign is None for v in run.report.vehicles)
    assert pipeline.current_report(legacy_db).report.decisions[-1].note == "Original decision."
    assert database_dump(legacy_db) == before


def test_legacy_database_upgrade_preserves_every_historical_record(legacy_db, raw):
    with sqlite3.connect(legacy_db) as con:
        before = {t: con.execute(f"SELECT * FROM {t}").fetchall() for t in (
            "affected_vehicles", "notices_sent", "repairs_done", "data_issues",
            "check_runs", "check_history", "coordinator_decisions")}
    original = pipeline.saved_run(legacy_db, 1)
    # New issues exercise the expanded data_issues enum; mismatched metadata
    # exercises the expanded check-history enum in the following upload.
    write(raw, "vehicles.csv", [])
    missing = pipeline.run_check(raw, legacy_db, check_date=AS_OF)
    assert any(i.issue_code == "ELIGIBILITY_UNAVAILABLE" for i in missing.report.data_issues)
    write(raw, "vehicles.csv", [[VIN, "UTILITY", "2024-06-01"]])
    latest = pipeline.run_check(raw, legacy_db, check_date=AS_OF)
    assert latest.report.flagged_repairs
    assert pipeline.saved_run(legacy_db, 1) == original
    with sqlite3.connect(legacy_db) as con:
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        for table, records in before.items():
            assert con.execute(f"SELECT * FROM {table}").fetchall()[:len(records)] == records
        assert con.execute("SELECT name FROM sqlite_master WHERE name='check_history_pair'").fetchone()
        assert con.execute("SELECT COUNT(*) FROM cur_data_issues").fetchone() == (0,)
    # Rechecking an old three-file ingest cannot borrow new master records.
    from recall_tracker.snapshot import read_snapshot
    with sqlite3.connect(legacy_db) as con:
        old = read_snapshot(con, 1)
        assert all(f.vehicle is None and f.campaign is None for f in old.facts)


def test_failed_upgrade_rolls_back_schema_history_and_source_rows(legacy_db, raw, monkeypatch):
    before = database_dump(legacy_db)
    def fail(*args):
        raise RuntimeError("Downstream failure after both schema upgrades")
    monkeypatch.setattr(storage.CheckStore, "save_run", fail)
    with pytest.raises(RuntimeError, match="Downstream failure"):
        pipeline.run_check(raw, legacy_db, check_date=AS_OF)
    assert database_dump(legacy_db) == before


def test_rechecking_legacy_ingest_does_not_invent_eligibility(legacy_db):
    report = pipeline.recheck(legacy_db, day_limit=61).report
    assert not report.flagged_repairs
    assert report.history


@pytest.mark.parametrize("seed,size,digest", [
    (7, 60, "f9cd65df64ca322d50386085b36adc3433f90780ee25e264199204a20a3aff1f"),
    (42, 500, "2ce72bf97aba5f1e7c92dbbdbdc767abf0e03ae7eaab2402db2498436877e1fd"),
])
def test_supplied_affected_demo_data_is_unchanged(seed, size, digest):
    # Hashes are from the pre-REC-34 generator at 610747c.
    import hashlib
    rows = generate.generate(seed, AS_OF, size)
    data = generate.render_csv(generate.COLUMNS["affected_vehicles.csv"], rows["affected_vehicles.csv"])
    assert hashlib.sha256(data).hexdigest() == digest
