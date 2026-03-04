#!/usr/bin/env python3
"""
CleanyGo Bot - Punto de entrada principal con Webhook
"""

import os
import sys
from flask import Flask, request, jsonify
from telebot.types import Update

# Inicializar base de datos primero
from database import init_db
init_db()

# Importar handlers
from handlers import common
from handlers.client import flow as client_flow
from handlers.client import search
from handlers.client import callbacks as client_callbacks
from handlers.worker import flow as worker_flow
from handlers.worker import jobs
from handlers.worker import profile

from config import bot, logger
from utils.icons import Icons

app = Flask(__name__)

@app.route('/')
def index():
    return '✅ CleanyGo Bot is running!', 200

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "bot": "CleanyGo online"}), 200

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        return 'Forbidden', 403

def setup_webhook():
    railway_domain = os.getenv('RAILWAY_PUBLIC_DOMAIN')
    if not railway_domain:
        logger.error("❌ RAILWAY_PUBLIC_DOMAIN no está configurado")
        sys.exit(1)

    webhook_url = f"https://{railway_domain}/webhook"
    current = bot.get_webhook_info()

    if current.url == webhook_url:
        logger.info(f"Webhook ya configurado: {webhook_url}")
        return webhook_url

    bot.remove_webhook(drop_pending_updates=True)
    bot.set_webhook(url=webhook_url, drop_pending_updates=True)
    logger.info(f"Webhook configurado: {webhook_url}")
    return webhook_url

if __name__ == "__main__":
    logger.info(f"{Icons.SUCCESS} Bot CleanyGo iniciando...")
    setup_webhook()
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"🚀 Servidor iniciando en puerto {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
