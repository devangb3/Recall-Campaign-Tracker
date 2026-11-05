"""VIN check digit helpers."""

import pytest

from recall_tracker.vin import (VIN_CHARS, check_digit, has_valid_check_digit,
                                with_check_digit)


def _value(c):
    if c.isdigit():
        return int(c)
    return {"K": 2, "M": 4, "G": 7, "D": 4, "A": 1, "P": 7, "X": 7}[c]


# A widely published valid VIN whose check digit is X.
KNOWN_X = "1M8GDM9AXKP042788"
# All ones: weights sum to 89, 89 % 11 = 1, so the check digit is 1.
ALL_ONES = "11111111111111111"


def test_known_vin_check_digit_is_x():
    assert check_digit(KNOWN_X) == "X"


def test_known_vin_is_valid():
    assert has_valid_check_digit(KNOWN_X)


def test_all_ones_is_valid():
    assert has_valid_check_digit(ALL_ONES)


def test_check_digit_ignores_position_9():
    assert check_digit(KNOWN_X[:8] + "0" + KNOWN_X[9:]) == "X"


@pytest.mark.parametrize("pos", [0, 7, 9, 16])
def test_changing_one_character_breaks_the_check(pos):
    # Swap in a digit whose VIN value differs (K and 2 both count as 2).
    vin = list(KNOWN_X)
    old = _value(vin[pos])
    vin[pos] = next(d for d in "123456789" if int(d) != old)
    assert not has_valid_check_digit("".join(vin))


def test_wrong_check_digit_is_invalid():
    assert not has_valid_check_digit(KNOWN_X[:8] + "5" + KNOWN_X[9:])


@pytest.mark.parametrize("letter", ["I", "O", "Q"])
def test_forbidden_letters_are_invalid(letter):
    assert not has_valid_check_digit(KNOWN_X[:11] + letter + KNOWN_X[12:])


@pytest.mark.parametrize("letter", ["I", "O", "Q"])
def test_forbidden_letters_are_not_vin_characters(letter):
    assert letter not in VIN_CHARS


def test_lower_case_is_invalid_without_normalizing():
    assert not has_valid_check_digit(KNOWN_X.lower())


@pytest.mark.parametrize("vin", ["", KNOWN_X[:16], KNOWN_X + "1"])
def test_wrong_length_is_invalid(vin):
    assert not has_valid_check_digit(vin)


@pytest.mark.parametrize("vin", [KNOWN_X[:16], KNOWN_X + "1"])
def test_check_digit_rejects_wrong_length(vin):
    with pytest.raises(ValueError):
        check_digit(vin)


def test_symbols_are_invalid():
    assert not has_valid_check_digit(KNOWN_X[:16] + "*")


def test_with_check_digit_makes_a_valid_vin():
    assert has_valid_check_digit(with_check_digit("SYNABCDE0RA123456"))


def test_with_check_digit_keeps_other_characters():
    fixed = with_check_digit("SYNABCDE0RA123456")
    assert fixed[:8] + fixed[9:] == "SYNABCDE" + "RA123456"


def test_with_check_digit_is_idempotent():
    once = with_check_digit("SYNABCDE0RA123456")
    assert with_check_digit(once) == once
