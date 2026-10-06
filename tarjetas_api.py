import logging
import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger("server-bot")

DEFAULT_API_URL = "http://127.0.0.1:3100"
API_TIMEOUT_SECONDS = 5.0

class TarjetasApiError(Exception):
    """Error de la API de tarjetas con un mensaje listo para mostrar."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

class TarjetasApiUnavailable(TarjetasApiError):
    def __init__(self):
        super().__init__("La API de tarjetas no responde")

class CardNotFound(TarjetasApiError):
    def __init__(self, nickname: str | None = None):
        detail = f" «{nickname}»" if nickname else ""
        super().__init__(f"No encontré la tarjeta{detail}")

class CardAlreadyExists(TarjetasApiError):
    def __init__(self):
        super().__init__("Ya existe una tarjeta con ese apodo")

class CardValidationError(TarjetasApiError):
    def __init__(self, details: str):
        super().__init__(f"La API rechazó los datos: {details}")

@dataclass(frozen=True)
class Card:
    nickname: str
    bank: str
    credit_limit: Decimal
    cut_day: int
    payment_days_after_cut: int
    last_four: str | None
    next_cut_date: date
    days_until_cut: int
    payment_due_date: date

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Card":
        return cls(
            nickname=data["nickname"],
            bank=data["bank"],
            credit_limit=Decimal(data["creditLimit"]),
            cut_day=int(data["cutDay"]),
            payment_days_after_cut=int(data["paymentDaysAfterCut"]),
            last_four=data.get("lastFour"),
            next_cut_date=date.fromisoformat(data["nextCutDate"]),
            days_until_cut=int(data["daysUntilCut"]),
            payment_due_date=date.fromisoformat(data["paymentDueDate"]),
        )

@dataclass(frozen=True)
class NewCard:
    nickname: str
    bank: str
    credit_limit: Decimal
    cut_day: int
    payment_days_after_cut: int | None = None
    last_four: str | None = None

    def to_payload(self) -> dict[str, Any]:
        # La API exige creditLimit como string y los días como número.
        payload: dict[str, Any] = {
            "nickname": self.nickname,
            "bank": self.bank,
            "creditLimit": f"{self.credit_limit:.2f}",
            "cutDay": self.cut_day,
        }
        if self.payment_days_after_cut is not None:
            payload["paymentDaysAfterCut"] = self.payment_days_after_cut
        if self.last_four is not None:
            payload["lastFour"] = self.last_four
        return payload

def api_url_from_env() -> str:
    return os.getenv("TARJETAS_API_URL", DEFAULT_API_URL).rstrip("/")

def describe_validation_details(details: Any) -> str:
    """Convierte el `details` de la API (lista de issues tipo zod) a texto."""
    if isinstance(details, list):
        parts = [_describe_issue(issue) for issue in details]
        return "; ".join(part for part in parts if part) or "datos inválidos"
    if isinstance(details, (str, dict)) and details:
        return str(details)
    return "datos inválidos"

def _describe_issue(issue: Any) -> str:
    if not isinstance(issue, dict):
        return str(issue)
    path = ".".join(str(p) for p in issue.get("path", []))
    message = str(issue.get("message", ""))
    return f"{path}: {message}" if path else message

def _error_body(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}

class TarjetasApiClient:
    def __init__(self, base_url: str | None = None, timeout: float = API_TIMEOUT_SECONDS):
        self.base_url = (base_url or api_url_from_env()).rstrip("/")
        self.timeout = timeout

    async def list_cards(self) -> list[Card]:
        response = await self._request("GET", "/cards")
        return [Card.from_json(item) for item in self._json(response)]

    async def next_card(self) -> Card:
        response = await self._request("GET", "/cards/next")
        return Card.from_json(self._json(response))

    async def get_card(self, nickname: str) -> Card:
        # La API no expone GET /cards/:nickname; se filtra la lista.
        wanted = nickname.casefold()
        for card in await self.list_cards():
            if card.nickname.casefold() == wanted:
                return card
        raise CardNotFound(nickname)

    async def create_card(self, card: NewCard) -> None:
        await self._request("POST", "/cards", json=card.to_payload())

    async def update_card(self, nickname: str, changes: dict[str, Any]) -> Card:
        await self._request(
            "PATCH", self._card_path(nickname), json=changes, nickname=nickname
        )
        # El contrato solo garantiza 200; se relee para mostrar fechas recalculadas.
        return await self.get_card(nickname)

    async def delete_card(self, nickname: str) -> None:
        await self._request("DELETE", self._card_path(nickname), nickname=nickname)

    @staticmethod
    def _card_path(nickname: str) -> str:
        return f"/cards/{quote(nickname, safe='')}"

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise TarjetasApiError("La API de tarjetas devolvió una respuesta inválida") from exc

    async def _request(
        self, method: str, path: str, nickname: str | None = None, **kwargs: Any
    ) -> httpx.Response:
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as http:
                response = await http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            logger.warning("API de tarjetas inaccesible: %s", type(exc).__name__)
            raise TarjetasApiUnavailable() from exc
        self._raise_for_status(response, nickname)
        return response

    @staticmethod
    def _raise_for_status(response: httpx.Response, nickname: str | None) -> None:
        status = response.status_code
        if status < 400:
            return
        if status == 404:
            raise CardNotFound(nickname)
        if status == 409:
            raise CardAlreadyExists()
        if status == 400:
            raise CardValidationError(
                describe_validation_details(_error_body(response).get("details"))
            )
        logger.error("API de tarjetas respondió %s", status)
        raise TarjetasApiError(f"La API de tarjetas devolvió un error inesperado ({status})")
