"""Generator output: files, columns, determinism, synthetic values."""

import csv
import hashlib
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from conftest import (AS_OF, CAMPAIGNS, SMALL, read_csv, ref_campaign,
                      ref_date, ref_vin, write_dataset)
from recall_tracker import generate as gen

REPO = Path(__file__).resolve().parent.parent
ALL_OUTPUTS = (*gen.COLUMNS, gen.MESS_LOG_FILE, "manifest.json")


def file_hashes(folder: Path) -> dict:
    return {name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
            for name in ALL_OUTPUTS}


def manifest(folder: Path) -> dict:
    return json.loads((folder / "manifest.json").read_text())


# ---- files and columns --------------------------------------------------
@pytest.mark.parametrize("name", ALL_OUTPUTS)
def test_output_file_exists(data_dir, name):
    assert (data_dir / name).is_file()


def test_no_other_files_are_written(data_dir):
    assert sorted(p.name for p in data_dir.iterdir()) == sorted(ALL_OUTPUTS)


@pytest.mark.parametrize("name", list(gen.COLUMNS))
def test_header_is_exactly_the_contract_columns(data_dir, name):
    with open(data_dir / name, newline="") as f:
        assert next(csv.reader(f)) == gen.COLUMNS[name]


def test_mess_log_header(data_dir):
    with open(data_dir / gen.MESS_LOG_FILE, newline="") as f:
        assert next(csv.reader(f)) == gen.MESS_LOG_COLUMNS


@pytest.mark.parametrize("name", list(gen.COLUMNS))
def test_every_row_has_every_column(data_dir, name):
    with open(data_dir / name, newline="") as f:
        widths = {len(r) for r in csv.reader(f)}
    assert widths == {len(gen.COLUMNS[name])}


@pytest.mark.parametrize("name", list(gen.COLUMNS))
def test_files_are_utf8_without_bom(data_dir, name):
    assert not (data_dir / name).read_bytes().startswith(b"\xef\xbb\xbf")


@pytest.mark.parametrize("name", list(gen.COLUMNS))
def test_files_use_unix_line_endings(data_dir, name):
    assert b"\r" not in (data_dir / name).read_bytes()


@pytest.mark.parametrize("name", list(gen.COLUMNS))
def test_files_end_with_a_newline(data_dir, name):
    assert (data_dir / name).read_bytes().endswith(b"\n")


# ---- manifest -----------------------------------------------------------
@pytest.mark.parametrize("name", [*gen.COLUMNS, gen.MESS_LOG_FILE])
def test_manifest_row_count_matches_file(data_dir, name):
    assert manifest(data_dir)["files"][name]["rows"] == len(
        read_csv(data_dir / name))


@pytest.mark.parametrize("name", [*gen.COLUMNS, gen.MESS_LOG_FILE])
def test_manifest_hash_matches_file(data_dir, name):
    digest = hashlib.sha256((data_dir / name).read_bytes()).hexdigest()
    assert manifest(data_dir)["files"][name]["sha256"] == digest


def test_manifest_records_seed_and_as_of(small_dir):
    m = manifest(small_dir)
    assert (m["seed"], m["as_of"]) == (SMALL["seed"], AS_OF.isoformat())


def test_manifest_records_generator_version(small_dir):
    assert manifest(small_dir)["generator_version"] == gen.GENERATOR_VERSION


# ---- determinism --------------------------------------------------------
def test_same_seed_gives_identical_files(small_dir, tmp_path):
    again = write_dataset(tmp_path, **SMALL)
    assert file_hashes(again) == file_hashes(small_dir)


@pytest.mark.parametrize("name", list(gen.COLUMNS))
def test_different_seed_gives_different_files(small_dir, tmp_path, name):
    other = write_dataset(tmp_path, seed=8, n_vehicles=SMALL["n_vehicles"])
    assert file_hashes(other)[name] != file_hashes(small_dir)[name]


def test_different_as_of_gives_different_files(small_dir, tmp_path):
    other = write_dataset(tmp_path, **SMALL, as_of=date(2026, 10, 1))
    assert file_hashes(other) != file_hashes(small_dir)


def test_output_does_not_depend_on_python_hash_seed(tmp_path):
    """Two processes with different hash seeds write the same bytes."""
    hashes = []
    for hash_seed in ("1", "999"):
        out = tmp_path / hash_seed
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        subprocess.run(
            [sys.executable, "-m", "recall_tracker.generate", "--seed", "7",
             "--vehicles", "60", "--out", str(out)],
            cwd=REPO, env=env, check=True, capture_output=True)
        hashes.append(file_hashes(out))
    assert hashes[0] == hashes[1]


def test_rerun_into_same_folder_overwrites_cleanly(tmp_path):
    write_dataset(tmp_path, seed=1, n_vehicles=60)
    write_dataset(tmp_path, **SMALL)
    fresh = write_dataset(tmp_path / "fresh", **SMALL)
    assert file_hashes(tmp_path) == file_hashes(fresh)


# ---- vehicle counts and campaigns --------------------------------------
def distinct_vins(rows):
    return {ref_vin(r["vin"]) or r["vin"] for r in rows}


def test_full_run_has_about_500_vehicles(full_dir):
    count = len(distinct_vins(read_csv(full_dir / gen.AFFECTED_FILE)))
    assert 490 <= count <= 510


def test_small_run_has_about_60_vehicles(small_dir):
    count = len(distinct_vins(read_csv(small_dir / gen.AFFECTED_FILE)))
    assert 55 <= count <= 65


def test_tiny_vehicle_count_still_gets_background(tmp_path):
    by_file = gen.generate(seed=3, as_of=AS_OF, n_vehicles=0)
    background = [r for r in by_file[gen.AFFECTED_FILE]
                  if r.tag == "background"]
    assert len({r.values["vin"] for r in background}) == gen.MIN_BACKGROUND


def test_some_vehicles_are_in_two_campaigns(files):
    seen = {}
    for r in files[gen.AFFECTED_FILE]:
        vin, cid = ref_vin(r["vin"]), ref_campaign(r["campaign_id"])
        if vin and cid:
            seen.setdefault(vin, set()).add(cid)
    assert any(len(c) == 2 for c in seen.values())


def test_no_vehicle_is_in_more_than_two_campaigns(files):
    seen = {}
    for r in files[gen.AFFECTED_FILE]:
        vin, cid = ref_vin(r["vin"]), ref_campaign(r["campaign_id"])
        if vin and cid:
            seen.setdefault(vin, set()).add(cid)
    assert max(len(c) for c in seen.values()) <= 2


@pytest.mark.parametrize("name", [f for f, cols in gen.COLUMNS.items() if "campaign_id" in cols])
def test_every_readable_campaign_is_a_known_campaign(files, name):
    found = {ref_campaign(r["campaign_id"]) for r in files[name]} - {None}
    assert found <= CAMPAIGNS


@pytest.mark.parametrize("cid", sorted(CAMPAIGNS))
def test_every_campaign_has_affected_vehicles(files, cid):
    assert any(ref_campaign(r["campaign_id"]) == cid
               for r in files[gen.AFFECTED_FILE])


# ---- synthetic values ---------------------------------------------------
@pytest.mark.parametrize("name", [f for f, cols in gen.COLUMNS.items() if "vin" in cols])
def test_every_readable_vin_starts_with_syn(files, name):
    vins = {ref_vin(r["vin"]) for r in files[name]} - {None}
    assert all(v.startswith("SYN") for v in vins)


def test_affected_vins_are_unique_per_campaign(files):
    pairs = [(ref_vin(r["vin"]), ref_campaign(r["campaign_id"]))
             for r in files[gen.AFFECTED_FILE]]
    good = [p for p in pairs if None not in p]
    assert len(good) == len(set(good))


def test_clean_dates_are_us_format_or_iso(files):
    raws = [r[col] for name, col in (("notices_sent.csv", "notice_date"),
                                     ("repairs_done.csv", "repair_date"))
            for r in files[name]]
    readable = [d for d in raws if ref_date(d)]
    assert all(len(d) == 10 for d in readable)


def test_tech_note_column_has_no_owner_data(files):
    notes = " ".join(r["tech_note"] for r in files[gen.REPAIRS_FILE])
    assert "@" not in notes


def test_quoted_tech_note_survives_csv_round_trip(full_dir):
    notes = {r["tech_note"] for r in read_csv(full_dir / gen.REPAIRS_FILE)}
    assert 'Customer reports "rattle" gone after fix.' in notes


def test_comma_in_tech_note_survives_csv_round_trip(full_dir):
    notes = {r["tech_note"] for r in read_csv(full_dir / gen.REPAIRS_FILE)}
    assert "Reflashed ECU software, test drive OK." in notes


# ---- as-of date limits and CLI -----------------------------------------
def test_as_of_too_early_is_refused():
    with pytest.raises(ValueError):
        gen.generate(seed=1, as_of=date(2026, 4, 30), n_vehicles=60)


def test_earliest_allowed_as_of_works():
    by_file = gen.generate(seed=1, as_of=date(2026, 5, 1), n_vehicles=60)
    assert by_file[gen.AFFECTED_FILE]


def test_cli_writes_all_outputs(tmp_path):
    gen.main(["--seed", "7", "--vehicles", "60", "--out", str(tmp_path)])
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(ALL_OUTPUTS)


def test_cli_creates_missing_output_folder(tmp_path):
    out = tmp_path / "a" / "b"
    gen.main(["--seed", "7", "--vehicles", "60", "--out", str(out)])
    assert (out / gen.AFFECTED_FILE).is_file()


def test_cli_reads_as_of_option(tmp_path):
    gen.main(["--seed", "7", "--vehicles", "60", "--as-of", "2026-09-30",
              "--out", str(tmp_path)])
    assert manifest(tmp_path)["as_of"] == "2026-09-30"


def test_cli_rejects_bad_as_of(tmp_path):
    with pytest.raises(SystemExit):
        gen.main(["--as-of", "11/01/2026", "--out", str(tmp_path)])
