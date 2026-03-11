"""
Matching service
Encuentra workers cercanos y envía solicitudes
"""

from telebot import types

from config import inject_bot, logger
from services.worker_service import find_available_workers
from services.request_service import assign_worker_to_request_safe

bot = inject_bot()

MAX_WORKERS_NOTIFY = 5


# =====================================================
# NOTIFICAR WORKERS
# =====================================================

def notify_nearby_workers(request_id, service_name, lat, lon, hora):
    """
    Busca workers cercanos y les envía la solicitud
    """

    try:

        workers, status, extra = find_available_workers(
            service_name,
            lat,
            lon,
            hora
        )

        if status != "success":

            logger.info(f"[MATCHING] Request {request_id} -> {status}")

            return 0

        notified = 0

        for worker in workers[:MAX_WORKERS_NOTIFY]:

            worker_id = worker[0]
            worker_name = worker[1]
            distance = worker[6]

            markup = types.InlineKeyboardMarkup()

            markup.add(
                types.InlineKeyboardButton(
                    "✅ Aceptar trabajo",
                    callback_data=f"worker_accept:{request_id}"
                ),
                types.InlineKeyboardButton(
                    "❌ Rechazar",
                    callback_data=f"worker_reject:{request_id}"
                )
            )

            text = f"""
🚨 Nueva solicitud disponible

🛠 Servicio: {service_name}
📍 Distancia: {distance:.1f} km
🕒 Hora: {hora}

¿Aceptar trabajo?
"""

            try:

                bot.send_message(
                    worker_id,
                    text,
                    reply_markup=markup
                )

                notified += 1

            except Exception as e:

                logger.warning(
                    f"[MATCHING] No se pudo enviar a {worker_id}: {e}"
                )

        logger.info(
            f"[MATCHING] Request {request_id} enviada a {notified} workers"
        )

        return notified

    except Exception as e:

        logger.error(f"[MATCHING ERROR] {e}")

        return 0


# =====================================================
# WORKER ACEPTA TRABAJO
# =====================================================

def handle_worker_accept(worker_id, request_id):
    """
    Worker intenta aceptar un trabajo
    """

    success = assign_worker_to_request_safe(
        request_id,
        worker_id
    )

    if not success:

        bot.send_message(
            worker_id,
            "⚠️ Otro trabajador aceptó este trabajo primero."
        )

        return False

    bot.send_message(
        worker_id,
        "✅ Has aceptado el trabajo correctamente."
    )

    logger.info(
        f"[MATCHING] Worker {worker_id} aceptó request {request_id}"
    )

    return True


# =====================================================
# WORKER RECHAZA
# =====================================================

def handle_worker_reject(worker_id, request_id):

    logger.info(
        f"[MATCHING] Worker {worker_id} rechazó request {request_id}"
    )

    bot.send_message(
        worker_id,
        "Solicitud rechazada."
    )

    return True
