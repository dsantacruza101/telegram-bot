import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from tarjetas_api import Card
from tarjetas_format import cut_phrase, esc, payment_phrase

logger = logging.getLogger("server-bot")

REMINDER_TIMEZONE = ZoneInfo("America/El_Salvador")
REMINDER_TIME = time(8, 0, tzinfo=REMINDER_TIMEZONE)
DEFAULT_DAYS_AHEAD = 3

@dataclass(frozen=True)
class CardAlert:
    card: Card
    cut_in_days: int | None
    payment_in_days: int | None

def days_ahead_from_env() -> int:
    raw = os.getenv("TARJETAS_REMINDER_DAYS")
    if raw is None:
        return DEFAULT_DAYS_AHEAD
    try:
        value = int(raw)
    except ValueError:
        value = -1
    if value < 0:
        logger.warning("TARJETAS_REMINDER_DAYS inválida, usando %s", DEFAULT_DAYS_AHEAD)
        return DEFAULT_DAYS_AHEAD
    return value

def today_in_el_salvador() -> date:
    return datetime.now(REMINDER_TIMEZONE).date()

def _days_if_due(target: date, today: date, days_ahead: int) -> int | None:
    days = (target - today).days
    return days if 0 <= days <= days_ahead else None

def select_alerts(cards: list[Card], today: date, days_ahead: int) -> list[CardAlert]:
    """Tarjetas cuyo corte o pago cae entre hoy y `days_ahead` días."""
    alerts = []
    for card in cards:
        cut = _days_if_due(card.next_cut_date, today, days_ahead)
        payment = _days_if_due(card.payment_due_date, today, days_ahead)
        if cut is not None or payment is not None:
            alerts.append(CardAlert(card, cut, payment))
    return alerts

def _format_alert(alert: CardAlert) -> str:
    lines = [f"💳 <b>{esc(alert.card.nickname)}</b> — {esc(alert.card.bank)}"]
    if alert.cut_in_days is not None:
        lines.append(f"   ✂️ {cut_phrase(alert.cut_in_days)}")
    if alert.payment_in_days is not None:
        lines.append(f"   🧾 {payment_phrase(alert.payment_in_days)}")
    return "\n".join(lines)

def format_reminder(alerts: list[CardAlert]) -> str:
    body = "\n\n".join(_format_alert(alert) for alert in alerts)
    return f"⏰ <b>Recordatorio de tarjetas</b>\n\n{body}"
