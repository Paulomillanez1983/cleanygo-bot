"""
Handlers para gestión de trabajos/asignaciones para profesionales.
Versión corregida para reflejar el precio real del trabajador.
"""

from telebot import types
from config import bot, logger, DB_FILE
from models.user_state import set_state, UserState
from utils.icons import Icons
from utils.keyboards import get_job_response_keyboard
from services.request_service import assign_worker_to_request_safe, get_request, update_request_status
from handlers.common import send_safe, edit_safe
import time
from database import db_execute
import sqlite3

# ===================== PRECIOS DE SERVICIOS (nombres por default) =====================
SERVICES_PRICES = {
    "ninaera": {"name": "Niñera", "price": 1500},
    "limpieza": {"name": "Limpieza", "price": 2000},
    "plomeria": {"name": "Plomería", "price": 2500},
}

# ===================== CREAR TABLA RECHAZOS =====================
def init_request_rejections_table():
    """Crea tabla request_rejections si no existe"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS request_rejections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL,
                worker_chat_id TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
        ''')
        conn.commit()
    logger.info("✅ Tabla request_rejections inicializada")

# Inicializar tabla al cargar el handler
init_request_rejections_table()

# ===================== HANDLERS =====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("job_accept:"))
def handle_job_accept(call):
    chat_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])
    
    logger.info(f"[JOB_ACCEPT] worker={chat_id} intenta aceptar request_id={request_id}")
    
    request = get_request(request_id)
    
    if not request:
        logger.warning(f"[JOB_ACCEPT] request_id={request_id} no encontrado")
        bot.answer_callback_query(call.id, "❌ Este trabajo no existe")
        edit_safe(chat_id, call.message.message_id, 
                  f"{Icons.ERROR} <b>Trabajo no disponible</b>\n\nNo se encontró la solicitud.")
        return
    
    if request["status"] not in ('pending', 'searching', 'waiting_acceptance'):
        logger.warning(f"[JOB_ACCEPT] request_id={request_id} status={request['status']} ya asignado")
        bot.answer_callback_query(call.id, "❌ Este trabajo ya fue tomado por otro profesional")
        edit_safe(chat_id, call.message.message_id, 
                  f"{Icons.ERROR} <b>Trabajo no disponible</b>\n\nYa fue asignado a otro profesional.")
        return
    
    # Intentar asignar de forma segura
    updated = assign_worker_to_request_safe(request_id, chat_id)
    if not updated:
        logger.warning(f"[JOB_ACCEPT] request_id={request_id} fallo al asignar a worker={chat_id}")
        bot.answer_callback_query(call.id, "❌ No se pudo asignar el trabajo")
        edit_safe(chat_id, call.message.message_id, 
                  f"{Icons.ERROR} <b>Trabajo no disponible</b>\n\nOtro profesional lo tomó primero.")
        return
    
    bot.answer_callback_query(call.id, "✅ ¡Trabajo asignado!")
    
    # Mensaje al trabajador
    worker_text = f"""
{Icons.SUCCESS} <b>¡Trabajo confirmado!</b>

{Icons.INFO} Contactá al cliente para coordinar los detalles.

{Icons.PHONE} <b>Cliente:</b> {request['client_chat_id']}
    """
    edit_safe(chat_id, call.message.message_id, worker_text)
    
    # Notificar al cliente
    client_id = request["client_chat_id"]
    service_id = request["service_id"]
    hora = request["hora"]
    
    # Obtener el precio real que puso el trabajador
    worker_price_info = db_execute(
        "SELECT precio FROM worker_services WHERE chat_id = ? AND service_id = ?",
        (chat_id, service_id),
        fetch_one=True
    )
    price = worker_price_info[0] if worker_price_info else 0
    
    # Nombre del servicio
    service_name = SERVICES_PRICES.get(service_id, {"name": service_id.capitalize()})["name"]
    
    client_text = f"""
{Icons.PARTY} <b>¡Encontramos tu profesional!</b>

Servicio: {service_name}
{Icons.MONEY} <b>Precio:</b> ${price}
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
    
    logger.info(f"[JOB_ACCEPT] request_id={request_id} asignado correctamente a worker={chat_id}")


@bot.callback_query_handler(func=lambda c: c.data.startswith("job_reject:"))
def handle_job_reject(call):
    chat_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])
    
    logger.info(f"[JOB_REJECT] worker={chat_id} rechazó request_id={request_id}")
    
    bot.answer_callback_query(call.id, "Trabajo rechazado")
    
    text = f"""
{Icons.INFO} <b>Trabajo rechazado</b>

Te seguiremos notificando de nuevas oportunidades.
    """
    edit_safe(chat_id, call.message.message_id, text)
    
    # Guardar el rechazo en DB
    try:
        db_execute(
            "INSERT INTO request_rejections (request_id, worker_chat_id, created_at) VALUES (?, ?, ?)",
            (request_id, chat_id, int(time.time())),
            commit=True
        )
        logger.info(f"[JOB_REJECT] registro rechazo guardado request_id={request_id}, worker={chat_id}")
    except Exception as e:
        logger.error(f"[JOB_REJECT] error guardando rechazo request_id={request_id}, worker={chat_id}: {e}")
