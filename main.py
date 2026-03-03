import telebot
from telebot import types
import re
import math
import threading
import time
import json
import os

TOKEN = "8534288619:AAG1i5-PdjUABerTQCp_y84XubBfVNJ34FU"
bot = telebot.TeleBot(TOKEN)

# ==============================
# 🔹 Datos persistentes temporales
# ==============================
DATA_FILE = "bot_data.json"

if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        data = json.load(f)
        workers = data.get("workers", {})
        clients = data.get("clients", {})
else:
    workers = {}
    clients = {}

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump({"workers": workers, "clients": clients}, f)

# ==============================
# 🔹 Helpers
# ==============================
def send_safe(chat_id, text, reply_markup=None):
    try:
        bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        print(f"No se pudo enviar mensaje a {chat_id}: {e}")

def validate_hora(text):
    return bool(re.match(r'^([01]\d|2[0-3]):([0-5]\d)$', text))

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

services_list = ["Niñera", "Cuidado de personas", "Instalación de aire acondicionado", "Visita técnica de aire acondicionado"]

# ==============================
# 🔹 Registro trabajador y precios
# ==============================
@bot.message_handler(commands=['soytrabajador'])
def start_worker_registration(message):
    chat_id = str(message.chat.id)
    workers[chat_id] = {"servicios": [], "precios": {}, "disponible": True, "info": {}, "ubicacion": {}}
    clients[chat_id] = {"estado": "seleccionando_servicios", "pedido": {}}
    save_data()
    ask_services_worker(chat_id)

def ask_services_worker(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for s in services_list:
        markup.add(types.InlineKeyboardButton(s, callback_data=f"service_{s}"))
    markup.add(types.InlineKeyboardButton("✅ Confirmar servicios", callback_data="confirm_services"))
    send_safe(chat_id, "Seleccioná los servicios que ofrecés (podés elegir varios):", markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("service_") or call.data=="confirm_services")
def handle_service_selection(call):
    chat_id = str(call.message.chat.id)
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
        save_data()
    elif data == "confirm_services":
        if not workers[chat_id]["servicios"]:
            bot.answer_callback_query(call.id, "Debes seleccionar al menos un servicio")
            return
        bot.answer_callback_query(call.id, "Servicios confirmados")
        send_safe(chat_id, f"✅ Servicios seleccionados: {', '.join(workers[chat_id]['servicios'])}")
        clients[chat_id]["estado"] = "ingresando_precios"
        save_data()
        ask_price_worker(chat_id, 0)

def ask_price_worker(chat_id, index):
    if index >= len(workers[chat_id]["servicios"]):
        send_safe(chat_id, "✅ Todos los precios ingresados. Ahora ingrese sus datos personales.")
        clients[chat_id]["estado"] = "ingresando_info"
        save_data()
        ask_worker_info(chat_id)
        return
    service = workers[chat_id]["servicios"][index]
    clients[chat_id]["pedido"]["index_price"] = index
    send_safe(chat_id, f"Ingresá el precio para '{service}':")

@bot.message_handler(func=lambda m: clients.get(str(m.chat.id), {}).get("estado")=="ingresando_precios")
def handle_worker_price(message):
    chat_id = str(message.chat.id)
    try:
        index = clients[chat_id]["pedido"]["index_price"]
        service = workers[chat_id]["servicios"][index]
        price = float(message.text)
        if price <= 0:
            send_safe(chat_id, "❌ Ingresá un precio válido mayor a 0")
            return
        workers[chat_id]["precios"][service] = price
        send_safe(chat_id, f"💰 Precio de '{service}' registrado: ${price}")
        save_data()
        ask_price_worker(chat_id, index+1)
    except ValueError:
        send_safe(chat_id, "❌ Ingresá un número válido para el precio.")

def ask_worker_info(chat_id):
    send_safe(chat_id, "📄 Enviá tu nombre completo:")
    clients[chat_id]["estado"] = "nombre_worker"
    save_data()

@bot.message_handler(func=lambda m: clients.get(str(m.chat.id), {}).get("estado")=="nombre_worker")
def handle_worker_name(message):
    chat_id = str(message.chat.id)
    workers[chat_id]["info"]["nombre"] = message.text
    send_safe(chat_id, "📄 Ahora enviá una foto de tu DNI (frontal):")
    clients[chat_id]["estado"] = "dni_worker"
    save_data()

@bot.message_handler(content_types=['photo'], func=lambda m: clients.get(str(m.chat.id), {}).get("estado")=="dni_worker")
def handle_worker_dni(message):
    chat_id = str(message.chat.id)
    file_id = message.photo[-1].file_id
    workers[chat_id]["info"]["dni"] = file_id
    send_safe(chat_id, "✅ Registro completo. Ahora estás en línea para recibir pedidos.\nPodés usar /offline para salir de línea.")
    clients[chat_id]["estado"] = "en_linea"
    workers[chat_id]["disponible"] = True
    save_data()

@bot.message_handler(commands=['offline'])
def go_offline(message):
    chat_id = str(message.chat.id)
    if chat_id in workers:
        workers[chat_id]["disponible"] = False
        send_safe(chat_id, "🛑 Ahora estás fuera de línea. No recibirás nuevos pedidos.")
        save_data()
    else:
        send_safe(chat_id, "❌ No estás registrado como trabajador.")

# ==============================
# 🔹 Actualizar ubicación trabajador
# ==============================
@bot.message_handler(commands=['actualizarubicacion'])
def update_worker_location(message):
    chat_id = str(message.chat.id)
    if chat_id not in workers:
        send_safe(chat_id, "❌ No estás registrado como trabajador.")
        return
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("📍 Enviar ubicación", request_location=True))
    send_safe(chat_id, "📍 Por favor enviá tu ubicación actual:", markup)
    clients[chat_id]["estado"] = "actualizando_ubicacion"
    save_data()

@bot.message_handler(content_types=['location'], func=lambda m: clients.get(str(m.chat.id), {}).get("estado")=="actualizando_ubicacion")
def handle_worker_location(message):
    chat_id = str(message.chat.id)
    location = message.location
    workers[chat_id]["ubicacion"] = {"lat": location.latitude, "lon": location.longitude}
    send_safe(chat_id, "✅ Ubicación actualizada.")
    clients[chat_id]["estado"] = "en_linea"
    save_data()

# ==============================
# 🔹 Cliente solicita servicio
# ==============================
@bot.message_handler(commands=['pedirservicio'])
def request_service(message):
    chat_id = str(message.chat.id)
    clients[chat_id] = {"estado": "seleccionando_servicio", "pedido": {}, "pedido_abierto": True}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for s in services_list:
        markup.add(s)
    send_safe(chat_id, "📝 Seleccioná el servicio que necesitás:", markup)
    save_data()

@bot.message_handler(func=lambda m: clients.get(str(m.chat.id), {}).get("estado")=="seleccionando_servicio")
def handle_client_service(message):
    chat_id = str(message.chat.id)
    service = message.text
    if service not in services_list:
        send_safe(chat_id, "❌ Servicio inválido, seleccioná uno de la lista.")
        return
    clients[chat_id]["pedido"]["servicio"] = service
    clients[chat_id]["estado"] = "ingresando_ubicacion"
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("📍 Enviar ubicación", request_location=True))
    send_safe(chat_id, "📍 Enviá tu ubicación para el servicio:", markup)
    save_data()

@bot.message_handler(content_types=['location'], func=lambda m: clients.get(str(m.chat.id), {}).get("estado")=="ingresando_ubicacion")
def handle_client_location(message):
    chat_id = str(message.chat.id)
    location = message.location
    clients[chat_id]["pedido"]["ubicacion"] = {"lat": location.latitude, "lon": location.longitude}
    clients[chat_id]["estado"] = "ingresando_horario"
    send_safe(chat_id, "🕒 Ingresá la hora para el servicio (HH:MM):")
    save_data()

@bot.message_handler(func=lambda m: clients.get(str(m.chat.id), {}).get("estado")=="ingresando_horario")
def handle_client_hora(message):
    chat_id = str(message.chat.id)
    hora = message.text
    if not validate_hora(hora):
        send_safe(chat_id, "❌ Formato inválido. Ingresá la hora como HH:MM")
        return
    clients[chat_id]["pedido"]["hora"] = hora
    pedido = clients[chat_id]["pedido"]
    ubic_cliente = pedido["ubicacion"]
    markup_confirm = types.InlineKeyboardMarkup()
    markup_confirm.add(types.InlineKeyboardButton("✅ Confirmar pedido", callback_data="confirmar_pedido"))
    send_safe(chat_id,
              f"📋 <b>Resumen del pedido</b>\n"
              f"Servicio: {pedido['servicio']}\n"
              f"Hora: {hora}\n"
              f"Ubicación: {ubic_cliente['lat']}, {ubic_cliente['lon']}\n"
              f"Mapa: <a href='https://www.google.com/maps/search/?api=1&query={ubic_cliente['lat']},{ubic_cliente['lon']}'>Ver en mapa</a>",
              markup_confirm)
    clients[chat_id]["estado"] = "confirmando_pedido"
    save_data()

# ==============================
# 🔹 Enviar pedido con reintentos y urgencia
# ==============================
def enviar_pedido_con_reintentos(client_id, pedido, radio_inicial=5, max_radio=20, incremento=5, espera_segundos=30):
    radio_km = radio_inicial
    start_time = time.time()
    alerta_urgencia_enviada = False

    while clients.get(client_id, {}).get("pedido_abierto", False) and radio_km <= max_radio:
        found = False
        map_markers = []

        for worker_id, worker_data in workers.items():
            if (pedido["servicio"] in worker_data["servicios"] and
                worker_data.get("disponible") and
                "lat" in worker_data.get("ubicacion", {}) and
                "lon" in worker_data.get("ubicacion", {})):

                distancia = haversine(pedido["ubicacion"]["lat"], pedido["ubicacion"]["lon"],
                                      worker_data["ubicacion"]["lat"], worker_data["ubicacion"]["lon"])
                if distancia <= radio_km:
                    found = True
                    map_markers.append(f"{worker_data['ubicacion']['lat']},{worker_data['ubicacion']['lon']}")
                    markup_worker = types.InlineKeyboardMarkup()
                    markup_worker.add(types.InlineKeyboardButton("✅ Aceptar", callback_data=f"aceptar_{client_id}"))
                    markup_worker.add(types.InlineKeyboardButton("❌ Rechazar", callback_data=f"rechazar_{client_id}"))
                    send_safe(worker_id,
                              f"🚨 Nuevo pedido cerca de ti ({distancia:.2f} km):\n"
                              f"Servicio: {pedido['servicio']}\n"
                              f"Hora: {pedido['hora']}\n"
                              f"Ubicación: {pedido['ubicacion']['lat']}, {pedido['ubicacion']['lon']}\n"
                              f"<a href='https://www.google.com/maps/search/?api=1&query={pedido['ubicacion']['lat']},{pedido['ubicacion']['lon']}'>Ver en mapa</a>",
                              markup_worker)

        if map_markers:
            base_url = "https://www.google.com/maps/dir/"
            map_url = base_url + "/".join(map_markers + [f"{pedido['ubicacion']['lat']},{pedido['ubicacion']['lon']}"])
            send_safe(client_id, f"🗺️ Trabajadores cercanos visualizados en mapa:\n{map_url}")

        if not alerta_urgencia_enviada and time.time() - start_time > 60:
            for worker_id, worker_data in workers.items():
                if pedido["servicio"] in worker_data["servicios"]:
                    send_safe(worker_id,
                              f"‼️ <b>URGENTE</b> ‼️\nPedido '{pedido['servicio']}' sin aceptación en 60s.\n"
                              f"<a href='https://www.google.com/maps/search/?api=1&query={pedido['ubicacion']['lat']},{pedido['ubicacion']['lon']}'>Ver ubicación</a>")
            alerta_urgencia_enviada = True

        if found:
            break
        else:
            time.sleep(espera_segundos)
            radio_km += incremento

    if clients.get(client_id, {}).get("pedido_abierto", False):
        markup_retry = types.InlineKeyboardMarkup()
        markup_retry.add(types.InlineKeyboardButton("🔄 Reintentar búsqueda", callback_data="reintentar_pedido"))
        send_safe(client_id, "⚠️ Lo sentimos, no se encontró ningún trabajador disponible para tu pedido.", markup_retry)

# ==============================
# 🔹 Botón reintentar para cliente
# ==============================
@bot.callback_query_handler(func=lambda call: call.data=="reintentar_pedido")
def reintentar_pedido(call):
    chat_id = str(call.message.chat.id)
    if chat_id in clients and clients[chat_id].get("pedido"):
        pedido = clients[chat_id]["pedido"].copy()
        clients[chat_id]["pedido_abierto"] = True
        threading.Thread(target=enviar_pedido_con_reintentos, args=(chat_id, pedido), daemon=True).start()
        send_safe(chat_id, "🔄 Reintentando búsqueda de prestadores cercanos...")
        save_data()

# ==============================
# 🔹 Confirmar pedido
# ==============================
@bot.callback_query_handler(func=lambda call: call.data=="confirmar_pedido")
def confirm_pedido(call):
    chat_id = str(call.message.chat.id)
    if chat_id not in clients:
        send_safe(chat_id, "❌ Error interno: cliente no registrado.")
        return
    pedido = clients[chat_id]["pedido"].copy()
    clients[chat_id]["pedido_abierto"] = True
    clients[chat_id]["estado"] = "buscando_prestador"
    threading.Thread(target=enviar_pedido_con_reintentos, args=(chat_id, pedido), daemon=True).start()
    send_safe(chat_id, "✅ Pedido enviado a los prestadores cercanos. Esperá que acepten.")
    save_data()

# ==============================
# 🔹 Confirmación llegada prestador al cliente
# ==============================
def enviar_confirmacion_cliente(client_id, servicio, prestador_id):
    markup_cliente = types.InlineKeyboardMarkup()
    markup_cliente.add(types.InlineKeyboardButton("✅ Aceptar servicio", callback_data=f"cliente_aceptar_{prestador_id}"))
    markup_cliente.add(types.InlineKeyboardButton("❌ Rechazar servicio", callback_data=f"cliente_rechazar_{prestador_id}"))
    send_safe(client_id,
              f"📌 Tu prestador ha llegado para el servicio '{servicio}'.\nConfirmá si recibiste el servicio:",
              markup_cliente)

@bot.callback_query_handler(func=lambda call: call.data.startswith("cliente_aceptar_") or call.data.startswith("cliente_rechazar_"))
def handle_cliente_confirmacion(call):
    client_id = str(call.message.chat.id)
    action, prestador_id = call.data.split("_")[1:]  # ['aceptar', 'prestador_id']

    if action == "aceptar":
        send_safe(client_id, "✅ Has confirmado la recepción del servicio. ¡Gracias!")
        send_safe(prestador_id, "🎉 El cliente ha confirmado que recibiste el servicio.")
    else:
        send_safe(client_id, "❌ Has rechazado el servicio. Por favor contactá al prestador.")
        send_safe(prestador_id, "⚠️ El cliente rechazó el servicio.")

# ==============================
# 🔹 Trabajador acepta/rechaza pedido
# ==============================
@bot.callback_query_handler(func=lambda call: call.data.startswith("aceptar_") or call.data.startswith("rechazar_"))
def handle_worker_response(call):
    worker_id = str(call.message.chat.id)
    action, client_id = call.data.split("_")

   if client_id not in clients:
        send_safe(worker_id, "❌ Pedido ya no existe o fue cancelado.")
        return

    if action == "aceptar":
        if not clients[client_id].get("pedido_abierto", True):
            send_safe(worker_id, "❌ Lo sentimos, otro trabajador ya tomó este pedido.")
            return

        # Marcar el pedido como tomado y trabajador ocupado
        clients[client_id]["pedido_abierto"] = False
        workers[worker_id]["disponible"] = False
        clients[client_id]["estado"] = "servicio_en_progreso"
        save_data()

        send_safe(worker_id, "🎉 Tomaste el trabajo. Contactá al cliente para coordinar.")
        # Notificar cliente que un trabajador aceptó
        enviar_confirmacion_cliente(client_id, clients[client_id]["pedido"]["servicio"], worker_id)
    else:
        send_safe(worker_id, "❌ Has rechazado el pedido.")

# ==============================
# 🔹 Comando /start
# ==============================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = str(message.chat.id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("Soy trabajador", "Quiero pedir un servicio")
    send_safe(chat_id, "👋 Bienvenido al Bot de Servicios.\nSeleccioná una opción:", markup)

# ==============================
# 🔹 Manejo de texto principal
# ==============================
@bot.message_handler(func=lambda m: True)
def main_text_handler(message):
    chat_id = str(message.chat.id)
    text = message.text.lower()
    if "soy trabajador" in text:
        start_worker_registration(message)
    elif "quiero pedir un servicio" in text:
        request_service(message)
    else:
        send_safe(chat_id, "❌ No entendí tu mensaje. Usá los botones para continuar.")

# ==============================
# 🔹 Iniciar bot
# ==============================
print("🤖 Bot iniciado...")
bot.infinity_polling():
