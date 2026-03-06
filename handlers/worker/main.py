"""
Módulo principal para manejo de workers - Menú y notificaciones de solicitudes
VERSIÓN CORREGIDA: Registro de handlers en función para evitar import circular
"""

from telebot import types
from config import get_bot, notify_client, get_db_connection
from handlers.common import send_safe, edit_safe
from utils.icons import Icons
import logging

logger = logging.getLogger(__name__)


def show_worker_menu(worker_id, worker_data=None, extra_buttons=None):
    """
    Muestra el menú principal del trabajador.
    """
    worker_id = int(worker_id)
    bot = get_bot()  # Obtener instancia actual del bot
    
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
        status_icon = "🟢" if is_active else "🔴"
        status_text = "Activo - Buscando solicitudes" if is_active else "Inactivo"
        
        text = f"""
👷 <b>Hola {worker_name}!</b>

{status_icon} <b>Estado:</b> {status_text}

ℹ️ Te notificaremos cuando haya solicitudes disponibles para tus servicios.

💰 <b>Consejo:</b> Mantené tu perfil actualizado para recibir más solicitudes.
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
                    "🧭 Ver ubicación del cliente", 
                    callback_data=f"view_location:{request_id}"
                ),
                types.InlineKeyboardButton(
                    "✅ Marcar como iniciado", 
                    callback_data=f"start_job:{request_id}"
                ),
                types.InlineKeyboardButton(
                    "📞 Contactar cliente", 
                    callback_data=f"contact_client:{request_id}"
                )
            )
        elif status == 'in_progress':
            markup.add(
                types.InlineKeyboardButton(
                    "✅ Completar servicio", 
                    callback_data=f"complete_job:{request_id}"
                )
            )
            
        markup.add(
            types.InlineKeyboardButton(
                "⚠️ Reportar problema", 
                callback_data=f"report_issue:{request_id}"
            )
        )
    else:
        # Sin solicitud - opciones generales
        if is_active:
            markup.add(
                types.InlineKeyboardButton(
                    "⚙️ Ver mis servicios", 
                    callback_data="worker_services"
                ),
                types.InlineKeyboardButton(
                    "📍 Actualizar ubicación", 
                    callback_data="update_location"
                )
            )
        else:
            markup.add(
                types.InlineKeyboardButton(
                    "▶️ Activar disponibilidad", 
                    callback_data="worker_activate"
                )
            )

    # Agregar botones extra si se pasaron
    if extra_buttons and isinstance(extra_buttons, list):
        for btn in extra_buttons:
            markup.add(btn)

    try:
        bot.send_message(worker_id, text, reply_markup=markup, parse_mode="HTML")
        logger.info(f"[WORKER MENU] Menú enviado a worker {worker_id}, request_activa={request_id}")
    except Exception as e:
        logger.error(f"[WORKER MENU ERROR] {e}")


def notify_worker_new_request(worker_id, request_data):
    """
    Notifica a un worker sobre una nueva solicitud disponible.
    """
    worker_id = int(worker_id)
    bot = get_bot()
    
    service_name = request_data.get('service_name', 'Servicio')
    request_time = request_data.get('request_time', 'No especificado')
    time_period = request_data.get('time_period', '')
    address = request_data.get('address', 'No especificada')
    request_id = request_data.get('request_id', 0)
    
    text = f"""
🔔 <b>¡Nueva solicitud disponible!</b>

📋 <b>Servicio:</b> {service_name}
🕐 <b>Hora:</b> {request_time} {time_period}
📍 <b>Ubicación:</b> {address}

ℹ️ ¿Deseas aceptar este trabajo?
"""
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(
            "✅ Aceptar", 
            callback_data=f"accept_request:{request_id}"
        ),
        types.InlineKeyboardButton(
            "❌ Rechazar", 
            callback_data=f"reject_request:{request_id}"
        ),
        types.InlineKeyboardButton(
            "ℹ️ Ver detalles", 
            callback_data=f"view_request:{request_id}"
        )
    )
    
    try:
        bot.send_message(worker_id, text, reply_markup=markup, parse_mode="HTML")
        logger.info(f"[NOTIFY WORKER] Solicitud {request_id} notificada a worker {worker_id}")
        return True
    except Exception as e:
        logger.error(f"[NOTIFY WORKER ERROR] worker={worker_id}, request={request_id}: {e}")
        return False


# ==================== FUNCIÓN DE REGISTRO DE HANDLERS ====================

def register_handlers(bot):
    """
    Registra todos los handlers de callbacks para workers.
    LLAMAR ESTA FUNCIÓN desde main.py después de crear el bot.
    """
    
    @bot.callback_query_handler(func=lambda c: c.data.startswith("accept_request:"))
    def handle_worker_accept_request(call):
        """Worker acepta una solicitud"""
        worker_id = call.message.chat.id
        request_id = int(call.data.split(":")[1])
        
        # Simular asignación (adaptar según tu requests_db)
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                # Actualizar request
                cursor.execute(
                    "UPDATE requests SET worker_id = ?, status = 'assigned' WHERE id = ?",
                    (worker_id, request_id)
                )
                # Actualizar worker
                cursor.execute(
                    "UPDATE workers SET current_request_id = ? WHERE user_id = ?",
                    (request_id, worker_id)
                )
                conn.commit()
            
            bot.answer_callback_query(call.id, "✅ ¡Solicitud asignada!")
            
            # Notificar al cliente
            notify_client(
                worker_id,  # Aquí debería ser el client_id real
                f"✅ <b>¡Tu solicitud fue aceptada!</b>\n\n"
                f"Un profesional ha sido asignado."
            )
            
            # Mostrar menú actualizado
            show_worker_menu(worker_id)
            logger.info(f"[WORKER ACCEPT] Worker {worker_id} aceptó request {request_id}")
            
        except Exception as e:
            logger.error(f"[WORKER ACCEPT ERROR] {e}")
            bot.answer_callback_query(call.id, "❌ Error al asignar")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("reject_request:"))
    def handle_worker_reject_request(call):
        """Worker rechaza una solicitud"""
        worker_id = call.message.chat.id
        request_id = int(call.data.split(":")[1])
        
        try:
            # Registrar rechazo en tabla de rechazos
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR IGNORE INTO request_rejections (request_id, worker_id) VALUES (?, ?)",
                    (request_id, worker_id)
                )
                conn.commit()
            
            bot.answer_callback_query(call.id, "Solicitud rechazada")
            
            # Editar mensaje
            try:
                bot.edit_message_text(
                    "ℹ️ Has rechazado la solicitud. Te notificaremos de nuevas oportunidades.",
                    chat_id=worker_id,
                    message_id=call.message.message_id
                )
            except:
                pass
                
            logger.info(f"[WORKER REJECT] Worker {worker_id} rechazó request {request_id}")
            
        except Exception as e:
            logger.error(f"[WORKER REJECT ERROR] {e}")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("view_request:"))
    def handle_worker_view_request(call):
        """Worker ve detalles de solicitud"""
        request_id = int(call.data.split(":")[1])
        
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM requests WHERE id = ?", (request_id,))
                request_data = cursor.fetchone()
            
            if not request_data:
                bot.answer_callback_query(call.id, "Solicitud no disponible")
                return
            
            text = f"""
ℹ️ <b>Detalles de la solicitud</b>

📋 <b>Servicio:</b> {request_data.get('service_name', request_data.get('service_id', 'No especificado'))}
🕐 <b>Hora:</b> {request_data.get('request_time', 'No definida')} {request_data.get('time_period', '')}
📍 <b>Dirección:</b> {request_data.get('address', 'No especificada')}

⚠️ <b>Nota:</b> Al aceptar, te comprometes a cumplir con el horario indicado.
"""
            bot.answer_callback_query(call.id, "Mostrando detalles...")
            bot.send_message(call.message.chat.id, text, parse_mode="HTML")
            
        except Exception as e:
            logger.error(f"[VIEW REQUEST ERROR] {e}")
            bot.answer_callback_query(call.id, "Error al obtener detalles")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("start_job:"))
    def handle_worker_start_job(call):
        """Worker inicia el servicio"""
        worker_id = call.message.chat.id
        request_id = int(call.data.split(":")[1])
        
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE requests SET status = 'in_progress' WHERE id = ?",
                    (request_id,)
                )
                conn.commit()
            
            bot.answer_callback_query(call.id, "Servicio iniciado")
            show_worker_menu(worker_id)
            logger.info(f"[JOB START] Worker {worker_id} inició request {request_id}")
            
        except Exception as e:
            logger.error(f"[JOB START ERROR] {e}")
            bot.answer_callback_query(call.id, "Error al iniciar")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("complete_job:"))
    def handle_worker_complete_job(call):
        """Worker completa el servicio"""
        worker_id = call.message.chat.id
        request_id = int(call.data.split(":")[1])
        
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                # Completar request
                cursor.execute(
                    "UPDATE requests SET status = 'completed', completed_at = strftime('%s','now') WHERE id = ?",
                    (request_id,)
                )
                # Liberar worker
                cursor.execute(
                    "UPDATE workers SET current_request_id = NULL WHERE user_id = ?",
                    (worker_id,)
                )
                conn.commit()
            
            bot.answer_callback_query(call.id, "¡Servicio completado!")
            show_worker_menu(worker_id)
            logger.info(f"[JOB COMPLETE] Worker {worker_id} completó request {request_id}")
            
        except Exception as e:
            logger.error(f"[JOB COMPLETE ERROR] {e}")
            bot.answer_callback_query(call.id, "Error al completar")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("contact_client:"))
    def handle_worker_contact_client(call):
        """Worker solicita contactar al cliente"""
        request_id = int(call.data.split(":")[1])
        
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT client_id FROM requests WHERE id = ?", (request_id,))
                result = cursor.fetchone()
                client_id = result['client_id'] if result else None
            
            bot.answer_callback_query(call.id, "Contacto solicitado")
            
            text = f"📞 <b>Contacto del cliente</b>\n\nID Cliente: <code>{client_id}</code>\n\n(Puedes escribirle directamente)"
            bot.send_message(call.message.chat.id, text, parse_mode="HTML")
            
        except Exception as e:
            logger.error(f"[CONTACT CLIENT ERROR] {e}")
            bot.answer_callback_query(call.id, "Error al obtener contacto")

    @bot.callback_query_handler(func=lambda c: c.data == "worker_activate")
    def handle_worker_activate(call):
        """Worker activa su disponibilidad"""
        worker_id = call.message.chat.id
        
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE workers SET is_active = 1 WHERE user_id = ?",
                    (worker_id,)
                )
                conn.commit()
            
            bot.answer_callback_query(call.id, "✅ Disponibilidad activada")
            show_worker_menu(worker_id)
            logger.info(f"[WORKER ACTIVATE] Worker {worker_id} activado")
            
        except Exception as e:
            logger.error(f"[ACTIVATE ERROR] {e}")
            bot.answer_callback_query(call.id, "Error al activar")

    @bot.callback_query_handler(func=lambda c: c.data == "worker_services")
    def handle_worker_services(call):
        """Worker ve sus servicios"""
        bot.answer_callback_query(call.id, "Función en desarrollo")
        bot.send_message(call.message.chat.id, "⚙️ Configuración de servicios - Próximamente")

    @bot.callback_query_handler(func=lambda c: c.data == "update_location")
    def handle_update_location(call):
        """Worker actualiza ubicación"""
        bot.answer_callback_query(call.id, "Función en desarrollo")
        bot.send_message(call.message.chat.id, "📍 Actualización de ubicación - Próximamente")

    logger.info("[WORKER HANDLERS] Handlers de worker registrados correctamente")
