"""
Client flow - Solo flujo de mensajes, NO callbacks
"""
import logging
from telebot import types

from config import logger, get_bot, set_state, update_data, get_data, clear_state, get_session
from models.states import UserState
from models.services_data import SERVICES
from utils.icons import Icons
from utils.keyboards import (
    get_time_selector,
    get_location_keyboard,
    get_confirmation_keyboard
)
from handlers.common import send_safe, edit_safe, delete_safe, remove_keyboard

bot = get_bot()
logger = logging.getLogger(__name__)


def get_service_display(service_id: str) -> str:
    svc = SERVICES.get(service_id, {})
    return f"{svc.get('icon','🔹')} <b>{svc.get('name', service_id)}</b>"


# ==================== INICIO ====================

def start_client_flow(chat_id):

    clear_state(chat_id)

    set_state(chat_id, UserState.CLIENT_SELECTING_SERVICE.value, {
        "flow": "client"
    })

    text = f"{Icons.SEARCH} <b>¿Qué servicio necesitás?</b>\n\nSeleccioná una opción:"

    markup = types.InlineKeyboardMarkup(row_width=1)

    for svc_id, svc in SERVICES.items():
        markup.add(
            types.InlineKeyboardButton(
                f"{svc['icon']} {svc['name']}",
                callback_data=f"client_svc:{svc_id}"
            )
        )

    send_safe(chat_id, text, markup)

    logger.info(f"[CLIENT FLOW] Iniciado | chat_id={chat_id}")


# ==================== SERVICIO ====================

@bot.callback_query_handler(func=lambda c: c.data.startswith("client_svc:"))
def handle_client_service_selection(call):

    chat_id = call.message.chat.id
    service_id = call.data.split(":")[1]

    update_data(
        chat_id,
        service_id=service_id,
        service_name=SERVICES[service_id]["name"]
    )

    set_state(chat_id, UserState.CLIENT_SELECTING_TIME.value)

    bot.answer_callback_query(call.id)

    text = (
        f"{Icons.CLOCK} <b>¿Para qué hora lo necesitás?</b>\n\n"
        f"Servicio: {get_service_display(service_id)}"
    )

    edit_safe(chat_id, call.message.message_id, text, get_time_selector())


# ==================== TIEMPO ====================

@bot.callback_query_handler(func=lambda c: c.data.startswith("time_quick:"))
def handle_quick_time(call):

    chat_id = call.message.chat.id

    try:

        parts = call.data.split(":")

        if len(parts) == 3:
            hour = parts[1]
            minute = parts[2]
        else:
            hour = parts[1]
            minute = "00"

        time_str = f"{hour}:{minute}"

        update_data(chat_id, selected_time=time_str, time_period="PM")

        bot.answer_callback_query(call.id, f"Hora: {time_str} PM")

        proceed_to_location(chat_id, call.message.message_id)

    except Exception as e:

        logger.error(f"[TIME QUICK ERROR] {e}")

        bot.answer_callback_query(call.id, "❌ Error seleccionando hora", show_alert=True)


@bot.callback_query_handler(func=lambda c: c.data.startswith("time_h:"))
def handle_time_hour(call):

    chat_id = call.message.chat.id

    try:

        hour = call.data.split(":")[1]

        update_data(chat_id, temp_hour=hour)

        bot.answer_callback_query(call.id)

        markup = types.InlineKeyboardMarkup(row_width=4)

        for minute in ["00", "15", "30", "45"]:
            markup.add(
                types.InlineKeyboardButton(
                    f"{hour}:{minute}",
                    callback_data=f"time_m:{hour}:{minute}"
                )
            )

        edit_safe(
            chat_id,
            call.message.message_id,
            f"{Icons.CLOCK} Seleccioná los minutos:",
            markup
        )

    except Exception as e:

        logger.error(f"[TIME HOUR ERROR] {e}")

        bot.answer_callback_query(call.id, "❌ Error seleccionando hora", show_alert=True)


@bot.callback_query_handler(func=lambda c: c.data.startswith("time_m:"))
def handle_time_minute(call):

    chat_id = call.message.chat.id

    try:

        parts = call.data.split(":")

        hour = parts[1]
        minute = parts[2]

        time_str = f"{hour}:{minute}"

        update_data(chat_id, selected_time=time_str, time_period="PM")

        bot.answer_callback_query(call.id, f"Hora: {time_str} PM")

        proceed_to_location(chat_id, call.message.message_id)

    except Exception as e:

        logger.error(f"[TIME MINUTE ERROR] {e}")

        bot.answer_callback_query(call.id, "❌ Error seleccionando minutos", show_alert=True)


# ==================== UBICACIÓN ====================

def proceed_to_location(chat_id: int, message_id: int):

    service_id = get_data(chat_id, "service_id")
    time_str = get_data(chat_id, "selected_time")

    if not service_id:
        send_safe(chat_id, f"{Icons.ERROR} Error: sesión expirada. Usá /start.")
        return

    set_state(chat_id, UserState.CLIENT_SHARING_LOCATION.value)

    text = f"""
{Icons.LOCATION} <b>Último paso: Ubicación</b>

Servicio: {get_service_display(service_id)}
Hora: {time_str} PM

Enviá tu ubicación.
"""

    delete_safe(chat_id, message_id)

    send_safe(
        chat_id,
        text,
        get_location_keyboard()
    )


# ==================== RECIBIR UBICACIÓN ====================

def _is_client_sharing_location(message):

    session = get_session(message.chat.id)

    return session.get("state") == UserState.CLIENT_SHARING_LOCATION.value


@bot.message_handler(content_types=['location'], func=_is_client_sharing_location)
def handle_client_location(message):

    chat_id = message.chat.id

    lat = message.location.latitude
    lon = message.location.longitude

    service_id = get_data(chat_id, "service_id")
    time_str = get_data(chat_id, "selected_time")

    update_data(chat_id, lat=lat, lon=lon)

    remove_keyboard(chat_id, "✅ Ubicación recibida")

    set_state(chat_id, UserState.CLIENT_CONFIRMING.value)

    text = f"""
{Icons.CALENDAR} <b>Confirmá tu solicitud</b>

Servicio: {get_service_display(service_id)}
Hora: {time_str} PM
Ubicación: {lat:.4f}, {lon:.4f}

¿Todo correcto?
"""

    send_safe(
        chat_id,
        text,
        get_confirmation_keyboard()
    )


# ==================== CLIENTE ESPERANDO ====================

def _is_client_waiting_acceptance(message):

    session = get_session(message.chat.id)

    return session.get("state") == UserState.CLIENT_WAITING_ACCEPTANCE.value


@bot.message_handler(func=_is_client_waiting_acceptance)
def handle_client_waiting_message(message):

    chat_id = message.chat.id
    request_id = get_data(chat_id, "request_id")

    if not request_id:
        send_safe(chat_id, f"{Icons.ERROR} Error de sesión. Usá /start.")
        return

    text = f"""
{Icons.CLOCK} <b>Estás esperando que un profesional acepte tu solicitud...</b>

Te avisaremos cuando alguien acepte.

¿Querés cancelar la solicitud?
"""

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            f"{Icons.ERROR} Cancelar solicitud",
            callback_data=f"client_cancel_request:{request_id}"
        )
    )

    send_safe(chat_id, text, markup)


# ==================== CONFIRMAR SOLICITUD ====================

@bot.callback_query_handler(func=lambda c: c.data == "confirm_yes")
def handle_client_confirm(call):

    chat_id = call.message.chat.id

    service_id = get_data(chat_id, "service_id")
    service_name = get_data(chat_id, "service_name")
    time_str = get_data(chat_id, "selected_time")
    lat = get_data(chat_id, "lat")
    lon = get_data(chat_id, "lon")

    if not all([service_id, time_str, lat, lon]):
        bot.answer_callback_query(call.id, "❌ Error: datos incompletos", show_alert=True)
        return

    from services.request_service import create_request

    try:

        request_id = create_request(
            client_id=chat_id,
            service_id=service_id,
            hora=time_str,
            lat=lat,
            lon=lon
        )

        if not request_id:
            bot.answer_callback_query(call.id, "❌ Error creando solicitud", show_alert=True)
            return

        logger.info(f"[REQUEST] Creada solicitud {request_id}")

    except Exception as e:

        logger.error(f"[REQUEST CREATE ERROR] {e}")

        bot.answer_callback_query(call.id, "❌ Error creando solicitud", show_alert=True)

        return

    set_state(chat_id, UserState.CLIENT_WAITING_ACCEPTANCE.value, {
        "request_id": request_id
    })

    bot.answer_callback_query(call.id, "✅ Solicitud enviada")

    text = f"""
{Icons.SEARCH} <b>¡Solicitud enviada!</b>

Estamos buscando profesionales disponibles para las {time_str} PM.

⏳ Esperando aceptación...
"""

    markup = types.InlineKeyboardMarkup()

    markup.add(
        types.InlineKeyboardButton(
            f"{Icons.ERROR} Cancelar solicitud",
            callback_data=f"client_cancel_request:{request_id}"
        )
    )

    edit_safe(chat_id, call.message.message_id, text, markup)

    from services.matching_service import notify_nearby_workers

    notify_nearby_workers(request_id, lat, lon, service_id)


# ==================== CANCELAR CONFIRMACIÓN ====================

@bot.callback_query_handler(func=lambda c: c.data == "confirm_no")
def handle_client_cancel_confirmation(call):

    chat_id = call.message.chat.id

    bot.answer_callback_query(call.id, "❌ Cancelado")

    edit_safe(
        chat_id,
        call.message.message_id,
        f"{Icons.ERROR} Solicitud cancelada. Usá /start para comenzar de nuevo."
    )

    clear_state(chat_id)


# ==================== CANCELAR SOLICITUD ====================

@bot.callback_query_handler(func=lambda c: c.data.startswith("client_cancel_request:"))
def handle_client_cancel_request(call):

    chat_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])

    from services.request_service import update_request_status, get_request

    request = get_request(request_id)

    if not request:
        bot.answer_callback_query(call.id, "❌ Solicitud no encontrada")
        return

    update_request_status(request_id, "cancelled_by_client")

    bot.answer_callback_query(call.id, "✅ Solicitud cancelada")

    edit_safe(
        chat_id,
        call.message.message_id,
        f"{Icons.ERROR} Solicitud cancelada."
    )

    clear_state(chat_id)
