from database import db_execute
from utils.location import haversine
from utils.time_utils import parse_time_string, is_time_overlap
from config import logger
import time

# ==================== ENCONTRAR TRABAJADORES DISPONIBLES ====================
def find_available_workers(service_id: str, lat: float, lon: float, 
                           hora_solicitada: str, radius_km: float = 10.0):
    """
    Encuentra trabajadores disponibles considerando:
    - Estado online (disponible = 1)
    - Servicio específico
    - Ubicación dentro del radio
    - Disponibilidad horaria (no solapamiento con trabajos existentes)
    Devuelve siempre (available_workers, status, extra)
    """
    try:
        # 1. Obtener trabajadores online con el servicio
        workers = db_execute(
            """SELECT w.chat_id, w.nombre, w.lat, w.lon, w.rating, ws.precio, w.current_request_id
               FROM workers w
               JOIN worker_services ws ON w.chat_id = ws.chat_id
               WHERE ws.service_id = ? AND w.disponible = 1 
               AND w.lat IS NOT NULL AND w.lon IS NOT NULL""",
            (service_id,)
        )

        if not workers:
            return [], "no_workers_online", []

        # 2. Filtrar por distancia
        nearby_workers = []
        for w in workers:
            dist = haversine(lat, lon, w[2], w[3])
            if dist <= radius_km:
                nearby_workers.append((*w, dist))

        if not nearby_workers:
            return [], "workers_far", []

        # 3. Verificar disponibilidad horaria
        available_workers = []
        busy_workers = []

        for worker in nearby_workers:
            worker_id = worker[0]

            busy_jobs = db_execute(
                """SELECT hora FROM requests 
                   WHERE worker_chat_id = ? 
                   AND status IN ('assigned', 'in_progress', 'waiting_acceptance')
                   AND date(created_at, 'unixepoch', 'localtime') = date('now', 'localtime')""",
                (worker_id,)
            )

            is_available = True
            if busy_jobs:
                for job in busy_jobs:
                    busy_hora = job[0]
                    if is_time_overlap(busy_hora, hora_solicitada):
                        is_available = False
                        busy_workers.append(worker)
                        break

            if is_available:
                available_workers.append(worker)

        if not available_workers and busy_workers:
            return [], "workers_busy", busy_workers

        # Ordenar por distancia
        available_workers.sort(key=lambda x: x[7])  # el índice 7 es la distancia
        return available_workers, "success", []

    except Exception as e:
        logger.error(f"[FIND WORKERS ERROR] service_id={service_id}, hora={hora_solicitada} -> {e}")
        return [], "error", []

# ==================== OBTENER TRABAJADOR POR ID ====================
def get_worker_by_id(chat_id: str):
    """Obtiene datos de un trabajador por su chat_id incluyendo request activo"""
    try:
        worker = db_execute(
            "SELECT * FROM workers WHERE chat_id = ?", 
            (str(chat_id),), 
            fetch_one=True
        )
        if worker:
            # Asegurar que tenga request_id activo
            worker["request_id"] = worker.get("current_request_id", 0)
        return worker
    except Exception as e:
        logger.error(f"[GET WORKER ERROR] chat_id={chat_id} -> {e}")
        return None

# ==================== ACTUALIZAR UBICACIÓN ====================
def update_worker_location(chat_id: str, lat: float, lon: float):
    """Actualiza ubicación del trabajador"""
    try:
        return db_execute(
            "UPDATE workers SET lat = ?, lon = ?, last_update = ? WHERE chat_id = ?",
            (lat, lon, int(time.time()), str(chat_id)),
            commit=True
        )
    except Exception as e:
        logger.error(f"[UPDATE LOCATION ERROR] chat_id={chat_id} -> {e}")
        return None

# ==================== CAMBIAR ESTADO ONLINE/OFFLINE ====================
def set_worker_availability(chat_id: str, disponible: bool):
    """Cambia estado online/offline del trabajador"""
    try:
        return db_execute(
            "UPDATE workers SET disponible = ? WHERE chat_id = ?",
            (1 if disponible else 0, str(chat_id)),
            commit=True
        )
    except Exception as e:
        logger.error(f"[SET AVAILABILITY ERROR] chat_id={chat_id}, disponible={disponible} -> {e}")
        return None

# ==================== ASIGNAR REQUEST ACTIVO AL WORKER ====================
def set_worker_current_request(chat_id: str, request_id: int):
    """Guarda el request activo del worker para mostrar botón iniciar servicio"""
    try:
        return db_execute(
            "UPDATE workers SET current_request_id = ? WHERE chat_id = ?",
            (request_id, str(chat_id)),
            commit=True
        )
    except Exception as e:
        logger.error(f"[SET CURRENT REQUEST ERROR] chat_id={chat_id}, request_id={request_id} -> {e}")
        return None
