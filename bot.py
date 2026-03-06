#!/usr/bin/env python3
"""
CleanyGo Bot - Railway Production Entrypoint
Webhook + handlers + DB + logging
"""

import os
import time
import json
import traceback

from telebot import TeleBot
from telebot.types import Update
from flask import Flask, jsonify, request

from config import inject_bot, init_db as config_init_db, logger


# ==================== CONFIG ====================

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN no definido en variables de entorno")

logger.info(f"[INIT] Token cargado: {TOKEN[:10]}...")


# ==================== CREAR BOT ====================

bot = TeleBot(
    TOKEN,
    parse_mode="HTML",
    threaded=True
)

logger.info(f"[INIT] Bot creado: {id(bot)}")


# ==================== INYECTAR BOT ====================

inject_bot(bot)
logger.info("[INIT] Bot inyectado en config")


# ==================== DB ====================

try:
    config_init_db()
    logger.info("[INIT] Base de datos inicializada")
except Exception as e:
    logger.error(f"[DB ERROR] {e}")


# ==================== CARGAR Y REGISTRAR HANDLERS ====================

try:

    from handlers.common import register_handlers as register_common_handlers
    register_common_handlers(bot)

    logger.info("[INIT] Handlers comunes registrados")

    # Worker flow
    import handlers.worker.flow

    logger.info("[INIT] Worker flow cargado")

    # DEBUG
    logger.info(f"[DEBUG] Total message handlers: {len(bot.message_handlers)}")
    logger.info(f"[DEBUG] Total callback handlers: {len(bot.callback_query_handlers)}")

except Exception as e:
    logger.error(f"[ERROR] Cargando handlers: {e}")
    logger.error(traceback.format_exc())
    raise


# ==================== FLASK ====================

app = Flask(__name__)


@app.route("/")
@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "bot": "online",
        "timestamp": time.time()
    }), 200


# ==================== WEBHOOK ====================

@app.route("/webhook", methods=["POST"])
def webhook():
    try:

        if not request.is_json:
            return "invalid", 403

        update_dict = request.get_json()

        update = Update.de_json(update_dict, bot)

        bot.process_new_updates([update])

    except Exception as e:
        logger.error(f"[WEBHOOK ERROR] {e}", exc_info=True)
        return str(e), 500

    return "", 200


# ==================== CONFIGURAR WEBHOOK ====================

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

    logger.error("[ERROR] RAILWAY_PUBLIC_DOMAIN no definido")


logger.info("[INIT] Bot listo para recibir webhooks")


# ==================== RUN ====================

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 8080))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
