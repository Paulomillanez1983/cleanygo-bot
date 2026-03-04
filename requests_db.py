# requests_db.py
import sqlite3
import time
from database import db_execute  # tu función de DB central

# -----------------------------
# CREAR TABLA REQUESTS
# -----------------------------
def init_requests_table():
    """Crea la tabla requests si no existe"""
    db_execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_chat_id TEXT NOT NULL,
            service_id TEXT NOT NULL,
            worker_chat_id TEXT,
            hora TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'searching',
            accepted_at INTEGER
        )
    """, commit=True)
    print("✅ Tabla requests lista")

# -----------------------------
# FUNCIONES CRUD
# -----------------------------
def create_request(client_chat_id: str, service_id: str, hora: str, 
                   lat: float, lon: float, status: str = 'searching'):
    """Crea una nueva solicitud"""
    db_execute(
        """INSERT INTO requests (client_chat_id, service_id, hora, lat, lon, status) 
           VALUES (?, ?, ?, ?, ?, ?)""",
        (str(client_chat_id), service_id, hora, lat, lon, status),
        commit=True
    )
    # Devuelve el ID recién creado
    return db_execute("SELECT last_insert_rowid()", fetch_one=True)[0]

def get_request(request_id: int):
    """Obtiene una solicitud por ID"""
    return db_execute("SELECT * FROM requests WHERE id = ?", (request_id,), fetch_one=True)

def update_request_status(request_id: int, status: str, worker_chat_id: str = None):
    """Actualiza estado de una solicitud"""
    ts = int(time.time())
    if worker_chat_id:
        db_execute(
            """UPDATE requests SET status = ?, worker_chat_id = ?, accepted_at = ? 
               WHERE id = ?""",
            (status, str(worker_chat_id), ts, request_id),
            commit=True
        )
    else:
        db_execute(
            "UPDATE requests SET status = ? WHERE id = ?",
            (status, request_id),
            commit=True
        )
    return get_request(request_id)

def assign_worker_to_request(request_id: int, worker_chat_id: str):
    """Asigna un trabajador a una solicitud y marca como 'assigned'"""
    ts = int(time.time())
    db_execute(
        """UPDATE requests 
           SET worker_chat_id = ?, status = 'assigned', accepted_at = ? 
           WHERE id = ?""",
        (str(worker_chat_id), ts, request_id),
        commit=True
    )
    return get_request(request_id)
