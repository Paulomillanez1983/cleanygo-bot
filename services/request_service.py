"""
Módulo para manejo de solicitudes (requests) en la base de datos.
Incluye creación, consulta, actualización y asignación de trabajadores.
Versión final corregida y segura para concurrencia en asignación de trabajos.
"""

import sqlite3
import time
import logging
from config import DB_FILE, logger

# ==================== LOGGING ====================
logger = logging.getLogger(__name__)

# ==================== UTILIDADES ====================
def get_db_connection():
    """Obtiene una conexión nueva a SQLite usando DB_FILE de config."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# ==================== CREAR SOLICITUD ====================
def create_request(client_chat_id: str, service_id: str, hora: str, 
                   lat: float, lon: float, status: str = 'pending'):
    """
    Crea una nueva solicitud y devuelve su ID real.
    Devuelve None si hubo algún error.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO requests (client_chat_id, service_id, hora, lat, lon, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(client_chat_id), service_id, hora, lat, lon, status)
        )
        conn.commit()
        request_id = cursor.lastrowid
        conn.close()

        if not request_id:
            logger.warning(f"[CREATE REQUEST FAIL] ID inválido para cliente={client_chat_id}")
            return None

        logger.info(f"[CREATE REQUEST] ID={request_id} cliente={client_chat_id}, servicio={service_id}")
        return request_id

    except Exception as e:
        logger.error(f"[CREATE REQUEST ERROR] cliente={client_chat_id}, servicio={service_id} -> {e}")
        return None

# ==================== OBTENER SOLICITUD ====================
def get_request(request_id: int):
    """Obtiene una solicitud por ID y devuelve un diccionario"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM requests WHERE id = ?", (request_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"[GET REQUEST ERROR] request_id={request_id} -> {e}")
        return None

# ==================== ACTUALIZAR ESTADO ====================
def update_request_status(request_id: int, status: str, worker_chat_id: str = None):
    """Actualiza el estado de una solicitud"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if worker_chat_id:
            cursor.execute(
                """UPDATE requests SET status = ?, worker_chat_id = ?, accepted_at = ?
                   WHERE id = ?""",
                (status, str(worker_chat_id), int(time.time()), request_id)
            )
        else:
            cursor.execute(
                "UPDATE requests SET status = ? WHERE id = ?",
                (status, request_id)
            )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"[UPDATE REQUEST ERROR] request_id={request_id}, status={status}, worker={worker_chat_id} -> {e}")
        return False

# ==================== ASIGNAR TRABAJADOR ====================
def assign_worker_to_request(request_id: int, worker_chat_id: str):
    """
    Asigna un trabajador a una solicitud SOLO si sigue disponible.
    Devuelve True si se asignó, False si ya fue tomada.
    Ahora es seguro ante concurrencia.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Transacción atómica: solo asigna si status sigue siendo 'pending', 'searching' o 'waiting_acceptance'
        cursor.execute(
            """UPDATE requests
               SET worker_chat_id = ?, status = 'assigned', accepted_at = ?
               WHERE id = ? AND status IN ('pending', 'searching', 'waiting_acceptance')""",
            (str(worker_chat_id), int(time.time()), request_id)
        )

        conn.commit()
        rows_updated = cursor.rowcount
        conn.close()

        if rows_updated > 0:
            logger.info(f"[ASSIGN REQUEST] request_id={request_id} asignada a worker={worker_chat_id}")
            return True
        else:
            logger.warning(f"[ASSIGN REQUEST FAIL] request_id={request_id} worker={worker_chat_id} status no disponible")
            return False

    except Exception as e:
        logger.error(f"[ASSIGN REQUEST ERROR] request_id={request_id}, worker={worker_chat_id} -> {e}")
        return False

# ==================== FUNCIÓN SEGURA PARA CALLBACKS ====================
def assign_worker_to_request_safe(request_id: int, worker_chat_id: str):
    """
    Versión segura para usar en callbacks de Telegram.
    Devuelve True si se pudo asignar, False si ya fue tomado.
    """
    return assign_worker_to_request(request_id, worker_chat_id)
