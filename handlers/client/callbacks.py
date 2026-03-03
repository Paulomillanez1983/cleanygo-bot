from telebot import types
from config import bot, logger
from models.user_state import set_state, update_data, get_data, clear_state, UserState
from models.services_data import SERVICES
from utils.icons import Icons
from utils.keyboards import get_alternative_times_keyboard, get_role_keyboard
from services.worker_service import find_available_workers
from services.request_service import create_request, update_request_status, get_request
from handlers.common import send_safe, edit_safe, remove_keyboard
from handlers.client.search import generate_no_availability_message, notify_worker
from handlers.client.flow import get_service_display

@bot.callback_query_handler(func=lambda c: c.data == "confirm_yes")
def handle_confirm_request(call):
    chat_id = call.message.chat.id
    
    # Obtener datos
    service_id = get_data(chat_id, "service_id")
    time_str = get_data(chat_id, "selected_time")
    period = get_data(chat_id, "time_period")
    lat = get_data(chat_id, "lat")
    lon = get_data(chat_id, "lon")
    hora_completa = f"{time_str} {period}"
    
    # Crear solicitud
    request_id = create_request(chat_id, service_id, hora_completa, lat, lon, 'searching')
    
    if request_id is None:
        bot.answer_callback_query(call.id, "Error al crear solicitud")
        return
    
    bot.answer_callback_query(call.id, "¡Buscando profesionales!")
    
    # Mensaje de búsqueda
    search_text = f"""
{Icons.SEARCH} <b>Buscando profesionales disponibles...</b>

{Icons.PENDING} Verificando disponibilidad para {SERVICES[service_id]['name']} a las {hora_completa}

{Icons.TIME} Esto tomará unos segundos...
    """
    
    edit_safe(chat_id, call.message.message_id, search_text)
    
    # Buscar trabajadores disponibles
    result = find_available_workers(service_id, lat, lon, hora_completa)
    
    if len(result) == 3:
        workers, status, extra = result
    else:
        workers, status = result
        extra = None
    
    if status != "success" or not workers:
        # No hay disponibilidad
        no_workers_text = generate_no_availability_message(status, service_id, hora_completa, extra)
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        if status == "workers_busy":
            markup.add(types.InlineKeyboardButton(
                "⏰ Ver otros horarios disponibles", 
                callback_data=f"alt_times:{service_id}:{request_id}"
            ))
        
        markup.add(types.InlineKeyboardButton(
            "🔄 Intentar de nuevo", 
            callback_data=f"retry_search:{request_id}"
        ))
        markup.add(types.InlineKeyboardButton(
            "◀️ Volver al inicio", 
            callback_data="back_start"
        ))
        
        update_request_status(request_id, 'no_workers_found')
        edit_safe(chat_id, call.message.message_id, no_workers_text, markup)
        return
    
    # Notificar trabajadores
    notified = 0
    for worker in workers:
        try:
            notify_worker(worker, request_id, service_id, hora_completa, lat, lon)
            notified += 1
        except Exception as e:
            logger.error(f"Error notificando a {worker[0]}: {e}")
    
    # Actualizar estado
    update_request_status(request_id, 'waiting_acceptance')
    set_state(chat_id, UserState.CLIENT_WAITING_ACCEPTANCE, {"request_id": request_id})
    
    waiting_text = f"""
{Icons.SUCCESS} <b>¡Solicitud enviada!</b>

{Icons.INFO} Hemos notificado a <b>{notified}</b> profesionales cercanos disponibles a las {hora_completa}.

{Icons.PENDING} Esperando que acepten tu solicitud...

{Icons.TIME} Tiempo estimado: 2-3 minutos
    """
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        f"{Icons.ERROR} Cancelar solicitud", 
        callback_data=f"cancel_req:{request_id}"
    ))
    
    edit_safe(chat_id, call.message.message_id, waiting_text, markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("retry_search:"))
def handle_retry_search(call):
    chat_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])
    
    request = get_request(request_id)
    if not request:
        bot.answer_callback_query(call.id, "Solicitud no encontrada")
        return
    
    _, client_id, service_id, _, hora, lat, lon, status, *_ = request
    
    import time
    update_request_status(request_id, 'searching')
    
    bot.answer_callback_query(call.id, "Reintentando búsqueda...")
    
    # Actualizar sesión
    hora_parts = hora.split()
    update_data(chat_id, 
        service_id=service_id,
        selected_time=hora_parts[0],
        time_period=hora_parts[1] if len(hora_parts) > 1 else "PM",
        lat=lat, lon=lon
    )
    
    # Reejecutar
    handle_confirm_request(call)

@bot.callback_query_handler(func=lambda c: c.data.startswith("alt_times:"))
def handle_alternative_times(call):
    chat_id = call.message.chat.id
    parts = call.data.split(":")
    service_id = parts[1]
    request_id = int(parts[2])
    
    text = f"""
{Icons.CLOCK} <b>Horarios alternativos disponibles</b>

{SERVICES[service_id]['icon']} <b>{SERVICES[service_id]['name']}</b>

Seleccioná otro horario:
    """
    
    edit_safe(chat_id, call.message.message_id, text, 
              get_alternative_times_keyboard(service_id, request_id))

@bot.callback_query_handler(func=lambda c: c.data.startswith("change_time:"))
def handle_change_time(call):
    chat_id = call.message.chat.id
    parts = call.data.split(":")
    request_id = int(parts[1])
    nueva_hora = parts[2]
    
    from services.request_service import db_execute
    db_execute(
        "UPDATE requests SET hora = ? WHERE id = ?",
        (f"{nueva_hora} PM", request_id),
        commit=True
    )
    
    bot.answer_callback_query(call.id, f"Hora cambiada a {nueva_hora}")
    handle_retry_search(call)

@bot.callback_query_handler(func=lambda c: c.data == "back_start")
def handle_back_start(call):
    chat_id = call.message.chat.id
    clear_state(chat_id)
    bot.answer_callback_query(call.id, "Volviendo al inicio...")
    
    welcome_text = f"""
{Icons.WAVE} <b>¡Bienvenido a CleanyGo!</b>

Conectamos personas que necesitan servicios con profesionales confiables cerca de ti.

<b>¿Qué necesitás hacer?</b>
    """
    
    edit_safe(chat_id, call.message.message_id, welcome_text, get_role_keyboard())
    set_state(chat_id, UserState.SELECTING_ROLE)
