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

user_states = {}

def set_state(chat_id, state, data=None):
    user_states[str(chat_id)] = {"state": state, "data": data or {}}

def get_state(chat_id):
    return user_states.get(str(chat_id), {"state": "idle", "data": {}})

def clear_state(chat_id):
    user_states.pop(str(chat_id), None)

# ==============================
# INICIO CON BOTONES GRANDES Y SEPARADOS
# ==============================
@bot.message_handler(commands=['start'])
def start_command(message):
    chat_id = message.chat.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("🛎️ Soy Cliente"))
    markup.add(types.KeyboardButton("💼 Soy Prestador"))
    markup.add(types.KeyboardButton("❌ Cancelar"))
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
# REGISTRO TRABAJADOR - SELECCIÓN DE SERVICIOS MEJORADA (sin trabarse)
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

    set_state(chat_id, "seleccionando_servicios", {"selected_services": [], "message_id": None})
    ask_services_worker(chat_id)

def ask_services_worker(chat_id):
    state = get_state(chat_id)
    selected = state["data"].get("selected_services", [])
    message_id = state["data"].get("message_id")

    markup = types.InlineKeyboardMarkup(row_width=1)
    for s in services_list:
        text = f"✅ {s}" if s in selected else f"❌ {s}"
        markup.add(types.InlineKeyboardButton(text, callback_data=f"service_{s}"))

    markup.add(types.InlineKeyboardButton("✅ Confirmar selección", callback_data="confirm_services"))

    text = "Seleccioná los servicios que ofrecés:\n\n(Marcá los que sí hacés con ✅)"

    if message_id:
        edit_safe(chat_id, message_id, text, markup)
    else:
        msg = bot.send_message(chat_id, text, reply_markup=markup)
        state["data"]["message_id"] = msg.message_id
        set_state(chat_id, "seleccionando_servicios", state["data"])

@bot.callback_query_handler(func=lambda call: call.data.startswith("service_") or call.data == "confirm_services")
def handle_service_selection(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    state = get_state(chat_id)
    if state["state"] != "seleccionando_servicios":
        bot.answer_callback_query(call.id, "Acción no válida ahora")
        return

    data = call.data
    selected = state["data"].setdefault("selected_services", [])

    if data.startswith("service_"):
        service = data.replace("service_", "")
        if service in selected:
            selected.remove(service)
            bot.answer_callback_query(call.id, f"❌ Quitaste {service}")
        else:
            selected.append(service)
            bot.answer_callback_query(call.id, f"✅ Agregaste {service}")

        # Refrescar botones
        ask_services_worker(chat_id)

    elif data == "confirm_services":
        if not selected:
            bot.answer_callback_query(call.id, "Debes seleccionar al menos un servicio")
            return

        bot.answer_callback_query(call.id, "Servicios confirmados")
        send_safe(chat_id, f"Servicios seleccionados: {', '.join(selected)}")
        set_state(chat_id, "ingresando_precios", {"services": selected[:], "current_index": 0})
        ask_price_worker(chat_id)

# (el resto del código queda exactamente igual: precios, nombre, DNI, ubicación, pedir servicio, selector de hora con botones, negociación, etc.)

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
