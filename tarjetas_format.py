import html
from datetime import date
from decimal import Decimal

from tarjetas_api import Card, NewCard

def esc(text: str) -> str:
    return html.escape(text)

def money(amount: Decimal) -> str:
    return f"${amount:,.2f}"

def date_label(value: date) -> str:
    return value.strftime("%d/%m/%Y")

def days_phrase(days: int) -> str:
    if days == 0:
        return "hoy"
    if days == 1:
        return "en 1 día"
    return f"en {days} días"

def cut_phrase(days: int) -> str:
    return "Corte hoy" if days == 0 else f"Corte {days_phrase(days)}"

def payment_phrase(days: int) -> str:
    return "Pago vence hoy" if days == 0 else f"Pago vence {days_phrase(days)}"

def format_card_line(card: Card) -> str:
    return (
        f"💳 <b>{esc(card.nickname)}</b> — {esc(card.bank)}\n"
        f"   Límite: <code>{money(card.credit_limit)}</code>\n"
        f"   Corte: {date_label(card.next_cut_date)} ({days_phrase(card.days_until_cut)})\n"
        f"   Pago: {date_label(card.payment_due_date)}"
    )

def format_card_list(cards: list[Card]) -> str:
    if not cards:
        return "No tienes tarjetas registradas. Usa /nuevatarjeta para agregar una."
    lines = "\n\n".join(format_card_line(card) for card in cards)
    return f"💳 <b>Tus tarjetas</b>\n\n{lines}"

def format_card_detail(card: Card) -> str:
    last_four = f"•••• {esc(card.last_four)}" if card.last_four else "—"
    return (
        f"💳 <b>{esc(card.nickname)}</b>\n\n"
        f"🏦 Banco: {esc(card.bank)}\n"
        f"💰 Límite: <code>{money(card.credit_limit)}</code>\n"
        f"🔢 Últimos 4: <code>{last_four}</code>\n"
        f"✂️ Día de corte: <code>{card.cut_day}</code>\n"
        f"📅 Próximo corte: {date_label(card.next_cut_date)} ({days_phrase(card.days_until_cut)})\n"
        f"⏳ Días de pago tras el corte: <code>{card.payment_days_after_cut}</code>\n"
        f"🧾 Fecha de pago: {date_label(card.payment_due_date)}"
    )

def format_next_cut(card: Card) -> str:
    return (
        f"✂️ <b>Próximo corte</b>\n\n"
        f"💳 <b>{esc(card.nickname)}</b> — {esc(card.bank)}\n"
        f"Corte: {date_label(card.next_cut_date)} ({days_phrase(card.days_until_cut)})\n"
        f"Pago: {date_label(card.payment_due_date)}"
    )

def format_new_card_summary(card: NewCard, payment_days: int) -> str:
    last_four = f"•••• {esc(card.last_four)}" if card.last_four else "—"
    return (
        "📝 <b>Resumen de la nueva tarjeta</b>\n\n"
        f"Apodo: <b>{esc(card.nickname)}</b>\n"
        f"Banco: {esc(card.bank)}\n"
        f"Límite: <code>{money(card.credit_limit)}</code>\n"
        f"Día de corte: <code>{card.cut_day}</code>\n"
        f"Días de pago: <code>{payment_days}</code>\n"
        f"Últimos 4: <code>{last_four}</code>\n\n"
        "¿Confirmas?"
    )
