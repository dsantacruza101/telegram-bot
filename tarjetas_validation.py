import re
from decimal import Decimal, InvalidOperation

DEFAULT_PAYMENT_DAYS = 15
MAX_TEXT_LENGTH = 40
SKIP_WORDS = frozenset({"saltar", "skip", "-"})

_LIMIT_PATTERN = re.compile(r"^\d+(\.\d{1,2})?$", re.ASCII)
_LAST_FOUR_PATTERN = re.compile(r"^\d{4}$", re.ASCII)
_LONG_DIGIT_RUN = re.compile(r"\d{12,}", re.ASCII)
_SEPARATORS = re.compile(r"[\s-]")

FULL_NUMBER_REFUSAL = (
    "Por seguridad no acepto números de tarjeta completos. "
    "Solo guardo los últimos 4 dígitos; nunca envíes el número completo ni el CVV."
)

class InvalidInput(ValueError):
    """Entrada del usuario inválida; el mensaje se muestra tal cual."""

class FullCardNumberRejected(InvalidInput):
    def __init__(self):
        super().__init__(FULL_NUMBER_REFUSAL)

def looks_like_full_card_number(text: str) -> bool:
    """True si hay 12+ dígitos seguidos, aun separados por espacios o guiones."""
    return _LONG_DIGIT_RUN.search(_SEPARATORS.sub("", text)) is not None

def is_skip(text: str) -> bool:
    return text.strip().casefold() in SKIP_WORDS

def reject_full_card_number(text: str) -> None:
    if looks_like_full_card_number(text):
        raise FullCardNumberRejected()

def _clean_text(text: str, label: str) -> str:
    reject_full_card_number(text)
    value = " ".join(text.split())
    if not value:
        raise InvalidInput(f"El {label} no puede estar vacío.")
    if len(value) > MAX_TEXT_LENGTH:
        raise InvalidInput(f"El {label} es demasiado largo (máximo {MAX_TEXT_LENGTH} caracteres).")
    return value

def parse_nickname(text: str) -> str:
    return _clean_text(text, "apodo")

def parse_bank(text: str) -> str:
    return _clean_text(text, "banco")

def parse_credit_limit(text: str) -> Decimal:
    reject_full_card_number(text)
    raw = text.strip().replace(",", "").lstrip("$")
    if not _LIMIT_PATTERN.match(raw):
        raise InvalidInput("El límite debe ser un monto con hasta 2 decimales, por ejemplo 1500 o 1500.50.")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise InvalidInput("El límite no es un número válido.") from exc
    if value <= 0:
        raise InvalidInput("El límite debe ser mayor que 0.")
    return value

def _parse_int_in_range(text: str, label: str, low: int, high: int) -> int:
    reject_full_card_number(text)
    raw = text.strip()
    if not raw.isascii() or not raw.isdigit() or not low <= int(raw) <= high:
        raise InvalidInput(f"{label} debe ser un número entero entre {low} y {high}.")
    return int(raw)

def parse_cut_day(text: str) -> int:
    return _parse_int_in_range(text, "El día de corte", 1, 31)

def parse_payment_days(text: str) -> int:
    return _parse_int_in_range(text, "Los días de pago", 1, 60)

def parse_payment_days_or_default(text: str) -> int:
    return DEFAULT_PAYMENT_DAYS if is_skip(text) else parse_payment_days(text)

def parse_last_four(text: str) -> str:
    reject_full_card_number(text)
    value = text.strip()
    if not _LAST_FOUR_PATTERN.match(value):
        raise InvalidInput("Los últimos 4 dígitos deben ser exactamente 4 números.")
    return value

def parse_last_four_optional(text: str) -> str | None:
    return None if is_skip(text) else parse_last_four(text)
