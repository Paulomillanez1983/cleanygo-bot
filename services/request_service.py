"""
Servicios para gestión de solicitudes (requests)
"""
from datetime import datetime
from config import get_db_connection, logger


# =====================================================
# CREAR REQUEST
# =====================================================

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
            """, (
                str(client_id),
                service_id,
                hora,
                lat,
                lon,
                status,
                int(datetime.now().timestamp())
            ))

            request_id = cursor.lastrowid

            conn.commit()

            logger.info(f"[REQUEST] Creada solicitud {request_id} para {client_id}")

            return request_id

    except Exception as e:

        logger.error(f"[REQUEST ERROR] {e}")

        return None


# =====================================================
# GET REQUEST
# =====================================================

def get_request(request_id):

    try:
        with get_db_connection() as conn:

            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM requests WHERE id = ?",
                (request_id,)
            )

            row = cursor.fetchone()

            if not row:
                logger.warning(f"[REQUEST] {request_id} no encontrada")
                return None

            return dict(row)

    except Exception as e:

        logger.error(f"[GET REQUEST ERROR] {e}")

        return None


# =====================================================
# UPDATE STATUS
# =====================================================

def update_request_status(request_id, status):

    try:
        with get_db_connection() as conn:

            cursor = conn.cursor()

            cursor.execute(
                "UPDATE requests SET status = ? WHERE id = ?",
                (status, request_id)
            )

            conn.commit()

            if cursor.rowcount == 0:
                logger.warning(f"[REQUEST] No se encontró request {request_id} para actualizar")
                return False

            logger.info(f"[REQUEST] {request_id} -> {status}")

            return True

    except Exception as e:

        logger.error(f"[UPDATE STATUS ERROR] {e}")

        return False


# =====================================================
# ATOMIC WORKER CLAIM (ESTILO UBER)
# =====================================================

def assign_worker_to_request_safe(request_id, worker_id):
    """
    Asignación segura anti-race-condition.
    Solo un worker puede ganar el trabajo.
    """

    try:
        with get_db_connection() as conn:

            cursor = conn.cursor()

            cursor.execute("""
                UPDATE requests
                SET worker_id = ?, status = 'assigned'
                WHERE id = ?
                AND status IN ('searching','pending','waiting_acceptance')
                AND worker_id IS NULL
            """, (str(worker_id), request_id))

            conn.commit()

            # Si no actualizó ninguna fila -> otro worker ganó
            if cursor.rowcount == 0:

                logger.warning(
                    f"[ASSIGN_SAFE] Worker {worker_id} perdió carrera para request {request_id}"
                )

                return False

            logger.info(
                f"[ASSIGN] Worker {worker_id} -> Request {request_id}"
            )

            return True

    except Exception as e:

        logger.error(f"[ASSIGN ERROR] {e}")

        return False


# =====================================================
# CANCEL
# =====================================================

def cancel_request(request_id, reason=""):

    logger.info(f"[CANCEL] Request {request_id} cancelada | reason={reason}")

    return update_request_status(request_id, "cancelled")


# =====================================================
# COMPLETE
# =====================================================

def complete_request(request_id):

    logger.info(f"[COMPLETE] Request {request_id} completada")

    return update_request_status(request_id, "completed")


# =====================================================
# REJECT (WORKER RECHAZA)
# =====================================================

def reject_request(request_id, worker_id):
    """
    Cuando un worker rechaza una solicitud,
    vuelve al estado searching para otro worker.
    """

    try:
        with get_db_connection() as conn:

            cursor = conn.cursor()

            cursor.execute("""
                UPDATE requests
                SET worker_id = NULL,
                    status = 'searching'
                WHERE id = ?
            """, (request_id,))

            conn.commit()

            if cursor.rowcount == 0:
                logger.warning(f"[REJECT] Request {request_id} no encontrada")
                return False

            logger.info(
                f"[REJECT] Worker {worker_id} rechazó request {request_id}"
            )

            return True

    except Exception as e:

        logger.error(f"[REJECT ERROR] {e}")

        return False
