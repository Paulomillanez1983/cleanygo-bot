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
import logging

# Configura logging solo si no está en config (producción)
logger = logging.getLogger(__name__)

# -----------------------------
# INICIO DEL FLUJO DE TRABAJADOR
# -----------------------------
@bot.message_handler(func=lambda m: m.text and ("trabajar" in m.text.lower() or "prestador" in m.text.lower()))
def handle_worker_start(message):
    start_worker_flow(message.chat.id)

def start_worker_flow(chat_id: str):
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
    if not session:
        bot.answer_callback_query(call.id, "Sesión expirada. Inicia de nuevo con 'trabajar'", show_alert=True)
        return
    
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
        bot.answer_callback_query(call.id, "Seleccioná al menos un servicio", show_alert=True)
        return
    
    bot.answer_callback_query(call.id, f"✓ {len(selected)} servicios seleccionados")
    
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except Exception:
        pass  # no importa si ya fue borrado
    
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
    services = get_data(chat_id, "services_to_price", [])
    idx = get_data(chat_id, "current_service_idx", 0)
    
    if idx >= len(services):
        set_state(chat_id, UserState.WORKER_ENTERING_NAME)
        text = f"""
{Icons.USER} <b>Paso 2/5: Tu nombre</b>

¿Cómo te llaman los clientes?
{Icons.INFO} Ingresá tu nombre completo
        """
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
        markup.add(types.KeyboardButton("❌ Cancelar registro"))
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")
        return
    
    service_id = services[idx]
    svc_name = SERVICES[service_id]["name"]
    text = f"""
{Icons.MONEY} <b>Paso ({idx+1}/{len(services)}): Precio por hora</b>

{SERVICES[service_id]['icon']} <b>{svc_name}</b>

Ingresá tu tarifa por hora (ej: 8000)
{Icons.INFO} Solo número, entre 1000 y 50000
    """
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    markup.add(types.KeyboardButton("⏭️ Saltar este servicio"))
    markup.add(types.KeyboardButton("❌ Cancelar registro"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(func=lambda m: "cancel" in m.text.lower() and "registro" in m.text.lower())
def handle_cancel_anywhere(message):
    chat_id = message.chat.id
    clear_state(chat_id)
    bot.send_message(
        chat_id,
        "Registro cancelado. Podés volver a empezar cuando quieras escribiendo 'trabajar'.",
        reply_markup=types.ReplyKeyboardRemove()
    )

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
    
    if "Saltar" in text or "cancel" in text.lower():
        return  # ya manejado arriba
    
    try:
        price = float(text)
        if price < 1000 or price > 50000:
            send_safe(chat_id, f"{Icons.WARNING} Precio debe estar entre 1000 y 50000")
            return
    except ValueError:
        send_safe(chat_id, f"{Icons.ERROR} Ingresá solo el número (ejemplo: 8000)")
        return
    
    services = get_data(chat_id, "services_to_price", [])
    idx = get_data(chat_id, "current_service_idx", 0)
    
    current_service = services[idx]
    prices = get_data(chat_id, "prices", {})
    prices[current_service] = price
    
    try:
        db_execute(
            "INSERT OR REPLACE INTO worker_services (chat_id, service_id, precio) VALUES (?, ?, ?)",
            (str(chat_id), current_service, price),
            commit=True
        )
    except Exception as e:
        logger.error(f"Error guardando precio: {e}")
        send_safe(chat_id, f"{Icons.ERROR} Error al guardar. Intentá de nuevo o contactá soporte.")
        return
    
    from handlers.common import format_price
    send_safe(chat_id, f"{Icons.SUCCESS} {SERVICES[current_service]['name']}: {format_price(price)}/hora")
    
    update_data(chat_id, prices=prices, current_service_idx=idx + 1)
    ask_next_price(chat_id)

# -----------------------------
# NOMBRE → TELÉFONO → DNI
# -----------------------------
@bot.message_handler(func=lambda m: get_session(m.chat.id).state == UserState.WORKER_ENTERING_NAME)
def handle_name_input(message):
    chat_id = message.chat.id
    name = message.text.strip()
    
    if len(name) < 3 or len(name) > 60:
        send_safe(chat_id, f"{Icons.WARNING} El nombre debe tener entre 3 y 60 caracteres.")
        return
    
    update_data(chat_id, worker_name=name)
    set_state(chat_id, UserState.WORKER_ENTERING_PHONE)
    
    text = f"""
{Icons.PHONE} <b>Paso 3/5: Teléfono</b>

Ingresá tu número de teléfono (WhatsApp preferido)

Ejemplo: 3516123456 o 351 6123-4567
    """
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("❌ Cancelar registro"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(func=lambda m: get_session(m.chat.id).state == UserState.WORKER_ENTERING_PHONE)
def handle_phone_input(message):
    chat_id = message.chat.id
    phone = re.sub(r'\D', '', message.text.strip())
    
    if len(phone) < 9 or len(phone) > 15:
        send_safe(chat_id, f"{Icons.WARNING} Número inválido. Ingresá entre 9 y 15 dígitos.")
        return
    
    update_data(chat_id, worker_phone=phone)
    set_state(chat_id, UserState.WORKER_UPLOADING_DNI)
    
    text = f"""
{Icons.CAMERA} <b>Paso 4/5: Verificación</b>

Enviá una foto clara de tu DNI (frente o dorso, da igual)

Esto es solo para seguridad interna y se guarda encriptado.
    """
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("❌ Cancelar registro"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(content_types=['photo'], func=lambda m: get_session(m.chat.id).state == UserState.WORKER_UPLOADING_DNI)
def handle_dni_upload(message):
    chat_id = message.chat.id
    file_id = message.photo[-1].file_id  # la de mayor resolución
    
    name = get_data(chat_id, "worker_name")
    phone = get_data(chat_id, "worker_phone")
    
    try:
        db_execute(
            "UPDATE workers SET nombre = ?, telefono = ?, dni_file_id = ? WHERE chat_id = ?",
            (name, phone, file_id, str(chat_id)),
            commit=True
        )
    except Exception as e:
        logger.error(f"Error guardando DNI: {e}")
        send_safe(chat_id, f"{Icons.ERROR} Error al guardar foto. Intentá de nuevo.")
        return
    
    set_state(chat_id, UserState.WORKER_SHARING_LOCATION)
    ask_worker_location(chat_id)

# -----------------------------
# UBICACIÓN - VERSIÓN PRODUCCIÓN
# -----------------------------
def ask_worker_location(chat_id: str):
    text = f"""
📍 <b>Paso 5/5: Ubicación de trabajo</b>

Para enviarte trabajos cercanos necesitamos tu ubicación actual.

• Preferido: tocá el botón azul de abajo  
• Si no aparece: tocá el clip ➜ Ubicación ➜ Enviar mi ubicación

Podés cambiarla después con /ubicacion
    """
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True, row_width=2)
    markup.add(types.KeyboardButton("📍 Enviar mi ubicación", request_location=True))
    markup.add(types.KeyboardButton("❌ Cancelar registro"))

    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(content_types=['location', 'venue'])
def handle_worker_location(message):
    chat_id = message.chat.id
    session = get_session(chat_id)
    
    # Seguridad extra: si no está en el estado esperado, no procesamos
    if not session or session.state != UserState.WORKER_SHARING_LOCATION:
        bot.send_message(chat_id, "Parece que el registro ya terminó o fue cancelado.\nUsá /perfil o 'trabajar' para verificar.")
        return

    lat, lon = None, None
    if message.location:
        lat = message.location.latitude
        lon = message.location.longitude
    elif message.venue:
        lat = message.venue.location.latitude
        lon = message.venue.location.longitude

    if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        send_safe(chat_id, "❌ Ubicación no válida. Usá el botón azul 'Enviar mi ubicación'.")
        return

    timestamp = int(time.time())
    
    try:
        db_execute(
            """
            UPDATE workers 
            SET lat = ?, lon = ?, last_update = ?, disponible = 1 
            WHERE chat_id = ?
            """,
            (lat, lon, timestamp, str(chat_id)),
            commit=True
        )
    except Exception as e:
        logger.error(f"Error actualizando ubicación DB: {e}")
        send_safe(chat_id, f"{Icons.ERROR} Error al guardar ubicación. Intentá de nuevo o contactá soporte.")
        return

    clear_state(chat_id)

    final_text = f"""
🎉 <b>¡Listo! Registro completado 100%</b>

Tu perfil ya está activo. Vas a recibir ofertas de trabajo cercanas.

<b>Comandos importantes:</b>
/online      → Activar y recibir trabajos
/offline     → Pausar notificaciones
/ubicacion   → Cambiar ubicación
/precios     → Modificar tarifas
/perfil      → Ver tu perfil completo
/ayuda       → Soporte

¡A ganar guita! 💪
    """
    remove_kb = types.ReplyKeyboardRemove()
    bot.send_message(chat_id, final_text, parse_mode="HTML", reply_markup=remove_kb)
