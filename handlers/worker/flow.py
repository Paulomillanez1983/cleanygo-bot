from telebot import types
from config import bot
from models.user_state import set_state, update_data, get_data, clear_state, UserState, get_session
from models.services_data import SERVICES
from utils.icons import Icons
from utils.keyboards import get_service_selector
from handlers.common import send_safe
from database import db_execute
import re
import time

# -----------------------------
# INICIO DEL FLUJO DE TRABAJADOR
# -----------------------------
@bot.message_handler(func=lambda m: m.text and ("trabajar" in m.text.lower() or "prestador" in m.text.lower()))
def handle_worker_start(message):
    start_worker_flow(message.chat.id)

def start_worker_flow(chat_id: str):
    """Inicia registro de trabajador"""
    worker = db_execute("SELECT * FROM workers WHERE chat_id = ?", (str(chat_id),), fetch_one=True)
    
    if worker:
        from handlers.worker.profile import show_worker_menu
        show_worker_menu(chat_id, worker)
        return
    
    set_state(chat_id, UserState.WORKER_SELECTING_SERVICES, {"selected_services": []})
    
    welcome_text = f"""
{Icons.BRIEFCASE} <b>Registro de Profesional</b>

¡Excelente! Vamos a configurar tu perfil para que puedas recibir trabajos.

<b>Paso 1/5:</b> ¿Qué servicios ofrecés?
{Icons.INFO} Podés seleccionar varios
    """
    
    send_safe(chat_id, welcome_text, get_service_selector([]))

# -----------------------------
# SELECCIÓN DE SERVICIOS
# -----------------------------
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
    
    from handlers.common import edit_safe
    edit_safe(chat_id, call.message.message_id, call.message.text, get_service_selector(selected))

@bot.callback_query_handler(func=lambda c: c.data == "svc_confirm")
def handle_service_confirm(call):
    chat_id = call.message.chat.id
    selected = get_data(chat_id, "selected_services", [])
    
    if not selected:
        bot.answer_callback_query(call.id, "Seleccioná al menos un servicio")
        return
    
    bot.answer_callback_query(call.id, f"✓ {len(selected)} servicios seleccionados")
    
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except:
        pass
    
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

# -----------------------------
# INGRESO DE PRECIOS
# -----------------------------
def ask_next_price(chat_id: str):
    """Pide precio para el siguiente servicio"""
    services = get_data(chat_id, "services_to_price", [])
    idx = get_data(chat_id, "current_service_idx", 0)
    
    if idx >= len(services):
        set_state(chat_id, UserState.WORKER_ENTERING_NAME)
        text = f"""
{Icons.USER} <b>Paso 2/5: Tu nombre</b>

¿Cómo te llaman los clientes?
{Icons.INFO} Ingresá tu nombre completo
        """
        bot.send_message(chat_id, text, parse_mode="HTML")
        return
    
    service_id = services[idx]
    svc_name = SERVICES[service_id]["name"]
    
    text = f"""
{Icons.MONEY} <b>Paso 1/5: Precios ({idx+1}/{len(services)})</b>

¿Cuál es tu tarifa por hora para:
{SERVICES[service_id]['icon']} <b>{svc_name}</b>?

{Icons.INFO} Ingresá solo el número (ej: 5000)
    """
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("⏭️ Saltar este servicio"))
    
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text and "Saltar" in m.text and get_session(m.chat.id).state == UserState.WORKER_ENTERING_PRICE)
def handle_skip_service_text(message):
    chat_id = message.chat.id
    services = get_data(chat_id, "services_to_price", [])
    idx = get_data(chat_id, "current_service_idx", 0)
    
    if idx < len(services):
        current_service = services[idx]
        bot.send_message(chat_id, f"⏭️ {SERVICES[current_service]['name']} saltado")
    
    update_data(chat_id, current_service_idx=idx + 1)
    ask_next_price(chat_id)

@bot.message_handler(func=lambda m: get_session(m.chat.id).state == UserState.WORKER_ENTERING_PRICE)
def handle_price_input(message):
    chat_id = message.chat.id
    text = message.text.strip()
    
    if "Saltar" in text:
        return
    
    try:
        price = float(text)
        if price < 1000 or price > 50000:
            send_safe(chat_id, f"{Icons.WARNING} Precio fuera de rango (1000-50000)")
            return
    except ValueError:
        send_safe(chat_id, f"{Icons.ERROR} Ingresá solo números (ej: 5000)")
        return
    
    services = get_data(chat_id, "services_to_price", [])
    idx = get_data(chat_id, "current_service_idx", 0)
    
    if idx >= len(services):
        ask_next_price(chat_id)
        return
        
    current_service = services[idx]
    prices = get_data(chat_id, "prices", {})
    prices[current_service] = price
    
    db_execute(
        "INSERT OR REPLACE INTO worker_services (chat_id, service_id, precio) VALUES (?, ?, ?)",
        (str(chat_id), current_service, price),
        commit=True
    )
    
    from handlers.common import format_price
    send_safe(chat_id, f"{Icons.SUCCESS} {SERVICES[current_service]['name']}: {format_price(price)}/hora")
    
    update_data(chat_id, prices=prices, current_service_idx=idx + 1)
    ask_next_price(chat_id)

# -----------------------------
# INGRESO DE NOMBRE Y TELÉFONO
# -----------------------------
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
    bot.send_message(chat_id, text, parse_mode="HTML")

@bot.message_handler(func=lambda m: get_session(m.chat.id).state == UserState.WORKER_ENTERING_PHONE)
def handle_phone_input(message):
    chat_id = message.chat.id
    phone = re.sub(r'\D', '', message.text.strip())
    
    if len(phone) < 10:
        send_safe(chat_id, f"{Icons.WARNING} Número inválido. Ingresá al menos 10 dígitos.")
        return
    
    update_data(chat_id, worker_phone=phone)
    set_state(chat_id, UserState.WORKER_UPLOADING_DNI)
    
    text = f"""
{Icons.CAMERA} <b>Paso 4/5: Verificación de identidad</b>

Para la seguridad de todos, necesitamos verificar tu identidad.

{Icons.INFO} Enviá una foto de tu DNI (frente o reverso)
    """
    bot.send_message(chat_id, text, parse_mode="HTML")

# -----------------------------
# SUBIDA DE DNI
# -----------------------------
@bot.message_handler(content_types=['photo'], 
                    func=lambda m: get_session(m.chat.id).state == UserState.WORKER_UPLOADING_DNI)
def handle_dni_upload(message):
    chat_id = message.chat.id
    file_id = message.photo[-1].file_id
    
    name = get_data(chat_id, "worker_name")
    phone = get_data(chat_id, "worker_phone")
    
    db_execute(
        "UPDATE workers SET nombre = ?, telefono = ?, dni_file_id = ? WHERE chat_id = ?",
        (name, phone, file_id, str(chat_id)),
        commit=True
    )
    
    set_state(chat_id, UserState.WORKER_SHARING_LOCATION)
    ask_worker_location(chat_id)

# -----------------------------
# PEDIR UBICACIÓN CON BOTÓN NATIVO
# -----------------------------
def ask_worker_location(chat_id: str):
    text = f"""
{Icons.LOCATION} <b>Paso 5/5: Ubicación de trabajo</b>

Enviá tu ubicación para recibir avisos de trabajos cercanos.
Podés actualizarla cuando quieras con /ubicacion
"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("📍 Enviar mi ubicación", request_location=True))
    markup.add(types.KeyboardButton("❌ Cancelar"))
    
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

# -----------------------------
# HANDLER DE UBICACIÓN
# -----------------------------
@bot.message_handler(content_types=['location'])
def handle_worker_location(message):
    chat_id = message.chat.id
    session = get_session(chat_id)

    if not session or str(session.state) != str(UserState.WORKER_SHARING_LOCATION):
        return

    if not hasattr(message, "location") or not message.location:
        bot.send_message(chat_id, f"{Icons.ERROR} No se pudo detectar tu ubicación. Intentá usar el botón nativo de Telegram.")
        return

    lat = message.location.latitude
    lon = message.location.longitude

    try:
        process_worker_location(chat_id, lat, lon)
    except:
        bot.send_message(chat_id, f"{Icons.ERROR} Error al guardar tu ubicación. Intentá nuevamente o escribí /cancel")

# -----------------------------
# PROCESAR UBICACIÓN ENTERPRISE
# -----------------------------
def process_worker_location(chat_id: str, lat: float, lon: float):
    """Procesa la ubicación y cierra el flujo correctamente sin que quede clavado"""
    timestamp = int(time.time())

    # 1️⃣ Guardar ubicación
    db_execute(
        "UPDATE workers SET lat = ?, lon = ?, last_update = ?, disponible = 1 WHERE chat_id = ?",
        (lat, lon, timestamp, str(chat_id)),
        commit=True
    )

    # 2️⃣ Limpiar estado
    clear_state(chat_id)

    # 3️⃣ Mensaje inmediato de confirmación
    bot.send_message(
        chat_id,
        "✅ Ubicación recibida correctamente",
        reply_markup=types.ReplyKeyboardRemove()
    )

    # 4️⃣ Enviar mensaje final de registro completo
    final_text = f"""
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
    bot.send_message(
        chat_id,
        final_text,
        parse_mode="HTML",
        reply_markup=types.ReplyKeyboardRemove()
    )
