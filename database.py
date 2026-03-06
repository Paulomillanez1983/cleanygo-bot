"""
Database module - Versión unificada con config.py
Mantiene compatibilidad hacia atrás mientras migra al nuevo esquema
"""

import sqlite3
import json
import time
from config import DB_FILE, logger, get_db_connection
from utils.icons import Icons


# ==================== INICIALIZACIÓN DB ====================
def init_db():
    """
    Inicializa base de datos con esquema unificado.
    Compatible con config.py y requests_db.py
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # ==================== TABLA WORKERS ====================
        cursor.execute('''
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
        ''')

        # ==================== TABLA WORKER_SERVICES ====================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS worker_services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                chat_id TEXT,
                service_id TEXT NOT NULL,
                precio REAL DEFAULT 0,
                UNIQUE(user_id, service_id),
                FOREIGN KEY (user_id) REFERENCES workers(user_id) ON DELETE CASCADE
            )
        ''')

        # ==================== TABLA REQUESTS ====================
        cursor.execute('''
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
        ''')

        # ==================== TABLA RATINGS ====================
        cursor.execute('''
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
        ''')

        # ==================== TABLA SESSIONS ====================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                user_id INTEGER PRIMARY KEY,
                chat_id TEXT UNIQUE,
                state TEXT,
                data TEXT DEFAULT '{}',
                last_activity INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # ==================== TABLA REJECTIONS ====================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS request_rejections (
                request_id INTEGER NOT NULL,
                worker_id INTEGER NOT NULL,
                rejected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (request_id, worker_id),
                FOREIGN KEY (request_id) REFERENCES requests(id) ON DELETE CASCADE,
                FOREIGN KEY (worker_id) REFERENCES workers(user_id) ON DELETE CASCADE
            )
        ''')

        # ==================== ÍNDICES ====================
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_requests_worker ON requests(worker_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_requests_client ON requests(client_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_workers_active ON workers(is_active)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_chat_id ON sessions(chat_id)')

        conn.commit()

        # ==================== MIGRACIONES ====================
        _migrate_old_data(cursor, conn)
        _ensure_columns(cursor, conn)

    logger.info(f"{Icons.SUCCESS} Base de datos unificada inicializada")


# ==================== MIGRACIÓN DE ESQUEMA ANTIGUO ====================
def _migrate_old_data(cursor, conn):

    try:
        cursor.execute("PRAGMA table_info(workers)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'chat_id' in columns and 'user_id' not in columns:

            logger.info(f"{Icons.WARNING} Detectado esquema antiguo, migrando...")

            cursor.execute('''
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
                    current_request_id INTEGER,
                    rating REAL DEFAULT 5.0,
                    total_jobs INTEGER DEFAULT 0,
                    last_update INTEGER,
                    created_at INTEGER DEFAULT (strftime('%s','now'))
                )
            ''')

            cursor.execute('''
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
            ''')

            cursor.execute("DROP TABLE workers")
            cursor.execute("ALTER TABLE workers_new RENAME TO workers")

            conn.commit()

            logger.info(f"{Icons.SUCCESS} Migración completada")

    except Exception as e:
        logger.error(f"Error en migración: {e}")


# ==================== MIGRACIÓN DE COLUMNAS ====================
def _ensure_columns(cursor, conn):

    try:

        # ---------- SESSIONS ----------
        cursor.execute("PRAGMA table_info(sessions)")
        columns = [c[1] for c in cursor.fetchall()]

        if "chat_id" not in columns:
            logger.info("Migrando sessions → chat_id")
            cursor.execute("ALTER TABLE sessions ADD COLUMN chat_id TEXT")

        if "last_activity" not in columns:
            logger.info("Migrando sessions → last_activity")
            cursor.execute("ALTER TABLE sessions ADD COLUMN last_activity INTEGER")

        # ---------- REQUESTS ----------
        cursor.execute("PRAGMA table_info(requests)")
        columns = [c[1] for c in cursor.fetchall()]

        if "worker_id" not in columns:
            logger.info("Migrando requests → worker_id")
            cursor.execute("ALTER TABLE requests ADD COLUMN worker_id INTEGER")

        if "client_id" not in columns:
            logger.info("Migrando requests → client_id")
            cursor.execute("ALTER TABLE requests ADD COLUMN client_id INTEGER")

        conn.commit()

    except Exception as e:
        logger.error(f"Error asegurando columnas: {e}")


# ==================== EJECUTAR CONSULTAS ====================
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

            return [dict(row) for row in cursor.fetchall()]

    except Exception as e:
        logger.error(f"DB Error: {e}")
        return None


# ==================== SESIONES ====================
def get_session(chat_id):

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT state,data FROM sessions WHERE user_id=? OR chat_id=?",
                (int(chat_id), str(chat_id))
            )

            row = cursor.fetchone()

            if row:
                try:
                    data = json.loads(row["data"]) if row["data"] else {}
                except:
                    data = {}

                return {
                    "state": row["state"],
                    "data": data
                }

            return None

    except Exception as e:
        logger.error(f"Error get_session: {e}")
        return None


def set_state(chat_id, state, data=None):

    try:

        data_json = json.dumps(data or {})
        timestamp = int(time.time())

        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO sessions(user_id,chat_id,state,data,last_activity,updated_at)
                VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    state=excluded.state,
                    data=excluded.data,
                    last_activity=excluded.last_activity,
                    updated_at=CURRENT_TIMESTAMP
            ''', (
                int(chat_id),
                str(chat_id),
                state,
                data_json,
                timestamp
            ))

            conn.commit()

    except Exception as e:
        logger.error(f"Error set_state: {e}")


def update_data(chat_id, **kwargs):

    session = get_session(chat_id) or {"state": None, "data": {}}
    session_data = session["data"]
    session_data.update(kwargs)

    set_state(chat_id, session["state"], session_data)


def clear_state(chat_id):

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


# ==================== MIGRACIÓN GRADUAL ====================
def ensure_worker_exists(chat_id, nombre="Trabajador"):

    try:

        with get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT user_id FROM workers WHERE user_id=? OR chat_id=?",
                (int(chat_id), str(chat_id))
            )

            if not cursor.fetchone():

                cursor.execute('''
                    INSERT INTO workers (user_id,chat_id,name,nombre,is_active,disponible)
                    VALUES (?,?,?,?,1,1)
                ''', (
                    int(chat_id),
                    str(chat_id),
                    nombre,
                    nombre
                ))

                conn.commit()

                logger.info(f"Worker {chat_id} creado automáticamente")

    except Exception as e:
        logger.error(f"Error ensure_worker: {e}")
