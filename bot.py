#!/usr/bin/env python3
"""
CleanyGo Bot - Entrada principal para Railway
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

# ==================== PASO 3: INYECTAR EN CONFIG ====================
import config
config.bot = bot
config.TOKEN = TOKEN
config.logger.info("Bot inyectado en config")

# ==================== PASO 4: BASE DE DATOS ====================
try:
    from database import init_db
    init_db()
    print("[INIT] ✅ DB OK", file=sys.stderr)
except Exception as e:
    print(f"[INIT] ❌ DB Error: {e}", file=sys.stderr)
    raise

# ==================== PASO 5: CARGAR HANDLERS ====================
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

print(f"[INIT] Handlers registrados: {len(bot.message_handlers)} message handlers", file=sys.stderr)

# ==================== PASO 6: FLASK APP ====================
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
        config.logger.error(f"[WEBHOOK ERROR] {e}")
    return '', 200

# ==================== PASO 7: CONFIGURAR WEBHOOK ====================
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
