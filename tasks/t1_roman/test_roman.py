"""Task T1 verification — the agent must NOT edit this file."""

from roman import roman_to_int


def test_single():
    assert roman_to_int("III") == 3


def test_subtractive_iv():
    assert roman_to_int("IV") == 4


def test_subtractive_ix():
    assert roman_to_int("IX") == 9


def test_lviii():
    assert roman_to_int("LVIII") == 58


def test_mcmxciv():
    assert roman_to_int("MCMXCIV") == 1994
