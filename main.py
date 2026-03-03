import telebot
from telebot import types
import re

TOKEN = "8534288619:AAG1i5-PdjUABerTQCp_y84XubBfVNJ34FU"
bot = telebot.TeleBot(TOKEN)

# 💾 Datos en memoria
workers = {}  # chat_id -> {"servicios": [], "precios": {}, "disponible": True, "info": {}}
clients = {}  # chat_id -> {"estado": str, "pedido": {}}
services_list = ["Niñera", "Cuidado de personas", "Instalación de aire acondicionado", "Visita técnica de aire acondicionado"]

# ==============================
# 🔹 Helpers
# ==============================
def send_safe(chat_id, text, reply_markup=None):
    try:
        bot.send_message(chat_id, text, reply_markup=reply_markup)
    except Exception as e:
        print(f"No se pudo enviar mensaje a {chat_id}: {e}")

def validate_hora(text):
    return bool(re.match(r'^([01]\d|2[0-3]):([0-5]\d)$', text))

# ==============================
# 🔹 /start
# ==============================
@bot.message_handler(commands=['start'])
def start(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("/soytrabajador", "/pedirservicio")
    send_safe(message.chat.id, "👋 Bienvenido a Clean&Go Córdoba\nSeleccioná tu rol:", markup)

# ==============================
# 🔹 Registro trabajador
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
    send_safe(chat_id, "Seleccioná los servicios que ofrecés (podés elegir varios):", markup)

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
        send_safe(chat_id, f"✅ Servicios seleccionados: {', '.join(workers[chat_id]['servicios'])}")
        clients[chat_id]["estado"] = "ingresando_precios"
        ask_price_worker(chat_id, 0)

def ask_price_worker(chat_id, index):
    if index >= len(workers[chat_id]["servicios"]):
        send_safe(chat_id, "✅ Todos los precios ingresados. Ahora ingrese sus datos personales.")
        clients[chat_id]["estado"] = "ingresando_info"
        ask_worker_info(chat_id)
        return
    service = workers[chat_id]["servicios"][index]
    clients[chat_id]["pedido"]["index_price"] = index
    send_safe(chat_id, f"Ingresá el precio para '{service}':")

@bot.message_handler(func=lambda m: clients.get(m.chat.id, {}).get("estado")=="ingresando_precios")
def handle_worker_price(message):
    chat_id = message.chat.id
    try:
        index = clients[chat_id]["pedido"]["index_price"]
        service = workers[chat_id]["servicios"][index]
        price = float(message.text)
        if price <= 0:
            send_safe(chat_id, "❌ Ingresá un precio válido mayor a 0")
            return
        workers[chat_id]["precios"][service] = price
        send_safe(chat_id, f"💰 Precio de '{service}' registrado: ${price}")
        ask_price_worker(chat_id, index+1)
    except ValueError:
        send_safe(chat_id, "❌ Ingresá un número válido para el precio.")

# ==============================
# Registro datos personales trabajador
# ==============================
def ask_worker_info(chat_id):
    send_safe(chat_id, "📄 Enviá tu nombre completo:")
    clients[chat_id]["estado"] = "nombre_worker"

@bot.message_handler(func=lambda m: clients.get(m.chat.id, {}).get("estado")=="nombre_worker")
def handle_worker_name(message):
    chat_id = message.chat.id
    workers[chat_id]["info"]["nombre"] = message.text
    send_safe(chat_id, "📄 Ahora enviá una foto de tu DNI (frontal):")
    clients[chat_id]["estado"] = "dni_worker"

@bot.message_handler(content_types=['photo'], func=lambda m: clients.get(m.chat.id, {}).get("estado")=="dni_worker")
def handle_worker_dni(message):
    chat_id = message.chat.id
    file_id = message.photo[-1].file_id
    workers[chat_id]["info"]["dni"] = file_id
    send_safe(chat_id, "✅ Registro completo. Ahora estás en línea para recibir pedidos.\nPodés usar /offline para salir de línea.")
    clients[chat_id]["estado"] = "en_linea"
    workers[chat_id]["disponible"] = True

@bot.message_handler(commands=['offline'])
def go_offline(message):
    chat_id = message.chat.id
    if chat_id in workers:
        workers[chat_id]["disponible"] = False
        send_safe(chat_id, "🛑 Ahora estás fuera de línea. No recibirás nuevos pedidos.")
    else:
        send_safe(chat_id, "❌ No estás registrado como trabajador.")

# ==============================
# Cliente solicita servicio con ubicación y horario
# ==============================
@bot.message_handler(commands=['pedirservicio'])
def request_service(message):
    chat_id = message.chat.id
    clients[chat_id] = {"estado": "seleccionando_servicio", "pedido": {}}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for s in services_list:
        markup.add(s)
    send_safe(chat_id, "📝 Seleccioná el servicio que necesitás:", markup)

@bot.message_handler(func=lambda m: clients.get(m.chat.id, {}).get("estado")=="seleccionando_servicio")
def handle_client_service(message):
    chat_id = message.chat.id
    service = message.text
    if service not in services_list:
        send_safe(chat_id, "❌ Servicio inválido, seleccioná uno de la lista.")
        return

    clients[chat_id]["pedido"]["servicio"] = service
    clients[chat_id]["estado"] = "ingresando_ubicacion"

    # Botón para enviar ubicación
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("📍 Enviar ubicación", request_location=True))
    send_safe(chat_id, "📍 Por favor enviá tu ubicación para el servicio:", markup)

@bot.message_handler(content_types=['location'], func=lambda m: clients.get(m.chat.id, {}).get("estado")=="ingresando_ubicacion")
def handle_client_location(message):
    chat_id = message.chat.id
    location = message.location
    clients[chat_id]["pedido"]["ubicacion"] = {"lat": location.latitude, "lon": location.longitude}
    clients[chat_id]["estado"] = "ingresando_horario"
    send_safe(chat_id, "🕒 Ingresá la hora para el servicio (HH:MM):")

@bot.message_handler(func=lambda m: clients.get(m.chat.id, {}).get("estado")=="ingresando_horario")
def handle_client_hora(message):
    chat_id = message.chat.id
    hora = message.text
    if not validate_hora(hora):
        send_safe(chat_id, "❌ Formato inválido. Ingresá la hora como HH:MM")
        return
    clients[chat_id]["pedido"]["hora"] = hora
    clients[chat_id]["estado"] = "confirmando_pedido"

    pedido = clients[chat_id]["pedido"]
    ubic = pedido["ubicacion"]
    send_safe(chat_id, f"✅ Pedido listo para enviar:\nServicio: {pedido['servicio']}\nHora: {hora}\nUbicación: {ubic['lat']}, {ubic['lon']}\n\nSi todo está correcto, el pedido será enviado a los prestadores disponibles.")

    # Enviar a trabajadores disponibles
    found = False
    for worker_id, worker_data in workers.items():
        if pedido["servicio"] in worker_data["servicios"] and worker_data.get("disponible"):
            found = True
            send_safe(worker_id, f"🚨 Nuevo pedido:\nServicio: {pedido['servicio']}\nHora: {hora}\nUbicación: {ubic['lat']}, {ubic['lon']}\nEscribí /aceptar para tomarlo.")

    if not found:
        send_safe(chat_id, "⚠️ No hay prestadores disponibles por el momento. Intentá más tarde.")

    clients[chat_id]["estado"] = "buscando_prestador"

@bot.message_handler(commands=['aceptar'])
def accept_job(message):
    chat_id = message.chat.id
    if chat_id in workers and workers[chat_id]["disponible"]:
        workers[chat_id]["disponible"] = False
        send_safe(chat_id, "🎉 Tomaste el trabajo. Contactá al cliente para coordinar.")
        for client_id, client_data in clients.items():
            if client_data.get("estado")=="buscando_prestador" and client_data["pedido"]["servicio"] in workers[chat_id]["servicios"]:
                send_safe(client_id, f"✅ Tu prestador ha aceptado el servicio '{client_data['pedido']['servicio']}'. Contactá para coordinar.")
                client_data["estado"] = "prestador_asignado"
    else:
        send_safe(chat_id, "❌ No estás registrado o ya no estás disponible.")

# ==============================
# Mantener bot en ejecución
# ==============================
print("🤖 Bot iniciado y listo para usar...")
bot.polling(non_stop=True)
