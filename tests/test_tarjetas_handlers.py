import json
from datetime import date
from unittest.mock import patch

import httpx
import respx
from telegram.ext import Application, ConversationHandler

import tarjetas_handlers as h
from conftest import API_URL, CARD_JSON, make_context, make_update, reply_text_of

END = ConversationHandler.END

async def send(step, text, context):
    update = make_update(text)
    state = await step(update, context)
    return state, update

# --- seguridad ---------------------------------------------------------------

async def test_unauthorized_user_gets_nothing(client):
    update = make_update(user_id=999)
    await h.tarjetas(update, make_context(client))
    update.effective_message.reply_text.assert_not_called()

# --- consultas ---------------------------------------------------------------

@respx.mock
async def test_tarjetas_lists_cards(client):
    respx.get(f"{API_URL}/cards").mock(return_value=httpx.Response(200, json=[CARD_JSON]))
    update = make_update()
    await h.tarjetas(update, make_context(client))
    assert "Viajes" in reply_text_of(update)
    assert update.effective_message.reply_text.call_args.kwargs["parse_mode"] == "HTML"

@respx.mock
async def test_api_down_replies_friendly_message(client):
    respx.get(f"{API_URL}/cards").mock(side_effect=httpx.ConnectError("down"))
    update = make_update()
    await h.tarjetas(update, make_context(client))
    assert "La API de tarjetas no responde" in reply_text_of(update)

@respx.mock
async def test_tarjeta_detail_joins_multiword_nickname(client):
    respx.get(f"{API_URL}/cards").mock(
        return_value=httpx.Response(200, json=[{**CARD_JSON, "nickname": "Mi Tarjeta"}])
    )
    update = make_update()
    await h.tarjeta(update, make_context(client, ["mi", "tarjeta"]))
    assert "Día de corte" in reply_text_of(update)

async def test_tarjeta_without_args_shows_usage(client):
    update = make_update()
    await h.tarjeta(update, make_context(client))
    assert "Uso:" in reply_text_of(update)

@respx.mock
async def test_proxcorte_ok_and_empty(client):
    route = respx.get(f"{API_URL}/cards/next")
    route.mock(return_value=httpx.Response(200, json=CARD_JSON))
    update = make_update()
    await h.proxcorte(update, make_context(client))
    assert "Próximo corte" in reply_text_of(update)
    route.mock(return_value=httpx.Response(404))
    update = make_update()
    await h.proxcorte(update, make_context(client))
    assert "No tienes tarjetas" in reply_text_of(update)

# --- /nuevatarjeta -----------------------------------------------------------

async def test_full_card_number_is_refused_deleted_and_state_kept(client):
    context = make_context(client)
    step = h.draft_step("nickname", h.parse_nickname, h.NICKNAME, h.BANK, "siguiente")
    state, update = await send(step, "4111 1111 1111 1111", context)
    assert state == h.NICKNAME
    assert "últimos 4" in reply_text_of(update)
    update.effective_message.delete.assert_awaited_once()
    assert "nickname" not in context.user_data.get(h.NEW_DRAFT_KEY, {})

async def test_invalid_step_input_keeps_state_and_valid_advances(client):
    context = make_context(client)
    step = h.draft_step("cut_day", h.parse_cut_day, h.CUT_DAY, h.PAYMENT_DAYS, "siguiente")
    state, update = await send(step, "40", context)
    assert state == h.CUT_DAY and "entre 1 y 31" in reply_text_of(update)
    state, _ = await send(step, "20", context)
    assert state == h.PAYMENT_DAYS
    assert context.user_data[h.NEW_DRAFT_KEY]["cut_day"] == 20

async def test_last_four_rejects_full_number_and_accepts_skip(client):
    context = make_context(client)
    context.user_data[h.NEW_DRAFT_KEY] = {
        "nickname": "Viajes", "bank": "BAC", "credit_limit": h.parse_credit_limit("100"),
        "cut_day": 5, "payment_days": 15,
    }
    state, update = await send(h.new_card_last_four, "4111111111111111", context)
    assert state == h.LAST_FOUR
    update.effective_message.delete.assert_awaited_once()
    state, update = await send(h.new_card_last_four, "saltar", context)
    assert state == h.CONFIRM
    assert "Resumen" in reply_text_of(update)
    assert update.effective_message.reply_text.call_args.kwargs["reply_markup"] is not None

@respx.mock
async def test_confirm_creates_card(client):
    route = respx.post(f"{API_URL}/cards").mock(return_value=httpx.Response(201, json=CARD_JSON))
    context = make_context(client)
    context.user_data[h.NEW_DRAFT_KEY] = {
        "nickname": "Viajes", "bank": "BAC", "credit_limit": h.parse_credit_limit("100"),
        "cut_day": 5, "payment_days": 15, "last_four": None,
    }
    update = make_update(callback_data="nueva:ok")
    assert await h.new_card_confirm(update, context) == END
    assert json.loads(route.calls[0].request.content)["creditLimit"] == "100.00"
    assert "guardada" in reply_text_of(update)
    assert h.NEW_DRAFT_KEY not in context.user_data

@respx.mock
async def test_confirm_duplicate_goes_back_to_nickname(client):
    respx.post(f"{API_URL}/cards").mock(return_value=httpx.Response(409))
    context = make_context(client)
    context.user_data[h.NEW_DRAFT_KEY] = {
        "nickname": "Viajes", "bank": "BAC", "credit_limit": h.parse_credit_limit("100"),
        "cut_day": 5, "payment_days": 15,
    }
    update = make_update(callback_data="nueva:ok")
    assert await h.new_card_confirm(update, context) == h.NICKNAME
    assert "Ya existe" in reply_text_of(update)

@respx.mock
async def test_confirm_surfaces_api_validation_error(client):
    body = {"error": "Datos inválidos", "details": [{"path": ["bank"], "message": "Required"}]}
    respx.post(f"{API_URL}/cards").mock(return_value=httpx.Response(400, json=body))
    context = make_context(client)
    context.user_data[h.NEW_DRAFT_KEY] = {
        "nickname": "V", "bank": "B", "credit_limit": h.parse_credit_limit("1"),
        "cut_day": 5, "payment_days": 15,
    }
    update = make_update(callback_data="nueva:ok")
    assert await h.new_card_confirm(update, context) == END
    assert "bank: Required" in reply_text_of(update)

async def test_cancel_clears_draft_and_ends(client):
    context = make_context(client)
    context.user_data[h.NEW_DRAFT_KEY] = {"nickname": "x"}
    state, update = await send(h.cancel_conversation, "/cancelar", context)
    assert state == END and h.NEW_DRAFT_KEY not in context.user_data
    assert "Cancelado" in reply_text_of(update)

# --- /editartarjeta ----------------------------------------------------------

@respx.mock
async def test_edit_flow(client):
    patch_route = respx.patch(f"{API_URL}/cards/Viajes").mock(return_value=httpx.Response(200, json={}))
    respx.get(f"{API_URL}/cards").mock(
        return_value=httpx.Response(200, json=[{**CARD_JSON, "creditLimit": "2000.50"}])
    )
    context = make_context(client, ["viajes"])
    update = make_update()
    assert await h.edit_card_start(update, context) == h.CHOOSE_FIELD
    assert update.effective_message.reply_text.call_args.kwargs["reply_markup"] is not None

    pick = make_update(callback_data="edit:limit")
    assert await h.edit_card_pick_field(pick, context) == h.NEW_VALUE

    state, bad = await send(h.edit_card_apply, "mucho", context)
    assert state == h.NEW_VALUE and not patch_route.called

    state, ok = await send(h.edit_card_apply, "2000.50", context)
    assert state == END
    assert json.loads(patch_route.calls[0].request.content) == {"creditLimit": "2000.50"}
    assert "actualizada" in reply_text_of(ok)

async def test_edit_refuses_full_card_number(client):
    context = make_context(client)
    context.user_data[h.EDIT_TARGET_KEY] = {"nickname": "Viajes", "field": "last_four"}
    state, update = await send(h.edit_card_apply, "4111111111111111", context)
    assert state == h.NEW_VALUE
    update.effective_message.delete.assert_awaited_once()

@respx.mock
async def test_edit_unknown_card(client):
    respx.get(f"{API_URL}/cards").mock(return_value=httpx.Response(200, json=[]))
    update = make_update()
    assert await h.edit_card_start(update, make_context(client, ["nada"])) == END
    assert "No encontré" in reply_text_of(update)

def test_edit_keyboard_offers_all_five_fields():
    data = [b.callback_data for row in h.edit_keyboard().inline_keyboard for b in row]
    assert data == [
        "edit:bank", "edit:limit", "edit:cut_day", "edit:payment_days", "edit:last_four", "edit:cancel",
    ]

# --- /borrartarjeta ----------------------------------------------------------

@respx.mock
async def test_delete_flow_yes(client):
    respx.get(f"{API_URL}/cards").mock(return_value=httpx.Response(200, json=[CARD_JSON]))
    route = respx.delete(f"{API_URL}/cards/Viajes").mock(return_value=httpx.Response(204))
    context = make_context(client, ["Viajes"])
    await h.delete_card_start(make_update(), context)
    update = make_update(callback_data="borrar:si")
    await h.delete_card_answer(update, context)
    assert route.called and "borrada" in reply_text_of(update)

@respx.mock
async def test_delete_flow_no_and_expired(client):
    respx.get(f"{API_URL}/cards").mock(return_value=httpx.Response(200, json=[CARD_JSON]))
    route = respx.delete(f"{API_URL}/cards/Viajes").mock(return_value=httpx.Response(204))
    context = make_context(client, ["Viajes"])
    await h.delete_card_start(make_update(), context)
    update = make_update(callback_data="borrar:no")
    await h.delete_card_answer(update, context)
    assert not route.called and "No se borró" in reply_text_of(update)
    update = make_update(callback_data="borrar:si")
    await h.delete_card_answer(update, context)
    assert not route.called and "expiró" in reply_text_of(update)

# --- recordatorio ------------------------------------------------------------

@respx.mock
async def test_reminder_sends_only_when_due(client):
    respx.get(f"{API_URL}/cards").mock(return_value=httpx.Response(200, json=[CARD_JSON]))
    context = make_context(client)
    with patch.object(h, "today_in_el_salvador", return_value=date(2026, 10, 1)):
        await h.send_card_reminders(context)
    context.bot.send_message.assert_not_called()
    with patch.object(h, "today_in_el_salvador", return_value=date(2026, 10, 13)):
        await h.send_card_reminders(context)
    assert "Corte en 2 días" in context.bot.send_message.call_args.args[1]

@respx.mock
async def test_reminder_reports_api_down(client):
    respx.get(f"{API_URL}/cards").mock(side_effect=httpx.ConnectError("down"))
    context = make_context(client)
    await h.send_card_reminders(context)
    assert "no responde" in context.bot.send_message.call_args.args[1]

# --- registro ----------------------------------------------------------------

def test_register_adds_handlers_and_daily_job():
    app = Application.builder().token("123456:test-token").build()
    h.register_tarjetas(app)
    assert h.CLIENT_KEY in app.bot_data
    jobs = app.job_queue.get_jobs_by_name("tarjetas-recordatorio")
    assert len(jobs) == 1
    commands = {c for handler in app.handlers[0] for c in getattr(handler, "commands", [])}
    assert {"tarjetas", "tarjeta", "proxcorte", "borrartarjeta"} <= commands
    entry_points = [
        c for handler in app.handlers[0] if isinstance(handler, ConversationHandler)
        for e in handler.entry_points for c in e.commands
    ]
    assert set(entry_points) == {"nuevatarjeta", "editartarjeta"}
