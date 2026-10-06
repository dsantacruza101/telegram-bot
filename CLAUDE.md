# Alfred (telegram-bot)

Bot de Telegram en Python 3 + python-telegram-bot 22.8, corre como servicio systemd `telegram-bot`
(`sudo systemctl restart telegram-bot`, logs con `sudo journalctl -u telegram-bot -f`).
Variables desde `/etc/telegram-bot.env` — NUNCA editar ni commitear `.env`. Ver README para la lista.

## Convenciones
- Todo handler va con `@restricted` (bot.py); responder con `reply()` y `parse_mode="HTML"`.
- Todo texto dinámico se escapa (`html.escape` / `esc()` / `pre()` / `code()`).
- Nunca loguear el token ni texto del usuario (ver `redact`).
- Nombres y mensajes en español; commits conventional commits en español.
- Ramas: `main` producción, `dev` desarrollo; deploy del bot es manual.

## Tarjetas
- API local `tarjetas` en `TARJETAS_API_URL` (default `http://127.0.0.1:3100`); NO modificarla desde este repo.
- Comandos: `/tarjetas`, `/tarjeta`, `/proxcorte`, `/nuevatarjeta`, `/editartarjeta`, `/borrartarjeta`, `/cancelar`.
- Recordatorio diario 08:00 America/El_Salvador (JobQueue); `TARJETAS_REMINDER_DAYS` (default 3).
- Jamás pedir ni aceptar número completo/CVV: solo últimos 4 (`tarjetas_validation.py`).
- La API exige `creditLimit` como string y días como números.

## Tests
`.venv-dev/bin/pytest` (pytest + respx, sin red). `bot.py` exige `TELEGRAM_TOKEN` y `CHAT_ID` al importarse;
`tests/conftest.py` los define. CI: tests con cobertura + SonarCloud.
