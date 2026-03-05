from database import db_execute
import time
import logging

logger = logging.getLogger(__name__)

# ==================== CREAR SOLICITUD ====================
def create_request(client_chat_id: str, service_id: str, hora: str, 
                   lat: float, lon: float, status: str = 'searching'):
    """Crea una nueva solicitud y devuelve su ID"""
    try:
        result = db_execute(
            """INSERT INTO requests (client_chat_id, service_id, hora, lat, lon, status) 
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(client_chat_id), service_id, hora, lat, lon, status),
            commit=True
        )
        if result is not None:
            last_id = db_execute("SELECT last_insert_rowid()", fetch_one=True)[0]
            logger.info(f"[CREATE REQUEST] ID={last_id} cliente={client_chat_id}, servicio={service_id}")
            return last_id
        return None
    except Exception as e:
        logger.error(f"[CREATE REQUEST ERROR] cliente={client_chat_id}, servicio={service_id} -> {e}")
        return None


# ==================== OBTENER SOLICITUD ====================
def get_request(request_id: int):
    """Obtiene una solicitud por ID"""
    try:
        req = db_execute(
            "SELECT * FROM requests WHERE id = ?", 
            (request_id,), 
            fetch_one=True
        )
        return req
    except Exception as e:
        logger.error(f"[GET REQUEST ERROR] request_id={request_id} -> {e}")
        return None


# ==================== ACTUALIZAR ESTADO ====================
def update_request_status(request_id: int, status: str, worker_chat_id: str = None):
    """Actualiza estado de una solicitud"""
    try:
        if worker_chat_id:
            return db_execute(
                """UPDATE requests SET status = ?, worker_chat_id = ?, accepted_at = ? 
                   WHERE id = ?""",
                (status, str(worker_chat_id), int(time.time()), request_id),
                commit=True
            )
        return db_execute(
            "UPDATE requests SET status = ? WHERE id = ?",
            (status, request_id),
            commit=True
        )
    except Exception as e:
        logger.error(f"[UPDATE REQUEST ERROR] request_id={request_id}, status={status}, worker={worker_chat_id} -> {e}")
        return None


# ==================== ASIGNAR TRABAJADOR ====================
def assign_worker_to_request(request_id: int, worker_chat_id: str):
    """Asigna un trabajador a una solicitud SOLO si sigue disponible"""
    try:
        rows_updated = db_execute(
            """UPDATE requests
               SET worker_chat_id = ?, status = 'assigned', accepted_at = ?
               WHERE id = ? AND status = 'waiting_acceptance'""",
            (str(worker_chat_id), int(time.time()), request_id),
            commit=True
        )
        if rows_updated and rows_updated > 0:
            logger.info(f"[ASSIGN REQUEST] request_id={request_id} asignada a worker={worker_chat_id}")
            return True
        else:
            logger.warning(f"[ASSIGN REQUEST FAIL] request_id={request_id} worker={worker_chat_id} status no disponible")
            return False
    except Exception as e:
        logger.error(f"[ASSIGN REQUEST ERROR] request_id={request_id}, worker={worker_chat_id} -> {e}")
        return False


# ==================== FUNCIÓN SEGURA PARA FLUJOS ====================
def assign_worker_to_request_safe(request_id: int, worker_chat_id: str):
    """
    Versión segura para usar en callbacks de Telegram.
    Devuelve True si se pudo asignar, False si ya fue tomado.
    """
    return assign_worker_to_request(request_id, worker_chat_id)
