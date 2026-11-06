"""Business findings use the shared list and keep bad data separate."""

from dataclasses import asdict
from datetime import date, datetime

import pytest

from recall_tracker.affected import AffectedList
from recall_tracker.checks import check_notifications, check_repairs
from recall_tracker.contract import (
    AffectedVehicle, ContractError, DataIssue, Facts, FindingKind, NoticeSent,
    RepairDone, build_report)

VIN = "SYN12345678901234"
OTHER_VIN = "SYN12345678901235"
CAMPAIGN = "RC-2026-001"
OTHER_CAMPAIGN = "RC-2026-002"
NOTICE = date(2026, 1, 1)
DAY_60 = date(2026, 3, 1)
DAY_61 = date(2026, 3, 2)
CHECK = date(2026, 11, 1)


def facts(notices=(), repairs=(), *, vin=VIN, campaign=CAMPAIGN,
          affected=True):
    return Facts(
        vin, campaign,
        (AffectedVehicle(vin, campaign),) if affected else (),
        tuple(NoticeSent(vin, campaign, day) for day in notices),
        tuple(RepairDone(vin, campaign, day) for day in repairs))


def affected_list(*rows):
    return AffectedList(tuple(row.affected[0] for row in rows))


def bad_notice(*, file="notices_sent.csv", vin=VIN, campaign=CAMPAIGN):
    return DataIssue(
        file, 2, "BAD_DATE", "quarantined",
        "Notice date 02/30/2026 is not a real date.",
        '{"notice_date":"02/30/2026"}', vin, campaign)


def test_missing_notice_is_a_notification_finding_without_a_deadline():
    row = facts()
    result = check_notifications(affected_list(row), (row,), NOTICE)
    assert len(result) == 1
    assert result[0].kind is FindingKind.NOTIFICATION
    assert result[0].facts is row
    assert result[0].check_date == NOTICE
    assert "No notice" in result[0].reason
    assert check_repairs(affected_list(row), (row,), CHECK) == ()


def test_repair_without_notice_is_still_only_a_notification_finding():
    row = facts(repairs=(DAY_60,))
    assert len(check_notifications(affected_list(row), (row,), CHECK)) == 1
    assert check_repairs(affected_list(row), (row,), CHECK) == ()


@pytest.mark.parametrize("notices", [(NOTICE,), (DAY_61, NOTICE)])
def test_any_accepted_notice_means_notified_even_with_conflicting_dates(notices):
    row = facts(notices=notices)
    assert check_notifications(affected_list(row), (row,), CHECK) == ()


def test_quarantined_notice_is_a_data_issue_not_a_missing_notice():
    row = facts()
    issues = (bad_notice(),)
    result = check_notifications(
        affected_list(row), (row,), CHECK, data_issues=issues)
    assert result == ()
    assert check_repairs(affected_list(row), (row,), CHECK) == ()
    report = build_report(CHECK, (row,), result, data_issues=issues)
    assert report.vehicles[0].in_notices
    assert report.vehicles[0].notice_date_used is None
    assert report.data_issues == issues


def test_future_notice_is_also_presence_evidence_without_a_usable_clock():
    row = facts()
    issue = DataIssue(
        "notices_sent.csv", 2, "FUTURE_DATE", "quarantined",
        "Notice date 12/01/2026 is after the as-of date 11/01/2026.",
        '{"notice_date":"12/01/2026"}', VIN, CAMPAIGN)
    result = check_notifications(
        affected_list(row), (row,), CHECK, data_issues=(issue,))
    assert result == ()
    assert check_repairs(affected_list(row), (row,), CHECK) == ()
    report = build_report(CHECK, (row,), result, data_issues=(issue,))
    assert report.vehicles[0].in_notices
    assert report.vehicles[0].inclusive_days is None


def test_bad_notice_does_not_hide_overdue_repair_after_another_valid_notice():
    row = facts(notices=(NOTICE,))
    issues = (bad_notice(),)
    assert check_notifications(
        affected_list(row), (row,), CHECK, data_issues=issues) == ()
    result = check_repairs(affected_list(row), (row,), DAY_61)
    assert len(result) == 1
    report = build_report(DAY_61, (row,), result, data_issues=issues)
    assert report.vehicles[0].notice_date_used == NOTICE
    assert report.vehicles[0].inclusive_days == 61


@pytest.mark.parametrize("issue", [
    bad_notice(vin=OTHER_VIN),
    bad_notice(campaign=OTHER_CAMPAIGN),
    bad_notice(file="repairs_done.csv"),
    bad_notice(vin=None),
    bad_notice(campaign=None),
])
def test_unrelated_or_unidentifiable_bad_rows_do_not_suppress_missing_notice(issue):
    row = facts()
    assert len(check_notifications(
        affected_list(row), (row,), CHECK, data_issues=(issue,))) == 1


@pytest.mark.parametrize("repairs,check_date,limit,flagged", [
    ((DAY_60,), CHECK, 60, False),
    ((DAY_61,), CHECK, 60, True),
    ((), DAY_60, 60, False),
    ((), DAY_61, 60, True),
    ((DAY_61,), CHECK, 61, False),
    ((), DAY_61, 61, False),
    ((NOTICE,), NOTICE, 1, False),
    ((), date(2026, 1, 2), 1, True),
])
def test_inclusive_boundary_for_repairs_and_unrepaired_vehicles(
        repairs, check_date, limit, flagged):
    row = facts(notices=(NOTICE,), repairs=repairs)
    result = check_repairs(
        affected_list(row), (row,), check_date, day_limit=limit)
    assert bool(result) is flagged
    if flagged:
        assert len(result) == 1
        assert result[0].kind is FindingKind.REPAIR
        assert result[0].facts is row
        assert str(limit) in result[0].reason
    build_report(check_date, (row,), result, day_limit=limit)


def test_default_repair_limit_is_60_and_reason_names_the_used_dates_and_count():
    row = facts(notices=(NOTICE,), repairs=(DAY_61,))
    result = check_repairs(affected_list(row), (row,), CHECK)
    assert len(result) == 1
    assert "2026-01-01" in result[0].reason
    assert "2026-03-02" in result[0].reason
    assert "61 inclusive days" in result[0].reason
    assert "60-day limit" in result[0].reason


def test_missing_repair_reason_uses_check_date_and_inclusive_count():
    row = facts(notices=(NOTICE,))
    result = check_repairs(affected_list(row), (row,), DAY_61)
    assert "No usable repair" in result[0].reason
    assert "2026-03-02" in result[0].reason
    assert "day 61" in result[0].reason


def test_later_notice_does_not_restart_the_repair_clock():
    row = facts(notices=(date(2026, 2, 1), NOTICE), repairs=(DAY_61,))
    assert len(check_repairs(affected_list(row), (row,), CHECK)) == 1


def test_earlier_usable_repair_closes_the_clock_despite_a_late_row():
    row = facts(notices=(NOTICE,), repairs=(DAY_61, DAY_60))
    assert check_repairs(affected_list(row), (row,), CHECK) == ()


def test_repair_before_notice_does_not_close_the_window():
    row = facts(notices=(NOTICE,), repairs=(date(2025, 12, 31),))
    assert check_repairs(affected_list(row), (row,), DAY_60) == ()
    result = check_repairs(affected_list(row), (row,), DAY_61)
    assert len(result) == 1
    assert "No usable repair" in result[0].reason


def test_bad_early_repair_does_not_hide_a_later_usable_repair():
    row = facts(notices=(NOTICE,), repairs=(date(2025, 12, 31), DAY_60))
    assert check_repairs(affected_list(row), (row,), CHECK) == ()


def test_both_checks_follow_the_same_shared_list_including_campaign_keys():
    missing = facts()
    late = facts(campaign=OTHER_CAMPAIGN, notices=(NOTICE,), repairs=(DAY_61,))
    other_missing = facts(vin=OTHER_VIN)
    extra = facts(vin="SYN12345678901236", notices=(NOTICE,), affected=False)
    shared = affected_list(other_missing, late, missing, missing)
    supplied = (extra, missing, late, other_missing)
    notified = check_notifications(shared, supplied, CHECK)
    repairs = check_repairs(shared, supplied, CHECK)
    assert [(r.vin, r.campaign_id) for r in notified] == [
        (OTHER_VIN, CAMPAIGN), (VIN, CAMPAIGN)]
    assert [(r.vin, r.campaign_id) for r in repairs] == [(VIN, OTHER_CAMPAIGN)]
    assert len(shared) == 3


def test_nonaffected_records_do_not_generate_business_findings():
    row = facts(notices=(NOTICE,), repairs=(DAY_61,), affected=False)
    shared = AffectedList(())
    assert check_notifications(shared, (row,), CHECK) == ()
    assert check_repairs(shared, (row,), CHECK) == ()


@pytest.mark.parametrize("check", [check_notifications, check_repairs])
def test_checks_reject_a_raw_pair_list_instead_of_building_their_own(check):
    row = facts()
    with pytest.raises(ContractError, match="shared AffectedList"):
        check(row.affected, (row,), CHECK)


@pytest.mark.parametrize("check", [check_notifications, check_repairs])
def test_checks_reject_missing_facts_for_a_shared_pair(check):
    row = facts()
    with pytest.raises(ContractError, match="missing affected facts"):
        check(affected_list(row), (), CHECK)


@pytest.mark.parametrize("check", [check_notifications, check_repairs])
def test_checks_reject_facts_without_the_accepted_affected_row(check):
    row = facts()
    unrelated = facts(notices=(NOTICE,), affected=False)
    with pytest.raises(ContractError, match="missing affected facts"):
        check(affected_list(row), (unrelated,), CHECK)


@pytest.mark.parametrize("check", [check_notifications, check_repairs])
def test_checks_reject_duplicate_facts_for_an_affected_pair(check):
    row = facts()
    with pytest.raises(ContractError, match="duplicate facts"):
        check(affected_list(row), (row, row), CHECK)


@pytest.mark.parametrize("limit", [0, -1, True, 60.0, "60", None])
def test_invalid_limits_are_rejected_even_for_an_empty_affected_list(limit):
    with pytest.raises(ContractError, match="day limit"):
        check_repairs(AffectedList(()), (), CHECK, day_limit=limit)


@pytest.mark.parametrize("check", [check_notifications, check_repairs])
def test_checks_reject_a_datetime_check_date(check):
    with pytest.raises(ContractError, match="calendar date"):
        check(AffectedList(()), (), datetime(2026, 11, 1))


def test_checks_do_not_mutate_their_shared_list_or_source_facts():
    row = facts(notices=(date(2026, 2, 1), NOTICE), repairs=(DAY_61,))
    shared = affected_list(row)
    original = asdict(row)
    pairs = shared.pairs
    check_notifications(shared, (row,), CHECK)
    check_repairs(shared, (row,), CHECK)
    assert asdict(row) == original
    assert shared.pairs is pairs
    assert row.notices[0].notice_date == date(2026, 2, 1)


def test_tech_notes_are_not_an_input_to_the_business_checks():
    # RepairDone deliberately has no tech_note field. The hostile note stored
    # by ingest cannot turn this repair for one pair into a campaign-wide fix.
    repaired = facts(notices=(NOTICE,), repairs=(DAY_60,))
    unrepaired = facts(vin=OTHER_VIN, notices=(NOTICE,))
    shared = affected_list(repaired, unrepaired)
    result = check_repairs(shared, (repaired, unrepaired), CHECK)
    assert [r.vin for r in result] == [OTHER_VIN]
    assert "tech_note" not in asdict(repaired.repairs[0])
