"""The command-line workflow emits reports or clear errors, never both."""

import json
import shutil

import pytest

from recall_tracker.__main__ import main


@pytest.fixture
def paths(small_dir, tmp_path):
    raw = tmp_path / "raw"
    shutil.copytree(small_dir, raw)
    return raw, tmp_path / "recall.db"


def command(capsys, *args):
    assert main(list(args)) == 0
    result = capsys.readouterr()
    assert result.err == ""
    return json.loads(result.out)


def test_check_report_recheck_and_runs_form_a_persisted_workflow(paths, capsys):
    raw, db = paths
    original = command(capsys, "check", "--raw", str(raw), "--db", str(db),
                       "--as-of", "2026-11-01")
    assert original["report"]["day_limit"] == 60
    assert original["report"]["findings"]
    assert command(capsys, "report", "--db", str(db)) == original
    shutil.rmtree(raw)
    recalculated = command(capsys, "recheck", "--db", str(db), "--day-limit", "61")
    assert recalculated["run_id"] == 2
    assert recalculated["ingest_id"] == original["ingest_id"]
    assert recalculated["report"]["day_limit"] == 61
    assert len(recalculated["report"]["findings"]) < len(original["report"]["findings"])
    again = command(capsys, "recheck", "--db", str(db))
    assert again["report"]["day_limit"] == 61
    assert command(capsys, "report", "--db", str(db), "--run-id", "1") == original
    runs = command(capsys, "runs", "--db", str(db))["runs"]
    assert [run["run_id"] for run in runs] == [1, 2, 3]
    assert [run["day_limit"] for run in runs] == [60, 61, 61]


def test_decide_updates_current_view_without_rewriting_saved_run(paths, capsys):
    raw, db = paths
    original = command(capsys, "check", "--raw", str(raw), "--db", str(db),
                       "--as-of", "2026-11-01")
    vehicle = original["report"]["vehicles"][0]
    note = "Ask the coordinator; never alter source records."
    result = command(capsys, "decide", "--db", str(db), "--vin", vehicle["vin"],
                     "--campaign-id", vehicle["campaign_id"], "--status", "follow up",
                     "--note", note, "--on", "2026-11-01")
    assert result == {"decision_id": 1}
    current = command(capsys, "report", "--db", str(db))
    assert current["report"]["decisions"][0]["status"] == "follow up"
    assert current["report"]["decisions"][0]["note"] == note
    assert command(capsys, "report", "--db", str(db), "--run-id", "1") == original


@pytest.mark.parametrize("file", [
    "affected_vehicles.csv", "notices_sent.csv", "repairs_done.csv"])
def test_missing_file_exits_two_with_no_success_looking_report(paths, capsys, file):
    raw, db = paths
    (raw / file).unlink()
    assert main(["check", "--raw", str(raw), "--db", str(db),
                 "--as-of", "2026-11-01"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert file in output.err
    assert "Nothing was changed" in output.err
    assert not db.exists()


def test_invalid_limit_does_not_create_database_or_emit_json(paths, capsys):
    raw, db = paths
    assert main(["check", "--raw", str(raw), "--db", str(db), "--day-limit", "0"]) == 2
    result = capsys.readouterr()
    assert result.out == ""
    assert "positive whole number" in result.err
    assert not db.exists()


@pytest.mark.parametrize("action", ["report", "recheck", "runs"])
def test_missing_database_has_clear_error_and_no_stdout(paths, capsys, action):
    _, db = paths
    assert main([action, "--db", str(db)]) == 2
    result = capsys.readouterr()
    assert result.out == ""
    assert "No recall database" in result.err
    assert not db.exists()


@pytest.mark.parametrize("extra", [["--as-of", "2026-02-30"],
                                  ["--day-limit", "sixty"]])
def test_invalid_command_arguments_use_exit_code_two(paths, capsys, extra):
    raw, db = paths
    with pytest.raises(SystemExit) as stopped:
        main(["check", "--raw", str(raw), "--db", str(db), *extra])
    assert stopped.value.code == 2
    result = capsys.readouterr()
    assert result.out == ""
    assert "error:" in result.err
    assert not db.exists()
