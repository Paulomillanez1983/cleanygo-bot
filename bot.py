#!/usr/bin/env python3
"""
CleanyGo Bot - Punto de entrada principal con Webhook
"""

import os
import sys
from flask import Flask, request
from telebot.types import Update

# Inicializar base de datos primero
from database import init_db
init_db()

# Importar handlers (registran sus decorators con el bot)
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
    """Health check básico"""
    return '✅ CleanyGo Bot is running!', 200

@app.route('/webhook', methods=['POST'])
def webhook():
    """Recibe actualizaciones de Telegram"""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        return 'Forbidden', 403

def setup_webhook():
    """Configura el webhook con Railway"""
    # Obtener el dominio público de Railway
    railway_domain = os.getenv('RAILWAY_PUBLIC_DOMAIN')
    
    if not railway_domain:
        logger.error("❌ RAILWAY_PUBLIC_DOMAIN no está configurado")
        sys.exit(1)
    
    webhook_url = f"https://{railway_domain}/webhook"
    
    # Eliminar webhook anterior y configurar nuevo
    bot.remove_webhook()
    bot.set_webhook(url=webhook_url)
    
    logger.info(f"✅ Webhook configurado: {webhook_url}")
    return webhook_url

if __name__ == "__main__":
    logger.info(f"{Icons.SUCCESS} Bot CleanyGo iniciando...")
    
    # Configurar webhook
    setup_webhook()
    
    # Obtener puerto de Railway
    port = int(os.environ.get('PORT', 5000))
    
    # Iniciar Flask
    logger.info(f"🚀 Servidor iniciando en puerto {port}")
    app.run(host='0.0.0.0', port=port)
