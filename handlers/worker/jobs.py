"""
Handlers para gestión de trabajos/asignaciones para profesionales.
VERSIÓN FINAL ESTABLE
"""

from telebot import types
from config import bot, logger, get_db_connection
from models.user_state import set_state, UserState
from utils.icons import Icons
from utils.telegram_safe import send_safe, edit_safe

from requests_db import (
    get_request,
    update_request_status,
    assign_worker_to_request,
    reject_request,
    complete_request
)

import time
from threading import Thread


# ===================== PRECIOS =====================

SERVICES_PRICES = {
    "niñera": {"name": "Niñera", "price": 1500},
    "limpieza": {"name": "Limpieza", "price": 2000},
    "plomeria": {"name": "Plomería", "price": 2500},
}


# ===================== BUSCAR WORKERS =====================

def find_available_workers(service_id, lat, lon, hora):

    try:

        if lat is None or lon is None:
            return [], "invalid_location", {}

        with get_db_connection() as conn:

            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT w.user_id, w.lat, w.lon
                FROM workers w
                JOIN worker_services ws ON w.user_id = ws.user_id
                WHERE ws.service_id = ?
                AND w.is_active = 1
                AND (w.current_request_id IS NULL OR w.current_request_id = 0)
                """,
                (service_id,)
            )

            workers = cursor.fetchall()

        if not workers:
            return [], "no_workers", {}

        available = []

        for w in workers:

            w_id = w["user_id"]
            w_lat = w["lat"]
            w_lon = w["lon"]

            if w_lat is None or w_lon is None:
                continue

            distance = ((lat - w_lat) ** 2 + (lon - w_lon) ** 2) ** 0.5

            available.append((w_id, distance))

        available.sort(key=lambda x: x[1])

        return available, "ok", {"total": len(available)}

    except Exception as e:

        logger.error(f"[FIND_WORKERS ERROR]: {e}")
        return [], "error", {}


# ===================== ASIGNACIÓN SEGURA =====================

def assign_worker_to_request_safe(request_id, worker_id):

    try:

        worker_id = int(worker_id)

        result = assign_worker_to_request(request_id, worker_id)

        if result:
            logger.info(f"[ASSIGN_SAFE] request={request_id} worker={worker_id}")
            return True

        logger.warning(f"[ASSIGN_SAFE FAIL] request={request_id}")
        return False

    except Exception as e:

        logger.error(f"[ASSIGN_SAFE ERROR]: {e}")
        return False


# ===================== WORKER ACEPTA =====================

@bot.callback_query_handler(func=lambda c: c.data.startswith("job_accept:"))
def handle_job_accept(call):

    worker_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])

    logger.info(f"[JOB_ACCEPT] worker={worker_id} request={request_id}")

    request = get_request(request_id)

    if not request:

        bot.answer_callback_query(call.id, "❌ Este trabajo no existe")

        edit_safe(
            bot,
            worker_id,
            call.message.message_id,
            f"{Icons.ERROR} <b>Trabajo no disponible</b>"
        )

        return

    if request["status"] not in ("pending", "searching", "waiting_acceptance"):

        bot.answer_callback_query(call.id, "❌ Este trabajo ya fue tomado")

        edit_safe(
            bot,
            worker_id,
            call.message.message_id,
            f"{Icons.ERROR} <b>Trabajo no disponible</b>"
        )

        return

    success = assign_worker_to_request_safe(request_id, worker_id)

    if not success:

        bot.answer_callback_query(call.id, "❌ No se pudo asignar")

        edit_safe(
            bot,
            worker_id,
            call.message.message_id,
            f"{Icons.ERROR} <b>Trabajo no disponible</b>"
        )

        return

    set_state(worker_id, UserState.JOB_IN_PROGRESS, {
        "request_id": request_id,
        "client_id": request.get("client_id") or request.get("client_chat_id"),
        "service_id": request.get("service_id"),
        "hora": request.get("request_time") or request.get("hora")
    })

    bot.answer_callback_query(call.id, "✅ Trabajo asignado")

    edit_safe(
        bot,
        worker_id,
        call.message.message_id,
        f"""
{Icons.SUCCESS} <b>¡Trabajo confirmado!</b>

{Icons.INFO} Contactá al cliente para coordinar
{Icons.PHONE} Cliente: {request.get('client_id') or request.get('client_chat_id')}
"""
    )

    client_id = request.get("client_id") or request.get("client_chat_id")

    if not client_id:
        return

    service_id = request.get("service_id")

    try:

        with get_db_connection() as conn:

            cursor = conn.cursor()

            cursor.execute(
                "SELECT precio FROM worker_services WHERE user_id=? AND service_id=?",
                (worker_id, service_id)
            )

            row = cursor.fetchone()

            price = row["precio"] if row else None

    except Exception as e:

        logger.error(f"[PRICE ERROR]: {e}")
        price = None

    if price is None:
        price = SERVICES_PRICES.get(service_id, {}).get("price", 0)

    service_name = SERVICES_PRICES.get(service_id, {"name": service_id})["name"]

    text = f"""
{Icons.PARTY} <b>¡Encontramos tu profesional!</b>

Servicio: {service_name}
{Icons.MONEY} Precio: ${price}
"""

    markup = types.InlineKeyboardMarkup()

    markup.add(
        types.InlineKeyboardButton(
            f"{Icons.SUCCESS} Acepto",
            callback_data=f"client_accept:{request_id}"
        ),
        types.InlineKeyboardButton(
            f"{Icons.ERROR} No acepto",
            callback_data=f"client_reject:{request_id}"
        )
    )

    send_safe(bot, client_id, text, reply_markup=markup)


# ===================== CLIENTE ACEPTA =====================

@bot.callback_query_handler(func=lambda c: c.data.startswith("client_accept:"))
def handle_client_accept(call):

    client_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])

    request = get_request(request_id)

    if not request:

        edit_safe(
            bot,
            client_id,
            call.message.message_id,
            f"{Icons.ERROR} Solicitud no encontrada"
        )

        return

    update_request_status(request_id, "accepted")

    edit_safe(
        bot,
        client_id,
        call.message.message_id,
        f"{Icons.SUCCESS} Servicio aceptado"
    )

    worker_id = request.get("worker_id") or request.get("worker_chat_id")

    if not worker_id:
        return

    send_safe(bot, worker_id, f"{Icons.SUCCESS} El cliente aceptó el servicio")

    markup = types.InlineKeyboardMarkup()

    markup.add(
        types.InlineKeyboardButton(
            f"{Icons.PLAY} Iniciar servicio",
            callback_data=f"start_job:{request_id}"
        )
    )

    send_safe(bot, worker_id, "Podés iniciar el servicio", reply_markup=markup)


# ===================== CLIENTE RECHAZA =====================

@bot.callback_query_handler(func=lambda c: c.data.startswith("client_reject:"))
def handle_client_reject(call):

    client_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])

    from requests_db import cancel_request

    cancel_request(request_id, reason="Cliente rechazó")

    edit_safe(
        bot,
        client_id,
        call.message.message_id,
        f"{Icons.ERROR} Cancelaste el servicio"
    )


# ===================== WORKER RECHAZA =====================

@bot.callback_query_handler(func=lambda c: c.data.startswith("job_reject:"))
def handle_job_reject(call):

    worker_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])

    bot.answer_callback_query(call.id, "Trabajo rechazado")

    edit_safe(
        bot,
        worker_id,
        call.message.message_id,
        f"{Icons.INFO} Trabajo rechazado"
    )

    reject_request(request_id, worker_id)


# ===================== TRACKING =====================

active_tracking = {}


@bot.callback_query_handler(func=lambda c: c.data.startswith("start_job:"))
def handle_start_job(call):

    worker_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])

    request = get_request(request_id)

    if not request:
        return

    client_id = request.get("client_id") or request.get("client_chat_id")

    update_request_status(request_id, "in_progress")

    send_safe(bot, client_id, "El profesional comenzó el servicio")

    def location_loop():

        while active_tracking.get(worker_id, {}).get("running"):

            try:

                with get_db_connection() as conn:

                    cursor = conn.cursor()

                    cursor.execute(
                        "SELECT lat,lon FROM workers WHERE user_id=?",
                        (worker_id,)
                    )

                    data = cursor.fetchone()

                if data and data["lat"] and data["lon"]:

                    bot.send_location(
                        client_id,
                        latitude=data["lat"],
                        longitude=data["lon"]
                    )

            except Exception as e:

                logger.error(f"[LOCATION ERROR] {e}")

            time.sleep(10)

    active_tracking[worker_id] = {"running": True}

    Thread(target=location_loop, daemon=True).start()


# ===================== FINALIZAR =====================

@bot.callback_query_handler(func=lambda c: c.data.startswith("finish_job:"))
def handle_finish_job(call):

    worker_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])

    request = get_request(request_id)

    if not request:
        return

    client_id = request.get("client_id") or request.get("client_chat_id")

    if worker_id in active_tracking:
        active_tracking[worker_id]["running"] = False

    complete_request(request_id)

    send_safe(bot, client_id, "Servicio finalizado")

    send_safe(bot, worker_id, "Gracias por tu trabajo")

    set_state(worker_id, UserState.SELECTING_ROLE)
