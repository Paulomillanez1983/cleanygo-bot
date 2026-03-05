# handlers/client/flow.py
"""
Flujo completo para clientes - Solicitud de servicios.
"""

from config import bot
from models.user_state import set_state, update_data, get_data, UserState, get_session
from models.services_data import SERVICES
from utils.icons import Icons
from utils.keyboards import (
    get_service_selector, get_time_selector, get_custom_time_selector,
    get_location_keyboard, get_confirmation_keyboard, get_role_keyboard
)
from handlers.common import send_safe, edit_safe, delete_safe, remove_keyboard
from telebot import types
import logging

logger = logging.getLogger(__name__)

# ==================== VARIABLE DE FLUJO ====================
flow = True

# ==================== FUNCIONES AUXILIARES CRÍTICAS ====================

def get_full_session(chat_id: str) -> dict:
    """Obtiene sesión completa: estado + datos"""
    chat_id = str(chat_id)
    session = get_session(chat_id)
    if not session:
        return {"state": UserState.IDLE.value, "data": {}}
    return session

def save_state_and_data(chat_id: str, state: UserState, data: dict = None):
    """
    Guarda estado Y datos juntos de forma atómica.
    CRÍTICO: Siempre preserva datos existentes.
    """
    chat_id = str(chat_id)
    
    # Obtener datos actuales si no se proporcionan nuevos
    if data is None:
        current = get_full_session(chat_id)
        data = current.get("data", {})
    
    # Usar update_data para mergear en lugar de reemplazar
    for key, value in data.items():
        update_data(chat_id, **{key: value})
    
    # Cambiar estado
    set_state(chat_id, state)
    
    logger.info(f"[SAVE] chat_id={chat_id}, state={state.value}, data_keys={list(data.keys())}")

def get_flow_data(chat_id: str, key: str, default=None):
    """Obtiene dato del flujo de forma segura"""
    chat_id = str(chat_id)
    try:
        return get_data(chat_id, key) or default
    except:
        # Fallback: leer directamente de sesión
        session = get_full_session(chat_id)
        return session.get("data", {}).get(key, default)

# ==================== FLUJO CLIENTE ====================

@bot.message_handler(func=lambda m: m.text and ("Necesito" in m.text or "servicio" in m.text.lower()))
def handle_client_start(message):
    start_client_flow(message.chat.id)

def start_client_flow(chat_id: str):
    """Inicia flujo de cliente"""
    chat_id = str(chat_id)
    
    # Limpiar datos anteriores y empezar fresco
    save_state_and_data(chat_id, UserState.CLIENT_SELECTING_SERVICE, {})
    
    text = f"""
{Icons.SEARCH} <b>¿Qué servicio necesitás?</b>

Seleccioná una opción:
    """
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    for svc_id, svc in SERVICES.items():
        markup.add(types.InlineKeyboardButton(
            f"{svc['icon']} {svc['name']}\n<i>{svc['desc']}</i>", 
            callback_data=f"client_svc:{svc_id}"
        ))
    
    send_safe(chat_id, text, markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("client_svc:"))
def handle_client_service_selection(call):
    chat_id = str(call.message.chat.id)
    service_id = call.data.split(":")[1]
    
    # ✅ Guardar datos Y estado juntos
    save_state_and_data(chat_id, UserState.CLIENT_SELECTING_TIME, {
        "service_id": service_id,
        "service_name": SERVICES[service_id]["name"]
    })
    
    # Verificar que se guardó
    verify = get_flow_data(chat_id, "service_id")
    logger.info(f"[SERVICE] Guardado: {verify}")
    
    bot.answer_callback_query(call.id, f"Seleccionaste: {SERVICES[service_id]['name']}")
    
    text = f"""
{Icons.CLOCK} <b>¿Para qué hora lo necesitás?</b>

Servicio: {get_service_display(service_id)}

<b>Opciones rápidas:</b>
    """
    
    edit_safe(chat_id, call.message.message_id, text, get_time_selector())

def get_service_display(service_id: str, with_price: float = None) -> str:
    """Función compartida para mostrar información de servicios."""
    svc = SERVICES.get(service_id, {})
    text = f"{svc.get('icon', '🔹')} <b>{svc.get('name', service_id)}</b>"
    if with_price:
        from handlers.common import format_price
        text += f"\n   <code>{format_price(with_price)}/hora</code>"
    return text

# Time handlers
@bot.callback_query_handler(func=lambda c: c.data.startswith("time_quick:"))
def handle_quick_time(call):
    chat_id = str(call.message.chat.id)
    parts = call.data.split(":")
    time_str = f"{parts[1]}:{parts[2]}"
    
    # ✅ Mergear datos existentes + nuevos
    current_data = get_full_session(chat_id).get("data", {})
    current_data.update({"selected_time": time_str, "time_period": "PM"})
    
    save_state_and_data(chat_id, UserState.CLIENT_SELECTING_TIME, current_data)
    
    bot.answer_callback_query(call.id, f"Hora: {time_str} PM")
    proceed_to_location(chat_id, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "time_custom")
def handle_custom_time_start(call):
    chat_id = call.message.chat.id
    text = f"{Icons.CLOCK} <b>Seleccioná la hora:</b>\n\nElegí la hora de inicio:"
    edit_safe(chat_id, call.message.message_id, text, get_custom_time_selector("hour"))

@bot.callback_query_handler(func=lambda c: c.data.startswith("time_h:"))
def handle_hour_selection(call):
    chat_id = call.message.chat.id
    hour = call.data.split(":")[1]
    text = f"{Icons.CLOCK} <b>Seleccioná los minutos:</b>\n\nHora: {hour}:__"
    edit_safe(chat_id, call.message.message_id, text, get_custom_time_selector("minute", hour))

@bot.callback_query_handler(func=lambda c: c.data.startswith("time_m:"))
def handle_minute_selection(call):
    chat_id = call.message.chat.id
    parts = call.data.split(":")
    hour, minute = parts[1], parts[2]
    time_str = f"{hour}:{minute}"
    text = f"{Icons.CLOCK} <b>¿AM o PM?</b>\n\nHora seleccionada: {time_str}"
    edit_safe(chat_id, call.message.message_id, text, get_custom_time_selector("ampm", time_str))

@bot.callback_query_handler(func=lambda c: c.data.startswith("time_final:"))
def handle_final_time(call):
    chat_id = str(call.message.chat.id)
    parts = call.data.split(":")
    time_str = f"{parts[1]}:{parts[2]}"
    period = parts[3]
    
    # ✅ Mergear datos existentes + nuevos
    current_data = get_full_session(chat_id).get("data", {})
    current_data.update({"selected_time": time_str, "time_period": period})
    
    save_state_and_data(chat_id, UserState.CLIENT_SELECTING_TIME, current_data)
    
    bot.answer_callback_query(call.id, f"✓ {time_str} {period}")
    proceed_to_location(chat_id, call.message.message_id)

def proceed_to_location(chat_id: str, message_id: int):
    """Pasa a solicitar ubicación"""
    chat_id = str(chat_id)
    
    # ✅ Recuperar datos de forma segura
    session = get_full_session(chat_id)
    data = session.get("data", {})
    
    service_id = data.get("service_id")
    time_str = data.get("selected_time")
    period = data.get("time_period")
    
    logger.info(f"[PROCEED_LOCATION] chat_id={chat_id}, session_state={session.get('state')}")
    logger.info(f"[PROCEED_LOCATION] datos: service={service_id}, time={time_str}, period={period}")
    logger.info(f"[PROCEED_LOCATION] data_keys: {list(data.keys())}")
    
    if not service_id:
        logger.error(f"[PROCEED_LOCATION] ERROR: service_id no encontrado. Data: {data}")
        send_safe(chat_id, f"{Icons.ERROR} Error: sesión expirada. Usá /start de nuevo.")
        return
    
    # ✅ Cambiar estado preservando datos
    save_state_and_data(chat_id, UserState.CLIENT_SHARING_LOCATION, data)
    
    text = f"""
{Icons.LOCATION} <b>Último paso: Ubicación</b>

📋 <b>Resumen de tu solicitud:</b>
• Servicio: {get_service_display(service_id)}
• Hora: {time_str} {period}

{Icons.INFO} Enviá tu ubicación para encontrar profesionales cercanos:
    """
    
    delete_safe(chat_id, message_id)
    send_safe(chat_id, text, get_location_keyboard())

# ✅ CORREGIDO: Filtro de ubicación
def _is_client_sharing_location(message):
    """Verifica si el usuario está esperando compartir ubicación"""
    try:
        chat_id = str(message.chat.id)
        session = get_full_session(chat_id)
        
        current_state = session.get("state", "idle")
        target = UserState.CLIENT_SHARING_LOCATION.value
        
        is_match = current_state == target
        
        logger.info(f"[CHECK] chat_id={chat_id}, state={current_state}, target={target}, match={is_match}")
        
        return is_match
            
    except Exception as e:
        logger.error(f"[CHECK] Error: {e}")
        return False

@bot.message_handler(content_types=['location'], func=_is_client_sharing_location)
def handle_client_location(message):
    """Procesa ubicación del cliente"""
    chat_id = str(message.chat.id)
    
    try:
        lat = message.location.latitude
        lon = message.location.longitude
        
        logger.info(f"[LOCATION] chat_id={chat_id}, lat={lat}, lon={lon}")
        
        # ✅ Recuperar datos completos
        session = get_full_session(chat_id)
        data = session.get("data", {})
        
        service_id = data.get("service_id")
        time_str = data.get("selected_time")
        period = data.get("time_period")
        
        logger.info(f"[LOCATION] datos: {data}")
        
        if not service_id or not time_str:
            logger.error(f"[LOCATION] Datos incompletos: service={service_id}, time={time_str}")
            send_safe(chat_id, f"{Icons.ERROR} Error: datos incompletos. Usá /start.")
            return
        
        # Agregar ubicación a datos
        data.update({"lat": lat, "lon": lon, "location_shared": True})
        
        # Eliminar teclado
        remove_keyboard(chat_id, "📍 Ubicación recibida")
        
        # Cambiar estado y guardar todo
        save_state_and_data(chat_id, UserState.CLIENT_CONFIRMING, data)
        
        # Mostrar confirmación
        confirmation_text = f"""
{Icons.CALENDAR} <b>Confirma tu solicitud</b>

{get_service_display(service_id)}
{Icons.TIME} <b>Hora:</b> {time_str} {period}
{Icons.LOCATION} <b>Ubicación:</b> {lat:.5f}, {lon:.5f}

¿Todo correcto?
        """
        
        send_safe(chat_id, confirmation_text, get_confirmation_keyboard())
        logger.info(f"[LOCATION] Confirmación enviada a {chat_id}")
        
    except Exception as e:
        logger.error(f"[LOCATION] Error: {e}")
        import traceback
        traceback.print_exc()
        send_safe(chat_id, f"{Icons.ERROR} Error. Usá /cancel.")
