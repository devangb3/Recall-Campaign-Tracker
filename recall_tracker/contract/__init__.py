"""Shared records the checks emit and the report reads.

A finding names one vehicle and campaign, the kind, the reason, the check
date, and the facts used. Kind is notification, repair, or data quality.
Data-quality findings stay on their own list. Notification and repair are
equal: the payload keeps the order the checks emitted and has no rank.

On time means the repair date is on or after the notice date and the
inclusive day count is less than or equal to the day limit::

    inclusive_days = (repair_date - notice_date).days + 1

The default limit is 60. Notice on 1 Jan 2026 and repair on 1 Mar 2026 is
day 60, on time. Repair on 2 Mar 2026 is day 61, late. The same count runs
from the notice date through the check date when no usable repair exists.

The clock starts at the earliest notice date and closes at the earliest
repair date on or after that notice. A repair before the notice does not
close it. An unnotified vehicle is a notification finding only.

A coordinator decision is a status (reviewed, follow up, or no action) and
an optional note, keyed by vin and campaign_id. Recording a new decision
keeps the earlier ones. The latest is current.

A check-history row is the check date, kind, and reason for one vin and
campaign_id, plus the day limit used for that check.

Facts use only these columns:

* affected vehicles: vin, campaign_id
* notices sent: vin, campaign_id, notice_date
* repairs done: vin, campaign_id, repair_date

A notice row with a bad date is a data-issue record. The pair was in the
notices file, so it is not a notification finding.

Current owner, central-body status, returned mail, and resale are not part
of this contract. This package does not scan the CSVs and does not invent
findings. It rejects a finding that contradicts the records above.
"""

from .data_issue import DataIssue
from .days import (
    DEFAULT_DAY_LIMIT, inclusive_day_count, is_on_time, notice_date_used,
    repair_date_used, repair_outside_limit)
from .decision import (
    Decision, DecisionStatus, append_decision, current_decision, decisions_for)
from .facts import AffectedVehicle, Facts, NoticeSent, RepairDone
from .finding import Finding, FindingKind
from .history import CheckHistoryRow, history_row
from .report import ReportPayload, VehicleView, build_report
from .serialize import (
    AffectedDict, DataIssueDict, DecisionDict, FactsDict, FindingDict,
    HistoryDict, NoticeDict, RepairDict, ReportDict, VehicleDict, to_dict)
from .validate import ContractError

__all__ = [
    "DEFAULT_DAY_LIMIT",
    "AffectedDict",
    "AffectedVehicle",
    "CheckHistoryRow",
    "ContractError",
    "DataIssue",
    "DataIssueDict",
    "Decision",
    "DecisionDict",
    "DecisionStatus",
    "Facts",
    "FactsDict",
    "Finding",
    "FindingDict",
    "FindingKind",
    "HistoryDict",
    "NoticeDict",
    "NoticeSent",
    "RepairDict",
    "RepairDone",
    "ReportDict",
    "ReportPayload",
    "VehicleDict",
    "VehicleView",
    "append_decision",
    "build_report",
    "current_decision",
    "decisions_for",
    "history_row",
    "inclusive_day_count",
    "is_on_time",
    "notice_date_used",
    "repair_date_used",
    "repair_outside_limit",
    "to_dict",
]
