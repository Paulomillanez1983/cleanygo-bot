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
    """Muestra info del servicio"""
    svc = SERVICES.get(service_id, {})
    return f"{svc.get('icon','🔹')} <b>{svc.get('name', service_id)}</b>"


# ==================== INICIO FLUJO ====================

def start_client_flow(chat_id):
    """Inicia el flujo de solicitud de servicio"""
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

        # soporta time_quick:18:00 o time_quick:18
        if len(parts) == 3:
            hour = parts[1]
            minute = parts[2]
        elif len(parts) == 2:
            hour = parts[1]
            minute = "00"
        else:
            raise ValueError("Formato inválido")

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

    logger.info(f"[CLIENT DATA] {get_data(chat_id)}")

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


# ==================== HANDLER UBICACIÓN ====================

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
