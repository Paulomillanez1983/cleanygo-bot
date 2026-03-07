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


# ================= INICIO FLUJO WORKER =================

def start_worker_flow(chat_id):
    """
    Inicia el flujo de trabajador cuando presiona '💼 Quiero trabajar'
    """

    bot = get_bot()

    logger.info(f"[WORKER FLOW] Inicio para {chat_id}")

    show_worker_menu(chat_id)


# ================= MENÚ PRINCIPAL WORKER =================

def show_worker_menu(worker_id, worker_data=None, extra_buttons=None):
    """
    Muestra el menú principal del trabajador.
    """

    worker_id = int(worker_id)
    bot = get_bot()

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

                current_request_id = worker_db["current_request_id"]
                worker_name = worker_db["name"] or "Trabajador"
                is_active = worker_db["is_active"]

                if current_request_id:

                    cursor.execute(
                        """
                        SELECT r.*, s.name as service_name
                        FROM requests r
                        LEFT JOIN services s ON r.service_id = s.id
                        WHERE r.id = ?
                        """,
                        (current_request_id,)
                    )

                    current_request = cursor.fetchone()

            else:

                worker_name = "Trabajador"
                is_active = False

    except Exception as e:

        logger.error(f"[WORKER MENU ERROR] {e}")

        worker_name = "Trabajador"
        is_active = False
        current_request = None


    # ================= TEXTO =================

    if current_request:

        text = f"""
{Icons.BRIEFCASE} <b>¡Tienes un trabajo activo!</b>

📋 <b>Servicio:</b> {current_request.get('service_name') or current_request.get('service_id', 'No especificado')}
🕐 <b>Hora:</b> {current_request.get('request_time', 'No definida')} {current_request.get('time_period', '')}
📍 <b>Ubicación:</b> Ver mapa

{Icons.INFO} Estado: <b>{current_request.get('status', 'pending').upper()}</b>
"""

        request_id = current_request["id"]

    else:

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


    # ================= BOTONES =================

    if current_request and request_id:

        status = current_request.get("status", "pending")

        if status == "assigned":

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

        elif status == "in_progress":

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


    if extra_buttons:

        for btn in extra_buttons:
            markup.add(btn)


    try:

        bot.send_message(
            worker_id,
            text,
            reply_markup=markup,
            parse_mode="HTML"
        )

        logger.info(f"[WORKER MENU] enviado a {worker_id}")

    except Exception as e:

        logger.error(f"[WORKER MENU SEND ERROR] {e}")


# ================= NOTIFICACIÓN NUEVA SOLICITUD =================

def notify_worker_new_request(worker_id, request_data):

    bot = get_bot()

    service_name = request_data.get("service_name", "Servicio")
    request_time = request_data.get("request_time", "No especificado")
    address = request_data.get("address", "No especificada")
    request_id = request_data.get("request_id", 0)

    text = f"""
🔔 <b>¡Nueva solicitud disponible!</b>

📋 <b>Servicio:</b> {service_name}
🕐 <b>Hora:</b> {request_time}
📍 <b>Ubicación:</b> {address}

¿Deseas aceptar este trabajo?
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
        )
    )

    bot.send_message(worker_id, text, reply_markup=markup, parse_mode="HTML")


# ================= REGISTRO HANDLERS =================

def register_handlers(bot):


    @bot.callback_query_handler(func=lambda c: c.data == "worker_activate")
    def handle_worker_activate(call):

        worker_id = call.message.chat.id

        try:

            with get_db_connection() as conn:

                cursor = conn.cursor()

                cursor.execute(
                    "UPDATE workers SET is_active = 1 WHERE user_id = ?",
                    (worker_id,)
                )

                conn.commit()

            bot.answer_callback_query(call.id, "Disponibilidad activada")

            show_worker_menu(worker_id)

        except Exception as e:

            logger.error(f"[ACTIVATE ERROR] {e}")

            bot.answer_callback_query(call.id, "Error al activar")


    logger.info("[WORKER HANDLERS] registrados correctamente")
