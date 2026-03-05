import os
import logging
import sqlite3
from contextlib import contextmanager

# ==================== LOGGING ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== VARIABLES ====================
# Token del bot (Railway o local)
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    logger.error("❌ BOT_TOKEN no definido en las variables de entorno")
    raise RuntimeError("Configura BOT_TOKEN en Railway Variables o .env local")

# Directorio base del proyecto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Archivo de la base de datos SQLite unificado
DB_FILE = os.path.join(BASE_DIR, "cleanygo_ux.db")

# ==================== BOT ====================
# Se inicializa luego en bot.py y se inyecta acá
bot = None

def inject_bot(bot_instance):
    """Inyecta la instancia del bot desde bot.py"""
    global bot
    bot = bot_instance
    logger.info("Bot inyectado en config")

# ==================== DATABASE ====================
@contextmanager
def get_db_connection():
    """Context manager para conexiones DB seguras"""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        yield conn
    except sqlite3.Error as e:
        logger.error(f"DB Connection Error: {e}")
        raise
    finally:
        if conn:
            conn.close()

def init_db():
    """Inicializa todas las tablas necesarias"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Tabla de workers
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
                current_request_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabla de servicios del worker
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS worker_services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                service_id TEXT,
                FOREIGN KEY (user_id) REFERENCES workers(user_id)
            )
        ''')
        
        # Tabla de solicitudes
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                service_id TEXT,
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
                completed_at TIMESTAMP
            )
        ''')
        
        # Tabla de sesiones de usuario
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                user_id INTEGER PRIMARY KEY,
                state TEXT,
                data TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabla de calificaciones
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER,
                rating INTEGER,
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabla de rechazos
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS request_rejections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER,
                worker_id INTEGER,
                rejected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (request_id, worker_id)
            )
        ''')
        
        conn.commit()
        logger.info("✅ Tablas creadas/verificadas")

# ==================== SESSION MANAGEMENT ====================
def get_state(user_id):
    """Obtiene el estado actual del usuario"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT state, data FROM sessions WHERE user_id = ?", 
                (user_id,)
            )
            row = cursor.fetchone()
            if row:
                import json
                return {
                    'state': row['state'],
                    'data': json.loads(row['data']) if row['data'] else {}
                }
            return None
    except Exception as e:
        logger.error(f"Error getting state for {user_id}: {e}")
        return None

def set_state(user_id, state, data=None):
    """Establece el estado del usuario"""
    try:
        import json
        with get_db_connection() as conn:
            cursor = conn.cursor()
            data_json = json.dumps(data) if data else '{}'
            cursor.execute('''
                INSERT INTO sessions (user_id, state, data, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    state = excluded.state,
                    data = excluded.data,
                    updated_at = CURRENT_TIMESTAMP
            ''', (user_id, state, data_json))
            conn.commit()
            logger.info(f"[DB] set_state: {user_id} -> {state}, keys={list(data.keys()) if data else []}")
    except Exception as e:
        logger.error(f"DB Error setting state for {user_id}: {e}")

def clear_state(user_id):
    """Limpia el estado del usuario"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            conn.commit()
            logger.info(f"[DB] clear_state: {user_id}")
    except Exception as e:
        logger.error(f"DB Error clearing state for {user_id}: {e}")

def get_data(user_id, key):
    """Obtiene un dato específico de la sesión"""
    session = get_state(user_id)
    if session and session.get('data'):
        return session['data'].get(key)
    return None

# ==================== NOTIFICATION SYSTEM (CORREGIDO) ====================
def notify_worker(worker_id, request_data):
    """
    Notifica a un worker sobre una nueva solicitud.
    CORREGIDO: Manejo seguro de valores nulos
    """
    if not bot:
        logger.error("Bot no inicializado")
        return False
    
    try:
        # Obtener info del worker con manejo seguro
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name, phone FROM workers WHERE user_id = ?", 
                (worker_id,)
            )
            worker = cursor.fetchone()
        
        if not worker:
            logger.error(f"Worker {worker_id} no encontrado")
            return False
        
        # ✅ CORRECCIÓN: Manejo seguro de valores nulos
        worker_name = worker['name'] or "Trabajador"
        worker_phone = worker['phone'] or "No disponible"
        
        # ✅ CORRECCIÓN: Manejo seguro de datos de la solicitud
        service_name = request_data.get('service_name') or "Servicio no especificado"
        request_time = request_data.get('request_time') or "Hora no especificada"
        time_period = request_data.get('time_period') or ""
        address = request_data.get('address') or "Dirección no compartida"
        
        # Construir mensaje de forma segura
        message = (
            f"🔔 <b>¡Nueva Solicitud!</b>\n\n"
            f"👤 <b>Cliente:</b> {request_data.get('client_name', 'Cliente')}\n"
            f"📋 <b>Servicio:</b> {service_name}\n"
            f"🕐 <b>Hora:</b> {request_time} {time_period}\n"
            f"📍 <b>Dirección:</b> {address}\n\n"
            f"¿Deseas aceptar esta solicitud?"
        )
        
        # Enviar notificación
        bot.send_message(
            chat_id=worker_id,
            text=message,
            parse_mode='HTML'
        )
        
        logger.info(f"✅ Notificación enviada a worker {worker_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error notificando a {worker_id}: {e}")
        return False

def notify_client(client_id, message):
    """Notifica al cliente"""
    if not bot:
        logger.error("Bot no inicializado")
        return False
    
    try:
        bot.send_message(chat_id=client_id, text=message, parse_mode='HTML')
        return True
    except Exception as e:
        logger.error(f"Error notificando a cliente {client_id}: {e}")
        return False

# ==================== REQUEST MANAGEMENT ====================
def create_request(client_id, service_data):
    """Crea una nueva solicitud y notifica a workers disponibles"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Insertar solicitud
            cursor.execute('''
                INSERT INTO requests 
                (client_id, service_id, service_name, request_time, time_period, lat, lon, address, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            ''', (
                client_id,
                service_data.get('service_id'),
                service_data.get('service_name'),
                service_data.get('selected_time'),
                service_data.get('time_period'),
                service_data.get('lat'),
                service_data.get('lon'),
                service_data.get('address', 'No especificada')
            ))
            
            request_id = cursor.lastrowid
            conn.commit()
            
            logger.info(f"[CREATE REQUEST] ID={request_id} cliente={client_id}, servicio={service_data.get('service_id')}")
            
            # Buscar workers disponibles para este servicio
            cursor.execute('''
                SELECT DISTINCT w.user_id 
                FROM workers w
                JOIN worker_services ws ON w.user_id = ws.user_id
                WHERE ws.service_id = ? 
                AND w.is_active = 1 
                AND w.current_request_id IS NULL
            ''', (service_data.get('service_id'),))
            
            available_workers = cursor.fetchall()
            
            # Notificar a cada worker disponible
            notified_count = 0
            for worker in available_workers:
                success = notify_worker(worker['user_id'], {
                    'request_id': request_id,
                    'service_name': service_data.get('service_name'),
                    'request_time': service_data.get('selected_time'),
                    'time_period': service_data.get('time_period'),
                    'address': service_data.get('address', 'No especificada'),
                    'client_name': 'Cliente'  # Podrías obtener el nombre real si lo guardas
                })
                if success:
                    notified_count += 1
            
            logger.info(f"Notificados {notified_count}/{len(available_workers)} workers disponibles")
            return request_id
            
    except Exception as e:
        logger.error(f"Error creando solicitud: {e}")
        raise
