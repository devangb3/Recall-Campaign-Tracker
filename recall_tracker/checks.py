"""Notification and repair checks over one accepted affected-vehicle list.

CSV validation and normalization belong to ingest. These checks consume the
shared list and its facts, never infer affected vehicles from other sources,
and never write a decision or change a source row.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from .affected import AffectedList
from .contract import (
    DEFAULT_DAY_LIMIT, DataIssue, Facts, Finding, FindingKind,
    inclusive_day_count, notice_date_used, repair_date_used, repair_outside_limit)
from .contract.data_issue import quarantined_notice
from .contract.validate import (
    ContractError, as_tuple, require_date, require_day_limit)


def _facts_for_affected(affected: AffectedList,
                        facts: Sequence[Facts]) -> tuple[Facts, ...]:
    """Match the shared pairs to accepted facts, preserving list order."""
    if type(affected) is not AffectedList:
        raise ContractError("affected must be the shared AffectedList")
    rows = as_tuple(facts, Facts, "facts")
    by_pair: dict[tuple[str, str], Facts] = {}
    for row in rows:
        key = (row.vin, row.campaign_id)
        if key in by_pair:
            raise ContractError(f"duplicate facts for {row.vin} {row.campaign_id}")
        by_pair[key] = row
    selected: list[Facts] = []
    for pair in affected:
        row = by_pair.get((pair.vin, pair.campaign_id))
        if row is None or row.affected != (pair,):
            raise ContractError(
                f"missing affected facts for {pair.vin} {pair.campaign_id}")
        selected.append(row)
    return tuple(selected)


def check_notifications(
        affected: AffectedList, facts: Sequence[Facts], check_date: date, *,
        data_issues: Sequence[DataIssue] = ()) -> tuple[Finding, ...]:
    """Flag affected pairs absent from a successfully loaded notices file.

    A quarantined notice with readable identifiers proves the pair was in
    that file. Its bad data is reported separately, rather than turning it
    into a missing-notice finding. File failures never reach these checks.
    """
    check_date = require_date(check_date, "check date")
    issues = as_tuple(data_issues, DataIssue, "data_issues")
    findings: list[Finding] = []
    for row in _facts_for_affected(affected, facts):
        if row.notices:
            continue
        if quarantined_notice(issues, row.vin, row.campaign_id):
            continue
        findings.append(Finding(
            row.vin, row.campaign_id, FindingKind.NOTIFICATION,
            "No notice is on file for this vehicle and campaign.",
            check_date, row))
    return tuple(findings)


def check_repairs(
        affected: AffectedList, facts: Sequence[Facts], check_date: date, *,
        day_limit: int = DEFAULT_DAY_LIMIT) -> tuple[Finding, ...]:
    """Flag late repairs and missing usable repairs past the inclusive limit.

    The earliest notice starts the clock. The earliest repair on or after
    it closes the clock. No usable notice date means no repair clock.
    """
    check_date = require_date(check_date, "check date")
    day_limit = require_day_limit(day_limit)
    findings: list[Finding] = []
    for row in _facts_for_affected(affected, facts):
        notice = notice_date_used(row)
        if notice is None or not repair_outside_limit(row, check_date, day_limit):
            continue
        repair = repair_date_used(row)
        end_date = check_date if repair is None else repair
        days = inclusive_day_count(notice, end_date)
        if repair is None:
            reason = (
                f"No usable repair is on file as of {check_date.isoformat()}, "
                f"day {days} from notice on {notice.isoformat()}, "
                f"beyond the {day_limit}-day inclusive limit.")
        else:
            reason = (
                f"Repair on {repair.isoformat()} took {days} inclusive days "
                f"from notice on {notice.isoformat()}, "
                f"exceeding the {day_limit}-day limit.")
        findings.append(Finding(
            row.vin, row.campaign_id, FindingKind.REPAIR, reason,
            check_date, row))
    return tuple(findings)
