# handlers/worker/jobs.py
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

# NOTA: No importar get_service_display aquí arriba - causa ciclo circular
# Se importa lazy dentro de las funciones que lo necesitan

@bot.callback_query_handler(func=lambda c: c.data.startswith("job_accept:"))
def handle_job_accept(call):
    chat_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])
    
    request = get_request(request_id)
    
    if not request or request[7] != 'waiting_acceptance':  # status
        bot.answer_callback_query(call.id, "❌ Este trabajo ya fue tomado por otro profesional")
        edit_safe(chat_id, call.message.message_id, 
                 f"{Icons.ERROR} <b>Trabajo no disponible</b>\n\nYa fue asignado a otro profesional.")
        return
    
    assign_worker_to_request(request_id, chat_id)
    bot.answer_callback_query(call.id, "✅ ¡Trabajo asignado!")
    
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
    
    # ✅ LAZY IMPORT: Importar aquí dentro de la función para evitar ciclo circular
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
