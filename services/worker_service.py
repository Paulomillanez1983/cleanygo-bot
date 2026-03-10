"""
Servicios para gestión de trabajadores (workers)
"""
import math
from config import get_db_connection, logger


def haversine(lat1, lon1, lat2, lon2):
    """
    Calcula distancia en km entre dos coordenadas usando la fórmula de Haversine
    """
    R = 6371  # Radio de la Tierra en km
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = (math.sin(delta_lat / 2) ** 2 + 
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


def find_available_workers(service_id, client_lat, client_lon, hora, max_distance_km=10):
    """
    Busca trabajadores disponibles para un servicio cercanos a una ubicación
    
    Returns: (workers_list, status, extra_info)
    - workers_list: lista de workers (dicts o tuplas)
    - status: 'success', 'no_workers_online', 'workers_far', 'workers_busy', 'error'
    - extra_info: datos adicionales según el status
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Buscar workers activos que ofrezcan el servicio
            cursor.execute("""
                SELECT w.chat_id, w.name, w.lat, w.lon, w.rating, ws.precio
                FROM workers w
                JOIN worker_services ws ON w.chat_id = ws.chat_id
                WHERE ws.service_id = ? AND w.is_active = 1
            """, (service_id,))
            
            workers = cursor.fetchall()
            
            if not workers:
                return [], "no_workers_online", None
            
            # Calcular distancias y filtrar por proximidad
            nearby_workers = []
            busy_workers = []
            
            for worker in workers:
                worker_dict = dict(worker)
                
                # Validar coordenadas
                if worker_dict.get('lat') is None or worker_dict.get('lon') is None:
                    continue
                
                dist = haversine(
                    client_lat, client_lon, 
                    worker_dict['lat'], worker_dict['lon']
                )
                worker_dict['distance'] = dist
                worker_dict['distance_text'] = f"{dist:.1f} km"
                
                # Verificar si está ocupado a esa hora (simplificado)
                # En una versión más compleja, verificarías contra la tabla requests
                cursor.execute("""
                    SELECT 1 FROM requests 
                    WHERE worker_id = ? AND hora = ? AND status IN ('assigned', 'in_progress')
                """, (worker_dict['chat_id'], hora))
                
                is_busy = cursor.fetchone() is not None
                
                if dist <= max_distance_km:
                    if is_busy:
                        busy_workers.append(worker_dict)
                    else:
                        nearby_workers.append(worker_dict)
            
            if not nearby_workers and not busy_workers:
                return [], "workers_far", None
            
            if not nearby_workers and busy_workers:
                return busy_workers, "workers_busy", busy_workers
            
            # Ordenar por distancia
            nearby_workers.sort(key=lambda x: x['distance'])
            
            # Convertir a formato de tupla para compatibilidad con código existente
            result_workers = []
            for w in nearby_workers:
                result_workers.append((
                    w['chat_id'],
                    w['name'],
                    w['lat'],
                    w['lon'],
                    w.get('rating', 0),
                    w.get('precio', 0),
                    w['distance']
                ))
            
            return result_workers, "success", None
            
    except Exception as e:
        logger.error(f"[FIND WORKERS ERROR] {e}")
        return [], "error", str(e)
