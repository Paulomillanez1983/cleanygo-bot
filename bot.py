#!/usr/bin/env python3
"""
CleanyGo Bot - Railway Production Entrypoint
Webhook + handlers + DB + logging
"""

import os
import time

from telebot import TeleBot
from telebot.types import Update
from flask import Flask, jsonify, request

# ==================== 1. CONFIG ====================

from config import inject_bot, init_db as config_init_db, logger

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN no definido en variables de entorno")

logger.info(f"[INIT] Token cargado: {TOKEN[:10]}...")

# ==================== 2. CREAR BOT ====================

bot = TeleBot(
    TOKEN,
    parse_mode="HTML",
    threaded=True
)

logger.info(f"[INIT] Bot creado: {id(bot)}")

# ==================== 3. INYECTAR BOT ====================

inject_bot(bot)
logger.info("[INIT] Bot inyectado en config")

# ==================== 4. INICIALIZAR DB ====================

config_init_db()
logger.info("[INIT] Base de datos inicializada")

# ==================== 5. FUNCIONES SEGURAS ====================

def send_safe(chat_id, text, reply_markup=None, parse_mode="HTML"):
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

    logger.info("[INIT] Handlers cargados correctamente")

except Exception as e:

    logger.error(f"[ERROR] Cargando handlers: {e}")
    raise


try:
    handlers_count = len(bot._message_handlers)
except:
    handlers_count = "unknown"

logger.info(f"[INIT] Handlers registrados: {handlers_count}")

# ==================== 7. TABLA REQUESTS ====================

try:

    from requests_db import init_requests_table

    init_requests_table()

    logger.info("[INIT] Tabla requests inicializada")

except Exception as e:

    logger.warning(f"[WARN] No se pudo inicializar requests: {e}")


# ==================== 8. FLASK APP ====================

app = Flask(__name__)


@app.route("/")
@app.route("/health")
def health():

    return jsonify({
        "status": "healthy",
        "bot": "online",
        "handlers": handlers_count,
        "timestamp": time.time()
    }), 200


# ==================== 9. WEBHOOK ====================

@app.route("/webhook", methods=["POST"])
def webhook():

    try:

        update_json = request.get_json(force=True)

        if not update_json:
            return "no update", 200

        update = Update.de_json(update_json, bot)

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

            logger.info("[INIT] Configurando webhook...")

            bot.remove_webhook(drop_pending_updates=True)

            time.sleep(1)

            bot.set_webhook(
                url=webhook_url,
                drop_pending_updates=True
            )

            logger.info(f"[INIT] Webhook configurado: {webhook_url}")

        else:

            logger.info(f"[INIT] Webhook ya configurado: {webhook_url}")

    except Exception as e:

        logger.error(f"[ERROR] Configurando webhook: {e}")

else:

    logger.error("[ERROR] RAILWAY_PUBLIC_DOMAIN no definido. Webhook NO configurado.")


logger.info("[INIT] Bot listo para recibir webhooks")


# ==================== 11. RUN LOCAL (DEBUG) ====================

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 8080))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
