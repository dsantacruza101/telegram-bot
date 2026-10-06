from decimal import Decimal

import pytest

from tarjetas_validation import (
    DEFAULT_PAYMENT_DAYS,
    FullCardNumberRejected,
    InvalidInput,
    looks_like_full_card_number,
    parse_bank,
    parse_credit_limit,
    parse_cut_day,
    parse_last_four,
    parse_last_four_optional,
    parse_nickname,
    parse_payment_days_or_default,
)

@pytest.mark.parametrize("text,expected", [
    ("1500", Decimal("1500")), ("1500.5", Decimal("1500.5")), ("1,500.25", Decimal("1500.25")), ("$99.99", Decimal("99.99")),
])
def test_credit_limit_valid(text, expected):
    assert parse_credit_limit(text) == expected

@pytest.mark.parametrize("text", ["0", "0.00", "-5", "abc", "10.123", "", "1e3", "١٢٣"])
def test_credit_limit_invalid(text):
    with pytest.raises(InvalidInput):
        parse_credit_limit(text)

@pytest.mark.parametrize("text,expected", [("1", 1), ("31", 31), (" 15 ", 15)])
def test_cut_day_valid(text, expected):
    assert parse_cut_day(text) == expected

@pytest.mark.parametrize("text", ["0", "32", "-1", "1.5", "x", ""])
def test_cut_day_invalid(text):
    with pytest.raises(InvalidInput):
        parse_cut_day(text)

@pytest.mark.parametrize("text,expected", [
    ("15", 15), ("60", 60), ("1", 1), ("saltar", DEFAULT_PAYMENT_DAYS), ("SKIP", DEFAULT_PAYMENT_DAYS), ("-", DEFAULT_PAYMENT_DAYS),
])
def test_payment_days_valid_or_default(text, expected):
    assert parse_payment_days_or_default(text) == expected

@pytest.mark.parametrize("text", ["0", "61", "abc"])
def test_payment_days_invalid(text):
    with pytest.raises(InvalidInput):
        parse_payment_days_or_default(text)

def test_last_four_valid_and_skip():
    assert parse_last_four("0042") == "0042"
    assert parse_last_four_optional("saltar") is None
    assert parse_last_four_optional("1234") == "1234"

@pytest.mark.parametrize("text", ["123", "12345", "12a4", "", "١٢٣٤"])
def test_last_four_invalid(text):
    with pytest.raises(InvalidInput):
        parse_last_four(text)

@pytest.mark.parametrize("text", [
    "4111111111111111",
    "4111 1111 1111 1111",
    "4111-1111-1111-1111",
    "mi tarjeta 411111111111 vence",
    "123456789012",
])
def test_full_card_numbers_are_detected(text):
    assert looks_like_full_card_number(text)

@pytest.mark.parametrize("text", ["1234", "12345678901", "Viajes 2026", "1500.00"])
def test_short_digit_runs_are_not_card_numbers(text):
    assert not looks_like_full_card_number(text)

@pytest.mark.parametrize("parser", [
    parse_nickname, parse_bank, parse_credit_limit, parse_cut_day, parse_last_four, parse_last_four_optional,
])
def test_every_parser_refuses_full_card_numbers(parser):
    with pytest.raises(FullCardNumberRejected) as error:
        parser("4111 1111 1111 1111")
    assert "últimos 4" in str(error.value)

def test_text_fields_are_trimmed_and_bounded():
    assert parse_nickname("  Mi   tarjeta  ") == "Mi tarjeta"
    with pytest.raises(InvalidInput):
        parse_bank("   ")
    with pytest.raises(InvalidInput):
        parse_nickname("x" * 41)
