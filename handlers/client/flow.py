"""
Flujo completo para clientes - Solicitud de servicios (UX optimizada)
con asignación automática a trabajadores, confirmación bidireccional y menú funcional.
VERSIÓN ESTABILIZADA
"""

import asyncio
import logging
from telebot import types

from config import notify_client, bot
from models.user_state import set_state, update_data, get_data, UserState, get_session, clear_state
from models.services_data import SERVICES
from utils.icons import Icons
from utils.keyboards import (
    get_service_selector,
    get_time_selector,
    get_custom_time_selector,
    get_location_keyboard,
    get_confirmation_keyboard,
    get_role_keyboard
)
from utils.telegram_safe import send_safe, edit_safe, delete_safe
from handlers.common import remove_keyboard
from requests_db import (
    create_request,
    assign_worker_to_request,
    get_request,
    complete_request,
    cancel_request
)
from handlers.worker import jobs as worker_jobs
from handlers.worker.main import show_worker_menu

logger = logging.getLogger(__name__)

# ==================== REGISTRO HANDLERS ====================

def register_handlers(_bot):
    """
    Compatibilidad con bot.py.
    No hace nada porque los handlers ya están registrados
    mediante decoradores usando el bot global de config.
    """
    logger.info("[CLIENT FLOW] Handlers cargados correctamente")


# ==================== FUNCIONES AUXILIARES ====================

def debug_session(chat_id: str, label: str):
    try:
        session = get_session(chat_id)
        logger.info(f"[DEBUG {label}] chat_id={chat_id}, session={session}")
        return session
    except Exception as e:
        logger.error(f"[DEBUG {label}] ERROR: {e}")
        return {"state": "error", "data": {}}


def save_state_and_data(chat_id: str, state: UserState, data_updates: dict = None):
    chat_id = str(chat_id)
    if data_updates:
        for key, value in data_updates.items():
            update_data(chat_id, **{key: value})
    set_state(chat_id, state)
    logger.info(f"[STATE] chat_id={chat_id} -> {state.value}")


def get_service_display(service_id: str, with_price: bool = False) -> str:
    svc = SERVICES.get(service_id, {})
    text = f"{svc.get('icon','🔹')} <b>{svc.get('name', service_id)}</b>"
    if with_price:
        price = worker_jobs.SERVICES_PRICES.get(service_id, {}).get("price", 0)
        text += f"\n<code>${price}</code>"
    return text


# ==================== FLUJO INICIAL ====================

@bot.message_handler(func=lambda m: m.text and ("Necesito" in m.text or "servicio" in m.text.lower()))
def handle_client_start(message):
    start_client_flow(message.chat.id)


def start_client_flow(chat_id):
    chat_id = str(chat_id)
    clear_state(chat_id)
    save_state_and_data(chat_id, UserState.CLIENT_SELECTING_SERVICE)

    text = f"{Icons.SEARCH} <b>¿Qué servicio necesitás?</b>\n\nSeleccioná una opción:"
    markup = types.InlineKeyboardMarkup(row_width=1)

    for svc_id, svc in SERVICES.items():
        markup.add(
            types.InlineKeyboardButton(
                f"{svc['icon']} {svc['name']}\n{svc['desc']}",
                callback_data=f"client_svc:{svc_id}"
            )
        )

    send_safe(bot, chat_id, text, markup)
    debug_session(chat_id, "POST_START")


# ==================== SERVICIO ====================

@bot.callback_query_handler(func=lambda c: c.data.startswith("client_svc:"))
def handle_client_service_selection(call):
    chat_id = str(call.message.chat.id)
    service_id = call.data.split(":")[1]

    update_data(chat_id, service_id=service_id, service_name=SERVICES[service_id]["name"])
    set_state(chat_id, UserState.CLIENT_SELECTING_TIME)
    bot.answer_callback_query(call.id)

    text = (
        f"{Icons.CLOCK} <b>¿Para qué hora lo necesitás?</b>\n\n"
        f"Servicio: {get_service_display(service_id)}"
    )

    edit_safe(bot, chat_id, call.message.message_id, text, get_time_selector())


# ==================== TIEMPO ====================

@bot.callback_query_handler(func=lambda c: c.data.startswith("time_quick:"))
def handle_quick_time(call):
    chat_id = str(call.message.chat.id)
    parts = call.data.split(":")
    time_str = f"{parts[1]}:{parts[2]}"

    update_data(chat_id, selected_time=time_str, time_period="PM")
    bot.answer_callback_query(call.id)
    proceed_to_location(chat_id, call.message.message_id)


# ==================== UBICACIÓN ====================

def proceed_to_location(chat_id: str, message_id: int):
    chat_id = str(chat_id)
    service_id = get_data(chat_id, "service_id")
    time_str = get_data(chat_id, "selected_time")
    period = get_data(chat_id, "time_period")

    if not service_id:
        send_safe(bot, chat_id, f"{Icons.ERROR} Error: sesión expirada. Usá /start.")
        return

    set_state(chat_id, UserState.CLIENT_SHARING_LOCATION)
    text = f"""
{Icons.LOCATION} <b>Último paso: Ubicación</b>

Servicio: {get_service_display(service_id)}
Hora: {time_str} {period}

Enviá tu ubicación.
"""

    delete_safe(bot, chat_id, message_id)
    send_safe(bot, chat_id, text, get_location_keyboard())


def _is_client_sharing_location(message):
    chat_id = str(message.chat.id)
    session = get_session(chat_id)
    return session.get("state") == UserState.CLIENT_SHARING_LOCATION.value


@bot.message_handler(content_types=['location'], func=_is_client_sharing_location)
def handle_client_location(message):
    chat_id = str(message.chat.id)
    lat = message.location.latitude
    lon = message.location.longitude

    service_id = get_data(chat_id, "service_id")
    time_str = get_data(chat_id, "selected_time")
    period = get_data(chat_id, "time_period")

    update_data(chat_id, lat=lat, lon=lon)
    remove_keyboard(bot, chat_id, "Ubicación recibida")
    set_state(chat_id, UserState.CLIENT_CONFIRMING)

    service_info = worker_jobs.SERVICES_PRICES.get(service_id, {"price": 0})
    text = f"""
{Icons.CALENDAR} <b>Confirmá tu solicitud</b>

Servicio: {service_id}
Precio: ${service_info['price']}
Hora: {time_str} {period}
"""
    send_safe(bot, chat_id, text, get_confirmation_keyboard())


# ==================== CONFIRMACIÓN ====================

@bot.callback_query_handler(func=lambda c: c.data == "confirm_yes_client")
def handle_client_confirmation(call):
    chat_id = str(call.message.chat.id)
    service_id = get_data(chat_id, "service_id")
    service_name = get_data(chat_id, "service_name")
    time_str = get_data(chat_id, "selected_time")
    period = get_data(chat_id, "time_period")
    lat = get_data(chat_id, "lat")
    lon = get_data(chat_id, "lon")

    request_id = create_request(
        client_id=int(chat_id),
        service_id=service_id,
        service_name=service_name,
        request_time=time_str,
        time_period=period,
        lat=lat,
        lon=lon,
        address="Ubicación del cliente"
    )

    if not request_id:
        bot.answer_callback_query(call.id, "Error al crear solicitud")
        return

    update_data(chat_id, request_id=request_id)
    set_state(chat_id, UserState.CLIENT_WAITING_ACCEPTANCE)
    bot.answer_callback_query(call.id, "Buscando profesionales...")

    hora = f"{time_str} {period}"
    workers, status, extra = worker_jobs.find_available_workers(service_id, lat, lon, hora)

    if not workers:
        send_safe(bot, chat_id, f"{Icons.WARNING} No hay profesionales disponibles.")
        return

    worker_id = workers[0][0]
    result = assign_worker_to_request(request_id, worker_id)

    if not result:
        send_safe(bot, chat_id, f"{Icons.ERROR} El profesional ya no está disponible.")
        return

    price = worker_jobs.SERVICES_PRICES.get(service_id, {}).get("price", 0)
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Aceptar", callback_data=f"client_accept:{request_id}"),
        types.InlineKeyboardButton("Rechazar", callback_data=f"client_reject:{request_id}")
    )

    send_safe(bot, chat_id, f"""
{Icons.SUCCESS} Profesional encontrado

Servicio: {service_name}
Precio: ${price}
Hora: {hora}
""", markup)

    # Mostrar menú al trabajador
    show_worker_menu(
        worker_id,
        {
            "request_id": request_id,
            "service_id": service_id,
            "hora": hora,
            "client_id": chat_id,
            "lat": lat,
            "lon": lon,
            "price": price
        }
    )

    edit_safe(bot, chat_id, call.message.message_id, f"{Icons.SEARCH} Buscando profesionales...")


# ==================== RESPUESTA CLIENTE ====================

@bot.callback_query_handler(func=lambda c: c.data.startswith("client_accept:"))
def handle_client_accept_worker(call):
    chat_id = str(call.message.chat.id)
    request_id = int(call.data.split(":")[1])
    request_data = get_request(request_id)

    if not request_data:
        bot.answer_callback_query(call.id, "Solicitud no encontrada")
        return

    worker_id = request_data.get("worker_id")

    # ✅ Llamada async desde sync
    asyncio.create_task(
        notify_client(worker_id, f"Cliente aceptó el servicio #{request_id}")
    )

    send_safe(bot, chat_id, f"{Icons.SUCCESS} Solicitud confirmada.")


@bot.callback_query_handler(func=lambda c: c.data.startswith("client_reject:"))
def handle_client_reject_worker(call):
    chat_id = str(call.message.chat.id)
    request_id = int(call.data.split(":")[1])

    cancel_request(request_id, reason="Cliente rechazó")
    send_safe(bot, chat_id, "Solicitud cancelada")
