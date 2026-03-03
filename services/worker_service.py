from database import db_execute
from utils.location import haversine
from utils.time_utils import parse_time_string, is_time_overlap
from config import logger

def find_available_workers(service_id: str, lat: float, lon: float, 
                          hora_solicitada: str, radius_km: float = 10.0):
    """
    Encuentra trabajadores disponibles considerando:
    - Estado online (disponible = 1)
    - Servicio específico
    - Ubicación dentro del radio
    - Disponibilidad horaria (no solapamiento con trabajos existentes)
    """
    
    # 1. Obtener trabajadores online con el servicio
    workers = db_execute(
        """SELECT w.chat_id, w.nombre, w.lat, w.lon, w.rating, ws.precio 
           FROM workers w
           JOIN worker_services ws ON w.chat_id = ws.chat_id
           WHERE ws.service_id = ? AND w.disponible = 1 
           AND w.lat IS NOT NULL AND w.lon IS NOT NULL""",
        (service_id,)
    )
    
    if not workers:
        return [], "no_workers_online"
    
    # 2. Filtrar por distancia
    nearby_workers = []
    for w in workers:
        dist = haversine(lat, lon, w[2], w[3])
        if dist <= radius_km:
            nearby_workers.append((*w, dist))
    
    if not nearby_workers:
        return [], "workers_far"
    
    # 3. Verificar disponibilidad horaria
    available_workers = []
    busy_workers = []
    
    for worker in nearby_workers:
        worker_id = worker[0]
        
        # Buscar trabajos asignados del worker para hoy
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
    available_workers.sort(key=lambda x: x[6])
    return available_workers, "success"

def get_worker_by_id(chat_id: str):
    """Obtiene datos de un trabajador por su chat_id"""
    return db_execute(
        "SELECT * FROM workers WHERE chat_id = ?", 
        (str(chat_id),), 
        fetch_one=True
    )

def update_worker_location(chat_id: str, lat: float, lon: float):
    """Actualiza ubicación del trabajador"""
    import time
    return db_execute(
        "UPDATE workers SET lat = ?, lon = ?, last_update = ? WHERE chat_id = ?",
        (lat, lon, int(time.time()), str(chat_id)),
        commit=True
    )

def set_worker_availability(chat_id: str, disponible: bool):
    """Cambia estado online/offline del trabajador"""
    return db_execute(
        "UPDATE workers SET disponible = ? WHERE chat_id = ?",
        (1 if disponible else 0, str(chat_id)),
        commit=True
    )
