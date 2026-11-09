"""Accepted source rows and the vehicle/campaign eligibility metadata."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from .validate import ContractError, as_tuple, require_date, require_text


@dataclass(frozen=True, slots=True)
class Vehicle:
    vin: str
    model: str
    build_date: date

    def __post_init__(self) -> None:
        require_text(self.vin, "vin")
        require_text(self.model, "model")
        require_date(self.build_date, "build_date")


@dataclass(frozen=True, slots=True)
class Campaign:
    campaign_id: str
    model: str
    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        require_text(self.campaign_id, "campaign_id")
        require_text(self.model, "model")
        require_date(self.start_date, "start_date")
        require_date(self.end_date, "end_date")
        if self.start_date > self.end_date:
            raise ContractError("campaign start_date must not follow end_date")


@dataclass(frozen=True, slots=True)
class AffectedVehicle:
    """One row of affected vehicles: vin, campaign_id."""

    vin: str
    campaign_id: str

    def __post_init__(self) -> None:
        require_text(self.vin, "vin")
        require_text(self.campaign_id, "campaign_id")


@dataclass(frozen=True, slots=True)
class NoticeSent:
    """One row of notices sent: vin, campaign_id, notice_date."""

    vin: str
    campaign_id: str
    notice_date: date

    def __post_init__(self) -> None:
        require_text(self.vin, "vin")
        require_text(self.campaign_id, "campaign_id")
        require_date(self.notice_date, "notice_date")


@dataclass(frozen=True, slots=True)
class RepairDone:
    """One row of repairs done: vin, campaign_id, repair_date."""

    vin: str
    campaign_id: str
    repair_date: date

    def __post_init__(self) -> None:
        require_text(self.vin, "vin")
        require_text(self.campaign_id, "campaign_id")
        require_date(self.repair_date, "repair_date")


@dataclass(frozen=True, slots=True)
class Facts:
    """The rows a check used for one vin and campaign_id."""

    vin: str
    campaign_id: str
    affected: tuple[AffectedVehicle, ...] = ()
    notices: tuple[NoticeSent, ...] = ()
    repairs: tuple[RepairDone, ...] = ()
    vehicle: Vehicle | None = None
    campaign: Campaign | None = None

    def __post_init__(self) -> None:
        require_text(self.vin, "vin")
        require_text(self.campaign_id, "campaign_id")
        affected = as_tuple(self.affected, AffectedVehicle, "affected")
        notices = as_tuple(self.notices, NoticeSent, "notices")
        repairs = as_tuple(self.repairs, RepairDone, "repairs")
        object.__setattr__(self, "affected", affected)
        object.__setattr__(self, "notices", notices)
        object.__setattr__(self, "repairs", repairs)
        if len(affected) > 1:
            raise ContractError("a vehicle is in the affected file at most once")
        if not affected and not notices and not repairs:
            raise ContractError("facts need a row from one of the three files")
        self._require_same_pair(affected)
        self._require_same_pair(notices)
        self._require_same_pair(repairs)
        if self.vehicle is not None and (
                type(self.vehicle) is not Vehicle or self.vehicle.vin != self.vin):
            raise ContractError("vehicle metadata must use this VIN")
        if self.campaign is not None and (
                type(self.campaign) is not Campaign
                or self.campaign.campaign_id != self.campaign_id):
            raise ContractError("campaign metadata must use this campaign_id")
        notice_dates = [row.notice_date for row in notices]
        repair_dates = [row.repair_date for row in repairs]
        if len(notice_dates) != len(set(notice_dates)):
            raise ContractError("duplicate notice date for this vehicle")
        if len(repair_dates) != len(set(repair_dates)):
            raise ContractError("duplicate repair date for this vehicle")

    def _require_same_pair(
            self, rows: Sequence[AffectedVehicle | NoticeSent | RepairDone]) -> None:
        for row in rows:
            if row.vin != self.vin or row.campaign_id != self.campaign_id:
                raise ContractError(
                    "every fact row must use this vin and campaign_id")


def campaign_applies(facts: Facts) -> bool | None:
    """Unknown metadata never proves that a vehicle is unaffected."""
    if facts.vehicle is None or facts.campaign is None:
        return None
    return (facts.vehicle.model == facts.campaign.model
            and facts.campaign.start_date <= facts.vehicle.build_date
            <= facts.campaign.end_date)
