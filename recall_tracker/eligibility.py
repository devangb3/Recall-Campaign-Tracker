"""Automatic flags for accepted repairs outside campaign eligibility."""

from datetime import date
from collections.abc import Sequence

from .contract import Facts, Finding, FindingKind
from .contract.facts import campaign_applies
from .contract.validate import as_tuple, require_date


def check_unaffected_repairs(facts: Sequence[Facts], check_date: date
                             ) -> tuple[Finding, ...]:
    check_date = require_date(check_date, "check date")
    flags = []
    for pair in as_tuple(facts, Facts, "facts"):
        if not pair.repairs or campaign_applies(pair) is not False:
            continue
        vehicle, campaign = pair.vehicle, pair.campaign
        assert vehicle is not None and campaign is not None
        reasons = []
        if vehicle.model != campaign.model:
            reasons.append(f"vehicle model {vehicle.model} does not match campaign model {campaign.model}")
        if not campaign.start_date <= vehicle.build_date <= campaign.end_date:
            reasons.append(f"build date {vehicle.build_date.isoformat()} is outside "
                           f"{campaign.start_date.isoformat()} to {campaign.end_date.isoformat()} (inclusive)")
        flags.append(Finding(
            pair.vin, pair.campaign_id, FindingKind.UNAFFECTED_REPAIR,
            "Repair on an unaffected vehicle: " + "; ".join(reasons) + ".",
            check_date, pair))
    return tuple(flags)
