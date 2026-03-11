"""
Handlers para gestión de trabajos/asignaciones para profesionales.
VERSIÓN FINAL CORREGIDA PARA CLEANYGO
"""

from telebot import types
from config import logger, get_db_connection, set_state
from models.states import UserState
from utils.icons import Icons
from utils.telegram_safe import send_safe, edit_safe
from services.request_service import (
    get_request,
    update_request_status,
    assign_worker_to_request_safe
)

import time
from threading import Thread


active_tracking = {}

# ===================== PRECIOS =====================

SERVICES_PRICES = {
    "niñera": {"name": "Niñera", "price": 15000},
    "cuidado": {"name": "Cuidado de personas", "price": 18000},
    "ac_inst": {"name": "Instalación A/C", "price": 25000},
    "ac_tech": {"name": "Visita técnica A/C", "price": 20000},
}


# ===================================================
# REGISTER
# ===================================================

def register_handlers(bot):

    # ===================== WORKER ACEPTA =====================

    @bot.callback_query_handler(func=lambda c: c.data.startswith("job_accept:"))
    def handle_job_accept(call):

        worker_id = call.message.chat.id
        request_id = int(call.data.split(":")[1])

        logger.info(f"[JOB_ACCEPT] worker={worker_id} request={request_id}")

        request = get_request(request_id)

        if not request:
            bot.answer_callback_query(call.id, "❌ Este trabajo no existe")
            return

        request_status = request.get("status", "")

        if request_status not in ("pending", "searching", "waiting_acceptance"):

            bot.answer_callback_query(call.id, "❌ Este trabajo ya fue tomado")

            edit_safe(
                worker_id,
                call.message.message_id,
                f"{Icons.ERROR} <b>Trabajo no disponible</b>"
            )
            return

        success = assign_worker_to_request_safe(request_id, worker_id)

        if not success:
            bot.answer_callback_query(call.id, "❌ No se pudo asignar")
            return

        set_state(worker_id, UserState.JOB_IN_PROGRESS.value, {
            "request_id": request_id,
            "client_id": request.get("client_id") or request.get("client_chat_id"),
            "service_id": request.get("service_id"),
            "hora": request.get("hora")
        })

        bot.answer_callback_query(call.id, "✅ Trabajo asignado")

        edit_safe(
            worker_id,
            call.message.message_id,
            f"""
{Icons.SUCCESS} <b>¡Trabajo confirmado!</b>

{Icons.INFO} Contactá al cliente
{Icons.PHONE} Cliente: {request.get('client_id') or request.get('client_chat_id')}
"""
        )

        client_id = request.get("client_id") or request.get("client_chat_id")

        if not client_id:
            return

        service_id = request.get("service_id")

        # Obtener precio del worker
        try:
            with get_db_connection() as conn:

                cursor = conn.cursor()

                cursor.execute(
                    "SELECT precio FROM worker_services WHERE chat_id=? AND service_id=?",
                    (str(worker_id), service_id)
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

        send_safe(client_id, text, reply_markup=markup)


    # ===================== CLIENTE ACEPTA =====================

    @bot.callback_query_handler(func=lambda c: c.data.startswith("client_accept:"))
    def handle_client_accept(call):

        client_id = call.message.chat.id
        request_id = int(call.data.split(":")[1])

        request = get_request(request_id)

        if not request:
            return

        update_request_status(request_id, "accepted")

        edit_safe(
            client_id,
            call.message.message_id,
            f"{Icons.SUCCESS} Servicio aceptado"
        )

        worker_id = request.get("worker_id") or request.get("worker_chat_id")

        if not worker_id:
            return

        send_safe(worker_id, f"{Icons.SUCCESS} El cliente aceptó el servicio")

        markup = types.InlineKeyboardMarkup()

        markup.add(
            types.InlineKeyboardButton(
                f"{Icons.PLAY} Iniciar servicio",
                callback_data=f"start_job:{request_id}"
            )
        )

        send_safe(worker_id, "Podés iniciar el servicio", reply_markup=markup)


    # ===================== START JOB =====================

    @bot.callback_query_handler(func=lambda c: c.data.startswith("start_job:"))
    def handle_start_job(call):

        worker_id = call.message.chat.id
        request_id = int(call.data.split(":")[1])

        request = get_request(request_id)

        if not request:
            return

        client_id = request.get("client_id") or request.get("client_chat_id")

        update_request_status(request_id, "in_progress")

        send_safe(client_id, "El profesional comenzó el servicio")

        def location_loop():

            while active_tracking.get(worker_id, {}).get("running"):

                try:

                    with get_db_connection() as conn:

                        cursor = conn.cursor()

                        cursor.execute(
                            "SELECT lat, lon FROM workers WHERE chat_id=?",
                            (str(worker_id),)
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

        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                f"{Icons.CHECK} Finalizar servicio",
                callback_data=f"finish_job:{request_id}"
            )
        )

        send_safe(
            worker_id,
            "Servicio en curso. Cuando termines, presioná finalizar.",
            reply_markup=markup
        )


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
            del active_tracking[worker_id]

        update_request_status(request_id, "completed")

        send_safe(client_id, "✅ Servicio finalizado")

        send_safe(worker_id, "🎉 Gracias por tu trabajo")

        set_state(worker_id, UserState.SELECTING_ROLE.value)
