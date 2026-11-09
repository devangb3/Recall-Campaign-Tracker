"""Planted business cases, planted data issues, safe mess, mess log."""

from collections import Counter
from datetime import date

import pytest

from conftest import (AS_OF, DATE_COL, find_issues, read_csv, ref_campaign,
                      ref_date, ref_vin, write_dataset)
from recall_tracker import generate as gen
from recall_tracker import plant

LIMIT = 60
ACTION_FOR = {
    "MISSING_VALUE": "quarantined", "BAD_VIN": "quarantined",
    "BAD_DATE": "quarantined", "BAD_CAMPAIGN": "quarantined",
    "FUTURE_DATE": "quarantined", "DUPLICATE_ROW": "dropped_duplicate",
    "DATE_CONFLICT": "kept", "REPAIR_BEFORE_NOTICE": "kept",
    "NOT_IN_AFFECTED": "kept",
}


def log_set(mess_log):
    return {(r["file"], int(r["row_num"]), r["issue_code"], r["action"])
            for r in mess_log}


def row_at(files, file, row_num):
    return files[file][int(row_num) - 2]


def log_rows(mess_log, code):
    return [r for r in mess_log if r["issue_code"] == code]


# ---- the mess log matches the files exactly ----------------------------
def test_no_planted_issue_is_missing_from_the_files(files, mess_log):
    found, _ = find_issues(files)
    assert log_set(mess_log) - found == set()


def test_no_unplanned_issue_is_in_the_files(files, mess_log):
    found, _ = find_issues(files)
    assert found - log_set(mess_log) == set()


@pytest.mark.parametrize("seed", range(10))
def test_mess_log_is_exact_for_many_seeds(tmp_path, seed):
    out = write_dataset(tmp_path, seed=seed, n_vehicles=80)
    files = {n: read_csv(out / n) for n in (*gen.COLUMNS, gen.MESS_LOG_FILE)}
    found, _ = find_issues(files)
    assert found == log_set(files[gen.MESS_LOG_FILE])


@pytest.mark.parametrize("as_of", [date(2026, 5, 1), date(2026, 8, 20),
                                   date(2027, 3, 1)])
def test_mess_log_is_exact_for_other_as_of_dates(tmp_path, as_of):
    out = write_dataset(tmp_path, seed=5, n_vehicles=80, as_of=as_of)
    files = {n: read_csv(out / n) for n in (*gen.COLUMNS, gen.MESS_LOG_FILE)}
    found, _ = find_issues(files, as_of)
    assert found == log_set(files[gen.MESS_LOG_FILE])


def test_one_log_entry_per_row(mess_log):
    keys = [(r["file"], r["row_num"]) for r in mess_log]
    assert len(keys) == len(set(keys))


# ---- mess log content ---------------------------------------------------
@pytest.mark.parametrize("code", sorted(ACTION_FOR))
def test_every_issue_code_is_planted(mess_log, code):
    assert log_rows(mess_log, code)


@pytest.mark.parametrize("code", sorted(set(ACTION_FOR) - {"DUPLICATE_ROW", "NOT_IN_AFFECTED"}))
def test_each_issue_code_planted_at_least_3_times(mess_log, code):
    assert len(log_rows(mess_log, code)) >= 3


def test_only_known_issue_codes(mess_log):
    assert {r["issue_code"] for r in mess_log} <= set(ACTION_FOR)


def test_action_matches_issue_code(mess_log):
    assert all(r["action"] == ACTION_FOR[r["issue_code"]] for r in mess_log)


def test_every_issue_has_a_reason(mess_log):
    assert all(r["reason"].strip() for r in mess_log)


def test_every_reason_is_one_sentence(mess_log):
    assert all(r["reason"].endswith(".") for r in mess_log)


def test_log_files_are_the_three_inputs(mess_log):
    assert {r["file"] for r in mess_log} <= set(gen.COLUMNS)


def test_log_row_numbers_are_inside_the_file(files, mess_log):
    assert all(2 <= int(r["row_num"]) <= len(files[r["file"]]) + 1
               for r in mess_log)


@pytest.mark.parametrize("file", [gen.AFFECTED_FILE, gen.NOTICES_FILE, gen.REPAIRS_FILE])
def test_each_dealership_file_has_planted_issues(mess_log, file):
    assert any(r["file"] == file for r in mess_log)


def test_log_is_sorted_by_file_then_row(mess_log):
    order = list(gen.COLUMNS)
    keys = [(order.index(r["file"]), int(r["row_num"])) for r in mess_log]
    assert keys == sorted(keys)


def test_log_column_is_a_real_column(mess_log):
    assert all(r["column"] in ("", *gen.COLUMNS[r["file"]]) for r in mess_log)


# ---- each planted issue really is what the log says --------------------
def test_missing_value_cells_are_blank(files, mess_log):
    assert all(row_at(files, r["file"], r["row_num"])[r["column"]] == ""
               for r in log_rows(mess_log, "MISSING_VALUE"))


def test_bad_vins_cannot_be_fixed(files, mess_log):
    assert all(ref_vin(row_at(files, r["file"], r["row_num"])["vin"]) is None
               for r in log_rows(mess_log, "BAD_VIN"))


def test_bad_vin_kinds_cover_length_letter_and_check_digit(files, mess_log):
    vins = [row_at(files, r["file"], r["row_num"])["vin"]
            for r in log_rows(mess_log, "BAD_VIN")]
    kinds = {"length" if len(v) != 17 else "letter" if "O" in v else "digit"
             for v in vins}
    assert kinds == {"length", "letter", "digit"}


def test_bad_dates_cannot_be_read(files, mess_log):
    assert all(ref_date(row_at(files, r["file"], r["row_num"])[r["column"]])
               is None for r in log_rows(mess_log, "BAD_DATE"))


def test_bad_dates_include_an_impossible_day(files, mess_log):
    raws = {row_at(files, r["file"], r["row_num"])[r["column"]]
            for r in log_rows(mess_log, "BAD_DATE")}
    assert "02/30/2026" in raws


def test_bad_dates_include_a_month_13(files, mess_log):
    raws = {row_at(files, r["file"], r["row_num"])[r["column"]]
            for r in log_rows(mess_log, "BAD_DATE")}
    assert "13/01/2026" in raws


def test_bad_campaigns_cannot_be_read(files, mess_log):
    assert all(ref_campaign(row_at(files, r["file"], r["row_num"])
                            ["campaign_id"]) is None
               for r in log_rows(mess_log, "BAD_CAMPAIGN"))


def test_future_dates_are_after_as_of(files, mess_log):
    assert all(ref_date(row_at(files, r["file"], r["row_num"])[r["column"]])
               > AS_OF for r in log_rows(mess_log, "FUTURE_DATE"))


def test_future_dates_planted_in_notices_and_repairs(mess_log):
    assert {r["file"] for r in log_rows(mess_log, "FUTURE_DATE")} == {
        gen.NOTICES_FILE, gen.REPAIRS_FILE}


def test_duplicate_equals_the_row_it_names(files, mess_log):
    for r in log_rows(mess_log, "DUPLICATE_ROW"):
        original = int(r["reason"].split("row ")[1].rstrip("."))
        assert (row_at(files, r["file"], original)
                == row_at(files, r["file"], r["row_num"]))


def test_duplicate_comes_after_its_original(mess_log):
    assert all(int(r["reason"].split("row ")[1].rstrip(".")) < int(r["row_num"])
               for r in log_rows(mess_log, "DUPLICATE_ROW"))


def test_duplicates_planted_in_notices_and_repairs(mess_log):
    assert {r["file"] for r in log_rows(mess_log, "DUPLICATE_ROW")} == {
        gen.NOTICES_FILE, gen.REPAIRS_FILE}


@pytest.mark.parametrize("file", [gen.NOTICES_FILE, gen.REPAIRS_FILE])
def test_date_conflicts_planted_in_each_dated_file(mess_log, file):
    assert any(r["file"] == file for r in log_rows(mess_log, "DATE_CONFLICT"))


def test_date_conflict_reason_names_both_dates(files, mess_log):
    for r in log_rows(mess_log, "DATE_CONFLICT"):
        later = row_at(files, r["file"], r["row_num"])[r["column"]]
        earlier_row = int(r["reason"].split("(row ")[1].split(")")[0])
        earlier = row_at(files, r["file"], earlier_row)[r["column"]]
        assert earlier in r["reason"] and later in r["reason"]


def test_date_conflict_rows_share_vin_and_campaign(files, mess_log):
    for r in log_rows(mess_log, "DATE_CONFLICT"):
        earlier_row = int(r["reason"].split("(row ")[1].split(")")[0])
        a = row_at(files, r["file"], earlier_row)
        b = row_at(files, r["file"], r["row_num"])
        assert (a["vin"], a["campaign_id"]) == (b["vin"], b["campaign_id"])


def test_date_conflict_dates_really_differ(files, mess_log):
    for r in log_rows(mess_log, "DATE_CONFLICT"):
        earlier_row = int(r["reason"].split("(row ")[1].split(")")[0])
        a = row_at(files, r["file"], earlier_row)[r["column"]]
        b = row_at(files, r["file"], r["row_num"])[r["column"]]
        assert ref_date(a) != ref_date(b)


def test_repair_before_notice_is_before_earliest_notice(files, mess_log):
    _, clean = find_issues(files)
    earliest = {}
    for v, c, d, _ in clean[gen.NOTICES_FILE]:
        earliest[(v, c)] = min(d, earliest.get((v, c), d))
    for r in log_rows(mess_log, "REPAIR_BEFORE_NOTICE"):
        row = row_at(files, r["file"], r["row_num"])
        pair = (ref_vin(row["vin"]), ref_campaign(row["campaign_id"]))
        assert ref_date(row["repair_date"]) < earliest[pair]


@pytest.mark.parametrize("file", [gen.NOTICES_FILE, gen.REPAIRS_FILE])
def test_not_in_affected_planted_for_notices_and_repairs(mess_log, file):
    assert any(r["file"] == file for r in log_rows(mess_log, "NOT_IN_AFFECTED"))


def test_not_in_affected_vin_is_absent_from_affected_file(files, mess_log):
    affected = {ref_vin(r["vin"]) for r in files[gen.AFFECTED_FILE]}
    assert all(ref_vin(row_at(files, r["file"], r["row_num"])["vin"])
               not in affected for r in log_rows(mess_log, "NOT_IN_AFFECTED"))


def test_reasons_quote_the_bad_value(files, mess_log):
    quoted = ("BAD_VIN", "BAD_DATE", "BAD_CAMPAIGN", "FUTURE_DATE")
    for r in mess_log:
        if r["issue_code"] in quoted:
            raw = row_at(files, r["file"], r["row_num"])[r["column"]]
            assert raw in r["reason"]


# ---- business cases (not data issues) -----------------------------------
def pairs(clean, file):
    out = {}
    for v, c, d, _ in clean[file]:
        out[(v, c)] = min(d, out.get((v, c), d)) if d else None
    return out


@pytest.fixture(scope="module")
def cases(files):
    _, clean = find_issues(files)
    affected = set(pairs(clean, gen.AFFECTED_FILE))
    notices = pairs(clean, gen.NOTICES_FILE)
    repairs = pairs(clean, gen.REPAIRS_FILE)

    def day(start, end):
        return (end - start).days + 1  # inclusive day count

    return {
        "not_notified": [p for p in affected if p not in notices],
        "repair_day_60": [p for p in affected if p in notices and p in repairs
                          and notices[p] == date(2026, 1, 1)
                          and repairs[p] == date(2026, 3, 1)],
        "repair_day_61": [p for p in affected if p in notices and p in repairs
                          and notices[p] == date(2026, 1, 1)
                          and repairs[p] == date(2026, 3, 2)],
        "no_repair_past_limit": [p for p in affected if p in notices
                                 and p not in repairs
                                 and day(notices[p], AS_OF) > LIMIT],
        "no_repair_within_limit": [p for p in affected if p in notices
                                   and p not in repairs
                                   and day(notices[p], AS_OF) <= LIMIT],
        "repair_without_notice": [p for p in affected if p in repairs
                                  and p not in notices],
    }


@pytest.mark.parametrize("case", ["not_notified", "repair_day_60",
                                  "repair_day_61", "no_repair_past_limit",
                                  "no_repair_within_limit",
                                  "repair_without_notice"])
def test_business_case_appears_at_least_3_times(cases, case):
    assert len(cases[case]) >= 3


def test_day_60_example_is_60_days_inclusive():
    assert (plant.DAY60_REPAIR - plant.DAY60_NOTICE).days + 1 == 60


def test_day_61_example_is_61_days_inclusive():
    assert (plant.DAY61_REPAIR - plant.DAY60_NOTICE).days + 1 == 61


def test_only_unaffected_repair_case_has_a_data_issue(data_dir, mess_log):
    by_file = gen.generate(**({"seed": 7, "n_vehicles": 60}
                              if "seed7" in str(data_dir)
                              else {"seed": 42, "n_vehicles": 500}),
                           as_of=AS_OF)
    case_rows = {(f, n) for f, rows in by_file.items()
                 for n, r in enumerate(rows, start=2)
                 if r.tag.startswith("case:")}
    logged = {(r["file"], int(r["row_num"])) for r in mess_log}
    outside_repairs = {(f, n) for f, rows in by_file.items()
                       for n, r in enumerate(rows, start=2)
                       if r.tag == "case:unaffected_repair"}
    assert len(outside_repairs) == 1
    assert case_rows & logged == outside_repairs


# ---- hostile tech note --------------------------------------------------
def test_hostile_note_appears_exactly_once(files):
    notes = [r["tech_note"] for r in files[gen.REPAIRS_FILE]]
    assert notes.count(plant.HOSTILE_NOTE) == 1


def test_hostile_note_row_is_otherwise_clean(files, mess_log):
    num = next(n for n, r in enumerate(files[gen.REPAIRS_FILE], start=2)
               if r["tech_note"] == plant.HOSTILE_NOTE)
    assert (gen.REPAIRS_FILE, str(num)) not in {
        (r["file"], r["row_num"]) for r in mess_log}


def test_hostile_note_vehicle_is_affected_and_notified(files):
    row = next(r for r in files[gen.REPAIRS_FILE]
               if r["tech_note"] == plant.HOSTILE_NOTE)
    _, clean = find_issues(files)
    pair = (row["vin"], row["campaign_id"])
    assert pair in pairs(clean, gen.AFFECTED_FILE) and pair in pairs(
        clean, gen.NOTICES_FILE)


# ---- safe mess ----------------------------------------------------------
def all_vins(files):
    return [r["vin"] for f, cols in gen.COLUMNS.items() if "vin" in cols for r in files[f]]


def test_safe_mess_lower_case_vin_present(full_dir):
    files = {f: read_csv(full_dir / f) for f in gen.COLUMNS}
    assert any(v.islower() and ref_vin(v) for v in all_vins(files))


def test_safe_mess_vin_with_spaces_present(full_dir):
    files = {f: read_csv(full_dir / f) for f in gen.COLUMNS}
    assert any(" " in v and ref_vin(v) for v in all_vins(files))


def test_safe_mess_vin_with_hyphens_present(full_dir):
    files = {f: read_csv(full_dir / f) for f in gen.COLUMNS}
    assert any("-" in v and ref_vin(v) for v in all_vins(files))


def test_safe_mess_loose_campaign_present(full_dir):
    raws = [r["campaign_id"] for f, cols in gen.COLUMNS.items() if "campaign_id" in cols
            for r in read_csv(full_dir / f)]
    assert any(ref_campaign(c) and c not in gen.CAMPAIGNS for c in raws)


@pytest.mark.parametrize("file", [gen.NOTICES_FILE, gen.REPAIRS_FILE])
def test_safe_mess_iso_date_present(full_dir, file):
    raws = [r[DATE_COL[file]] for r in read_csv(full_dir / file)]
    assert any("-" in d and ref_date(d) for d in raws)


def test_safe_mess_only_touches_background_rows():
    by_file = gen.generate(seed=42, as_of=AS_OF, n_vehicles=500)
    planted = [r for rows in by_file.values() for r in rows
               if r.tag.startswith(("case:", "issue_carrier"))]
    assert all(r.values["campaign_id"] in gen.CAMPAIGNS for r in planted)


def test_safe_mess_rows_are_never_flagged(files, mess_log):
    logged = {(r["file"], int(r["row_num"])) for r in mess_log}
    messy = {(f, n) for f, cols in gen.COLUMNS.items() if "campaign_id" in cols
             for n, r in enumerate(files[f], start=2)
             if r["campaign_id"] not in gen.CAMPAIGNS
             and ref_campaign(r["campaign_id"])}
    assert messy & logged == set()


# ---- planting helpers ---------------------------------------------------
def test_order_rows_keeps_duplicate_after_original():
    import random
    from recall_tracker.generate import Row
    link = ("dup", gen.NOTICES_FILE, "X")
    rows = [Row(gen.NOTICES_FILE, {"n": i}) for i in range(20)]
    rows += [Row(gen.NOTICES_FILE, {"n": "a"}, link=link),
             Row(gen.NOTICES_FILE, {"n": "b"}, link=link)]
    for seed in range(50):
        ordered = plant.order_rows(random.Random(seed), list(rows))
        idx = [i for i, r in enumerate(ordered) if r.link == link]
        assert idx[0] < idx[1]


def test_order_rows_keeps_every_row():
    import random
    from recall_tracker.generate import Row
    rows = [Row(gen.NOTICES_FILE, {"n": i}) for i in range(30)]
    assert len(plant.order_rows(random.Random(1), list(rows))) == 30


def test_iso_safe_mess_keeps_the_same_date():
    import random
    from recall_tracker.generate import Row
    rows = [Row(gen.NOTICES_FILE, {"vin": "SYN", "campaign_id": "RC-2026-001",
                                   "notice_date": "07/04/2026"})
            for _ in range(200)]
    plant.apply_safe_mess(random.Random(0), rows)
    dates = {r.values["notice_date"] for r in rows}
    assert dates == {"07/04/2026", "2026-07-04"}


def test_no_notice_before_the_first_campaign_window(full_dir):
    raws = [r["notice_date"] for r in read_csv(full_dir / gen.NOTICES_FILE)]
    oldest = min(d for d in map(ref_date, raws) if d)
    assert oldest >= min(start for start, _ in gen.CAMPAIGNS.values())


def test_no_repair_before_the_first_campaign_window(full_dir):
    raws = [r["repair_date"] for r in read_csv(full_dir / gen.REPAIRS_FILE)]
    oldest = min(d for d in map(ref_date, raws) if d)
    assert oldest >= min(start for start, _ in gen.CAMPAIGNS.values())
