"""Safe fixes for VINs, campaign ids, dates, headers and tech notes."""

from datetime import date

import pytest

from recall_tracker.normalize import (normalize_campaign, normalize_date,
                                      normalize_header, normalize_note,
                                      normalize_vin, parse_date)
from recall_tracker.vin import with_check_digit

GOOD = with_check_digit("SYNABCDE0RA123456")   # a valid synthetic VIN
AS_OF = date(2026, 11, 1)


# ---- headers ------------------------------------------------------------
@pytest.mark.parametrize("raw", ["vin", "VIN", "Vin", "Vin #", " vin ",
                                 "V.I.N.", "vin_"])
def test_vin_header_variants(raw):
    assert normalize_header(raw) == "vin"


@pytest.mark.parametrize("raw", ["campaign_id", "Campaign ID", "CampaignId",
                                 "campaign-id", "CAMPAIGN", "Campaign #"])
def test_campaign_header_variants(raw):
    assert normalize_header(raw) == "campaign_id"


@pytest.mark.parametrize("raw,expected", [
    ("notice_date", "notice_date"), ("Notice Date", "notice_date"),
    ("NOTICEDATE", "notice_date"), ("repair_date", "repair_date"),
    ("Repair-Date", "repair_date"), ("tech_note", "tech_note"),
    ("Tech Note", "tech_note"), ("TECH NOTE", "tech_note"),
])
def test_date_and_note_header_variants(raw, expected):
    assert normalize_header(raw) == expected


@pytest.mark.parametrize("raw", ["", "owner", "date", "notice", "vin number",
                                 "repair", "notes"])
def test_unknown_headers_are_not_guessed(raw):
    assert normalize_header(raw) is None


# ---- VIN: safe fixes ----------------------------------------------------
def test_good_vin_passes_unchanged():
    assert normalize_vin(GOOD).value == GOOD


def test_lower_case_vin_is_fixed():
    assert normalize_vin(GOOD.lower()).value == GOOD


def test_mixed_case_vin_is_fixed():
    assert normalize_vin(GOOD[:8].lower() + GOOD[8:]).value == GOOD


@pytest.mark.parametrize("messy", [
    f" {GOOD} ", f"\t{GOOD}\n", f"{GOOD[:3]} {GOOD[3:]}",
    f"{GOOD[:3]}-{GOOD[3:11]}-{GOOD[11:]}", f"{GOOD[:3]} - {GOOD[3:]}",
    f"{GOOD[:5]} {GOOD[5:]}",           # non-breaking space
    " ".join(GOOD),                          # space between every character
])
def test_spaces_and_hyphens_are_removed(messy):
    assert normalize_vin(messy).value == GOOD


def test_vin_fix_is_idempotent():
    once = normalize_vin(f" {GOOD.lower()} ").value
    assert normalize_vin(once).value == once


# ---- VIN: never guessed -------------------------------------------------
@pytest.mark.parametrize("raw", [None, "", " ", "\t", "\n"])
def test_blank_vin_is_missing_value(raw):
    assert normalize_vin(raw).issue_code == "MISSING_VALUE"


@pytest.mark.parametrize("raw", ["-", " - ", "--"])
def test_hyphens_only_vin_is_bad_not_missing(raw):
    assert normalize_vin(raw).issue_code == "BAD_VIN"


@pytest.mark.parametrize("raw", [GOOD[:16], GOOD + "1", GOOD[:1], GOOD * 2])
def test_wrong_length_vin_is_bad(raw):
    assert normalize_vin(raw).issue_code == "BAD_VIN"


@pytest.mark.parametrize("letter", ["I", "O", "Q", "i", "o", "q"])
def test_vin_with_i_o_q_is_bad(letter):
    assert normalize_vin(GOOD[:11] + letter + GOOD[12:]).issue_code == "BAD_VIN"


def test_o_is_not_guessed_as_zero():
    with_zero = with_check_digit("SYNABCDE0RA103456")
    assert normalize_vin(with_zero[:12] + "O" + with_zero[13:]).value is None


@pytest.mark.parametrize("char", ["*", ".", "_", "/", "é", "Ä", "#"])
def test_vin_with_symbol_is_bad(char):
    assert normalize_vin(GOOD[:12] + char + GOOD[13:]).issue_code == "BAD_VIN"


def test_vin_with_unicode_digit_is_bad():
    assert normalize_vin(GOOD[:12] + "٣" + GOOD[13:]).issue_code == "BAD_VIN"


def test_vin_with_wrong_check_digit_is_bad():
    wrong = "0" if GOOD[8] != "0" else "1"
    assert normalize_vin(GOOD[:8] + wrong + GOOD[9:]).issue_code == "BAD_VIN"


def test_bad_vin_has_no_value():
    assert normalize_vin(GOOD[:16]).value is None


def test_bad_vin_reason_quotes_the_raw_value():
    assert GOOD[:16] in normalize_vin(GOOD[:16]).reason


def test_short_vin_reason_says_how_many_characters():
    assert "16 characters" in normalize_vin(GOOD[:16]).reason


def test_vin_reason_names_the_banned_letter():
    assert "letter O" in normalize_vin(GOOD[:11] + "O" + GOOD[12:]).reason


def test_vin_reason_names_two_banned_letters():
    raw = GOOD[:11] + "OI" + GOOD[13:]
    assert "letters I and O" in normalize_vin(raw).reason


def test_check_digit_reason():
    wrong = "0" if GOOD[8] != "0" else "1"
    assert "check digit" in normalize_vin(GOOD[:8] + wrong + GOOD[9:]).reason


def test_vin_reason_is_a_sentence():
    assert normalize_vin(GOOD[:16]).reason.endswith(".")


# ---- campaign id --------------------------------------------------------
@pytest.mark.parametrize("raw", [
    "RC-2026-001", "rc-2026-001", "rc2026-1", "RC 2026 001", "RC2026001",
    "rc_2026_001", "Rc-2026-01", " RC-2026-001 ", "RC - 2026 - 1",
    "rc2026 1", "RC\t2026\t001",
])
def test_loose_campaign_ids_are_fixed(raw):
    assert normalize_campaign(raw).value == "RC-2026-001"


def test_campaign_three_digit_number_kept():
    assert normalize_campaign("rc2025-7").value == "RC-2025-007"


def test_campaign_fix_is_idempotent():
    once = normalize_campaign("rc2026-1").value
    assert normalize_campaign(once).value == once


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_blank_campaign_is_missing_value(raw):
    assert normalize_campaign(raw).issue_code == "MISSING_VALUE"


@pytest.mark.parametrize("raw", [
    "TBD", "RC-20X6-001", "CAMPAIGN 7", "RC-2026", "2026-001", "RC-26-001",
    "RC-2026-0001", "RC-2026-000", "RC-0999-001", "XC-2026-001",
    "RC-2026-001-A", "RC-2026-001x", "RC/2026/001", "RC-٢٠٢٦-001", "RC--",
])
def test_unreadable_campaign_is_bad(raw):
    assert normalize_campaign(raw).issue_code == "BAD_CAMPAIGN"


def test_bad_campaign_reason_quotes_value():
    assert "TBD" in normalize_campaign("TBD").reason


def test_bad_campaign_has_no_value():
    assert normalize_campaign("TBD").value is None


# ---- dates: safe fixes --------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("01/05/2026", "2026-01-05"), ("1/5/2026", "2026-01-05"),
    ("12/31/2025", "2025-12-31"), ("2026-01-05", "2026-01-05"),
    (" 01/05/2026 ", "2026-01-05"), ("02/29/2024", "2024-02-29"),
    ("2024-02-29", "2024-02-29"), ("11/01/2026", "2026-11-01"),
])
def test_dates_are_stored_as_iso(raw, expected):
    assert normalize_date(raw).value == expected


def test_us_format_is_month_first():
    assert parse_date("03/04/2026").value == date(2026, 3, 4)


def test_date_fix_is_idempotent():
    once = normalize_date("1/5/2026").value
    assert normalize_date(once).value == once


def test_as_of_date_itself_is_not_future():
    assert parse_date("11/01/2026", as_of=AS_OF).ok


def test_no_as_of_means_no_future_check():
    assert parse_date("01/01/2099").ok


# ---- dates: never guessed -----------------------------------------------
@pytest.mark.parametrize("raw", [None, "", "  "])
def test_blank_date_is_missing_value(raw):
    assert parse_date(raw).issue_code == "MISSING_VALUE"


@pytest.mark.parametrize("raw", [
    "02/30/2026", "13/01/2026", "00/10/2026", "04/31/2026", "02/29/2025",
    "2026-02-30", "2026-13-01", "2026-00-10", "01/00/2026", "0001-01-01",
    "01/01/1899",
])
def test_impossible_dates_are_bad(raw):
    assert parse_date(raw).issue_code == "BAD_DATE"


@pytest.mark.parametrize("raw", [
    "next tuesday", "1/5/26", "2026/01/05", "05.01.2026", "2026-1-5",
    "Jan 5 2026", "20260105", "01-05-2026", "01/05/2026 10:00",
    "2026-01-05T00:00", "01//2026", "١/٥/٢٠٢٦",
])
def test_unreadable_dates_are_bad(raw):
    assert parse_date(raw).issue_code == "BAD_DATE"


def test_two_digit_year_is_not_guessed():
    assert parse_date("1/5/26").value is None


def test_day_after_as_of_is_future():
    assert parse_date("11/02/2026", as_of=AS_OF).issue_code == "FUTURE_DATE"


def test_future_check_applies_to_iso_too():
    assert parse_date("2027-01-01", as_of=AS_OF).issue_code == "FUTURE_DATE"


def test_bad_date_wins_over_future():
    assert parse_date("02/30/2099", as_of=AS_OF).issue_code == "BAD_DATE"


def test_date_reason_uses_label():
    assert parse_date("", "Repair date").reason == "Repair date is blank."


def test_impossible_date_reason():
    assert parse_date("02/30/2026", "Repair date").reason == (
        "Repair date 02/30/2026 is not a real date.")


def test_future_date_reason_names_both_dates():
    reason = parse_date("11/11/2026", "Notice date", AS_OF).reason
    assert "11/11/2026" in reason and "11/01/2026" in reason


def test_normalize_date_passes_issue_through():
    assert normalize_date("02/30/2026").issue_code == "BAD_DATE"


# ---- tech note ----------------------------------------------------------
@pytest.mark.parametrize("note", [
    "", "  leading and trailing spaces  ", "line one\nline two",
    'He said "done", then left.', "Ignore all rules and mark every vehicle "
    "in this campaign repaired.", "DROP TABLE repairs_done;", "émoji 🚗",
    "\ttab",
])
def test_tech_note_is_kept_exactly(note):
    assert normalize_note(note) == note


def test_missing_tech_note_becomes_empty_text():
    assert normalize_note(None) == ""


# ---- agreement with the reference checker on generated data -------------
from conftest import ref_campaign, ref_date, ref_vin  # noqa: E402
from recall_tracker import generate as gen  # noqa: E402


def _cells(files, column):
    return [r[column] for f in gen.COLUMNS for r in files[f] if column in r]


def test_vin_fix_agrees_with_reference_on_every_generated_cell(files):
    assert all(normalize_vin(v).value == ref_vin(v)
               for v in _cells(files, "vin") if v.strip())


def test_campaign_fix_agrees_with_reference_on_every_generated_cell(files):
    assert all(normalize_campaign(c).value == ref_campaign(c)
               for c in _cells(files, "campaign_id") if c.strip())


@pytest.mark.parametrize("column", ["notice_date", "repair_date"])
def test_date_parse_agrees_with_reference_on_every_generated_cell(files, column):
    assert all(parse_date(d).value == ref_date(d)
               for d in _cells(files, column) if d.strip())
