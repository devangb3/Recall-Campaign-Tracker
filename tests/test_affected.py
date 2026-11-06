"""The accepted affected list preserves pair identity, order and immutability."""

from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from recall_tracker.affected import AffectedList
from recall_tracker.contract import AffectedVehicle, ContractError, NoticeSent

VIN_A = "SYN12345678901234"
VIN_B = "SYN12345678901235"
CAMP_A = "RC-2026-001"
CAMP_B = "RC-2026-002"


def test_pairs_keep_source_order_and_separate_campaigns():
    pairs = (
        AffectedVehicle(VIN_A, CAMP_B),
        AffectedVehicle(VIN_A, CAMP_A),
        AffectedVehicle(VIN_B, CAMP_A),
    )
    affected = AffectedList(pairs)
    assert tuple(affected) == pairs
    assert len(affected) == 3


def test_repeated_pair_keeps_its_first_position():
    first = AffectedVehicle(VIN_A, CAMP_A)
    second = AffectedVehicle(VIN_B, CAMP_A)
    affected = AffectedList((first, second, AffectedVehicle(VIN_A, CAMP_A)))
    assert affected.pairs == (first, second)
    assert affected.pairs[0] is first


def test_empty_accepted_list_is_valid():
    affected = AffectedList(())
    assert affected.pairs == ()
    assert len(affected) == 0


def test_shared_pairs_cannot_be_changed_through_the_original_sequence():
    first = AffectedVehicle(VIN_A, CAMP_A)
    supplied = [first]
    affected = AffectedList(supplied)
    supplied.append(AffectedVehicle(VIN_B, CAMP_A))
    assert affected.pairs == (first,)
    with pytest.raises(FrozenInstanceError):
        affected.pairs = ()


@pytest.mark.parametrize("pairs", [
    None,
    "vin,campaign_id",
    iter(()),
    {"vin": VIN_A, "campaign_id": CAMP_A},
    ({"vin": VIN_A, "campaign_id": CAMP_A},),
    (NoticeSent(VIN_A, CAMP_A, date(2026, 1, 1)),),
])
def test_only_sequences_of_accepted_affected_records_are_allowed(pairs):
    with pytest.raises(ContractError, match="pairs must"):
        AffectedList(pairs)
