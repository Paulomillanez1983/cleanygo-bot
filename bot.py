#!/usr/bin/env python3
"""
CleanyGo Bot - Railway Production Entrypoint
Versión optimizada para Railway + Gunicorn + Webhook
"""

import os
import time
import traceback

from telebot import TeleBot
from telebot.types import Update
from flask import Flask, jsonify, request

from config import inject_bot, init_db as config_init_db, logger


# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN no definido")

logger.info(f"[INIT] Token cargado: {TOKEN[:10]}...")


# =========================================================
# CREAR BOT
# =========================================================

bot = TeleBot(
    TOKEN,
    parse_mode="HTML",
    threaded=True  # IMPORTANTE: permite múltiples updates simultáneos
)

logger.info(f"[INIT] Bot creado: {id(bot)}")


# =========================================================
# INYECTAR BOT EN CONFIG
# =========================================================

inject_bot(bot)

logger.info("[INIT] Bot inyectado en config")


# =========================================================
# INICIALIZAR DB
# =========================================================

try:

    config_init_db()

    logger.info("[INIT] Base de datos inicializada")

except Exception as e:

    logger.error(f"[DB ERROR] {e}", exc_info=True)

    raise


# =========================================================
# CARGAR HANDLERS (ORDEN CORREGIDO PARA EVITAR CIRCULARES)
# =========================================================

def load_handlers():
    """
    Carga handlers en orden específico.
    Los decoradores registran automáticamente al importar.
    """

    try:
        # 0. Importar models primero (sin dependencias circulares)
        import models.states
        import models.services_data
        logger.info("[INIT] Models cargados")

        # 1. Utils básicos (sin dependencias de models)
        import utils.icons
        import utils.telegram_safe
        logger.info("[INIT] Utils básicos cargados")

        # 2. Keyboards (depende de models.services_data)
        import utils.keyboards
        logger.info("[INIT] Keyboards cargados")

        # 3. Handlers comunes
        import handlers.common
        logger.info("[INIT] Handlers comunes cargados")

        # 4. Flujo cliente
        import handlers.client.flow
        logger.info("[INIT] Client flow cargado")

        # 5. Callbacks cliente
        import handlers.client.callbacks
        logger.info("[INIT] Client callbacks cargados")

        # 6. Flujo trabajador
        import handlers.worker.flow
        logger.info("[INIT] Worker flow cargado")

        # 7. Jobs trabajador
        import handlers.worker.jobs
        logger.info("[INIT] Worker jobs cargados")

        logger.info(f"[DEBUG] Message handlers: {len(bot.message_handlers)}")
        logger.info(f"[DEBUG] Callback handlers: {len(bot.callback_query_handlers)}")

    except Exception as e:

        logger.error(f"[ERROR] Cargando handlers: {e}")
        logger.error(traceback.format_exc())

        raise


load_handlers()


# =========================================================
# FLASK APP
# =========================================================

app = Flask(__name__)


@app.route("/")
@app.route("/health")
def health():
    """
    Endpoint de health check para Railway
    """

    return jsonify({
        "status": "healthy",
        "bot": "online",
        "handlers": {
            "message": len(bot.message_handlers),
            "callback": len(bot.callback_query_handlers)
        },
        "timestamp": time.time()
    }), 200


@app.route("/webhook", methods=["POST"])
def webhook():

    try:

        if not request.is_json:
            return jsonify({"error": "JSON required"}), 403

        update_dict = request.get_json()

        if update_dict.get("callback_query"):
            data = update_dict["callback_query"].get("data", "N/A")
            logger.info(f"[WEBHOOK] Callback: {data}")

        update = Update.de_json(update_dict)

        bot.process_new_updates([update])

    except Exception as e:

        logger.error(f"[WEBHOOK ERROR] {e}")
        logger.error(traceback.format_exc())

        return jsonify({"error": "Internal error"}), 500

    return jsonify({"status": "ok"}), 200

# =========================================================
# CONFIGURAR WEBHOOK
# =========================================================

def setup_webhook():

    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")

    if not domain:
        logger.warning("[WEBHOOK] RAILWAY_PUBLIC_DOMAIN no definido")
        return False

    webhook_url = f"https://{domain}/webhook"

    try:

        current = bot.get_webhook_info()

        if current.url != webhook_url:

            logger.info(f"[INIT] Configurando webhook: {webhook_url}")

            bot.remove_webhook(drop_pending_updates=True)

            time.sleep(1)

            bot.set_webhook(
                url=webhook_url,
                drop_pending_updates=True
            )

        else:

            logger.info("[INIT] Webhook ya configurado")

        return True

    except Exception as e:

        logger.error(f"[WEBHOOK ERROR] {e}")

        return False


# =========================================================
# INICIALIZAR WEBHOOK SOLO EN RAILWAY
# =========================================================

if os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
    setup_webhook()

logger.info("[INIT] Bot listo")


# =========================================================
# RUN LOCAL
# =========================================================

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 8080))

    logger.info(f"[INIT] Iniciando servidor local en puerto {port}")

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=True
    )
