"""The shared affected VIN/campaign pairs from one accepted ingest.

CSV parsing, normalization and quarantine belong to ingest. The snapshot
adapter constructs this list once and passes it to both business checks.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from .contract.facts import AffectedVehicle
from .contract.validate import as_tuple


@dataclass(frozen=True, slots=True)
class AffectedList:
    """Unique vehicle-campaign pairs in source order, shared by both checks."""

    pairs: tuple[AffectedVehicle, ...]

    def __post_init__(self) -> None:
        pairs = as_tuple(self.pairs, AffectedVehicle, "pairs")
        object.__setattr__(self, "pairs", tuple(dict.fromkeys(pairs)))

    def __iter__(self) -> Iterator[AffectedVehicle]:
        return iter(self.pairs)

    def __len__(self) -> int:
        return len(self.pairs)
