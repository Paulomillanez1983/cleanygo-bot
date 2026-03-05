"""
Módulo para manejo de solicitudes (requests) en la base de datos.
Incluye creación, consulta, actualización y asignación de trabajadores.
Versión final corregida y segura para concurrencia en asignación de trabajos.
"""

import sqlite3
import time
import logging
from contextlib import contextmanager
from config import DB_FILE, logger, notify_worker, get_db_connection

# ==================== LOGGING ====================
logger = logging.getLogger(__name__)

# ==================== CREAR SOLICITUD ====================
def create_request(client_chat_id: str, service_id: str, service_name: str, 
                   hora: str, time_period: str, lat: float, lon: float, 
                   address: str = None, status: str = 'pending'):
    """
    Crea una nueva solicitud, notifica a workers disponibles y devuelve su ID.
    Devuelve None si hubo algún error.
    """
    request_id = None
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # ✅ CORREGIDO: Insertar con todos los campos necesarios
            cursor.execute(
                """INSERT INTO requests 
                   (client_id, service_id, service_name, request_time, time_period, 
                    lat, lon, address, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (int(client_chat_id), service_id, service_name, hora, time_period,
                 lat, lon, address or "No especificada", status, int(time.time()))
            )
            
            conn.commit()
            request_id = cursor.lastrowid
            
            if not request_id:
                logger.warning(f"[CREATE REQUEST FAIL] ID inválido para cliente={client_chat_id}")
                return None
            
            logger.info(f"[CREATE REQUEST] ID={request_id} cliente={client_chat_id}, servicio={service_id}")

            # ✅ NUEVO: Buscar y notificar workers disponibles para este servicio
            cursor.execute("""
                SELECT DISTINCT w.user_id, w.name, w.phone 
                FROM workers w
                JOIN worker_services ws ON w.user_id = ws.user_id
                WHERE ws.service_id = ? 
                AND w.is_active = 1 
                AND (w.current_request_id IS NULL OR w.current_request_id = 0)
            """, (service_id,))
            
            available_workers = cursor.fetchall()
            logger.info(f"[CREATE REQUEST] Encontrados {len(available_workers)} workers disponibles para {service_id}")

        # ✅ NUEVO: Notificar fuera de la transacción para no bloquear
        notified_count = 0
        for worker in available_workers:
            try:
                # ✅ CORREGIDO: Pasar datos completos y seguros
                success = notify_worker(worker['user_id'], {
                    'request_id': request_id,
                    'service_id': service_id,
                    'service_name': service_name or "Servicio",
                    'request_time': hora or "No especificada",
                    'time_period': time_period or "",
                    'lat': lat,
                    'lon': lon,
                    'address': address or "No especificada",
                    'client_id': client_chat_id
                })
                if success:
                    notified_count += 1
            except Exception as e:
                logger.error(f"[NOTIFY ERROR] Fallo al notificar a worker {worker['user_id']}: {e}")
        
        logger.info(f"[CREATE REQUEST] Notificados {notified_count}/{len(available_workers)} workers")
        return request_id

    except Exception as e:
        logger.error(f"[CREATE REQUEST ERROR] cliente={client_chat_id}, servicio={service_id} -> {e}")
        # Si se creó la request pero falló la notificación, igual devolver el ID
        return request_id

# ==================== OBTENER SOLICITUD ====================
def get_request(request_id: int):
    """Obtiene una solicitud por ID y devuelve un diccionario"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM requests WHERE id = ?", (request_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"[GET REQUEST ERROR] request_id={request_id} -> {e}")
        return None

def get_pending_requests_for_worker(worker_chat_id: str, service_ids: list = None):
    """
    Obtiene solicitudes pendientes disponibles para un worker.
    Filtra por servicios que el worker ofrece (opcional).
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            if service_ids:
                placeholders = ','.join('?' * len(service_ids))
                query = f"""
                    SELECT * FROM requests 
                    WHERE status IN ('pending', 'searching') 
                    AND service_id IN ({placeholders})
                    AND (worker_id IS NULL OR worker_id = 0)
                    ORDER BY created_at DESC
                """
                cursor.execute(query, service_ids)
            else:
                cursor.execute("""
                    SELECT * FROM requests 
                    WHERE status IN ('pending', 'searching') 
                    AND (worker_id IS NULL OR worker_id = 0)
                    ORDER BY created_at DESC
                """)
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"[GET PENDING ERROR] worker={worker_chat_id} -> {e}")
        return []

# ==================== ACTUALIZAR ESTADO ====================
def update_request_status(request_id: int, status: str, worker_chat_id: str = None):
    """Actualiza el estado de una solicitud"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            if worker_chat_id:
                cursor.execute(
                    """UPDATE requests 
                       SET status = ?, worker_id = ?, accepted_at = ? 
                       WHERE id = ?""",
                    (status, int(worker_chat_id), int(time.time()), request_id)
                )
            else:
                cursor.execute(
                    "UPDATE requests SET status = ? WHERE id = ?",
                    (status, request_id)
                )
            
            conn.commit()
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
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Transacción atómica: solo asigna si status sigue siendo 'pending', 'searching' o 'waiting_acceptance'
            cursor.execute(
                """UPDATE requests
                   SET worker_id = ?, status = 'assigned', accepted_at = ?
                   WHERE id = ? AND status IN ('pending', 'searching', 'waiting_acceptance')""",
                (int(worker_chat_id), int(time.time()), request_id)
            )

            conn.commit()
            rows_updated = cursor.rowcount

            if rows_updated > 0:
                logger.info(f"[ASSIGN REQUEST] request_id={request_id} asignada a worker={worker_chat_id}")
                
                # ✅ NUEVO: Actualizar current_request_id del worker
                cursor.execute(
                    "UPDATE workers SET current_request_id = ? WHERE user_id = ?",
                    (request_id, int(worker_chat_id))
                )
                conn.commit()
                
                return True
            else:
                logger.warning(f"[ASSIGN REQUEST FAIL] request_id={request_id} worker={worker_chat_id} - ya fue tomada o status inválido")
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

# ==================== CANCELAR/RECHAZAR SOLICITUD ====================
def reject_request(request_id: int, worker_chat_id: str):
    """
    Registra que un worker rechazó una solicitud y libera al worker.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Registrar rechazo
            cursor.execute(
                "INSERT OR IGNORE INTO request_rejections (request_id, worker_id) VALUES (?, ?)",
                (request_id, int(worker_chat_id))
            )
            
            # Liberar al worker si tenía asignada esta request
            cursor.execute(
                "UPDATE workers SET current_request_id = NULL WHERE user_id = ? AND current_request_id = ?",
                (int(worker_chat_id), request_id)
            )
            
            conn.commit()
            logger.info(f"[REJECT REQUEST] request_id={request_id} rechazada por worker={worker_chat_id}")
            return True
    except Exception as e:
        logger.error(f"[REJECT REQUEST ERROR] request_id={request_id}, worker={worker_chat_id} -> {e}")
        return False

def complete_request(request_id: int):
    """Marca una solicitud como completada"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Obtener worker asignado
            cursor.execute("SELECT worker_id FROM requests WHERE id = ?", (request_id,))
            row = cursor.fetchone()
            
            if row and row['worker_id']:
                # Liberar al worker
                cursor.execute(
                    "UPDATE workers SET current_request_id = NULL WHERE user_id = ?",
                    (row['worker_id'],)
                )
            
            # Completar request
            cursor.execute(
                "UPDATE requests SET status = 'completed', completed_at = ? WHERE id = ?",
                (int(time.time()), request_id)
            )
            
            conn.commit()
            logger.info(f"[COMPLETE REQUEST] request_id={request_id} completada")
            return True
    except Exception as e:
        logger.error(f"[COMPLETE REQUEST ERROR] request_id={request_id} -> {e}")
        return False
