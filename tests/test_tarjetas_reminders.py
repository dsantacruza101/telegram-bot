from datetime import date

import pytest

from conftest import TODAY, make_card
from tarjetas_reminders import (
    DEFAULT_DAYS_AHEAD,
    REMINDER_TIME,
    days_ahead_from_env,
    format_reminder,
    select_alerts,
)

def card(nickname: str, cut: str, pay: str):
    return make_card(nickname=nickname, nextCutDate=cut, paymentDueDate=pay)

def test_reminder_runs_at_8am_el_salvador():
    assert (REMINDER_TIME.hour, REMINDER_TIME.minute) == (8, 0)
    assert str(REMINDER_TIME.tzinfo) == "America/El_Salvador"

def test_nothing_due_returns_no_alerts():
    assert select_alerts([card("A", "2026-10-20", "2026-11-04")], TODAY, 3) == []

def test_cut_within_window():
    (alert,) = select_alerts([card("A", "2026-10-09", "2026-11-04")], TODAY, 3)
    assert (alert.cut_in_days, alert.payment_in_days) == (3, None)

def test_payment_within_window():
    (alert,) = select_alerts([card("A", "2026-10-20", "2026-10-06")], TODAY, 3)
    assert (alert.cut_in_days, alert.payment_in_days) == (None, 0)

def test_both_cut_and_payment():
    (alert,) = select_alerts([card("A", "2026-10-07", "2026-10-08")], TODAY, 3)
    assert (alert.cut_in_days, alert.payment_in_days) == (1, 2)

def test_boundaries_are_inclusive_and_past_is_ignored():
    assert select_alerts([card("A", "2026-10-10", "2026-12-01")], TODAY, 3) == []
    assert select_alerts([card("A", "2026-10-06", "2026-12-01")], TODAY, 0)
    assert select_alerts([card("A", "2026-10-05", "2026-10-04")], TODAY, 3) == []

def test_only_due_cards_are_kept_in_order():
    cards = [card("Lejos", "2026-11-01", "2026-11-16"), card("Cerca", "2026-10-08", "2026-10-23")]
    assert [a.card.nickname for a in select_alerts(cards, TODAY, 3)] == ["Cerca"]

def test_days_are_computed_from_dates_not_api_counter():
    stale = make_card(nextCutDate="2026-10-08", daysUntilCut=99, paymentDueDate="2026-12-01")
    (alert,) = select_alerts([stale], TODAY, 3)
    assert alert.cut_in_days == 2

def test_message_text_and_escaping():
    alerts = select_alerts([card("<A>", "2026-10-08", "2026-10-06")], date(2026, 10, 6), 3)
    text = format_reminder(alerts)
    assert "Corte en 2 días" in text and "Pago vence hoy" in text
    assert "&lt;A&gt;" in text and "<A>" not in text

@pytest.mark.parametrize("raw,expected", [("5", 5), ("0", 0), ("-1", 3), ("abc", 3), ("", 3)])
def test_days_ahead_env(monkeypatch, raw, expected):
    monkeypatch.setenv("TARJETAS_REMINDER_DAYS", raw)
    assert days_ahead_from_env() == expected

def test_days_ahead_default(monkeypatch):
    monkeypatch.delenv("TARJETAS_REMINDER_DAYS", raising=False)
    assert days_ahead_from_env() == DEFAULT_DAYS_AHEAD == 3
