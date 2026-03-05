"""
Módulo principal para manejo de workers - Menú y notificaciones de solicitudes
VERSIÓN CORREGIDA: Integración completa con requests_db y notificaciones
"""

from telebot import types
from config import bot, notify_client, get_db_connection
from handlers.common import send_safe, edit_safe
from utils.icons import Icons
from utils.keyboards import get_worker_request_keyboard
import logging

logger = logging.getLogger(__name__)

def show_worker_menu(worker_id, worker_data=None, extra_buttons=None):
    """
    Muestra el menú principal del trabajador.
    
    Parámetros:
    - worker_id: chat_id del trabajador (int)
    - worker_data: diccionario opcional con datos de solicitud activa
    - extra_buttons: lista opcional de InlineKeyboardButton adicionales
    """
    worker_id = int(worker_id)
    
    # Obtener datos actualizados del worker desde DB
    current_request = None
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT current_request_id, name, is_active FROM workers WHERE user_id = ?", 
                (worker_id,)
            )
            worker_db = cursor.fetchone()
            
            if worker_db:
                current_request_id = worker_db['current_request_id']
                worker_name = worker_db['name'] or "Trabajador"
                is_active = worker_db['is_active']
                
                # Si hay request activa, obtener detalles
                if current_request_id:
                    cursor.execute("""
                        SELECT r.*, s.name as service_name 
                        FROM requests r
                        LEFT JOIN services s ON r.service_id = s.id
                        WHERE r.id = ?
                    """, (current_request_id,))
                    current_request = cursor.fetchone()
            else:
                worker_name = "Trabajador"
                is_active = False
                
    except Exception as e:
        logger.error(f"[WORKER MENU] Error obteniendo datos de worker {worker_id}: {e}")
        worker_name = "Trabajador"
        is_active = False
        current_request = None

    # Construir mensaje base
    if current_request:
        # Worker tiene solicitud activa
        text = f"""
{Icons.BRIEFCASE} <b>¡Tienes un trabajo activo!</b>

📋 <b>Servicio:</b> {current_request.get('service_name') or current_request.get('service_id', 'No especificado')}
🕐 <b>Hora:</b> {current_request.get('request_time', 'No definida')} {current_request.get('time_period', '')}
📍 <b>Ubicación:</b> Ver mapa

{Icons.INFO} Estado: <b>{current_request.get('status', 'pending').upper()}</b>
"""
        request_id = current_request['id']
    else:
        # Worker disponible, sin solicitudes
        status_icon = Icons.GREEN_CIRCLE if is_active else Icons.RED_CIRCLE
        status_text = "Activo - Buscando solicitudes" if is_active else "Inactivo"
        
        text = f"""
{Icons.WORKER} <b>Hola {worker_name}!</b>

{status_icon} <b>Estado:</b> {status_text}

{Icons.INFO} Te notificaremos cuando haya solicitudes disponibles para tus servicios.

{Icons.MONEY} <b>Consejo:</b> Mantené tu perfil actualizado para recibir más solicitudes.
"""
        request_id = None

    markup = types.InlineKeyboardMarkup(row_width=1)

    # Botones según estado
    if current_request and request_id:
        # Hay solicitud activa - mostrar acciones
        status = current_request.get('status', 'pending')
        
        if status == 'assigned':
            markup.add(
                types.InlineKeyboardButton(
                    f"{Icons.NAVIGATION} Ver ubicación del cliente", 
                    callback_data=f"view_location:{request_id}"
                ),
                types.InlineKeyboardButton(
                    f"{Icons.CHECK} Marcar como iniciado", 
                    callback_data=f"start_job:{request_id}"
                ),
                types.InlineKeyboardButton(
                    f"{Icons.PHONE} Contactar cliente", 
                    callback_data=f"contact_client:{request_id}"
                )
            )
        elif status == 'in_progress':
            markup.add(
                types.InlineKeyboardButton(
                    f"{Icons.CHECK} Completar servicio", 
                    callback_data=f"complete_job:{request_id}"
                )
            )
            
        markup.add(
            types.InlineKeyboardButton(
                f"{Icons.WARNING} Reportar problema", 
                callback_data=f"report_issue:{request_id}"
            )
        )
    else:
        # Sin solicitud - opciones generales
        if is_active:
            markup.add(
                types.InlineKeyboardButton(
                    f"{Icons.SETTINGS} Ver mis servicios", 
                    callback_data="worker_services"
                ),
                types.InlineKeyboardButton(
                    f"{Icons.LOCATION} Actualizar ubicación", 
                    callback_data="update_location"
                )
            )
        else:
            markup.add(
                types.InlineKeyboardButton(
                    f"{Icons.PLAY} Activar disponibilidad", 
                    callback_data="worker_activate"
                )
            )

    # Agregar botones extra si se pasaron
    if extra_buttons and isinstance(extra_buttons, list):
        for btn in extra_buttons:
            markup.add(btn)

    send_safe(worker_id, text, markup)
    logger.info(f"[WORKER MENU] Menú enviado a worker {worker_id}, request_activa={request_id}")

def notify_worker_new_request(worker_id, request_data):
    """
    Notifica a un worker sobre una nueva solicitud disponible.
    Esta función es llamada por broadcast_to_workers desde config.py
    
    Parámetros:
    - worker_id: ID del trabajador
    - request_data: dict con datos de la solicitud
    """
    worker_id = int(worker_id)
    
    service_name = request_data.get('service_name', 'Servicio')
    request_time = request_data.get('request_time', 'No especificado')
    time_period = request_data.get('time_period', '')
    address = request_data.get('address', 'No especificada')
    request_id = request_data.get('request_id', 0)
    
    text = f"""
{Icons.BELL} <b>¡Nueva solicitud disponible!</b>

📋 <b>Servicio:</b> {service_name}
🕐 <b>Hora:</b> {request_time} {time_period}
📍 <b>Ubicación:</b> {address}

{Icons.INFO} ¿Deseas aceptar este trabajo?
"""
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(
            f"{Icons.SUCCESS} Aceptar", 
            callback_data=f"accept_request:{request_id}"
        ),
        types.InlineKeyboardButton(
            f"{Icons.ERROR} Rechazar", 
            callback_data=f"reject_request:{request_id}"
        ),
        types.InlineKeyboardButton(
            f"{Icons.INFO} Ver detalles", 
            callback_data=f"view_request:{request_id}"
        )
    )
    
    try:
        send_safe(worker_id, text, markup)
        logger.info(f"[NOTIFY WORKER] Solicitud {request_id} notificada a worker {worker_id}")
        return True
    except Exception as e:
        logger.error(f"[NOTIFY WORKER ERROR] worker={worker_id}, request={request_id}: {e}")
        return False

# ==================== HANDLERS DE CALLBACKS ====================

@bot.callback_query_handler(func=lambda c: c.data.startswith("accept_request:"))
def handle_worker_accept_request(call):
    """Worker acepta una solicitud"""
    worker_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])
    
    from requests_db import assign_worker_to_request, get_request
    
    # Intentar asignar
    result = assign_worker_to_request(request_id, worker_id)
    
    if result:
        # Éxito - obtener datos actualizados
        request_data = get_request(request_id)
        
        bot.answer_callback_query(call.id, "✅ ¡Solicitud asignada!")
        
        # Notificar al cliente
        client_id = request_data.get('client_id')
        if client_id:
            notify_client(
                client_id, 
                f"{Icons.SUCCESS} <b>¡Tu solicitud fue aceptada!</b>\n\n"
                f"Un profesional ha sido asignado y se pondrá en contacto contigo."
            )
        
        # Mostrar menú actualizado al worker
        show_worker_menu(worker_id)
        logger.info(f"[WORKER ACCEPT] Worker {worker_id} aceptó request {request_id}")
    else:
        # Fallo - probablemente ya fue tomada
        bot.answer_callback_query(call.id, "❌ Esta solicitud ya no está disponible")
        edit_safe(
            worker_id, 
            call.message.message_id, 
            f"{Icons.ERROR} Esta solicitud ya fue tomada por otro profesional."
        )

@bot.callback_query_handler(func=lambda c: c.data.startswith("reject_request:"))
def handle_worker_reject_request(call):
    """Worker rechaza una solicitud"""
    worker_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])
    
    from requests_db import reject_request
    
    # Registrar rechazo
    reject_request(request_id, worker_id)
    
    bot.answer_callback_query(call.id, "Solicitud rechazada")
    edit_safe(
        worker_id,
        call.message.message_id,
        f"{Icons.INFO} Has rechazado la solicitud. Te notificaremos de nuevas oportunidades."
    )
    
    logger.info(f"[WORKER REJECT] Worker {worker_id} rechazó request {request_id}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("view_request:"))
def handle_worker_view_request(call):
    """Worker ve detalles de solicitud antes de aceptar"""
    request_id = int(call.data.split(":")[1])
    
    from requests_db import get_request
    
    request_data = get_request(request_id)
    if not request_data:
        bot.answer_callback_query(call.id, "Solicitud no disponible")
        return
    
    text = f"""
{Icons.INFO} <b>Detalles de la solicitud</b>

📋 <b>Servicio:</b> {request_data.get('service_name', 'No especificado')}
🕐 <b>Hora:</b> {request_data.get('request_time')} {request_data.get('time_period', '')}
📍 <b>Dirección:</b> {request_data.get('address', 'No especificada')}
💰 <b>Precio estimado:</b> ${request_data.get('precio_acordado', 'A convenir')}

{Icons.WARNING} <b>Nota:</b> Al aceptar, te comprometes a cumplir con el horario indicado.
"""
    bot.answer_callback_query(call.id, "Mostrando detalles...")
    send_safe(call.message.chat.id, text)

@bot.callback_query_handler(func=lambda c: c.data.startswith("start_job:"))
def handle_worker_start_job(call):
    """Worker inicia el servicio (llegó al lugar)"""
    worker_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])
    
    from requests_db import update_request_status, get_request
    
    # Actualizar estado
    success = update_request_status(request_id, 'in_progress')
    
    if success:
        request_data = get_request(request_id)
        client_id = request_data.get('client_id')
        
        bot.answer_callback_query(call.id, "Servicio iniciado")
        
        # Notificar al cliente
        if client_id:
            notify_client(
                client_id,
                f"{Icons.INFO} <b>¡Tu profesional ha llegado!</b>\n\n"
                f"El servicio ha comenzado. {Icons.WORKER}"
            )
        
        # Actualizar menú del worker
        show_worker_menu(worker_id)
        logger.info(f"[JOB START] Worker {worker_id} inició request {request_id}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("complete_job:"))
def handle_worker_complete_job(call):
    """Worker completa el servicio"""
    worker_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])
    
    from requests_db import complete_request, get_request
    
    result = complete_request(request_id)
    
    if result:
        request_data = get_request(request_id)
        client_id = request_data.get('client_id')
        
        bot.answer_callback_query(call.id, "¡Servicio completado!")
        
        # Notificar al cliente para calificación
        if client_id:
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("⭐ Calificar servicio", callback_data=f"rate_service:{request_id}")
            )
            notify_client(
                client_id,
                f"{Icons.CHECK} <b>Servicio completado</b>\n\n"
                f"¿Cómo fue tu experiencia? Por favor, califica al profesional.",
                markup=markup
            )
        
        # Liberar al worker y mostrar menú disponible
        show_worker_menu(worker_id)
        logger.info(f"[JOB COMPLETE] Worker {worker_id} completó request {request_id}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("contact_client:"))
def handle_worker_contact_client(call):
    """Worker solicita contactar al cliente"""
    request_id = int(call.data.split(":")[1])
    
    from requests_db import get_request
    
    request_data = get_request(request_id)
    if not request_data:
        bot.answer_callback_query(call.id, "Error al obtener datos")
        return
    
    # Aquí podrías implementar un sistema de mensajes intermediado
    # o compartir el contacto del cliente si así lo desea
    bot.answer_callback_query(call.id, "Contacto solicitado")
    send_safe(
        call.message.chat.id,
        f"{Icons.PHONE} <b>Contacto del cliente</b>\n\n"
        f"ID Cliente: <code>{request_data.get('client_id')}</code>\n"
        f"(En producción: compartir teléfono o chat directo)"
    )
