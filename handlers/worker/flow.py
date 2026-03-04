import os
import time
import re
import logging
from telebot import types, apihelper
from config import bot
from models.user_state import (
    set_state, update_data, get_data,
    clear_state, UserState, get_session
)
from models.services_data import SERVICES
from utils.icons import Icons
from utils.keyboards import get_service_selector
from handlers.common import send_safe, edit_safe
from database import db_execute


# ==================== CONFIGURACIÓN ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger(__name__)
apihelper.SESSION_TIME_TO_LIVE = 10 * 60


# ======================================================
# ==================== FLUJO WORKER ====================
# ======================================================

@bot.message_handler(regexp=r'(?i)(trabajar|prestador|quiero trabajar)')
def handle_worker_start(message):
    chat_id = message.chat.id
    logger.info(f"[START] Activado por '{message.text}' | chat_id: {chat_id}")
    start_worker_flow(chat_id)


def start_worker_flow(chat_id: int):
    worker = db_execute(
        "SELECT * FROM workers WHERE chat_id = ?",
        (str(chat_id),),
        fetch_one=True
    )

    if worker:
        from handlers.worker.profile import show_worker_menu
        show_worker_menu(chat_id, worker)
        return

    set_state(chat_id, UserState.WORKER_SELECTING_SERVICES, {
        "selected_services": []
    })

    text = f"""
{Icons.BRIEFCASE} <b>Registro de Profesional</b>

Vamos a configurar tu perfil.

<b>Paso 1/5:</b> ¿Qué servicios ofrecés?
{Icons.INFO} Podés seleccionar varios.
    """

    send_safe(chat_id, text, get_service_selector([]))


# ======================================================
# ==================== SERVICIOS =======================
# ======================================================

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
    edit_safe(chat_id, call.message.message_id, call.message.text, get_service_selector(selected))


@bot.callback_query_handler(func=lambda c: c.data == "svc_confirm")
def handle_service_confirm(call):
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

    db_execute(
        "INSERT OR IGNORE INTO workers (chat_id, disponible) VALUES (?, 0)",
        (str(chat_id),),
        commit=True
    )

    set_state(chat_id, UserState.WORKER_ENTERING_PRICE, {
        "services_to_price": selected[:],
        "current_service_idx": 0,
        "prices": {}
    })

    ask_next_price(chat_id)


# ======================================================
# ==================== PRECIOS =========================
# ======================================================

def ask_next_price(chat_id: int):
    services = get_data(chat_id, "services_to_price", [])
    idx = get_data(chat_id, "current_service_idx", 0)

    if idx >= len(services):
        set_state(chat_id, UserState.WORKER_ENTERING_NAME)
        ask_worker_name(chat_id)
        return

    service_id = services[idx]
    service_name = SERVICES.get(service_id, {}).get("name", service_id)

    text = f"""
{Icons.MONEY} <b>Precio para {service_name} ({idx+1}/{len(services)})</b>

Ingresá tarifa por hora (solo números)
    """

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("⏭️ Saltar")
    markup.add("❌ Cancelar")

    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")


@bot.message_handler(func=lambda m:
    get_session(m.chat.id)
    and get_session(m.chat.id).state == UserState.WORKER_ENTERING_PRICE
)
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
        update_data(chat_id, prices=prices, current_service_idx=idx + 1)
        ask_next_price(chat_id)
        return

    if not text.isdigit():
        bot.send_message(chat_id, "❌ Ingresá solo números.")
        return

    price = int(text)

    prices = get_data(chat_id, "prices", {})
    prices[services[idx]] = price
    update_data(chat_id, prices=prices, current_service_idx=idx + 1)

    bot.send_message(chat_id, f"✅ Precio guardado: ${price}/hora")
    ask_next_price(chat_id)


# ======================================================
# ==================== NOMBRE ==========================
# ======================================================

def ask_worker_name(chat_id: int):
    text = f"""
{Icons.USER} <b>Paso 2/5: Tu nombre</b>

¿Cómo te llaman los clientes?
    """

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("❌ Cancelar")

    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")


@bot.message_handler(func=lambda m:
    get_session(m.chat.id)
    and get_session(m.chat.id).state == UserState.WORKER_ENTERING_NAME
)
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
    set_state(chat_id, UserState.WORKER_ENTERING_PHONE)
    ask_worker_phone(chat_id)


# ======================================================
# ==================== TELÉFONO ========================
# ======================================================

def ask_worker_phone(chat_id: int):
    text = f"""
{Icons.PHONE} <b>Paso 3/5: Teléfono</b>

Ingresá tu número de contacto.
"""

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("❌ Cancelar"))

    bot.send_message(
        chat_id,
        text,
        reply_markup=markup,
        parse_mode="HTML"
    )


@bot.message_handler(func=lambda m: (
    m.text is not None and
    get_session(m.chat.id) is not None and
    get_session(m.chat.id).state == UserState.WORKER_ENTERING_PHONE
))
def handle_phone_input(message):
    chat_id = message.chat.id
    phone = message.text.strip()

    if phone == "❌ Cancelar":
        cancel_flow(chat_id)
        return

    # Solo números
    digits = re.sub(r"\D", "", phone)

    if len(digits) < 8:
        bot.send_message(chat_id, "❌ Número inválido. Ingresá al menos 8 dígitos.")
        return

    # Guardar número limpio
    update_data(chat_id, worker_phone=digits)

    # Cambiar estado
    set_state(chat_id, UserState.WORKER_ENTERING_DNI)

    # Ir al siguiente paso
    ask_worker_dni(chat_id)


# ======================================================
# ==================== DNI =============================
# ======================================================

def ask_worker_dni(chat_id: int):
    text = f"""
{Icons.USER} <b>Paso 4/5: DNI</b>

Ingresá tu documento (7 u 8 dígitos).
    """

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("❌ Cancelar")

    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")


@bot.message_handler(func=lambda m:
    get_session(m.chat.id)
    and get_session(m.chat.id).state == UserState.WORKER_ENTERING_DNI
)
def handle_dni_input(message):
    chat_id = message.chat.id
    dni = re.sub(r'\D', '', message.text.strip())

    if not (7 <= len(dni) <= 8):
        bot.send_message(chat_id, "❌ DNI inválido.")
        return

    save_worker_data(chat_id, dni)
    set_state(chat_id, UserState.WORKER_SHARING_LOCATION)
    ask_worker_location(chat_id)


def save_worker_data(chat_id: int, dni: str):
    name = get_data(chat_id, "worker_name")
    phone = get_data(chat_id, "worker_phone")
    prices = get_data(chat_id, "prices", {})
    selected_services = get_data(chat_id, "selected_services", [])

    db_execute("""
        UPDATE workers 
        SET name = ?, phone = ?, dni = ?, services = ?, prices = ?
        WHERE chat_id = ?
    """, (
        name,
        phone,
        dni,
        ",".join(selected_services),
        str(prices),
        str(chat_id)
    ), commit=True)


# ======================================================
# ==================== UBICACIÓN =======================
# ======================================================

def ask_worker_location(chat_id: int):
    text = f"""
{Icons.LOCATION} <b>Paso 5/5: Ubicación</b>

Tocá el botón azul para enviar tu ubicación.
    """

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("📍 Enviar ubicación", request_location=True))
    markup.add("❌ Cancelar")

    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")


@bot.message_handler(content_types=['location'])
def handle_location(message):
    chat_id = message.chat.id
    session = get_session(chat_id)

    if not session or session.state != UserState.WORKER_SHARING_LOCATION:
        return

    lat = message.location.latitude
    lon = message.location.longitude
    timestamp = int(time.time())

    db_execute("""
        UPDATE workers 
        SET lat = ?, lon = ?, last_update = ?, disponible = 1
        WHERE chat_id = ?
    """, (lat, lon, timestamp, str(chat_id)), commit=True)

    clear_state(chat_id)

    bot.send_message(
        chat_id,
        f"{Icons.PARTY} <b>¡Registro completado!</b>\n\nYa estás activo 💪",
        parse_mode="HTML",
        reply_markup=types.ReplyKeyboardRemove()
    )


# ======================================================
# ==================== UTIL ============================
# ======================================================

def cancel_flow(chat_id: int):
    clear_state(chat_id)
    bot.send_message(
        chat_id,
        "Registro cancelado.",
        reply_markup=types.ReplyKeyboardRemove()
    )


# ======================================================
# ==================== POLLING =========================
# ======================================================

if __name__ == "__main__":
    logger.info("Bot iniciado en modo POLLING")

    while True:
        try:
            bot.infinity_polling(
                timeout=60,
                long_polling_timeout=30,
                skip_pending=True
            )
        except Exception as e:
            logger.error(f"Error en polling: {e}")
            time.sleep(10)
