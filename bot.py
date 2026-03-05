#!/usr/bin/env python3
"""
CleanyGo Bot - Entrada principal optimizada para Railway
"""

import os
import gevent
from flask import Flask, request, jsonify
from telebot.types import Update

app = Flask(__name__)

# ----- INICIALIZACIÓN LAZY -----
_bot_initialized = False
bot = None

def init_bot():
    """Inicializa bot y base de datos solo cuando se necesita"""
    global _bot_initialized, bot
    
    if _bot_initialized:
        return bot
        
    # 1. Inicializar DB primero
    from database import init_db
    init_db()
    
    # 2. Inicializar Bot (ahora sí tenemos TOKEN en runtime)
    from config import get_bot
    global bot
    bot = get_bot()
    
    # 3. Importar handlers AHORA que bot existe
    import handlers.common
    import handlers.client.flow
    import handlers.client.search
    import handlers.client.callbacks
    import handlers.worker.flow
    import handlers.worker.jobs
    import handlers.worker.profile
    
    _bot_initialized = True
    return bot

# ----- Healthcheck -----
@app.route('/')
@app.route('/health')
def health():
    return jsonify({
        "status": "healthy", 
        "service": "running",
        "bot_initialized": _bot_initialized
    }), 200

# ----- Webhook endpoint -----
@app.route('/webhook', methods=['POST'])
def webhook():
    if not _bot_initialized:
        init_bot()
        
    if request.headers.get('content-type') != 'application/json':
        return 'Forbidden', 403
    
    json_string = request.get_data().decode('utf-8')
    update = Update.de_json(json_string)
    
    # Usar gevent en lugar de threading para compatibilidad
    gevent.spawn(bot.process_new_updates, [update])
    
    return '', 200

# ----- Webhook setup -----
def setup_webhook():
    """Configura webhook en Railway"""
    try:
        domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN')
        if domain and _bot_initialized:
            webhook_url = f"https://{domain}/webhook"
            bot.remove_webhook()
            bot.set_webhook(url=webhook_url)
            logger.info(f"Webhook configurado: {webhook_url}")
    except Exception as e:
        logger.error(f"Error configurando webhook: {e}")

# Inicializar en primer request o al arrancar (si tenemos variables)
@app.before_request
def ensure_initialized():
    if not _bot_initialized:
        init_bot()
        if os.environ.get('RAILWAY_PUBLIC_DOMAIN'):
            setup_webhook()

# ----- LOCAL -----
if __name__ == "__main__":
    init_bot()  # Inicializar inmediatamente en local
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
