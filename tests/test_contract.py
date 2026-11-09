"""The check and report contract: shared records, day count, payload."""

import json
from datetime import date, datetime

import pytest

from recall_tracker.contract import (
    DEFAULT_DAY_LIMIT, AffectedVehicle, CheckHistoryRow, ContractError,
    DataIssue, Decision, DecisionStatus, Facts, Finding, FindingKind,
    NoticeSent, RepairDone, ReportPayload, append_decision, build_report,
    current_decision, decisions_for, history_row, inclusive_day_count,
    is_on_time, notice_date_used, repair_date_used, repair_outside_limit,
    to_dict)

VIN = "SYN12345678901234"
CID = "RC-2026-001"
NOTICE = date(2026, 1, 1)
DAY_60 = date(2026, 3, 1)
DAY_61 = date(2026, 3, 2)
CHECK = date(2026, 11, 1)

EXCLUDED = {
    "current_owner", "owner", "central_body", "central_body_status",
    "returned_mail", "returned", "resale", "priority", "rank", "severity",
    "tech_note", "nhtsa",
}


def facts(notices=(), repairs=(), affected=True, vin=VIN, cid=CID):
    return Facts(
        vin,
        cid,
        (AffectedVehicle(vin, cid),) if affected else (),
        tuple(NoticeSent(vin, cid, day) for day in notices),
        tuple(RepairDone(vin, cid, day) for day in repairs),
    )


def finding(rows, kind, reason="Needs a look.", check_date=CHECK):
    return Finding(rows.vin, rows.campaign_id, kind, reason, check_date, rows)


def decision(status=DecisionStatus.FOLLOW_UP, note="Ask the file room.",
             decided_on=CHECK, vin=VIN, cid=CID):
    return Decision(vin, cid, status, note, decided_on)


# ---- day count ----------------------------------------------------------
def test_default_day_limit_is_60():
    assert DEFAULT_DAY_LIMIT == 60


def test_notice_to_1_mar_2026_is_day_60_and_on_time():
    assert inclusive_day_count(NOTICE, DAY_60) == 60
    assert is_on_time(NOTICE, DAY_60, 60)


def test_notice_to_2_mar_2026_is_day_61_and_late():
    assert inclusive_day_count(NOTICE, DAY_61) == 61
    assert not is_on_time(NOTICE, DAY_61, 60)


def test_same_day_repair_counts_as_one_day():
    assert inclusive_day_count(NOTICE, NOTICE) == 1
    assert is_on_time(NOTICE, NOTICE, 60)


def test_a_higher_limit_makes_day_61_on_time():
    assert is_on_time(NOTICE, DAY_61, 61)


def test_repair_before_the_notice_is_not_on_time():
    assert not is_on_time(NOTICE, date(2025, 12, 31), 60)


def test_inclusive_count_rejects_an_end_before_the_start():
    with pytest.raises(ContractError):
        inclusive_day_count(DAY_61, NOTICE)


@pytest.mark.parametrize("limit", [0, -1, True, 60.0, "60"])
def test_day_limit_must_be_a_positive_whole_number(limit):
    with pytest.raises(ContractError):
        is_on_time(NOTICE, DAY_60, limit)


def test_day_count_rejects_a_datetime():
    stamp = datetime(2026, 3, 1, 15, 0)
    with pytest.raises(ContractError):
        inclusive_day_count(NOTICE, stamp)


# ---- facts and the dates the check uses --------------------------------
def test_earliest_notice_starts_the_clock():
    rows = facts(notices=(date(2026, 2, 1), NOTICE))
    assert notice_date_used(rows) == NOTICE
    assert rows.notices[0].notice_date == date(2026, 2, 1)


def test_earliest_repair_on_or_after_the_notice_closes_the_clock():
    rows = facts(notices=(NOTICE,), repairs=(DAY_61, DAY_60))
    assert repair_date_used(rows) == DAY_60


def test_a_repair_before_the_notice_does_not_close_the_window():
    rows = facts(notices=(NOTICE,), repairs=(date(2025, 12, 15),))
    assert repair_date_used(rows) is None


def test_no_notice_means_the_repair_clock_does_not_start():
    rows = facts(repairs=(DAY_60,))
    assert notice_date_used(rows) is None
    assert repair_date_used(rows) is None


def test_missing_repair_uses_the_check_date_against_the_limit():
    rows = facts(notices=(NOTICE,))
    assert not repair_outside_limit(rows, DAY_60, 60)
    assert repair_outside_limit(rows, DAY_61, 60)


def test_repair_check_does_not_run_without_a_notice():
    with pytest.raises(ContractError, match="notice date"):
        repair_outside_limit(facts(), CHECK, 60)


def test_facts_reject_a_row_for_a_different_vehicle():
    with pytest.raises(ContractError):
        Facts(VIN, CID, (), (NoticeSent("OTHER", CID, NOTICE),), ())


def test_facts_reject_two_affected_rows_and_a_duplicate_date():
    with pytest.raises(ContractError):
        Facts(VIN, CID, (AffectedVehicle(VIN, CID), AffectedVehicle(VIN, CID)),
              (), ())
    with pytest.raises(ContractError):
        facts(notices=(NOTICE, NOTICE))


def test_repair_rows_have_no_tech_note():
    assert "tech_note" not in RepairDone.__slots__


# ---- decisions ----------------------------------------------------------
def test_every_decision_is_kept_and_the_latest_is_current():
    first = decision(DecisionStatus.REVIEWED, note=None, decided_on=date(2026, 11, 1))
    second = decision(DecisionStatus.NO_ACTION, "Closed the file.", date(2026, 11, 3))
    kept = append_decision((), first)
    both = append_decision(kept, second)
    assert kept == (first,)
    assert both == (first, second)
    assert current_decision(both, VIN, CID) == second
    assert decisions_for(both, VIN, CID) == both


def test_same_day_decisions_keep_record_order():
    earlier = decision(DecisionStatus.REVIEWED, None, CHECK)
    later = decision(DecisionStatus.FOLLOW_UP, "Still open.", CHECK)
    both = append_decision(append_decision((), earlier), later)
    assert current_decision(both, VIN, CID) == later
    assert both[0] == earlier


def test_a_decision_for_another_pair_does_not_become_current():
    other = decision(cid="RC-2026-002")
    assert current_decision((other,), VIN, CID) is None


@pytest.mark.parametrize("note", ["", "  ", " padded "])
def test_a_note_is_optional_and_cannot_be_blank_or_padded(note):
    decision(note=None)
    with pytest.raises(ContractError):
        decision(note=note)


def test_status_must_be_one_of_the_three():
    with pytest.raises(ContractError):
        Decision(VIN, CID, "follow up", None, CHECK)


# ---- payload ------------------------------------------------------------
def test_day_60_vehicle_is_on_time_and_takes_no_repair_finding():
    rows = facts(notices=(NOTICE,), repairs=(DAY_60,))
    payload = build_report(CHECK, (rows,), ())
    view = payload.vehicles[0]
    assert view.inclusive_days == 60
    assert view.on_time is True
    assert view.notice_date_used == NOTICE
    assert view.repair_date_used == DAY_60
    assert view.in_notices is True
    with pytest.raises(ContractError, match="outside the day limit"):
        build_report(CHECK, (rows,), (finding(rows, FindingKind.REPAIR),))


def test_day_61_is_a_repair_finding_and_the_count_stops_at_the_repair():
    rows = facts(notices=(NOTICE,), repairs=(DAY_61,))
    flag = finding(rows, FindingKind.REPAIR, "Repair is outside the day limit.")
    payload = build_report(CHECK, (rows,), (flag,))
    view = payload.vehicles[0]
    assert view.inclusive_days == 61
    assert view.on_time is False
    assert payload.findings == (flag,)
    assert payload.data_quality == ()


def test_no_repair_on_1_mar_is_inside_the_limit_and_on_2_mar_is_not():
    rows = facts(notices=(NOTICE,))
    inside = build_report(DAY_60, (rows,), ())
    assert inside.vehicles[0].inclusive_days == 60
    assert inside.vehicles[0].on_time is None
    assert inside.vehicles[0].repair_date_used is None
    with pytest.raises(ContractError):
        build_report(DAY_60, (rows,), (finding(rows, FindingKind.REPAIR,
                                               check_date=DAY_60),))
    flag = finding(rows, FindingKind.REPAIR, "No repair within the day limit.",
                   DAY_61)
    outside = build_report(DAY_61, (rows,), (flag,), day_limit=60)
    assert outside.vehicles[0].inclusive_days == 61
    assert outside.findings == (flag,)


def test_an_unnotified_vehicle_is_the_notification_finding_only():
    rows = facts()
    flag = finding(rows, FindingKind.NOTIFICATION, "No notice on file.")
    payload = build_report(CHECK, (rows,), (flag,))
    view = payload.vehicles[0]
    assert view.in_notices is False
    assert view.notice_date_used is None
    assert view.repair_date_used is None
    assert view.inclusive_days is None
    assert payload.findings == (flag,)
    with pytest.raises(ContractError, match="notice date"):
        build_report(CHECK, (rows,), (flag, finding(rows, FindingKind.REPAIR)))


def test_notification_and_repair_stay_in_emitted_order():
    late = facts(notices=(NOTICE,), repairs=(DAY_61,))
    missing = facts(vin="SYN00000000000000")
    repair = finding(late, FindingKind.REPAIR, "Late repair.")
    notice = finding(missing, FindingKind.NOTIFICATION, "No notice on file.")
    quality = finding(late, FindingKind.DATA_QUALITY,
                      "Notice dates 01/01/2026 and 02/01/2026 disagree.")
    payload = build_report(CHECK, (late, missing), (repair, quality, notice))
    assert payload.findings == (repair, notice)
    assert [row.kind for row in payload.findings] == [
        FindingKind.REPAIR, FindingKind.NOTIFICATION]
    assert payload.data_quality == (quality,)
    assert payload.vehicles[0].data_quality_reasons == (quality.reason,)
    assert payload.vehicles[1].data_quality_reasons == ()


def test_conflicting_notice_dates_use_the_earliest_and_stay_data_quality():
    rows = facts(notices=(date(2026, 2, 1), NOTICE), repairs=(DAY_60,))
    quality = finding(rows, FindingKind.DATA_QUALITY,
                      "Notice dates 2026-02-01 and 2026-01-01 disagree.")
    payload = build_report(CHECK, (rows,), (quality,))
    assert payload.findings == ()
    assert payload.data_quality == (quality,)
    assert payload.vehicles[0].notice_date_used == NOTICE
    assert payload.vehicles[0].on_time is True
    assert payload.vehicles[0].data_quality_reasons == (quality.reason,)


def test_the_payload_keeps_history_and_the_current_decision():
    rows = facts(notices=(NOTICE,), repairs=(DAY_61,))
    flag = finding(rows, FindingKind.REPAIR, "Late repair.")
    older = decision(DecisionStatus.REVIEWED, None, date(2026, 11, 2))
    newer = decision(DecisionStatus.FOLLOW_UP, "Call the shop.", date(2026, 11, 4))
    past = CheckHistoryRow(
        VIN, CID, date(2026, 10, 1), FindingKind.REPAIR, "Late repair.", 45)
    payload = build_report(
        CHECK, (rows,), (flag,),
        decisions=append_decision(append_decision((), older), newer),
        history=(past, history_row(flag, 60)),
        day_limit=60)
    assert payload.history[0].day_limit == 45
    assert payload.history[1].day_limit == 60
    assert payload.decisions == (older, newer)
    assert payload.vehicles[0].decision == newer
    assert payload.day_limit == 60


def test_a_decision_for_a_vehicle_absent_from_this_upload_is_kept():
    rows = facts()
    flag = finding(rows, FindingKind.NOTIFICATION, "No notice on file.")
    leftover = decision(vin="SYN99999999999999", cid="RC-2025-007")
    payload = build_report(CHECK, (rows,), (flag,), decisions=(leftover,))
    assert payload.decisions == (leftover,)
    assert payload.vehicles[0].decision is None


def test_screen_payload_uses_the_contract_keys_and_drops_excluded_ones():
    rows = facts(notices=(NOTICE,), repairs=(DAY_61,))
    flag = finding(rows, FindingKind.REPAIR, "Late repair.")
    quality = finding(rows, FindingKind.DATA_QUALITY, "Repair date sits before the notice.")
    payload = build_report(
        CHECK, (rows,), (flag, quality),
        decisions=(decision(note=None),),
        history=(history_row(flag, 60),))
    dumped = to_dict(payload)
    json.dumps(dumped)
    assert list(dumped) == [
        "check_date", "day_limit", "findings", "flagged_repairs", "data_quality", "data_issues",
        "decisions", "history", "vehicles"]
    assert list(dumped["findings"][0]) == [
        "vin", "campaign_id", "kind", "reason", "check_date", "facts"]
    assert dumped["findings"][0]["kind"] == "repair"
    assert dumped["data_quality"][0]["kind"] == "data quality"
    assert list(dumped["findings"][0]["facts"]) == [
        "affected", "notices", "repairs", "vehicle", "campaign"]
    assert list(dumped["findings"][0]["facts"]["repairs"][0]) == [
        "vin", "campaign_id", "repair_date"]
    assert list(dumped["vehicles"][0]) == [
        "vin", "campaign_id", "in_notices", "notice_date_used",
        "repair_date_used", "inclusive_days", "day_limit", "on_time",
        "decision", "data_quality_reasons", "facts"]
    assert dumped["vehicles"][0]["decision"]["status"] == "follow up"
    assert dumped["vehicles"][0]["decision"]["note"] is None
    assert dumped["history"][0]["kind"] == "repair"
    assert _keys(dumped).isdisjoint(EXCLUDED)


def test_a_quarantined_row_is_a_data_issue_without_a_finding():
    issue = DataIssue(
        "notices_sent.csv", 4, "BAD_VIN", "quarantined",
        "VIN XXX is not 17 characters.", "XXX,RC-2026-001,01/01/2026")
    payload = build_report(CHECK, (), (), data_issues=(issue,))
    assert payload.findings == ()
    assert payload.data_quality == ()
    assert payload.data_issues == (issue,)
    dumped = to_dict(payload)["data_issues"][0]
    assert dumped["vin"] is None
    assert dumped["campaign_id"] is None
    assert dumped["raw_row"] == "XXX,RC-2026-001,01/01/2026"


def test_a_bad_notice_date_is_a_data_issue_and_not_a_missing_notice():
    rows = facts()
    issue = DataIssue(
        "notices_sent.csv", 5, "BAD_DATE", "quarantined",
        "Notice date 02/30/2026 is not a real date.",
        f"{VIN},{CID},02/30/2026", VIN, CID)
    payload = build_report(CHECK, (rows,), (), data_issues=(issue,))
    view = payload.vehicles[0]
    assert payload.findings == ()
    assert payload.data_issues == (issue,)
    assert view.in_notices is True
    assert view.notice_date_used is None
    assert view.inclusive_days is None
    with pytest.raises(ContractError, match="data issue"):
        build_report(
            CHECK, (rows,),
            (finding(rows, FindingKind.NOTIFICATION, "No notice on file."),),
            data_issues=(issue,))


def test_a_finding_cannot_carry_a_rank_or_an_owner():
    rows = facts()
    flag = finding(rows, FindingKind.NOTIFICATION, "No notice on file.")
    assert {"priority", "rank", "owner"}.isdisjoint(Finding.__slots__)
    with pytest.raises(AttributeError):
        flag.reason = "changed"
    # Python 3.12's frozen slotted dataclass calls super() for an unknown
    # name and raises TypeError. 3.13 raises AttributeError. The name is
    # not stored on either version.
    with pytest.raises((AttributeError, TypeError)):
        flag.owner = "someone"
    assert not hasattr(flag, "owner")


def test_payload_rejects_a_finding_whose_facts_differ():
    rows = facts(notices=(NOTICE,), repairs=(DAY_61,))
    other = facts(notices=(NOTICE,), repairs=(DAY_60,))
    flag = Finding(rows.vin, rows.campaign_id, FindingKind.REPAIR, "Late.",
                   CHECK, other)
    with pytest.raises(ContractError, match="do not match"):
        build_report(CHECK, (rows,), (flag,))


def test_direct_payload_rejects_data_quality_mixed_into_findings():
    rows = facts()
    flag = finding(rows, FindingKind.DATA_QUALITY, "Bad vin digit.")
    view_rows = facts()
    with pytest.raises(ContractError, match="own list"):
        ReportPayload(
            CHECK, 60, (flag,), (), (), (),
            (build_report(CHECK, (view_rows,), ()).vehicles[0],))


def _keys(value):
    found = set()
    if isinstance(value, dict):
        found.update(value)
        for child in value.values():
            found.update(_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_keys(child))
    return found
