"""
Handlers para gestión de trabajos/asignaciones para profesionales.
"""

from telebot import types
from config import bot, logger
from models.user_state import set_state, UserState
from models.services_data import SERVICES
from utils.icons import Icons
from utils.keyboards import get_job_response_keyboard
from services.request_service import get_request, assign_worker_to_request
from handlers.common import send_safe, edit_safe
import time
from database import db_execute

# ===================== HANDLERS =====================

@bot.callback_query_handler(func=lambda c: c.data.startswith("job_accept:"))
def handle_job_accept(call):
    chat_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])
    
    request = get_request(request_id)
    
    # Validar existencia y disponibilidad
    if not request:
        bot.answer_callback_query(call.id, "❌ Este trabajo no existe")
        edit_safe(chat_id, call.message.message_id, 
                  f"{Icons.ERROR} <b>Trabajo no disponible</b>\n\nNo se encontró la solicitud.")
        return
    
    if request[7] != 'waiting_acceptance':  # índice 7 = status
        bot.answer_callback_query(call.id, "❌ Este trabajo ya fue tomado por otro profesional")
        edit_safe(chat_id, call.message.message_id, 
                  f"{Icons.ERROR} <b>Trabajo no disponible</b>\n\nYa fue asignado a otro profesional.")
        return
    
    # Asignar el trabajador
    assign_worker_to_request(request_id, chat_id)
    bot.answer_callback_query(call.id, "✅ ¡Trabajo asignado!")
    
    # Mensaje al trabajador
    worker_text = f"""
{Icons.SUCCESS} <b>¡Trabajo confirmado!</b>

{Icons.INFO} Contactá al cliente para coordinar los detalles.

{Icons.PHONE} <b>Cliente:</b> {request[1]}
    """
    edit_safe(chat_id, call.message.message_id, worker_text)
    
    # Notificar al cliente
    client_id = request[1]
    service_id = request[2]
    hora = request[4]
    
    # Importar lazy para evitar ciclo circular
    from handlers.client.flow import get_service_display
    
    client_text = f"""
{Icons.PARTY} <b>¡Encontramos tu profesional!</b>

{get_service_display(service_id)}
{Icons.TIME} <b>Hora:</b> {hora}

{Icons.INFO} El profesional se pondrá en contacto con vos pronto.

{Icons.CAR} <b>Estado:</b> En camino al servicio
    """
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(f"{Icons.SUCCESS} Recibí el servicio", 
                                  callback_data=f"client_complete:{request_id}"),
        types.InlineKeyboardButton(f"{Icons.ERROR} Reportar problema", 
                                  callback_data=f"client_issue:{request_id}")
    )
    
    send_safe(client_id, client_text, markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("job_reject:"))
def handle_job_reject(call):
    chat_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])
    
    bot.answer_callback_query(call.id, "Trabajo rechazado")
    
    text = f"""
{Icons.INFO} <b>Trabajo rechazado</b>

Te seguiremos notificando de nuevas oportunidades.
    """
    edit_safe(chat_id, call.message.message_id, text)

# ===================== SERVICE FUNCTIONS =====================

def create_request(client_chat_id: str, service_id: str, hora: str, 
                   lat: float, lon: float, status: str = 'waiting_acceptance'):
    """Crea una nueva solicitud"""
    result = db_execute(
        """INSERT INTO requests (client_chat_id, service_id, hora, lat, lon, status) 
           VALUES (?, ?, ?, ?, ?, ?)""",
        (str(client_chat_id), service_id, hora, lat, lon, status),
        commit=True
    )
    
    if result is not None:
        return db_execute("SELECT last_insert_rowid()", fetch_one=True)[0]
    return None


def get_request(request_id: int):
    """Obtiene una solicitud por ID"""
    return db_execute(
        "SELECT * FROM requests WHERE id = ?", 
        (request_id,), 
        fetch_one=True
    )


def update_request_status(request_id: int, status: str, worker_chat_id: str = None):
    """Actualiza estado de una solicitud"""
    if worker_chat_id:
        return db_execute(
            """UPDATE requests SET status = ?, worker_chat_id = ?, accepted_at = ? 
               WHERE id = ?""",
            (status, str(worker_chat_id), int(time.time()), request_id),
            commit=True
        )
    return db_execute(
        "UPDATE requests SET status = ? WHERE id = ?",
        (status, request_id),
        commit=True
    )


def assign_worker_to_request(request_id: int, worker_chat_id: str):
    """Asigna un trabajador a una solicitud SOLO si sigue disponible"""
    return db_execute(
        """UPDATE requests
           SET worker_chat_id = ?, status = 'assigned', accepted_at = ?
           WHERE id = ? AND status = 'waiting_acceptance'""",
        (str(worker_chat_id), int(time.time()), request_id),
        commit=True
    )
