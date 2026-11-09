"""The complete tool runs on Julian's CSV ingest and preserves its history."""

import csv
import hashlib
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from conftest import AS_OF, write_master_data
from recall_tracker import generate, pipeline
from recall_tracker.contract import (
    ContractError, Decision, DecisionStatus, FindingKind, to_dict)
from recall_tracker.ingest import FILES, IngestStopError, load
from recall_tracker.plant import HOSTILE_NOTE
from recall_tracker.vin import with_check_digit


CAMPAIGN = "RC-2026-001"
SECOND_CAMPAIGN = "RC-2026-002"
BOUNDARY_DATE = date(2026, 3, 4)


def vin(n):
    return with_check_digit(f"SYNTEST0RA{n:07d}")


def hashes(raw):
    return {name: hashlib.sha256((raw / name).read_bytes()).hexdigest()
            for name in FILES}


def counts(db):
    with sqlite3.connect(db) as con:
        return tuple(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                     for table in ("ingests", "check_runs",
                                   "coordinator_decisions"))


@pytest.fixture
def boundary_raw(tmp_path):
    """Independent, readable examples of the locked client rules."""
    raw = tmp_path / "raw"
    raw.mkdir()
    rows = {
        "affected_vehicles.csv": (
            ["vin", "campaign_id"],
            [[vin(n), CAMPAIGN] for n in range(1, 8)] +
            [[vin(1), SECOND_CAMPAIGN], ["", CAMPAIGN]]),
        "notices_sent.csv": (
            ["vin", "campaign_id", "notice_date"],
            [[vin(n), CAMPAIGN, "01/01/2026"] for n in (1, 2, 3, 6)] +
            [[vin(4), CAMPAIGN, "03/03/2026"],
             [vin(6), CAMPAIGN, "02/28/2026"],
             [vin(7), CAMPAIGN, "02/30/2026"],
             [vin(8), CAMPAIGN, "01/01/2026"]]),
        "repairs_done.csv": (
            ["vin", "campaign_id", "repair_date", "tech_note"],
            [[vin(1), CAMPAIGN, "03/01/2026", "Completed."],
             [vin(2), CAMPAIGN, "03/02/2026", HOSTILE_NOTE],
             [vin(5), CAMPAIGN, "03/01/2026", "No notice on file."],
             [vin(6), CAMPAIGN, "12/31/2025", "Before notice."],
             [vin(6), CAMPAIGN, "03/02/2026", "First usable repair."],
             [vin(6), CAMPAIGN, "03/03/2026", "Later repair."]]),
    }
    for name, (header, values) in rows.items():
        with (raw / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(values)
    write_master_data(raw, [r for _, values in rows.values() for r in values])
    return raw


def test_locked_cases_run_from_csv_to_saved_report(boundary_raw, tmp_path):
    db = tmp_path / "recall.db"
    before = hashes(boundary_raw)
    run = pipeline.run_check(boundary_raw, db, check_date=BOUNDARY_DATE)
    report = run.report
    flags = {(f.vin, f.campaign_id): f.kind for f in report.findings}
    assert flags == {
        (vin(2), CAMPAIGN): FindingKind.REPAIR,
        (vin(3), CAMPAIGN): FindingKind.REPAIR,
        (vin(5), CAMPAIGN): FindingKind.NOTIFICATION,
        (vin(6), CAMPAIGN): FindingKind.REPAIR,
        (vin(1), SECOND_CAMPAIGN): FindingKind.NOTIFICATION,
    }
    views = {(v.vin, v.campaign_id): v for v in report.vehicles}
    assert views[(vin(1), CAMPAIGN)].inclusive_days == 60
    assert views[(vin(1), CAMPAIGN)].on_time is True
    assert views[(vin(2), CAMPAIGN)].inclusive_days == 61
    assert views[(vin(2), CAMPAIGN)].on_time is False
    assert views[(vin(4), CAMPAIGN)].inclusive_days == 2
    assert views[(vin(6), CAMPAIGN)].notice_date_used == date(2026, 1, 1)
    assert views[(vin(6), CAMPAIGN)].repair_date_used == date(2026, 3, 2)
    assert views[(vin(7), CAMPAIGN)].in_notices is True
    assert views[(vin(7), CAMPAIGN)].notice_date_used is None
    assert report.data_quality
    assert all(f.kind is FindingKind.DATA_QUALITY for f in report.data_quality)
    assert any(f.vin == vin(6) and "before" in f.reason
               for f in report.data_quality)
    assert any(f.vin == vin(8) for f in report.data_quality)
    assert any(issue.vin is None and issue.action == "quarantined"
               for issue in report.data_issues)
    assert report.decisions == ()
    assert hashes(boundary_raw) == before
    assert pipeline.saved_run(db, run.run_id) == run
    assert pipeline.current_report(db) == run
    assert counts(db) == (1, 1, 0)


@pytest.mark.parametrize("seed,size", [(7, 60), (42, 500)])
def test_generated_seed_locked_cases_and_normalization(seed, size, tmp_path):
    raw, db = tmp_path / "raw", tmp_path / "recall.db"
    rows = generate.generate(seed, AS_OF, size)
    generate.write_outputs(rows, raw, seed, AS_OF)
    before = hashes(raw)
    run = pipeline.run_check(raw, db, check_date=AS_OF)
    by_pair = {(view.vin, view.campaign_id): view
               for view in run.report.vehicles}
    flags = {(f.vin, f.campaign_id): f.kind for f in run.report.findings}
    expected = {
        "case:not_notified": FindingKind.NOTIFICATION,
        "case:repair_day_60": None,
        "case:repair_day_61": FindingKind.REPAIR,
        "case:no_repair_past_limit": FindingKind.REPAIR,
        "case:no_repair_within_limit": None,
        "case:repair_without_notice": FindingKind.NOTIFICATION,
        "case:hostile_note": None,
    }
    for row in rows["affected_vehicles.csv"]:
        if row.tag in expected:
            pair = (row.values["vin"], row.values["campaign_id"])
            assert flags.get(pair) is expected[row.tag], row.tag
            if row.tag == "case:repair_day_60":
                assert by_pair[pair].inclusive_days == 60
            elif row.tag == "case:repair_day_61":
                assert by_pair[pair].inclusive_days == 61
    with sqlite3.connect(db) as con:
        accepted = set(con.execute(
            "SELECT vin, campaign_id FROM cur_affected_vehicles"))
        assert accepted == {pair for pair, v in by_pair.items()
                            if v.facts.affected}
        assert {(f.vin, f.campaign_id) for f in run.report.findings} <= accepted
        assert con.execute(
            "SELECT tech_note FROM cur_repairs_done WHERE tech_note=?",
            (HOSTILE_NOTE,)).fetchone() == (HOSTILE_NOTE,)
    assert all(len(v.vin) == 17 and v.vin == v.vin.upper()
               for v in run.report.vehicles)
    assert len(run.report.data_issues) == 26
    assert all(f.kind is not FindingKind.DATA_QUALITY
               for f in run.report.findings)
    assert run.report.decisions == ()
    assert hashes(raw) == before
    # A fully serialized payload is ready for Sanket's report views.
    assert to_dict(pipeline.current_report(db).report) == to_dict(run.report)


def test_both_business_checks_receive_same_accepted_list(
        boundary_raw, tmp_path, monkeypatch):
    seen = []
    for name in ("check_notifications", "check_repairs"):
        original = getattr(pipeline, name)

        def capture(affected, *args, _original=original, **kwargs):
            seen.append(affected)
            return _original(affected, *args, **kwargs)

        monkeypatch.setattr(pipeline, name, capture)
    run = pipeline.run_check(boundary_raw, tmp_path / "recall.db",
                             check_date=BOUNDARY_DATE)
    assert len(seen) == 2
    assert seen[0] is seen[1]
    assert len(seen[0]) == 8  # blank-VIN affected row was quarantined
    assert {(p.vin, p.campaign_id) for p in seen[0]} == {
        (v.vin, v.campaign_id) for v in run.report.vehicles if v.facts.affected}


def damage(raw, name, problem, monkeypatch):
    target = raw / name
    if problem == "missing":
        target.unlink()
    elif problem == "unreadable":
        original = Path.read_bytes

        def no_read(self):
            if self == target:
                raise PermissionError(13, "Permission denied")
            return original(self)

        monkeypatch.setattr(Path, "read_bytes", no_read)
    elif problem == "malformed":
        target.write_text('vin,campaign_id\n"Unclosed CSV', encoding="utf-8")
    elif problem == "bad_encoding":
        target.write_bytes(b"\xff\xfe\x80")
    elif problem == "missing_column":
        target.write_text("vin\n" + vin(1) + "\n", encoding="utf-8")
    else:
        raise AssertionError(problem)


@pytest.mark.parametrize("name", FILES)
@pytest.mark.parametrize("problem", [
    "missing", "unreadable", "malformed", "bad_encoding", "missing_column"])
@pytest.mark.parametrize("existing_db", [False, True])
def test_any_unusable_file_stops_without_partial_result(
        name, problem, existing_db, boundary_raw, tmp_path, monkeypatch):
    db = tmp_path / "recall.db"
    if existing_db:
        original = pipeline.run_check(boundary_raw, db,
                                     check_date=BOUNDARY_DATE)
        before = db.read_bytes()
    damage(boundary_raw, name, problem, monkeypatch)
    with pytest.raises(IngestStopError, match=name):
        pipeline.run_check(boundary_raw, db, check_date=BOUNDARY_DATE,
                           day_limit=17)
    if existing_db:
        assert db.read_bytes() == before
        assert counts(db) == (1, 1, 0)
        assert pipeline.saved_runs(db) == (original,)
        assert pipeline.settings(db) == {"day_limit": 60}
    else:
        assert not db.exists()


def test_downstream_failure_rolls_back_ingest_limit_and_run(
        boundary_raw, tmp_path, monkeypatch):
    db = tmp_path / "recall.db"
    original = pipeline.run_check(boundary_raw, db, check_date=BOUNDARY_DATE)
    before = db.read_bytes()

    def fail(*args, **kwargs):
        raise RuntimeError("check failed after ingest")

    monkeypatch.setattr(pipeline, "check_repairs", fail)
    with pytest.raises(RuntimeError, match="check failed after ingest"):
        pipeline.run_check(boundary_raw, db, check_date=BOUNDARY_DATE,
                           day_limit=17)
    assert db.read_bytes() == before
    assert counts(db) == (1, 1, 0)
    assert pipeline.settings(db) == {"day_limit": 60}
    assert pipeline.saved_runs(db) == (original,)


def test_recheck_uses_loaded_data_saves_limit_and_keeps_original_runs(
        boundary_raw, tmp_path):
    db = tmp_path / "recall.db"
    first = pipeline.run_check(boundary_raw, db, check_date=BOUNDARY_DATE)
    for name in FILES:
        (boundary_raw / name).unlink()
    second = pipeline.recheck(db, day_limit=61)
    assert second.ingest_id == first.ingest_id
    assert second.check_date == first.check_date
    assert second.day_limit == 61
    assert {(f.vin, f.campaign_id) for f in second.report.findings
            if f.kind is FindingKind.REPAIR} == {(vin(3), CAMPAIGN)}
    assert pipeline.settings(db) == {"day_limit": 61}
    third = pipeline.recheck(db)
    assert third.day_limit == 61
    assert counts(db) == (1, 3, 0)
    assert pipeline.saved_run(db, first.run_id) == first
    assert pipeline.saved_runs(db) == (first, second, third)
    assert len(third.report.history) == sum(
        len(r.report.findings) + len(r.report.data_quality)
        for r in (first, second, third))


def test_recheck_preserves_later_clock_when_only_limit_changes(small_dir, tmp_path):
    db = tmp_path / "recall.db"
    first = pipeline.run_check(small_dir, db, check_date=AS_OF)
    later_date = AS_OF + timedelta(days=90)
    later = pipeline.recheck(db, check_date=later_date)
    assert later.ingest_id == first.ingest_id
    changed = pipeline.recheck(db, day_limit=61)
    assert changed.check_date == later_date
    assert changed.report.check_date == later_date


def test_recheck_new_julian_ingest_uses_its_own_clock(small_dir, full_dir, tmp_path):
    db = tmp_path / "recall.db"
    pipeline.run_check(small_dir, db, check_date=AS_OF)
    pipeline.recheck(db, check_date=AS_OF + timedelta(days=90))
    new_ingest = load(full_dir, db, AS_OF)
    new_run = pipeline.recheck(db)
    assert new_run.ingest_id == new_ingest
    assert new_run.check_date == AS_OF


def test_recheck_builds_directly_on_julians_ingest_only_db(small_dir, tmp_path):
    db = tmp_path / "recall.db"
    ingest_id = load(small_dir, db, AS_OF)
    assert pipeline.settings(db) == {"day_limit": 60}
    assert pipeline.saved_runs(db) == ()
    run = pipeline.recheck(db)
    assert run.ingest_id == ingest_id
    assert run.check_date == AS_OF
    assert run.report.findings
    assert counts(db) == (1, 1, 0)


def test_decisions_append_and_survive_later_uploads(small_dir, full_dir, tmp_path):
    db = tmp_path / "recall.db"
    first = pipeline.run_check(small_dir, db, check_date=AS_OF)
    view = next(v for v in first.report.vehicles if v.facts.affected)
    reviewed = Decision(view.vin, view.campaign_id, DecisionStatus.REVIEWED,
                        "Read records.", AS_OF)
    follow_up = Decision(view.vin, view.campaign_id, DecisionStatus.FOLLOW_UP,
                         "Coordinator will review.", AS_OF)
    backdated = Decision(view.vin, view.campaign_id, DecisionStatus.NO_ACTION,
                         None, AS_OF - timedelta(days=1))
    for decision in (reviewed, follow_up, backdated):
        pipeline.record_decision(db, decision)
    report = pipeline.current_report(db).report
    current = next(v for v in report.vehicles
                   if (v.vin, v.campaign_id) == (view.vin, view.campaign_id))
    assert current.decision == follow_up  # same-day insertion tie, not backdate
    assert report.decisions == (reviewed, follow_up, backdated)
    assert pipeline.saved_run(db, first.run_id) == first
    assert first.report.decisions == ()
    second = pipeline.run_check(full_dir, db, check_date=AS_OF)
    assert second.ingest_id != first.ingest_id
    assert second.report.decisions == (reviewed, follow_up, backdated)
    assert len(second.report.history) > len(first.report.history)
    assert counts(db) == (2, 2, 3)
    assert pipeline.saved_run(db, first.run_id) == first


@pytest.mark.parametrize("bad_date", [False, 0, ""])
def test_falsey_invalid_check_dates_are_rejected(boundary_raw, tmp_path, bad_date):
    db = tmp_path / "recall.db"
    with pytest.raises(ContractError, match="calendar date"):
        pipeline.run_check(boundary_raw, db, check_date=bad_date)
    assert not db.exists()


def test_recheck_before_ingest_date_does_not_save_partial_run(small_dir, tmp_path):
    db = tmp_path / "recall.db"
    first = pipeline.run_check(small_dir, db, check_date=AS_OF)
    before = db.read_bytes()
    with pytest.raises(pipeline.PipelineError, match="cannot precede"):
        pipeline.recheck(db, check_date=AS_OF - timedelta(days=1), day_limit=7)
    assert db.read_bytes() == before
    assert pipeline.saved_runs(db) == (first,)
    assert pipeline.settings(db) == {"day_limit": 60}
