"""
Client flow - Solicitar servicios
Usa ÚNICAMENTE models.user_state (NO UserSession)
"""
import asyncio
import logging
from telebot import types, apihelper

from config import bot, logger, notify_client
from models.user_state import (
    set_state, update_data, get_data, get_session, clear_state, UserState
)
from models.services_data import SERVICES
from utils.icons import Icons
from utils.keyboards import (
    get_time_selector,
    get_location_keyboard,
    get_confirmation_keyboard
)
from handlers.common import send_safe, edit_safe, delete_safe, remove_keyboard
from handlers.worker import jobs as worker_jobs
from requests_db import (
    create_request,
    assign_worker_to_request,
    get_request,
    cancel_request
)

logger = logging.getLogger(__name__)


# ==================== FLUJO INICIAL ====================

def start_client_flow(chat_id):
    """Inicia el flujo de solicitud de servicio"""
    chat_id = str(chat_id)
    clear_state(chat_id)
    set_state(chat_id, UserState.CLIENT_SELECTING_SERVICE.value)

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
    logger.info(f"[CLIENT FLOW STARTED] chat_id={chat_id}")


# ==================== SERVICIO ====================

@bot.callback_query_handler(func=lambda c: c.data.startswith("client_svc:"))
def handle_client_service_selection(call):
    chat_id = str(call.message.chat.id)
    service_id = call.data.split(":")[1]

    update_data(chat_id, service_id=service_id, service_name=SERVICES[service_id]["name"])
    set_state(chat_id, UserState.CLIENT_SELECTING_TIME.value)
    
    bot.answer_callback_query(call.id)

    text = (
        f"{Icons.CLOCK} <b>¿Para qué hora lo necesitás?</b>\n\n"
        f"Servicio: {get_service_display(service_id)}"
    )

    edit_safe(bot, chat_id, call.message.message_id, text, get_time_selector())


def get_service_display(service_id: str, with_price: bool = False) -> str:
    svc = SERVICES.get(service_id, {})
    text = f"{svc.get('icon','🔹')} <b>{svc.get('name', service_id)}</b>"
    return text


# ==================== TIEMPO ====================

@bot.callback_query_handler(func=lambda c: c.data.startswith("time_quick:"))
def handle_quick_time(call):
    chat_id = str(call.message.chat.id)
    parts = call.data.split(":")
    time_str = f"{parts[1]}:{parts[2]}"

    update_data(chat_id, selected_time=time_str, time_period="PM")
    bot.answer_callback_query(call.id)
    proceed_to_location(chat_id, call.message.message_id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("time_h:"))
def handle_time_hour(call):
    """Handler para selección de hora (paso 1)"""
    chat_id = str(call.message.chat.id)
    hour = call.data.split(":")[1]
    
    update_data(chat_id, temp_hour=hour)
    bot.answer_callback_query(call.id)
    
    # Mostrar selección de minutos
    markup = types.InlineKeyboardMarkup(row_width=4)
    for minute in ["00", "15", "30", "45"]:
        markup.add(types.InlineKeyboardButton(
            f"{hour}:{minute}",
            callback_data=f"time_m:{hour}:{minute}"
        ))
    
    edit_safe(bot, chat_id, call.message.message_id, 
              f"{Icons.CLOCK} Seleccioná los minutos:", markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("time_m:"))
def handle_time_minute(call):
    """Handler para selección de minutos (paso 2)"""
    chat_id = str(call.message.chat.id)
    parts = call.data.split(":")
    hour = parts[1]
    minute = parts[2]
    
    time_str = f"{hour}:{minute}"
    update_data(chat_id, selected_time=time_str, time_period="PM")
    bot.answer_callback_query(call.id, f"Hora seleccionada: {time_str} PM")
    
    proceed_to_location(chat_id, call.message.message_id)


# ==================== UBICACIÓN ====================

def proceed_to_location(chat_id: str, message_id: int):
    """Pasa al paso de ubicación"""
    chat_id = str(chat_id)
    service_id = get_data(chat_id, "service_id")
    time_str = get_data(chat_id, "selected_time")

    if not service_id:
        send_safe(bot, chat_id, f"{Icons.ERROR} Error: sesión expirada. Usá /start.")
        return

    set_state(chat_id, UserState.CLIENT_SHARING_LOCATION.value)
    
    text = f"""
{Icons.LOCATION} <b>Último paso: Ubicación</b>

Servicio: {get_service_display(service_id)}
Hora: {time_str} PM

Enviá tu ubicación.
"""

    delete_safe(bot, chat_id, message_id)
    send_safe(bot, chat_id, text, get_location_keyboard())


def _is_client_sharing_location(message):
    """Check para el handler de ubicación"""
    chat_id = str(message.chat.id)
    return get_data(chat_id, "state") == UserState.CLIENT_SHARING_LOCATION.value


@bot.message_handler(content_types=['location'], func=_is_client_sharing_location)
def handle_client_location(message):
    """Procesa la ubicación compartida"""
    chat_id = str(message.chat.id)
    lat = message.location.latitude
    lon = message.location.longitude

    service_id = get_data(chat_id, "service_id")
    time_str = get_data(chat_id, "selected_time")

    update_data(chat_id, lat=lat, lon=lon)
    remove_keyboard(bot, chat_id, "Ubicación recibida")
    set_state(chat_id, UserState.CLIENT_CONFIRMING.value)

    text = f"""
{Icons.CALENDAR} <b>Confirmá tu solicitud</b>

Servicio: {get_service_display(service_id)}
Hora: {time_str} PM
Ubicación: {lat:.4f}, {lon:.4f}
"""
    send_safe(bot, chat_id, text, get_confirmation_keyboard())


# ==================== CONFIRMACIÓN ====================

@bot.callback_query_handler(func=lambda c: c.data == "confirm_yes")
def handle_client_confirmation(call):
    """
    Handler ÚNICO para confirmación.
    Reemplaza al de client/callbacks.py
    """
    chat_id = str(call.message.chat.id)
    
    # Recuperar datos
    service_id = get_data(chat_id, "service_id")
    service_name = get_data(chat_id, "service_name")
    time_str = get_data(chat_id, "selected_time")
    lat = get_data(chat_id, "lat")
    lon = get_data(chat_id, "lon")

    if not all([service_id, time_str, lat, lon]):
        logger.error(f"[CONFIRM] Datos incompletos: {get_session(chat_id)}")
        bot.answer_callback_query(call.id, "❌ Error: Datos incompletos", show_alert=True)
        return

    bot.answer_callback_query(call.id, "🔍 Buscando profesionales...")

    # Crear solicitud en BD
    request_id = create_request(
        client_id=int(chat_id),
        service_id=service_id,
        service_name=service_name,
        request_time=time_str,
        time_period="PM",
        lat=lat,
        lon=lon,
        address="Ubicación del cliente"
    )

    if not request_id:
        bot.answer_callback_query(call.id, "❌ Error al crear solicitud", show_alert=True)
        return

    update_data(chat_id, request_id=request_id)
    set_state(chat_id, UserState.CLIENT_WAITING_ACCEPTANCE.value)

    # Buscar trabajadores
    hora = f"{time_str} PM"
    
    try:
        workers, status, extra = worker_jobs.find_available_workers(service_id, lat, lon, hora)
    except Exception as e:
        logger.error(f"[CONFIRM] Error buscando workers: {e}")
        workers, status = [], "error"

    if not workers:
        send_safe(bot, chat_id, f"{Icons.WARNING} No hay profesionales disponibles en este momento.")
        # Permitir reintentar
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔄 Reintentar", callback_data=f"retry_search:{request_id}"))
        markup.add(types.InlineKeyboardButton("◀️ Volver al inicio", callback_data="back_start"))
        edit_safe(bot, chat_id, call.message.message_id, "No hay profesionales disponibles.", markup)
        return

    # Asignar primer trabajador disponible
    worker_id = workers[0][0]
    result = assign_worker_to_request(request_id, worker_id)

    if not result:
        send_safe(bot, chat_id, f"{Icons.ERROR} El profesional ya no está disponible.")
        return

    # Notificar al cliente
    price = worker_jobs.SERVICES_PRICES.get(service_id, {}).get("price", 0)
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Aceptar", callback_data=f"client_accept:{request_id}"),
        types.InlineKeyboardButton("❌ Rechazar", callback_data=f"client_reject:{request_id}")
    )

    send_safe(bot, chat_id, f"""
{Icons.SUCCESS} <b>Profesional encontrado</b>

Servicio: {service_name}
Precio: ${price}
Hora: {hora}

¿Aceptás este profesional?
""", markup)

    # Notificar al trabajador
    from handlers.worker.main import show_worker_menu
    show_worker_menu(worker_id, {
        "request_id": request_id,
        "service_id": service_id,
        "hora": hora,
        "client_id": chat_id,
        "lat": lat,
        "lon": lon,
        "price": price
    })

    edit_safe(bot, chat_id, call.message.message_id, f"{Icons.SEARCH} Profesional encontrado...")


@bot.callback_query_handler(func=lambda c: c.data == "confirm_no")
def handle_client_reject_confirmation(call):
    """Usuario rechazó la confirmación, volver a empezar"""
    chat_id = str(call.message.chat.id)
    bot.answer_callback_query(call.id, "Cancelado")
    start_client_flow(chat_id)


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

    # Notificar al trabajador
    asyncio.create_task(
        notify_client(worker_id, f"✅ Cliente aceptó el servicio #{request_id}")
    )

    edit_safe(bot, chat_id, call.message.message_id, 
              f"{Icons.SUCCESS} <b>Solicitud confirmada</b>\n\nEl profesional ha sido notificado.")
    
    set_state(chat_id, UserState.JOB_IN_PROGRESS.value)


@bot.callback_query_handler(func=lambda c: c.data.startswith("client_reject:"))
def handle_client_reject_worker(call):
    chat_id = str(call.message.chat.id)
    request_id = int(call.data.split(":")[1])

    cancel_request(request_id, reason="Cliente rechazó")
    
    bot.answer_callback_query(call.id, "Solicitud cancelada")
    edit_safe(bot, chat_id, call.message.message_id, 
              f"{Icons.ERROR} Solicitud cancelada.\n\nUsá /start para nueva solicitud.")
    
    clear_state(chat_id)
