"""The affected list is affected_vehicles.csv, shared by both checks."""

import csv
from pathlib import Path

import pytest

from recall_tracker.affected import (
    AffectedList, AffectedListError, load_affected_list,
    vehicles_for_notification_check, vehicles_for_repair_check)
from recall_tracker.contract import AffectedVehicle

VIN_A = "SYN12345678901234"
VIN_B = "SYN12345678901235"
CAMP_A = "RC-2026-001"
CAMP_B = "RC-2026-002"


def write_affected(folder: Path, rows: list[dict[str, str]],
                   columns: list[str] | None = None) -> Path:
    path = folder / "affected_vehicles.csv"
    names = columns if columns is not None else ["vin", "campaign_id"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, names, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_the_list_is_the_vin_and_campaign_pairs_in_file_order(tmp_path):
    path = write_affected(tmp_path, [
        {"vin": VIN_A, "campaign_id": CAMP_B},
        {"vin": VIN_A, "campaign_id": CAMP_A},
        {"vin": VIN_B, "campaign_id": CAMP_A},
    ])
    affected = load_affected_list(path)
    assert [(row.vin, row.campaign_id) for row in affected] == [
        (VIN_A, CAMP_B),
        (VIN_A, CAMP_A),
        (VIN_B, CAMP_A),
    ]


def test_one_vin_in_two_campaigns_is_two_pairs(tmp_path):
    path = write_affected(tmp_path, [
        {"vin": VIN_A, "campaign_id": CAMP_A},
        {"vin": VIN_A, "campaign_id": CAMP_B},
    ])
    assert len(load_affected_list(path)) == 2


def test_a_repeated_pair_is_one_vehicle_campaign(tmp_path):
    path = write_affected(tmp_path, [
        {"vin": VIN_A, "campaign_id": CAMP_A},
        {"vin": VIN_B, "campaign_id": CAMP_A},
        {"vin": VIN_A, "campaign_id": CAMP_A},
    ])
    affected = load_affected_list(path)
    assert [(row.vin, row.campaign_id) for row in affected] == [
        (VIN_A, CAMP_A),
        (VIN_B, CAMP_A),
    ]


def test_model_and_build_date_do_not_decide_who_is_affected(tmp_path):
    path = write_affected(tmp_path, [
        {"vin": VIN_A, "campaign_id": CAMP_A,
         "model": "Harbor", "build_date": "2010-01-01"},
        {"vin": VIN_B, "campaign_id": CAMP_A,
         "model": "Summit", "build_date": "2030-06-30"},
    ], ["vin", "campaign_id", "model", "build_date"])
    assert [(row.vin, row.campaign_id) for row in load_affected_list(path)] == [
        (VIN_A, CAMP_A),
        (VIN_B, CAMP_A),
    ]


def test_scrap_theft_export_and_resale_do_not_remove_a_vehicle(tmp_path):
    path = write_affected(tmp_path, [
        {"vin": VIN_A, "campaign_id": CAMP_A, "scrap": "yes", "theft": "yes",
         "export": "yes", "resale": "yes"},
        {"vin": VIN_B, "campaign_id": CAMP_B, "scrap": "no", "theft": "no",
         "export": "no", "resale": "no"},
    ], ["vin", "campaign_id", "scrap", "theft", "export", "resale"])
    assert [(row.vin, row.campaign_id) for row in load_affected_list(path)] == [
        (VIN_A, CAMP_A),
        (VIN_B, CAMP_B),
    ]


def test_another_file_in_the_folder_is_not_consulted(tmp_path):
    path = write_affected(tmp_path, [{"vin": VIN_A, "campaign_id": CAMP_A}])
    (tmp_path / "notices_sent.csv").write_text(
        "vin,campaign_id,notice_date\n"
        f"{VIN_B},{CAMP_A},01/01/2026\n",
        encoding="utf-8")
    (tmp_path / "central_body.csv").write_text(
        f"vin,status\n{VIN_B},current\n", encoding="utf-8")
    affected = load_affected_list(path)
    assert [(row.vin, row.campaign_id) for row in affected] == [
        (VIN_A, CAMP_A)]


def test_a_campaign_id_is_kept_as_written(tmp_path):
    path = write_affected(tmp_path, [
        {"vin": VIN_A, "campaign_id": "rc2026-1"},
    ])
    affected = load_affected_list(path)
    assert affected.pairs[0].campaign_id == "rc2026-1"


def test_header_only_file_is_an_empty_list(tmp_path):
    path = write_affected(tmp_path, [])
    assert load_affected_list(path).pairs == ()


def test_missing_file_names_the_problem(tmp_path):
    with pytest.raises(AffectedListError, match="affected_vehicles.csv is missing"):
        load_affected_list(tmp_path / "affected_vehicles.csv")


def test_a_folder_is_not_a_source_of_vehicles(tmp_path):
    with pytest.raises(AffectedListError, match="not a folder"):
        load_affected_list(tmp_path)


def test_another_csv_is_not_the_affected_list(tmp_path):
    path = tmp_path / "notices_sent.csv"
    path.write_text(
        f"vin,campaign_id,notice_date\n{VIN_A},{CAMP_A},01/01/2026\n",
        encoding="utf-8")
    with pytest.raises(AffectedListError, match="not the affected-vehicle list"):
        load_affected_list(path)


def test_a_missing_column_names_the_column(tmp_path):
    path = write_affected(
        tmp_path, [{"vin": VIN_A}], columns=["vin"])
    with pytest.raises(AffectedListError, match="missing required column campaign_id"):
        load_affected_list(path)


def test_a_blank_campaign_is_not_a_pair(tmp_path):
    path = write_affected(tmp_path, [{"vin": VIN_A, "campaign_id": ""}])
    with pytest.raises(AffectedListError, match="row 2"):
        load_affected_list(path)


def test_a_blank_vin_is_not_a_pair(tmp_path):
    path = write_affected(tmp_path, [{"vin": "", "campaign_id": CAMP_A}])
    with pytest.raises(AffectedListError, match="row 2"):
        load_affected_list(path)


def test_both_checks_use_the_same_list(tmp_path):
    path = write_affected(tmp_path, [
        {"vin": VIN_A, "campaign_id": CAMP_A},
        {"vin": VIN_B, "campaign_id": CAMP_B},
    ])
    affected = load_affected_list(path)
    assert vehicles_for_notification_check(affected) is affected.pairs
    assert vehicles_for_repair_check(affected) is affected.pairs


def test_a_check_does_not_build_its_own_list_from_rows():
    rows = [AffectedVehicle(VIN_A, CAMP_A)]
    with pytest.raises(AffectedListError, match="does not build its own"):
        vehicles_for_notification_check(rows)
    with pytest.raises(AffectedListError, match="does not build its own"):
        vehicles_for_repair_check(rows)


def test_the_list_keeps_one_pair_when_built_from_records():
    repeated = (
        AffectedVehicle(VIN_A, CAMP_A),
        AffectedVehicle(VIN_A, CAMP_A),
        AffectedVehicle(VIN_B, CAMP_B),
    )
    affected = AffectedList(repeated)
    assert affected.pairs == (
        AffectedVehicle(VIN_A, CAMP_A),
        AffectedVehicle(VIN_B, CAMP_B),
    )
