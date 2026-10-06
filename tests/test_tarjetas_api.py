import json
from decimal import Decimal

import httpx
import pytest
import respx

from conftest import API_URL, CARD_JSON
from tarjetas_api import (
    CardAlreadyExists,
    CardNotFound,
    CardValidationError,
    NewCard,
    TarjetasApiClient,
    TarjetasApiError,
    TarjetasApiUnavailable,
    api_url_from_env,
    describe_validation_details,
)

@respx.mock
async def test_list_cards_parses_models(client):
    respx.get(f"{API_URL}/cards").mock(return_value=httpx.Response(200, json=[CARD_JSON]))
    cards = await client.list_cards()
    assert len(cards) == 1
    assert cards[0].nickname == "Viajes"
    assert cards[0].credit_limit == Decimal("1500.00")
    assert cards[0].next_cut_date.isoformat() == "2026-10-15"

@respx.mock
async def test_card_without_last_four(client):
    respx.get(f"{API_URL}/cards").mock(
        return_value=httpx.Response(200, json=[{**CARD_JSON, "lastFour": None}])
    )
    assert (await client.list_cards())[0].last_four is None

@respx.mock
async def test_next_card_not_found(client):
    respx.get(f"{API_URL}/cards/next").mock(return_value=httpx.Response(404, json={"error": "x"}))
    with pytest.raises(CardNotFound):
        await client.next_card()

@respx.mock
async def test_get_card_is_case_insensitive(client):
    respx.get(f"{API_URL}/cards").mock(return_value=httpx.Response(200, json=[CARD_JSON]))
    assert (await client.get_card("viajes")).nickname == "Viajes"

@respx.mock
async def test_get_card_missing(client):
    respx.get(f"{API_URL}/cards").mock(return_value=httpx.Response(200, json=[]))
    with pytest.raises(CardNotFound) as error:
        await client.get_card("Nada")
    assert "Nada" in error.value.message

@respx.mock
async def test_create_card_sends_limit_as_string_and_days_as_numbers(client):
    route = respx.post(f"{API_URL}/cards").mock(return_value=httpx.Response(201, json=CARD_JSON))
    await client.create_card(NewCard("Viajes", "BAC", Decimal("1500.5"), 15, 20, "1234"))
    assert json.loads(route.calls[0].request.content) == {
        "nickname": "Viajes",
        "bank": "BAC",
        "creditLimit": "1500.50",
        "cutDay": 15,
        "paymentDaysAfterCut": 20,
        "lastFour": "1234",
    }

@respx.mock
async def test_create_card_omits_optional_fields(client):
    route = respx.post(f"{API_URL}/cards").mock(return_value=httpx.Response(201, json=CARD_JSON))
    await client.create_card(NewCard("Viajes", "BAC", Decimal("10"), 5))
    assert set(json.loads(route.calls[0].request.content)) == {"nickname", "bank", "creditLimit", "cutDay"}

@respx.mock
async def test_create_duplicate_maps_to_conflict(client):
    respx.post(f"{API_URL}/cards").mock(return_value=httpx.Response(409, json={"error": "dup"}))
    with pytest.raises(CardAlreadyExists):
        await client.create_card(NewCard("Viajes", "BAC", Decimal("10"), 5))

@respx.mock
async def test_validation_error_surfaces_details(client):
    body = {
        "error": "Datos inválidos",
        "details": [{"path": ["cutDay"], "message": "Too big: expected number to be <=31"}],
    }
    respx.post(f"{API_URL}/cards").mock(return_value=httpx.Response(400, json=body))
    with pytest.raises(CardValidationError) as error:
        await client.create_card(NewCard("Viajes", "BAC", Decimal("10"), 99))
    assert "cutDay: Too big" in error.value.message

@respx.mock
async def test_update_patches_encoded_nickname_then_rereads(client):
    patch = respx.patch(f"{API_URL}/cards/Mi%20Tarjeta%2FX").mock(return_value=httpx.Response(200, json={}))
    respx.get(f"{API_URL}/cards").mock(
        return_value=httpx.Response(200, json=[{**CARD_JSON, "nickname": "Mi Tarjeta/X"}])
    )
    card = await client.update_card("Mi Tarjeta/X", {"bank": "BAC"})
    assert json.loads(patch.calls[0].request.content) == {"bank": "BAC"}
    assert card.nickname == "Mi Tarjeta/X"

@respx.mock
async def test_update_missing_card(client):
    respx.patch(f"{API_URL}/cards/Nada").mock(return_value=httpx.Response(404))
    with pytest.raises(CardNotFound) as error:
        await client.update_card("Nada", {"bank": "BAC"})
    assert "Nada" in error.value.message

@respx.mock
async def test_delete_success_and_missing(client):
    respx.delete(f"{API_URL}/cards/Viajes").mock(return_value=httpx.Response(204))
    respx.delete(f"{API_URL}/cards/Nada").mock(return_value=httpx.Response(404))
    await client.delete_card("Viajes")
    with pytest.raises(CardNotFound):
        await client.delete_card("Nada")

@respx.mock
@pytest.mark.parametrize("error", [httpx.ConnectError("boom"), httpx.ReadTimeout("slow")])
async def test_api_down_maps_to_unavailable(client, error):
    respx.get(f"{API_URL}/cards").mock(side_effect=error)
    with pytest.raises(TarjetasApiUnavailable) as raised:
        await client.list_cards()
    assert raised.value.message == "La API de tarjetas no responde"

@respx.mock
async def test_unexpected_status(client):
    respx.get(f"{API_URL}/cards").mock(return_value=httpx.Response(500, text="oops"))
    with pytest.raises(TarjetasApiError) as error:
        await client.list_cards()
    assert "500" in error.value.message

@respx.mock
async def test_invalid_json_body(client):
    respx.get(f"{API_URL}/cards").mock(return_value=httpx.Response(200, text="<html>"))
    with pytest.raises(TarjetasApiError):
        await client.list_cards()

def test_base_url_from_env(monkeypatch):
    monkeypatch.setenv("TARJETAS_API_URL", "http://otro:9/")
    assert api_url_from_env() == "http://otro:9"
    assert TarjetasApiClient().base_url == "http://otro:9"
    monkeypatch.delenv("TARJETAS_API_URL")
    assert api_url_from_env() == "http://127.0.0.1:3100"

def test_default_timeout_is_five_seconds():
    assert TarjetasApiClient(base_url="http://x").timeout == 5.0

@pytest.mark.parametrize(
    "details,expected",
    [
        ([{"path": ["a", "b"], "message": "mal"}], "a.b: mal"),
        ([{"message": "solo"}], "solo"),
        (["texto"], "texto"),
        ("directo", "directo"),
        ([], "datos inválidos"),
        (None, "datos inválidos"),
    ],
)
def test_describe_validation_details(details, expected):
    assert describe_validation_details(details) == expected
