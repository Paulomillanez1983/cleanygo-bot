#!/usr/bin/env python3
"""
CleanyGo Bot - Entrada principal para Railway (Lazy Loading)
"""

import os
import sys
from flask import Flask, jsonify

# ==================== APP FLASK (sin inicializar nada) ====================
app = Flask(__name__)

_initialized = False
_bot = None

def _init():
    """Inicializa todo - llamado solo cuando se necesita"""
    global _initialized, _bot
    
    if _initialized:
        return _bot
    
    print("[INIT] Iniciando CleanyGo...", file=sys.stderr)
    
    # 1. Base de datos
    try:
        from database import init_db
        init_db()
        print("[INIT] ✅ Base de datos OK", file=sys.stderr)
    except Exception as e:
        print(f"[INIT] ❌ Error DB: {e}", file=sys.stderr)
        raise
    
    # 2. Bot y handlers
    try:
        from config import TOKEN
        if not TOKEN:
            raise RuntimeError("BOT_TOKEN no definido")
        
        from telebot import TeleBot
        _bot = TeleBot(TOKEN, parse_mode="HTML")
        print(f"[INIT] ✅ Bot creado (token: {TOKEN[:10]}...)", file=sys.stderr)
        
        # Importar handlers AHORA que bot existe
        import handlers.common
        import handlers.client.flow
        import handlers.client.search
        import handlers.client.callbacks
        import handlers.worker.flow
        import handlers.worker.jobs
        import handlers.worker.profile
        print("[INIT] ✅ Handlers cargados", file=sys.stderr)
        
    except Exception as e:
        print(f"[INIT] ❌ Error Bot: {e}", file=sys.stderr)
        raise
    
    # 3. Webhook (solo si tenemos dominio)
    try:
        domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN')
        if domain and _bot:
            webhook_url = f"https://{domain}/webhook"
            _bot.remove_webhook()
            _bot.set_webhook(url=webhook_url)
            print(f"[INIT] ✅ Webhook: {webhook_url}", file=sys.stderr)
    except Exception as e:
        print(f"[INIT] ⚠️ Webhook error: {e}", file=sys.stderr)
        # No crashea si el webhook falla
    
    _initialized = True
    return _bot

# ==================== RUTAS ====================

@app.route('/')
@app.route('/health')
def health():
    """Healthcheck - siempre responde 200"""
    return jsonify({
        "status": "healthy",
        "initialized": _initialized,
        "timestamp": __import__('time').time()
    }), 200

@app.route('/webhook', methods=['POST'])
def webhook():
    """Endpoint de Telegram"""
    bot = _init()  # Inicializa si es necesario
    
    from flask import request
    from telebot.types import Update
    import gevent
    
    if request.headers.get('content-type') != 'application/json':
        return 'Forbidden', 403
    
    json_string = request.get_data().decode('utf-8')
    update = Update.de_json(json_string)
    
    # Procesar en background
    gevent.spawn(bot.process_new_updates, [update])
    return '', 200

# ==================== INICIALIZACIÓN AL ARRANCAR ====================
# Esto se ejecuta cuando Gunicorn carga la app, no al importar
with app.app_context():
    try:
        _init()
    except Exception as e:
        print(f"[INIT] Error en contexto: {e}", file=sys.stderr)
        # No raise - dejar que healthcheck falle si hay error grave

# ==================== LOCAL ====================
if __name__ == "__main__":
    _init()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
