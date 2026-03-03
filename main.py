import telebot
from telebot import types

# ==============================
# 🔑 Token del bot
# ==============================
TOKEN = "8534288619:AAG1i5-PdjUABerTQCp_y84XubBfVNJ34FU"
bot = telebot.TeleBot(TOKEN)

# ==============================
# 💾 Datos en memoria
# ==============================
workers = {}  # chat_id -> {"servicios": [], "precios": {}, "disponible": True, "info": {}}
clients = {}  # chat_id -> {"estado": str, "pedido": {}}
services_list = ["Niñera", "Cuidado de personas", "Instalación de aire acondicionado", "Visita técnica de aire acondicionado"]

# ==============================
# 🔹 /start
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
# 🔹 /soytrabajador - inicio registro proveedor
# ==============================
@bot.message_handler(commands=['soytrabajador'])
def start_worker_registration(message):
    chat_id = message.chat.id
    workers[chat_id] = {"servicios": [], "precios": {}, "disponible": True, "info": {}}
    clients[chat_id] = {"estado": "seleccionando_servicios", "pedido": {}}
    ask_services_worker(chat_id)

def ask_services_worker(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for s in services_list:
        markup.add(types.InlineKeyboardButton(s, callback_data=f"service_{s}"))
    markup.add(types.InlineKeyboardButton("✅ Confirmar servicios", callback_data="confirm_services"))
    bot.send_message(chat_id, "Seleccioná los servicios que ofrecés (podés elegir varios):", reply_markup=markup)

# ==============================
# 🔹 Manejo selección múltiple de servicios
# ==============================
@bot.callback_query_handler(func=lambda call: call.data.startswith("service_") or call.data=="confirm_services")
def handle_service_selection(call):
    chat_id = call.message.chat.id
    data = call.data
    if chat_id not in workers:
        bot.answer_callback_query(call.id, "No estás registrado como trabajador")
        return

    if data.startswith("service_"):
        service = data.replace("service_", "")
        if service in workers[chat_id]["servicios"]:
            workers[chat_id]["servicios"].remove(service)
            bot.answer_callback_query(call.id, f"❌ {service} eliminado")
        else:
            workers[chat_id]["servicios"].append(service)
            bot.answer_callback_query(call.id, f"✅ {service} agregado")
    elif data == "confirm_services":
        if not workers[chat_id]["servicios"]:
            bot.answer_callback_query(call.id, "Debes seleccionar al menos un servicio")
            return
        bot.answer_callback_query(call.id, "Servicios confirmados")
        bot.send_message(chat_id, f"✅ Servicios seleccionados: {', '.join(workers[chat_id]['servicios'])}")
        clients[chat_id]["estado"] = "ingresando_precios"
        ask_price_worker(chat_id, 0)

# ==============================
# 🔹 Registro de precios por servicio
# ==============================
def ask_price_worker(chat_id, index):
    if index >= len(workers[chat_id]["servicios"]):
        bot.send_message(chat_id, "✅ Todos los precios ingresados. Ahora ingrese sus datos personales.")
        clients[chat_id]["estado"] = "ingresando_info"
        ask_worker_info(chat_id)
        return
    service = workers[chat_id]["servicios"][index]
    clients[chat_id]["pedido"]["index_price"] = index
    bot.send_message(chat_id, f"Ingresá el precio para '{service}':")

@bot.message_handler(func=lambda m: clients.get(m.chat.id, {}).get("estado")=="ingresando_precios")
def handle_worker_price(message):
    chat_id = message.chat.id
    try:
        index = clients[chat_id]["pedido"]["index_price"]
        service = workers[chat_id]["servicios"][index]
        price = float(message.text)
        workers[chat_id]["precios"][service] = price
        bot.send_message(chat_id, f"💰 Precio de '{service}' registrado: ${price}")
        ask_price_worker(chat_id, index+1)
    except ValueError:
        bot.send_message(chat_id, "❌ Ingresá un número válido para el precio.")

# ==============================
# 🔹 Registro datos personales proveedor
# ==============================
def ask_worker_info(chat_id):
    bot.send_message(chat_id, "📄 Enviá tu nombre completo:")
    clients[chat_id]["estado"] = "nombre_worker"

@bot.message_handler(func=lambda m: clients.get(m.chat.id, {}).get("estado")=="nombre_worker")
def handle_worker_name(message):
    chat_id = message.chat.id
    workers[chat_id]["info"]["nombre"] = message.text
    bot.send_message(chat_id, "📄 Ahora enviá una foto de tu DNI (foto frontal):")
    clients[chat_id]["estado"] = "dni_worker"

@bot.message_handler(content_types=['photo'], func=lambda m: clients.get(m.chat.id, {}).get("estado")=="dni_worker")
def handle_worker_dni(message):
    chat_id = message.chat.id
    file_id = message.photo[-1].file_id
    workers[chat_id]["info"]["dni"] = file_id
    bot.send_message(chat_id, "✅ Registro completo. Ya podés recibir pedidos.")
    clients[chat_id]["estado"] = "registro_completo"

# ==============================
# 🔹 /pedirservicio (cliente) - igual que antes
# ==============================
@bot.message_handler(commands=['pedirservicio'])
def request_service(message):
    chat_id = message.chat.id
    clients[chat_id] = {"estado": "seleccionando_servicio", "pedido": {}}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for s in services_list:
        markup.add(s)
    bot.send_message(chat_id, "📝 Seleccioná el servicio que necesitás:", reply_markup=markup)

# Aquí se mantiene igual flujo de cliente: dirección → horario → notificación a proveedores

# ==============================
# 🔄 Mantener bot en ejecución
# ==============================
print("🤖 Bot iniciado y listo para usar...")
bot.polling(non_stop=True)
