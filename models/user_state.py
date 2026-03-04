import sqlite3
import json
import time
from enum import Enum
from config import DB_FILE, logger

# ==================== ENUM ESTADOS ====================
class UserState(Enum):
    IDLE = "idle"
    SELECTING_ROLE = "selecting_role"

    # Worker flow
    WORKER_SELECTING_SERVICES = "worker_selecting_services"
    WORKER_ENTERING_PRICE = "worker_entering_price"
    WORKER_ENTERING_NAME = "worker_entering_name"
    WORKER_ENTERING_PHONE = "worker_entering_phone"
    WORKER_ENTERING_DNI = "worker_entering_dni"
    WORKER_SHARING_LOCATION = "worker_sharing_location"

    # Client flow
    CLIENT_SELECTING_SERVICE = "client_selecting_service"
    CLIENT_SELECTING_DATE = "client_selecting_date"
    CLIENT_SELECTING_TIME = "client_selecting_time"
    CLIENT_SHARING_LOCATION = "client_sharing_location"
    CLIENT_CONFIRMING = "client_confirming"
    CLIENT_WAITING_ACCEPTANCE = "client_waiting_acceptance"

    JOB_IN_PROGRESS = "job_in_progress"


# ==================== SESIONES CON SQLITE ====================
def init_sessions_table():
    """Crear tabla sessions si no existe"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                chat_id TEXT PRIMARY KEY,
                state TEXT,
                data TEXT,
                last_activity INTEGER
            )
        ''')
        conn.commit()
    logger.info("✅ Tabla sessions inicializada")


def get_session(chat_id: str) -> dict:
    """Obtener sesión de SQLite"""
    chat_id = str(chat_id)
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT state, data FROM sessions WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        if row:
            state, data_json = row
            try:
                data = json.loads(data_json) if data_json else {}
            except:
                data = {}
            return {"state": state, "data": data}
        else:
            return {"state": UserState.IDLE.value, "data": {}}


def set_state(chat_id: str, state: UserState, data: dict = None):
    """Guardar o actualizar sesión en SQLite"""
    chat_id = str(chat_id)
    data_json = json.dumps(data or {})
    timestamp = int(time.time())
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO sessions(chat_id, state, data, last_activity)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                state=excluded.state,
                data=excluded.data,
                last_activity=excluded.last_activity
        ''', (chat_id, state.value, data_json, timestamp))
        conn.commit()


def update_data(chat_id: str, **kwargs):
    """Actualizar solo el diccionario de datos de la sesión"""
    session = get_session(chat_id)
    session_data = session["data"]
    session_data.update(kwargs)
    set_state(chat_id, UserState(session["state"]), session_data)


def get_data(chat_id: str, key: str, default=None):
    session = get_session(chat_id)
    return session["data"].get(key, default)


def clear_state(chat_id: str):
    """Eliminar sesión de SQLite"""
    chat_id = str(chat_id)
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE chat_id = ?", (chat_id,))
        conn.commit()
