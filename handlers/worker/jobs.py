"""
Handlers para gestión de trabajos/asignaciones para profesionales.
Incluye aceptación/rechazo del cliente según el precio y actualización de sesión.
"""

from telebot import types
from config import bot, logger, DB_FILE
from models.user_state import set_state, UserState, update_data
from utils.icons import Icons
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

init_request_rejections_table()

# ===================== HANDLER: TRABAJADOR ACEPTA TRABAJO =====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("job_accept:"))
def handle_job_accept(call):
    chat_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])

    logger.info(f"[JOB_ACCEPT] worker={chat_id} intenta aceptar request_id={request_id}")

    request = get_request(request_id)
    if not request:
        bot.answer_callback_query(call.id, "❌ Este trabajo no existe")
        edit_safe(chat_id, call.message.message_id, f"{Icons.ERROR} <b>Trabajo no disponible</b>")
        return

    if request["status"] not in ('pending', 'searching', 'waiting_acceptance'):
        bot.answer_callback_query(call.id, "❌ Este trabajo ya fue tomado")
        edit_safe(chat_id, call.message.message_id, f"{Icons.ERROR} <b>Trabajo no disponible</b>")
        return

    updated = assign_worker_to_request_safe(request_id, chat_id)
    if not updated:
        bot.answer_callback_query(call.id, "❌ No se pudo asignar")
        edit_safe(chat_id, call.message.message_id, f"{Icons.ERROR} <b>Trabajo no disponible</b>")
        return

    # ===================== ACTUALIZAR SESIÓN DEL TRABAJADOR =====================
    set_state(chat_id, UserState.JOB_IN_PROGRESS, {
        "request_id": request_id,
        "client_id": request["client_chat_id"],
        "service_id": request["service_id"],
        "hora": request["hora"]
    })

    bot.answer_callback_query(call.id, "✅ ¡Trabajo asignado!")
    edit_safe(chat_id, call.message.message_id, f"""
{Icons.SUCCESS} <b>¡Trabajo confirmado!</b>
{Icons.INFO} Contactá al cliente para coordinar.
{Icons.PHONE} <b>Cliente:</b> {request['client_chat_id']}
""")

    # ==================== NOTIFICAR AL CLIENTE =====================
    client_id = request["client_chat_id"]
    service_id = request["service_id"]
    hora = request["hora"]

    worker_price_info = db_execute(
        "SELECT precio FROM worker_services WHERE chat_id = ? AND service_id = ?",
        (chat_id, service_id),
        fetch_one=True
    )
    price = worker_price_info[0] if worker_price_info else 0
    service_name = SERVICES_PRICES.get(service_id, {"name": service_id.capitalize()})["name"]

    client_text = f"""
{Icons.PARTY} <b>¡Encontramos tu profesional!</b>

Servicio: {service_name}
{Icons.MONEY} <b>Precio:</b> ${price}
{Icons.TIME} <b>Hora:</b> {hora}

{Icons.INFO} Confirmá si aceptás el servicio.
"""

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(f"{Icons.SUCCESS} Acepto", callback_data=f"client_accept:{request_id}"),
        types.InlineKeyboardButton(f"{Icons.ERROR} No acepto", callback_data=f"client_reject:{request_id}")
    )

    send_safe(client_id, client_text, markup)
    logger.info(f"[JOB_ACCEPT] request_id={request_id} enviado al cliente para aceptación")

# ===================== HANDLER: CLIENTE ACEPTA =====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("client_accept:"))
def handle_client_accept(call):
    client_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])

    request = get_request(request_id)
    if not request:
        bot.answer_callback_query(call.id, "❌ Esta solicitud no existe")
        edit_safe(client_id, call.message.message_id, f"{Icons.ERROR} Solicitud no encontrada")
        return

    # ===================== ACTUALIZAR ESTADO =====================
    update_request_status(request_id, "accepted")  # Estado estandarizado

    # ===================== NOTIFICAR CLIENTE =====================
    edit_safe(client_id, call.message.message_id, f"{Icons.SUCCESS} Gracias, aceptaste el servicio ✅")

    # ===================== NOTIFICAR TRABAJADOR =====================
    worker_id = request.get("worker_chat_id")
    if worker_id:
        send_safe(worker_id, f"{Icons.SUCCESS} El cliente aceptó el servicio. ¡Podés realizarlo!")

        # REFRESCAR MENÚ DEL TRABAJADOR PARA MOSTRAR BOTÓN INICIAR SERVICIO
        worker_data = db_execute(
            "SELECT * FROM workers WHERE chat_id=?",
            (str(worker_id),),
            fetch_one=True
        )
        if worker_data:
            try:
                from handlers.worker.main import show_worker_menu
                show_worker_menu(worker_id, worker_data)
            except Exception as e:
                logger.error(f"[CLIENT_ACCEPT] error mostrando menú worker_id={worker_id}: {e}")

# ===================== HANDLER: CLIENTE RECHAZA =====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("client_reject:"))
def handle_client_reject(call):
    client_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])

    request = get_request(request_id)
    if not request:
        bot.answer_callback_query(call.id, "❌ Esta solicitud no existe")
        edit_safe(client_id, call.message.message_id, f"{Icons.ERROR} Solicitud no encontrada")
        return

    update_request_status(request_id, "rejected")
    edit_safe(client_id, call.message.message_id, f"{Icons.ERROR} Cancelaste el servicio ❌")

    worker_id = request.get("worker_chat_id")
    if worker_id:
        send_safe(worker_id, f"{Icons.ERROR} El cliente rechazó el servicio. No se realizará.")

# ===================== HANDLER: TRABAJADOR RECHAZA =====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("job_reject:"))
def handle_job_reject(call):
    chat_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])

    bot.answer_callback_query(call.id, "Trabajo rechazado")
    edit_safe(chat_id, call.message.message_id,
              f"{Icons.INFO} <b>Trabajo rechazado</b>\nTe seguiremos notificando.")

    try:
        db_execute(
            "INSERT INTO request_rejections (request_id, worker_chat_id, created_at) VALUES (?, ?, ?)",
            (request_id, chat_id, int(time.time())),
            commit=True
        )
        logger.info(f"[JOB_REJECT] Registro de rechazo guardado: request_id={request_id}, worker={chat_id}")
    except Exception as e:
        logger.error(f"[JOB_REJECT] Error guardando rechazo request_id={request_id}, worker={chat_id}: {e}")
