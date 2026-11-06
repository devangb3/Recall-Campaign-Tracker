"""Checks shared by every record in the contract."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import TypeVar

T = TypeVar("T")


class ContractError(ValueError):
    """The records do not match the check and report contract."""


def require_text(value: object, field: str) -> str:
    """Return value when it is a non-blank string with no outer whitespace."""
    if type(value) is not str or value == "" or value != value.strip():
        raise ContractError(f"{field} must be a non-blank string")
    return value


def require_date(value: object, field: str) -> date:
    """Return value when it is a calendar date and not a datetime."""
    if type(value) is not date:
        raise ContractError(f"{field} must be a calendar date")
    return value


def require_day_limit(day_limit: object) -> int:
    """Return the day limit when it is a positive whole number."""
    if type(day_limit) is not int or day_limit < 1:
        raise ContractError("day limit must be a positive whole number")
    return day_limit


def as_tuple(items: Sequence[T], typ: type[T], field: str) -> tuple[T, ...]:
    """Copy a sequence into a tuple of one record type."""
    if isinstance(items, str) or not isinstance(items, Sequence):
        raise ContractError(f"{field} must be a sequence")
    rows = tuple(items)
    for item in rows:
        if type(item) is not typ:
            raise ContractError(f"{field} must contain {typ.__name__} records")
    return rows
