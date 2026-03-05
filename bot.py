#!/usr/bin/env python3
"""
CleanyGo Bot - Entrada principal para Railway
"""

import os
import sys
from flask import Flask, jsonify, request
from telebot.types import Update

# ==================== CONFIGURACIÓN PRIMERO ====================
print("[INIT] Cargando configuración...", file=sys.stderr)

from config import TOKEN, logger
if not TOKEN:
    raise RuntimeError("BOT_TOKEN no definido")

from telebot import TeleBot

# Crear bot INMEDIATAMENTE (no lazy)
bot = TeleBot(TOKEN, parse_mode="HTML")
print(f"[INIT] Bot creado (token: {TOKEN[:10]}...)", file=sys.stderr)

# ==================== BASE DE DATOS ====================
try:
    from database import init_db
    init_db()
    print("[INIT] ✅ Base de datos OK", file=sys.stderr)
except Exception as e:
    print(f"[INIT] ❌ Error DB: {e}", file=sys.stderr)
    raise

# ==================== HANDLERS (después de tener bot) ====================
# Importar TODOS los handlers para registrar decorators
print("[INIT] Cargando handlers...", file=sys.stderr)

try:
    import handlers.common
    import handlers.client.flow
    import handlers.client.search
    import handlers.client.callbacks
    import handlers.worker.flow
    import handlers.worker.jobs
    import handlers.worker.profile
    print("[INIT] ✅ Handlers cargados", file=sys.stderr)
except Exception as e:
    print(f"[INIT] ❌ Error handlers: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc(file=sys.stderr)
    raise

# ==================== FLASK APP ====================
app = Flask(__name__)

@app.route('/')
@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "bot": "online",
        "handlers_loaded": True,
        "timestamp": __import__('time').time()
    }), 200

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') != 'application/json':
        return 'Forbidden', 403
    
    json_string = request.get_data().decode('utf-8')
    update = Update.de_json(json_string)
    
    # Procesar síncronamente (más confiable para debug)
    bot.process_new_updates([update])
    return '', 200

# ==================== WEBHOOK SETUP ====================
def setup_webhook():
    try:
        domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN')
        if not domain:
            print("[INIT] ⚠️ RAILWAY_PUBLIC_DOMAIN no definido", file=sys.stderr)
            return
            
        webhook_url = f"https://{domain}/webhook"
        
        # Verificar webhook actual
        info = bot.get_webhook_info()
        if info.url == webhook_url:
            print(f"[INIT] ✅ Webhook ya configurado: {webhook_url}", file=sys.stderr)
            return
            
        # Configurar nuevo webhook
        bot.remove_webhook()
        bot.set_webhook(url=webhook_url)
        print(f"[INIT] ✅ Webhook configurado: {webhook_url}", file=sys.stderr)
        
    except Exception as e:
        print(f"[INIT] ⚠️ Error webhook: {e}", file=sys.stderr)

# Configurar webhook al arrancar
setup_webhook()

# ==================== LOCAL ====================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
