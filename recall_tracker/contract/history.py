"""One saved check row: date, kind, and reason for a vin and campaign."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .finding import Finding, FindingKind
from .validate import ContractError, require_date, require_day_limit, require_text


@dataclass(frozen=True, slots=True)
class CheckHistoryRow:
    """One saved check: date, kind, and reason for one vin and campaign."""

    vin: str
    campaign_id: str
    check_date: date
    kind: FindingKind
    reason: str
    day_limit: int

    def __post_init__(self) -> None:
        require_text(self.vin, "vin")
        require_text(self.campaign_id, "campaign_id")
        require_date(self.check_date, "check date")
        if type(self.kind) is not FindingKind:
            raise ContractError(
                "kind must be notification, repair, data quality, or unaffected repair")
        require_text(self.reason, "reason")
        require_day_limit(self.day_limit)


def history_row(finding: Finding, day_limit: int) -> CheckHistoryRow:
    """The history row for one finding, using the day limit of that check."""
    if type(finding) is not Finding:
        raise ContractError("finding must be a Finding")
    return CheckHistoryRow(
        vin=finding.vin,
        campaign_id=finding.campaign_id,
        check_date=finding.check_date,
        kind=finding.kind,
        reason=finding.reason,
        day_limit=require_day_limit(day_limit),
    )
