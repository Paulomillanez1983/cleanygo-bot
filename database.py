import sqlite3
from config import DB_FILE, logger
from utils.icons import Icons

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # Tabla de trabajadores
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS workers (
                chat_id TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                dni_file_id TEXT,
                telefono TEXT,
                disponible INTEGER DEFAULT 1,
                lat REAL,
                lon REAL,
                last_update INTEGER,
                rating REAL DEFAULT 5.0,
                total_jobs INTEGER DEFAULT 0,
                created_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        ''')
        
        # Tabla de servicios con precios
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS worker_services (
                chat_id TEXT,
                service_id TEXT,
                precio REAL NOT NULL,
                PRIMARY KEY (chat_id, service_id),
                FOREIGN KEY (chat_id) REFERENCES workers(chat_id) ON DELETE CASCADE
            )
        ''')
        
        # Tabla de solicitudes
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_chat_id TEXT NOT NULL,
                service_id TEXT NOT NULL,
                fecha TEXT,
                hora TEXT,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                worker_chat_id TEXT,
                precio_acordado REAL,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                accepted_at INTEGER,
                completed_at INTEGER
            )
        ''')
        
        # Tabla de ratings
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER,
                from_chat_id TEXT,
                to_chat_id TEXT,
                rating INTEGER,
                comment TEXT,
                created_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        ''')
        
        conn.commit()
    logger.info(f"{Icons.SUCCESS} Base de datos inicializada")

def db_execute(query, params=(), fetch_one=False, commit=False):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            if commit:
                conn.commit()
            if fetch_one:
                return cursor.fetchone()
            return cursor.fetchall()
    except Exception as e:
        logger.error(f"DB Error: {e}")
        return None

