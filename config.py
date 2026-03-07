"""
Configuración central del bot CleanyGo.
VERSIÓN CORREGIDA - Thread-safe, sin race conditions.
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
    BRIEFCASE = "💼"
    PHONE = "📱"
    LOCATION = "📍"

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

# ==================== THREAD-SAFE DATABASE POOL ====================

class DatabasePool:
    """
    Pool de conexiones SQLite thread-safe.
    Cada hilo obtiene su propia conexión dedicada.
    """
    _local = threading.local()
    _init_lock = threading.Lock()
    _wal_enabled = False

    @classmethod
    def get_connection(cls):
        """Obtiene conexión dedicada para el hilo actual"""
        # Verificar si ya tenemos conexión para este hilo
        if not hasattr(cls._local, 'connection') or cls._local.connection is None:
            cls._local.connection = sqlite3.connect(
                DB_FILE,
                timeout=30.0,  # Esperar hasta 30s si está bloqueada
                check_same_thread=False,  # Permitir uso en diferentes threads
                isolation_level=None  # Autocommit para evitar bloqueos largos
            )
            cls._local.connection.row_factory = sqlite3.Row
            
            # Activar WAL mode una sola vez por conexión
            cls._local.connection.execute("PRAGMA journal_mode=WAL")
            cls._local.connection.execute("PRAGMA synchronous=NORMAL")
            cls._local.connection.execute("PRAGMA busy_timeout=30000")
            cls._local.connection.execute("PRAGMA foreign_keys=ON")
            
        return cls._local.connection

    @classmethod
    def close_connection(cls):
        """Cierra conexión del hilo actual"""
        if hasattr(cls._local, 'connection') and cls._local.connection:
            try:
                cls._local.connection.close()
            except:
                pass
            cls._local.connection = None


@contextmanager
def get_db_connection():
    """
    Context manager que usa el pool thread-safe.
    Maneja automáticamente commit/rollback.
    """
    conn = None
    try:
        conn = DatabasePool.get_connection()
        # Iniciar transacción explícita
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except sqlite3.OperationalError as e:
        if conn:
            conn.rollback()
        if "database is locked" in str(e):
            logger.warning(f"[DB LOCK] Base de datos bloqueada, reintentando...")
            raise  # Dejar que db_execute maneje el retry
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise
    # No cerramos la conexión aquí - se reutiliza por hilo

# ==================== DB INIT ====================

_db_init_lock = threading.Lock()
_db_initialized = False

def init_db():
    """Inicialización thread-safe de la base de datos"""
    global _db_initialized
    
    if _db_initialized:
        return

    with _db_init_lock:
        if _db_initialized:
            return

        try:
            logger.info("🚀 Inicializando DB")
            
            # Usar conexión temporal para inicialización
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

def _create_tables(cursor):
    """Crea tablas necesarias"""
    
    # Tabla de sesiones - USAR chat_id como PRIMARY KEY (TEXT)
    # Telegram chat_id puede ser muy grande, mejor como TEXT
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions(
            chat_id TEXT PRIMARY KEY,
            state TEXT DEFAULT 'IDLE',
            data TEXT DEFAULT '{}',
            last_activity INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT 0
        )
    """)
    
    # Tabla de workers
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workers(
            chat_id TEXT PRIMARY KEY,
            name TEXT,
            phone TEXT,
            dni TEXT,
            lat REAL,
            lon REAL,
            is_active INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT 0
        )
    """)
    
    # Tabla de servicios del worker
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS worker_services(
            chat_id TEXT,
            service_id TEXT,
            precio REAL DEFAULT 0,
            PRIMARY KEY (chat_id, service_id),
            FOREIGN KEY (chat_id) REFERENCES workers(chat_id) ON DELETE CASCADE
        )
    """)
    
    # Tabla de requests
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id TEXT,
            service_id TEXT,
            service_name TEXT,
            lat REAL,
            lon REAL,
            address TEXT,
            worker_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at INTEGER DEFAULT 0
        )
    """)

def _create_indexes(cursor):
    """Crea índices para performance"""
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_activity ON sessions(last_activity)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_worker_services ON worker_services(chat_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status)"
    )

# ==================== DB EXECUTE CON RETRY ====================

def db_execute(query, params=(), fetch_one=False, max_retries=3):
    """
    Ejecuta query con retry automático ante bloqueos.
    CRÍTICO: Maneja database is locked automáticamente.
    """
    last_error = None
    
    for attempt in range(max_retries):
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                
                if query.strip().upper().startswith("SELECT"):
                    if fetch_one:
                        row = cursor.fetchone()
                        return dict(row) if row else None
                    else:
                        rows = cursor.fetchall()
                        return [dict(r) for r in rows]
                else:
                    # INSERT/UPDATE/DELETE
                    return cursor.lastrowid if cursor.lastrowid else True
                    
        except sqlite3.OperationalError as e:
            last_error = e
            if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                wait_time = 0.05 * (2 ** attempt)  # Exponential backoff
                logger.warning(f"[DB LOCK] Reintentando en {wait_time}s (intento {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            logger.error(f"[DB ERROR] {e} | Query: {query[:100]}...")
            raise
            
        except Exception as e:
            logger.error(f"[DB ERROR] {e} | Query: {query[:100]}...")
            raise
    
    # Si agotamos reintentos
    raise last_error if last_error else sqlite3.OperationalError("Max retries exceeded")

# ==================== SESSION MANAGEMENT (CORREGIDO) ====================

class UserSession:
    """
    Gestión de sesiones thread-safe.
    CLAVE: Usa siempre chat_id como string (TEXT).
    """
    
    @staticmethod
    def _normalize_id(chat_id) -> str:
        """Normaliza cualquier ID a string consistente"""
        return str(int(chat_id)) if isinstance(chat_id, (int, float)) else str(chat_id)
    
    @staticmethod
    def _safe_json_loads(data_json: str) -> Dict:
        """Carga JSON con manejo de errores"""
        if not data_json or data_json == "" or data_json == "{}":
            return {}
        try:
            result = json.loads(data_json)
            return result if isinstance(result, dict) else {}
        except Exception as e:
            logger.warning(f"[JSON LOAD] Error parseando JSON: {e}, usando vacío")
            return {}
    
    @staticmethod
    def _safe_json_dumps(data: Dict) -> str:
        """Serializa a JSON con manejo de tipos"""
        def sanitize(obj):
            if isinstance(obj, dict):
                return {k: sanitize(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [sanitize(x) for x in obj]
            if isinstance(obj, (str, int, float, bool, type(None))):
                return obj
            return str(obj)
        
        try:
            return json.dumps(sanitize(data), ensure_ascii=False)
        except Exception as e:
            logger.error(f"[JSON DUMP] Error serializando: {e}")
            return "{}"

    @classmethod
    def get(cls, chat_id) -> Dict[str, Any]:
        """
        Obtiene sesión por chat_id.
        Siempre retorna dict válido, nunca None.
        """
        chat_id_str = cls._normalize_id(chat_id)
        
        try:
            row = db_execute(
                "SELECT state, data FROM sessions WHERE chat_id = ?",
                (chat_id_str,),
                fetch_one=True
            )
            
            if row:
                state = row.get("state") or "IDLE"
                data = cls._safe_json_loads(row.get("data") or "{}")
                return {"state": state, "data": data, "chat_id": chat_id_str}
            
            # No existe, retornar estructura vacía pero válida
            return {"state": "IDLE", "data": {}, "chat_id": chat_id_str}
            
        except Exception as e:
            logger.error(f"[SESSION GET] Error para {chat_id_str}: {e}")
            # Fallback absoluto
            return {"state": "IDLE", "data": {}, "chat_id": chat_id_str}

    @classmethod
    def set(cls, chat_id: int, state: str, data: Optional[Dict] = None) -> bool:
        """
        Establece estado y datos de sesión.
        Usa INSERT OR REPLACE para atomicidad.
        """
        chat_id_str = cls._normalize_id(chat_id)
        data = data if data is not None else {}
        
        if not isinstance(data, dict):
            logger.warning(f"[SESSION SET] Data no era dict ({type(data)}), convirtiendo")
            data = {}
        
        try:
            data_json = cls._safe_json_dumps(data)
            timestamp = int(time.time())
            
            # INSERT OR REPLACE es atómico en SQLite
            db_execute(
                """INSERT OR REPLACE INTO sessions 
                   (chat_id, state, data, last_activity, created_at) 
                   VALUES (?, ?, ?, ?, 
                       COALESCE((SELECT created_at FROM sessions WHERE chat_id=?), ?)
                   )""",
                (chat_id_str, state, data_json, timestamp, chat_id_str, timestamp)
            )
            
            logger.info(f"[STATE] {chat_id_str} -> {state}")
            return True
            
        except Exception as e:
            logger.error(f"[SESSION SET] Error para {chat_id_str}: {e}")
            return False

    @classmethod
    def update(cls, chat_id: int, **kwargs) -> bool:
        """Actualiza campos específicos preservando el resto"""
        chat_id_str = cls._normalize_id(chat_id)
        
        try:
            # Obtener actual
            current = cls.get(chat_id_str)
            current_data = current.get("data", {})
            
            if not isinstance(current_data, dict):
                current_data = {}
            
            # Merge
            new_data = current_data.copy()
            for k, v in kwargs.items():
                if v is not None:
                    new_data[k] = v
            
            # Guardar
            return cls.set(chat_id_str, current.get("state", "IDLE"), new_data)
            
        except Exception as e:
            logger.error(f"[SESSION UPDATE] Error para {chat_id_str}: {e}")
            return False

    @classmethod
    def clear(cls, chat_id: int) -> bool:
        """Elimina sesión completamente"""
        chat_id_str = cls._normalize_id(chat_id)
        
        try:
            db_execute(
                "DELETE FROM sessions WHERE chat_id = ?",
                (chat_id_str,)
            )
            logger.info(f"[CLEAR] Sesión eliminada para {chat_id_str}")
            return True
        except Exception as e:
            logger.error(f"[SESSION CLEAR] Error para {chat_id_str}: {e}")
            return False

    @classmethod
    def get_data(cls, chat_id: int, key: str, default=None):
        """Obtiene valor específico de data"""
        session = cls.get(chat_id)
        data = session.get("data", {})
        return data.get(key, default) if isinstance(data, dict) else default


# ==================== API COMPATIBLE (Funciones standalone) ====================

def get_session(chat_id):
    """API compatible - retorna dict con state y data"""
    return UserSession.get(chat_id)

def set_state(chat_id, state, data=None):
    """API compatible"""
    return UserSession.set(chat_id, state, data)

def update_data(chat_id, **kwargs):
    """API compatible"""
    return UserSession.update(chat_id, **kwargs)

def clear_state(chat_id):
    """API compatible"""
    return UserSession.clear(chat_id)

def get_data(chat_id, key, default=None):
    """API compatible"""
    return UserSession.get_data(chat_id, key, default)

# ==================== WORKERS ====================

def ensure_worker_exists(chat_id):
    """Verifica/crea worker si no existe"""
    chat_id_str = str(chat_id)
    
    try:
        existing = db_execute(
            "SELECT chat_id FROM workers WHERE chat_id = ?",
            (chat_id_str,),
            fetch_one=True
        )
        
        if existing:
            return True
            
        # Crear nuevo
        db_execute(
            "INSERT INTO workers (chat_id, is_active, created_at) VALUES (?, 0, ?)",
            (chat_id_str, int(time.time()))
        )
        logger.info(f"[WORKER] Creado nuevo worker: {chat_id_str}")
        return True
        
    except Exception as e:
        logger.error(f"[WORKER ENSURE] Error {chat_id_str}: {e}")
        return False

# ==================== NOTIFICATIONS ====================

class Notifier:
    @staticmethod
    def notify_worker(worker_chat_id, message_text, parse_mode="HTML"):
        """Envía notificación a un worker específico"""
        if not _bot_instance:
            return False
        
        try:
            _bot_instance.send_message(worker_chat_id, message_text, parse_mode=parse_mode)
            return True
        except Exception as e:
            logger.error(f"[NOTIFY] Error enviando a {worker_chat_id}: {e}")
            return False

notify_worker = Notifier.notify_worker

def broadcast_to_workers(service_id, message_text):
    """Notifica a todos los workers de un servicio"""
    try:
        workers = db_execute(
            "SELECT DISTINCT chat_id FROM worker_services WHERE service_id = ?",
            (service_id,),
            fetch_one=False
        )
        
        sent = 0
        for worker in workers:
            if Notifier.notify_worker(worker["chat_id"], message_text):
                sent += 1
        
        logger.info(f"[BROADCAST] Enviado a {sent}/{len(workers)} workers")
        return sent
        
    except Exception as e:
        logger.error(f"[BROADCAST] Error: {e}")
        return 0
