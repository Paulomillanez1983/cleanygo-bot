import sqlite3
from config import DB_FILE, logger
from utils.icons import Icons

# ==================== TABLA SESSIONS ====================
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # ... tus tablas existentes ...

        # Tabla de sesiones para estados de usuario
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                chat_id TEXT PRIMARY KEY,
                state TEXT,
                data TEXT,
                last_activity INTEGER
            )
        ''')
        
        conn.commit()
    logger.info(f"{Icons.SUCCESS} Base de datos inicializada")

# ==================== FUNCIONES DE SESIÓN ====================
import json
import time

def get_session(chat_id):
    row = db_execute(
        "SELECT state, data FROM sessions WHERE chat_id = ?",
        (str(chat_id),),
        fetch_one=True
    )
    if row:
        state, data_json = row
        try:
            data = json.loads(data_json) if data_json else {}
        except:
            data = {}
        return {"state": state, "data": data}
    return None

def set_state(chat_id, state, data=None):
    data_json = json.dumps(data or {})
    timestamp = int(time.time())
    db_execute('''
        INSERT INTO sessions(chat_id, state, data, last_activity)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            state=excluded.state,
            data=excluded.data,
            last_activity=excluded.last_activity
    ''', (str(chat_id), state, data_json, timestamp), commit=True)

def update_data(chat_id, **kwargs):
    session = get_session(chat_id) or {"state": None, "data": {}}
    session_data = session["data"]
    session_data.update(kwargs)
    set_state(chat_id, session["state"], session_data)

def clear_state(chat_id):
    db_execute("DELETE FROM sessions WHERE chat_id = ?", (str(chat_id),), commit=True)
