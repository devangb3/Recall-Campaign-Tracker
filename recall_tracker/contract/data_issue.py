"""A row that cannot be a finding.

A blank vin, a bad vin, a bad campaign, or a bad date has no good row for
the check to use. The report keeps it here: file, source row, issue code,
action, reason, and the raw row. Vin and campaign_id are set only when
they can be read.

A quarantined row in the notices file means the pair was in that file. It
is a data issue. It is not a notification finding.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .validate import ContractError, require_text

AFFECTED_FILE = "affected_vehicles.csv"
NOTICES_FILE = "notices_sent.csv"
REPAIRS_FILE = "repairs_done.csv"
SOURCE_FILES = frozenset({AFFECTED_FILE, NOTICES_FILE, REPAIRS_FILE})

# Code -> the only action REC-18 allows for that code.
_ACTION_FOR = {
    "MISSING_VALUE": "quarantined",
    "BAD_VIN": "quarantined",
    "BAD_CAMPAIGN": "quarantined",
    "BAD_DATE": "quarantined",
    "FUTURE_DATE": "quarantined",
    "DUPLICATE_ROW": "dropped_duplicate",
    "DATE_CONFLICT": "kept",
    "REPAIR_BEFORE_NOTICE": "kept",
    "NOT_IN_AFFECTED": "kept",
}


@dataclass(frozen=True, slots=True)
class DataIssue:
    """One ingest problem the findings list cannot carry."""

    file: str
    src_row: int
    issue_code: str
    action: str
    reason: str
    raw_row: str
    vin: str | None = None
    campaign_id: str | None = None

    def __post_init__(self) -> None:
        if self.file not in SOURCE_FILES:
            raise ContractError(
                "file must be affected_vehicles.csv, notices_sent.csv, "
                "or repairs_done.csv")
        if type(self.src_row) is not int or self.src_row < 2:
            raise ContractError("src_row must be a data row number, 2 or more")
        expected = _ACTION_FOR.get(self.issue_code)
        if expected is None:
            raise ContractError(f"unknown issue code {self.issue_code}")
        if self.action != expected:
            raise ContractError(
                f"{self.issue_code} uses action {expected}")
        require_text(self.reason, "reason")
        if type(self.raw_row) is not str:
            raise ContractError("raw_row must be the raw row text")
        if self.vin is not None:
            require_text(self.vin, "vin")
        if self.campaign_id is not None:
            require_text(self.campaign_id, "campaign_id")


def quarantined_notice(issues: Sequence[DataIssue], vin: str,
                       campaign_id: str) -> bool:
    """True when this pair has a notices-file row that was quarantined.

    The row is in the file. The date, or another required value, could not
    be used. That is not the same as the pair being absent.
    """
    for issue in issues:
        if (issue.file == NOTICES_FILE
                and issue.action == "quarantined"
                and issue.vin == vin
                and issue.campaign_id == campaign_id):
            return True
    return False
