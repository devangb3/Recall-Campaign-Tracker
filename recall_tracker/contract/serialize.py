"""JSON-ready form of the report payload. Dates are ISO strings."""

from __future__ import annotations

from datetime import date
from typing import TypedDict

from .data_issue import DataIssue
from .decision import Decision
from .facts import Facts
from .finding import Finding
from .report import ReportPayload
from .validate import ContractError


class AffectedDict(TypedDict):
    vin: str
    campaign_id: str


class NoticeDict(TypedDict):
    vin: str
    campaign_id: str
    notice_date: str


class RepairDict(TypedDict):
    vin: str
    campaign_id: str
    repair_date: str


class FactsDict(TypedDict):
    affected: list[AffectedDict]
    notices: list[NoticeDict]
    repairs: list[RepairDict]


class FindingDict(TypedDict):
    vin: str
    campaign_id: str
    kind: str
    reason: str
    check_date: str
    facts: FactsDict


class DecisionDict(TypedDict):
    vin: str
    campaign_id: str
    status: str
    note: str | None
    decided_on: str


class HistoryDict(TypedDict):
    vin: str
    campaign_id: str
    check_date: str
    kind: str
    reason: str
    day_limit: int


class DataIssueDict(TypedDict):
    file: str
    src_row: int
    issue_code: str
    action: str
    reason: str
    raw_row: str
    vin: str | None
    campaign_id: str | None


class VehicleDict(TypedDict):
    vin: str
    campaign_id: str
    in_notices: bool
    notice_date_used: str | None
    repair_date_used: str | None
    inclusive_days: int | None
    day_limit: int
    on_time: bool | None
    decision: DecisionDict | None
    data_quality_reasons: list[str]
    facts: FactsDict


class ReportDict(TypedDict):
    check_date: str
    day_limit: int
    findings: list[FindingDict]
    data_quality: list[FindingDict]
    data_issues: list[DataIssueDict]
    decisions: list[DecisionDict]
    history: list[HistoryDict]
    vehicles: list[VehicleDict]


def _iso(value: date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _facts_dict(facts: Facts) -> FactsDict:
    return {
        "affected": [{"vin": row.vin, "campaign_id": row.campaign_id}
                     for row in facts.affected],
        "notices": [{"vin": row.vin, "campaign_id": row.campaign_id,
                     "notice_date": row.notice_date.isoformat()}
                    for row in facts.notices],
        "repairs": [{"vin": row.vin, "campaign_id": row.campaign_id,
                     "repair_date": row.repair_date.isoformat()}
                    for row in facts.repairs],
    }


def _finding_dict(finding: Finding) -> FindingDict:
    return {
        "vin": finding.vin,
        "campaign_id": finding.campaign_id,
        "kind": finding.kind.value,
        "reason": finding.reason,
        "check_date": finding.check_date.isoformat(),
        "facts": _facts_dict(finding.facts),
    }


def _decision_dict(decision: Decision) -> DecisionDict:
    return {
        "vin": decision.vin,
        "campaign_id": decision.campaign_id,
        "status": decision.status.value,
        "note": decision.note,
        "decided_on": decision.decided_on.isoformat(),
    }


def _data_issue_dict(issue: DataIssue) -> DataIssueDict:
    return {
        "file": issue.file,
        "src_row": issue.src_row,
        "issue_code": issue.issue_code,
        "action": issue.action,
        "reason": issue.reason,
        "raw_row": issue.raw_row,
        "vin": issue.vin,
        "campaign_id": issue.campaign_id,
    }


def to_dict(payload: ReportPayload) -> ReportDict:
    """The JSON-ready payload. Dates are ISO strings. Null means absent."""
    if type(payload) is not ReportPayload:
        raise ContractError("payload must be a ReportPayload")
    return {
        "check_date": payload.check_date.isoformat(),
        "day_limit": payload.day_limit,
        "findings": [_finding_dict(finding) for finding in payload.findings],
        "data_quality": [_finding_dict(finding)
                         for finding in payload.data_quality],
        "data_issues": [_data_issue_dict(issue)
                        for issue in payload.data_issues],
        "decisions": [_decision_dict(decision)
                      for decision in payload.decisions],
        "history": [{
            "vin": row.vin,
            "campaign_id": row.campaign_id,
            "check_date": row.check_date.isoformat(),
            "kind": row.kind.value,
            "reason": row.reason,
            "day_limit": row.day_limit,
        } for row in payload.history],
        "vehicles": [{
            "vin": view.vin,
            "campaign_id": view.campaign_id,
            "in_notices": view.in_notices,
            "notice_date_used": _iso(view.notice_date_used),
            "repair_date_used": _iso(view.repair_date_used),
            "inclusive_days": view.inclusive_days,
            "day_limit": view.day_limit,
            "on_time": view.on_time,
            "decision": None if view.decision is None else _decision_dict(
                view.decision),
            "data_quality_reasons": list(view.data_quality_reasons),
            "facts": _facts_dict(view.facts),
        } for view in payload.vehicles],
    }
