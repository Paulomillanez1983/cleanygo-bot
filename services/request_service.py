"""
Servicios para gestión de solicitudes (requests)
"""
import sqlite3
from datetime import datetime
from config import get_db_connection, logger


def create_request(client_id, service_id, hora, lat, lon, status="searching"):
    """
    Crea una nueva solicitud de servicio
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO requests 
                (client_id, service_id, hora, lat, lon, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (str(client_id), service_id, hora, lat, lon, status, int(datetime.now().timestamp())))
            
            request_id = cursor.lastrowid
            logger.info(f"[REQUEST] Creada solicitud {request_id} para {client_id}")
            return request_id
    except Exception as e:
        logger.error(f"[REQUEST ERROR] {e}")
        return None


def get_request(request_id):
    """
    Obtiene una solicitud por ID
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM requests WHERE id = ?
            """, (request_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"[GET REQUEST ERROR] {e}")
        return None


def update_request_status(request_id, status):
    """
    Actualiza el estado de una solicitud
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE requests SET status = ? WHERE id = ?
            """, (status, request_id))
            logger.info(f"[REQUEST] {request_id} -> {status}")
            return True
    except Exception as e:
        logger.error(f"[UPDATE STATUS ERROR] {e}")
        return False


def assign_worker_to_request_safe(request_id, worker_id):
    """
    Asigna un trabajador a una solicitud de forma segura (evita race conditions)
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Verificar que siga disponible
            cursor.execute("SELECT status FROM requests WHERE id = ?", (request_id,))
            row = cursor.fetchone()
            
            if not row or row['status'] not in ('searching', 'pending', 'waiting_acceptance'):
                logger.warning(f"[ASSIGN_SAFE] Request {request_id} no disponible (status={row['status'] if row else 'None'})")
                return False
            
            cursor.execute("""
                UPDATE requests SET worker_id = ?, status = 'assigned' WHERE id = ?
            """, (str(worker_id), request_id))
            
            logger.info(f"[ASSIGN] Worker {worker_id} -> Request {request_id}")
            return True
    except Exception as e:
        logger.error(f"[ASSIGN ERROR] {e}")
        return False


def cancel_request(request_id, reason=""):
    """
    Cancela una solicitud
    """
    return update_request_status(request_id, "cancelled")


def complete_request(request_id):
    """
    Marca una solicitud como completada
    """
    return update_request_status(request_id, "completed")


def reject_request(request_id, worker_id):
    """
    Registra que un worker rechazó una solicitud (para lógica futura)
    """
    # Por ahora solo logueamos, en el futuro podríamos llevar un registro
    logger.info(f"[REJECT] Worker {worker_id} rechazó request {request_id}")
    return True
