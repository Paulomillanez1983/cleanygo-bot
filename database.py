"""
Database module - Versión unificada con config.py
Optimizada para bots Telegram en producción
"""

import sqlite3
import json
import time
import threading
import os

# Configuración de DB - DEFINIR AQUÍ para evitar import circular
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "cleanygo_ux.db")

# Lock global para evitar race conditions en inicialización
_db_init_lock = threading.Lock()
_db_initialized = False

# Logger simple (importar de config si está disponible, sino usar logging)
try:
    from config import logger, Icons
except ImportError:
    import logging
    logger = logging.getLogger("cleanygo-bot")
    class Icons:
        SUCCESS = "✅"
        WARNING = "⚠️"


# ==============================
# INICIALIZACIÓN DB
# ==============================

def init_db():
    """Inicializa la base de datos con migraciones garantizadas."""
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
            
            # Configuración SQLite
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            conn.commit()
            
            # MIGRACIONES PRIMERO (importante!)
            _run_migrations(cursor, conn)
            
            # Crear tablas
            _create_tables(cursor, conn)
            
            # Crear índices
            _create_indexes(cursor, conn)
            
            conn.commit()
            conn.close()
            
            _db_initialized = True
            logger.info(f"{Icons.SUCCESS} Base de datos inicializada correctamente")
            
        except Exception as e:
            logger.error(f"Error inicializando DB: {e}")
            raise


def _run_migrations(cursor, conn):
    """Ejecuta migraciones necesarias antes de crear tablas."""
    try:
        # ========== MIGRAR SESSIONS ==========
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(sessions)")
            columns = {col[1] for col in cursor.fetchall()}
            
            # Agregar columnas faltantes una por una con manejo de errores
            if "chat_id" not in columns:
                try:
                    cursor.execute("ALTER TABLE sessions ADD COLUMN chat_id TEXT")
                    logger.info(f"{Icons.WARNING} Migrado: chat_id agregado a sessions")
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        raise
            
            if "last_activity" not in columns:
                try:
                    cursor.execute("ALTER TABLE sessions ADD COLUMN last_activity INTEGER")
                    logger.info(f"{Icons.WARNING} Migrado: last_activity agregado a sessions")
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        raise
            
            if "updated_at" not in columns:
                try:
                    cursor.execute("ALTER TABLE sessions ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                    logger.info(f"{Icons.WARNING} Migrado: updated_at agregado a sessions")
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        raise
            
            conn.commit()
        
        # ========== MIGRAR WORKERS ==========
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='workers'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(workers)")
            columns = [col[1] for col in cursor.fetchall()]
            
            # Si tiene chat_id pero no user_id, es esquema antiguo
            if columns and "chat_id" in columns and "user_id" not in columns:
                logger.info(f"{Icons.WARNING} Migrando esquema antiguo workers")
                
                # Crear tabla nueva
                cursor.execute("""
                    CREATE TABLE workers_new (
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
                
                # Migrar datos
                cursor.execute("""
                    INSERT INTO workers_new 
                    (user_id, chat_id, nombre, telefono, dni_file_id, lat, lon,
                     disponible, rating, total_jobs, last_update, created_at)
                    SELECT 
                        CAST(chat_id AS INTEGER),
                        chat_id,
                        nombre,
                        telefono,
                        dni_file_id,
                        lat,
                        lon,
                        disponible,
                        rating,
                        total_jobs,
                        last_update,
                        created_at
                    FROM workers
                """)
                
                cursor.execute("DROP TABLE workers")
                cursor.execute("ALTER TABLE workers_new RENAME TO workers")
                conn.commit()
                logger.info(f"{Icons.SUCCESS} Migración workers completada")
                
    except Exception as e:
        logger.error(f"Error en migraciones: {e}")
        raise


def _create_tables(cursor, conn):
    """Crea todas las tablas si no existen."""
    
    # WORKERS
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
    
    # RATINGS
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER,
            from_user_id INTEGER,
            to_user_id INTEGER,
            from_chat_id TEXT,
            to_chat_id TEXT,
            rating INTEGER,
            comment TEXT,
            created_at INTEGER DEFAULT (strftime('%s','now'))
        )
    """)
    
    # SESSIONS - Versión completa con todas las columnas
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
    """Crea índices."""
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
            pass  # Ya existe
    
    conn.commit()


# ==============================
# CONNECTION MANAGER
# ==============================

from contextlib import contextmanager

@contextmanager
def get_db_connection():
    """Context manager para conexiones SQLite."""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
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


# ==============================
# EJECUTAR CONSULTAS
# ==============================

def db_execute(query, params=(), fetch_one=False, commit=False):
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


# ==============================
# SESIONES (CORREGIDAS)
# ==============================

def get_session(chat_id):
    """Obtiene sesión buscando por user_id o chat_id."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT state, data FROM sessions WHERE user_id=? OR chat_id=?",
                (int(chat_id), str(chat_id))
            )
            
            row = cursor.fetchone()
            
            if not row:
                return None
            
            try:
                data = json.loads(row["data"]) if row["data"] else {}
            except:
                data = {}
            
            return {
                "state": row["state"],
                "data": data
            }
            
    except Exception as e:
        logger.error(f"Error get_session: {e}")
        return None


def set_state(chat_id, state, data=None):
    """Guarda estado asegurando ambos campos user_id y chat_id."""
    try:
        data_json = json.dumps(data or {})
        timestamp = int(time.time())
        chat_id_int = int(chat_id)
        chat_id_str = str(chat_id)
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Verificar existencia
            cursor.execute(
                "SELECT user_id FROM sessions WHERE user_id=? OR chat_id=?",
                (chat_id_int, chat_id_str)
            )
            
            existing = cursor.fetchone()
            
            if existing:
                # UPDATE con COALESCE para no perder datos existentes
                cursor.execute("""
                    UPDATE sessions 
                    SET state=?,
                        data=?,
                        last_activity=?,
                        updated_at=CURRENT_TIMESTAMP,
                        chat_id=COALESCE(chat_id, ?),
                        user_id=COALESCE(user_id, ?)
                    WHERE user_id=? OR chat_id=?
                """, (state, data_json, timestamp, chat_id_str, chat_id_int,
                      chat_id_int, chat_id_str))
            else:
                # INSERT nuevo
                cursor.execute("""
                    INSERT INTO sessions (user_id, chat_id, state, data, last_activity, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (chat_id_int, chat_id_str, state, data_json, timestamp))
            
            conn.commit()
            
    except Exception as e:
        logger.error(f"Error set_state: {e}")


def update_data(chat_id, **kwargs):
    """Actualiza datos parciales."""
    session = get_session(chat_id) or {"state": None, "data": {}}
    data = session["data"]
    data.update(kwargs)
    set_state(chat_id, session["state"], data)


def clear_state(chat_id):
    """Elimina sesión."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM sessions WHERE user_id=? OR chat_id=?",
                (int(chat_id), str(chat_id))
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Error clear_state: {e}")


# ==============================
# WORKERS
# ==============================

def ensure_worker_exists(chat_id, nombre="Trabajador"):
    """Crea worker si no existe."""
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
            logger.info(f"{Icons.SUCCESS} Worker {chat_id} creado")
            
    except Exception as e:
        logger.error(f"Error ensure_worker: {e}")


# ==============================
# CLASE UserSession (para compatibilidad con config.py)
# ==============================

class UserSession:
    """Clase compatible con el código existente en config.py"""
    
    @staticmethod
    def get(user_id):
        return get_session(user_id)
    
    @staticmethod
    def set(user_id, state, data=None):
        set_state(user_id, state, data)
    
    @staticmethod
    def clear(user_id):
        clear_state(user_id)
