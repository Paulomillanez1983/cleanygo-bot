import telebot
from telebot import types
import re
import math
import threading
import time
import logging
import sqlite3  # Usamos sqlite3 síncrono en lugar de aiosqlite
import os
from datetime import datetime

# ⚠️ NUNCA expongas el token en el código. Usa variables de entorno
TOKEN = os.getenv("BOT_TOKEN", "TU_TOKEN_AQUI")
DB_FILE = "services_bot.db"

bot = telebot.TeleBot(TOKEN)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

services_list = [
    "Niñera",
    "Cuidado de personas",
    "Instalación de aire acondicionado",
    "Visita técnica de aire acondicionado"
]

# ==============================
# BASE DE DATOS (SÍNCRONA)
# ==============================
def init_db():
    """Inicializa la base de datos SQLite de forma síncrona"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS workers (
                    chat_id TEXT PRIMARY KEY,
                    nombre TEXT,
                    dni_file_id TEXT,
                    disponible INTEGER DEFAULT 1,
                    lat REAL,
                    lon REAL,
                    last_update INTEGER
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS worker_services (
                    chat_id TEXT,
                    servicio TEXT,
                    precio REAL NOT NULL,
                    PRIMARY KEY (chat_id, servicio),
                    FOREIGN KEY (chat_id) REFERENCES workers(chat_id) ON DELETE CASCADE
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_chat_id TEXT NOT NULL,
                    servicio TEXT NOT NULL,
                    hora TEXT,
                    lat REAL NOT NULL,
                    lon REAL NOT NULL,
                    status TEXT DEFAULT 'open',
                    worker_chat_id TEXT,
                    created_at INTEGER DEFAULT (strftime('%s', 'now')),
                    updated_at INTEGER DEFAULT (strftime('%s', 'now'))
                )
            ''')
            
            conn.commit()
        logger.info("✅ Base de datos SQLite inicializada correctamente")
        return True
    except Exception as e:
        logger.error(f"❌ Error inicializando DB: {e}")
        return False

def db_execute(query, params=(), fetch_one=False, commit=False):
    """Ejecuta queries de forma síncrona"""
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
        logger.error(f"Error en DB: {e}")
        return None

# ==============================
# UTILIDADES
# ==============================
def send_safe(chat_id, text, reply_markup=None):
    try:
        bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error enviando a {chat_id}: {e}")

def edit_safe(chat_id, message_id, text, reply_markup=None):
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error editando mensaje {message_id}: {e}")

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def is_valid_price(text):
    try:
        price = float(text)
        return price > 0
    except ValueError:
        return False

# ==============================
# MANEJO DE ESTADOS
# ==============================
user_states = {}

def set_state(chat_id, state, data=None):
    user_states[str(chat_id)] = {"state": state, "data": data or {}}

def get_state(chat_id):
    return user_states.get(str(chat_id), {"state": "idle", "data": {}})

def clear_state(chat_id):
    user_states.pop(str(chat_id), None)

# ==============================
# COMANDO START
# ==============================
@bot.message_handler(commands=['start'])
def start_command(message):
    chat_id = message.chat.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(
        types.KeyboardButton("🛎️ Soy Cliente"),
        types.KeyboardButton("💼 Soy Prestador"),
        types.KeyboardButton("❌ Cancelar")
    )
    send_safe(chat_id, "👋 ¡Bienvenido al Bot de Servicios!\n\nElige tu rol:", markup)

@bot.message_handler(func=lambda m: m.text == "🛎️ Soy Cliente")
def soy_cliente(message):
    request_service(message)

@bot.message_handler(func=lambda m: m.text == "💼 Soy Prestador")
def soy_prestador(message):
    start_worker_registration(message)

@bot.message_handler(func=lambda m: m.text == "❌ Cancelar")
def cancel_keyboard(message):
    cancel_process(message)

@bot.message_handler(commands=['cancel'])
def cancel_command(message):
    cancel_process(message)

def cancel_process(message):
    chat_id = message.chat.id
    clear_state(chat_id)
    markup = types.ReplyKeyboardRemove()
    send_safe(chat_id, "❌ Proceso cancelado. Usa /start para comenzar de nuevo.", markup)

# ==============================
# REGISTRO DE TRABAJADOR
# ==============================
@bot.message_handler(commands=['soytrabajador'])
def start_worker_registration(message):
    chat_id = message.chat.id
    
    if get_state(chat_id)["state"] != "idle":
        send_safe(chat_id, "⚠️ Ya estás en otro proceso. Usa /cancel primero.")
        return

    # Verificar si ya existe
    exists = db_execute("SELECT 1 FROM workers WHERE chat_id = ?", (str(chat_id),), fetch_one=True)
    
    if not exists:
        db_execute(
            "INSERT OR IGNORE INTO workers (chat_id, disponible, last_update) VALUES (?, 1, ?)", 
            (str(chat_id), int(time.time())), 
            commit=True
        )
        logger.info(f"Nuevo trabajador registrado: {chat_id}")
    
    set_state(chat_id, "seleccionando_servicios", {"selected_services": [], "message_id": None})
    ask_services_worker(chat_id)

def ask_services_worker(chat_id):
    state = get_state(chat_id)
    selected = state["data"].get("selected_services", [])
    message_id = state["data"].get("message_id")

    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for s in services_list:
        text = f"✅ {s}" if s in selected else f"⬜ {s}"
        markup.add(types.InlineKeyboardButton(text, callback_data=f"service_{s}"))

    if selected:
        markup.add(types.InlineKeyboardButton("✅ Confirmar selección", callback_data="confirm_services"))

    text = "🔧 <b>Seleccioná los servicios que ofrecés:</b>\n\n"
    if selected:
        text += f"<i>Seleccionados: {', '.join(selected)}</i>\n\n"
    text += "Tocá un servicio para seleccionarlo/deseleccionarlo:"

    try:
        if message_id:
            edit_safe(chat_id, message_id, text, markup)
        else:
            msg = bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")
            state["data"]["message_id"] = msg.message_id
            set_state(chat_id, "seleccionando_servicios", state["data"])
    except Exception as e:
        logger.error(f"Error en ask_services_worker: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("service_") or call.data == "confirm_services")
def handle_service_selection(call):
    chat_id = call.message.chat.id
    state = get_state(chat_id)
    
    if state["state"] != "seleccionando_servicios":
        bot.answer_callback_query(call.id, "⚠️ Acción no válida ahora")
        return

    data = call.data
    selected = state["data"].setdefault("selected_services", [])

    if data.startswith("service_"):
        service = data.replace("service_", "")
        
        if service in selected:
            selected.remove(service)
            bot.answer_callback_query(call.id, f"❌ {service} removido")
        else:
            selected.append(service)
            bot.answer_callback_query(call.id, f"✅ {service} agregado")

        ask_services_worker(chat_id)

    elif data == "confirm_services":
        if not selected:
            bot.answer_callback_query(call.id, "⚠️ Debes seleccionar al menos un servicio")
            return

        bot.answer_callback_query(call.id, "✅ Servicios confirmados")
        
        # Limpiar mensaje inline
        try:
            bot.edit_message_text(
                f"✅ Servicios seleccionados: <b>{', '.join(selected)}</b>\n\nAhora ingresá los precios...",
                chat_id,
                state["data"]["message_id"],
                parse_mode="HTML"
            )
        except:
            pass
            
        set_state(chat_id, "ingresando_precios", {"services": selected[:], "current_index": 0, "prices": {}})
        ask_price_worker(chat_id)

def ask_price_worker(chat_id):
    state = get_state(chat_id)
    services = state["data"]["services"]
    current_idx = state["data"]["current_index"]
    
    if current_idx >= len(services):
        # Todos los precios ingresados, pasar a nombre
        set_state(chat_id, "esperando_nombre", {"prices": state["data"]["prices"]})
        send_safe(chat_id, "📝 <b>Ingresá tu nombre completo:</b>")
        return
    
    service = services[current_idx]
    send_safe(chat_id, f"💰 <b>Precio para '{service}'</b>\n\nIngresá el monto en números (ej: 1500.50):")

@bot.message_handler(func=lambda m: get_state(m.chat.id)["state"] == "ingresando_precios")
def handle_price_input(message):
    chat_id = message.chat.id
    text = message.text
    
    if not is_valid_price(text):
        send_safe(chat_id, "❌ Precio inválido. Ingresá un número mayor a 0 (ej: 1500):")
        return
    
    state = get_state(chat_id)
    services = state["data"]["services"]
    current_idx = state["data"]["current_index"]
    current_service = services[current_idx]
    
    # Guardar precio
    state["data"]["prices"][current_service] = float(text)
    state["data"]["current_index"] += 1
    
    set_state(chat_id, "ingresando_precios", state["data"])
    ask_price_worker(chat_id)

@bot.message_handler(func=lambda m: get_state(m.chat.id)["state"] == "esperando_nombre")
def handle_name_input(message):
    chat_id = message.chat.id
    nombre = message.text.strip()
    
    if len(nombre) < 3:
        send_safe(chat_id, "❌ Nombre muy corto. Ingresá al menos 3 caracteres:")
        return
    
    state = get_state(chat_id)
    state["data"]["nombre"] = nombre
    
    set_state(chat_id, "esperando_dni", state["data"])
    send_safe(chat_id, "📎 <b>Envía una foto de tu DNI</b> (frente o reverso) para verificación:")

@bot.message_handler(content_types=['photo'], func=lambda m: get_state(m.chat.id)["state"] == "esperando_dni")
def handle_dni_photo(message):
    chat_id = message.chat.id
    file_id = message.photo[-1].file_id  # Mejor calidad
    
    state = get_state(chat_id)
    prices = state["data"]["prices"]
    nombre = state["data"]["nombre"]
    
    # Guardar en DB
    db_execute(
        "UPDATE workers SET nombre = ?, dni_file_id = ? WHERE chat_id = ?",
        (nombre, file_id, str(chat_id)),
        commit=True
    )
    
    # Guardar precios
    for servicio, precio in prices.items():
        db_execute(
            "INSERT OR REPLACE INTO worker_services (chat_id, servicio, precio) VALUES (?, ?, ?)",
            (str(chat_id), servicio, precio),
            commit=True
        )
    
    clear_state(chat_id)
    
    # Pedir ubicación
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("📍 Enviar mi ubicación", request_location=True))
    markup.add(types.KeyboardButton("❌ Cancelar"))
    
    send_safe(
        chat_id,
        f"✅ <b>¡Registro casi completo!</b>\n\n"
        f"Nombre: {nombre}\n"
        f"Servicios: {', '.join(prices.keys())}\n\n"
        f"📍 <b>Último paso:</b> Enviá tu ubicación para que los clientes te encuentren:",
        markup
    )

@bot.message_handler(content_types=['location'], func=lambda m: get_state(m.chat.id)["state"] == "idle")
def handle_worker_location(message):
    chat_id = message.chat.id
    lat = message.location.latitude
    lon = message.location.longitude
    
    db_execute(
        "UPDATE workers SET lat = ?, lon = ?, last_update = ? WHERE chat_id = ?",
        (lat, lon, int(time.time()), str(chat_id)),
        commit=True
    )
    
    markup = types.ReplyKeyboardRemove()
    send_safe(
        chat_id,
        "✅ <b>¡Registro completado!</b>\n\n"
        "Ya estás disponible para recibir solicitudes de clientes cercanos.\n\n"
        "Usá /misdatos para ver tu perfil o /pausa para pausar notificaciones.",
        markup
    )

# ==============================
# FLUJO CLIENTE (BÁSICO)
# ==============================
def request_service(message):
    chat_id = message.chat.id
    clear_state(chat_id)
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    for service in services_list:
        markup.add(types.InlineKeyboardButton(service, callback_data=f"request_{service}"))
    
    send_safe(chat_id, "🔍 <b>¿Qué servicio necesitás?</b>", markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("request_"))
def handle_service_request(call):
    chat_id = call.message.chat.id
    service = call.data.replace("request_", "")
    
    bot.answer_callback_query(call.id)
    
    set_state(chat_id, "esperando_ubicacion_cliente", {"servicio": service})
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("📍 Enviar mi ubicación", request_location=True))
    markup.add(types.KeyboardButton("❌ Cancelar"))
    
    send_safe(
        chat_id,
        f"✅ Servicio: <b>{service}</b>\n\n"
        f"📍 Enviá tu ubicación para encontrar prestadores cercanos:",
        markup
    )

@bot.message_handler(content_types=['location'], func=lambda m: get_state(m.chat.id)["state"] == "esperando_ubicacion_cliente")
def handle_client_location(message):
    chat_id = message.chat.id
    lat = message.location.latitude
    lon = message.location.longitude
    
    state = get_state(chat_id)
    servicio = state["data"]["servicio"]
    
    # Guardar solicitud
    db_execute(
        "INSERT INTO requests (client_chat_id, servicio, lat, lon) VALUES (?, ?, ?, ?)",
        (str(chat_id), servicio, lat, lon),
        commit=True
    )
    
    # Buscar trabajadores cercanos disponibles
    workers = db_execute(
        "SELECT w.chat_id, w.nombre, w.lat, w.lon, ws.precio "
        "FROM workers w "
        "JOIN worker_services ws ON w.chat_id = ws.chat_id "
        "WHERE ws.servicio = ? AND w.disponible = 1 AND w.lat IS NOT NULL",
        (servicio,)
    )
    
    if not workers:
        clear_state(chat_id)
        send_safe(chat_id, "😔 No hay prestadores disponibles para este servicio en este momento.")
        return
    
    # Calcular distancias y filtrar por radio (ej: 10km)
    cercanos = []
    for worker in workers:
        w_chat_id, w_nombre, w_lat, w_lon, w_precio = worker
        if w_lat and w_lon:
            dist = haversine(lat, lon, w_lat, w_lon)
            if dist <= 10:  # Radio de 10km
                cercanos.append((w_chat_id, w_nombre, dist, w_precio))
    
    if not cercanos:
        clear_state(chat_id)
        send_safe(chat_id, "😔 No hay prestadores disponibles dentro de 10km de tu ubicación.")
        return
    
    # Ordenar por distancia
    cercanos.sort(key=lambda x: x[2])
    
    # Mostrar opciones al cliente
    markup = types.InlineKeyboardMarkup(row_width=1)
    text = f"🔍 <b>Prestadores encontrados para {servicio}:</b>\n\n"
    
    for i, (w_id, w_nombre, dist, precio) in enumerate(cercanos[:5], 1):  # Top 5
        text += f"{i}. <b>{w_nombre}</b>\n"
        text += f"   📍 {dist:.1f}km | 💰 ${precio:.2f}\n\n"
        markup.add(types.InlineKeyboardButton(
            f"Contratar a {w_nombre} (${precio:.0f})", 
            callback_data=f"hire_{w_id}_{servicio}"
        ))
    
    markup.add(types.InlineKeyboardButton("❌ Cancelar", callback_data="cancel_hire"))
    
    set_state(chat_id, "seleccionando_prestador", {"servicio": servicio, "lat": lat, "lon": lon})
    send_safe(chat_id, text, markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("hire_"))
def handle_hire_worker(call):
    chat_id = call.message.chat.id
    data = call.data.split("_")
    worker_id = data[1]
    servicio = data[2]
    
    bot.answer_callback_query(call.id, "✅ Solicitud enviada al prestador")
    
    # Notificar al trabajador
    send_safe(
        worker_id,
        f"🛎️ <b>¡Nueva solicitud de trabajo!</b>\n\n"
        f"Servicio: {servicio}\n"
        f"Cliente ID: {chat_id}\n\n"
        f"Usá /aceptar_{chat_id} para aceptar o /rechazar_{chat_id} para rechazar."
    )
    
    clear_state(chat_id)
    send_safe(chat_id, "⏳ Solicitud enviada al prestador. Esperando confirmación...")

@bot.callback_query_handler(func=lambda call: call.data == "cancel_hire")
def cancel_hire(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id, "Cancelado")
    clear_state(chat_id)
    send_safe(chat_id, "❌ Búsqueda cancelada. Usá /start para comenzar de nuevo.")

# ==============================
# INICIO DEL BOT
# ==============================
if __name__ == "__main__":
    # Inicializar DB
    if not init_db():
        print("❌ No se pudo inicializar la base de datos. Saliendo...")
        exit(1)
    
    logger.info("🤖 Bot iniciado correctamente")
    print("🤖 Bot corriendo... Presiona Ctrl+C para detener")
    
    # Iniciar polling con manejo de errores
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
    except Exception as e:
        logger.error(f"Error en polling: {e}")
        print(f"❌ Error crítico: {e}")

