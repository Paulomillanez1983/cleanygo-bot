"""
Worker flow - Registro de trabajadores
"""

import time
import re
import traceback
from telebot import types, apihelper

from config import logger, get_bot, db_execute, set_state, update_data, get_data, clear_state, get_session
from models.states import UserState
from models.services_data import SERVICES
from utils.icons import Icons

bot = get_bot()

apihelper.SESSION_TIME_TO_LIVE = 10 * 60


ACTIVE_WORKER_STATES = [
    UserState.WORKER_SELECTING_SERVICES.value,
    UserState.WORKER_ENTERING_NAME.value,
    UserState.WORKER_ENTERING_PHONE.value,
    UserState.WORKER_ENTERING_DNI.value,
    UserState.WORKER_SHARING_LOCATION.value,
]


# =====================================================
# START FLOW
# =====================================================

def start_worker_flow(chat_id):
    try:
        logger.info(f"[START FLOW] chat_id={chat_id}")

        existing = db_execute(
            "SELECT 1 FROM workers WHERE chat_id = ?",
            (str(chat_id),),
            fetch_one=True
        )

        if existing:
            bot.send_message(chat_id, f"{Icons.INFO} Ya tenés un perfil registrado.")
            return

        clear_state(chat_id)

        set_state(chat_id, UserState.WORKER_SELECTING_SERVICES.value)

        bot.send_message(
            chat_id,
            f"{Icons.BRIEFCASE} Iniciando registro profesional...",
            reply_markup=types.ReplyKeyboardRemove()
        )

        _send_service_selector(chat_id, [])

    except Exception as e:
        logger.error(f"[START FLOW ERROR] {chat_id}: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(chat_id, f"{Icons.ERROR} Error iniciando. Usá /start")


# =====================================================
# SERVICIOS
# =====================================================

def _send_service_selector(chat_id, selected_services):

    text = (
        f"{Icons.BRIEFCASE} <b>Registro Profesional</b>\n\n"
        f"Paso 1/5\n"
        f"Seleccioná los servicios que ofrecés:"
    )

    markup = _build_service_markup(selected_services)

    bot.send_message(
        chat_id,
        text,
        parse_mode="HTML",
        reply_markup=markup
    )


def _build_service_markup(selected_services):

    if not isinstance(selected_services, list):
        selected_services = []

    markup = types.InlineKeyboardMarkup(row_width=2)

    for svc_id, svc in SERVICES.items():

        name = svc["name"]
        is_selected = svc_id in selected_services

        text = f"{'✅ ' if is_selected else ''}{name}"

        markup.add(
            types.InlineKeyboardButton(
                text=text,
                callback_data=f"svc_toggle:{svc_id}"
            )
        )

    markup.add(
        types.InlineKeyboardButton(
            "Confirmar ✅",
            callback_data="svc_confirm"
        )
    )

    return markup


# =====================================================
# CALLBACKS
# =====================================================

@bot.callback_query_handler(func=lambda c: c.data.startswith("svc_toggle:"))
def handle_service_toggle(call):

    chat_id = call.message.chat.id
    message_id = call.message.message_id

    try:

        service_id = call.data.split(":")[1]

        selected = get_data(chat_id, "selected_services") or []

        if service_id in selected:
            selected.remove(service_id)
        else:
            selected.append(service_id)

        update_data(chat_id, selected_services=selected)

        new_markup = _build_service_markup(selected)

        bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=new_markup
        )

        bot.answer_callback_query(call.id)

    except Exception as e:

        logger.error(f"[TOGGLE ERROR] {chat_id}: {e}")
        bot.answer_callback_query(call.id, "Error")


@bot.callback_query_handler(func=lambda c: c.data == "svc_confirm")
def handle_service_confirm(call):

    chat_id = call.message.chat.id

    try:

        selected = get_data(chat_id, "selected_services") or []

        if not selected:
            bot.answer_callback_query(
                call.id,
                "⚠️ Seleccioná al menos un servicio",
                show_alert=True
            )
            return

        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass

        set_state(chat_id, UserState.WORKER_ENTERING_NAME.value)

        bot.send_message(
            chat_id,
            "📝 <b>Paso 2/5</b>\n¿Cuál es tu nombre completo?",
            parse_mode="HTML"
        )

        bot.answer_callback_query(call.id)

    except Exception as e:

        logger.error(f"[CONFIRM ERROR] {chat_id}: {e}")
        bot.answer_callback_query(call.id, "Error", show_alert=True)


# =====================================================
# DISPATCHER
# =====================================================

@bot.message_handler(func=lambda m: get_session(m.chat.id).get("state") in ACTIVE_WORKER_STATES)
def worker_flow_dispatcher(message):

    chat_id = message.chat.id
    current_state = get_session(chat_id).get("state")

    try:

        if current_state == UserState.WORKER_ENTERING_NAME.value:
            _process_name_input(message, chat_id)

        elif current_state == UserState.WORKER_ENTERING_PHONE.value:
            _process_phone_input(message, chat_id)

        elif current_state == UserState.WORKER_ENTERING_DNI.value:
            _process_dni_input(message, chat_id)

        elif current_state == UserState.WORKER_SHARING_LOCATION.value:
            _process_location_text(message, chat_id)

    except Exception as e:

        logger.error(f"[DISPATCHER ERROR] {chat_id}: {e}")
        bot.send_message(chat_id, f"{Icons.ERROR} Error. Escribí /start")


# =====================================================
# NOMBRE
# =====================================================

def _process_name_input(message, chat_id):

    text = (message.text or "").strip()

    if len(text) < 2:
        bot.send_message(chat_id, "❌ Nombre muy corto")
        return

    update_data(chat_id, worker_name=text)

    set_state(chat_id, UserState.WORKER_ENTERING_PHONE.value)

    bot.send_message(
        chat_id,
        f"👤 Nombre: {text}\n\n📱 Paso 3/5\n¿Cuál es tu teléfono?"
    )


# =====================================================
# PHONE
# =====================================================

def _process_phone_input(message, chat_id):

    if not message.text:
        bot.send_message(chat_id, "❌ Necesito un número")
        return

    phone = re.sub(r"\D", "", message.text)

    if len(phone) < 8:
        bot.send_message(chat_id, "❌ Número muy corto")
        return

    update_data(chat_id, worker_phone=phone)

    set_state(chat_id, UserState.WORKER_ENTERING_DNI.value)

    bot.send_message(
        chat_id,
        "🆔 Paso 4/5\n¿Cuál es tu DNI?"
    )


# =====================================================
# DNI
# =====================================================

def _process_dni_input(message, chat_id):

    if not message.text:
        bot.send_message(chat_id, "❌ Necesito DNI")
        return

    dni = re.sub(r"\D", "", message.text)

    if len(dni) < 7:
        bot.send_message(chat_id, "❌ DNI inválido")
        return

    update_data(chat_id, worker_dni=dni)

    try:

        _save_worker_to_db(chat_id)

        set_state(chat_id, UserState.WORKER_SHARING_LOCATION.value)

        _request_location(chat_id)

    except Exception as e:

        logger.error(f"[DNI ERROR] {chat_id}: {e}")
        bot.send_message(chat_id, f"{Icons.ERROR} Error guardando datos")


# =====================================================
# SAVE WORKER
# =====================================================

def _save_worker_to_db(chat_id):

    name = get_data(chat_id, "worker_name")
    phone = get_data(chat_id, "worker_phone")
    dni = get_data(chat_id, "worker_dni")
    services = get_data(chat_id, "selected_services") or []

    now = int(time.time())

    db_execute(
        """
        INSERT OR REPLACE INTO workers
        (chat_id, name, phone, dni, is_active, created_at)
        VALUES (?,?,?,?,0,?)
        """,
        (str(chat_id), name, phone, dni, now)
    )

    db_execute(
        "DELETE FROM worker_services WHERE chat_id = ?",
        (str(chat_id),)
    )

    for svc in services:

        db_execute(
            """
            INSERT INTO worker_services
            (chat_id, service_id)
            VALUES (?,?)
            """,
            (str(chat_id), svc)
        )

    logger.info(f"[WORKER SAVED] {chat_id}")


# =====================================================
# LOCATION
# =====================================================

def _request_location(chat_id):

    markup = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        one_time_keyboard=True
    )

    markup.add(
        types.KeyboardButton(
            "📍 Enviar ubicación",
            request_location=True
        )
    )

    markup.add(
        types.KeyboardButton("❌ Cancelar registro")
    )

    bot.send_message(
        chat_id,
        "📍 Paso 5/5\nCompartí tu ubicación",
        reply_markup=markup
    )


def _process_location_text(message, chat_id):

    if message.text and "cancelar" in message.text.lower():

        clear_state(chat_id)

        db_execute(
            "DELETE FROM workers WHERE chat_id = ? AND is_active = 0",
            (str(chat_id),)
        )

        bot.send_message(
            chat_id,
            "Registro cancelado",
            reply_markup=types.ReplyKeyboardRemove()
        )


@bot.message_handler(content_types=["location"])
def handle_location_shared(message):

    chat_id = message.chat.id

    if get_session(chat_id).get("state") != UserState.WORKER_SHARING_LOCATION.value:
        return

    try:

        lat = message.location.latitude
        lon = message.location.longitude
        now = int(time.time())

        db_execute(
            """
            UPDATE workers
            SET lat=?, lon=?, is_active=1, last_seen=?
            WHERE chat_id=?
            """,
            (lat, lon, now, str(chat_id))
        )

        clear_state(chat_id)

        bot.send_message(
            chat_id,
            "🎉 Registro completado!",
            reply_markup=types.ReplyKeyboardRemove()
        )

        logger.info(f"[WORKER COMPLETE] {chat_id}")

    except Exception as e:

        logger.error(f"[LOCATION ERROR] {chat_id}: {e}")

        bot.send_message(
            chat_id,
            "Error guardando ubicación",
            reply_markup=types.ReplyKeyboardRemove()
        )
