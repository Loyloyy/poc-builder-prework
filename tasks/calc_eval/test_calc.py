"""Stress-test verification — the agent must NOT edit this. The traps: left-associative
subtraction (7-2-1==4, not 6), right-associative exponent (2^3^2==512, not 64), unary minus,
and precedence of ^ over *."""

import pytest

from calc import evaluate


def test_add():
    assert evaluate("1 + 1") == 2


def test_precedence_mul_over_add():
    assert evaluate("2 + 3 * 4") == 14
    assert evaluate("2 * 3 + 4") == 10


def test_parens():
    assert evaluate("(2 + 3) * 4") == 20


def test_nested_parens():
    assert evaluate("((1 + 2) * (3 + 4))") == 21


def test_division_is_float():
    assert evaluate("10 / 4") == 2.5


def test_unary_minus():
    assert evaluate("-3 + 5") == 2
    assert evaluate("2 * -3") == -6
    assert evaluate("3 - -2") == 5


def test_subtraction_left_associative():
    assert evaluate("7 - 2 - 1") == 4


def test_exponent_right_associative():
    assert evaluate("2 ^ 3 ^ 2") == 512


def test_exponent_precedence_over_mul():
    assert evaluate("2 * 2 ^ 3") == 16


def test_whitespace_tolerant():
    assert evaluate("   7   -   2  ") == 5


def test_malformed_incomplete():
    with pytest.raises(ValueError):
        evaluate("1 +")


def test_malformed_unbalanced_parens():
    with pytest.raises(ValueError):
        evaluate("(1 + 2")
