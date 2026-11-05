"""VIN helpers: the North American check digit (position 9).

Only synthetic VINs are made in this project. Every generated VIN starts
with SYN, a manufacturer code that no real maker uses.
"""

# Letters I, O and Q are never used in a VIN.
VIN_CHARS = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"

_TRANSLIT = {
    **{str(d): d for d in range(10)},
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
}
_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]


def check_digit(vin: str) -> str:
    """Return the check digit ('0'-'9' or 'X') for a 17-character VIN.

    The character at position 9 is ignored (its weight is 0).
    """
    if len(vin) != 17:
        raise ValueError("VIN must be 17 characters")
    total = sum(_TRANSLIT[c] * w for c, w in zip(vin, _WEIGHTS))
    rem = total % 11
    return "X" if rem == 10 else str(rem)


def has_valid_check_digit(vin: str) -> bool:
    """True when vin is 17 allowed characters and position 9 is correct."""
    if len(vin) != 17 or any(c not in _TRANSLIT for c in vin):
        return False
    return vin[8] == check_digit(vin)


def with_check_digit(vin: str) -> str:
    """Return vin with the correct check digit written into position 9."""
    return vin[:8] + check_digit(vin) + vin[9:]
