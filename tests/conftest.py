import os
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# bot.py lee estas variables al importarse, así que van antes de cualquier import del bot.
os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-token")
os.environ.setdefault("CHAT_ID", "42")

from tarjetas_api import Card, TarjetasApiClient  # noqa: E402
from tarjetas_handlers import CLIENT_KEY  # noqa: E402

API_URL = "http://tarjetas.test"
AUTHORIZED_ID = int(os.environ["CHAT_ID"])

CARD_JSON = {
    "nickname": "Viajes",
    "bank": "Banco Agrícola",
    "creditLimit": "1500.00",
    "cutDay": 15,
    "paymentDaysAfterCut": 15,
    "lastFour": "1234",
    "nextCutDate": "2026-10-15",
    "daysUntilCut": 9,
    "paymentDueDate": "2026-10-30",
}

def make_card(**overrides) -> Card:
    return Card.from_json({**CARD_JSON, **overrides})

@pytest.fixture
def client() -> TarjetasApiClient:
    return TarjetasApiClient(base_url=API_URL)

def make_update(text: str | None = None, user_id: int = AUTHORIZED_ID, callback_data: str | None = None):
    message = SimpleNamespace(
        text=text,
        reply_text=AsyncMock(),
        delete=AsyncMock(),
        edit_text=AsyncMock(),
    )
    query = None
    if callback_data is not None:
        query = SimpleNamespace(
            data=callback_data, answer=AsyncMock(), edit_message_reply_markup=AsyncMock()
        )
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_message=message,
        callback_query=query,
    )

def make_context(client: TarjetasApiClient, args: list[str] | None = None):
    return SimpleNamespace(
        args=args or [],
        user_data={},
        application=SimpleNamespace(bot_data={CLIENT_KEY: client}),
        bot=SimpleNamespace(send_message=AsyncMock()),
    )

def reply_text_of(update) -> str:
    return update.effective_message.reply_text.call_args.args[0]

TODAY = date(2026, 10, 6)
LIMIT = Decimal("1500.00")
