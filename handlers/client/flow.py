# handlers/client/flow.py
"""
Flujo completo para clientes - Solicitud de servicios (UX optimizada)
con asignación automática a trabajadores y menú funcional.
"""

from config import bot
from models.user_state import set_state, update_data, get_data, UserState, get_session
from models.services_data import SERVICES
from utils.icons import Icons
from utils.keyboards import (
    get_service_selector, get_time_selector, get_custom_time_selector,
    get_location_keyboard, get_confirmation_keyboard, get_role_keyboard
)
from handlers.common import send_safe, edit_safe, delete_safe, remove_keyboard
from telebot import types
import logging

# Importar precios y funciones de jobs
from handlers.worker import jobs as worker_jobs
from handlers.worker.main import show_worker_menu
from services import request_service

logger = logging.getLogger(__name__)

flow = True

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
        logger.info(f"[SAVE] chat_id={chat_id}, updated keys: {list(data_updates.keys())}")
    set_state(chat_id, state)
    logger.info(f"[SAVE] chat_id={chat_id}, state={state.value}")

def get_flow_data(chat_id: str, key: str, default=None):
    chat_id = str(chat_id)
    try:
        result = get_data(chat_id, key)
        return result if result is not None else default
    except Exception as e:
        logger.error(f"[GET] ERROR chat_id={chat_id}, key={key}: {e}")
        return default

def get_service_display(service_id: str, with_price: bool = False) -> str:
    svc = SERVICES.get(service_id, {})
    text = f"{svc.get('icon', '🔹')} <b>{svc.get('name', service_id)}</b>"
    if with_price:
        price = worker_jobs.SERVICES_PRICES.get(service_id, {}).get("price", 0)
        text += f"\n   <code>${price}</code>"
    return text

# ==================== FLUJO INICIAL ====================

@bot.message_handler(func=lambda m: m.text and ("Necesito" in m.text or "servicio" in m.text.lower()))
def handle_client_start(message):
    start_client_flow(message.chat.id)

def start_client_flow(chat_id: str):
    chat_id = str(chat_id)
    from models.user_state import clear_state
    clear_state(chat_id)
    save_state_and_data(chat_id, UserState.CLIENT_SELECTING_SERVICE, {})

    text = f"{Icons.SEARCH} <b>¿Qué servicio necesitás?</b>\n\nSeleccioná una opción:"
    markup = types.InlineKeyboardMarkup(row_width=1)
    for svc_id, svc in SERVICES.items():
        markup.add(types.InlineKeyboardButton(
            f"{svc['icon']} {svc['name']}\n<i>{svc['desc']}</i>",
            callback_data=f"client_svc:{svc_id}"
        ))
    send_safe(chat_id, text, markup)
    debug_session(chat_id, "POST_START")

@bot.callback_query_handler(func=lambda c: c.data.startswith("client_svc:"))
def handle_client_service_selection(call):
    chat_id = str(call.message.chat.id)
    service_id = call.data.split(":")[1]

    update_data(chat_id, service_id=service_id, service_name=SERVICES[service_id]["name"])
    set_state(chat_id, UserState.CLIENT_SELECTING_TIME)
    debug_session(chat_id, "POST_SERVICE")

    bot.answer_callback_query(call.id, f"Seleccionaste: {SERVICES[service_id]['name']}")
    text = f"{Icons.CLOCK} <b>¿Para qué hora lo necesitás?</b>\nServicio: {get_service_display(service_id)}\n<b>Opciones rápidas:</b>"
    edit_safe(chat_id, call.message.message_id, text, get_time_selector())

# ==================== HANDLERS DE TIEMPO ====================

@bot.callback_query_handler(func=lambda c: c.data.startswith("time_quick:"))
def handle_quick_time(call):
    chat_id = str(call.message.chat.id)
    parts = call.data.split(":")
    time_str = f"{parts[1]}:{parts[2]}"
    update_data(chat_id, selected_time=time_str, time_period="PM")
    debug_session(chat_id, "POST_TIME")
    bot.answer_callback_query(call.id, f"Hora: {time_str} PM")
    proceed_to_location(chat_id, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "time_custom")
def handle_custom_time_start(call):
    chat_id = call.message.chat.id
    edit_safe(chat_id, call.message.message_id, f"{Icons.CLOCK} <b>Seleccioná la hora:</b>", get_custom_time_selector("hour"))

@bot.callback_query_handler(func=lambda c: c.data.startswith("time_h:"))
def handle_hour_selection(call):
    chat_id = call.message.chat.id
    hour = call.data.split(":")[1]
    edit_safe(chat_id, call.message.message_id, f"{Icons.CLOCK} <b>Seleccioná los minutos:</b>\nHora: {hour}:__", get_custom_time_selector("minute", hour))

@bot.callback_query_handler(func=lambda c: c.data.startswith("time_m:"))
def handle_minute_selection(call):
    chat_id = call.message.chat.id
    hour, minute = call.data.split(":")[1], call.data.split(":")[2]
    time_str = f"{hour}:{minute}"
    edit_safe(chat_id, call.message.message_id, f"{Icons.CLOCK} <b>¿AM o PM?</b>\nHora seleccionada: {time_str}", get_custom_time_selector("ampm", time_str))

@bot.callback_query_handler(func=lambda c: c.data.startswith("time_final:"))
def handle_final_time(call):
    chat_id = str(call.message.chat.id)
    parts = call.data.split(":")
    time_str, period = f"{parts[1]}:{parts[2]}", parts[3]
    update_data(chat_id, selected_time=time_str, time_period=period)
    debug_session(chat_id, "POST_TIME_FINAL")
    bot.answer_callback_query(call.id, f"✓ {time_str} {period}")
    proceed_to_location(chat_id, call.message.message_id)

# ==================== UBICACIÓN ====================

def proceed_to_location(chat_id: str, message_id: int):
    chat_id = str(chat_id)
    service_id = get_data(chat_id, "service_id")
    time_str = get_data(chat_id, "selected_time")
    period = get_data(chat_id, "time_period")

    if not service_id:
        send_safe(chat_id, f"{Icons.ERROR} Error: sesión expirada. Usá /start de nuevo.")
        return

    set_state(chat_id, UserState.CLIENT_SHARING_LOCATION)

    summary_text = f"""
{Icons.LOCATION} <b>Último paso: Ubicación</b>

📋 <b>Resumen de tu solicitud:</b>
• Servicio: {get_service_display(service_id)}
• Hora: {time_str} {period}

{Icons.INFO} Enviá tu ubicación para encontrar profesionales cercanos:
"""
    delete_safe(chat_id, message_id)
    send_safe(chat_id, summary_text, get_location_keyboard())

def _is_client_sharing_location(message):
    chat_id = str(message.chat.id)
    session = get_session(chat_id)
    return session.get("state") == UserState.CLIENT_SHARING_LOCATION.value

@bot.message_handler(content_types=['location'], func=_is_client_sharing_location)
def handle_client_location(message):
    chat_id = str(message.chat.id)
    lat, lon = message.location.latitude, message.location.longitude
    service_id = get_data(chat_id, "service_id")
    time_str = get_data(chat_id, "selected_time")
    period = get_data(chat_id, "time_period")

    update_data(chat_id, lat=lat, lon=lon, location_shared=True)
    remove_keyboard(chat_id, "📍 Ubicación recibida")
    set_state(chat_id, UserState.CLIENT_CONFIRMING)

    service_info = worker_jobs.SERVICES_PRICES.get(service_id, {"name": service_id, "price": 0})

    confirmation_text = f"""
{Icons.CALENDAR} <b>Confirma tu solicitud</b>

Servicio: {service_info['name']}
{Icons.MONEY} <b>Precio:</b> ${service_info['price']}
{Icons.TIME} <b>Hora:</b> {time_str} {period}
{Icons.LOCATION} <b>Ubicación:</b> {lat:.5f}, {lon:.5f}
"""
    send_safe(chat_id, confirmation_text, get_confirmation_keyboard())
    logger.info(f"[LOCATION] Confirmación enviada")

# ==================== CONFIRMACIÓN FINAL ====================

@bot.callback_query_handler(func=lambda c: c.data == "confirm_yes_client")
def handle_client_confirmation(call):
    chat_id = str(call.message.chat.id)
    service_id = get_data(chat_id, "service_id")
    time_str = get_data(chat_id, "selected_time")
    period = get_data(chat_id, "time_period")
    lat = get_data(chat_id, "lat")
    lon = get_data(chat_id, "lon")
    hora_completa = f"{time_str} {period}"

    # Crear request si no existe
    session = get_session(chat_id)
    request_id = session.get("data", {}).get("request_id")
    if not request_id:
        request_id = request_service.create_request(
            client_chat_id=chat_id,
            service_id=service_id,
            hora=hora_completa,
            lat=lat,
            lon=lon,
            status='waiting_acceptance'
        )
        if not request_id:
            bot.answer_callback_query(call.id, "❌ Error al crear la solicitud, intentá de nuevo")
            return
        update_data(chat_id, request_id=request_id)

    # Cambiar estado
    set_state(chat_id, UserState.CLIENT_WAITING_ACCEPTANCE, {"request_id": request_id})
    bot.answer_callback_query(call.id, "¡Solicitud enviada! Buscando profesionales cercanos...")

    # ==================== ASIGNAR TRABAJADOR DISPONIBLE ====================
    available_workers, status, extra = worker_jobs.find_available_workers(
        service_id, lat, lon, hora_completa
    )

    if available_workers:
        assigned_worker = available_workers[0]
        worker_id = assigned_worker[0]
        # Intentar asignar de manera segura
        success = worker_jobs.assign_worker_to_request_safe(request_id, worker_id)
        if success:
            # Mostrar menú al worker
            worker_data = {
                "request_id": request_id,
                "service_id": service_id,
                "hora": hora_completa,
                "client_id": chat_id
            }
            show_worker_menu(worker_id, worker_data)
        else:
            logger.warning(f"[ASSIGN FAIL] request_id={request_id} worker={worker_id} ya fue tomada")
    else:
        logger.info(f"[NO WORKERS] status={status}, extra={extra}")

    # Mensaje de búsqueda optimizado para el cliente
    search_text = f"""
{Icons.SEARCH} <b>Buscando profesionales disponibles...</b>

Servicio: {worker_jobs.SERVICES_PRICES.get(service_id, {}).get('name', service_id)}
Hora: {hora_completa}
Ubicación recibida ✅

{Icons.TIME} Esto puede tardar unos segundos...
"""
    edit_safe(chat_id, call.message.message_id, search_text)
