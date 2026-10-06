# Alfred — Telegram bot del servidor

Bot de Telegram (python-telegram-bot 22.x) para administrar el servidor y las tarjetas de crédito.
Solo responde al usuario con `CHAT_ID` (decorador `@restricted`).

## Comandos

Servidor: `/status`, `/containers`, `/deploy`, `/logs`, `/disk`, `/ip`, `/claude <tarea>`, `/chat inicio|fin`.

Tarjetas (consumen la API local `tarjetas`):

| Comando | Descripción |
|---|---|
| `/tarjetas` | Lista compacta: apodo, banco, límite, próximo corte (días restantes) y fecha de pago |
| `/tarjeta <apodo>` | Detalle completo de una tarjeta |
| `/proxcorte` | Tarjeta con el corte más cercano |
| `/nuevatarjeta` | Asistente: apodo, banco, límite, día de corte, días de pago (default 15, «saltar»), últimos 4 (opcional), resumen con Confirmar/Cancelar |
| `/editartarjeta <apodo>` | Botones para elegir el campo (banco, límite, día de corte, días de pago, últimos 4) y nuevo valor |
| `/borrartarjeta <apodo>` | Confirmación Sí/No y borrado |
| `/cancelar` | Sale de cualquier asistente |

Alfred nunca guarda ni acepta números de tarjeta completos ni CVV: si se escriben 12 o más
dígitos seguidos, rechaza el mensaje (e intenta borrarlo del chat). Solo se guardan los últimos 4.

### Recordatorio diario

Todos los días a las 08:00 (America/El_Salvador) Alfred revisa las tarjetas y, si el corte o el pago
caen entre hoy y N días, envía un único mensaje ("Corte en N días", "Pago vence en N días").
Si no hay nada próximo, no envía nada. Requiere `python-telegram-bot[job-queue]`; sin él el bot
arranca igual pero sin recordatorios (queda un warning en el log).

## Variables de entorno

Cargadas por systemd desde `/etc/telegram-bot.env` (nunca se commitean).

| Variable | Obligatoria | Default | Uso |
|---|---|---|---|
| `TELEGRAM_TOKEN` | sí | — | Token del bot |
| `CHAT_ID` | sí | — | Único usuario autorizado |
| `WEBHOOK_SECRET` | para `/deploy` | — | HMAC del webhook de deploy |
| `TARJETAS_API_URL` | no | `http://127.0.0.1:3100` | URL base de la API de tarjetas |
| `TARJETAS_REMINDER_DAYS` | no | `3` | Días de anticipación del recordatorio |

## Estructura

- `bot.py` — handlers del servidor, autorización, registro de comandos.
- `tarjetas_api.py` — cliente httpx async, modelos y excepciones tipadas.
- `tarjetas_validation.py` — validación local de la entrada (incluye rechazo de números completos).
- `tarjetas_format.py` — formato HTML de los mensajes.
- `tarjetas_reminders.py` — selección y texto del recordatorio.
- `tarjetas_handlers.py` — comandos, conversaciones, job diario y `register_tarjetas`.

## Desarrollo

```bash
python3 -m venv .venv-dev && .venv-dev/bin/pip install -r requirements-dev.txt
.venv-dev/bin/pytest
```

Los tests no usan red (HTTP mockeado con respx). Producción usa `venv/` con `requirements.txt`.
Ramas: `main` producción, `dev` desarrollo; commits en español (conventional commits).
