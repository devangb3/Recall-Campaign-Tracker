"""Coordinator-facing routes use real ingest, checks and persisted reports."""

import json
import shutil

import pytest

from recall_tracker.api import Application


@pytest.fixture
def app(small_dir, tmp_path):
    raw = tmp_path / "raw"
    shutil.copytree(small_dir, raw)
    return Application(tmp_path / "recall.db", raw)


def checked(app):
    status, value = app.request("POST", "/api/checks", {"check_date": "2026-11-01"})
    assert status == 201, value
    return value


def test_check_returns_a_json_report_with_separate_business_and_data_issues(app):
    result = checked(app)
    assert result["run_id"] == 1
    assert result["ingest_id"] == 1
    report = result["report"]
    assert report["check_date"] == "2026-11-01"
    assert report["day_limit"] == 60
    assert sum(bool(view["facts"]["affected"]) for view in report["vehicles"]) == 60
    assert {finding["kind"] for finding in report["findings"]} == {
        "notification", "repair"}
    assert {finding["kind"] for finding in report["data_quality"]} == {"data quality"}
    assert len(report["data_issues"]) == 27
    assert any(issue["vin"] is None for issue in report["data_issues"])
    assert json.loads(json.dumps(result)) == result
    assert app.request("GET", "/api/report") == (200, result)


def test_health_and_default_settings_do_not_create_a_database(app):
    assert app.request("GET", "/healthz") == (200, {"status": "ok"})
    assert app.request("GET", "/api/settings") == (200, {"day_limit": 60})
    assert not app.db_path.exists()


@pytest.mark.parametrize("file", [
    "affected_vehicles.csv", "notices_sent.csv", "repairs_done.csv"])
def test_bad_file_returns_only_clear_error_without_publishing_a_run(app, file):
    (app.raw_dir / file).unlink()
    status, value = app.request("POST", "/api/checks", {"check_date": "2026-11-01"})
    assert status == 422
    assert set(value) == {"error"}
    assert file in value["error"]
    assert "Nothing was changed" in value["error"]
    assert not app.db_path.exists()


def test_bad_upload_preserves_existing_run_decisions_and_day_limit(app):
    initial = checked(app)
    vehicle = initial["report"]["vehicles"][0]
    assert app.request("POST", "/api/decisions", {
        "vin": vehicle["vin"], "campaign_id": vehicle["campaign_id"],
        "status": "reviewed", "decided_on": "2026-11-01"})[0] == 201
    before = app.request("GET", "/api/report")[1]
    (app.raw_dir / "notices_sent.csv").write_text("vin,campaign_id\n", encoding="utf-8")
    status, value = app.request("POST", "/api/checks", {
        "check_date": "2026-11-01", "day_limit": 90})
    assert status == 422
    assert set(value) == {"error"}
    assert "notices_sent.csv" in value["error"]
    assert "notice_date" in value["error"]
    assert app.request("GET", "/api/report") == (200, before)
    assert app.request("GET", "/api/runs/1") == (200, initial)
    assert app.request("GET", "/api/settings") == (200, {"day_limit": 60})
    assert len(app.request("GET", "/api/runs")[1]["runs"]) == 1


def test_day_limit_recalculates_and_persists_without_source_files(app):
    original = checked(app)
    shutil.rmtree(app.raw_dir)
    status, changed = app.request("POST", "/api/day-limit", {"day_limit": 61})
    assert status == 201
    assert changed["ingest_id"] == original["ingest_id"]
    assert changed["run_id"] != original["run_id"]
    assert changed["report"]["day_limit"] == 61
    assert len(changed["report"]["findings"]) < len(original["report"]["findings"])
    reopened = Application(app.db_path, app.raw_dir)
    assert reopened.request("GET", "/api/settings") == (200, {"day_limit": 61})
    status, recalculated = reopened.request("POST", "/api/recheck", {})
    assert status == 201
    assert recalculated["ingest_id"] == original["ingest_id"]
    assert recalculated["report"]["day_limit"] == 61
    assert app.request("GET", "/api/runs/1") == (200, original)


def test_decisions_and_history_keep_every_entry_while_original_run_is_immutable(app):
    original = checked(app)
    vehicle = original["report"]["vehicles"][0]
    pair = {key: vehicle[key] for key in ("vin", "campaign_id")}
    for status, note in [("reviewed", "  File checked.  "), ("follow up", "Ask the coordinator.")]:
        response, value = app.request("POST", "/api/decisions", {
            **pair, "status": status, "note": note, "decided_on": "2026-11-01"})
        assert response == 201
        assert value["decision_id"] > 0
    status, current = app.request("GET", "/api/report")
    assert status == 200
    assert current["run_id"] == original["run_id"]
    assert [decision["status"] for decision in current["report"]["decisions"]] == [
        "reviewed", "follow up"]
    assert current["report"]["decisions"][0]["note"] == "File checked."
    selected = next(view for view in current["report"]["vehicles"]
                    if (view["vin"], view["campaign_id"]) ==
                    (pair["vin"], pair["campaign_id"]))
    assert selected["decision"]["status"] == "follow up"
    assert app.request("GET", "/api/runs/1") == (200, original)
    status, history = app.request("GET", "/api/history")
    assert status == 200
    assert history["history"] == original["report"]["history"]
    assert history["decisions"] == current["report"]["decisions"]
    status, runs = app.request("GET", "/api/runs")
    assert status == 200
    assert runs["runs"] == [{"run_id": 1, "ingest_id": 1,
                              "check_date": "2026-11-01", "day_limit": 60}]


@pytest.mark.parametrize("body", [
    [], "not an object", True, 5,
    {"unknown": 1}, {"check_date": None}, {"check_date": False},
    {"check_date": "2026-02-30"}, {"check_date": "20261101"},
    {"check_date": "11/01/2026"}, {"check_date": "2026-11-01T00:00:00"},
    {"day_limit": True}, {"day_limit": "60"}, {"day_limit": 0},
    {"day_limit": 60.0}, {"day_limit": None},
])
def test_invalid_check_fields_return_error_without_touching_database(app, body):
    status, value = app.request("POST", "/api/checks", body)
    assert status == 400
    assert set(value) == {"error"}
    assert not app.db_path.exists()


@pytest.mark.parametrize("body", [{}, {"status": "close campaign"},
                                  {"status": "reviewed", "note": True}])
def test_invalid_decision_is_rejected_without_creating_storage(app, body):
    status, value = app.request("POST", "/api/decisions", body)
    assert status == 400
    assert set(value) == {"error"}
    assert not app.db_path.exists()


def test_day_limit_requires_a_value_and_unknown_routes_return_errors(app):
    assert app.request("POST", "/api/day-limit", {})[0] == 400
    for method, path in [("GET", "/missing"), ("POST", "/missing"),
                         ("DELETE", "/api/checks")]:
        status, value = app.request(method, path)
        assert status == 404
        assert set(value) == {"error"}
    assert not app.db_path.exists()


def test_run_lookup_errors_do_not_return_a_report(app):
    checked(app)
    for path, expected in [("/api/runs/999", 404), ("/api/runs/nope", 400),
                           ("/api/runs/0", 400)]:
        status, value = app.request("GET", path)
        assert status == expected
        assert set(value) == {"error"}


def test_unexpected_failure_returns_only_generic_error(app, monkeypatch, caplog):
    checked(app)

    def fail(*args, **kwargs):
        raise RuntimeError("internal detail must not appear as a successful report")

    monkeypatch.setattr("recall_tracker.api.pipeline.recheck", fail)
    status, value = app.request("POST", "/api/recheck", {})
    assert status == 500
    assert set(value) == {"error"}
    assert "internal detail" not in value["error"]
    assert caplog.records
