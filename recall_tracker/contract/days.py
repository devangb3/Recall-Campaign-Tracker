"""Inclusive day count and the dates a check uses."""

from __future__ import annotations

from datetime import date

from .facts import Facts
from .validate import ContractError, require_date, require_day_limit

DEFAULT_DAY_LIMIT = 60


def inclusive_day_count(start: date, end: date) -> int:
    """Count calendar dates from start through end, both ends included.

    Notice on 1 Jan 2026 and repair on 1 Mar 2026 is 60. Repair on 2 Mar
    2026 is 61. The same start and end is 1.
    """
    start = require_date(start, "start date")
    end = require_date(end, "end date")
    if end < start:
        raise ContractError(
            f"{end.isoformat()} is before {start.isoformat()}")
    return (end - start).days + 1


def is_on_time(notice_date: date, repair_date: date, day_limit: int) -> bool:
    """True when the repair is on or after the notice and within the limit."""
    notice_date = require_date(notice_date, "notice_date")
    repair_date = require_date(repair_date, "repair_date")
    day_limit = require_day_limit(day_limit)
    if repair_date < notice_date:
        return False
    return inclusive_day_count(notice_date, repair_date) <= day_limit


def notice_date_used(facts: Facts) -> date | None:
    """Earliest notice date for this pair, or None when no notice is on file."""
    if type(facts) is not Facts:
        raise ContractError("facts must be a Facts record")
    if not facts.notices:
        return None
    return min(row.notice_date for row in facts.notices)


def repair_date_used(facts: Facts) -> date | None:
    """Earliest repair on or after the notice date the check uses.

    A repair before the notice does not close the window. No notice means
    the repair clock does not start.
    """
    notice = notice_date_used(facts)
    if notice is None:
        return None
    usable = [row.repair_date for row in facts.repairs
              if row.repair_date >= notice]
    if not usable:
        return None
    return min(usable)


def repair_outside_limit(facts: Facts, check_date: date,
                         day_limit: int) -> bool:
    """True when this affected, notified vehicle takes one repair finding.

    No usable repair: compare the notice date through the check date with
    the limit. A usable repair: compare that repair with the limit.
    """
    check_date = require_date(check_date, "check date")
    day_limit = require_day_limit(day_limit)
    if type(facts) is not Facts:
        raise ContractError("facts must be a Facts record")
    if len(facts.affected) != 1:
        raise ContractError("the repair check runs on affected vehicles only")
    notice = notice_date_used(facts)
    if notice is None:
        raise ContractError(
            "the repair check runs only when a notice date exists")
    repair = repair_date_used(facts)
    if repair is None:
        return inclusive_day_count(notice, check_date) > day_limit
    return not is_on_time(notice, repair, day_limit)
