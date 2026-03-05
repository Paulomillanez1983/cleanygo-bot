"""
Módulo unificado para manejo de solicitudes (requests).
Integra: CRUD de DB, notificaciones a workers y gestión de asignaciones.
Esquema de DB compatible con config.py
"""

import sqlite3
import time
import logging
from typing import Optional, Dict, List, Any
from config import get_db_connection, notify_worker, broadcast_to_workers, logger

# ==================== INICIALIZACIÓN ====================
def init_requests_table():
    """Crea/actualiza la tabla requests con el esquema unificado"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                service_id TEXT NOT NULL,
                service_name TEXT,
                request_time TEXT NOT NULL,
                time_period TEXT,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                address TEXT,
                worker_id INTEGER,
                status TEXT DEFAULT 'pending',
                precio_acordado REAL,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                accepted_at INTEGER,
                completed_at INTEGER,
                FOREIGN KEY (worker_id) REFERENCES workers(user_id)
            )
        ''')
        
        # Índices para performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_requests_worker ON requests(worker_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_requests_service ON requests(service_id)')
        
        logger.info("✅ Tabla requests inicializada")
        conn.commit()

# ==================== CRUD BÁSICO ====================
def create_request(
    client_id: int,
    service_id: str,
    service_name: str,
    request_time: str,
    time_period: str = None,
    lat: float = 0.0,
    lon: float = 0.0,
    address: str = None,
    precio_acordado: float = None
) -> Optional[int]:
    """
    Crea una nueva solicitud y notifica a workers disponibles.
    Retorna el ID de la solicitud o None si falla.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO requests 
                (client_id, service_id, service_name, request_time, time_period,
                 lat, lon, address, status, precio_acordado)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            ''', (client_id, service_id, service_name, request_time, time_period,
                  lat, lon, address or "No especificada", precio_acordado))
            
            request_id = cursor.lastrowid
            conn.commit()
            
            if not request_id:
                logger.error(f"[CREATE REQUEST] Fallo al crear request para cliente {client_id}")
                return None
            
            logger.info(f"[CREATE REQUEST] ID={request_id} cliente={client_id} servicio={service_id}")
        
        # Notificar a workers disponibles (fuera de transacción)
        if request_id:
            notified = broadcast_to_workers(service_id, {
                'request_id': request_id,
                'service_name': service_name or service_id,
                'request_time': request_time,
                'time_period': time_period or "",
                'address': address or "No especificada",
                'client_id': client_id,
                'lat': lat,
                'lon': lon
            })
            logger.info(f"[CREATE REQUEST] Notificados {notified} workers para request {request_id}")
        
        return request_id
        
    except Exception as e:
        logger.error(f"[CREATE REQUEST ERROR] cliente={client_id}: {e}")
        return None

def get_request(request_id: int) -> Optional[Dict[str, Any]]:
    """Obtiene una solicitud completa por ID"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM requests WHERE id = ?", (request_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"[GET REQUEST ERROR] id={request_id}: {e}")
        return None

def get_requests_by_status(status: str, limit: int = 50) -> List[Dict]:
    """Obtiene solicitudes por estado"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM requests WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit)
            )
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"[GET REQUESTS ERROR] status={status}: {e}")
        return []

def get_pending_requests_for_service(service_id: str) -> List[Dict]:
    """Obtiene solicitudes pendientes para un servicio específico"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM requests 
                WHERE service_id = ? AND status IN ('pending', 'searching')
                ORDER BY created_at DESC
            ''', (service_id,))
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"[GET PENDING ERROR] service={service_id}: {e}")
        return []

# ==================== ACTUALIZACIONES DE ESTADO ====================
def update_request_status(
    request_id: int, 
    status: str, 
    worker_id: int = None
) -> bool:
    """Actualiza el estado de una solicitud"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            ts = int(time.time())
            
            if worker_id:
                cursor.execute('''
                    UPDATE requests 
                    SET status = ?, worker_id = ?, accepted_at = ? 
                    WHERE id = ?
                ''', (status, worker_id, ts, request_id))
            else:
                cursor.execute(
                    "UPDATE requests SET status = ? WHERE id = ?",
                    (status, request_id)
                )
            
            conn.commit()
            logger.info(f"[UPDATE STATUS] request={request_id} -> {status} (worker={worker_id})")
            return True
            
    except Exception as e:
        logger.error(f"[UPDATE STATUS ERROR] request={request_id}: {e}")
        return False

def assign_worker_to_request(request_id: int, worker_id: int) -> Optional[Dict]:
    """
    Asigna un worker a una solicitud solo si está disponible (pending/searching).
    Retorna la solicitud actualizada o None si falla.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            ts = int(time.time())
            
            # Intentar asignar solo si está disponible (concurrencia segura)
            cursor.execute('''
                UPDATE requests 
                SET worker_id = ?, status = 'assigned', accepted_at = ? 
                WHERE id = ? AND status IN ('pending', 'searching')
            ''', (worker_id, ts, request_id))
            
            conn.commit()
            
            if cursor.rowcount == 0:
                logger.warning(f"[ASSIGN FAIL] request={request_id} no disponible para worker={worker_id}")
                return None
            
            # Actualizar current_request_id del worker
            # ✅ AHORA (corregido):
           cursor.execute(
             "UPDATE workers SET current_request_id = NULL WHERE user_id = ? AND current_request_id = ?",
             (worker_id, request_id)
             )

            conn.commit()
            
            logger.info(f"[ASSIGN] request={request_id} asignada a worker={worker_id}")
            return get_request(request_id)
            
    except Exception as e:
        logger.error(f"[ASSIGN ERROR] request={request_id}, worker={worker_id}: {e}")
        return None

def release_worker_from_request(worker_id: int, request_id: int = None) -> bool:
    """Libera a un worker de su solicitud actual"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            if request_id:
                # Verificar que el worker tenga esa request asignada
                cursor.execute(
                    "UPDATE workers SET current_request_id = NULL 
                     WHERE user_id = ? AND current_request_id = ?",
                    (worker_id, request_id)
                )
            else:
                # Liberar cualquier request asignada
                cursor.execute(
                    "UPDATE workers SET current_request_id = NULL WHERE user_id = ?",
                    (worker_id,)
                )
            
            conn.commit()
            logger.info(f"[RELEASE] worker={worker_id} liberado")
            return True
            
    except Exception as e:
        logger.error(f"[RELEASE ERROR] worker={worker_id}: {e}")
        return False

def complete_request(request_id: int) -> bool:
    """Marca una solicitud como completada y libera al worker"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            ts = int(time.time())
            
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
            cursor.execute('''
                UPDATE requests 
                SET status = 'completed', completed_at = ? 
                WHERE id = ?
            ''', (ts, request_id))
            
            conn.commit()
            logger.info(f"[COMPLETE] request={request_id} completada")
            return True
            
    except Exception as e:
        logger.error(f"[COMPLETE ERROR] request={request_id}: {e}")
        return False

def cancel_request(request_id: int, reason: str = None) -> bool:
    """Cancela una solicitud y libera al worker si estaba asignado"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Obtener worker asignado antes de cancelar
            cursor.execute("SELECT worker_id FROM requests WHERE id = ?", (request_id,))
            row = cursor.fetchone()
            
            if row and row['worker_id']:
                cursor.execute(
                    "UPDATE workers SET current_request_id = NULL WHERE user_id = ?",
                    (row['worker_id'],)
                )
            
            # Cancelar request
            cursor.execute(
                "UPDATE requests SET status = 'cancelled' WHERE id = ?",
                (request_id,)
            )
            
            conn.commit()
            logger.info(f"[CANCEL] request={request_id} cancelada. Reason: {reason}")
            return True
            
    except Exception as e:
        logger.error(f"[CANCEL ERROR] request={request_id}: {e}")
        return False

# ==================== RECHAZOS ====================
def reject_request(request_id: int, worker_id: int) -> bool:
    """Registra que un worker rechazó una solicitud"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR IGNORE INTO request_rejections (request_id, worker_id)
                VALUES (?, ?)
            ''', (request_id, worker_id))
            
            conn.commit()
            logger.info(f"[REJECT] worker={worker_id} rechazó request={request_id}")
            return True
            
    except Exception as e:
        logger.error(f"[REJECT ERROR] request={request_id}, worker={worker_id}: {e}")
        return False

def has_worker_rejected(request_id: int, worker_id: int) -> bool:
    """Verifica si un worker ya rechazó una solicitud"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 1 FROM request_rejections 
                WHERE request_id = ? AND worker_id = ?
            ''', (request_id, worker_id))
            return cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"[CHECK REJECT ERROR]: {e}")
        return False

# ==================== BACKWARDS COMPATIBILITY ====================
# Alias para código antiguo que use nombres anteriores
create_request_db = create_request
get_request_db = get_request
assign_worker_to_request_safe = assign_worker_to_request
