import telebot
from telebot import types
import math
import time
import logging
import sqlite3
import os
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Dict

# ==================== CONFIGURACIÓN ====================
TOKEN = os.getenv("BOT_TOKEN", "8534288619:AAG1i5-PdjUABerTQCp_y84XubBfVNJ34FU")
DB_FILE = "cleanygo_ux.db"

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== EMOJIS Y ESTILOS ====================
class Icons:
    WAVE = "👋"
    SUCCESS = "✅"
    ERROR = "❌"
    WARNING = "⚠️"
    INFO = "ℹ️"
    MONEY = "💰"
    LOCATION = "📍"
    TIME = "⏰"
    USER = "👤"
    CAMERA = "📷"
    CHECK = "✓"
    CROSS = "✗"
    PENDING = "⏳"
    SEARCH = "🔍"
    STAR = "⭐"
    BELL = "🛎️"
    BRIEFCASE = "💼"
    BABY = "👶"
    ELDER = "🧓"
    SNOW = "❄️"
    TOOLS = "🔧"
    CAR = "🚗"
    HOME = "🏠"
    PHONE = "📱"
    MAP = "🗺️"
    CALENDAR = "📅"
    CLOCK = "🕐"
    BACK = "◀️"
    NEXT = "▶️"
    REFRESH = "🔄"
    OFFLINE = "😴"
    ONLINE = "🟢"
    PARTY = "🎉"
    LOCK = "🔒"

# ==================== SERVICIOS CON ICONOS ====================
SERVICES = {
    "niñera": {"name": "Niñera", "icon": Icons.BABY, "desc": "Cuidado de niños"},
    "cuidado": {"name": "Cuidado de personas", "icon": Icons.ELDER, "desc": "Adultos mayores"},
    "ac_inst": {"name": "Instalación A/C", "icon": Icons.SNOW, "desc": "Aire acondicionado"},
    "ac_tech": {"name": "Visita técnica A/C", "icon": Icons.TOOLS, "desc": "Reparación/mantenimiento"}
}

# ==================== BASE DE DATOS ====================
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # Tabla de trabajadores mejorada
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
        
        # Tabla de solicitudes mejorada
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

# ==================== GESTIÓN DE ESTADOS MEJORADA ====================
class UserState(Enum):
    IDLE = "idle"
    SELECTING_ROLE = "selecting_role"
    WORKER_SELECTING_SERVICES = "worker_selecting_services"
    WORKER_ENTERING_PRICE = "worker_entering_price"
    WORKER_ENTERING_NAME = "worker_entering_name"
    WORKER_ENTERING_PHONE = "worker_entering_phone"
    WORKER_UPLOADING_DNI = "worker_uploading_dni"
    WORKER_SHARING_LOCATION = "worker_sharing_location"
    CLIENT_SELECTING_SERVICE = "client_selecting_service"
    CLIENT_SELECTING_DATE = "client_selecting_date"
    CLIENT_SELECTING_TIME = "client_selecting_time"
    CLIENT_SHARING_LOCATION = "client_sharing_location"
    CLIENT_CONFIRMING = "client_confirming"
    CLIENT_WAITING_ACCEPTANCE = "client_waiting_acceptance"
    JOB_IN_PROGRESS = "job_in_progress"

@dataclass
class UserSession:
    state: UserState
    data: Dict
    last_activity: float
    
    def __init__(self, state=UserState.IDLE, data=None):
        self.state = state
        self.data = data or {}
        self.last_activity = time.time()

user_sessions: Dict[str, UserSession] = {}

def get_session(chat_id: str) -> UserSession:
    chat_id = str(chat_id)
    if chat_id not in user_sessions:
        user_sessions[chat_id] = UserSession()
    return user_sessions[chat_id]

def set_state(chat_id: str, state: UserState, data: Dict = None):
    session = get_session(chat_id)
    session.state = state
    if data:
        session.data.update(data)
    session.last_activity = time.time()

def clear_state(chat_id: str):
    user_sessions.pop(str(chat_id), None)

def update_data(chat_id: str, **kwargs):
    session = get_session(chat_id)
    session.data.update(kwargs)

def get_data(chat_id: str, key: str, default=None):
    return get_session(chat_id).data.get(key, default)

# ==================== UTILIDADES UX ====================
def send_safe(chat_id, text, reply_markup=None, parse_mode="HTML"):
    try:
        return bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Error sending to {chat_id}: {e}")
        return None

def edit_safe(chat_id, message_id, text, reply_markup=None):
    try:
        return bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error editing message {message_id}: {e}")
        return None

def delete_safe(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass

def show_loading(chat_id, text="Procesando..."):
    """Muestra un indicador de carga animado"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"{Icons.PENDING} {text}", callback_data="loading"))
    return send_safe(chat_id, f"<i>{Icons.PENDING} {text}</i>", markup)

def remove_keyboard(chat_id, text=""):
    """Elimina el teclado de manera limpia"""
    markup = types.ReplyKeyboardRemove()
    return send_safe(chat_id, text, markup)

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def format_price(price: float) -> str:
    return f"${price:,.0f}".replace(",", ".")

def get_service_display(service_id: str, with_price: float = None) -> str:
    svc = SERVICES.get(service_id, {})
    text = f"{svc.get('icon', '🔹')} <b>{svc.get('name', service_id)}</b>"
    if with_price:
        text += f"\n   <code>{format_price(with_price)}/hora</code>"
    return text

# ==================== TECLADOS UX MEJORADOS ====================
def get_role_keyboard():
    """Teclado de selección de rol con descripciones"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(
        types.KeyboardButton(f"{Icons.BELL} Necesito un servicio"),
        types.KeyboardButton(f"{Icons.BRIEFCASE} Quiero trabajar"),
        types.KeyboardButton(f"{Icons.INFO} Ayuda")
    )
    return markup

def get_cancel_keyboard(text="Cancelar"):
    """Teclado de cancelación siempre disponible"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton(f"{Icons.ERROR} {text}"))
    return markup

def get_location_keyboard(text="📍 Enviar mi ubicación"):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton(text, request_location=True))
    markup.add(types.KeyboardButton(f"{Icons.ERROR} Cancelar"))
    return markup

def get_service_selector(chat_id: str, selected: List[str] = None) -> types.InlineKeyboardMarkup:
    """Selector de servicios con toggles visuales"""
    if selected is None:
        selected = get_data(chat_id, "selected_services", [])
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for svc_id, svc in SERVICES.items():
        is_selected = svc_id in selected
        icon = Icons.CHECK if is_selected else Icons.CROSS
        text = f"{icon} {svc['icon']} {svc['name']}"
        callback = f"svc_toggle:{svc_id}"
        markup.add(types.InlineKeyboardButton(text, callback_data=callback))
    
    if selected:
        markup.add(types.InlineKeyboardButton(
            f"{Icons.SUCCESS} Confirmar ({len(selected)})", 
            callback_data="svc_confirm"
        ))
    
    return markup

def get_time_selector() -> types.InlineKeyboardMarkup:
    """Selector de hora TODO EN UN SOLO MENÚ (mejora UX principal)"""
    markup = types.InlineKeyboardMarkup(row_width=4)
    
    # Horas populares primero
    popular_hours = [8, 9, 10, 14, 15, 16, 17, 18]
    hour_buttons = []
    for h in popular_hours:
        hour_buttons.append(types.InlineKeyboardButton(
            f"{h:02d}:00", callback_data=f"time_quick:{h}:00"
        ))
    markup.add(*hour_buttons)
    
    # Opción "Otra hora" para personalizar
    markup.add(types.InlineKeyboardButton(
        f"{Icons.CLOCK} Elegir otra hora...", callback_data="time_custom"
    ))
    
    return markup

def get_custom_time_selector(step="hour", value=None) -> types.InlineKeyboardMarkup:
    """Selector de hora personalizado paso a paso"""
    markup = types.InlineKeyboardMarkup(row_width=4)
    
    if step == "hour":
        buttons = []
        for h in range(0, 24, 2):
            btn_text = f"{h:02d}:00"
            buttons.append(types.InlineKeyboardButton(
                btn_text, callback_data=f"time_h:{h}"
            ))
        markup.add(*buttons[:6])
        markup.add(*buttons[6:12])
        markup.add(*buttons[12:18])
        markup.add(*buttons[18:])
        
    elif step == "minute":
        markup.add(
            types.InlineKeyboardButton("00", callback_data=f"time_m:{value}:00"),
            types.InlineKeyboardButton("15", callback_data=f"time_m:{value}:15"),
            types.InlineKeyboardButton("30", callback_data=f"time_m:{value}:30"),
            types.InlineKeyboardButton("45", callback_data=f"time_m:{value}:45")
        )
        markup.add(types.InlineKeyboardButton(f"{Icons.BACK} Cambiar hora", callback_data="time_back_hour"))
        
    elif step == "ampm":
        hour, minute = value.split(":")
        markup.add(
            types.InlineKeyboardButton(f"🌅 AM ({hour}:{minute} AM)", callback_data=f"time_final:{value}:AM"),
            types.InlineKeyboardButton(f"🌙 PM ({hour}:{minute} PM)", callback_data=f"time_final:{value}:PM")
        )
        markup.add(types.InlineKeyboardButton(f"{Icons.BACK} Cambiar minutos", callback_data=f"time_back_min:{hour}"))
    
    markup.add(types.InlineKeyboardButton(f"{Icons.ERROR} Cancelar", callback_data="time_cancel"))
    return markup

def get_confirmation_keyboard() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(f"{Icons.SUCCESS} Sí, confirmar", callback_data="confirm_yes"),
        types.InlineKeyboardButton(f"{Icons.ERROR} No, corregir", callback_data="confirm_no")
    )
    return markup

def get_job_response_keyboard(request_id: int) -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(f"{Icons.SUCCESS} Aceptar", callback_data=f"job_accept:{request_id}"),
        types.InlineKeyboardButton(f"{Icons.ERROR} Rechazar", callback_data=f"job_reject:{request_id}")
    )
    return markup

# ==================== FLUJO PRINCIPAL MEJORADO ====================
@bot.message_handler(commands=['start'])
def cmd_start(message):
    chat_id = message.chat.id
    clear_state(chat_id)
    
    welcome_text = f"""
{Icons.WAVE} <b>¡Bienvenido a CleanyGo!</b>

Conectamos personas que necesitan servicios con profesionales confiables cerca de ti.

<b>¿Qué necesitás hacer?</b>
    """
    
    msg = send_safe(chat_id, welcome_text, get_role_keyboard())
    set_state(chat_id, UserState.SELECTING_ROLE)

@bot.message_handler(func=lambda m: m.text and ("Necesito" in m.text or "servicio" in m.text.lower()))
def handle_client_start(message):
    start_client_flow(message.chat.id)

@bot.message_handler(func=lambda m: m.text and ("trabajar" in m.text.lower() or "prestador" in m.text.lower()))
def handle_worker_start(message):
    start_worker_flow(message.chat.id)

def start_client_flow(chat_id: str):
    """Inicia flujo de cliente con UX mejorada"""
    set_state(chat_id, UserState.CLIENT_SELECTING_SERVICE)
    
    text = f"""
{Icons.SEARCH} <b>¿Qué servicio necesitás?</b>

Seleccioná una opción:
    """
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    for svc_id, svc in SERVICES.items():
        markup.add(types.InlineKeyboardButton(
            f"{svc['icon']} {svc['name']}\n<i>{svc['desc']}</i>", 
            callback_data=f"client_svc:{svc_id}"
        ))
    
    send_safe(chat_id, text, markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("client_svc:"))
def handle_client_service_selection(call):
    chat_id = call.message.chat.id
    service_id = call.data.split(":")[1]
    
    set_state(chat_id, UserState.CLIENT_SELECTING_TIME, {
        "service_id": service_id,
        "service_name": SERVICES[service_id]["name"]
    })
    
    bot.answer_callback_query(call.id, f"Seleccionaste: {SERVICES[service_id]['name']}")
    
    text = f"""
{Icons.CLOCK} <b>¿Para qué hora lo necesitás?</b>

Servicio: {get_service_display(service_id)}

<b>Opciones rápidas:</b>
    """
    
    edit_safe(chat_id, call.message.message_id, text, get_time_selector())

@bot.callback_query_handler(func=lambda c: c.data.startswith("time_quick:"))
def handle_quick_time(call):
    chat_id = call.message.chat.id
    time_str = call.data.split(":")[1] + ":" + call.data.split(":")[2]
    
    update_data(chat_id, selected_time=time_str, time_period="PM")  # Default PM para servicios
    
    bot.answer_callback_query(call.id, f"Hora: {time_str} PM")
    
    proceed_to_location(chat_id, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "time_custom")
def handle_custom_time_start(call):
    chat_id = call.message.chat.id
    
    text = f"""
{Icons.CLOCK} <b>Seleccioná la hora:</b>

Elegí la hora de inicio:
    """
    
    edit_safe(chat_id, call.message.message_id, text, get_custom_time_selector("hour"))

@bot.callback_query_handler(func=lambda c: c.data.startswith("time_h:"))
def handle_hour_selection(call):
    chat_id = call.message.chat.id
    hour = call.data.split(":")[1]
    
    text = f"""
{Icons.CLOCK} <b>Seleccioná los minutos:</b>

Hora: {hour}:__
    """
    
    edit_safe(chat_id, call.message.message_id, text, get_custom_time_selector("minute", hour))

@bot.callback_query_handler(func=lambda c: c.data.startswith("time_m:"))
def handle_minute_selection(call):
    chat_id = call.message.chat.id
    parts = call.data.split(":")
    hour = parts[1]
    minute = parts[2]
    time_str = f"{hour}:{minute}"
    
    text = f"""
{Icons.CLOCK} <b>¿AM o PM?</b>

Hora seleccionada: {time_str}
    """
    
    edit_safe(chat_id, call.message.message_id, text, get_custom_time_selector("ampm", time_str))

@bot.callback_query_handler(func=lambda c: c.data.startswith("time_final:"))
def handle_final_time(call):
    chat_id = call.message.chat.id
    parts = call.data.split(":")
    time_str = f"{parts[1]}:{parts[2]}"
    period = parts[3]
    
    update_data(chat_id, selected_time=time_str, time_period=period)
    
    bot.answer_callback_query(call.id, f"✓ {time_str} {period}")
    
    proceed_to_location(chat_id, call.message.message_id)

def proceed_to_location(chat_id: str, message_id: int):
    """Pasa a solicitar ubicación"""
    set_state(chat_id, UserState.CLIENT_SHARING_LOCATION)
    
    service_id = get_data(chat_id, "service_id")
    time_str = get_data(chat_id, "selected_time")
    period = get_data(chat_id, "time_period")
    
    text = f"""
{Icons.LOCATION} <b>Último paso: Ubicación</b>

📋 <b>Resumen de tu solicitud:</b>
• Servicio: {get_service_display(service_id)}
• Hora: {time_str} {period}

{Icons.INFO} Enviá tu ubicación para encontrar profesionales cercanos:
    """
    
    # Eliminar mensaje anterior y enviar nuevo con teclado de ubicación
    delete_safe(chat_id, message_id)
    send_safe(chat_id, text, get_location_keyboard())

@bot.message_handler(content_types=['location'], func=lambda m: get_session(m.chat.id).state == UserState.CLIENT_SHARING_LOCATION)
def handle_client_location(message):
    chat_id = message.chat.id
    lat = message.location.latitude
    lon = message.location.longitude
    
    update_data(chat_id, lat=lat, lon=lon, location_shared=True)
    
    # Mostrar confirmación
    service_id = get_data(chat_id, "service_id")
    time_str = get_data(chat_id, "selected_time")
    period = get_data(chat_id, "time_period")
    
    confirmation_text = f"""
{Icons.CALENDAR} <b>Confirma tu solicitud</b>

{get_service_display(service_id)}
{Icons.TIME} <b>Hora:</b> {time_str} {period}
{Icons.LOCATION} <b>Ubicación:</b> Recibida ✓

¿Todo correcto?
    """
    
    set_state(chat_id, UserState.CLIENT_CONFIRMING)
    remove_keyboard(chat_id)
    send_safe(chat_id, confirmation_text, get_confirmation_keyboard())

@bot.callback_query_handler(func=lambda c: c.data == "confirm_yes")
def handle_confirm_request(call):
    chat_id = call.message.chat.id
    
    # Crear solicitud en DB
    service_id = get_data(chat_id, "service_id")
    time_str = get_data(chat_id, "selected_time")
    period = get_data(chat_id, "time_period")
    lat = get_data(chat_id, "lat")
    lon = get_data(chat_id, "lon")
    hora_completa = f"{time_str} {period}"
    
    result = db_execute(
        """INSERT INTO requests (client_chat_id, service_id, hora, lat, lon, status) 
           VALUES (?, ?, ?, ?, ?, 'searching')""",
        (str(chat_id), service_id, hora_completa, lat, lon),
        commit=True
    )
    
    if result is None:
        bot.answer_callback_query(call.id, "Error al crear solicitud")
        return
    
    request_id = db_execute("SELECT last_insert_rowid()", fetch_one=True)[0]
    
    bot.answer_callback_query(call.id, "¡Buscando profesionales!")
    
    # Mensaje de búsqueda animado
    search_text = f"""
{Icons.SEARCH} <b>Buscando profesionales...</b>

{Icons.PENDING} Estamos buscando {SERVICES[service_id]['name']}s cerca de tu ubicación.

{Icons.TIME} Esto tomará unos segundos...
    """
    
    edit_safe(chat_id, call.message.message_id, search_text)
    
    # Buscar trabajadores cercanos
    workers = find_nearby_workers(service_id, lat, lon)
    
    if not workers:
        no_workers_text = f"""
{Icons.WARNING} <b>No encontramos profesionales cercanos</b>

No hay {SERVICES[service_id]['name']}s disponibles en tu zona en este momento.

{Icons.INFO} ¿Querés intentar con otro horario o servicio?
        """
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔄 Intentar de nuevo", callback_data="retry_search"))
        markup.add(types.InlineKeyboardButton("◀️ Volver al inicio", callback_data="back_start"))
        
        edit_safe(chat_id, call.message.message_id, no_workers_text, markup)
        return
    
    # Notificar a trabajadores
    notified = 0
    for worker in workers:
        try:
            notify_worker(worker, request_id, service_id, hora_completa, lat, lon)
            notified += 1
        except Exception as e:
            logger.error(f"Error notificando a {worker[0]}: {e}")
    
    # Actualizar estado
    db_execute("UPDATE requests SET status='waiting_acceptance' WHERE id=?", (request_id,), commit=True)
    set_state(chat_id, UserState.CLIENT_WAITING_ACCEPTANCE, {"request_id": request_id})
    
    waiting_text = f"""
{Icons.SUCCESS} <b>¡Solicitud enviada!</b>

{Icons.INFO} Hemos notificado a <b>{notified}</b> profesionales cercanos.

{Icons.PENDING} Esperando que acepten tu solicitud...

{Icons.TIME} Tiempo estimado: 2-3 minutos
    """
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"{Icons.ERROR} Cancelar solicitud", callback_data=f"cancel_req:{request_id}"))
    
    edit_safe(chat_id, call.message.message_id, waiting_text, markup)

def find_nearby_workers(service_id: str, lat: float, lon: float, radius_km: float = 10.0):
    """Encuentra trabajadores cercanos disponibles"""
    workers = db_execute(
        """SELECT w.chat_id, w.nombre, w.lat, w.lon, w.rating, ws.precio 
           FROM workers w
           JOIN worker_services ws ON w.chat_id = ws.chat_id
           WHERE ws.service_id = ? AND w.disponible = 1 
           AND w.lat IS NOT NULL AND w.lon IS NOT NULL""",
        (service_id,)
    )
    
    if not workers:
        return []
    
    # Calcular distancias y filtrar
    nearby = []
    for w in workers:
        dist = haversine(lat, lon, w[2], w[3])
        if dist <= radius_km:
            nearby.append((*w, dist))
    
    # Ordenar por distancia
    nearby.sort(key=lambda x: x[6])
    return nearby

def notify_worker(worker, request_id, service_id, hora, lat, lon):
    """Notifica al trabajador de nuevo trabajo"""
    worker_id, nombre, w_lat, w_lon, rating, precio = worker[:6]
    dist = worker[6] if len(worker) > 6 else 0
    
    # Crear enlace a Google Maps
    maps_url = f"https://www.google.com/maps?q={lat},{lon}"
    
    text = f"""
{Icons.BELL} <b>¡Nuevo trabajo disponible!</b>

{get_service_display(service_id)}
{Icons.TIME} <b>Hora:</b> {hora}
{Icons.MONEY} <b>Tu precio:</b> {format_price(precio)}/hora
{Icons.LOCATION} <b>Distancia:</b> {dist:.1f} km

{Icons.INFO} ¿Aceptás este trabajo?
    """
    
    markup = get_job_response_keyboard(request_id)
    markup.add(types.InlineKeyboardButton(f"{Icons.MAP} Ver en mapa", url=maps_url))
    
    send_safe(worker_id, text, markup)

# ==================== FLUJO TRABAJADOR MEJORADO ====================
def start_worker_flow(chat_id: str):
    """Inicia registro de trabajador"""
    # Verificar si ya está registrado
    worker = db_execute("SELECT * FROM workers WHERE chat_id = ?", (str(chat_id),), fetch_one=True)
    
    if worker:
        # Ya registrado, mostrar menú de trabajador
        show_worker_menu(chat_id, worker)
        return
    
    # Nuevo registro
    set_state(chat_id, UserState.WORKER_SELECTING_SERVICES, {"selected_services": []})
    
    welcome_text = f"""
{Icons.BRIEFCASE} <b>Registro de Profesional</b>

¡Excelente! Vamos a configurar tu perfil para que puedas recibir trabajos.

<b>Paso 1/5:</b> ¿Qué servicios ofrecés?
{Icons.INFO} Podés seleccionar varios
    """
    
    send_safe(chat_id, welcome_text, get_service_selector(chat_id))

@bot.callback_query_handler(func=lambda c: c.data.startswith("svc_toggle:"))
def handle_service_toggle(call):
    chat_id = call.message.chat.id
    service_id = call.data.split(":")[1]
    
    session = get_session(chat_id)
    selected = session.data.get("selected_services", [])
    
    if service_id in selected:
        selected.remove(service_id)
        bot.answer_callback_query(call.id, f"❌ {SERVICES[service_id]['name']} removido")
    else:
        selected.append(service_id)
        bot.answer_callback_query(call.id, f"✅ {SERVICES[service_id]['name']} agregado")
    
    update_data(chat_id, selected_services=selected)
    
    # Actualizar teclado
    edit_safe(chat_id, call.message.message_id, call.message.text, get_service_selector(chat_id))

@bot.callback_query_handler(func=lambda c: c.data == "svc_confirm")
def handle_service_confirm(call):
    chat_id = call.message.chat.id
    selected = get_data(chat_id, "selected_services", [])
    
    if not selected:
        bot.answer_callback_query(call.id, "Seleccioná al menos un servicio")
        return
    
    bot.answer_callback_query(call.id, f"✓ {len(selected)} servicios seleccionados")
    
    # Guardar en DB temporalmente
    db_execute(
        "INSERT OR IGNORE INTO workers (chat_id, disponible) VALUES (?, 0)",
        (str(chat_id),),
        commit=True
    )
    
    set_state(chat_id, UserState.WORKER_ENTERING_PRICE, {
        "services_to_price": selected[:],
        "current_service_idx": 0,
        "prices": {}
    })
    
    ask_next_price(chat_id)

def ask_next_price(chat_id: str):
    """Pide precio para el siguiente servicio"""
    services = get_data(chat_id, "services_to_price", [])
    idx = get_data(chat_id, "current_service_idx", 0)
    
    if idx >= len(services):
        # Todos los precios ingresados, pasar a nombre
        set_state(chat_id, UserState.WORKER_ENTERING_NAME)
        text = f"""
{Icons.USER} <b>Paso 2/5: Tu nombre</b>

¿Cómo te llaman los clientes?
{Icons.INFO} Ingresá tu nombre completo
        """
        remove_keyboard(chat_id, text)
        return
    
    service_id = services[idx]
    svc_name = SERVICES[service_id]["name"]
    
    text = f"""
{Icons.MONEY} <b>Paso 1/5: Precios ({idx+1}/{len(services)})</b>

¿Cuál es tu tarifa por hora para:
{SERVICES[service_id]['icon']} <b>{svc_name}</b>?

{Icons.INFO} Ingresá solo el número (ej: 5000)
    """
    
    markup = get_cancel_keyboard("Saltar este servicio")
    send_safe(chat_id, text, markup)

@bot.message_handler(func=lambda m: get_session(m.chat.id).state == UserState.WORKER_ENTERING_PRICE)
def handle_price_input(message):
    chat_id = message.chat.id
    text = message.text.strip()
    
    # Validar número
    try:
        price = float(text)
        if price < 1000:
            send_safe(chat_id, f"{Icons.WARNING} El precio parece muy bajo. ¿Es correcto? (mínimo $1000)")
            return
        if price > 50000:
            send_safe(chat_id, f"{Icons.WARNING} El precio parece muy alto. ¿Es correcto? (máximo $50000)")
            return
    except ValueError:
        send_safe(chat_id, f"{Icons.ERROR} Por favor ingresá solo números (ej: 5000)")
        return
    
    # Guardar precio
    services = get_data(chat_id, "services_to_price", [])
    idx = get_data(chat_id, "current_service_idx", 0)
    current_service = services[idx]
    
    prices = get_data(chat_id, "prices", {})
    prices[current_service] = price
    
    # Guardar en DB
    db_execute(
        "INSERT OR REPLACE INTO worker_services (chat_id, service_id, precio) VALUES (?, ?, ?)",
        (str(chat_id), current_service, price),
        commit=True
    )
    
    # Confirmación visual
    send_safe(chat_id, f"{Icons.SUCCESS} {SERVICES[current_service]['name']}: {format_price(price)}/hora")
    
    # Siguiente
    update_data(chat_id, prices=prices, current_service_idx=idx + 1)
    ask_next_price(chat_id)

@bot.message_handler(func=lambda m: get_session(m.chat.id).state == UserState.WORKER_ENTERING_NAME)
def handle_name_input(message):
    chat_id = message.chat.id
    name = message.text.strip()
    
    if len(name) < 3:
        send_safe(chat_id, f"{Icons.WARNING} Nombre muy corto. Ingresá al menos 3 letras.")
        return
    
    update_data(chat_id, worker_name=name)
    set_state(chat_id, UserState.WORKER_ENTERING_PHONE)
    
    text = f"""
{Icons.PHONE} <b>Paso 3/5: Teléfono</b>

Ingresá tu número de teléfono para que los clientes puedan contactarte:

{Icons.INFO} Formato: 11 1234-5678
    """
    
    send_safe(chat_id, text, get_cancel_keyboard())

@bot.message_handler(func=lambda m: get_session(m.chat.id).state == UserState.WORKER_ENTERING_PHONE)
def handle_phone_input(message):
    chat_id = message.chat.id
    phone = message.text.strip()
    
    # Validación básica de teléfono argentino
    phone_clean = re.sub(r'\D', '', phone)
    if len(phone_clean) < 10:
        send_safe(chat_id, f"{Icons.WARNING} Número inválido. Ingresá al menos 10 dígitos.")
        return
    
    update_data(chat_id, worker_phone=phone_clean)
    set_state(chat_id, UserState.WORKER_UPLOADING_DNI)
    
    text = f"""
{Icons.CAMERA} <b>Paso 4/5: Verificación de identidad</b>

Para la seguridad de todos, necesitamos verificar tu identidad.

{Icons.INFO} Enviá una foto de tu DNI (frente o reverso)
    """
    
    send_safe(chat_id, text, get_cancel_keyboard())

@bot.message_handler(content_types=['photo'], func=lambda m: get_session(m.chat.id).state == UserState.WORKER_UPLOADING_DNI)
def handle_dni_upload(message):
    chat_id = message.chat.id
    file_id = message.photo[-1].file_id
    
    # Guardar todo
    name = get_data(chat_id, "worker_name")
    phone = get_data(chat_id, "worker_phone")
    
    db_execute(
        "UPDATE workers SET nombre = ?, telefono = ?, dni_file_id = ? WHERE chat_id = ?",
        (name, phone, file_id, str(chat_id)),
        commit=True
    )
    
    set_state(chat_id, UserState.WORKER_SHARING_LOCATION)
    
    text = f"""
{Icons.LOCATION} <b>Paso 5/5: Ubicación de trabajo</b>

¿Dónde trabajás? 

{Icons.INFO} Enviá tu ubicación para recibir avisos de trabajos cercanos.
{Icons.INFO} Podés actualizarla cuando quieras con /ubicacion
    """
    
    send_safe(chat_id, text, get_location_keyboard())

@bot.message_handler(content_types=['location'], func=lambda m: get_session(m.chat.id).state == UserState.WORKER_SHARING_LOCATION)
def handle_worker_location(message):
    chat_id = message.chat.id
    lat = message.location.latitude
    lon = message.location.longitude
    
    db_execute(
        "UPDATE workers SET lat = ?, lon = ?, last_update = ?, disponible = 1 WHERE chat_id = ?",
        (lat, lon, int(time.time()), str(chat_id)),
        commit=True
    )
    
    clear_state(chat_id)
    remove_keyboard(chat_id)
    
    # Mensaje de éxito
    success_text = f"""
{Icons.PARTY} <b>¡Registro completado!</b>

Ya estás activo y recibirás notificaciones de trabajos cercanos.

<b>Tus comandos:</b>
/online - Activar disponibilidad
/offline - Pausar notificaciones  
/ubicacion - Actualizar ubicación
/precios - Modificar tarifas
/perfil - Ver tu perfil
/ayuda - Ayuda y soporte
    """
    
    send_safe(chat_id, success_text)

def show_worker_menu(chat_id: str, worker_data):
    """Muestra menú para trabajador ya registrado"""
    is_online = worker_data[3] if len(worker_data) > 3 else 0
    
    status_icon = Icons.ONLINE if is_online else Icons.OFFLINE
    status_text = "En línea" if is_online else "Desconectado"
    
    text = f"""
{Icons.BRIEFCASE} <b>Panel de Profesional</b>

{status_icon} <b>Estado:</b> {status_text}
⭐ <b>Rating:</b> {worker_data[7] if len(worker_data) > 7 else 5.0}/5.0

<b>¿Qué querés hacer?</b>
    """
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    if is_online:
        markup.add(types.InlineKeyboardButton(f"{Icons.OFFLINE} Desconectarme", callback_data="worker_offline"))
    else:
        markup.add(types.InlineKeyboardButton(f"{Icons.ONLINE} Conectarme", callback_data="worker_online"))
    
    markup.add(
        types.InlineKeyboardButton(f"{Icons.LOCATION} Ubicación", callback_data="worker_location"),
        types.InlineKeyboardButton(f"{Icons.MONEY} Precios", callback_data="worker_prices"),
        types.InlineKeyboardButton(f"{Icons.USER} Mi Perfil", callback_data="worker_profile")
    )
    
    send_safe(chat_id, text, markup)

# ==================== GESTIÓN DE TRABAJOS ====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("job_accept:"))
def handle_job_accept(call):
    chat_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])
    
    # Verificar que el trabajo siga disponible
    request = db_execute(
        "SELECT * FROM requests WHERE id = ? AND status = 'waiting_acceptance'",
        (request_id,), fetch_one=True
    )
    
    if not request:
        bot.answer_callback_query(call.id, "❌ Este trabajo ya fue tomado por otro profesional")
        edit_safe(chat_id, call.message.message_id, f"{Icons.ERROR} <b>Trabajo no disponible</b>\n\nYa fue asignado a otro profesional.")
        return
    
    # Asignar trabajo
    db_execute(
        "UPDATE requests SET worker_chat_id = ?, status = 'assigned', accepted_at = ? WHERE id = ?",
        (str(chat_id), int(time.time()), request_id),
        commit=True
    )
    
    bot.answer_callback_query(call.id, "✅ ¡Trabajo asignado!")
    
    # Notificar al trabajador
    worker_text = f"""
{Icons.SUCCESS} <b>¡Trabajo confirmado!</b>

{Icons.INFO} Contactá al cliente para coordinar los detalles.

{Icons.PHONE} <b>Cliente:</b> {request[1]}
    """
    
    edit_safe(chat_id, call.message.message_id, worker_text)
    
    # Notificar al cliente
    client_id = request[1]
    service_id = request[2]
    hora = request[4]
    
    client_text = f"""
{Icons.PARTY} <b>¡Encontramos tu profesional!</b>

{get_service_display(service_id)}
{Icons.TIME} <b>Hora:</b> {hora}

{Icons.INFO} El profesional se pondrá en contacto con vos pronto.

{Icons.CAR} <b>Estado:</b> En camino al servicio
    """
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(f"{Icons.SUCCESS} Recibí el servicio", callback_data=f"client_complete:{request_id}"),
        types.InlineKeyboardButton(f"{Icons.ERROR} Reportar problema", callback_data=f"client_issue:{request_id}")
    )
    
    send_safe(client_id, client_text, markup)

# ==================== COMANDOS ADICIONALES ====================
@bot.message_handler(commands=['cancel'])
def cmd_cancel(message):
    chat_id = message.chat.id
    clear_state(chat_id)
    remove_keyboard(chat_id, f"{Icons.SUCCESS} Cancelado. Usá /start para comenzar de nuevo.")

@bot.message_handler(commands=['ayuda', 'help'])
def cmd_help(message):
    text = f"""
{Icons.INFO} <b>Ayuda de CleanyGo</b>

<b>Para Clientes:</b>
/start - Solicitar un servicio
/cancel - Cancelar solicitud actual

<b>Para Profesionales:</b>
/start - Registrarte o ver panel
/online - Activar disponibilidad  
/offline - Pausar notificaciones
/ubicacion - Cambiar ubicación
/precios - Modificar tarifas

<b>Soporte:</b>
@soporte_cleanygo
    """
    send_safe(message.chat.id, text)

# ==================== INICIO ====================
if __name__ == "__main__":
    init_db()
    logger.info(f"{Icons.SUCCESS} Bot CleanyGo UX iniciado")
    
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except Exception as e:
        logger.error(f"Error crítico: {e}")
