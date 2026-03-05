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

        # ==================== TABLA WORKERS (UNIFICADA) ====================
        # Usa user_id (INTEGER) como en config.py, pero mantiene chat_id para compatibilidad
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS workers (
                user_id INTEGER PRIMARY KEY,
                chat_id TEXT UNIQUE,  -- Para compatibilidad hacia atrás
                name TEXT,
                nombre TEXT,          -- Alias para compatibilidad
                phone TEXT,
                telefono TEXT,        -- Alias para compatibilidad
                email TEXT,
                address TEXT,
                dni_file_id TEXT,
                lat REAL,
                lon REAL,
                is_active BOOLEAN DEFAULT 1,
                disponible INTEGER DEFAULT 1,  -- Alias para compatibilidad
                current_request_id INTEGER DEFAULT NULL,
                rating REAL DEFAULT 5.0,
                total_jobs INTEGER DEFAULT 0,
                last_update INTEGER,
                created_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        ''')

        # ==================== TABLA WORKER_SERVICES (UNIFICADA) ====================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS worker_services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                chat_id TEXT,  -- Para compatibilidad
                service_id TEXT NOT NULL,
                precio REAL DEFAULT 0,
                UNIQUE(user_id, service_id),
                FOREIGN KEY (user_id) REFERENCES workers(user_id) ON DELETE CASCADE
            )
        ''')

        # ==================== TABLA REQUESTS (UNIFICADA) ====================
        # Combina campos de ambos esquemas
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,           -- Nuevo esquema
                client_chat_id TEXT,           -- Compatibilidad antigua
                service_id TEXT NOT NULL,
                service_name TEXT,
                request_time TEXT,             -- Nuevo esquema
                time_period TEXT,              -- Nuevo esquema
                fecha TEXT,                    -- Compatibilidad
                hora TEXT,                     -- Compatibilidad
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                address TEXT,
                worker_id INTEGER,             -- Nuevo esquema
                worker_chat_id TEXT,           -- Compatibilidad
                status TEXT DEFAULT 'pending',
                precio_acordado REAL,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                accepted_at INTEGER,
                completed_at INTEGER,
                FOREIGN KEY (worker_id) REFERENCES workers(user_id)
            )
        ''')

        # ==================== TABLA RATINGS (UNIFICADA) ====================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER,
                from_user_id INTEGER,
                to_user_id INTEGER,
                from_chat_id TEXT,  -- Compatibilidad
                to_chat_id TEXT,    -- Compatibilidad
                rating INTEGER,
                comment TEXT,
                created_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        ''')

        # ==================== TABLA SESSIONS (UNIFICADA) ====================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                user_id INTEGER PRIMARY KEY,
                chat_id TEXT UNIQUE,  -- Compatibilidad
                state TEXT,
                data TEXT DEFAULT '{}',
                last_activity INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # ==================== TABLA REJECTIONS (NUEVA) ====================
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

        conn.commit()

        # ==================== MIGRACIÓN DE DATOS (si es necesario) ====================
        _migrate_old_data(cursor, conn)

    logger.info(f"{Icons.SUCCESS} Base de datos unificada inicializada")

def _migrate_old_data(cursor, conn):
    """
    Migra datos del esquema antiguo al nuevo si existen
    """
    try:
        # Verificar si existe tabla antigua con estructura diferente
        cursor.execute("PRAGMA table_info(workers)")
        columns = [col[1] for col in cursor.fetchall()]
        
        # Si existe chat_id pero no user_id, necesitamos migrar
        if 'chat_id' in columns and 'user_id' not in columns:
            logger.info(f"{Icons.WARNING} Detectado esquema antiguo, migrando...")
            
            # Crear tabla temporal con nuevo esquema
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS workers_new (
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
                    created_at INTEGER DEFAULT (strftime('%s', 'now'))
                )
            ''')
            
            # Migrar datos: chat_id -> user_id (convertir a int)
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
            
            # Reemplazar tabla
            cursor.execute("DROP TABLE workers")
            cursor.execute("ALTER TABLE workers_new RENAME TO workers")
            
            conn.commit()
            logger.info(f"{Icons.SUCCESS} Migración completada")
            
    except Exception as e:
        logger.error(f"Error en migración: {e}")

# ==================== EJECUTAR CONSULTAS (COMPATIBILIDAD) ====================
def db_execute(query, params=(), fetch_one=False, commit=False):
    """
    Ejecuta consultas SQL de manera segura.
    Mantiene compatibilidad con código antiguo.
    """
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

# ==================== FUNCIONES DE SESIÓN (COMPATIBILIDAD) ====================
def get_session(chat_id):
    """
    Obtiene sesión por chat_id (compatibilidad con código antiguo)
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Buscar por user_id o chat_id
            cursor.execute('''
                SELECT state, data FROM sessions 
                WHERE user_id = ? OR chat_id = ?
            ''', (int(chat_id), str(chat_id)))
            row = cursor.fetchone()
            
            if row:
                state, data_json = row['state'], row['data']
                try:
                    data = json.loads(data_json) if data_json else {}
                except:
                    data = {}
                return {"state": state, "data": data}
            return None
    except Exception as e:
        logger.error(f"Error get_session: {e}")
        return None

def set_state(chat_id, state, data=None):
    """
    Establece estado por chat_id (compatibilidad)
    """
    try:
        data_json = json.dumps(data or {})
        timestamp = int(time.time())
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO sessions(user_id, chat_id, state, data, last_activity, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    state=excluded.state,
                    data=excluded.data,
                    last_activity=excluded.last_activity,
                    updated_at=CURRENT_TIMESTAMP
            ''', (int(chat_id), str(chat_id), state, data_json, timestamp))
            conn.commit()
    except Exception as e:
        logger.error(f"Error set_state: {e}")

def update_data(chat_id, **kwargs):
    """
    Actualiza datos de sesión (compatibilidad)
    """
    session = get_session(chat_id) or {"state": None, "data": {}}
    session_data = session["data"]
    session_data.update(kwargs)
    set_state(chat_id, session["state"], session_data)

def clear_state(chat_id):
    """
    Limpia sesión por chat_id (compatibilidad)
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM sessions WHERE user_id = ? OR chat_id = ?", 
                (int(chat_id), str(chat_id))
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Error clear_state: {e}")

# ==================== FUNCIONES AUXILIARES PARA MIGRACIÓN ====================
def ensure_worker_exists(chat_id, nombre="Trabajador"):
    """
    Asegura que un worker exista en la tabla (para migración gradual)
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT user_id FROM workers WHERE user_id = ? OR chat_id = ?", 
                (int(chat_id), str(chat_id))
            )
            if not cursor.fetchone():
                # Crear worker con ambos IDs
                cursor.execute('''
                    INSERT INTO workers (user_id, chat_id, name, nombre, is_active, disponible)
                    VALUES (?, ?, ?, ?, 1, 1)
                ''', (int(chat_id), str(chat_id), nombre, nombre))
                conn.commit()
                logger.info(f"Worker {chat_id} creado automáticamente")
    except Exception as e:
        logger.error(f"Error ensure_worker: {e}")
