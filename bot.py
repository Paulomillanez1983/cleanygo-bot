#!/usr/bin/env python3
"""
CleanyGo Bot - Entrada principal para Railway
VERSIÓN CORREGIDA: Inyección consistente con config.py
"""

import os
import sys

# ==================== PASO 1: VERIFICAR TOKEN ====================
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    print("❌ FATAL: BOT_TOKEN no definido", file=sys.stderr)
    raise RuntimeError("Configura BOT_TOKEN en Railway Variables")

print(f"[INIT] Token: {TOKEN[:10]}...", file=sys.stderr)

# ==================== PASO 2: CREAR BOT ÚNICO ====================
from telebot import TeleBot
bot = TeleBot(TOKEN, parse_mode="HTML")
print(f"[INIT] Bot creado: {id(bot)}", file=sys.stderr)

# ==================== PASO 3: INYECTAR EN CONFIG (CORREGIDO) ====================
# ✅ CORREGIDO: Usar inject_bot en lugar de asignación directa
from config import inject_bot, init_db as config_init_db
inject_bot(bot)
print("[INIT] ✅ Bot inyectado en config via inject_bot()", file=sys.stderr)

# ==================== PASO 4: BASE DE DATOS ====================
try:
    # ✅ Usar init_db desde config que ya tiene la conexión configurada
    config_init_db()
    print("[INIT] ✅ DB inicializada desde config", file=sys.stderr)
except Exception as e:
    print(f"[INIT] ❌ DB Error: {e}", file=sys.stderr)
    raise

# ==================== PASO 5: CARGAR HANDLERS ====================
print("[INIT] Cargando handlers...", file=sys.stderr)
try:
    # ✅ CORREGIDO: Importar en orden correcto para evitar circular imports
    import handlers.common
    import handlers.client.flow
    import handlers.client.search
    import handlers.client.callbacks
    import handlers.worker.flow
    import handlers.worker.jobs
    import handlers.worker.profile
    import handlers.worker.main  # ✅ AGREGADO: Importar el main de worker
    print("[INIT] ✅ Handlers cargados", file=sys.stderr)
except Exception as e:
    print(f"[INIT] ❌ Error handlers: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc(file=sys.stderr)
    raise

print(f"[INIT] Handlers registrados: {len(bot.message_handlers)} message handlers", file=sys.stderr)

# ==================== PASO 6: INICIALIZAR REQUESTS_DB ====================
# ✅ AGREGADO: Inicializar tabla de requests
try:
    from requests_db import init_requests_table
    init_requests_table()
    print("[INIT] ✅ Tabla requests inicializada", file=sys.stderr)
except Exception as e:
    print(f"[INIT] ⚠️ Error inicializando requests: {e}", file=sys.stderr)

# ==================== PASO 7: FLASK APP ====================
from flask import Flask, jsonify, request
from telebot.types import Update

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

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') != 'application/json':
        return 'Forbidden', 403
    
    json_string = request.get_data().decode('utf-8')
    try:
        update = Update.de_json(json_string)
        bot.process_new_updates([update])
    except Exception as e:
        from config import logger
        logger.error(f"[WEBHOOK ERROR] {e}")
    return '', 200

# ==================== PASO 8: CONFIGURAR WEBHOOK ====================
def setup_webhook():
    try:
        domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN')
        if not domain:
            print("[INIT] ⚠️ RAILWAY_PUBLIC_DOMAIN no definido", file=sys.stderr)
            return
        
        webhook_url = f"https://{domain}/webhook"
        bot.remove_webhook()
        bot.set_webhook(url=webhook_url)
        print(f"[INIT] ✅ Webhook configurado: {webhook_url}", file=sys.stderr)
        
    except Exception as e:
        print(f"[INIT] ⚠️ Webhook error: {e}", file=sys.stderr)

setup_webhook()

# ==================== LOCAL ====================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
