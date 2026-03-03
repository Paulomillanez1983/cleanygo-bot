import telebot
from telebot import types

# ==============================
# 🔑 Configuración del token
# ==============================
TOKEN = "8534288619:AAG1i5-PdjUABerTQCp_y84XubBfVNJ34FU"  # Pon tu token de @BotFather
if not TOKEN:
    raise ValueError("❌ No se encontró el token. Por favor poné el token de tu bot.")

bot = telebot.TeleBot(TOKEN)

# ==============================
# 💾 Datos en memoria
# ==============================
workers = {}  # {chat_id: {"servicios": [], "precios": {}, "disponible": True}}
clients = {}  # {chat_id: {"estado": str, "pedido": {}}}
services_list = ["Niñera", "Cuidado de personas", "Instalación de aire acondicionado", "Visita técnica de aire acondicionado"]

# ==============================
# 🔹 Comando /start
# ==============================
@bot.message_handler(commands=['start'])
def start(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("/soytrabajador", "/pedirservicio")
    bot.send_message(message.chat.id,
                     "👋 Bienvenido a Clean&Go Córdoba\n\n"
                     "Seleccioná tu rol:",
                     reply_markup=markup)

# ==============================
# 🔹 Registro de proveedor /soytrabajador
# ==============================
@bot.message_handler(commands=['soytrabajador'])
def register_worker(message):
    chat_id = message.chat.id
    workers[chat_id] = {"servicios": [], "precios": {}, "disponible": True}
    bot.send_message(chat_id, "✅ Registrado como trabajador. Ahora ingresá los servicios que prestás.")
    # Pasa al estado de selección de servicios
    clients[chat_id] = {"estado": "registrando_servicios", "pedido": {}}
    ask_services_worker(message)

def ask_services_worker(message):
    chat_id = message.chat.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for s in services_list:
        markup.add(s)
    bot.send_message(chat_id, "Seleccioná un servicio que ofrecés (podés enviar varios uno por uno):", reply_markup=markup)
    clients[chat_id]["estado"] = "registrando_servicios"

@bot.message_handler(func=lambda m: clients.get(m.chat.id, {}).get("estado") == "registrando_servicios")
def handle_worker_services(message):
    chat_id = message.chat.id
    service = message.text
    if service in services_list:
        workers[chat_id]["servicios"].append(service)
        bot.send_message(chat_id, f"✅ Servicio '{service}' agregado. Ahora ingresá el precio (por hora o por visita según corresponda).")
        clients[chat_id]["estado"] = "registrando_precios"
        clients[chat_id]["pedido"]["ultimo_servicio"] = service
    else:
        bot.send_message(chat_id, "❌ Servicio inválido, seleccioná uno de la lista.")

@bot.message_handler(func=lambda m: clients.get(m.chat.id, {}).get("estado") == "registrando_precios")
def handle_worker_prices(message):
    chat_id = message.chat.id
    price = message.text
    service = clients[chat_id]["pedido"]["ultimo_servicio"]
    try:
        workers[chat_id]["precios"][service] = float(price)
        bot.send_message(chat_id, f"💰 Precio de '{service}' registrado: ${price}")
        # Preguntar si quiere agregar otro servicio
        ask_services_worker(message)
    except ValueError:
        bot.send_message(chat_id, "❌ Ingresá un número válido para el precio.")

# ==============================
# 🔹 Solicitar servicio /pedirservicio
# ==============================
@bot.message_handler(commands=['pedirservicio'])
def request_service(message):
    chat_id = message.chat.id
    clients[chat_id] = {"estado": "seleccionando_servicio", "pedido": {}}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for s in services_list:
        markup.add(s)
    bot.send_message(chat_id, "📝 Seleccioná el servicio que necesitás:", reply_markup=markup)

@bot.message_handler(func=lambda m: clients.get(m.chat.id, {}).get("estado") == "seleccionando_servicio")
def handle_client_service(message):
    chat_id = message.chat.id
    service = message.text
    if service in services_list:
        clients[chat_id]["pedido"]["servicio"] = service
        clients[chat_id]["estado"] = "ingresando_direccion"
        bot.send_message(chat_id, "📍 Enviá tu dirección o compartí tu ubicación actual usando el botón de ubicación.")
    else:
        bot.send_message(chat_id, "❌ Servicio inválido, seleccioná uno de la lista.")

@bot.message_handler(func=lambda m: clients.get(m.chat.id, {}).get("estado") == "ingresando_direccion")
def handle_client_address(message):
    chat_id = message.chat.id
    if message.location:
        clients[chat_id]["pedido"]["ubicacion"] = (message.location.latitude, message.location.longitude)
        bot.send_message(chat_id, "✅ Ubicación recibida.")
    else:
        clients[chat_id]["pedido"]["direccion"] = message.text
        bot.send_message(chat_id, f"✅ Dirección registrada: {message.text}")
    clients[chat_id]["estado"] = "seleccionando_horario"
    bot.send_message(chat_id, "🕒 Ingresá el horario aproximado que necesitás el servicio (ej: 15:30)")

@bot.message_handler(func=lambda m: clients.get(m.chat.id, {}).get("estado") == "seleccionando_horario")
def handle_client_time(message):
    chat_id = message.chat.id
    clients[chat_id]["pedido"]["horario"] = message.text
    clients[chat_id]["estado"] = "pedido_completo"
    service = clients[chat_id]["pedido"]["servicio"]
    bot.send_message(chat_id, f"✅ Pedido completo para '{service}' a las {message.text}. Buscando trabajadores disponibles...")

    # Notificar a todos los trabajadores que ofrezcan ese servicio
    for worker_id, worker_data in workers.items():
        if service in worker_data["servicios"] and worker_data["disponible"]:
            try:
                bot.send_message(worker_id,
                                 f"🚨 Nuevo pedido para '{service}' disponible.\nEscribí /aceptar para tomar el trabajo.")
            except Exception as e:
                print(f"No se pudo notificar al trabajador {worker_id}: {e}")

# ==============================
# 🔹 Aceptar trabajo /aceptar
# ==============================
@bot.message_handler(commands=['aceptar'])
def accept_job(message):
    chat_id = message.chat.id
    if chat_id in workers:
        workers[chat_id]["disponible"] = False
        bot.send_message(chat_id, "🎉 Tomaste el trabajo. Contactá al cliente para coordinar.")
        # Podés agregar notificación al cliente en el futuro
    else:
        bot.send_message(chat_id, "❌ No estás registrado como trabajador.")

# ==============================
# 🔄 Mantener el bot en ejecución
# ==============================
print("🤖 Bot iniciado y listo para usar...")
bot.polling(non_stop=True)
