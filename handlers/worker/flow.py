from config import bot
from models.user_state import set_state, update_data, get_data, clear_state, UserState, get_session
from models.services_data import SERVICES
from utils.icons import Icons
from utils.keyboards import get_service_selector, get_cancel_keyboard, get_location_keyboard
from handlers.common import send_safe, remove_keyboard
from database import db_execute
import re

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
    
    send_safe(chat_id, text, get_cancel_keyboard("Saltar este servicio"))

@bot.message_handler(func=lambda m: get_session(m.chat.id).state == UserState.WORKER_ENTERING_PRICE)
def handle_price_input(message):
    chat_id = message.chat.id
    text = message.text.strip()
    
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
    
    services = get_data(chat_id, "services_to_price", [])
    idx = get_data(chat_id, "current_service_idx", 0)
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
    
    text = f"""
{Icons.LOCATION} <b>Paso 5/5: Ubicación de trabajo</b>

¿Dónde trabajás? 

{Icons.INFO} Enviá tu ubicación para recibir avisos de trabajos cercanos.
{Icons.INFO} Podés actualizarla cuando quieras con /ubicacion
    """
    
    send_safe(chat_id, text, get_location_keyboard())

@bot.message_handler(content_types=['location'], 
                    func=lambda m: get_session(m.chat.id).state == UserState.WORKER_SHARING_LOCATION)
def handle_worker_location(message):
    chat_id = message.chat.id
    lat = message.location.latitude
    lon = message.location.longitude
    
    import time
    db_execute(
        "UPDATE workers SET lat = ?, lon = ?, last_update = ?, disponible = 1 WHERE chat_id = ?",
        (lat, lon, int(time.time()), str(chat_id)),
        commit=True
    )
    
    clear_state(chat_id)
    remove_keyboard(chat_id)
    
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
