"""The affected-vehicle list for this one dealership.

The list is affected_vehicles.csv. The columns are vin and campaign_id.
A pair is one vehicle-campaign. The notification check and the repair
check both take this list. Neither one builds its own.

The list is not derived from model and build dates. There is no central
body to consult. A vehicle is not removed for scrap, theft, or export.
Resale is out of scope.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from recall_tracker.contract.data_issue import AFFECTED_FILE
from recall_tracker.contract.facts import AffectedVehicle
from recall_tracker.contract.validate import ContractError

COLUMNS = ("vin", "campaign_id")


class AffectedListError(Exception):
    """affected_vehicles.csv cannot supply the shared affected list."""


@dataclass(frozen=True, slots=True)
class AffectedList:
    """The vehicle-campaign pairs both checks walk, in file order."""

    pairs: tuple[AffectedVehicle, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "pairs", _unique_pairs(self.pairs))

    def __iter__(self) -> Iterator[AffectedVehicle]:
        return iter(self.pairs)

    def __len__(self) -> int:
        return len(self.pairs)


def load_affected_list(path: Path | str) -> AffectedList:
    """Read the dealership file. This is the only affected list."""
    source = Path(path)
    if source.is_dir():
        raise AffectedListError(
            "pass affected_vehicles.csv, not a folder of other sources")
    if source.name != AFFECTED_FILE:
        raise AffectedListError(
            f"{source.name} is not the affected-vehicle list")
    try:
        with source.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            _require_columns(reader.fieldnames)
            return AffectedList(_pairs(reader))
    except FileNotFoundError as exc:
        raise AffectedListError(f"{AFFECTED_FILE} is missing") from exc
    except UnicodeDecodeError as exc:
        raise AffectedListError(f"{AFFECTED_FILE} cannot be read") from exc
    except OSError as exc:
        raise AffectedListError(f"{AFFECTED_FILE} cannot be read") from exc


def vehicles_for_notification_check(
        affected: AffectedList) -> tuple[AffectedVehicle, ...]:
    """The pairs the notification check walks. It does not build a list."""
    return _pairs_for("notification", affected)


def vehicles_for_repair_check(
        affected: AffectedList) -> tuple[AffectedVehicle, ...]:
    """The pairs the repair check walks. It uses the same list."""
    return _pairs_for("repair", affected)


def _pairs_for(
        check: str, affected: AffectedList) -> tuple[AffectedVehicle, ...]:
    if type(affected) is not AffectedList:
        raise AffectedListError(
            f"the {check} check uses the affected list and does not "
            "build its own")
    return affected.pairs


def _require_columns(fieldnames: Sequence[str] | None) -> None:
    if not fieldnames:
        raise AffectedListError(f"{AFFECTED_FILE} has no header")
    names = tuple(fieldnames)
    if any(name is None or name == "" for name in names):
        raise AffectedListError(f"{AFFECTED_FILE} has an empty column name")
    if len(names) != len(set(names)):
        raise AffectedListError(f"{AFFECTED_FILE} repeats a column name")
    missing = [column for column in COLUMNS if column not in names]
    if missing:
        listed = ", ".join(missing)
        noun = "column" if len(missing) == 1 else "columns"
        raise AffectedListError(
            f"{AFFECTED_FILE} is missing required {noun} {listed}")


def _pairs(reader: csv.DictReader) -> tuple[AffectedVehicle, ...]:
    found: list[AffectedVehicle] = []
    for row_number, row in enumerate(reader, start=2):
        found.append(_pair(row_number, row))
    return tuple(found)


def _pair(row_number: int, row: Mapping[str, str | None]) -> AffectedVehicle:
    vin = row.get("vin")
    campaign_id = row.get("campaign_id")
    if vin is None or campaign_id is None:
        raise AffectedListError(
            f"{AFFECTED_FILE} row {row_number} is missing vin or campaign_id")
    try:
        return AffectedVehicle(vin, campaign_id)
    except ContractError as exc:
        raise AffectedListError(
            f"{AFFECTED_FILE} row {row_number}: {exc}") from exc


def _unique_pairs(pairs: Sequence[AffectedVehicle]) -> tuple[AffectedVehicle, ...]:
    if isinstance(pairs, str) or not isinstance(pairs, Sequence):
        raise AffectedListError("pairs must be a sequence of vehicle-campaigns")
    seen: set[tuple[str, str]] = set()
    unique: list[AffectedVehicle] = []
    for pair in pairs:
        if type(pair) is not AffectedVehicle:
            raise AffectedListError("each pair must be one vehicle-campaign")
        key = (pair.vin, pair.campaign_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(pair)
    return tuple(unique)
