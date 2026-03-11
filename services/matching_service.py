"""
Matching service - Full Auto
Conecta clientes y workers automáticamente
- Notifica workers cercanos
- Maneja aceptación/rechazo automáticamente
- Notifica al cliente con nombre y contacto
- Reintentos automáticos si un worker rechaza
"""

from telebot import types
from config import get_bot, logger
from services.worker_service import find_available_workers, get_worker_info
from services.request_service import assign_worker_to_request_safe, get_request, update_request_status

bot = get_bot()
MAX_WORKERS_NOTIFY = 5


# =====================================================
# NOTIFICAR WORKERS
# =====================================================
def notify_nearby_workers(request_id, service_name, lat, lon, hora, notified_workers=None):
    """
    Busca workers cercanos y les envía la solicitud
    """
    if notified_workers is None:
        notified_workers = []

    if not service_name:
        logger.error(f"[MATCHING] notify_nearby_workers: service_name vacío para request {request_id}")
        return 0

    try:
        workers, status, extra = find_available_workers(service_name, lat, lon, hora)

        if status != "success" or not workers:
            logger.info(f"[MATCHING] Request {request_id} -> {status} | workers={len(workers) if workers else 0}")
            return 0

        notified = 0

        # Filtrar workers ya notificados
        workers_to_notify = [w for w in workers if w[0] not in notified_workers]

        for worker in workers_to_notify[:MAX_WORKERS_NOTIFY]:
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
                bot.send_message(worker_id, text, reply_markup=markup)
                notified += 1
                notified_workers.append(worker_id)
            except Exception as e:
                logger.warning(f"[MATCHING] No se pudo enviar a {worker_id}: {e}")

        logger.info(f"[MATCHING] Request {request_id} enviada a {notified} workers")
        return notified_workers

    except Exception as e:
        logger.error(f"[MATCHING ERROR] {e}")
        return notified_workers


# =====================================================
# WORKER ACEPTA TRABAJO
# =====================================================
def handle_worker_accept(worker_id, request_id):
    """
    Worker acepta un trabajo y notifica al cliente
    """
    try:
        success = assign_worker_to_request_safe(request_id, worker_id)

        if not success:
            bot.send_message(worker_id, "⚠️ Otro trabajador aceptó este trabajo primero.")
            return False

        bot.send_message(worker_id, "✅ Has aceptado el trabajo correctamente.")
        logger.info(f"[MATCHING] Worker {worker_id} aceptó request {request_id}")

        # Notificar cliente
        _notify_client(request_id, worker_id=worker_id, accepted=True)

        # Marcar request como 'assigned'
        update_request_status(request_id, "assigned")

        return True

    except Exception as e:
        logger.error(f"[MATCHING ERROR] handle_worker_accept: {e}")
        return False


# =====================================================
# WORKER RECHAZA
# =====================================================
def handle_worker_reject(worker_id, request_id):
    """
    Worker rechaza un trabajo y se busca otro automáticamente
    """
    try:
        bot.send_message(worker_id, "❌ Solicitud rechazada.")
        logger.info(f"[MATCHING] Worker {worker_id} rechazó request {request_id}")

        # Notificar cliente de rechazo temporal
        _notify_client(request_id, worker_id=worker_id, accepted=False)

        # Buscar siguiente worker automáticamente
        request = get_request(request_id)
        if request and request.get("status") == "pending":
            service_name = request.get("service_name")
            lat = request.get("lat")
            lon = request.get("lon")
            hora = request.get("hora")
            notified_workers = request.get("notified_workers") or []
            notified_workers = notify_nearby_workers(
                request_id,
                service_name,
                lat,
                lon,
                hora,
                notified_workers=notified_workers
            )
            # Guardar lista de trabajadores notificados para no repetir
            update_request_status(request_id, "pending", extra={"notified_workers": notified_workers})

        return True
    except Exception as e:
        logger.error(f"[MATCHING ERROR] handle_worker_reject: {e}")
        return False


# =====================================================
# NOTIFICAR CLIENTE
# =====================================================
def _notify_client(request_id, worker_id=None, accepted=True):
    """
    Envía mensaje al cliente sobre la aceptación/rechazo de un worker
    """
    try:
        request = get_request(request_id)
        if not request:
            logger.warning(f"[CLIENT NOTIFY] Request {request_id} no encontrada")
            return

        client_id = request.get("client_id")
        if not client_id:
            logger.warning(f"[CLIENT NOTIFY] Request {request_id} sin client_id")
            return

        if accepted and worker_id:
            worker_info = get_worker_info(worker_id)
            worker_name = worker_info.get("name", "Un profesional")
            worker_phone = worker_info.get("phone", "sin contacto disponible")

            text = (
                f"✅ {worker_name} aceptó tu solicitud.\n"
                f"📱 Contacto: {worker_phone}\n"
                f"Pronto se pondrá en contacto contigo."
            )
        else:
            text = f"❌ Un profesional rechazó tu solicitud. Buscando otro disponible..."

        bot.send_message(client_id, text)

    except Exception as e:
        logger.error(f"[CLIENT NOTIFY ERROR] request {request_id}: {e}")
