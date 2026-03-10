# services/request_service.py

import math
from config import get_db_connection, logger
from services.worker_service import find_available_workers


# ===============================
# CREATE REQUEST
# ===============================

def create_request(client_id, service_id, hora, lat, lon, status="searching"):
    """
    Crea una solicitud en la base de datos
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO requests
        (client_chat_id, service_id, hora, lat, lon, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
    """, (client_id, service_id, hora, lat, lon, status))

    request_id = cursor.lastrowid
    conn.commit()
    conn.close()

    logger.info(f"[REQUEST] Nueva solicitud creada {request_id}")

    return request_id


# ===============================
# GET REQUEST
# ===============================

def get_request(request_id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, client_chat_id, service_id, hora, lat, lon, status, worker_id
        FROM requests
        WHERE id = ?
    """, (request_id,))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "request_id": row[0],
        "client_chat_id": row[1],
        "service_id": row[2],
        "hora": row[3],
        "lat": row[4],
        "lon": row[5],
        "status": row[6],
        "worker_id": row[7]
    }


# ===============================
# UPDATE STATUS
# ===============================

def update_request_status(request_id, status):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE requests
        SET status = ?
        WHERE id = ?
    """, (status, request_id))

    conn.commit()
    conn.close()

    logger.info(f"[REQUEST] {request_id} status -> {status}")


# ===============================
# SAFE ASSIGN WORKER
# ===============================

def assign_worker_to_request_safe(request_id, worker_id):
    """
    Asignación segura para evitar race conditions
    """

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT status FROM requests
        WHERE id = ?
    """, (request_id,))

    row = cursor.fetchone()

    if not row:
        conn.close()
        return False

    if row[0] != "searching":
        conn.close()
        return False

    cursor.execute("""
        UPDATE requests
        SET worker_id = ?, status = 'assigned'
        WHERE id = ?
    """, (worker_id, request_id))

    conn.commit()
    conn.close()

    logger.info(f"[ASSIGN] worker {worker_id} -> request {request_id}")

    return True


# ===============================
# FIND WORKERS WRAPPER
# ===============================

def find_workers_for_request(service_id, lat, lon, hora):

    workers, status, extra = find_available_workers(
        service_id,
        lat,
        lon,
        hora
    )

    return workers, status, extra
