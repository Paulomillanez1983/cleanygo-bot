import os
from flask import Flask, request, abort
from telebot import types, apihelper
from config import bot  # Asegúrate de que aquí esté: bot = telebot.TeleBot(TOKEN)
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

# Logging completo para producción
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Aumentar tiempo de sesión para evitar expiraciones rápidas
apihelper.SESSION_TIME_TO_LIVE = 10 * 60  # 10 minutos

# -----------------------------
# ENDPOINT WEBHOOK
# -----------------------------
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return 'OK', 200
    abort(403)

# -----------------------------
# DEBUG GLOBAL (para saber si recibe mensajes)
# -----------------------------
@bot.message_handler(func=lambda m: True)
def debug_all_messages(message):
    logger.debug(f"[DEBUG MSG] Recibido: '{message.text}' | chat_id: {message.chat.id}")
    # Comentar esta línea en prod final si no querés respuestas de debug
    # bot.reply_to(message, f"Debug: Recibí '{message.text}'")

# -----------------------------
# INICIO DEL FLUJO DE TRABAJADOR
# -----------------------------
@bot.message_handler(regexp=r'(?i)(trabajar|prestador|quiero trabajar)')
def handle_worker_start(message):
    chat_id = message.chat.id
    logger.info(f"[START] Activado por '{message.text}' | chat_id: {chat_id}")
    start_worker_flow(chat_id)

def start_worker_flow(chat_id: str):
    worker = db_execute("SELECT * FROM workers WHERE chat_id = ?", (str(chat_id),), fetch_one=True)
    
    if worker:
        from handlers.worker.profile import show_worker_menu
        show_worker_menu(chat_id, worker)
        return
    
    set_state(chat_id, UserState.WORKER_SELECTING_SERVICES, {"selected_services": []})
    
    welcome_text = f"""
{Icons.BRIEFCASE} <b>Registro de Profesional</b>

¡Excelente! Vamos a configurar tu perfil para que puedas recibir trabajos.

<b>Paso 1/5:</b> ¿Qué servicios ofrecés?
{Icons.INFO} Podés seleccionar varios
    """
    send_safe(chat_id, welcome_text, get_service_selector([]))

# -----------------------------
# SELECCIÓN DE SERVICIOS (callback)
# -----------------------------
@bot.callback_query_handler(func=lambda c: c.data.startswith("svc_toggle:"))
def handle_service_toggle(call):
    chat_id = call.message.chat.id
    service_id = call.data.split(":")[1]
    
    session = get_session(chat_id)
    if not session:
        bot.answer_callback_query(call.id, "Sesión perdida. Iniciá de nuevo.", show_alert=True)
        return
    
    selected = session.data.get("selected_services", [])
    
    if service_id in selected:
        selected.remove(service_id)
        bot.answer_callback_query(call.id, f"❌ {SERVICES[service_id]['name']} removido")
    else:
        selected.append(service_id)
        bot.answer_callback_query(call.id, f"✅ {SERVICES[service_id]['name']} agregado")
    
    update_data(chat_id, selected_services=selected)
    from handlers.common import edit_safe
    edit_safe(chat_id, call.message.message_id, call.message.text, get_service_selector(selected))

@bot.callback_query_handler(func=lambda c: c.data == "svc_confirm")
def handle_service_confirm(call):
    chat_id = call.message.chat.id
    selected = get_data(chat_id, "selected_services", [])
    
    if not selected:
        bot.answer_callback_query(call.id, "Seleccioná al menos un servicio", show_alert=True)
        return
    
    bot.answer_callback_query(call.id, f"✓ {len(selected)} servicios seleccionados")
    
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except:
        pass
    
    db_execute("INSERT OR IGNORE INTO workers (chat_id, disponible) VALUES (?, 0)", (str(chat_id),), commit=True)
    
    set_state(chat_id, UserState.WORKER_ENTERING_PRICE, {
        "services_to_price": selected[:],
        "current_service_idx": 0,
        "prices": {}
    })
    ask_next_price(chat_id)

# -----------------------------
# PRECIOS (el resto igual, solo agrego logs)
# -----------------------------
def ask_next_price(chat_id: str):
    services = get_data(chat_id, "services_to_price", [])
    idx = get_data(chat_id, "current_service_idx", 0)
    
    if idx >= len(services):
        set_state(chat_id, UserState.WORKER_ENTERING_NAME)
        text = f"""
{Icons.USER} <b>Paso 2/5: Tu nombre</b>

¿Cómo te llaman los clientes?
        """
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton("❌ Cancelar"))
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")
        return
    
    service_id = services[idx]
    text = f"""
{Icons.MONEY} <b>Precio para {SERVICES[service_id]['name']} ({idx+1}/{len(services)})</b>

Ingresá tarifa por hora (ej: 8000)
    """
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("⏭️ Saltar"))
    markup.add(types.KeyboardButton("❌ Cancelar"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

# ... (agregá los handlers de price_input, skip, name, phone, dni como en tu versión anterior, con logger.info en cada uno si querés debug)

# -----------------------------
# UBICACIÓN FINAL
# -----------------------------
def ask_worker_location(chat_id: str):
    text = f"""
📍 <b>Paso 5/5: Ubicación</b>

Tocá el botón azul abajo o clip > Ubicación.
    """
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("📍 Enviar ubicación", request_location=True))
    markup.add(types.KeyboardButton("❌ Cancelar"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(content_types=['location'])
def handle_worker_location(message):
    chat_id = message.chat.id
    logger.info(f"[LOCATION] Recibida | chat_id: {chat_id} | lat: {message.location.latitude}")

    session = get_session(chat_id)
    if not session:
        logger.warning("[LOCATION] Sesión perdida - forzando estado")
        set_state(chat_id, UserState.WORKER_SHARING_LOCATION)
        session = get_session(chat_id)

    if session.state != UserState.WORKER_SHARING_LOCATION:
        logger.warning(f"[LOCATION] Estado incorrecto: {session.state}")
        bot.send_message(chat_id, "Estado no esperado. Reiniciá con 'trabajar'.")
        return

    lat = message.location.latitude
    lon = message.location.longitude

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        send_safe(chat_id, "❌ Ubicación inválida. Intentá de nuevo.")
        return

    timestamp = int(time.time())
    try:
        db_execute(
            "UPDATE workers SET lat = ?, lon = ?, last_update = ?, disponible = 1 WHERE chat_id = ?",
            (lat, lon, timestamp, str(chat_id)),
            commit=True
        )
        logger.info(f"[LOCATION] DB actualizada OK")
    except Exception as e:
        logger.error(f"[LOCATION] Error DB: {str(e)}")
        send_safe(chat_id, f"❌ Error al guardar. Contactá soporte.")
        return

    clear_state(chat_id)
    logger.info(f"[LOCATION] Registro completado | chat_id: {chat_id}")

    final_text = f"""
🎉 <b>¡Registro completado!</b>

Estás activo y recibirás trabajos cercanos.

Comandos útiles:
/online      → Activar
/offline     → Pausar
/ubicacion   → Cambiar ubicación
/precios     → Modificar tarifas
/perfil      → Ver tu perfil
/ayuda       → Soporte

¡A romperla, loco! 💪
    """
    bot.send_message(chat_id, final_text, parse_mode="HTML", reply_markup=types.ReplyKeyboardRemove())

# -----------------------------
# SETUP WEBHOOK AL INICIO
# -----------------------------
if __name__ == "__main__":
    PORT = int(os.environ.get('PORT', 8443))
    # Usa RAILWAY_PUBLIC_DOMAIN o RAILWAY_STATIC_URL según tu plan
    domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN') or os.environ.get('RAILWAY_STATIC_URL')
    if not domain:
        logger.error("No se encontró dominio en variables de entorno. Setear RAILWAY_PUBLIC_DOMAIN")
        exit(1)
    
    WEBHOOK_URL = f"https://{domain}/webhook"

    try:
        bot.remove_webhook()
        logger.info("Webhook removido")
        bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"Webhook configurado en: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"Error seteando webhook: {str(e)}")
        exit(1)

    app.run(host='0.0.0.0', port=PORT, debug=False)
