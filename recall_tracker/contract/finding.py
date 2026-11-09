"""A finding: one vehicle, one campaign, and why it was flagged."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from .facts import Facts
from .validate import ContractError, require_date, require_text


class FindingKind(Enum):
    NOTIFICATION = "notification"
    REPAIR = "repair"
    UNAFFECTED_REPAIR = "unaffected repair"
    DATA_QUALITY = "data quality"


@dataclass(frozen=True, slots=True)
class Finding:
    """One flag: the pair, the kind, why, when it was checked, and the facts."""

    vin: str
    campaign_id: str
    kind: FindingKind
    reason: str
    check_date: date
    facts: Facts

    def __post_init__(self) -> None:
        require_text(self.vin, "vin")
        require_text(self.campaign_id, "campaign_id")
        if type(self.kind) is not FindingKind:
            raise ContractError(
                "kind must be notification, repair, data quality, or unaffected repair")
        require_text(self.reason, "reason")
        require_date(self.check_date, "check date")
        if type(self.facts) is not Facts:
            raise ContractError("facts must be a Facts record")
        if self.vin != self.facts.vin or self.campaign_id != self.facts.campaign_id:
            raise ContractError(
                "a finding uses the vin and campaign_id on its facts")
