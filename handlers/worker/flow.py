import os
import time
import re
import json
import logging
import traceback
from telebot import types, apihelper
from config import bot
from models.services_data import SERVICES
from utils.icons import Icons
from utils.keyboards import get_service_selector
from database import db_execute

# ==================== CONFIGURACIÓN ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)
apihelper.SESSION_TIME_TO_LIVE = 10 * 60

# ==================== SESIONES EN SQLITE ====================
def get_session(chat_id: str):
    row = db_execute("SELECT state, data FROM sessions WHERE chat_id = ?", (str(chat_id),), fetch_one=True)
    if row:
        state, data_json = row
        data = json.loads(data_json) if data_json else {}
        return {"state": state, "data": data}
    else:
        db_execute("INSERT INTO sessions (chat_id, state, data, last_activity) VALUES (?, ?, ?, ?)",
                   (str(chat_id), "IDLE", "{}", int(time.time())), commit=True)
        return {"state": "IDLE", "data": {}}

def set_state(chat_id: str, state: str, data: dict = None):
    session = get_session(chat_id)
    new_data = session["data"]
    if data:
        new_data.update(data)
    db_execute(
        "INSERT OR REPLACE INTO sessions (chat_id, state, data, last_activity) VALUES (?, ?, ?, ?)",
        (str(chat_id), state, json.dumps(new_data), int(time.time())),
        commit=True
    )

def update_data(chat_id: str, **kwargs):
    session = get_session(chat_id)
    new_data = session["data"]
    new_data.update(kwargs)
    db_execute(
        "UPDATE sessions SET data = ?, last_activity = ? WHERE chat_id = ?",
        (json.dumps(new_data), int(time.time()), str(chat_id)),
        commit=True
    )

def get_data(chat_id: str, key: str, default=None):
    session = get_session(chat_id)
    return session["data"].get(key, default)

def clear_state(chat_id: str):
    db_execute("DELETE FROM sessions WHERE chat_id = ?", (str(chat_id),), commit=True)

# ==================== FLUJO WORKER ====================
@bot.message_handler(regexp=r'(?i)(trabajar|prestador|quiero trabajar)')
def handle_worker_start(message):
    chat_id = message.chat.id
    try:
        logger.info(f"[START] Activado por '{message.text}' | chat_id: {chat_id}")
        start_worker_flow(chat_id)
    except Exception as e:
        logger.error(f"[START ERROR] chat_id={chat_id} -> {e}")
        bot.send_message(chat_id, "❌ Ocurrió un error iniciando tu registro. Intentá de nuevo.")

def start_worker_flow(chat_id: int):
    try:
        worker = db_execute(
            "SELECT * FROM workers WHERE chat_id = ?",
            (str(chat_id),),
            fetch_one=True
        )
        if worker:
            try:
                from handlers.worker.profile import show_worker_menu
                bot.send_chat_action(chat_id, 'typing')
                show_worker_menu(chat_id, worker)
            except:
                bot.send_message(chat_id, "Perfil activo. Función de menú no disponible.")
            return

        set_state(chat_id, "WORKER_SELECTING_SERVICES", {"selected_services": []})

        text = f"""
{Icons.BRIEFCASE} <b>Registro de Profesional</b>

Vamos a configurar tu perfil.

<b>Paso 1/5:</b> ¿Qué servicios ofrecés?
{Icons.INFO} Podés seleccionar varios.
        """
        bot.send_message(chat_id, text, reply_markup=get_service_selector([]), parse_mode="HTML")
    except Exception as e:
        logger.error(f"[FLOW START ERROR] chat_id={chat_id} -> {e}")
        bot.send_message(chat_id, "❌ Error iniciando flujo de registro.")

# ==================== SERVICIOS ====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("svc_toggle:"))
def handle_service_toggle(call):
    try:
        chat_id = call.message.chat.id
        service_id = call.data.split(":")[1]

        session = get_session(chat_id)
        if not session:
            bot.answer_callback_query(call.id, "Sesión perdida. Iniciá de nuevo.", show_alert=True)
            return

        selected = session["data"].get("selected_services", [])
        if service_id in selected:
            selected.remove(service_id)
            bot.answer_callback_query(call.id, f"❌ {SERVICES[service_id]['name']} removido")
        else:
            selected.append(service_id)
            bot.answer_callback_query(call.id, f"✅ {SERVICES[service_id]['name']} agregado")

        update_data(chat_id, selected_services=selected)
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=get_service_selector(selected))
    except Exception as e:
        logger.error(f"[SERVICE TOGGLE ERROR] chat_id={call.message.chat.id} -> {e}")
        bot.answer_callback_query(call.id, "❌ Ocurrió un error.", show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data == "svc_confirm")
def handle_service_confirm(call):
    try:
        chat_id = call.message.chat.id
        selected = get_data(chat_id, "selected_services", [])
        if not selected:
            bot.answer_callback_query(call.id, "Seleccioná al menos un servicio", show_alert=True)
            return

        bot.answer_callback_query(call.id)
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass

        set_state(chat_id, "WORKER_ENTERING_PRICE", {
            "services_to_price": selected[:],
            "current_service_idx": 0,
            "prices": {}
        })
        ask_next_price(chat_id)
    except Exception as e:
        logger.error(f"[SERVICE CONFIRM ERROR] chat_id={call.message.chat.id} -> {e}")
        bot.answer_callback_query(call.id, "❌ Ocurrió un error confirmando servicios.", show_alert=True)

# ==================== PRECIOS ====================
def ask_next_price(chat_id: str):
    services = get_data(chat_id, "services_to_price", [])
    idx = get_data(chat_id, "current_service_idx", 0)

    if idx >= len(services):
        set_state(chat_id, "WORKER_ENTERING_NAME")
        ask_worker_name(chat_id)
        return

    service_id = services[idx]
    service_name = SERVICES.get(service_id, {}).get("name", service_id)

    text = f"{Icons.MONEY} <b>Precio para {service_name} ({idx+1}/{len(services)})</b>\nIngresá tarifa por hora (solo números)"
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("⏭️ Saltar")
    markup.add("❌ Cancelar")
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(func=lambda m: get_session(m.chat.id)["state"] == "WORKER_ENTERING_PRICE")
def handle_price_input(message):
    chat_id = message.chat.id
    text = message.text.strip()
    if text == "❌ Cancelar":
        cancel_flow(chat_id)
        return

    services = get_data(chat_id, "services_to_price", [])
    idx = get_data(chat_id, "current_service_idx", 0)

    if text == "⏭️ Saltar":
        prices = get_data(chat_id, "prices", {})
        prices[services[idx]] = None
        update_data(chat_id, prices=prices, current_service_idx=idx+1)
        ask_next_price(chat_id)
        return

    if not text.isdigit():
        bot.send_message(chat_id, "❌ Ingresá solo números.")
        return

    price = int(text)
    prices = get_data(chat_id, "prices", {})
    prices[services[idx]] = price
    update_data(chat_id, prices=prices, current_service_idx=idx+1)
    bot.send_message(chat_id, f"✅ Precio guardado: ${price}/hora")
    ask_next_price(chat_id)

# ==================== NOMBRE ====================
def ask_worker_name(chat_id: str):
    text = f"{Icons.USER} <b>Paso 2/5: Tu nombre</b>\n¿Cómo te llaman los clientes?"
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("❌ Cancelar")
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(func=lambda m: get_session(m.chat.id)["state"] == "WORKER_ENTERING_NAME")
def handle_name_input(message):
    chat_id = message.chat.id
    name = message.text.strip()
    if name == "❌ Cancelar":
        cancel_flow(chat_id)
        return
    if len(name) < 2:
        bot.send_message(chat_id, "❌ Nombre muy corto.")
        return

    update_data(chat_id, worker_name=name)
    set_state(chat_id, "WORKER_ENTERING_PHONE")
    ask_worker_phone(chat_id)

# ==================== TELÉFONO ====================
def ask_worker_phone(chat_id: str):
    text = f"{Icons.PHONE} <b>Paso 3/5: Teléfono</b>\nIngresá tu número de contacto."
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("❌ Cancelar"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(func=lambda m: get_session(m.chat.id)["state"] == "WORKER_ENTERING_PHONE")
def handle_phone_input(message):
    chat_id = message.chat.id
    phone = re.sub(r"\D", "", message.text.strip())
    if message.text == "❌ Cancelar":
        cancel_flow(chat_id)
        return
    if len(phone) < 8:
        bot.send_message(chat_id, "❌ Número inválido. Ingresá al menos 8 dígitos.")
        return

    update_data(chat_id, worker_phone=phone)
    set_state(chat_id, "WORKER_ENTERING_DNI")
    ask_worker_dni(chat_id)

# ==================== DNI ====================
def ask_worker_dni(chat_id: str):
    text = f"{Icons.USER} <b>Paso 4/5: DNI</b>\nIngresá tu documento (7 u 8 dígitos)."
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("❌ Cancelar"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(func=lambda m: get_session(m.chat.id)["state"] == "WORKER_ENTERING_DNI")
def handle_dni_input(message):
    chat_id = message.chat.id
    dni = re.sub(r"\D", "", message.text.strip())
    if message.text == "❌ Cancelar":
        cancel_flow(chat_id)
        return
    if not (7 <= len(dni) <= 8):
        bot.send_message(chat_id, "❌ DNI inválido. Debe tener 7 u 8 dígitos.")
        return

    save_worker_data(chat_id, dni)
    set_state(chat_id, "WORKER_SHARING_LOCATION")
    ask_worker_location(chat_id)

# ==================== UBICACIÓN ====================
def ask_worker_location(chat_id: str):
    text = f"{Icons.LOCATION} <b>Paso 5/5: Ubicación</b>\nTocá el botón azul para enviar tu ubicación."
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("📍 Enviar ubicación", request_location=True))
    markup.add("❌ Cancelar")
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(content_types=['location'])
def handle_location(message):
    chat_id = message.chat.id
    session = get_session(chat_id)
    if not session or session["state"] != "WORKER_SHARING_LOCATION":
        return
    if not message.location:
        bot.send_message(chat_id, "❌ No se recibió la ubicación. Intentá de nuevo.", reply_markup=types.ReplyKeyboardRemove())
        return

    lat = message.location.latitude
    lon = message.location.longitude
    timestamp = int(time.time())

    worker = db_execute("SELECT chat_id FROM workers WHERE chat_id = ?", (str(chat_id),), fetch_one=True)
    if not worker:
        bot.send_message(chat_id, "❌ Error: Perfil no encontrado. Reiniciá con /start", reply_markup=types.ReplyKeyboardRemove())
        return

    db_execute("UPDATE workers SET lat=?, lon=?, last_update=?, disponible=1 WHERE chat_id=?",
               (lat, lon, timestamp, str(chat_id)), commit=True)

    bot.send_message(chat_id, f"{Icons.PARTY} <b>¡Registro completado!</b>\n\nYa estás activo 💪",
                     parse_mode="HTML", reply_markup=types.ReplyKeyboardRemove())
    try:
        from handlers.worker.profile import show_worker_menu
        worker_data = db_execute("SELECT * FROM workers WHERE chat_id=?", (str(chat_id),), fetch_one=True)
        if worker_data:
            show_worker_menu(chat_id, worker_data)
    except:
        pass
    clear_state(chat_id)

# ==================== CANCELAR FLUJO ====================
def cancel_flow(chat_id: str):
    clear_state(chat_id)
    bot.send_message(chat_id, "❌ Registro cancelado. Escribí 'trabajar' para reiniciar.", reply_markup=types.ReplyKeyboardRemove())

# ==================== GUARDAR WORKER EN DB ====================
def save_worker_data(chat_id: str, dni: str):
    name = get_data(chat_id, "worker_name")
    phone = get_data(chat_id, "worker_phone")
    prices = get_data(chat_id, "prices", {})
    selected_services = get_data(chat_id, "selected_services", [])

    if not name or not phone:
        bot.send_message(chat_id, "❌ Faltan datos. Reiniciá el registro.", reply_markup=types.ReplyKeyboardRemove())
        clear_state(chat_id)
        return

    db_execute("""
        INSERT OR REPLACE INTO workers (chat_id, nombre, telefono, dni_file_id, disponible, lat, lon, last_update)
        VALUES (?, ?, ?, ?, 0, NULL, NULL, NULL)
    """, (str(chat_id), name, phone, dni), commit=True)

    db_execute("DELETE FROM worker_services WHERE chat_id=?", (str(chat_id),), commit=True)

    for service_id in selected_services:
        precio = float(prices.get(service_id) or 0)
        db_execute(
            "INSERT OR REPLACE INTO worker_services (chat_id, service_id, precio) VALUES (?, ?, ?)",
            (str(chat_id), service_id, precio),
            commit=True
    )
