"""
Configuración central del bot CleanyGo.
Maneja: logging, variables de entorno, conexión DB, sesiones de usuario y notificaciones.
VERSIÓN UNIFICADA
"""

import os
import logging
import sqlite3
import json
import threading
import time
from contextlib import contextmanager
from typing import Optional, Dict, Any

# ==================== LOGGING ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("cleanygo-bot")

# ==================== ICONS ====================

class Icons:
    SUCCESS = "✅"
    WARNING = "⚠️"
    ERROR = "❌"
    INFO = "ℹ️"

# ==================== VARIABLES DE ENTORNO ====================

def get_bot_token() -> str:
    token = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        logger.error("❌ BOT_TOKEN no definido")
        raise RuntimeError("Configura BOT_TOKEN")

    logger.info("✅ Token cargado")
    return token


TOKEN = get_bot_token()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "cleanygo_ux.db")

# ==================== BOT INSTANCE ====================

_bot_instance = None

def inject_bot(bot_instance):
    global _bot_instance
    _bot_instance = bot_instance
    logger.info("✅ Bot inyectado en config")

def get_bot():
    if not _bot_instance:
        raise RuntimeError("Bot no inicializado")
    return _bot_instance

# ==================== DATABASE CONNECTION ====================

@contextmanager
def get_db_connection():

    conn = None

    try:
        conn = sqlite3.connect(
            DB_FILE,
            timeout=30,
            check_same_thread=False
        )

        conn.row_factory = sqlite3.Row

        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")

        yield conn

        conn.commit()

    except sqlite3.Error as e:

        if conn:
            conn.rollback()

        logger.error(f"[DB ERROR] {e}")
        raise

    finally:

        if conn:
            conn.close()

# ==================== DB INIT ====================

_db_init_lock = threading.Lock()
_db_initialized = False


def init_db():

    global _db_initialized

    if _db_initialized:
        return

    with _db_init_lock:

        if _db_initialized:
            return

        try:

            logger.info("🚀 Inicializando DB")

            conn = sqlite3.connect(DB_FILE, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")

            _create_tables(cursor)
            _create_indexes(cursor)

            conn.commit()
            conn.close()

            _db_initialized = True

            logger.info("✅ DB lista")

        except Exception as e:

            logger.error(f"❌ Error DB init {e}")
            raise

# ==================== TABLES ====================

def _create_tables(cursor):

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions(
            user_id INTEGER PRIMARY KEY,
            chat_id TEXT,
            state TEXT,
            data TEXT DEFAULT '{}',
            last_activity INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workers(
            user_id INTEGER PRIMARY KEY,
            chat_id TEXT UNIQUE,
            name TEXT,
            is_active INTEGER DEFAULT 1,
            current_request_id INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS worker_services(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            service_id TEXT,
            precio REAL DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
            service_id TEXT,
            service_name TEXT,
            lat REAL,
            lon REAL,
            address TEXT,
            worker_id INTEGER,
            status TEXT DEFAULT 'pending',
            created_at INTEGER
        )
    """)

# ==================== INDEXES ====================

def _create_indexes(cursor):

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_chat_id ON sessions(chat_id)"
    )

# ==================== SESSION MANAGEMENT ====================

class UserSession:

    @staticmethod
    def get(user_id: int):

        try:

            with get_db_connection() as conn:

                cursor = conn.cursor()

                cursor.execute(
                    "SELECT state,data FROM sessions WHERE user_id=? OR chat_id=?",
                    (int(user_id), str(user_id))
                )

                row = cursor.fetchone()

                if not row:
                    return None

                try:
                    data = json.loads(row["data"]) if row["data"] else {}

                except Exception:
                    logger.warning(
                        f"[SESSION] JSON corrupto {user_id} - reiniciando"
                    )
                    UserSession.clear(user_id)
                    data = {}

                return {
                    "state": row["state"],
                    "data": data
                }

        except Exception as e:

            logger.error(f"[SESSION GET ERROR] {user_id} {e}")
            return None


    @staticmethod
    def set(user_id: int, state: str, data: Dict = None):

        try:

            data_json = json.dumps(data or {}, default=str)

            timestamp = int(time.time())

            user_id_int = int(user_id)
            chat_id_str = str(user_id)

            with get_db_connection() as conn:

                cursor = conn.cursor()

                cursor.execute(
                    "SELECT user_id FROM sessions WHERE user_id=? OR chat_id=?",
                    (user_id_int, chat_id_str)
                )

                existing = cursor.fetchone()

                if existing:

                    cursor.execute("""
                        UPDATE sessions
                        SET state=?,
                            data=?,
                            last_activity=?
                        WHERE user_id=? OR chat_id=?
                    """,
                    (
                        state,
                        data_json,
                        timestamp,
                        user_id_int,
                        chat_id_str
                    ))

                else:

                    cursor.execute("""
                        INSERT INTO sessions
                        (user_id,chat_id,state,data,last_activity)
                        VALUES(?,?,?,?,?)
                    """,
                    (
                        user_id_int,
                        chat_id_str,
                        state,
                        data_json,
                        timestamp
                    ))

        except Exception as e:

            logger.error(f"[SESSION SET ERROR] {user_id} {e}")


    @staticmethod
    def clear(user_id: int):

        try:

            with get_db_connection() as conn:

                cursor = conn.cursor()

                cursor.execute(
                    "DELETE FROM sessions WHERE user_id=? OR chat_id=?",
                    (int(user_id), str(user_id))
                )

        except Exception as e:

            logger.error(f"[SESSION CLEAR ERROR] {user_id} {e}")

# ==================== SESSION HELPERS ====================

def get_session(chat_id):
    return UserSession.get(chat_id)


def set_state(chat_id, state, data=None):
    UserSession.set(chat_id, state, data)


def update_data(chat_id, **kwargs):

    session = UserSession.get(chat_id)

    if not session:
        session = {
            "state": "idle",
            "data": {}
        }

    session_data = session["data"]

    session_data.update(kwargs)

    UserSession.set(
        chat_id,
        session["state"],
        session_data
    )


def clear_state(chat_id):
    UserSession.clear(chat_id)

# ==================== DB EXECUTE ====================

def db_execute(query, params=(), fetch_one=False):

    try:

        with get_db_connection() as conn:

            cursor = conn.cursor()

            cursor.execute(query, params)

            if fetch_one:

                row = cursor.fetchone()

                return dict(row) if row else None

            rows = cursor.fetchall()

            return [dict(r) for r in rows]

    except Exception as e:

        logger.error(f"DB Error {e}")
        return None

# ==================== WORKERS ====================

def ensure_worker_exists(chat_id):

    try:

        with get_db_connection() as conn:

            cursor = conn.cursor()

            cursor.execute(
                "SELECT user_id FROM workers WHERE user_id=?",
                (int(chat_id),)
            )

            if cursor.fetchone():
                return

            cursor.execute(
                "INSERT INTO workers(user_id,chat_id) VALUES(?,?)",
                (int(chat_id), str(chat_id))
            )

            logger.info(f"Worker {chat_id} creado")

    except Exception as e:

        logger.error(f"Worker create error {e}")

# ==================== NOTIFICATIONS ====================

class Notifier:

    @staticmethod
    def notify_worker(worker_id, request_data):

        if not _bot_instance:
            return False

        try:

            text = (
                "🔔 Nueva solicitud\n\n"
                f"Servicio: {request_data.get('service_name')}\n"
                f"Dirección: {request_data.get('address')}"
            )

            _bot_instance.send_message(
                worker_id,
                text
            )

            return True

        except Exception as e:

            logger.error(f"Notify worker error {e}")
            return False


notify_worker = Notifier.notify_worker

# ==================== BROADCAST ====================

def broadcast_to_workers(service_id, request_data):

    notified = 0

    try:

        with get_db_connection() as conn:

            cursor = conn.cursor()

            cursor.execute("""
                SELECT DISTINCT w.user_id
                FROM workers w
                JOIN worker_services ws
                ON w.user_id = ws.user_id
                WHERE ws.service_id=?
                AND w.is_active=1
            """,(service_id,))

            workers = cursor.fetchall()

        for worker in workers:

            if Notifier.notify_worker(
                worker["user_id"],
                request_data
            ):
                notified += 1

        return notified

    except Exception as e:

        logger.error(f"Broadcast error {e}")
        return 0
