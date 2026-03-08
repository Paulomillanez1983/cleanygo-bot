#!/usr/bin/env python3
"""
CleanyGo Bot - Railway Production Entrypoint
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

bot = TeleBot(TOKEN, parse_mode="HTML", threaded=False)
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
# CARGAR HANDLERS (ORDEN IMPORTANTE)
# =========================================================

def load_handlers():
    """
    Carga handlers en orden específico.
    Los decoradores registran automáticamente al importar.
    """
    try:
        # 1. Comunes primero (start, cancel, menú principal)
        import handlers.common
        logger.info("[INIT] Handlers comunes cargados")
        
        # 2. Flujo del cliente (mensajes y callbacks de navegación)
        #    Esto registra: client_svc, time_quick, time_h, time_m, location
        import handlers.client.flow
        logger.info("[INIT] Client flow cargado")
        
        # 3. Callbacks del cliente (confirmación, cancel, retry, etc.)
        #    Esto registra: confirm_yes, cancel_req, retry_search, etc.
        import handlers.client.callbacks
        logger.info("[INIT] Client callbacks cargados")
        
        # 4. Flujo del trabajador
        import handlers.worker.flow
        logger.info("[INIT] Worker flow cargado")
        
        # Debug
        logger.info(f"[DEBUG] Message handlers: {len(bot.message_handlers)}")
        logger.info(f"[DEBUG] Callback handlers: {len(bot.callback_query_handlers)}")
        
        # Verificar que confirm_yes está registrado
        confirm_handlers = [h for h in bot.callback_query_handlers 
                          if hasattr(h, 'func') and 'confirm_yes' in str(h.func)]
        logger.info(f"[DEBUG] Handlers para confirm_yes: {len(confirm_handlers)}")
        
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
        
        # Log para debug
        if update_dict.get('callback_query'):
            data = update_dict['callback_query'].get('data', 'N/A')
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
        logger.error("[ERROR] RAILWAY_PUBLIC_DOMAIN no definido")
        return False
    
    webhook_url = f"https://{domain}/webhook"
    
    try:
        current = bot.get_webhook_info()
        if current.url != webhook_url:
            logger.info(f"[INIT] Configurando webhook: {webhook_url}")
            bot.remove_webhook(drop_pending_updates=True)
            time.sleep(1)
            bot.set_webhook(url=webhook_url, drop_pending_updates=True)
        else:
            logger.info(f"[INIT] Webhook ya configurado")
        return True
    except Exception as e:
        logger.error(f"[ERROR] Webhook: {e}")
        return False

setup_webhook()
logger.info("[INIT] Bot listo")

# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
