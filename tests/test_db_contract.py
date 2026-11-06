"""REC-29: the recall.db contract that part 2 and part 3 read.

Runs on the seed 7 and seed 42 fixtures. If a column is renamed, or a bad
value slips into a clean table, these tests fail in CI.
"""

import re
import shutil
import sqlite3

import pytest

from conftest import AS_OF
from recall_tracker.ingest import ACTION_FOR, FILES, load

COLUMNS = {
    "ingests": ["ingest_id", "started_at", "finished_at", "as_of_date",
                "status", "files", "row_counts"],
    "affected_vehicles": ["ingest_id", "src_file", "src_row", "vin",
                          "campaign_id"],
    "notices_sent": ["ingest_id", "src_file", "src_row", "vin", "campaign_id",
                     "notice_date"],
    "repairs_done": ["ingest_id", "src_file", "src_row", "vin", "campaign_id",
                     "repair_date", "tech_note"],
    "data_issues": ["issue_id", "ingest_id", "file", "src_row", "column",
                    "raw_value", "issue_code", "action", "reason", "vin",
                    "campaign_id", "raw_row"],
    "quarantine": ["ingest_id", "file", "src_row", "raw_json", "issue_codes"],
}
CURRENT = ["affected_vehicles", "notices_sent", "repairs_done", "data_issues",
           "quarantine"]
VIN = re.compile(r"[A-HJ-NPR-Z0-9]{17}")
CAMPAIGN = re.compile(r"RC-[0-9]{4}-[0-9]{3}")
ISO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
NO_OWNER_TABLES = ["campaigns", "owners", "registrations", "sales", "mailings",
                   "dealers", "owner_history"]


@pytest.fixture(scope="module")
def db(data_dir, tmp_path_factory):
    raw = tmp_path_factory.mktemp("contract")
    for name in FILES:
        shutil.copy(data_dir / name, raw / name)
    path = raw / "recall.db"
    load(raw, path, AS_OF)
    con = sqlite3.connect(path)
    yield con
    con.close()


def values(db, sql):
    return [row[0] for row in db.execute(sql)]


@pytest.mark.parametrize("table", list(COLUMNS))
def test_table_columns(db, table):
    assert [r[1] for r in db.execute(f"PRAGMA table_info({table})")] == \
        COLUMNS[table]


@pytest.mark.parametrize("table", CURRENT)
def test_current_view_has_table_columns(db, table):
    assert [r[1] for r in db.execute(f"PRAGMA table_info(cur_{table})")] == \
        COLUMNS[table]


@pytest.mark.parametrize("table", NO_OWNER_TABLES)
def test_out_of_scope_tables_do_not_exist(db, table):
    assert not values(db, "SELECT name FROM sqlite_master WHERE name="
                          f"'{table}'")


@pytest.mark.parametrize("table", ["affected_vehicles", "notices_sent",
                                   "repairs_done"])
def test_vins_are_17_upper_case_characters(db, table):
    assert all(VIN.fullmatch(v) for v in values(db, f"SELECT vin FROM {table}"))


@pytest.mark.parametrize("table", ["affected_vehicles", "notices_sent",
                                   "repairs_done"])
def test_campaign_ids_are_normalized(db, table):
    assert all(CAMPAIGN.fullmatch(c)
               for c in values(db, f"SELECT campaign_id FROM {table}"))


@pytest.mark.parametrize("table,col", [("notices_sent", "notice_date"),
                                       ("repairs_done", "repair_date"),
                                       ("ingests", "as_of_date")])
def test_dates_are_iso(db, table, col):
    assert all(ISO.fullmatch(d) for d in values(db, f"SELECT {col} FROM {table}"))


@pytest.mark.parametrize("table,col", [("notices_sent", "notice_date"),
                                       ("repairs_done", "repair_date")])
def test_no_clean_date_after_as_of(db, table, col):
    assert max(values(db, f"SELECT {col} FROM {table}")) <= AS_OF.isoformat()


def test_issue_codes_are_rec18_codes(db):
    assert set(values(db, "SELECT issue_code FROM data_issues")) <= set(
        ACTION_FOR)


def test_actions_match_issue_codes(db):
    assert all(ACTION_FOR[c] == a for c, a in db.execute(
        "SELECT issue_code, action FROM data_issues"))


def test_issue_vins_are_clean_when_present(db):
    assert all(VIN.fullmatch(v) for v in values(
        db, "SELECT vin FROM data_issues WHERE vin IS NOT NULL"))


def test_src_rows_start_at_2(db):
    assert min(values(db, "SELECT src_row FROM data_issues")) >= 2


def test_affected_pairs_unique_per_ingest(db):
    assert values(db, "SELECT COUNT(*) FROM (SELECT ingest_id, vin, "
                      "campaign_id FROM affected_vehicles GROUP BY 1, 2, 3 "
                      "HAVING COUNT(*) > 1)") == [0]


@pytest.mark.parametrize("table,col", [("notices_sent", "notice_date"),
                                       ("repairs_done", "repair_date")])
def test_no_two_rows_share_vehicle_campaign_and_date(db, table, col):
    assert values(db, f"SELECT COUNT(*) FROM (SELECT vin, campaign_id, {col} "
                      f"FROM {table} GROUP BY 1, 2, 3 HAVING COUNT(*) > 1)") \
        == [0]
