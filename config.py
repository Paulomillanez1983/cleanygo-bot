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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== VARIABLES DE ENTORNO ====================
def get_bot_token() -> str:
    """Obtiene el token del bot desde variables de entorno"""
    token = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("❌ BOT_TOKEN no definido en variables de entorno")
        raise RuntimeError("Configura BOT_TOKEN en Railway Variables o .env")
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
    """Context manager para conexiones SQLite seguras"""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE, timeout=20.0)  # Timeout para concurrencia
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")  # Activar FK constraints
        yield conn
        conn.commit()
    except sqlite3.Error as e:
        if conn:
            conn.rollback()
        logger.error(f"DB Error: {e}")
        raise
    finally:
        if conn:
            conn.close()

def init_db():
    """Inicializa el esquema de base de datos"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Workers
        cursor.execute('''
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
        ''')
        
        # Servicios que ofrece cada worker
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS worker_services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                service_id TEXT NOT NULL,
                UNIQUE(user_id, service_id),
                FOREIGN KEY (user_id) REFERENCES workers(user_id) ON DELETE CASCADE
            )
        ''')
        
        # Solicitudes/Requests
        cursor.execute('''
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
                FOREIGN KEY (worker_id) REFERENCES workers(user_id)
            )
        ''')
        
        # Índices para performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_requests_worker ON requests(worker_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_requests_client ON requests(client_id)')
        
        # Sesiones de usuario (estados del bot)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                user_id INTEGER PRIMARY KEY,
                state TEXT,
                data TEXT DEFAULT '{}',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Calificaciones
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL,
                from_user_id INTEGER,
                to_user_id INTEGER,
                rating INTEGER CHECK(rating >= 1 AND rating <= 5),
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Rechazos de solicitudes
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
        
        logger.info("✅ Base de datos inicializada correctamente")

# ==================== SESSION MANAGEMENT ====================
class UserSession:
    """Helper class para manejo de sesiones de usuario"""
    
    @staticmethod
    def get(user_id: int) -> Optional[Dict[str, Any]]:
        """Obtiene el estado y datos del usuario"""
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
                        'state': row['state'],
                        'data': json.loads(row['data']) if row['data'] else {}
                    }
                return None
        except Exception as e:
            logger.error(f"[SESSION GET ERROR] user_id={user_id}: {e}")
            return None
    
    @staticmethod
    def set(user_id: int, state: str, data: Dict = None):
        """Establece estado y datos del usuario"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                data_json = json.dumps(data or {})
                
                cursor.execute('''
                    INSERT INTO sessions (user_id, state, data, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id) DO UPDATE SET
                        state = excluded.state,
                        data = excluded.data,
                        updated_at = CURRENT_TIMESTAMP
                ''', (user_id, state, data_json))
                
                logger.info(f"[SESSION SET] {user_id} -> {state}")
        except Exception as e:
            logger.error(f"[SESSION SET ERROR] user_id={user_id}: {e}")
    
    @staticmethod
    def clear(user_id: int):
        """Elimina la sesión del usuario"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
                logger.info(f"[SESSION CLEAR] {user_id}")
        except Exception as e:
            logger.error(f"[SESSION CLEAR ERROR] user_id={user_id}: {e}")
    
    @staticmethod
    def get_data(user_id: int, key: str) -> Any:
        """Obtiene un valor específico de la sesión"""
        session = UserSession.get(user_id)
        if session and session.get('data'):
            return session['data'].get(key)
        return None

# Alias para compatibilidad con código existente
get_state = UserSession.get
set_state = UserSession.set
clear_state = UserSession.clear
get_data = UserSession.get_data

# ==================== NOTIFICATION SYSTEM ====================
class Notifier:
    """Sistema centralizado de notificaciones"""
    
    @staticmethod
    def _safe_get(data: Dict, key: str, default: str = "No especificado") -> str:
        """Obtiene valor seguro de diccionario"""
        value = data.get(key)
        return str(value) if value is not None else default
    
    @staticmethod
    def notify_worker(worker_id: int, request_data: Dict) -> bool:
        """
        Notifica a un worker sobre nueva solicitud.
        Manejo robusto de valores nulos para evitar errores de formato.
        """
        if not _bot_instance:
            logger.error("[NOTIFY] Bot no inicializado")
            return False
        
        try:
            # Obtener info del worker
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name, phone, is_active FROM workers WHERE user_id = ?", 
                    (worker_id,)
                )
                worker = cursor.fetchone()
            
            if not worker:
                logger.warning(f"[NOTIFY] Worker {worker_id} no existe")
                return False
            
            if not worker['is_active']:
                logger.info(f"[NOTIFY] Worker {worker_id} inactivo, saltando")
                return False
            
            # Construir mensaje con valores seguros
            worker_name = worker['name'] or "Trabajador"
            
            message = (
                f"🔔 <b>¡Nueva Solicitud de Servicio!</b>\n\n"
                f"📋 <b>Servicio:</b> {Notifier._safe_get(request_data, 'service_name')}\n"
                f"🕐 <b>Hora:</b> {Notifier._safe_get(request_data, 'request_time')} "
                f"{Notifier._safe_get(request_data, 'time_period')}\n"
                f"📍 <b>Ubicación:</b> {Notifier._safe_get(request_data, 'address')}\n\n"
                f"¿Aceptas este trabajo?"
            )
            
            # Enviar con botón de acción (opcional, si quieres inline keyboard)
            _bot_instance.send_message(
                chat_id=worker_id,
                text=message,
                parse_mode='HTML'
            )
            
            logger.info(f"[NOTIFY] ✅ Worker {worker_id} notificado (request: {request_data.get('request_id')})")
            return True
            
        except Exception as e:
            logger.error(f"[NOTIFY ERROR] worker_id={worker_id}: {e}")
            return False
    
    @staticmethod
    def notify_client(client_id: int, message: str, parse_mode: str = 'HTML') -> bool:
        """Envía notificación a cliente"""
        if not _bot_instance:
            logger.error("[NOTIFY] Bot no inicializado")
            return False
        
        try:
            _bot_instance.send_message(
                chat_id=client_id,
                text=message,
                parse_mode=parse_mode
            )
            return True
        except Exception as e:
            logger.error(f"[NOTIFY CLIENT ERROR] client_id={client_id}: {e}")
            return False
    
    @staticmethod
    def broadcast_to_workers(service_id: str, request_data: Dict) -> int:
        """
        Notifica a todos los workers disponibles para un servicio.
        Retorna cantidad de notificaciones exitosas.
        """
        notified = 0
        
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT DISTINCT w.user_id 
                    FROM workers w
                    JOIN worker_services ws ON w.user_id = ws.user_id
                    WHERE ws.service_id = ? 
                    AND w.is_active = 1 
                    AND (w.current_request_id IS NULL OR w.current_request_id = 0)
                ''', (service_id,))
                
                workers = cursor.fetchall()
            
            for worker in workers:
                if Notifier.notify_worker(worker['user_id'], request_data):
                    notified += 1
            
            logger.info(f"[BROADCAST] {notified}/{len(workers)} workers notificados para {service_id}")
            return notified
            
        except Exception as e:
            logger.error(f"[BROADCAST ERROR]: {e}")
            return 0

# Alias para uso directo
notify_worker = Notifier.notify_worker
notify_client = Notifier.notify_client
broadcast_to_workers = Notifier.broadcast_to_workers
# ==================== COMPATIBILIDAD HACIA ATRÁS ====================
# Permite que handlers importen 'bot' directamente después de inject_bot()

def __getattr__(name):
    """Intercepta import config.bot y devuelve la instancia inyectada"""
    global _bot_instance
    if name == 'bot':
        if _bot_instance is None:
            raise RuntimeError(
                "Bot no inicializado. "
                "Asegúrate de llamar config.inject_bot(bot) antes de importar handlers"
            )
        return _bot_instance
    raise AttributeError(f"module 'config' has no attribute '{name}'")
