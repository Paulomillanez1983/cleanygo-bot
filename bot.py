#!/usr/bin/env python3
"""
CleanyGo Bot - Railway Production Entrypoint
Webhook + handlers + DB + logging
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
    raise RuntimeError("BOT_TOKEN no definido en variables de entorno")

logger.info(f"[INIT] Token cargado: {TOKEN[:10]}...")


# =========================================================
# CREAR BOT
# =========================================================

bot = TeleBot(
    TOKEN,
    parse_mode="HTML",
    threaded=False  # Importante para Flask/Gunicorn
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
    raise  # Detener si la BD falla


# =========================================================
# CARGAR HANDLERS (ORDEN IMPORTANTE)
# =========================================================

def load_handlers():
    """
    Carga todos los módulos de handlers.
    En telebot, los decoradores @bot.callback_query_handler 
    registran los handlers automáticamente al importar.
    """
    try:
        # 1. Handlers comunes (start, help, etc.)
        import handlers.common
        logger.info("[INIT] Handlers comunes cargados")
        
        # 2. Handlers del cliente (solicitar servicios)
        # Estos registran: confirm_yes, cancel_req, retry_search, etc.
        import handlers.client.callbacks
        logger.info("[INIT] Client callbacks cargados")
        
        # 3. Flujo del cliente (selección de servicio, ubicación, etc.)
        import handlers.client.flow
        logger.info("[INIT] Client flow cargado")
        
        # 4. Handlers del trabajador
        import handlers.worker.callbacks  # Si existe
        logger.info("[INIT] Worker callbacks cargados")
        
        # 5. Flujo del trabajador
        import handlers.worker.flow
        logger.info("[INIT] Worker flow cargado")
        
        # Debug: contar handlers registrados
        logger.info(f"[DEBUG] Message handlers: {len(bot.message_handlers)}")
        logger.info(f"[DEBUG] Callback handlers: {len(bot.callback_query_handlers)}")
        logger.info(f"[DEBUG] Inline handlers: {len(bot.inline_handlers)}")
        
        # Listar algunos handlers para verificar
        callback_patterns = []
        for handler in bot.callback_query_handlers:
            if hasattr(handler, 'func'):
                # Extraer el filtro de la función lambda si es posible
                callback_patterns.append(str(handler.func))
        
        logger.info(f"[DEBUG] Callback filters: {callback_patterns[:5]}...")
        
    except Exception as e:
        logger.error(f"[ERROR] Cargando handlers: {e}")
        logger.error(traceback.format_exc())
        raise

# Cargar handlers
load_handlers()


# =========================================================
# FLASK APP
# =========================================================

app = Flask(__name__)


@app.route("/")
@app.route("/health")
def health():
    """Endpoint de health check para Railway"""
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
    """
    Recibe updates de Telegram y los procesa.
    """
    try:
        if not request.is_json:
            logger.warning("[WEBHOOK] Request no es JSON")
            return jsonify({"error": "JSON required"}), 403
        
        update_dict = request.get_json()
        
        # Log de debug (opcional, quitar en producción alta carga)
        if update_dict.get('callback_query'):
            logger.info(f"[WEBHOOK] Callback: {update_dict['callback_query'].get('data', 'N/A')}")
        elif update_dict.get('message'):
            msg_text = update_dict['message'].get('text', 'N/A')[:50]
            logger.info(f"[WEBHOOK] Message: {msg_text}")
        
        # Convertir dict a objeto Update de telebot
        update = Update.de_json(update_dict)
        
        # Procesar update
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
    """Configura el webhook con Telegram"""
    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    
    if not domain:
        logger.error("[ERROR] RAILWAY_PUBLIC_DOMAIN no definido")
        logger.info("[INFO] Usando polling mode (desarrollo local)")
        return False
    
    webhook_url = f"https://{domain}/webhook"
    
    try:
        # Obtener info actual del webhook
        current = bot.get_webhook_info()
        logger.info(f"[WEBHOOK] URL actual: {current.url}")
        logger.info(f"[WEBHOOK] Pending updates: {current.pending_update_count}")
        
        if current.url != webhook_url:
            logger.info(f"[INIT] Configurando webhook en: {webhook_url}")
            
            # Eliminar webhook anterior
            bot.remove_webhook(drop_pending_updates=True)
            time.sleep(1)
            
            # Establecer nuevo webhook
            bot.set_webhook(
                url=webhook_url,
                drop_pending_updates=True,
                timeout=60
            )
            
            logger.info(f"[INIT] Webhook configurado exitosamente")
        else:
            logger.info(f"[INIT] Webhook ya configurado correctamente")
            
        return True
        
    except Exception as e:
        logger.error(f"[ERROR] Configurando webhook: {e}", exc_info=True)
        return False


# Configurar webhook al iniciar
webhook_configured = setup_webhook()

logger.info("[INIT] Bot listo para recibir webhooks")


# =========================================================
# RUN SERVER
# =========================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    
    # En producción, Gunicorn maneja el servidor
    # Este bloque solo corre en desarrollo local
    logger.info(f"[INIT] Iniciando servidor Flask en puerto {port}")
    
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=True  # Importante para manejar múltiples requests
    )
