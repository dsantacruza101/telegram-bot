import functools
import logging
import warnings
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot import CHAT_ID, reply, restricted
from tarjetas_api import (
    CardAlreadyExists,
    CardNotFound,
    NewCard,
    TarjetasApiClient,
    TarjetasApiError,
)
from tarjetas_format import (
    esc,
    format_card_detail,
    format_card_list,
    format_new_card_summary,
    format_next_cut,
)
from tarjetas_reminders import (
    REMINDER_TIME,
    days_ahead_from_env,
    format_reminder,
    select_alerts,
    today_in_el_salvador,
)
from tarjetas_validation import (
    FullCardNumberRejected,
    InvalidInput,
    parse_bank,
    parse_credit_limit,
    parse_cut_day,
    parse_last_four,
    parse_last_four_optional,
    parse_nickname,
    parse_payment_days,
    parse_payment_days_or_default,
)

logger = logging.getLogger("server-bot")

Context = ContextTypes.DEFAULT_TYPE
CLIENT_KEY = "tarjetas_client"
NEW_DRAFT_KEY = "tarjeta_nueva"
EDIT_TARGET_KEY = "tarjeta_editar"
DELETE_TARGET_KEY = "tarjeta_borrar"
END = ConversationHandler.END

NICKNAME, BANK, LIMIT, CUT_DAY, PAYMENT_DAYS, LAST_FOUR, CONFIRM = range(7)
CHOOSE_FIELD, NEW_VALUE = range(2)

TEXT_ONLY = filters.TEXT & ~filters.COMMAND

def api(context: Context) -> TarjetasApiClient:
    return context.application.bot_data[CLIENT_KEY]

# Los errores de la API se traducen a un mensaje amable en lugar de dejar
# que lleguen a on_error; END cierra cualquier conversación en curso.
def handle_api_errors(handler: Callable[[Update, Context], Awaitable[int | None]]):
    @functools.wraps(handler)
    async def wrapper(update: Update, context: Context) -> int | None:
        try:
            return await handler(update, context)
        except TarjetasApiError as exc:
            await reply(update, f"❌ {esc(exc.message)}", parse_mode="HTML")
            return END

    return wrapper

def nickname_from_args(context: Context) -> str:
    return " ".join(context.args or []).strip()

async def reply_usage(update: Update, usage: str) -> None:
    await reply(update, f"Uso: {esc(usage)}", parse_mode="HTML")

async def delete_sensitive_message(update: Update) -> None:
    message = update.effective_message
    if message is None:
        return
    try:
        await message.delete()
    except TelegramError:
        logger.info("No se pudo borrar un mensaje con un número de tarjeta")

# --- Consultas -------------------------------------------------------------

@restricted
@handle_api_errors
async def tarjetas(update: Update, context: Context) -> None:
    cards = await api(context).list_cards()
    await reply(update, format_card_list(cards), parse_mode="HTML")

@restricted
@handle_api_errors
async def tarjeta(update: Update, context: Context) -> None:
    nickname = nickname_from_args(context)
    if not nickname:
        await reply_usage(update, "/tarjeta <apodo>")
        return
    card = await api(context).get_card(nickname)
    await reply(update, format_card_detail(card), parse_mode="HTML")

@restricted
@handle_api_errors
async def proxcorte(update: Update, context: Context) -> None:
    try:
        card = await api(context).next_card()
    except CardNotFound:
        await reply(update, "No tienes tarjetas registradas.")
        return
    await reply(update, format_next_cut(card), parse_mode="HTML")

# --- Pasos de conversación -------------------------------------------------

async def cancel_conversation(update: Update, context: Context) -> int:
    for key in (NEW_DRAFT_KEY, EDIT_TARGET_KEY):
        context.user_data.pop(key, None)
    await reply(update, "❌ Cancelado.")
    return END

async def reject_invalid_input(update: Update, error: InvalidInput) -> None:
    if isinstance(error, FullCardNumberRejected):
        await delete_sensitive_message(update)
        await reply(update, f"🚫 {esc(str(error))}", parse_mode="HTML")
        return
    await reply(update, f"⚠️ {esc(str(error))}\nIntenta de nuevo o usa /cancelar.", parse_mode="HTML")

def inline_keyboard(*rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=data) for label, data in row] for row in rows]
    )

# --- /nuevatarjeta ---------------------------------------------------------

@restricted
async def new_card_start(update: Update, context: Context) -> int:
    context.user_data[NEW_DRAFT_KEY] = {}
    await reply(
        update,
        "💳 <b>Nueva tarjeta</b>\n\n"
        "Solo guardo los últimos 4 dígitos; nunca me envíes el número completo ni el CVV.\n"
        "Usa /cancelar para salir en cualquier momento.\n\n"
        "¿Qué apodo le pones? (por ejemplo: Viajes)",
        parse_mode="HTML",
    )
    return NICKNAME

def draft_step(
    key: str,
    parse: Callable[[str], Any],
    current_state: int,
    next_state: int,
    next_prompt: str,
):
    """Crea un paso que valida el texto, lo guarda en el borrador y avanza."""

    @restricted
    async def step(update: Update, context: Context) -> int:
        try:
            value = parse(update.effective_message.text)
        except InvalidInput as error:
            await reject_invalid_input(update, error)
            return current_state
        context.user_data.setdefault(NEW_DRAFT_KEY, {})[key] = value
        await reply(update, next_prompt, parse_mode="HTML")
        return next_state

    return step

def draft_to_new_card(draft: dict[str, Any]) -> NewCard:
    return NewCard(
        nickname=draft["nickname"],
        bank=draft["bank"],
        credit_limit=draft["credit_limit"],
        cut_day=draft["cut_day"],
        payment_days_after_cut=draft["payment_days"],
        last_four=draft.get("last_four"),
    )

@restricted
async def new_card_last_four(update: Update, context: Context) -> int:
    try:
        last_four = parse_last_four_optional(update.effective_message.text)
    except InvalidInput as error:
        await reject_invalid_input(update, error)
        return LAST_FOUR
    draft = context.user_data.setdefault(NEW_DRAFT_KEY, {})
    draft["last_four"] = last_four
    card = draft_to_new_card(draft)
    await reply(
        update,
        format_new_card_summary(card, draft["payment_days"]),
        parse_mode="HTML",
        reply_markup=inline_keyboard([("✅ Confirmar", "nueva:ok"), ("❌ Cancelar", "nueva:no")]),
    )
    return CONFIRM

@restricted
async def new_card_confirm_hint(update: Update, context: Context) -> int:
    await reply(update, "Usa los botones Confirmar/Cancelar o /cancelar.")
    return CONFIRM

async def drop_keyboard(update: Update) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)

@restricted
@handle_api_errors
async def new_card_confirm(update: Update, context: Context) -> int:
    await drop_keyboard(update)
    draft = context.user_data.get(NEW_DRAFT_KEY)
    if not draft:
        await reply(update, "Esta conversación expiró. Usa /nuevatarjeta otra vez.")
        return END
    try:
        await api(context).create_card(draft_to_new_card(draft))
    except CardAlreadyExists as exc:
        await reply(update, f"❌ {esc(exc.message)}. Escribe otro apodo o usa /cancelar.", parse_mode="HTML")
        return NICKNAME
    context.user_data.pop(NEW_DRAFT_KEY, None)
    await reply(update, f"✅ Tarjeta <b>{esc(draft['nickname'])}</b> guardada.", parse_mode="HTML")
    return END

@restricted
async def new_card_cancel_button(update: Update, context: Context) -> int:
    await drop_keyboard(update)
    return await cancel_conversation(update, context)

def build_new_card_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("nuevatarjeta", new_card_start)],
        states={
            NICKNAME: [MessageHandler(TEXT_ONLY, draft_step(
                "nickname", parse_nickname, NICKNAME, BANK, "¿De qué banco es?"))],
            BANK: [MessageHandler(TEXT_ONLY, draft_step(
                "bank", parse_bank, BANK, LIMIT, "¿Cuál es el límite de crédito? (por ejemplo: 1500 o 1500.50)"))],
            LIMIT: [MessageHandler(TEXT_ONLY, draft_step(
                "credit_limit", parse_credit_limit, LIMIT, CUT_DAY, "¿Qué día del mes es el corte? (1-31)"))],
            CUT_DAY: [MessageHandler(TEXT_ONLY, draft_step(
                "cut_day", parse_cut_day, CUT_DAY, PAYMENT_DAYS,
                "¿Cuántos días después del corte vence el pago? (1-60)\n"
                "Escribe un número o «saltar» para usar 15."))],
            PAYMENT_DAYS: [MessageHandler(TEXT_ONLY, draft_step(
                "payment_days", parse_payment_days_or_default, PAYMENT_DAYS, LAST_FOUR,
                "¿Últimos 4 dígitos de la tarjeta? Escribe los 4 números o «saltar»."))],
            LAST_FOUR: [MessageHandler(TEXT_ONLY, new_card_last_four)],
            CONFIRM: [
                CallbackQueryHandler(new_card_confirm, pattern=r"^nueva:ok$"),
                CallbackQueryHandler(new_card_cancel_button, pattern=r"^nueva:no$"),
                MessageHandler(TEXT_ONLY, new_card_confirm_hint),
            ],
        },
        fallbacks=[CommandHandler("cancelar", restricted(cancel_conversation))],
    )

# --- /editartarjeta --------------------------------------------------------

@dataclass(frozen=True)
class EditField:
    label: str
    api_key: str
    parse: Callable[[str], Any]
    hint: str

def _limit_as_api_value(text: str) -> str:
    amount: Decimal = parse_credit_limit(text)
    return f"{amount:.2f}"

EDIT_FIELDS: dict[str, EditField] = {
    "bank": EditField("Banco", "bank", parse_bank, "Escribe el nuevo banco."),
    "limit": EditField("Límite", "creditLimit", _limit_as_api_value, "Escribe el nuevo límite (por ejemplo 2000.50)."),
    "cut_day": EditField("Día de corte", "cutDay", parse_cut_day, "Escribe el nuevo día de corte (1-31)."),
    "payment_days": EditField("Días de pago", "paymentDaysAfterCut", parse_payment_days, "Escribe los días de pago tras el corte (1-60)."),
    "last_four": EditField("Últimos 4", "lastFour", parse_last_four, "Escribe los 4 dígitos finales."),
}
EDIT_FIELD_PATTERN = r"^edit:(" + "|".join(EDIT_FIELDS) + r")$"

def edit_keyboard() -> InlineKeyboardMarkup:
    buttons = [(field.label, f"edit:{key}") for key, field in EDIT_FIELDS.items()]
    return inline_keyboard(buttons[:3], buttons[3:], [("❌ Cancelar", "edit:cancel")])

@restricted
@handle_api_errors
async def edit_card_start(update: Update, context: Context) -> int:
    nickname = nickname_from_args(context)
    if not nickname:
        await reply_usage(update, "/editartarjeta <apodo>")
        return END
    card = await api(context).get_card(nickname)
    context.user_data[EDIT_TARGET_KEY] = {"nickname": card.nickname}
    await reply(
        update,
        f"✏️ ¿Qué campo de <b>{esc(card.nickname)}</b> quieres editar?",
        parse_mode="HTML",
        reply_markup=edit_keyboard(),
    )
    return CHOOSE_FIELD

@restricted
async def edit_card_pick_field(update: Update, context: Context) -> int:
    await drop_keyboard(update)
    target = context.user_data.get(EDIT_TARGET_KEY)
    if not target:
        await reply(update, "Esta conversación expiró. Usa /editartarjeta otra vez.")
        return END
    field_key = update.callback_query.data.split(":", 1)[1]
    target["field"] = field_key
    await reply(update, f"{esc(EDIT_FIELDS[field_key].hint)}\nUsa /cancelar para salir.", parse_mode="HTML")
    return NEW_VALUE

@restricted
@handle_api_errors
async def edit_card_apply(update: Update, context: Context) -> int:
    target = context.user_data.get(EDIT_TARGET_KEY)
    if not target or "field" not in target:
        await reply(update, "Esta conversación expiró. Usa /editartarjeta otra vez.")
        return END
    field = EDIT_FIELDS[target["field"]]
    try:
        value = field.parse(update.effective_message.text)
    except InvalidInput as error:
        await reject_invalid_input(update, error)
        return NEW_VALUE
    card = await api(context).update_card(target["nickname"], {field.api_key: value})
    context.user_data.pop(EDIT_TARGET_KEY, None)
    await reply(update, f"✅ Tarjeta actualizada.\n\n{format_card_detail(card)}", parse_mode="HTML")
    return END

@restricted
async def edit_card_cancel_button(update: Update, context: Context) -> int:
    await drop_keyboard(update)
    return await cancel_conversation(update, context)

def build_edit_card_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("editartarjeta", edit_card_start)],
        states={
            CHOOSE_FIELD: [
                CallbackQueryHandler(edit_card_pick_field, pattern=EDIT_FIELD_PATTERN),
                CallbackQueryHandler(edit_card_cancel_button, pattern=r"^edit:cancel$"),
            ],
            NEW_VALUE: [MessageHandler(TEXT_ONLY, edit_card_apply)],
        },
        fallbacks=[CommandHandler("cancelar", restricted(cancel_conversation))],
    )

# --- /borrartarjeta --------------------------------------------------------

@restricted
@handle_api_errors
async def delete_card_start(update: Update, context: Context) -> None:
    nickname = nickname_from_args(context)
    if not nickname:
        await reply_usage(update, "/borrartarjeta <apodo>")
        return
    card = await api(context).get_card(nickname)
    # El apodo no cabe de forma fiable en callback_data (64 bytes), se guarda aparte.
    context.user_data[DELETE_TARGET_KEY] = card.nickname
    await reply(
        update,
        f"🗑️ ¿Seguro que quieres borrar <b>{esc(card.nickname)}</b>? No se puede deshacer.",
        parse_mode="HTML",
        reply_markup=inline_keyboard([("Sí, borrar", "borrar:si"), ("No", "borrar:no")]),
    )

@restricted
@handle_api_errors
async def delete_card_answer(update: Update, context: Context) -> None:
    await drop_keyboard(update)
    nickname = context.user_data.pop(DELETE_TARGET_KEY, None)
    if nickname is None:
        await reply(update, "Esta confirmación expiró. Usa /borrartarjeta otra vez.")
        return
    if update.callback_query.data != "borrar:si":
        await reply(update, "👍 No se borró nada.")
        return
    await api(context).delete_card(nickname)
    await reply(update, f"🗑️ Tarjeta <b>{esc(nickname)}</b> borrada.", parse_mode="HTML")

# --- Recordatorio diario ---------------------------------------------------

async def send_card_reminders(context: Context) -> None:
    try:
        cards = await api(context).list_cards()
    except TarjetasApiError as exc:
        logger.warning("Recordatorio de tarjetas omitido: %s", exc.message)
        await context.bot.send_message(
            CHAT_ID, f"⚠️ No pude revisar tus tarjetas: {esc(exc.message)}", parse_mode="HTML"
        )
        return
    alerts = select_alerts(cards, today_in_el_salvador(), days_ahead_from_env())
    if alerts:
        await context.bot.send_message(CHAT_ID, format_reminder(alerts), parse_mode="HTML")

# --- Registro --------------------------------------------------------------

def register_tarjetas(app: Application) -> None:
    app.bot_data[CLIENT_KEY] = TarjetasApiClient()
    app.add_handler(CommandHandler("tarjetas", tarjetas))
    app.add_handler(CommandHandler("tarjeta", tarjeta))
    app.add_handler(CommandHandler("proxcorte", proxcorte))
    app.add_handler(CommandHandler("borrartarjeta", delete_card_start))
    app.add_handler(CallbackQueryHandler(delete_card_answer, pattern=r"^borrar:(si|no)$"))
    # PTB avisa de que los CallbackQueryHandler de una conversación no se
    # distinguen por mensaje; aquí solo hay una conversación activa por usuario.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app.add_handler(build_new_card_conversation())
        app.add_handler(build_edit_card_conversation())
    if app.job_queue is None:
        logger.warning("JobQueue no disponible (falta python-telegram-bot[job-queue]); sin recordatorios")
        return
    app.job_queue.run_daily(send_card_reminders, REMINDER_TIME, name="tarjetas-recordatorio")
