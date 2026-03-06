"""
Configuración central del bot CleanyGo.
Maneja: logging, variables de entorno, conexión DB, sesiones de usuario y notificaciones.
"""

import os
import logging
import sqlite3
import json
import threading
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
        raise RuntimeError("Bot no inicializado. Llama a inject_bot() primero")
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


# Lock global para inicialización
_db_init_lock = threading.Lock()
_db_initialized = False


# ==================== INIT DATABASE ====================

def init_db():
    """Inicializa el esquema de base de datos con migraciones"""
    global _db_initialized
    
    if _db_initialized:
        return
    
    with _db_init_lock:
        if _db_initialized:
            return
            
        try:
            conn = sqlite3.connect(DB_FILE, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Configuración
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys = ON")
            conn.commit()
            
            # ========== MIGRACIONES PRIMERO ==========
            _run_migrations(cursor, conn)
            
            # ========== CREAR TABLAS ==========
            _create_tables(cursor, conn)
            
            # ========== ÍNDICES ==========
            _create_indexes(cursor, conn)
            
            conn.commit()
            conn.close()
            
            _db_initialized = True
            logger.info("✅ Base de datos inicializada correctamente")
            
        except Exception as e:
            logger.error(f"Error inicializando DB: {e}")
            raise


def _run_migrations(cursor, conn):
    """Ejecuta migraciones necesarias"""
    try:
        # Verificar tabla sessions
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(sessions)")
            columns = {col[1] for col in cursor.fetchall()}
            
            if "chat_id" not in columns:
                logger.warning("⚠️ Migrando: Agregando chat_id a sessions")
                cursor.execute("ALTER TABLE sessions ADD COLUMN chat_id TEXT")
                
            if "last_activity" not in columns:
                logger.warning("⚠️ Migrando: Agregando last_activity a sessions")
                cursor.execute("ALTER TABLE sessions ADD COLUMN last_activity INTEGER")
            
            conn.commit()
            
        # Verificar tabla workers
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='workers'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(workers)")
            columns = {col[1] for col in cursor.fetchall()}
            
            # Migrar workers antiguo (chat_id -> user_id)
            if "chat_id" in columns and "user_id" not in columns:
                logger.warning("⚠️ Migrando esquema antiguo workers")
                
                cursor.execute("""
                    CREATE TABLE workers_new (
                        user_id INTEGER PRIMARY KEY,
                        chat_id TEXT UNIQUE,
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
                
                cursor.execute("""
                    INSERT INTO workers_new (user_id, chat_id, name, phone, email, address, lat, lon, is_active, current_request_id, created_at)
                    SELECT CAST(chat_id AS INTEGER), chat_id, name, phone, email, address, lat, lon, is_active, current_request_id, created_at
                    FROM workers
                """)
                
                cursor.execute("DROP TABLE workers")
                cursor.execute("ALTER TABLE workers_new RENAME TO workers")
                conn.commit()
                logger.info("✅ Migración workers completada")
                
    except Exception as e:
        logger.error(f"Error en migraciones: {e}")


def _create_tables(cursor, conn):
    """Crea todas las tablas"""
    
    # WORKERS - Versión completa con todos los campos
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workers (
            user_id INTEGER PRIMARY KEY,
            chat_id TEXT UNIQUE,
            name TEXT,
            nombre TEXT,
            phone TEXT,
            telefono TEXT,
            email TEXT,
            address TEXT,
            dni_file_id TEXT,
            lat REAL,
            lon REAL,
            is_active BOOLEAN DEFAULT 1,
            disponible INTEGER DEFAULT 1,
            current_request_id INTEGER DEFAULT NULL,
            rating REAL DEFAULT 5.0,
            total_jobs INTEGER DEFAULT 0,
            last_update INTEGER,
            created_at INTEGER DEFAULT (strftime('%s','now'))
        )
    """)
    
    # WORKER SERVICES
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS worker_services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id TEXT,
            service_id TEXT NOT NULL,
            precio REAL DEFAULT 0,
            UNIQUE(user_id, service_id),
            FOREIGN KEY (user_id) REFERENCES workers(user_id) ON DELETE CASCADE
        )
    """)
    
    # REQUESTS
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
            client_chat_id TEXT,
            service_id TEXT NOT NULL,
            service_name TEXT,
            request_time TEXT,
            time_period TEXT,
            fecha TEXT,
            hora TEXT,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            address TEXT,
            worker_id INTEGER,
            worker_chat_id TEXT,
            status TEXT DEFAULT 'pending',
            precio_acordado REAL,
            created_at INTEGER DEFAULT (strftime('%s','now')),
            accepted_at INTEGER,
            completed_at INTEGER,
            FOREIGN KEY (worker_id) REFERENCES workers(user_id)
        )
    """)
    
    # SESSIONS - Con chat_id y last_activity
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            user_id INTEGER PRIMARY KEY,
            chat_id TEXT,
            state TEXT,
            data TEXT DEFAULT '{}',
            last_activity INTEGER,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # RATINGS
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER,
            from_user_id INTEGER,
            to_user_id INTEGER,
            from_chat_id TEXT,
            to_chat_id TEXT,
            rating INTEGER CHECK(rating >= 1 AND rating <= 5),
            comment TEXT,
            created_at INTEGER DEFAULT (strftime('%s','now'))
        )
    """)
    
    # REQUEST REJECTIONS
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS request_rejections (
            request_id INTEGER NOT NULL,
            worker_id INTEGER NOT NULL,
            rejected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (request_id, worker_id),
            FOREIGN KEY (request_id) REFERENCES requests(id) ON DELETE CASCADE,
            FOREIGN KEY (worker_id) REFERENCES workers(user_id) ON DELETE CASCADE
        )
    """)
    
    # BOT LOGS
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT,
            message TEXT,
            created_at INTEGER DEFAULT (strftime('%s','now'))
        )
    """)
    
    conn.commit()


def _create_indexes(cursor, conn):
    """Crea índices"""
    indexes = [
        ("idx_requests_status", "requests(status)"),
        ("idx_requests_worker", "requests(worker_id)"),
        ("idx_requests_client", "requests(client_id)"),
        ("idx_requests_created", "requests(created_at)"),
        ("idx_workers_active", "workers(is_active)"),
        ("idx_workers_location", "workers(lat,lon)"),
        ("idx_sessions_chat_id", "sessions(chat_id)"),
        ("idx_ratings_target", "ratings(to_user_id)"),
    ]
    
    for idx_name, table_cols in indexes:
        try:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table_cols}")
        except sqlite3.OperationalError:
            pass
    
    conn.commit()


# ==================== SESSION MANAGEMENT (CORREGIDO) ====================

class UserSession:

    @staticmethod
    def get(user_id: int) -> Optional[Dict[str, Any]]:
        """Obtiene sesión buscando por user_id o chat_id"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Buscar por ambos campos
                cursor.execute(
                    "SELECT state, data FROM sessions WHERE user_id=? OR chat_id=?",
                    (int(user_id), str(user_id))
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
        """Guarda sesión asegurando chat_id y user_id"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                data_json = json.dumps(data or {})
                timestamp = int(time.time())
                user_id_int = int(user_id)
                chat_id_str = str(user_id)
                
                # Verificar si existe
                cursor.execute(
                    "SELECT user_id FROM sessions WHERE user_id=? OR chat_id=?",
                    (user_id_int, chat_id_str)
                )
                
                existing = cursor.fetchone()
                
                if existing:
                    # Actualizar
                    cursor.execute("""
                        UPDATE sessions 
                        SET state=?, 
                            data=?, 
                            last_activity=?, 
                            updated_at=CURRENT_TIMESTAMP,
                            chat_id=COALESCE(chat_id, ?),
                            user_id=COALESCE(user_id, ?)
                        WHERE user_id=? OR chat_id=?
                    """, (state, data_json, timestamp, chat_id_str, user_id_int,
                          user_id_int, chat_id_str))
                else:
                    # Insertar nuevo
                    cursor.execute("""
                        INSERT INTO sessions (user_id, chat_id, state, data, last_activity, updated_at)
                        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (user_id_int, chat_id_str, state, data_json, timestamp))
                
        except Exception as e:
            logger.error(f"[SESSION SET ERROR] {user_id}: {e}")

    @staticmethod
    def clear(user_id: int):
        """Elimina sesión"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM sessions WHERE user_id=? OR chat_id=?",
                    (int(user_id), str(user_id))
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
                JOIN worker_services ws ON w.user_id = ws.user_id
                WHERE ws.service_id = ?
                AND w.is_active = 1
                AND (w.current_request_id IS NULL OR w.current_request_id = '')
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
            raise RuntimeError("Bot no inicializado. Llama a inject_bot(bot)")
        return _bot_instance
        
    raise AttributeError(name)


# ==================== NOTIFICACIONES ASYNC ====================

async def notify_client(chat_id: int, message: str):
    try:
        bot = get_bot()
        await bot.send_message(chat_id=chat_id, text=message)
        logger.info(f"📩 Notificación enviada a cliente {chat_id}")
    except Exception as e:
        logger.error(f"❌ Error enviando notificación: {e}")


# ==================== COMPATIBILIDAD IMPORTS ====================

notify_worker = Notifier.notify_worker


# ==================== FUNCIONES ADICIONALES DE DATABASE.PY ====================

def db_execute(query, params=(), fetch_one=False, commit=False):
    """Ejecuta consultas SQL genéricas"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            
            if commit:
                conn.commit()
            
            if fetch_one:
                row = cursor.fetchone()
                return dict(row) if row else None
            
            rows = cursor.fetchall()
            return [dict(r) for r in rows] if rows else []
            
    except sqlite3.Error as e:
        logger.error(f"DB Error: {e}")
        return None


def get_session(chat_id):
    """Alias compatible con database.py"""
    return UserSession.get(chat_id)


def set_state(chat_id, state, data=None):
    """Alias compatible con database.py"""
    UserSession.set(chat_id, state, data)


def update_data(chat_id, **kwargs):
    """Actualiza datos parciales de sesión"""
    session = UserSession.get(chat_id) or {"state": None, "data": {}}
    session_data = session["data"]
    session_data.update(kwargs)
    UserSession.set(chat_id, session["state"], session_data)


def clear_state(chat_id):
    """Alias compatible con database.py"""
    UserSession.clear(chat_id)


def ensure_worker_exists(chat_id, nombre="Trabajador"):
    """Crea worker si no existe"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT user_id FROM workers WHERE user_id=? OR chat_id=?",
                (int(chat_id), str(chat_id))
            )
            
            if cursor.fetchone():
                return
            
            cursor.execute("""
                INSERT INTO workers (user_id, chat_id, name, nombre, is_active, disponible)
                VALUES (?, ?, ?, ?, 1, 1)
            """, (int(chat_id), str(chat_id), nombre, nombre))
            
            conn.commit()
            logger.info(f"✅ Worker {chat_id} creado")
            
    except Exception as e:
        logger.error(f"Error ensure_worker: {e}")
