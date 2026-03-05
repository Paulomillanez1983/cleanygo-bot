#!/usr/bin/env python3
"""
CleanyGo Bot - Optimizado para Railway
"""

import os
import gevent
from flask import Flask, request, jsonify
from telebot.types import Update

app = Flask(__name__)

# ----- INICIALIZACIÓN -----
_initialized = False
_bot = None

def init_app():
    """Inicializa todo una sola vez por worker"""
    global _initialized, _bot
    
    if _initialized:
        return _bot
        
    # DB
    from database import init_db
    init_db()
    
    # Bot
    from config import TOKEN
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN no definido")
    
    from telebot import TeleBot
    _bot = TeleBot(TOKEN, parse_mode="HTML")
    
    # Handlers (importar después de tener bot)
    import handlers.common
    import handlers.client.flow
    import handlers.client.search
    import handlers.client.callbacks
    import handlers.worker.flow
    import handlers.worker.jobs
    import handlers.worker.profile
    
    # Webhook (solo si somos el worker maestro)
    if os.environ.get('GUNICORN_WORKER_ID') == '0' or not os.environ.get('GUNICORN_WORKER_ID'):
        _setup_webhook_once(_bot)
    
    _initialized = True
    return _bot

def _setup_webhook_once(bot_instance):
    """Configura webhook con manejo de rate limits"""
    try:
        domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN')
        if not domain:
            return
            
        webhook_url = f"https://{domain}/webhook"
        
        # Verificar estado actual
        info = bot_instance.get_webhook_info()
        if info.url == webhook_url and not info.pending_update_count:
            return  # Ya está OK
            
        # Configurar con retry
        import time
        for attempt in range(3):
            try:
                bot_instance.remove_webhook()
                time.sleep(0.5)
                bot_instance.set_webhook(url=webhook_url)
                print(f"✅ Webhook OK: {webhook_url}")
                return
            except Exception as e:
                if "429" in str(e):
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    raise
    except Exception as e:
        print(f"⚠️ Webhook error (no crítico): {e}")

# ----- RUTAS -----
@app.route('/')
@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "initialized": _initialized,
        "timestamp": __import__('time').time()
    }), 200

@app.route('/webhook', methods=['POST'])
def webhook():
    bot_instance = init_app()
    
    if request.headers.get('content-type') != 'application/json':
        return 'Forbidden', 403
    
    json_string = request.get_data().decode('utf-8')
    update = Update.de_json(json_string)
    
    # Procesar asíncronamente
    gevent.spawn(bot_instance.process_new_updates, [update])
    return '', 200

# ----- LOCAL -----
if __name__ == "__main__":
    init_app()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
