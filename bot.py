#!/usr/bin/env python3
"""
CleanyGo Bot - Entrada final para Railway
Webhook + handlers + requests + send_safe
"""

import os
import sys
import json
from telebot import TeleBot
from flask import Flask, jsonify, request
from telebot.types import Update

# ==================== 1. TOKEN ====================
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN no definido en Variables de entorno")

print(f"[INIT] Token: {TOKEN[:10]}...", file=sys.stderr)

# ==================== 2. CREAR BOT ====================
bot = TeleBot(TOKEN, parse_mode="HTML")
print(f"[INIT] Bot creado: {id(bot)}", file=sys.stderr)

# ==================== 3. INYECTAR EN CONFIG ====================
from config import inject_bot, init_db as config_init_db, logger

inject_bot(bot)
print("[INIT] ✅ Bot inyectado en config", file=sys.stderr)

# ==================== 4. INICIALIZAR DB ====================
config_init_db()
print("[INIT] ✅ DB inicializada desde config", file=sys.stderr)

# ==================== 5. FUNCIONES UTILES ====================
def send_safe(chat_id, text, reply_markup=None, parse_mode="HTML"):
    """Envía mensaje de forma segura"""
    try:
        return bot.send_message(
            chat_id,
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except Exception as e:
        logger.error(f"[SEND ERROR] {e} | ChatID: {chat_id}")
        return None


def edit_safe(chat_id, message_id, text, reply_markup=None):
    """Edita mensaje de forma segura"""
    try:
        return bot.edit_message_text(
            text,
            chat_id,
            message_id,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"[EDIT ERROR] {e} | MessageID: {message_id}")
        return None


# ==================== 6. CARGAR HANDLERS ====================
try:

    import handlers.common
    import handlers.client.flow
    import handlers.client.search
    import handlers.client.callbacks

    import handlers.worker.flow
    import handlers.worker.jobs
    import handlers.worker.profile
    import handlers.worker.main

    print("[INIT] ✅ Handlers cargados", file=sys.stderr)

except Exception as e:

    print(f"[INIT] ❌ Error handlers: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc(file=sys.stderr)
    raise

print(
    f"[INIT] Handlers registrados: {len(bot.message_handlers)} message handlers",
    file=sys.stderr
)

# ==================== 7. INICIALIZAR REQUESTS ====================
try:

    from requests_db import init_requests_table

    init_requests_table()

    print("[INIT] ✅ Tabla requests inicializada", file=sys.stderr)

except Exception as e:

    print(f"[INIT] ⚠️ Error requests: {e}", file=sys.stderr)


# ==================== 8. FLASK APP ====================
app = Flask(__name__)


@app.route('/')
@app.route('/health')
def health():

    return jsonify({
        "status": "healthy",
        "bot": "online",
        "handlers": len(bot.message_handlers),
        "timestamp": __import__('time').time()
    }), 200


# ==================== 9. WEBHOOK ====================
@app.route('/webhook', methods=['POST'])
def webhook():

    content_type = request.headers.get("content-type", "")

    if "application/json" not in content_type:
        return "Forbidden", 403

    try:

        json_string = request.get_data().decode("utf-8")

        update_dict = json.loads(json_string)

        update = Update.de_json(update_dict)

        bot.process_new_updates([update])

    except Exception as e:

        logger.error(f"[WEBHOOK ERROR] {e}")

    return "", 200


# ==================== 10. CONFIGURAR WEBHOOK ====================
domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")

if domain:

    webhook_url = f"https://{domain}/webhook"

    try:

        current = bot.get_webhook_info()

        if current.url != webhook_url:

            bot.remove_webhook(drop_pending_updates=True)

            bot.set_webhook(
                url=webhook_url,
                drop_pending_updates=True
            )

            logger.info(f"✅ Webhook configurado: {webhook_url}")

        else:

            logger.info(f"Webhook ya configurado: {webhook_url}")

    except Exception as e:

        logger.error(f"❌ Error configurando webhook: {e}")

else:

    logger.error(
        "⚠️ RAILWAY_PUBLIC_DOMAIN no definido. Webhook NO configurado."
    )


print("[INIT] ✅ Bot y Flask listos para recibir webhooks", file=sys.stderr)


# ==================== 11. RUN LOCAL SOLO DEBUG ====================
if __name__ == "__main__":

    port = int(os.environ.get("PORT", 8080))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=True
    )
