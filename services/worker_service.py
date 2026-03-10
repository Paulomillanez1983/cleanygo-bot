# services/worker_service.py

import math
from config import get_db_connection, logger


# ==================================
# HAVERSINE DISTANCE
# ==================================

def haversine(lat1, lon1, lat2, lon2):

    R = 6371  # radio tierra km

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


# ==================================
# FIND AVAILABLE WORKERS
# ==================================

def find_available_workers(service_id, lat, lon, hora_completa):

    try:

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                w.chat_id,
                w.name,
                w.lat,
                w.lon,
                w.rating,
                w.jobs_done,
                w.is_active
            FROM workers w
            JOIN worker_services ws
            ON w.chat_id = ws.worker_chat_id
            WHERE ws.service_id = ?
            """,
            (service_id,)
        )

        rows = cursor.fetchall()
        conn.close()

    except Exception as e:

        logger.error(f"[MATCH ERROR] DB query failed: {e}")
        return [], "db_error", None


    if not rows:
        return [], "no_workers_registered", None


    available_workers = []
    far_workers = []


    for row in rows:

        worker_chat_id = row[0]
        name = row[1]
        w_lat = row[2]
        w_lon = row[3]
        rating = row[4]
        jobs_done = row[5]
        is_active = row[6]


        # worker offline
        if not is_active:
            continue


        # worker sin ubicación
        if w_lat is None or w_lon is None:
            continue


        try:

            distance = haversine(lat, lon, w_lat, w_lon)

        except Exception as e:

            logger.warning(f"[DISTANCE ERROR] worker={worker_chat_id}")
            continue


        worker = [
            worker_chat_id,
            name,
            w_lat,
            w_lon,
            rating,
            jobs_done,
            distance
        ]


        if distance <= 10:
            available_workers.append(worker)
        else:
            far_workers.append(worker)


    if not available_workers:

        if far_workers:
            return [], "workers_far", far_workers

        return [], "no_workers_online", None


    available_workers.sort(key=lambda x: x[6])


    logger.info(f"[MATCH] {len(available_workers)} workers encontrados")


    return available_workers, "success", None
