from decimal import Decimal

from conftest import make_card
from tarjetas_api import NewCard
from tarjetas_format import (
    cut_phrase,
    days_phrase,
    format_card_detail,
    format_card_list,
    format_new_card_summary,
    format_next_cut,
    money,
    payment_phrase,
)

def test_money_has_thousands_and_two_decimals():
    assert money(Decimal("1500")) == "$1,500.00"

def test_days_phrases():
    assert days_phrase(0) == "hoy"
    assert days_phrase(1) == "en 1 día"
    assert days_phrase(3) == "en 3 días"
    assert cut_phrase(0) == "Corte hoy"
    assert cut_phrase(2) == "Corte en 2 días"
    assert payment_phrase(0) == "Pago vence hoy"
    assert payment_phrase(1) == "Pago vence en 1 día"

def test_list_is_compact_and_complete():
    text = format_card_list([make_card()])
    assert "Viajes" in text and "Banco Agrícola" in text
    assert "$1,500.00" in text
    assert "15/10/2026 (en 9 días)" in text
    assert "30/10/2026" in text

def test_empty_list_hint():
    assert "/nuevatarjeta" in format_card_list([])

def test_dynamic_values_are_html_escaped():
    card = make_card(nickname="<b>Mala</b> & Co", bank="A<B")
    for text in (format_card_list([card]), format_card_detail(card), format_next_cut(card)):
        assert "<b>Mala</b>" not in text
        assert "&lt;b&gt;Mala&lt;/b&gt; &amp; Co" in text

def test_detail_shows_last_four_only_masked():
    assert "•••• 1234" in format_card_detail(make_card())
    assert "—" in format_card_detail(make_card(lastFour=None))

def test_new_card_summary():
    text = format_new_card_summary(NewCard("Viajes", "BAC", Decimal("2000.5"), 10, 15, None), 15)
    assert "$2,000.50" in text and "Día de corte: <code>10</code>" in text and "¿Confirmas?" in text
