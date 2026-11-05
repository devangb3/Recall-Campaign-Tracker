"""The payload the screens read, assembled from the other records."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from .days import (
    DEFAULT_DAY_LIMIT, inclusive_day_count, is_on_time, notice_date_used,
    repair_date_used, repair_outside_limit)
from .decision import Decision, current_decision
from .facts import Facts
from .finding import Finding, FindingKind
from .history import CheckHistoryRow
from .validate import (
    ContractError, as_tuple, require_date, require_day_limit, require_text)


@dataclass(frozen=True, slots=True)
class VehicleView:
    """What the vehicle screen reads for one vin and campaign_id."""

    vin: str
    campaign_id: str
    in_notices: bool
    notice_date_used: date | None
    repair_date_used: date | None
    inclusive_days: int | None
    day_limit: int
    on_time: bool | None
    decision: Decision | None
    data_quality_reasons: tuple[str, ...]
    facts: Facts

    def __post_init__(self) -> None:
        require_text(self.vin, "vin")
        require_text(self.campaign_id, "campaign_id")
        if type(self.in_notices) is not bool:
            raise ContractError("in_notices must be true or false")
        if self.notice_date_used is not None:
            require_date(self.notice_date_used, "notice_date_used")
        if self.repair_date_used is not None:
            require_date(self.repair_date_used, "repair_date_used")
        if self.inclusive_days is not None and (
                type(self.inclusive_days) is not int or self.inclusive_days < 1):
            raise ContractError("inclusive_days must be a positive whole number")
        require_day_limit(self.day_limit)
        if self.on_time is not None and type(self.on_time) is not bool:
            raise ContractError("on_time must be true, false, or omitted")
        if self.decision is not None and type(self.decision) is not Decision:
            raise ContractError("decision must be a Decision")
        reasons = as_tuple(self.data_quality_reasons, str, "data_quality_reasons")
        object.__setattr__(self, "data_quality_reasons", reasons)
        for reason in reasons:
            require_text(reason, "data-quality reason")
        if type(self.facts) is not Facts:
            raise ContractError("facts must be a Facts record")
        if self.vin != self.facts.vin or self.campaign_id != self.facts.campaign_id:
            raise ContractError(
                "a vehicle view uses the vin and campaign_id on its facts")


def _split_findings(
        findings: tuple[Finding, ...]) -> tuple[tuple[Finding, ...], tuple[Finding, ...]]:
    """Move data quality onto its own list without ranking the other two."""
    flagged: list[Finding] = []
    quality: list[Finding] = []
    for finding in findings:
        if finding.kind is FindingKind.DATA_QUALITY:
            quality.append(finding)
        else:
            assert finding.kind in (FindingKind.NOTIFICATION, FindingKind.REPAIR)
            flagged.append(finding)
    return tuple(flagged), tuple(quality)


def _vehicle_view(facts: Facts, check_date: date, day_limit: int,
                  quality: Sequence[Finding],
                  decisions: Sequence[Decision]) -> VehicleView:
    notice = notice_date_used(facts)
    repair = repair_date_used(facts)
    if notice is None:
        inclusive: int | None = None
        on_time: bool | None = None
    elif repair is None:
        inclusive = inclusive_day_count(notice, check_date)
        on_time = None
    else:
        inclusive = inclusive_day_count(notice, repair)
        on_time = is_on_time(notice, repair, day_limit)
    reasons = tuple(
        finding.reason for finding in quality
        if finding.vin == facts.vin and finding.campaign_id == facts.campaign_id)
    return VehicleView(
        vin=facts.vin,
        campaign_id=facts.campaign_id,
        in_notices=notice is not None,
        notice_date_used=notice,
        repair_date_used=repair,
        inclusive_days=inclusive,
        day_limit=day_limit,
        on_time=on_time,
        decision=current_decision(decisions, facts.vin, facts.campaign_id),
        data_quality_reasons=reasons,
        facts=facts,
    )


@dataclass(frozen=True, slots=True)
class ReportPayload:
    """The records the screens read for one run.

    ``findings`` holds notification and repair in the order they were
    emitted. ``data_quality`` is the other list. ``decisions`` keeps every
    decision, including ones for a vehicle that is not in this upload.
    ``history`` keeps every check row. ``vehicles`` is one view per pair
    whose facts were supplied.
    """

    check_date: date
    day_limit: int
    findings: tuple[Finding, ...]
    data_quality: tuple[Finding, ...]
    decisions: tuple[Decision, ...]
    history: tuple[CheckHistoryRow, ...]
    vehicles: tuple[VehicleView, ...]

    def __post_init__(self) -> None:
        require_date(self.check_date, "check date")
        require_day_limit(self.day_limit)
        findings = as_tuple(self.findings, Finding, "findings")
        quality = as_tuple(self.data_quality, Finding, "data_quality")
        decisions = as_tuple(self.decisions, Decision, "decisions")
        history = as_tuple(self.history, CheckHistoryRow, "history")
        vehicles = as_tuple(self.vehicles, VehicleView, "vehicles")
        object.__setattr__(self, "findings", findings)
        object.__setattr__(self, "data_quality", quality)
        object.__setattr__(self, "decisions", decisions)
        object.__setattr__(self, "history", history)
        object.__setattr__(self, "vehicles", vehicles)
        self._reject_duplicates("findings", findings)
        self._reject_duplicates("data_quality", quality)
        self._check_kinds(findings, quality)
        views = self._views_by_pair(vehicles)
        self._check_findings(findings, views)
        self._check_quality(quality, views)
        self._check_views(vehicles, quality, decisions)

    def _reject_duplicates(self, field: str, rows: tuple[object, ...]) -> None:
        if len(rows) != len(set(rows)):
            raise ContractError(f"duplicate {field}")

    def _check_kinds(self, findings: tuple[Finding, ...],
                     quality: tuple[Finding, ...]) -> None:
        for finding in findings:
            if finding.kind is FindingKind.DATA_QUALITY:
                raise ContractError(
                    "data-quality findings stay on their own list")
            assert finding.kind in (
                FindingKind.NOTIFICATION, FindingKind.REPAIR)
        for finding in quality:
            if finding.kind is not FindingKind.DATA_QUALITY:
                raise ContractError(
                    "data-quality findings stay on their own list")

    def _views_by_pair(
            self, vehicles: tuple[VehicleView, ...]) -> dict[tuple[str, str], VehicleView]:
        views: dict[tuple[str, str], VehicleView] = {}
        for view in vehicles:
            key = (view.vin, view.campaign_id)
            if key in views:
                raise ContractError(
                    f"duplicate vehicle {view.vin} {view.campaign_id}")
            if view.day_limit != self.day_limit:
                raise ContractError("a vehicle uses the report day limit")
            views[key] = view
        return views

    def _check_findings(self, findings: tuple[Finding, ...],
                        views: dict[tuple[str, str], VehicleView]) -> None:
        seen: set[tuple[str, str, FindingKind]] = set()
        for finding in findings:
            self._require_vehicle(finding, views)
            key = (finding.vin, finding.campaign_id, finding.kind)
            if key in seen:
                raise ContractError(
                    "one notification finding and one repair finding per vehicle")
            seen.add(key)
            if finding.kind is FindingKind.NOTIFICATION:
                facts = finding.facts
                if len(facts.affected) != 1 or facts.notices:
                    raise ContractError(
                        "a notification finding is an affected vehicle "
                        "with no notice on file")
            else:
                if not repair_outside_limit(
                        finding.facts, self.check_date, self.day_limit):
                    raise ContractError(
                        "a repair finding is a repair outside the day limit")

    def _check_quality(self, quality: tuple[Finding, ...],
                       views: dict[tuple[str, str], VehicleView]) -> None:
        for finding in quality:
            self._require_vehicle(finding, views)

    def _require_vehicle(self, finding: Finding,
                         views: dict[tuple[str, str], VehicleView]) -> None:
        if finding.check_date != self.check_date:
            raise ContractError("a finding uses the report check date")
        view = views.get((finding.vin, finding.campaign_id))
        if view is None:
            raise ContractError(
                f"no vehicle facts for {finding.vin} {finding.campaign_id}")
        if finding.facts != view.facts:
            raise ContractError(
                f"finding facts do not match {finding.vin} {finding.campaign_id}")

    def _check_views(self, vehicles: tuple[VehicleView, ...],
                     quality: tuple[Finding, ...],
                     decisions: tuple[Decision, ...]) -> None:
        for view in vehicles:
            expected = _vehicle_view(
                view.facts, self.check_date, self.day_limit, quality, decisions)
            if view != expected:
                raise ContractError(
                    f"vehicle {view.vin} {view.campaign_id} "
                    "does not match its facts")


def build_report(check_date: date, vehicles: Sequence[Facts],
                 findings: Sequence[Finding], *,
                 decisions: Sequence[Decision] = (),
                 history: Sequence[CheckHistoryRow] = (),
                 day_limit: int = DEFAULT_DAY_LIMIT) -> ReportPayload:
    """Assemble the payload the screens read.

    Data-quality findings are moved to their own list. Notification and
    repair stay in the order given. Nothing in this payload is sorted by
    kind.
    """
    check_date = require_date(check_date, "check date")
    day_limit = require_day_limit(day_limit)
    vehicle_facts = as_tuple(vehicles, Facts, "vehicles")
    finding_rows = as_tuple(findings, Finding, "findings")
    decision_rows = as_tuple(decisions, Decision, "decisions")
    history_rows = as_tuple(history, CheckHistoryRow, "history")
    flagged, quality = _split_findings(finding_rows)
    views = tuple(
        _vehicle_view(facts, check_date, day_limit, quality, decision_rows)
        for facts in vehicle_facts)
    return ReportPayload(
        check_date=check_date,
        day_limit=day_limit,
        findings=flagged,
        data_quality=quality,
        decisions=decision_rows,
        history=history_rows,
        vehicles=views,
    )
