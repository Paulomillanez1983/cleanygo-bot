import os
from flask import Flask, request, abort
from telebot import types, apihelper
from config import bot
from models.user_state import set_state, update_data, get_data, clear_state, UserState, get_session
from models.services_data import SERVICES
from utils.icons import Icons
from utils.keyboards import get_service_selector
from handlers.common import send_safe, edit_safe  # <-- IMPORTAR AQUÍ ARRIBA
from database import db_execute
import re
import time
import logging

app = Flask(__name__)

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

apihelper.SESSION_TIME_TO_LIVE = 10 * 60

# ==================== WEBHOOK ====================

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return 'OK', 200
    abort(403)

# ==================== DEBUG ====================

@bot.message_handler(func=lambda m: True, content_types=['text'])
def debug_all_messages(message):
    session = get_session(message.chat.id)

    # Solo loguea si no hay estado activo
    if not session:
        logger.debug(
            f"[DEBUG] Recibido: '{message.text}' | chat_id: {message.chat.id}"
        )
# ==================== FLUJO TRABAJADOR ====================

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

# ==================== SERVICIOS (CALLBACKS) ====================

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
    # USAR edit_safe IMPORTADO ARRIBA
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

# ==================== PRECIOS ====================

def ask_next_price(chat_id: str):
    services = get_data(chat_id, "services_to_price", [])
    idx = get_data(chat_id, "current_service_idx", 0)
    
    if idx >= len(services):
        # Terminamos con precios, pasar a nombre
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
    service_name = SERVICES.get(service_id, {}).get('name', service_id)
    
    text = f"""
{Icons.MONEY} <b>Precio para {service_name} ({idx+1}/{len(services)})</b>

Ingresá tarifa por hora (solo números, ej: 8000)
    """
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("⏭️ Saltar"))
    markup.add(types.KeyboardButton("❌ Cancelar"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(func=lambda m: get_session(m.chat.id) and get_session(m.chat.id).state == UserState.WORKER_ENTERING_PRICE)
def handle_price_input(message):
    chat_id = message.chat.id
    text = message.text.strip()
    
    logger.info(f"[PRICE] Input: '{text}' | chat_id: {chat_id}")
    
    if text == "❌ Cancelar":
        clear_state(chat_id)
        bot.send_message(chat_id, "Registro cancelado. Escribí 'trabajar' para reiniciar.", reply_markup=types.ReplyKeyboardRemove())
        return
    
    services = get_data(chat_id, "services_to_price", [])
    idx = get_data(chat_id, "current_service_idx", 0)
    
    # Seguridad: si ya terminamos los servicios, pasar a nombre
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
    
    if text == "⏭️ Saltar":
        # Guardar precio como None o 0
        prices = get_data(chat_id, "prices", {})
        prices[services[idx]] = None
        update_data(chat_id, prices=prices, current_service_idx=idx + 1)
        ask_next_price(chat_id)
        return
    
    # Validar que sea número
    if not text.isdigit():
        bot.send_message(chat_id, "❌ Ingresá solo números (ej: 8000)")
        return
    
    price = int(text)
    prices = get_data(chat_id, "prices", {})
    prices[services[idx]] = price
    update_data(chat_id, prices=prices, current_service_idx=idx + 1)
    
    bot.send_message(chat_id, f"✅ Precio guardado: ${price}/hora")
    ask_next_price(chat_id)

# ==================== NOMBRE ====================

@bot.message_handler(func=lambda m: get_session(m.chat.id) and get_session(m.chat.id).state == UserState.WORKER_ENTERING_NAME)
def handle_name_input(message):
    chat_id = message.chat.id
    name = message.text.strip()
    
    logger.info(f"[NAME] Input: '{name}' | chat_id: {chat_id}")
    
    if name == "❌ Cancelar":
        clear_state(chat_id)
        bot.send_message(chat_id, "Registro cancelado.", reply_markup=types.ReplyKeyboardRemove())
        return
    
    if len(name) < 2:
        bot.send_message(chat_id, "❌ El nombre es muy corto. Intentá de nuevo.")
        return
    
    # Guardar en session
    update_data(chat_id, worker_name=name)
    
    # Pasar a teléfono
    set_state(chat_id, UserState.WORKER_ENTERING_PHONE)
    text = f"""
{Icons.PHONE} <b>Paso 3/5: Teléfono</b>

Ingresá tu número de contacto (ej: 11 1234-5678)
    """
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("❌ Cancelar"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

# ==================== TELÉFONO ====================

@bot.message_handler(func=lambda m: get_session(m.chat.id) and get_session(m.chat.id).state == UserState.WORKER_ENTERING_PHONE)
def handle_phone_input(message):
    chat_id = message.chat.id
    phone = message.text.strip()
    
    logger.info(f"[PHONE] Input: '{phone}' | chat_id: {chat_id}")
    
    if phone == "❌ Cancelar":
        clear_state(chat_id)
        bot.send_message(chat_id, "Registro cancelado.", reply_markup=types.ReplyKeyboardRemove())
        return
    
    # Validación básica de teléfono (al menos 8 dígitos)
    phone_digits = re.sub(r'\D', '', phone)
    if len(phone_digits) < 8:
        bot.send_message(chat_id, "❌ Número inválido. Ingresá al menos 8 dígitos.")
        return
    
    update_data(chat_id, worker_phone=phone)
    
    # Pasar a DNI
    set_state(chat_id, UserState.WORKER_ENTERING_DNI)
    text = f"""
{Icons.USER} <b>Paso 4/5: DNI</b>

Ingresá tu número de documento (sin puntos ni espacios)
    """
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("❌ Cancelar"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

# ==================== DNI ====================

@bot.message_handler(func=lambda m: get_session(m.chat.id) and get_session(m.chat.id).state == UserState.WORKER_ENTERING_DNI)
def handle_dni_input(message):
    chat_id = message.chat.id
    dni = message.text.strip()
    
    logger.info(f"[DNI] Input: '{dni}' | chat_id: {chat_id}")
    
    if dni == "❌ Cancelar":
        clear_state(chat_id)
        bot.send_message(chat_id, "Registro cancelado.", reply_markup=types.ReplyKeyboardRemove())
        return
    
    # Validar DNI (7-8 dígitos)
    dni_clean = re.sub(r'\D', '', dni)
    if not (7 <= len(dni_clean) <= 8):
        bot.send_message(chat_id, "❌ DNI inválido. Debe tener 7 u 8 dígitos.")
        return
    
    # Guardar todos los datos en DB
    name = get_data(chat_id, "worker_name")
    phone = get_data(chat_id, "worker_phone")
    prices = get_data(chat_id, "prices", {})
    selected_services = get_data(chat_id, "selected_services", [])
    
    try:
        db_execute(
            """UPDATE workers 
               SET name = ?, phone = ?, dni = ?, services = ?, prices = ? 
               WHERE chat_id = ?""",
            (name, phone, dni_clean, ','.join(selected_services), str(prices), str(chat_id)),
            commit=True
        )
        logger.info(f"[DNI] Datos guardados en DB")
    except Exception as e:
        logger.error(f"[DNI] Error DB: {e}")
        bot.send_message(chat_id, "❌ Error al guardar. Intentá de nuevo.")
        return
    
    # Pasar a ubicación
    set_state(chat_id, UserState.WORKER_SHARING_LOCATION)
    ask_worker_location(chat_id)

# ==================== UBICACIÓN ====================

def ask_worker_location(chat_id: str):
    text = f"""
{Icons.LOCATION} <b>Paso 5/5: Ubicación</b>

Tocá el botón azul abajo o clip > Ubicación para enviar dónde trabajás.
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
    
    # Si no hay sesión o no está en el estado correcto, ignorar (puede ser de otro flujo)
    if not session or session.state != UserState.WORKER_SHARING_LOCATION:
        logger.warning(f"[LOCATION] Ignorando - estado: {session.state if session else 'None'}")
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
{Icons.PARTY} <b>¡Registro completado!</b>

Estás activo y recibirás trabajos cercanos.

Comandos útiles:
/online      → Activar
/offline     → Pausar
/ubicacion   → Cambiar ubicación
/precios     → Modificar tarifas
/perfil      → Ver tu perfil
/ayuda       → Soporte

¡A romperla! 💪
    """
    bot.send_message(chat_id, final_text, parse_mode="HTML", reply_markup=types.ReplyKeyboardRemove())

# ==================== INICIO ====================

if __name__ == "__main__":
    PORT = int(os.environ.get('PORT', 8443))
    domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN') or os.environ.get('RAILWAY_STATIC_URL')
    
    if not domain:
        logger.error("No se encontró dominio en variables de entorno.")
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
