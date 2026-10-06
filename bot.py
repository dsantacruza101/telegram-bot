import asyncio
import functools
import hashlib
import hmac
import html
import logging
import os
import sys
import time

import psutil
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s — %(message)s", level=logging.INFO
)
logger = logging.getLogger("server-bot")

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))

# Seguridad — solo tú puedes usar el bot
def authorized(update: Update) -> bool:
    # effective_user es None en updates sin autor (canales, posts editados
    # por el canal); sin usuario no hay nada que autorizar.
    user = update.effective_user
    return user is not None and user.id == CHAT_ID

# Envolver el handler hace que olvidar la autorizacion sea imposible: un
# handler sin @restricted salta a la vista, uno sin el `if` no.
def restricted(handler):
    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not authorized(update):
            return
        return await handler(update, context)

    return wrapper

# Telegram rechaza el mensaje entero si el output lleva ` o _, así que
# todo lo dinámico va escapado como HTML.
def pre(text: str) -> str:
    return f"<pre>{html.escape(text.strip()) or '(sin salida)'}</pre>"

def code(text: str) -> str:
    return f"<code>{html.escape(text.strip())}</code>"

# python-telegram-bot mete la URL de la API (con el token dentro) en el texto
# de varias excepciones de red, así que nunca sale crudo del proceso.
def redact(text: str) -> str:
    return text.replace(TOKEN, "<token>") if TOKEN else text

# update.message es None cuando el update es una edición o viene de un canal;
# un único punto de guarda evita repetir el `if` en cada handler.
async def reply(update: Update, text: str, **kwargs) -> None:
    message = update.effective_message
    if message is None:
        logger.warning("Update sin mensaje, no se puede responder")
        return
    await message.reply_text(text, **kwargs)

async def run(cmd: list[str], timeout: int = 30) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return f"❌ Comando no encontrado: {cmd[0]}"

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        # create_subprocess_exec no mata el hijo al expirar, a diferencia de
        # subprocess.run; sin esto quedaria huerfano corriendo.
        proc.kill()
        await proc.wait()
        return f"⏱️ Timeout tras {timeout}s"

    out = stdout.decode(errors="replace")
    return out or stderr.decode(errors="replace")

@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(
        update,
        "🤖 <b>DSantacruz Server Bot</b>\n\n"
        "Comandos disponibles:\n"
        "/status — Estado del servidor\n"
        "/containers — Estado de Docker\n"
        "/deploy — Trigger deploy portfolio\n"
        "/logs — Últimos logs de Nginx\n"
        "/disk — Uso del disco\n"
        "/ip — IP pública\n"
        "/claude &lt;tarea&gt; — Delegar a Claude Code\n"
        "/chat inicio|fin — Modo conversación con Claude Code\n\n"
        "💳 Tarjetas:\n"
        "/tarjetas — Lista de tarjetas\n"
        "/tarjeta &lt;apodo&gt; — Detalle de una tarjeta\n"
        "/proxcorte — Próximo corte\n"
        "/nuevatarjeta — Agregar tarjeta\n"
        "/editartarjeta &lt;apodo&gt; — Editar tarjeta\n"
        "/borrartarjeta &lt;apodo&gt; — Borrar tarjeta\n"
        "/cancelar — Salir de un asistente",
        parse_mode="HTML"
    )

def cpu_temp() -> str:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return f"{int(f.read().strip()) / 1000:.1f}°C"
    except (OSError, ValueError):
        return "N/A"

@restricted
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    up = int(time.time() - psutil.boot_time())

    msg = (
        f"🖥️ <b>Estado del Servidor</b>\n\n"
        f"🔥 CPU: <code>{cpu}%</code>\n"
        f"💾 RAM: <code>{ram.used // (1024**3)}GB / {ram.total // (1024**3)}GB ({ram.percent}%)</code>\n"
        f"🌡️ Temperatura: <code>{cpu_temp()}</code>\n"
        f"⚡ Uptime: <code>{up // 86400}d {up % 86400 // 3600}h</code>"
    )
    await reply(update, msg, parse_mode="HTML")

@restricted
async def containers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    out = await run(["docker", "ps", "--format", "{{.Names}} — {{.Status}}"])
    await reply(
        update, f"🐳 <b>Containers Docker</b>\n\n{pre(out[:3000])}", parse_mode="HTML"
    )

@restricted
async def deploy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update, "🚀 Iniciando deploy del portafolio...")

    secret = os.getenv("WEBHOOK_SECRET")
    payload = '{"ref":"refs/heads/main"}'
    signature = "sha256=" + hmac.new(
        secret.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()

    out = await run(
        ["curl", "-s", "-X", "POST",
         "https://webhook.dsantacruz.com/deploy/portfolio",
         "-H", "Content-Type: application/json",
         "-H", f"X-Hub-Signature-256: {signature}",
         "-d", payload],
        timeout=60
    )
    await reply(
        update, f"✅ Deploy triggered: {pre(out[:3000])}", parse_mode="HTML"
    )

@restricted
async def logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    out = await run(["tail", "-20", "/var/log/nginx/access.log"])
    await reply(
        update, f"📋 <b>Últimos logs Nginx</b>\n\n{pre(out[-3000:])}", parse_mode="HTML"
    )

@restricted
async def disk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    disk = psutil.disk_usage('/')
    msg = (
        f"💿 <b>Uso del Disco</b>\n\n"
        f"Total: <code>{disk.total // (1024**3)}GB</code>\n"
        f"Usado: <code>{disk.used // (1024**3)}GB</code>\n"
        f"Libre: <code>{disk.free // (1024**3)}GB</code>\n"
        f"Porcentaje: <code>{disk.percent}%</code>"
    )
    await reply(update, msg, parse_mode="HTML")

@restricted
async def ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    out = await run(["curl", "-s", "ifconfig.me"], timeout=15)
    await reply(
        update, f"🌐 IP pública: {code(out[:200])}", parse_mode="HTML"
    )

@restricted
async def claude_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await reply(update, "Uso: /claude <tarea>")
        return
    tarea = " ".join(context.args)
    await reply(
        update, f"🤖 Delegando a Claude Code: {code(tarea)}", parse_mode="HTML"
    )
    out = await run(["/home/dsantacruz/.nvm/versions/node/v22.23.2/bin/claude", "-p", tarea], timeout=300)
    await reply(
        update, f"✅ <b>Claude responde:</b>\n\n{pre(out[:3500])}", parse_mode="HTML"
    )

@restricted
async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    accion = context.args[0].lower() if context.args else ""
    if accion == "inicio":
        context.user_data["chat_mode"] = True
        context.user_data["chat_history"] = []
        await reply(
            update,
            "💬 <b>Modo conversación</b>\n\n"
            "Estado: <code>activado</code>\n\n"
            "Cualquier mensaje sin / se enviará a Claude Code manteniendo el historial. "
            "Usa /chat fin para salir.",
            parse_mode="HTML"
        )
    elif accion == "fin":
        context.user_data["chat_mode"] = False
        context.user_data["chat_history"] = []
        await reply(
            update,
            "💬 <b>Modo conversación</b>\n\n"
            "Estado: <code>desactivado</code>\n\n"
            "Historial borrado.",
            parse_mode="HTML"
        )
    else:
        await reply(update, "Uso: /chat inicio | /chat fin")

@restricted
async def chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("chat_mode"):
        return
    message = update.effective_message
    if message is None or not message.text:
        return

    history = context.user_data.setdefault("chat_history", [])
    history.append({"role": "Usuario", "text": message.text})

    transcript = "\n\n".join(f"{h['role']}: {h['text']}" for h in history)
    out = await run(
        ["/home/dsantacruz/.nvm/versions/node/v22.23.2/bin/claude", "-p", transcript],
        timeout=300
    )
    history.append({"role": "Claude", "text": out})

    await reply(update, pre(out[:3500]), parse_mode="HTML")

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Error en handler", exc_info=context.error)
    try:
        await context.bot.send_message(
            CHAT_ID,
            f"⚠️ <b>Error en el bot</b>\n\n{pre(redact(str(context.error))[:1000])}",
            parse_mode="HTML"
        )
    except Exception:
        logger.exception("No se pudo notificar el error por Telegram")

def main():
    # Al correr como script este módulo es __main__; el alias evita que el
    # `from bot import ...` de tarjetas_handlers cargue una segunda copia.
    sys.modules.setdefault("bot", sys.modules[__name__])
    from tarjetas_handlers import register_tarjetas

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("containers", containers))
    app.add_handler(CommandHandler("deploy", deploy))
    app.add_handler(CommandHandler("logs", logs))
    app.add_handler(CommandHandler("disk", disk))
    app.add_handler(CommandHandler("ip", ip))
    app.add_handler(CommandHandler("claude", claude_task))
    app.add_handler(CommandHandler("chat", chat))
    # Antes de chat_message: las conversaciones de tarjetas tienen prioridad
    # sobre el modo chat para los mensajes de texto.
    register_tarjetas(app)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_message))
    app.add_error_handler(on_error)
    logger.info("🤖 Bot corriendo...")
    app.run_polling()

if __name__ == "__main__":
    main()
