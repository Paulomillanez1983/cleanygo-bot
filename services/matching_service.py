from config import logger
from services.worker_service import find_available_workers
from config import get_bot

bot = get_bot()

def notify_nearby_workers(request_id, lat, lon, service_id):

    workers, status, extra = find_available_workers(
        service_id,
        lat,
        lon,
        None
    )

    if status != "success":
        logger.info(f"[MATCHING] No workers encontrados: {status}")
        return 0

    notified = 0

    for worker in workers[:5]:

        worker_id = worker[0]

        text = f"""
🔔 Nueva solicitud disponible

Servicio: {service_id}
Distancia: {worker[6]:.1f} km

¿Aceptar trabajo?
"""

        bot.send_message(worker_id, text)

        notified += 1

    logger.info(f"[MATCHING] Workers notificados: {notified}")

    return notified
