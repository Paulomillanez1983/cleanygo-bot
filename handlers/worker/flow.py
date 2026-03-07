import os
import time
import re
import json
import logging
import traceback
from telebot import types, apihelper
from config import get_bot
bot = get_bot()

from models.services_data import SERVICES
from utils.icons import Icons
from database import db_execute

# ==================== CONFIGURACIÓN ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger(__name__)
apihelper.SESSION_TIME_TO_LIVE = 10 * 60


# ==================== SESIONES ====================

def get_session(chat_id):

    row = db_execute(
        "SELECT state, data FROM sessions WHERE chat_id = ?",
        (str(chat_id),),
        fetch_one=True
    )

    if row:
        state, data_json = row

        try:
            data = json.loads(data_json) if data_json else {}

        except Exception:
            logger.error(f"[SESSION] JSON corrupto para {chat_id} - reiniciando")

            db_execute(
                "UPDATE sessions SET state='IDLE', data='{}', last_activity=? WHERE chat_id=?",
                (int(time.time()), str(chat_id))
            )

            return {"state": "IDLE", "data": {}}

        return {"state": state, "data": data}

    db_execute(
        "INSERT INTO sessions (chat_id,state,data,last_activity) VALUES (?,?,?,?)",
        (str(chat_id), "IDLE", "{}", int(time.time()))
    )

    return {"state": "IDLE", "data": {}}


def safe_json(data):

    if isinstance(data, dict):
        return {k: safe_json(v) for k, v in data.items()}

    if isinstance(data, list):
        return [safe_json(x) for x in data]

    if isinstance(data, (str, int, float, type(None))):
        return data

    return str(data)


def set_state(chat_id, state, data=None):

    session = get_session(chat_id)
    new_data = session["data"]

    if data:
        new_data.update(data)

    db_execute(
        "INSERT OR REPLACE INTO sessions (chat_id,state,data,last_activity) VALUES (?,?,?,?)",
        (
            str(chat_id),
            state,
            json.dumps(safe_json(new_data)),
            int(time.time())
        )
    )


def update_data(chat_id, **kwargs):

    session = get_session(chat_id)
    new_data = session["data"]

    new_data.update(kwargs)

    db_execute(
        "UPDATE sessions SET data=?, last_activity=? WHERE chat_id=?",
        (
            json.dumps(safe_json(new_data)),
            int(time.time()),
            str(chat_id)
        )
    )


def get_data(chat_id, key, default=None):

    session = get_session(chat_id)

    return session["data"].get(key, default)


def clear_state(chat_id):

    db_execute(
        "DELETE FROM sessions WHERE chat_id=?",
        (str(chat_id),)
    )


# ==================== WORKER START ====================

@bot.message_handler(func=lambda m: m.text and "trabajar" in m.text.lower())
def handle_worker_start(message):

    chat_id = message.chat.id

    try:

        logger.info(f"[START] Activado por '{message.text}' | chat_id={chat_id}")

        start_worker_flow(chat_id)

    except Exception as e:

        logger.error(f"[START ERROR] {e}")

        bot.send_message(
            chat_id,
            f"{Icons.ERROR} Error iniciando registro"
        )


# ==================== SELECTOR SERVICIOS ====================

def get_service_selector_inline(selected):

    markup = types.InlineKeyboardMarkup(row_width=2)

    buttons = []

    for svc_id, svc in SERVICES.items():

        name = svc["name"]

        text = f"✅ {name}" if svc_id in selected else name

        buttons.append(
            types.InlineKeyboardButton(
                text=text,
                callback_data=f"svc_toggle:{svc_id}"
            )
        )

    buttons.append(
        types.InlineKeyboardButton(
            "Confirmar ✅",
            callback_data="svc_confirm"
        )
    )

    markup.add(*buttons)

    return markup


# ==================== FLUJO REGISTRO ====================

def start_worker_flow(chat_id):

    worker = db_execute(
        "SELECT * FROM workers WHERE chat_id=?",
        (str(chat_id),),
        fetch_one=True
    )

    if worker:

        bot.send_message(chat_id, f"{Icons.INFO} Ya tenés perfil.")

        return

    set_state(chat_id, "WORKER_SELECTING_SERVICES", {"selected_services": []})

    text = (
        f"{Icons.BRIEFCASE} <b>Registro Profesional</b>\n\n"
        "Paso 1/5\n"
        "Seleccioná servicios"
    )

    bot.send_message(
        chat_id,
        text,
        parse_mode="HTML",
        reply_markup=get_service_selector_inline([])
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("svc_toggle:"))
def toggle_service(call):

    chat_id = call.message.chat.id

    service_id = call.data.split(":")[1]

    selected = get_data(chat_id, "selected_services", [])

    if service_id in selected:

        selected.remove(service_id)

    else:

        selected.append(service_id)

    update_data(chat_id, selected_services=selected)

    bot.edit_message_reply_markup(
        chat_id,
        call.message.message_id,
        reply_markup=get_service_selector_inline(selected)
    )

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data == "svc_confirm")
def confirm_services(call):

    chat_id = call.message.chat.id

    selected = get_data(chat_id, "selected_services", [])

    if not selected:

        bot.answer_callback_query(
            call.id,
            "Seleccioná al menos uno",
            show_alert=True
        )

        return

    bot.delete_message(chat_id, call.message.message_id)

    set_state(
        chat_id,
        "WORKER_ENTERING_NAME",
        {"selected_services": selected}
    )

    bot.send_message(chat_id, "Tu nombre?")


# ==================== NOMBRE ====================

@bot.message_handler(func=lambda m: get_session(m.chat.id)["state"] == "WORKER_ENTERING_NAME")
def save_name(message):

    chat_id = message.chat.id

    update_data(chat_id, worker_name=message.text)

    set_state(chat_id, "WORKER_ENTERING_PHONE")

    bot.send_message(chat_id, "Tu teléfono?")


# ==================== TELEFONO ====================

@bot.message_handler(func=lambda m: get_session(m.chat.id)["state"] == "WORKER_ENTERING_PHONE")
def save_phone(message):

    chat_id = message.chat.id

    phone = re.sub(r"\D", "", message.text)

    update_data(chat_id, worker_phone=phone)

    set_state(chat_id, "WORKER_ENTERING_DNI")

    bot.send_message(chat_id, "Tu DNI?")


# ==================== DNI ====================

@bot.message_handler(func=lambda m: get_session(m.chat.id)["state"] == "WORKER_ENTERING_DNI")
def save_dni(message):

    chat_id = message.chat.id

    dni = re.sub(r"\D", "", message.text)

    save_worker_data(chat_id, dni)

    set_state(chat_id, "WORKER_SHARING_LOCATION")

    ask_location(chat_id)


# ==================== UBICACION ====================

def ask_location(chat_id):

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)

    markup.add(
        types.KeyboardButton(
            "📍 Enviar ubicación",
            request_location=True
        )
    )

    bot.send_message(
        chat_id,
        "Compartí tu ubicación",
        reply_markup=markup
    )


@bot.message_handler(content_types=["location"])
def save_location(message):

    chat_id = message.chat.id

    lat = message.location.latitude
    lon = message.location.longitude

    db_execute(
        "UPDATE workers SET lat=?,lon=?,is_active=1 WHERE chat_id=?",
        (lat, lon, str(chat_id))
    )

    bot.send_message(chat_id, "🎉 Registro completado")

    clear_state(chat_id)


# ==================== GUARDAR WORKER ====================

def save_worker_data(chat_id, dni):

    name = get_data(chat_id, "worker_name")
    phone = get_data(chat_id, "worker_phone")
    services = get_data(chat_id, "selected_services", [])

    db_execute(
        """
        INSERT OR REPLACE INTO workers
        (chat_id,name,is_active)
        VALUES (?,?,0)
        """,
        (str(chat_id), name)
    )

    db_execute(
        "DELETE FROM worker_services WHERE chat_id=?",
        (str(chat_id),)
    )

    for svc in services:

        db_execute(
            """
            INSERT INTO worker_services
            (chat_id,service_id)
            VALUES (?,?)
            """,
            (str(chat_id), svc)
    )
