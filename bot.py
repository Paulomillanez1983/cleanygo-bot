#!/usr/bin/env python3
"""
CleanyGo Bot - Optimized for Railway with Gevent
"""

import os
import gevent
from flask import Flask, request, jsonify
from telebot.types import Update

from config import logger
from utils.icons import Icons

# Initialize Flask first
app = Flask(__name__)

# Lazy database initialization
_db_initialized = False

def get_db():
    global _db_initialized
    if not _db_initialized:
        from database import init_db
        init_db()
        _db_initialized = True

# Import bot after Flask setup to avoid circular imports
from config import bot

# Import handlers for decorators
import handlers.common
import handlers.client.flow
import handlers.client.search
import handlers.client.callbacks
import handlers.worker.flow
import handlers.worker.jobs
import handlers.worker.profile

# ----- Healthcheck -----
@app.route('/')
@app.route('/health')
def health():
    return jsonify({
        "status": "healthy", 
        "bot": "CleanyGo online",
        "service": "running"
    }), 200

# ----- Webhook endpoint -----
@app.route('/webhook', methods=['POST'])
def webhook():
    get_db()  # Initialize DB on first request if needed
    
    if request.headers.get('content-type') != 'application/json':
        return 'Forbidden', 403
    
    json_string = request.get_data().decode('utf-8')
    update = Update.de_json(json_string)
    
    # Use gevent spawn instead of threading for compatibility with gunicorn+gevent
    gevent.spawn(bot.process_new_updates, [update])
    
    return '', 200

# ----- Webhook setup on startup -----
def setup_webhook():
    """Configure webhook on Railway startup"""
    try:
        domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN')
        if domain:
            webhook_url = f"https://{domain}/webhook"
            bot.remove_webhook()
            bot.set_webhook(url=webhook_url)
            logger.info(f"{Icons.SUCCESS} Webhook set to: {webhook_url}")
        else:
            logger.warning(f"{Icons.WARNING} RAILWAY_PUBLIC_DOMAIN not set, using polling mode")
    except Exception as e:
        logger.error(f"{Icons.ERROR} Failed to set webhook: {e}")

# Run setup when module loads (only in workers, not during health checks)
if os.environ.get('RAILWAY_ENVIRONMENT'):
    setup_webhook()

# ----- LOCAL DEVELOPMENT ONLY -----
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"{Icons.SUCCESS} Starting CleanyGo locally on port {port}")
    # Use Flask dev server locally, Gunicorn in production
    app.run(host="0.0.0.0", port=port, threaded=True)
