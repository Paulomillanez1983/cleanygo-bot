"""
Handlers para gestión de trabajos/asignaciones para profesionales.
VERSIÓN CON PRECIO PERSONALIZADO Y TRACKING EN TIEMPO REAL
"""

from telebot import types
from config import logger, get_db_connection, set_state, get_data, clear_state
from models.states import UserState, get_state
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

# ===================== PRECIOS (Fallback si no ingresa el worker) =====================

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

        # Asignar worker
        success = assign_worker_to_request_safe(request_id, worker_id)

        if not success:
            bot.answer_callback_query(call.id, "❌ No se pudo asignar")
            return

        # Guardar en estado que está esperando ingresar precio
        set_state(worker_id, UserState.WORKER_ENTERING_PRICE.value, {
            "request_id": request_id,
            "client_id": request.get("client_id") or request.get("client_chat_id"),
            "service_id": request.get("service_id"),
            "hora": request.get("hora"),
            "message_id": call.message.message_id
        })

        bot.answer_callback_query(call.id, "💰 Ingresá el precio del servicio")

        # Pedir al worker que ingrese el precio
        service_id = request.get("service_id")
        default_price = SERVICES_PRICES.get(service_id, {}).get("price", 0)
        service_name = SERVICES_PRICES.get(service_id, {"name": service_id})["name"]

        edit_safe(
            worker_id,
            call.message.message_id,
            f"""
{Icons.MONEY} <b>¿Cuál es tu precio para este servicio?</b>

Servicio: {service_name}
Hora: {request.get('hora')}

💡 Precio sugerido: ${default_price}

Escribí el monto en números (ej: 18000)
"""
        )


    # ===================== WORKER INGRESA PRECIO =====================

    @bot.message_handler(func=lambda m: get_state(m.chat.id) == UserState.WORKER_ENTERING_PRICE.value)
    def handle_worker_price_input(message):

        worker_id = message.chat.id
        
        # Obtener datos del estado
        state_data = get_data(worker_id)
        
        if not state_data:
            return

        request_id = state_data.get("request_id")
        client_id = state_data.get("client_id")
        service_id = state_data.get("service_id")
        hora = state_data.get("hora")

        # Validar que sea un número
        try:
            price = int(message.text.strip())
            if price <= 0:
                raise ValueError
        except ValueError:
            send_safe(worker_id, f"{Icons.ERROR} Por favor ingresá un número válido (ej: 18000)")
            return

        # Guardar precio en la solicitud
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE requests SET worker_price = ? WHERE id = ?",
                    (price, request_id)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"[PRICE SAVE ERROR]: {e}")
            send_safe(worker_id, f"{Icons.ERROR} Error guardando el precio. Intentá de nuevo.")
            return

        # Cambiar estado del worker
        set_state(worker_id, UserState.JOB_IN_PROGRESS.value, {
            "request_id": request_id,
            "client_id": client_id,
            "service_id": service_id,
            "hora": hora,
            "price": price
        })

        # Actualizar estado de la solicitud
        update_request_status(request_id, "waiting_client_acceptance")

        service_name = SERVICES_PRICES.get(service_id, {"name": service_id})["name"]

        # Confirmar al worker
        send_safe(
            worker_id,
            f"""
{Icons.SUCCESS} <b>Precio enviado: ${price}</b>

Esperando que el cliente acepte...
"""
        )

        # Notificar al cliente con el precio propuesto
        text = f"""
{Icons.PARTY} <b>¡Encontramos tu profesional!</b>

Servicio: {service_name}
{Icons.CLOCK} Hora: {hora}
{Icons.MONEY} <b>Precio: ${price}</b>

¿Aceptás este presupuesto?
"""

        markup = types.InlineKeyboardMarkup()

        markup.add(
            types.InlineKeyboardButton(
                f"{Icons.SUCCESS} Sí, acepto",
                callback_data=f"client_accept_price:{request_id}"
            ),
            types.InlineKeyboardButton(
                f"{Icons.ERROR} No, rechazo",
                callback_data=f"client_reject_price:{request_id}"
            )
        )

        send_safe(client_id, text, reply_markup=markup)


    # ===================== CLIENTE ACEPTA PRECIO =====================

    @bot.callback_query_handler(func=lambda c: c.data.startswith("client_accept_price:"))
    def handle_client_accept_price(call):

        client_id = call.message.chat.id
        request_id = int(call.data.split(":")[1])

        request = get_request(request_id)

        if not request:
            return

        # Obtener datos
        worker_id = request.get("worker_id") or request.get("worker_chat_id")
        price = request.get("worker_price", 0)
        service_id = request.get("service_id")
        service_name = SERVICES_PRICES.get(service_id, {"name": service_id})["name"]

        update_request_status(request_id, "accepted")

        edit_safe(
            client_id,
            call.message.message_id,
            f"""
{Icons.SUCCESS} <b>¡Servicio confirmado!</b>

Servicio: {service_name}
{Icons.MONEY} Precio acordado: ${price}

El profesional está en camino. Podés ver su ubicación en tiempo real 📍
"""
        )

        if not worker_id:
            return

        # Notificar al worker
        send_safe(
            worker_id,
            f"""
{Icons.SUCCESS} <b>¡El cliente aceptó!</b>

Precio: ${price}
{Icons.ROCKET} Podés iniciar el servicio
"""
        )

        markup = types.InlineKeyboardMarkup()

        markup.add(
            types.InlineKeyboardButton(
                f"{Icons.PLAY} Iniciar servicio y compartir ubicación",
                callback_data=f"start_job_tracking:{request_id}"
            )
        )

        send_safe(worker_id, "Presioná cuando estés en camino:", reply_markup=markup)


    # ===================== CLIENTE RECHAZA PRECIO =====================

    @bot.callback_query_handler(func=lambda c: c.data.startswith("client_reject_price:"))
    def handle_client_reject_price(call):

        client_id = call.message.chat.id
        request_id = int(call.data.split(":")[1])

        request = get_request(request_id)

        if not request:
            return

        worker_id = request.get("worker_id") or request.get("worker_chat_id")

        update_request_status(request_id, "rejected")

        edit_safe(
            client_id,
            call.message.message_id,
            f"{Icons.ERROR} Solicitud cancelada. Buscando otro profesional..."
        )

        if worker_id:
            send_safe(worker_id, f"{Icons.ERROR} El cliente no aceptó el precio. Buscando otros trabajos...")
            clear_state(worker_id)

        # TODO: Volver a buscar otro worker o cancelar solicitud


    # ===================== START JOB CON TRACKING =====================

    @bot.callback_query_handler(func=lambda c: c.data.startswith("start_job_tracking:"))
    def handle_start_job_tracking(call):

        worker_id = call.message.chat.id
        request_id = int(call.data.split(":")[1])

        request = get_request(request_id)

        if not request:
            return

        client_id = request.get("client_id") or request.get("client_chat_id")

        update_request_status(request_id, "in_progress")

        # Notificar al cliente que el profesional inició
        send_safe(
            client_id,
            f"""
{Icons.SUCCESS} <b>¡El profesional está en camino!</b>

📍 Recibirás su ubicación actualizada cada 10 segundos.
"""
        )

        # Enviar ubicación inicial
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
            logger.error(f"[INITIAL LOCATION ERROR] {e}")

        # Iniciar tracking en tiempo real
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

        # Editar mensaje del worker
        edit_safe(
            worker_id,
            call.message.message_id,
            f"""
{Icons.SUCCESS} <b>Servicio iniciado</b>

📍 Estás compartiendo tu ubicación con el cliente.
Presioná finalizar cuando termines.
"""
        )

        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                f"{Icons.CHECK} Finalizar servicio",
                callback_data=f"finish_job:{request_id}"
            )
        )

        send_safe(
            worker_id,
            "Cuando llegues y completes el trabajo:",
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
        price = request.get("worker_price", 0)

        if worker_id in active_tracking:
            active_tracking[worker_id]["running"] = False
            del active_tracking[worker_id]

        update_request_status(request_id, "completed")

        # Notificar al cliente
        send_safe(
            client_id,
            f"""
{Icons.CHECK} <b>Servicio finalizado</b>

{Icons.MONEY} Monto a pagar: ${price}

¡Gracias por usar CleanYGo!
"""
        )

        # Notificar al worker
        send_safe(
            worker_id,
            f"""
{Icons.PARTY} <b>¡Trabajo completado!</b>

{Icons.MONEY} Cobro: ${price}
{Icons.STAR} ¡Excelente trabajo!
"""
        )

        clear_state(worker_id)
