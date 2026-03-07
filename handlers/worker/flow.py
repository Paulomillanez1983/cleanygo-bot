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
            logger.error(f"[SESSION] JSON corrupto para {chat_id} - reiniciando sesión")
            db_execute(
                "UPDATE sessions SET state='IDLE', data='{}', last_activity=? WHERE chat_id=?",
                (int(time.time()), str(chat_id)),
                commit=True
            )
            return {"state": "IDLE", "data": {}}
        return {"state": state, "data": data}

    # Si no hay sesión, crearla
    db_execute(
        "INSERT INTO sessions (chat_id, state, data, last_activity) VALUES (?, ?, ?, ?)",
        (str(chat_id), "IDLE", "{}", int(time.time())),
        commit=True
    )
    return {"state": "IDLE", "data": {}}


def set_state(chat_id: str, state: str, data: dict = None):
    session = get_session(chat_id)
    new_data = session["data"]
    if data is not None:
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
    db_execute(
        "DELETE FROM sessions WHERE chat_id = ?",
        (str(chat_id),),
        commit=True
    )


# ==================== FLUJO WORKER ====================
@bot.message_handler(func=lambda m: m.text and "trabajar" in m.text.lower())
def handle_worker_start(message):
    chat_id = message.chat.id
    try:
        logger.info(f"[START] Activado por '{message.text}' | chat_id: {chat_id}")
        start_worker_flow(chat_id)
    except Exception as e:
        logger.error(f"[START ERROR] chat_id={chat_id} -> {e}")
        bot.send_message(
            chat_id,
            f"{Icons.ERROR} Ocurrió un error iniciando tu registro. Intentá de nuevo."
        )


# ==================== SELECCIÓN DE SERVICIOS ====================
def get_service_selector_inline(selected_services):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []

    for svc_id, svc in SERVICES.items():
        name = svc['name']
        text = f"✅ {name}" if svc_id in selected_services else name
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
                bot.send_message(chat_id, f"{Icons.INFO} Perfil activo.")
            return

        set_state(chat_id, "WORKER_SELECTING_SERVICES", {"selected_services": []})

        text = (
            f"{Icons.BRIEFCASE} <b>Registro de Profesional</b>\n\n"
            f"Vamos a configurar tu perfil paso a paso.\n\n"
            f"<b>Paso 1/5:</b> Seleccioná los servicios que ofrecés\n"
            f"{Icons.INFO} Podés seleccionar varios."
        )

        bot.send_message(
            chat_id,
            text,
            reply_markup=get_service_selector_inline([]),
            parse_mode="HTML"
        )
    except Exception:
        logger.error(traceback.format_exc())
        bot.send_message(chat_id, f"{Icons.ERROR} Error iniciando flujo.")


@bot.callback_query_handler(func=lambda c: c.data.startswith("svc_toggle:"))
def handle_service_toggle(call):
    chat_id = call.message.chat.id
    service_id = call.data.split(":")[1]

    try:
        selected = get_data(chat_id, "selected_services", [])
        if service_id in selected:
            selected.remove(service_id)
            bot.answer_callback_query(call.id, "Servicio removido ❌")
        else:
            selected.append(service_id)
            bot.answer_callback_query(call.id, "Servicio agregado ✅")
        update_data(chat_id, selected_services=selected)
        bot.edit_message_reply_markup(
            chat_id,
            call.message.message_id,
            reply_markup=get_service_selector_inline(selected)
        )
    except Exception:
        logger.error(traceback.format_exc())
        bot.answer_callback_query(call.id, "Error ❌")


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

    set_state(chat_id, "WORKER_ENTERING_PRICE", {
        "selected_services": selected,
        "services_to_price": selected[:],
        "current_service_idx": 0,
        "prices": {}
    })

    ask_next_price(chat_id)


# ==================== PRECIOS ====================
def ask_next_price(chat_id):
    services = get_data(chat_id, "services_to_price", [])
    idx = get_data(chat_id, "current_service_idx", 0)
    prices = get_data(chat_id, "prices", {})

    if idx >= len(services):
        set_state(chat_id, "WORKER_ENTERING_NAME")
        ask_worker_name(chat_id)
        return

    service_id = services[idx]
    service_name = SERVICES.get(service_id, {}).get("name", service_id)

    text = f"{Icons.MONEY} <b>Precio para {service_name}</b>\nIngresá tarifa por hora."

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("⏭️ Saltar")
    markup.add("❌ Cancelar")

    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")


@bot.message_handler(func=lambda m: get_session(m.chat.id)["state"] == "WORKER_ENTERING_PRICE")
def handle_price_input(message):
    chat_id = message.chat.id
    text = message.text.strip()

    services = get_data(chat_id, "services_to_price", [])
    idx = get_data(chat_id, "current_service_idx", 0)
    prices = get_data(chat_id, "prices", {})

    if text == "❌ Cancelar":
        cancel_flow(chat_id)
        return

    service_id = services[idx]

    if text == "⏭️ Saltar":
        prices[service_id] = None
        update_data(chat_id, prices=prices, current_service_idx=idx+1)
        ask_next_price(chat_id)
        return

    if not text.isdigit():
        bot.send_message(chat_id, "Ingresá solo números")
        return

    price = int(text)
    prices[service_id] = price
    update_data(chat_id, prices=prices, current_service_idx=idx+1)
    bot.send_message(chat_id, f"Precio guardado ${price}")
    ask_next_price(chat_id)


# ==================== NOMBRE ====================
def ask_worker_name(chat_id):
    text = f"{Icons.USER} <b>Paso 2/5: Tu nombre</b>"
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

    update_data(chat_id, worker_name=name)
    set_state(chat_id, "WORKER_ENTERING_PHONE")
    ask_worker_phone(chat_id)


# ==================== TELÉFONO ====================
def ask_worker_phone(chat_id):
    text = f"{Icons.PHONE} <b>Paso 3/5: Teléfono</b>"
    bot.send_message(chat_id, text, parse_mode="HTML")


@bot.message_handler(func=lambda m: get_session(m.chat.id)["state"] == "WORKER_ENTERING_PHONE")
def handle_phone_input(message):
    chat_id = message.chat.id
    phone = re.sub(r"\D", "", message.text)
    update_data(chat_id, worker_phone=phone)
    set_state(chat_id, "WORKER_ENTERING_DNI")
    ask_worker_dni(chat_id)


# ==================== DNI ====================
def ask_worker_dni(chat_id):
    text = f"{Icons.USER} <b>Paso 4/5: DNI</b>"
    bot.send_message(chat_id, text, parse_mode="HTML")


@bot.message_handler(func=lambda m: get_session(m.chat.id)["state"] == "WORKER_ENTERING_DNI")
def handle_dni_input(message):
    chat_id = message.chat.id
    dni = re.sub(r"\D", "", message.text)
    save_worker_data(chat_id, dni)
    set_state(chat_id, "WORKER_SHARING_LOCATION")
    ask_worker_location(chat_id)


# ==================== UBICACIÓN ====================
def ask_worker_location(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("📍 Enviar ubicación", request_location=True))
    bot.send_message(chat_id, "Compartí tu ubicación", reply_markup=markup)


@bot.message_handler(content_types=['location'])
def handle_location(message):
    chat_id = message.chat.id
    lat = message.location.latitude
    lon = message.location.longitude

    db_execute(
        "UPDATE workers SET lat=?, lon=?, disponible=1 WHERE chat_id=?",
        (lat, lon, str(chat_id)),
        commit=True
    )

    bot.send_message(chat_id, f"{Icons.PARTY} Registro completado")
    clear_state(chat_id)


# ==================== CANCELAR ====================
def cancel_flow(chat_id):
    clear_state(chat_id)
    bot.send_message(chat_id, "Registro cancelado")


# ==================== GUARDAR WORKER ====================
def save_worker_data(chat_id, dni):
    name = get_data(chat_id, "worker_name")
    phone = get_data(chat_id, "worker_phone")
    prices = get_data(chat_id, "prices", {})
    selected_services = get_data(chat_id, "selected_services", [])

    db_execute(
        """
        INSERT OR REPLACE INTO workers
        (chat_id,nombre,telefono,dni_file_id,disponible)
        VALUES (?,?,?,?,0)
        """,
        (str(chat_id), name, phone, dni),
        commit=True
    )

    db_execute(
        "DELETE FROM worker_services WHERE chat_id=?",
        (str(chat_id),),
        commit=True
    )

    for service_id in selected_services:
        precio = float(prices.get(service_id) or 0)
        db_execute(
            """
            INSERT OR REPLACE INTO worker_services
            (chat_id,service_id,precio)
            VALUES (?,?,?)
            """,
            (str(chat_id), service_id, precio),
            commit=True
    )
