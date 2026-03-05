#!/usr/bin/env python3
"""
CleanyGo Bot - Entrada principal optimizada para Railway
"""

import os
from flask import Flask, request, jsonify
from telebot.types import Update

from database import init_db
init_db()

from config import bot, logger
from utils.icons import Icons

# Import handlers para registrar decoradores
import handlers.common
import handlers.client.flow
import handlers.client.search
import handlers.client.callbacks
import handlers.worker.flow
import handlers.worker.jobs
import handlers.worker.profile

app = Flask(__name__)

# ----- Healthcheck -----
@app.route('/')
@app.route('/health')
def health():
    return jsonify({"status": "healthy", "bot": "CleanyGo online"}), 200

# ----- Webhook endpoint -----
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    return 'Forbidden', 403

# ----- SOLO EJECUCIÓN LOCAL -----
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"{Icons.SUCCESS} Iniciando CleanyGo localmente en puerto {port}")
    app.run(host="0.0.0.0", port=port)
