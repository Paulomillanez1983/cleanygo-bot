import telebot
from telebot import types
import re
import math
import threading
import time
import logging
import aiosqlite
import asyncio

TOKEN = "8534288619:AAG1i5-PdjUABerTQCp_y84XubBfVNJ34FU"
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

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('''
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
        await db.execute('''
            CREATE TABLE IF NOT EXISTS worker_services (
                chat_id TEXT,
                servicio TEXT,
                precio REAL NOT NULL,
                PRIMARY KEY (chat_id, servicio),
                FOREIGN KEY (chat_id) REFERENCES workers(chat_id) ON DELETE CASCADE
            )
        ''')
        await db.execute('''
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
        await db.commit()
    logger.info("✅ Base de datos SQLite inicializada correctamente")

async def db_execute(query, params=(), fetch_one=False, commit=False):
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute(query, params)
        if commit:
            await db.commit()
        if fetch_one:
            return await cursor.fetchone()
        return await cursor.fetchall()

def send_safe(chat_id, text, reply_markup=None):
    try:
        bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error enviando a {chat_id}: {e}")

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

user_states = {}

def set_state(chat_id, state, data=None):
    user_states[str(chat_id)] = {"state": state, "data": data or {}}

def get_state(chat_id):
    return user_states.get(str(chat_id), {"state": "idle", "data": {}})

def clear_state(chat_id):
    user_states.pop(str(chat_id), None)

# ==============================
# INICIO CON BOTONES GRANDES
# ==============================
@bot.message_handler(commands=['start'])
def start_command(message):
    chat_id = message.chat.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    btn_cliente = types.KeyboardButton("🛎️ Soy Cliente")
    btn_trabajador = types.KeyboardButton("💼 Soy Prestador")
    btn_cancel = types.KeyboardButton("❌ Cancelar")
    markup.add(btn_cliente)
    markup.add(btn_trabajador)
    markup.add(btn_cancel)
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

# ==============================
# REGISTRO TRABAJADOR
# ==============================
@bot.message_handler(commands=['soytrabajador'])
def start_worker_registration(message):
    chat_id = message.chat.id
    if get_state(chat_id)["state"] != "idle":
        send_safe(chat_id, "Ya estás en otro proceso. Usa /cancel primero.")
        return

    exists = asyncio.run(db_execute("SELECT 1 FROM workers WHERE chat_id = ?", (str(chat_id),), fetch_one=True))
    if not exists:
        asyncio.run(db_execute("INSERT OR IGNORE INTO workers (chat_id, disponible, last_update) VALUES (?, 1, ?)", (str(chat_id), int(time.time())), commit=True))

    set_state(chat_id, "seleccionando_servicios", {"selected_services": []})
    ask_services_worker(chat_id)

def ask_services_worker(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    state = get_state(chat_id)
    selected = state["data"].get("selected_services", [])
    for s in services_list:
        text = f"✅ {s}" if s in selected else s
        markup.add(types.InlineKeyboardButton(text, callback_data=f"service_{s}"))
    markup.add(types.InlineKeyboardButton("✅ Confirmar servicios", callback_data="confirm_services"))
    send_safe(chat_id, "Seleccioná los servicios que ofrecés:", markup)

# (el resto de handlers de registro trabajador quedan iguales: handle_service_selection, ask_price_worker, handle_worker_price, handle_worker_name, handle_worker_dni, etc.)

# ==============================
# PEDIR SERVICIO - SELECTOR DE HORA BONITO
# ==============================
@bot.message_handler(commands=['pedirservicio'])
def request_service(message):
    chat_id = message.chat.id
    if get_state(chat_id)["state"] != "idle":
        send_safe(chat_id, "Terminá o cancelá el proceso actual con /cancel")
        return
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    for s in services_list:
        markup.add(s)
    send_safe(chat_id, "Seleccioná el servicio que necesitás:", markup)
    set_state(chat_id, "seleccionando_servicio_cliente")

@bot.message_handler(func=lambda m: get_state(m.chat.id)["state"] == "seleccionando_servicio_cliente")
def handle_service_choice(message):
    chat_id = message.chat.id
    servicio = message.text.strip()
    if servicio not in services_list:
        send_safe(chat_id, "Servicio no válido. Elegí de la lista.")
        return
    set_state(chat_id, "seleccionando_hora", {"servicio": servicio})
    send_hora_selector(chat_id)

def send_hora_selector(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=6)
    for h in range(0, 24):
        h_str = f"{h:02d}"
        markup.add(types.InlineKeyboardButton(h_str, callback_data=f"hora_{h_str}"))
    send_safe(chat_id, "Seleccioná la hora (HH):", markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("hora_"))
def handle_hora(call):
    chat_id = call.message.chat.id
    state = get_state(chat_id)
    if state["state"] != "seleccionando_hora":
        return
    hora = call.data.replace("hora_", "")
    state["data"]["hora"] = hora
    send_minutos_selector(chat_id)

def send_minutos_selector(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=4)
    for m in ["00", "15", "30", "45"]:
        markup.add(types.InlineKeyboardButton(m, callback_data=f"min_{m}"))
    send_safe(chat_id, "Seleccioná los minutos:", markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("min_"))
def handle_minutos(call):
    chat_id = call.message.chat.id
    state = get_state(chat_id)
    minutos = call.data.replace("min_", "")
    state["data"]["minutos"] = minutos
    send_ampm_selector(chat_id)

def send_ampm_selector(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("AM", callback_data="ampm_AM"))
    markup.add(types.InlineKeyboardButton("PM", callback_data="ampm_PM"))
    send_safe(chat_id, "Seleccioná AM o PM:", markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("ampm_"))
def handle_ampm(call):
    chat_id = call.message.chat.id
    state = get_state(chat_id)
    ampm = call.data.replace("ampm_", "")
    state["data"]["ampm"] = ampm
    hora_completa = f"{state['data']['hora']}:{state['data']['minutos']} {ampm}"
    send_safe(chat_id, f"Hora seleccionada: {hora_completa}")
    set_state(chat_id, "esperando_ubicacion_cliente", {"servicio": state["data"]["servicio"], "hora": hora_completa})
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("📍 Enviar mi ubicación", request_location=True))
    send_safe(chat_id, "Enviá tu ubicación para encontrar prestadores cercanos:", markup)

# (el resto del código: handle_client_location, confirm_pedido, buscar_prestadores, handle_worker_response, etc. queda igual que tu versión que funcionaba)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(init_db())
        logger.info("✅ DB OK")
    except Exception as e:
        logger.error(f"Error DB: {e}")
        print(f"Error DB: {e}")
        raise

    logger.info("🤖 Bot iniciado correctamente")
    print("🤖 Bot corriendo...")

    bot.infinity_polling(timeout=30, long_polling_timeout=30, skip_pending=True)
