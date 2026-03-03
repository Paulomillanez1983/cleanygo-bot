import os
from flask import Flask, request, abort
from telebot import types, apihelper
from config import bot  # Asumiendo que bot = TeleBot(TOKEN) está ahí
from models.user_state import set_state, update_data, get_data, clear_state, UserState, get_session
from models.services_data import SERVICES
from utils.icons import Icons
from utils.keyboards import get_service_selector
from handlers.common import send_safe
from database import db_execute
import re
import time
import logging

app = Flask(__name__)

# Logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Webhook endpoint
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'POST':
        update = types.Update.de_json(request.get_json(force=True))
        bot.process_new_updates([update])
        return 'OK', 200
    abort(403)

# Resto del código igual (handlers de mensajes, etc.) ...

# UBICACIÓN HANDLER (igual, pero loguea más)
@bot.message_handler(content_types=['location'])
def handle_worker_location(message):
    chat_id = message.chat.id
    logger.debug(f"[WEBHOOK LOCATION] Recibida para {chat_id} - lat: {message.location.latitude if message.location else 'NONE'}")

    session = get_session(chat_id)
    if not session:
        logger.warning(f"[LOCATION] Session None - Force set")
        set_state(chat_id, UserState.WORKER_SHARING_LOCATION)
        session = get_session(chat_id)
    
    if session.state != UserState.WORKER_SHARING_LOCATION:
        logger.warning(f"[LOCATION] Estado malo: {session.state}")
        bot.send_message(chat_id, "Estado cagado. Reiniciá con 'trabajar'.")
        return

    lat = message.location.latitude
    lon = message.location.longitude
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        logger.error(f"[LOCATION] Coords mierda: {lat}, {lon}")
        send_safe(chat_id, "❌ Ubicación inválida.")
        return

    timestamp = int(time.time())
    try:
        db_execute("UPDATE workers SET lat = ?, lon = ?, last_update = ?, disponible = 1 WHERE chat_id = ?",
                   (lat, lon, timestamp, str(chat_id)), commit=True)
        logger.info(f"[LOCATION] DB OK para {chat_id}")
    except Exception as e:
        logger.error(f"[LOCATION] DB falla: {str(e)}")
        send_safe(chat_id, f"❌ Error DB: {str(e)}. Soporte.")
        return

    clear_state(chat_id)
    logger.info(f"[LOCATION] Clear OK")

    final_text = f"""
🎉 <b>Registro piola!</b>

Activo para trabajos cerca.

Comandos:
/online - Prendé
/offline - Apagá
/ubicacion - Cambiá
/precios - Tarifas
/perfil - Mirá perfil
/ayuda - Ayuda
    """
    bot.send_message(chat_id, final_text, parse_mode="HTML", reply_markup=types.ReplyKeyboardRemove())

# ... (el resto de tus handlers: start, services, prices, name, phone, dni – dejalo igual)

# Setup webhook
if __name__ == "__main__":
    PORT = int(os.environ.get('PORT', 8443))
    WEBHOOK_URL = f"https://{os.environ.get('RAILWAY_STATIC_URL')}/webhook"  // O tu domain si tenés custom

    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    logger.info(f"Webhook set to {WEBHOOK_URL}")

    app.run(host='0.0.0.0', port=PORT, debug=True)
