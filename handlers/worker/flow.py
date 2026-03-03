from telebot import types, apihelper
from config import bot
from models.user_state import set_state, update_data, get_data, clear_state, UserState, get_session
from models.services_data import SERVICES
from utils.icons import Icons
from utils.keyboards import get_service_selector
from handlers.common import send_safe
from database import db_execute
import re
import time
import logging

# Logging full para prod (manda a file o console)
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Fix session timeout (5 min idle)
apihelper.SESSION_TIME_TO_LIVE = 5 * 60

# Resto del código igual hasta el handler de location...

# UBICACIÓN - VERSIÓN FINAL PROD
def ask_worker_location(chat_id: str):
    text = f"""
📍 <b>Paso 5/5: Ubicación de trabajo</b>

Enviá tu ubicación actual para terminar.

Tocá 📍 abajo o clip > Ubicación.
    """
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("📍 Enviar ubicación", request_location=True))
    markup.add(types.KeyboardButton("❌ Cancelar"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(content_types=['location'])
def handle_worker_location(message):
    chat_id = message.chat.id
    logger.info(f"[LOCATION] Recibida para chat_id: {chat_id} - lat: {message.location.latitude if message.location else 'NONE'}")

    session = get_session(chat_id)
    if not session:
        logger.warning(f"[LOCATION] Session None para {chat_id} - Recreando fallback")
        set_state(chat_id, UserState.WORKER_SHARING_LOCATION)  # Force si perdido
        session = get_session(chat_id)
    
    if session.state != UserState.WORKER_SHARING_LOCATION:
        logger.warning(f"[LOCATION] Estado equivocado: {session.state} para {chat_id}")
        bot.send_message(chat_id, "Estado no esperado. Reiniciá con 'trabajar'.")
        return

    lat = message.location.latitude
    lon = message.location.longitude
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        logger.error(f"[LOCATION] Coords inválidas: {lat}, {lon}")
        send_safe(chat_id, "❌ Ubicación inválida. Intentá de nuevo.")
        return

    timestamp = int(time.time())
    try:
        db_execute(
            "UPDATE workers SET lat = ?, lon = ?, last_update = ?, disponible = 1 WHERE chat_id = ?",
            (lat, lon, timestamp, str(chat_id)),
            commit=True
        )
        logger.info(f"[LOCATION] DB updated OK para {chat_id}")
    except Exception as e:
        logger.error(f"[LOCATION] DB error: {str(e)}")
        send_safe(chat_id, f"❌ Error guardando: {str(e)}. Contactá soporte.")
        return

    clear_state(chat_id)
    logger.info(f"[LOCATION] Estado cleared para {chat_id}")

    final_text = f"""
🎉 <b>Registro completo!</b>

Activo para laburos cercanos.

Comandos:
/online - Activar
/offline - Pausar
/ubicacion - Cambiar
/precios - Tarifas
/perfil - Ver perfil
/ayuda - Soporte
    """
    bot.send_message(chat_id, final_text, parse_mode="HTML", reply_markup=types.ReplyKeyboardRemove())

# ... resto igual

# EN TU MAIN.PY O DONDE CORRAS EL BOT:
def run_bot_safe():
    bot.remove_webhook()  # Mata webhook si existe
    while True:
        try:
            logger.info("Starting infinity polling...")
            bot.infinity_polling(timeout=40, long_polling_timeout=25, skip_pending=True, allowed_updates=['message', 'location', 'photo', 'callback_query'])
        except Exception as e:
            logger.error(f"Polling crash: {str(e)}")
            time.sleep(10)  # Retry

if __name__ == "__main__":
    run_bot_safe()
