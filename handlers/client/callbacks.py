"""
Client callbacks - Todos los callbacks del cliente
"""
import os
import time
import traceback
from telebot import types, apihelper

# CAMBIO: usar get_bot
from config import logger, get_bot
from models.user_state import set_state, update_data, get_data, clear_state, UserState
from models.services_data import SERVICES
from utils.icons import Icons
from utils.keyboards import get_alternative_times_keyboard, get_role_keyboard
from services.worker_service import find_available_workers
from services.request_service import create_request, update_request_status, get_request, db_execute
from handlers.common import send_safe, edit_safe, remove_keyboard

# NUEVO: obtener bot
bot = get_bot()

from handlers.client.search import generate_no_availability_message, notify_worker


# =========================================================
# CONFIRMAR SOLICITUD (callback_data="confirm_yes")
# =========================================================

@bot.callback_query_handler(func=lambda c: c.data == "confirm_yes")
def handle_confirm_request(call):
    """Crea la solicitud y busca trabajadores disponibles"""
    chat_id = call.message.chat.id
    
    # Recuperar datos de la sesión
    service_id = get_data(chat_id, "service_id")
    time_str = get_data(chat_id, "selected_time")
    period = get_data(chat_id, "time_period") or "PM"
    lat = get_data(chat_id, "lat")
    lon = get_data(chat_id, "lon")

    # Validar datos requeridos
    if not all([service_id, time_str, lat, lon]):
        logger.error(f"[CONFIRM] Datos incompletos en chat_id={chat_id}")
        bot.answer_callback_query(call.id, "❌ Error: Datos incompletos. Empezá de nuevo.", show_alert=True)
        handle_back_start(call)
        return

    hora_completa = f"{time_str} {period}"

    # Crear solicitud en BD
    request_id = create_request(chat_id, service_id, hora_completa, lat, lon, 'searching')

    if request_id is None:
        logger.error(f"[CONFIRM] Error al crear solicitud para chat_id={chat_id}")
        bot.answer_callback_query(call.id, "❌ Error al crear solicitud", show_alert=True)
        return

    bot.answer_callback_query(call.id, "🔍 ¡Buscando profesionales!")

    # Mostrar mensaje de búsqueda
    search_text = f"""
{Icons.SEARCH} <b>Buscando profesionales disponibles...</b>

{Icons.PENDING} Verificando disponibilidad para {SERVICES.get(service_id, {}).get('name', 'Servicio')} a las {hora_completa}

{Icons.TIME} Esto tomará unos segundos...
    """

    edit_safe(chat_id, call.message.message_id, search_text)

    # Buscar trabajadores
    try:
        result = find_available_workers(service_id, lat, lon, hora_completa)
        
        if not result:
            workers, status, extra = [], "error", None
        elif isinstance(result, tuple) and len(result) >= 3:
            workers, status, extra = result[0], result[1], result[2]
        elif isinstance(result, tuple) and len(result) == 2:
            workers, status, extra = result[0], result[1], None
        else:
            workers, status, extra = [], "error", None
            
    except Exception as e:
        logger.error(f"[CONFIRM] Error en find_available_workers: {e}")
        workers, status, extra = [], "error", str(e)

    # Si no hay trabajadores disponibles
    if status != "success" or not workers:
        logger.info(f"[CONFIRM] No workers found: status={status}, chat_id={chat_id}")
        
        no_workers_text = generate_no_availability_message(status, service_id, hora_completa, extra)

        markup = types.InlineKeyboardMarkup(row_width=1)

        if status == "workers_busy":
            markup.add(
                types.InlineKeyboardButton(
                    "⏰ Ver otros horarios disponibles",
                    callback_data=f"alt_times:{service_id}:{request_id}"
                )
            )

        markup.add(
            types.InlineKeyboardButton(
                "🔄 Intentar de nuevo",
                callback_data=f"retry_search:{request_id}"
            ),
            types.InlineKeyboardButton(
                "◀️ Volver al inicio",
                callback_data="back_start"
            )
        )

        update_request_status(request_id, 'no_workers_found')
        edit_safe(chat_id, call.message.message_id, no_workers_text, markup)
        return

    # Notificar trabajadores encontrados
    notified = 0
    notification_errors = []

    for worker in workers:
        try:
            notify_worker(worker, request_id, service_id, hora_completa, lat, lon)
            notified += 1
            logger.info(f"[CONFIRM] Notificado trabajador {worker[0]} para request {request_id}")
        except Exception as e:
            logger.error(f"[CONFIRM] Error notificando a {worker[0]}: {e}")
            notification_errors.append(str(e))

    # Actualizar estado de la solicitud
    update_request_status(request_id, 'waiting_acceptance')

    # Guardar estado del usuario
    set_state(
        chat_id,
        UserState.CLIENT_WAITING_ACCEPTANCE,
        {"request_id": request_id, "service_id": service_id, "hora": hora_completa}
    )

    # Mensaje de confirmación al cliente
    waiting_text = f"""
{Icons.SUCCESS} <b>¡Solicitud enviada!</b>

{Icons.INFO} Hemos notificado a <b>{notified}</b> profesionales cercanos disponibles a las {hora_completa}.

{Icons.PENDING} Esperando que acepten tu solicitud...

{Icons.TIME} Tiempo estimado: 2-3 minutos
    """

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            f"{Icons.ERROR} Cancelar solicitud",
            callback_data=f"cancel_req:{request_id}"
        )
    )

    edit_safe(chat_id, call.message.message_id, waiting_text, markup)
    logger.info(f"[CONFIRM] Solicitud {request_id} creada. Notified={notified}")


# =========================================================
# CANCELAR SOLICITUD (callback_data="cancel_req:")
# =========================================================

@bot.callback_query_handler(func=lambda c: c.data.startswith("cancel_req:"))
def handle_cancel_request(call):
    """Cancela una solicitud activa"""
    chat_id = call.message.chat.id
    
    try:
        request_id = int(call.data.split(":")[1])
    except (ValueError, IndexError) as e:
        logger.error(f"[CANCEL] Error parseando request_id: {call.data}, error: {e}")
        bot.answer_callback_query(call.id, "❌ Error interno", show_alert=True)
        return

    # Verificar que la solicitud existe y pertenece a este usuario
    request = get_request(request_id)
    
    if not request:
        logger.warning(f"[CANCEL] Solicitud {request_id} no encontrada")
        bot.answer_callback_query(call.id, "❌ Solicitud no encontrada", show_alert=True)
        return
    
    # request = (id, client_id, service_id, fecha, hora, lat, lon, status, ...)
    if request[1] != chat_id:
        logger.warning(f"[CANCEL] Usuario {chat_id} intentó cancelar solicitud {request_id} de {request[1]}")
        bot.answer_callback_query(call.id, "❌ No tenés permiso para cancelar esta solicitud", show_alert=True)
        return
    
    current_status = request[7] if len(request) > 7 else 'unknown'
    
    # Solo cancelar si está en estado cancelable
    if current_status in ['completed', 'cancelled', 'rejected']:
        bot.answer_callback_query(call.id, f"⚠️ La solicitud ya está {current_status}", show_alert=True)
        return
    
    # Actualizar estado en BD
    try:
        update_request_status(request_id, 'cancelled')
        logger.info(f"[CANCEL] Solicitud {request_id} cancelada por usuario {chat_id}")
    except Exception as e:
        logger.error(f"[CANCEL] Error actualizando BD: {e}")
        bot.answer_callback_query(call.id, "❌ Error al cancelar", show_alert=True)
        return

    bot.answer_callback_query(call.id, "✅ Solicitud cancelada correctamente")

    # Mensaje de confirmación
    cancelled_text = f"""
{Icons.ERROR} <b>Solicitud cancelada</b>

Tu solicitud #{request_id} ha sido cancelada correctamente.

{Icons.WAVE} ¿Necesitás algo más?
    """

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "🔄 Nueva solicitud",
            callback_data="new_request"
        ),
        types.InlineKeyboardButton(
            "◀️ Volver al inicio",
            callback_data="back_start"
        )
    )

    edit_safe(chat_id, call.message.message_id, cancelled_text, markup)
    
    # Limpiar estado del usuario
    clear_state(chat_id)
    set_state(chat_id, UserState.SELECTING_ROLE)


# =========================================================
# REINTENTAR BUSQUEDA (callback_data="retry_search:")
# =========================================================

@bot.callback_query_handler(func=lambda c: c.data.startswith("retry_search:"))
def handle_retry_search(call):
    """Reintenta la búsqueda de trabajadores"""
    chat_id = call.message.chat.id
    
    try:
        request_id = int(call.data.split(":")[1])
    except (ValueError, IndexError) as e:
        logger.error(f"[RETRY] Error parseando request_id: {call.data}, error: {e}")
        bot.answer_callback_query(call.id, "❌ Error interno", show_alert=True)
        return

    request = get_request(request_id)

    if not request:
        logger.warning(f"[RETRY] Solicitud {request_id} no encontrada")
        bot.answer_callback_query(call.id, "❌ Solicitud no encontrada", show_alert=True)
        return

    # Extraer datos de la solicitud existente
    try:
        _, client_id, service_id, _, hora, lat, lon, status, *_ = request
    except ValueError as e:
        logger.error(f"[RETRY] Error desempaquetando request {request_id}: {e}")
        bot.answer_callback_query(call.id, "❌ Error en datos de solicitud", show_alert=True)
        return

    # Verificar que el usuario sea el dueño
    if client_id != chat_id:
        logger.warning(f"[RETRY] Usuario {chat_id} intentó retry de solicitud {request_id} de {client_id}")
        bot.answer_callback_query(call.id, "❌ No autorizado", show_alert=True)
        return

    # Actualizar estado
    try:
        update_request_status(request_id, 'searching')
    except Exception as e:
        logger.error(f"[RETRY] Error actualizando estado: {e}")

    bot.answer_callback_query(call.id, "🔄 Reintentando búsqueda...")

    # Parsear hora
    hora_parts = hora.split()
    time_str = hora_parts[0] if hora_parts else "12:00"
    period = hora_parts[1] if len(hora_parts) > 1 else "PM"

    # Actualizar datos en sesión
    update_data(
        chat_id,
        service_id=service_id,
        selected_time=time_str,
        time_period=period,
        lat=lat,
        lon=lon
    )

    # Llamar a confirmar nuevamente
    try:
        handle_confirm_request(call)
    except Exception as e:
        logger.error(f"[RETRY] Error en handle_confirm_request: {e}")
        bot.answer_callback_query(call.id, "❌ Error al reintentar", show_alert=True)
        handle_back_start(call)


# =========================================================
# HORARIOS ALTERNATIVOS (callback_data="alt_times:")
# =========================================================

@bot.callback_query_handler(func=lambda c: c.data.startswith("alt_times:"))
def handle_alternative_times(call):
    """Muestra horarios alternativos cuando los trabajadores están ocupados"""
    chat_id = call.message.chat.id
    
    try:
        parts = call.data.split(":")
        if len(parts) < 3:
            raise ValueError("Formato inválido")
        service_id = parts[1]
        request_id = int(parts[2])
    except (ValueError, IndexError) as e:
        logger.error(f"[ALT_TIMES] Error parseando callback: {call.data}, error: {e}")
        bot.answer_callback_query(call.id, "❌ Error interno", show_alert=True)
        return

    # Verificar que el servicio existe
    service = SERVICES.get(service_id)
    if not service:
        logger.error(f"[ALT_TIMES] Servicio {service_id} no encontrado")
        bot.answer_callback_query(call.id, "❌ Servicio no disponible", show_alert=True)
        return

    text = f"""
{Icons.CLOCK} <b>Horarios alternativos disponibles</b>

{service.get('icon', '🔧')} <b>{service.get('name', 'Servicio')}</b>

Seleccioná otro horario:
    """

    try:
        keyboard = get_alternative_times_keyboard(service_id, request_id)
        edit_safe(chat_id, call.message.message_id, text, keyboard)
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"[ALT_TIMES] Error mostrando teclado: {e}")
        bot.answer_callback_query(call.id, "❌ Error al cargar horarios", show_alert=True)


# =========================================================
# CAMBIAR HORA (callback_data="change_time:")
# =========================================================

@bot.callback_query_handler(func=lambda c: c.data.startswith("change_time:"))
def handle_change_time(call):
    """Cambia el horario de una solicitud existente"""
    chat_id = call.message.chat.id
    
    try:
        parts = call.data.split(":")
        if len(parts) < 3:
            raise ValueError("Formato inválido")
        request_id = int(parts[1])
        nueva_hora = parts[2]
    except (ValueError, IndexError) as e:
        logger.error(f"[CHANGE_TIME] Error parseando callback: {call.data}, error: {e}")
        bot.answer_callback_query(call.id, "❌ Error interno", show_alert=True)
        return

    # Actualizar en BD
    try:
        db_execute(
            "UPDATE requests SET hora = ? WHERE id = ? AND client_id = ?",
            (f"{nueva_hora} PM", request_id, chat_id),
            commit=True
        )
        logger.info(f"[CHANGE_TIME] Hora actualizada para request {request_id}: {nueva_hora} PM")
    except Exception as e:
        logger.error(f"[CHANGE_TIME] Error actualizando BD: {e}")
        bot.answer_callback_query(call.id, "❌ Error al cambiar hora", show_alert=True)
        return

    bot.answer_callback_query(call.id, f"✅ Hora cambiada a {nueva_hora} PM")

    # Reintentar búsqueda con nueva hora
    try:
        handle_retry_search(call)
    except Exception as e:
        logger.error(f"[CHANGE_TIME] Error en retry: {e}")
        bot.answer_callback_query(call.id, "❌ Error al buscar con nueva hora", show_alert=True)


# =========================================================
# VOLVER AL INICIO (callback_data="back_start")
# =========================================================

@bot.callback_query_handler(func=lambda c: c.data == "back_start")
def handle_back_start(call):
    """Vuelve al menú principal"""
    chat_id = call.message.chat.id

    # Limpiar estado
    clear_state(chat_id)

    bot.answer_callback_query(call.id, "🏠 Volviendo al inicio...")

    welcome_text = f"""
{Icons.WAVE} <b>¡Bienvenido a CleanyGo!</b>

Conectamos personas que necesitan servicios con profesionales confiables cerca de ti.

<b>¿Qué necesitás hacer?</b>
    """

    try:
        edit_safe(
            chat_id,
            call.message.message_id,
            welcome_text,
            get_role_keyboard()
        )
    except Exception as e:
        logger.error(f"[BACK_START] Error editando mensaje: {e}")
        send_safe(chat_id, welcome_text, get_role_keyboard())

    set_state(chat_id, UserState.SELECTING_ROLE)
    logger.info(f"[BACK_START] Usuario {chat_id} volvió al inicio")


# =========================================================
# NUEVA SOLICITUD (callback_data="new_request")
# =========================================================

@bot.callback_query_handler(func=lambda c: c.data == "new_request")
def handle_new_request(call):
    """Inicia una nueva solicitud (después de cancelar)"""
    chat_id = call.message.chat.id
    
    bot.answer_callback_query(call.id, "🆕 Nueva solicitud")
    
    # Limpiar datos anteriores
    clear_state(chat_id)
    
    # Redirigir a flujo de selección de servicio
    from handlers.client.flow import start_client_flow
    start_client_flow(chat_id)


# =========================================================
# COMPATIBILIDAD
# =========================================================

def register_handlers():
    """Telebot registra handlers automáticamente con decoradores"""
    logger.info("✅ Client callbacks registrados")
