"""Coordinator decisions. A new one keeps every earlier one."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum

from .validate import ContractError, as_tuple, require_date, require_text


class DecisionStatus(Enum):
    REVIEWED = "reviewed"
    FOLLOW_UP = "follow up"
    NO_ACTION = "no action"


@dataclass(frozen=True, slots=True)
class Decision:
    """One coordinator decision. A later decision does not erase this one."""

    vin: str
    campaign_id: str
    status: DecisionStatus
    note: str | None
    decided_on: date

    def __post_init__(self) -> None:
        require_text(self.vin, "vin")
        require_text(self.campaign_id, "campaign_id")
        if type(self.status) is not DecisionStatus:
            raise ContractError(
                "status must be reviewed, follow up, or no action")
        if self.note is not None:
            require_text(self.note, "note")
        require_date(self.decided_on, "decided_on")


def append_decision(decisions: Sequence[Decision],
                    decision: Decision) -> tuple[Decision, ...]:
    """Return every decision, including this one. The earlier ones stay."""
    if type(decision) is not Decision:
        raise ContractError("decision must be a Decision")
    return as_tuple(decisions, Decision, "decisions") + (decision,)


def decisions_for(decisions: Sequence[Decision], vin: str,
                  campaign_id: str) -> tuple[Decision, ...]:
    """Every decision kept for this vin and campaign_id, oldest first."""
    require_text(vin, "vin")
    require_text(campaign_id, "campaign_id")
    rows = as_tuple(decisions, Decision, "decisions")
    return tuple(row for row in rows
                 if row.vin == vin and row.campaign_id == campaign_id)


def current_decision(decisions: Sequence[Decision], vin: str,
                     campaign_id: str) -> Decision | None:
    """The latest decision for this pair. None means none has been recorded.

    A later decided_on wins. Two decisions on the same day keep list order:
    the one recorded later is current. Earlier decisions remain in the list.
    """
    chosen: Decision | None = None
    chosen_at = -1
    for index, decision in enumerate(decisions_for(decisions, vin, campaign_id)):
        if chosen is None or (decision.decided_on, index) >= (
                chosen.decided_on, chosen_at):
            chosen = decision
            chosen_at = index
    return chosen
