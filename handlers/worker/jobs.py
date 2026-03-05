"""
Handlers para gestión de trabajos/asignaciones para profesionales.
Incluye aceptación/rechazo del cliente según el precio, búsqueda de trabajadores disponibles y actualización de sesión.
"""

from telebot import types
from config import bot, logger, DB_FILE
from models.user_state import set_state, UserState
from utils.icons import Icons
from services.request_service import get_request, update_request_status
from handlers.common import send_safe, edit_safe
from database import db_execute
import time
import sqlite3
from threading import Thread

# ===================== PRECIOS DE SERVICIOS (nombres por default) =====================
SERVICES_PRICES = {
    "ninaera": {"name": "Niñera", "price": 1500},
    "limpieza": {"name": "Limpieza", "price": 2000},
    "plomeria": {"name": "Plomería", "price": 2500},
}

# ===================== TABLA DE RECHAZOS =====================
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

# ===================== FUNCIONES AUXILIARES =====================
def find_available_workers(service_id, lat, lon, hora):
    """
    Retorna lista de trabajadores disponibles [(chat_id, distancia), ...], status y extra info
    """
    workers = db_execute(
        "SELECT chat_id, lat, lon FROM workers WHERE service_id=? AND available=1",
        (service_id,),
        fetch_all=True
    )
    if not workers:
        return [], "no_workers", {}

    # Calcular proximidad aproximada (simplificado)
    available = []
    for w in workers:
        w_chat, w_lat, w_lon = w
        if w_lat and w_lon:
            distance = ((lat - w_lat)**2 + (lon - w_lon)**2)**0.5
            available.append((w_chat, distance))
    available.sort(key=lambda x: x[1])  # más cercano primero
    return available, "ok", {"total": len(available)}

def assign_worker_to_request_safe(request_id, worker_chat_id):
    """
    Asigna worker a request si todavía está disponible.
    Retorna True si tuvo éxito, False si ya fue tomado.
    """
    request = get_request(request_id)
    if not request or request.get("worker_chat_id"):
        return False
    try:
        db_execute(
            "UPDATE requests SET worker_chat_id=?, status='pending' WHERE id=? AND (worker_chat_id IS NULL OR worker_chat_id='')",
            (str(worker_chat_id), request_id),
            commit=True
        )
        return True
    except Exception as e:
        logger.error(f"[ASSIGN_SAFE] Error asignando worker={worker_chat_id} a request_id={request_id}: {e}")
        return False

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

    update_request_status(request_id, "accepted")
    edit_safe(client_id, call.message.message_id, f"{Icons.SUCCESS} Gracias, aceptaste el servicio ✅")

    worker_id = request.get("worker_chat_id") or get_request(request_id).get("worker_chat_id")
    if worker_id:
        send_safe(worker_id, f"{Icons.SUCCESS} El cliente aceptó el servicio. ¡Podés realizarlo!")
        set_state(worker_id, UserState.JOB_IN_PROGRESS, {
            "request_id": request_id,
            "client_id": client_id,
            "service_id": request["service_id"],
            "hora": request["hora"]
        })

        # Botón para iniciar servicio
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton(f"{Icons.PLAY} Iniciar servicio", callback_data=f"start_job:{request_id}"))
        send_safe(worker_id, f"{Icons.INFO} Podés iniciar el servicio ahora.", markup)

        # Integrar botón extra en menú principal
        worker_data = db_execute("SELECT * FROM workers WHERE chat_id=?", (str(worker_id),), fetch_one=True)
        if worker_data:
            try:
                from handlers.worker.main import show_worker_menu
                show_worker_menu(worker_id, worker_data, extra_buttons=[
                    types.InlineKeyboardButton(f"{Icons.PLAY} Iniciar servicio", callback_data=f"start_job:{request_id}")
                ])
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

# ===================== HANDLER: TRABAJADOR INICIA SERVICIO =====================
active_tracking = {}  # chat_id -> {"thread": Thread, "running": bool}

@bot.callback_query_handler(func=lambda c: c.data.startswith("start_job:"))
def handle_start_job(call):
    chat_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])
    request = get_request(request_id)
    if not request:
        edit_safe(chat_id, call.message.message_id, f"{Icons.ERROR} Trabajo no encontrado")
        return

    client_id = request["client_chat_id"]
    edit_safe(chat_id, call.message.message_id, f"{Icons.SUCCESS} Servicio iniciado. Enviando ubicación al cliente...")

    set_state(chat_id, UserState.JOB_IN_PROGRESS, {
        "request_id": request_id,
        "client_id": client_id
    })

    send_safe(client_id, f"{Icons.INFO} El profesional comenzó el servicio. Recibirás ubicación en tiempo real.")

    def location_loop(chat_id, client_id):
        while active_tracking.get(chat_id, {}).get("running"):
            worker_data = db_execute(
                "SELECT lat, lon FROM workers WHERE chat_id=?",
                (str(chat_id),),
                fetch_one=True
            )
            if worker_data and worker_data[0] and worker_data[1]:
                lat, lon = worker_data
                bot.send_location(client_id, latitude=lat, longitude=lon)
            else:
                bot.send_message(client_id, f"{Icons.ERROR} Ubicación no disponible")
            time.sleep(10)

    active_tracking[chat_id] = {"thread": None, "running": True}
    thread = Thread(target=location_loop, args=(chat_id, client_id), daemon=True)
    thread.start()
    active_tracking[chat_id]["thread"] = thread

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton(f"{Icons.STOP} Finalizar servicio", callback_data=f"finish_job:{request_id}"))
    send_safe(chat_id, f"{Icons.INFO} Podés finalizar el servicio cuando termines.", markup)

# ===================== HANDLER: TRABAJADOR FINALIZA SERVICIO =====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("finish_job:"))
def handle_finish_job(call):
    chat_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])
    request = get_request(request_id)
    if not request:
        edit_safe(chat_id, call.message.message_id, f"{Icons.ERROR} Trabajo no encontrado")
        return

    client_id = request["client_chat_id"]

    # Detener hilo de ubicación
    if chat_id in active_tracking:
        active_tracking[chat_id]["running"] = False
        active_tracking.pop(chat_id)

    set_state(chat_id, UserState.SELECTING_ROLE)
    update_request_status(request_id, "completed")

    send_safe(client_id, f"{Icons.SUCCESS} El profesional finalizó el servicio ✅")
    send_safe(chat_id, f"{Icons.SUCCESS} Servicio finalizado. Gracias por tu trabajo ✅")

    # Refrescar menú del trabajador
    worker_data = db_execute("SELECT * FROM workers WHERE chat_id=?", (str(chat_id),), fetch_one=True)
    if worker_data:
        try:
            from handlers.worker.main import show_worker_menu
            show_worker_menu(chat_id, worker_data)
        except Exception as e:
            logger.error(f"[FINISH_JOB] error mostrando menú worker_id={chat_id}: {e}")
