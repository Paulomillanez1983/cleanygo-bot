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

@bot.callback_query_handler(func=lambda call: call.data.startswith("service_") or call.data == "confirm_services")
def handle_service_selection(call):
    chat_id = call.message.chat.id
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
            bot.answer_callback_query(call.id, f"❌ {service} eliminado")
        else:
            selected.append(service)
            bot.answer_callback_query(call.id, f"✅ {service} agregado")
        ask_services_worker(chat_id)
    elif data == "confirm_services":
        if not selected:
            bot.answer_callback_query(call.id, "Debes seleccionar al menos un servicio")
            return
        bot.answer_callback_query(call.id, "Servicios confirmados")
        send_safe(chat_id, f"Servicios seleccionados: {', '.join(selected)}")
        set_state(chat_id, "ingresando_precios", {"services": selected[:], "current_index": 0})
        ask_price_worker(chat_id)

def ask_price_worker(chat_id):
    state = get_state(chat_id)
    idx = state["data"]["current_index"]
    services = state["data"]["services"]
    if idx >= len(services):
        send_safe(chat_id, "✅ Todos los precios ingresados. Ahora tu nombre completo.")
        set_state(chat_id, "nombre_worker")
        return
    service = services[idx]
    send_safe(chat_id, f"Precio para '{service}' (número mayor a 0):")

@bot.message_handler(func=lambda m: get_state(m.chat.id)["state"] == "ingresando_precios")
def handle_worker_price(message):
    chat_id = message.chat.id
    state = get_state(chat_id)
    text = message.text.strip()
    if not is_valid_price(text):
        send_safe(chat_id, "❌ Ingresá un número válido mayor a 0")
        return
    price = float(text)
    service = state["data"]["services"][state["data"]["current_index"]]
    asyncio.run(db_execute("INSERT OR REPLACE INTO worker_services (chat_id, servicio, precio) VALUES (?, ?, ?)", (str(chat_id), service, price), commit=True))
    send_safe(chat_id, f"💰 Precio de '{service}': ${price}")
    state["data"]["current_index"] += 1
    ask_price_worker(chat_id)

@bot.message_handler(func=lambda m: get_state(m.chat.id)["state"] == "nombre_worker")
def handle_worker_name(message):
    chat_id = message.chat.id
    nombre = message.text.strip()
    if len(nombre) < 3:
        send_safe(chat_id, "El nombre debe tener al menos 3 letras.")
        return
    asyncio.run(db_execute("UPDATE workers SET nombre = ? WHERE chat_id = ?", (nombre, str(chat_id)), commit=True))
    send_safe(chat_id, "📄 Ahora enviá foto del DNI (frontal)")
    set_state(chat_id, "dni_worker")

@bot.message_handler(content_types=['photo'], func=lambda m: get_state(m.chat.id)["state"] == "dni_worker")
def handle_worker_dni(message):
    chat_id = message.chat.id
    file_id = message.photo[-1].file_id
    asyncio.run(db_execute("UPDATE workers SET dni_file_id = ?, last_update = ? WHERE chat_id = ?", (file_id, int(time.time()), str(chat_id)), commit=True))
    send_safe(chat_id, "✅ Registro completo. Estás en línea.\n/offline para desconectarte.\n/actualizarubicacion para tu posición.")
    clear_state(chat_id)

@bot.message_handler(commands=['offline'])
def go_offline(message):
    chat_id = message.chat.id
    exists = asyncio.run(db_execute("SELECT 1 FROM workers WHERE chat_id = ?", (str(chat_id),), fetch_one=True))
    if not exists:
        send_safe(chat_id, "No estás registrado como trabajador.")
        return
    asyncio.run(db_execute("UPDATE workers SET disponible = 0 WHERE chat_id = ?", (str(chat_id),), commit=True))
    send_safe(chat_id, "🛑 Estás fuera de línea.")

@bot.message_handler(commands=['actualizarubicacion'])
def update_worker_location(message):
    chat_id = message.chat.id
    exists = asyncio.run(db_execute("SELECT 1 FROM workers WHERE chat_id = ?", (str(chat_id),), fetch_one=True))
    if not exists:
        send_safe(chat_id, "Solo trabajadores registrados pueden actualizar ubicación.")
        return
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("📍 Enviar ubicación", request_location=True))
    send_safe(chat_id, "Enviá tu ubicación actual:", markup)
    set_state(chat_id, "actualizando_ubicacion")

@bot.message_handler(content_types=['location'], func=lambda m: get_state(m.chat.id)["state"] == "actualizando_ubicacion")
def handle_worker_location(message):
    chat_id = message.chat.id
    loc = message.location
    asyncio.run(db_execute("UPDATE workers SET lat = ?, lon = ?, last_update = ? WHERE chat_id = ?", (loc.latitude, loc.longitude, int(time.time()), str(chat_id)), commit=True))
    send_safe(chat_id, "✅ Ubicación guardada.")
    clear_state(chat_id)

@bot.message_handler(commands=['pedirservicio'])
def request_service(message):
    chat_id = message.chat.id
    if get_state(chat_id)["state"] != "idle":
        send_safe(chat_id, "Terminá o cancelá el proceso actual con /cancel")
        return
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
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
    set_state(chat_id, "ingresando_hora", {"servicio": servicio})
    send_safe(chat_id, "Ingresá la hora aproximada (formato HH:MM):")

@bot.message_handler(func=lambda m: get_state(m.chat.id)["state"] == "ingresando_hora")
def handle_hora(message):
    chat_id = message.chat.id
    hora = message.text.strip()
    if not re.match(r'^([01]\d|2[0-3]):([0-5]\d)$', hora):
        send_safe(chat_id, "Formato inválido. Usa HH:MM (ej: 14:30)")
        return
    state = get_state(chat_id)
    state["data"]["hora"] = hora
    set_state(chat_id, "esperando_ubicacion_cliente", state["data"])
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("📍 Enviar mi ubicación", request_location=True))
    send_safe(chat_id, "Enviá tu ubicación para encontrar prestadores cercanos:", markup)

@bot.message_handler(content_types=['location'], func=lambda m: get_state(m.chat.id)["state"] == "esperando_ubicacion_cliente")
def handle_client_location(message):
    chat_id = message.chat.id
    loc = message.location
    state = get_state(chat_id)
    pedido = {
        "servicio": state["data"]["servicio"],
        "hora": state["data"]["hora"],
        "ubicacion": {"lat": loc.latitude, "lon": loc.longitude}
    }
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Enviar pedido", callback_data="confirmar_pedido"))
    send_safe(chat_id, f"Confirmá:\nServicio: {pedido['servicio']}\nHora: {pedido['hora']}\nUbicación recibida.", markup)
    set_state(chat_id, "confirmando_pedido", {"pedido": pedido})

@bot.callback_query_handler(func=lambda call: call.data == "confirmar_pedido")
def confirm_pedido(call):
    chat_id = call.message.chat.id
    state = get_state(chat_id)
    if state["state"] != "confirmando_pedido":
        return
    pedido = state["data"]["pedido"]
    asyncio.run(db_execute("INSERT INTO requests (client_chat_id, servicio, hora, lat, lon) VALUES (?, ?, ?, ?, ?)", (str(chat_id), pedido["servicio"], pedido["hora"], pedido["ubicacion"]["lat"], pedido["ubicacion"]["lon"]), commit=True))
    send_safe(chat_id, "✅ Pedido enviado. Buscando prestadores cercanos...")
    threading.Thread(target=buscar_prestadores, args=(chat_id, pedido), daemon=True).start()
    clear_state(chat_id)

def buscar_prestadores(client_id, pedido, radio_inicial=5, max_radio=30, incremento=7, espera=40):
    radio = radio_inicial
    start = time.time()
    urgencia_enviada = False
    while time.time() - start < 900:
        found = False
        workers_near = []
        rows = asyncio.run(db_execute("""
            SELECT w.chat_id, w.lat, w.lon, w.disponible
            FROM workers w JOIN worker_services ws ON w.chat_id = ws.chat_id
            WHERE ws.servicio = ? AND w.disponible = 1 AND w.lat IS NOT NULL AND w.lon IS NOT NULL
        """, (pedido["servicio"],)))
        for row in rows:
            w_id, w_lat, w_lon, disp = row
            if disp != 1: continue
            dist = haversine(pedido["ubicacion"]["lat"], pedido["ubicacion"]["lon"], w_lat, w_lon)
            if dist <= radio:
                found = True
                workers_near.append((w_id, dist, w_lat, w_lon))
        if found:
            for w_id, dist, lat, lon in workers_near:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("✅ Aceptar", callback_data=f"aceptar_{client_id}"))
                markup.add(types.InlineKeyboardButton("❌ Rechazar", callback_data=f"rechazar_{client_id}"))
                send_safe(w_id, f"🚨 Pedido cerca ({dist:.1f} km)!\nServicio: {pedido['servicio']}\nHora: {pedido['hora']}\n<a href='https://maps.google.com/?q={pedido['ubicacion']['lat']},{pedido['ubicacion']['lon']}'>Ver mapa</a>", markup)
            send_safe(client_id, "Encontramos prestadores cercanos. Esperando respuesta...")
            return
        if not urgencia_enviada and time.time() - start > 90:
            urgencia_enviada = True
            urg_rows = asyncio.run(db_execute("SELECT DISTINCT w.chat_id FROM workers w JOIN worker_services ws ON w.chat_id = ws.chat_id WHERE ws.servicio = ?", (pedido["servicio"],)))
            for (w_id,) in urg_rows:
                send_safe(w_id, f"‼️ URGENTE ‼️\nPedido de {pedido['servicio']} sin respuesta.\n<a href='https://maps.google.com/?q={pedido['ubicacion']['lat']},{pedido['ubicacion']['lon']}'>Ver ubicación</a>")
        time.sleep(espera)
        radio += incremento
    send_safe(client_id, "No encontramos prestadores disponibles ahora.")

@bot.callback_query_handler(func=lambda call: call.data.startswith(("aceptar_", "rechazar_")))
def handle_worker_response(call):
    worker_id = str(call.message.chat.id)
    action, client_id = call.data.split("_", 1)
    client_id = str(client_id)
    if action == "aceptar":
        asyncio.run(db_execute("UPDATE workers SET disponible = 0 WHERE chat_id = ?", (worker_id,), commit=True))
        send_safe(worker_id, "🎉 Tomaste el pedido. Contactá al cliente.")
        send_safe(client_id, "¡Un prestador aceptó tu pedido!")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Recibí el servicio", callback_data=f"cliente_ok_{worker_id}"))
        markup.add(types.InlineKeyboardButton("❌ Problema", callback_data=f"cliente_no_{worker_id}"))
        send_safe(client_id, f"El prestador está en camino.", markup)
    else:
        send_safe(worker_id, "Rechazaste el pedido.")

@bot.message_handler(commands=['cancel'])
def cancel_process(message):
    chat_id = message.chat.id
    old_state = get_state(chat_id)["state"]
    clear_state(chat_id)
    send_safe(chat_id, "Proceso cancelado." if old_state != "idle" else "No había proceso activo.")

@bot.message_handler(commands=['start'])
def start_command(message):
    send_safe(message.chat.id, "👋 Bienvenido!\n\n/soytrabajador → registrarte como prestador\n/pedirservicio → solicitar un servicio\n/cancel → salir de cualquier proceso")

@bot.message_handler(func=lambda m: True)
def fallback(message):
    state = get_state(message.chat.id)["state"]
    if state == "idle":
        send_safe(message.chat.id, "Usá /start para ver opciones.")
    else:
        send_safe(message.chat.id, "Estoy esperando algo específico. Usa /cancel si querés reiniciar.")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(init_db())
    except Exception as e:
        logger.error(f"❌ Error DB: {e}")
        print(f"❌ Error DB: {e}")
        raise

    logger.info("🤖 Bot iniciado correctamente en Railway")
    print("🤖 Bot corriendo...")

    bot.infinity_polling(timeout=30, long_polling_timeout=30, skip_pending=True)
