"""
Configuración central del bot CleanyGo.
Maneja: logging, variables de entorno, conexión DB, sesiones de usuario y notificaciones.
"""

import os
import logging
import sqlite3
import json
from contextlib import contextmanager
from typing import Optional, Dict, Any

# ==================== LOGGING ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("cleanygo-bot")

# ==================== VARIABLES DE ENTORNO ====================

def get_bot_token() -> str:
    """Obtiene el token del bot desde variables de entorno"""
    token = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        logger.error("❌ BOT_TOKEN no definido en variables de entorno")
        raise RuntimeError("Configura BOT_TOKEN en Railway Variables o .env")

    # ⚠️ NO LOGGEAR TOKEN
    logger.info("✅ Token del bot cargado correctamente")

    return token


TOKEN = get_bot_token()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "cleanygo_ux.db")

# ==================== BOT INSTANCE ====================

_bot_instance = None


def inject_bot(bot_instance):
    """Inyecta la instancia del bot desde bot.py"""
    global _bot_instance
    _bot_instance = bot_instance
    logger.info("✅ Bot inyectado en config")


def get_bot():
    """Obtiene la instancia del bot"""
    if not _bot_instance:
        raise RuntimeError(
            "Bot no inicializado. Llama a inject_bot() primero"
        )
    return _bot_instance


# ==================== DATABASE CONNECTION ====================

@contextmanager
def get_db_connection():
    """
    Context manager para conexiones SQLite seguras.
    Incluye WAL mode para alta concurrencia.
    """
    conn = None

    try:
        conn = sqlite3.connect(
            DB_FILE,
            timeout=30,
            check_same_thread=False
        )

        conn.row_factory = sqlite3.Row

        # 🔥 WAL mejora concurrencia en Railway
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


# ==================== INIT DATABASE ====================

def init_db():
    """Inicializa el esquema de base de datos"""

    with get_db_connection() as conn:

        cursor = conn.cursor()

        # ==================== WORKERS ====================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS workers (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                phone TEXT,
                email TEXT,
                address TEXT,
                lat REAL,
                lon REAL,
                is_active BOOLEAN DEFAULT 1,
                current_request_id INTEGER DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ==================== WORKER SERVICES ====================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS worker_services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                service_id TEXT NOT NULL,
                UNIQUE(user_id, service_id),
                FOREIGN KEY (user_id)
                REFERENCES workers(user_id)
                ON DELETE CASCADE
            )
        """)

        # ==================== REQUESTS ====================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                service_id TEXT NOT NULL,
                service_name TEXT,
                request_time TEXT,
                time_period TEXT,
                lat REAL,
                lon REAL,
                address TEXT,
                worker_id INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                accepted_at TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (worker_id)
                REFERENCES workers(user_id)
            )
        """)

        # ==================== INDEXES ====================

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_requests_status
            ON requests(status)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_requests_worker
            ON requests(worker_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_requests_client
            ON requests(client_id)
        """)

        # ==================== SESSIONS ====================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                user_id INTEGER PRIMARY KEY,
                state TEXT,
                data TEXT DEFAULT '{}',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ==================== RATINGS ====================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL,
                from_user_id INTEGER,
                to_user_id INTEGER,
                rating INTEGER CHECK(rating >= 1 AND rating <= 5),
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ==================== REJECTIONS ====================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS request_rejections (
                request_id INTEGER NOT NULL,
                worker_id INTEGER NOT NULL,
                rejected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (request_id, worker_id),
                FOREIGN KEY (request_id)
                REFERENCES requests(id)
                ON DELETE CASCADE,
                FOREIGN KEY (worker_id)
                REFERENCES workers(user_id)
                ON DELETE CASCADE
            )
        """)

        logger.info("✅ Base de datos inicializada correctamente")


# ==================== SESSION MANAGEMENT ====================

class UserSession:

    @staticmethod
    def get(user_id: int) -> Optional[Dict[str, Any]]:

        try:

            with get_db_connection() as conn:

                cursor = conn.cursor()

                cursor.execute(
                    "SELECT state, data FROM sessions WHERE user_id = ?",
                    (user_id,)
                )

                row = cursor.fetchone()

                if row:

                    return {
                        "state": row["state"],
                        "data": json.loads(row["data"]) if row["data"] else {}
                    }

                return None

        except Exception as e:

            logger.error(f"[SESSION GET ERROR] {user_id}: {e}")
            return None


    @staticmethod
    def set(user_id: int, state: str, data: Dict = None):

        try:

            with get_db_connection() as conn:

                cursor = conn.cursor()

                data_json = json.dumps(data or {})

                cursor.execute("""

                    INSERT INTO sessions (user_id, state, data, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)

                    ON CONFLICT(user_id) DO UPDATE SET
                        state = excluded.state,
                        data = excluded.data,
                        updated_at = CURRENT_TIMESTAMP

                """, (user_id, state, data_json))

        except Exception as e:

            logger.error(f"[SESSION SET ERROR] {user_id}: {e}")


    @staticmethod
    def clear(user_id: int):

        try:

            with get_db_connection() as conn:

                cursor = conn.cursor()

                cursor.execute(
                    "DELETE FROM sessions WHERE user_id = ?",
                    (user_id,)
                )

        except Exception as e:

            logger.error(f"[SESSION CLEAR ERROR] {user_id}: {e}")


# ==================== NOTIFICATIONS ====================

class Notifier:

    @staticmethod
    def _safe_get(data: Dict, key: str, default="No especificado"):

        value = data.get(key)

        return str(value) if value else default


    @staticmethod
    def notify_worker(worker_id: int, request_data: Dict):

        if not _bot_instance:
            logger.error("[NOTIFY] Bot no inicializado")
            return False

        try:

            message = (

                "🔔 <b>Nueva Solicitud</b>\n\n"

                f"📋 {Notifier._safe_get(request_data,'service_name')}\n"
                f"🕐 {Notifier._safe_get(request_data,'request_time')} "
                f"{Notifier._safe_get(request_data,'time_period')}\n"
                f"📍 {Notifier._safe_get(request_data,'address')}\n\n"

                "¿Aceptas este trabajo?"

            )

            _bot_instance.send_message(
                chat_id=worker_id,
                text=message,
                parse_mode="HTML"
            )

            return True

        except Exception as e:

            logger.error(f"[NOTIFY WORKER ERROR] {worker_id}: {e}")
            return False


# ==================== BROADCAST ====================

def broadcast_to_workers(service_id: str, request_data: Dict):

    notified = 0

    try:

        with get_db_connection() as conn:

            cursor = conn.cursor()

            cursor.execute("""

                SELECT DISTINCT w.user_id
                FROM workers w
                JOIN worker_services ws
                ON w.user_id = ws.user_id

                WHERE ws.service_id = ?
                AND w.is_active = 1
                AND (w.current_request_id IS NULL)

            """, (service_id,))

            workers = cursor.fetchall()

        for worker in workers:

            if Notifier.notify_worker(worker["user_id"], request_data):
                notified += 1

        logger.info(f"[BROADCAST] {notified} workers notificados")

        return notified

    except Exception as e:

        logger.error(f"[BROADCAST ERROR] {e}")
        return 0


# ==================== COMPATIBILIDAD ====================

def __getattr__(name):

    global _bot_instance

    if name == "bot":

        if _bot_instance is None:

            raise RuntimeError(
                "Bot no inicializado. Llama a inject_bot(bot)"
            )

        return _bot_instance

    raise AttributeError(name)
# =========================
# NOTIFICACIONES
# =========================

async def notify_client(chat_id: int, message: str):

    try:

        bot = get_bot()

        await bot.send_message(
            chat_id=chat_id,
            text=message
        )

        logger.info(f"📩 Notificación enviada a cliente {chat_id}")

    except Exception as e:
        logger.error(f"❌ Error enviando notificación: {e}")
        notify_worker = Notifier.notify_worker
