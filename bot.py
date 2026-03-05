#!/usr/bin/env python3
"""
CleanyGo Bot - Entrada principal para Railway
VERSIÓN FINAL: Webhook + handlers + requests
"""

import os
import sys
from telebot import TeleBot
from flask import Flask, jsonify, request
from telebot.types import Update

# ==================== 1. TOKEN ====================
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN no definido en Variables de entorno")

print(f"[INIT] Token: {TOKEN[:10]}...", file=sys.stderr)

# ==================== 2. CREAR BOT ====================
bot = TeleBot(TOKEN, parse_mode="HTML")
print(f"[INIT] Bot creado: {id(bot)}", file=sys.stderr)

# ==================== 3. INYECTAR EN CONFIG ====================
from config import inject_bot, init_db as config_init_db, logger
inject_bot(bot)
print("[INIT] ✅ Bot inyectado en config", file=sys.stderr)

# ==================== 4. INICIALIZAR DB ====================
config_init_db()
print("[INIT] ✅ DB inicializada desde config", file=sys.stderr)

# ==================== 5. CARGAR HANDLERS ====================
try:
    import handlers.common
    import handlers.client.flow
    import handlers.client.search
    import handlers.client.callbacks
    import handlers.worker.flow
    import handlers.worker.jobs
    import handlers.worker.profile
    import handlers.worker.main
    print("[INIT] ✅ Handlers cargados", file=sys.stderr)
except Exception as e:
    print(f"[INIT] ❌ Error handlers: {e}", file=sys.stderr)
    import traceback; traceback.print_exc(file=sys.stderr)
    raise

print(f"[INIT] Handlers registrados: {len(bot.message_handlers)} message handlers", file=sys.stderr)

# ==================== 6. INICIALIZAR REQUESTS ====================
try:
    from requests_db import init_requests_table
    init_requests_table()
    print("[INIT] ✅ Tabla requests inicializada", file=sys.stderr)
except Exception as e:
    print(f"[INIT] ⚠️ Error requests: {e}", file=sys.stderr)

# ==================== 7. FLASK APP ====================
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
        logger.error(f"[WEBHOOK ERROR] {e}")
    return '', 200

# ==================== 8. CONFIGURAR WEBHOOK ====================
def setup_webhook():
    domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN')
    if not domain:
        print("[INIT] ⚠️ RAILWAY_PUBLIC_DOMAIN no definido", file=sys.stderr)
        return
    webhook_url = f"https://{domain}/webhook"
    bot.remove_webhook()
    bot.set_webhook(url=webhook_url)
    print(f"[INIT] ✅ Webhook configurado: {webhook_url}", file=sys.stderr)

setup_webhook()
print("[INIT] ✅ Bot y Flask listos para recibir webhooks", file=sys.stderr)

# ==================== 9. RUN LOCAL SOLO DEBUG ====================
if __name__ == "__main__":
    # Solo para testing local, nunca en producción
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
