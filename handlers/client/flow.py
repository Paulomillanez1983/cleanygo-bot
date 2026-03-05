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

def debug_session(chat_id: str, label: str):
    """Debug: muestra el estado actual de la sesión"""
    try:
        session = get_session(chat_id)
        logger.info(f"[DEBUG {label}] chat_id={chat_id}, session={session}")
        return session
    except Exception as e:
        logger.error(f"[DEBUG {label}] ERROR: {e}")
        return {"state": "error", "data": {}}

def save_state_and_data(chat_id: str, state: UserState, data_updates: dict = None):
    """
    Guarda estado y actualiza datos de forma atómica.
    CRÍTICO: Usa update_data para mergear, no reemplazar.
    """
    chat_id = str(chat_id)
    
    # 1. Primero actualizar datos si hay nuevos
    if data_updates:
        for key, value in data_updates.items():
            update_data(chat_id, **{key: value})
        logger.info(f"[SAVE] chat_id={chat_id}, updated keys: {list(data_updates.keys())}")
    
    # 2. Luego cambiar estado (update_data ya guardó todo)
    set_state(chat_id, state)
    logger.info(f"[SAVE] chat_id={chat_id}, state={state.value}")

def get_flow_data(chat_id: str, key: str, default=None):
    """Obtiene dato del flujo usando get_data del modelo"""
    chat_id = str(chat_id)
    try:
        result = get_data(chat_id, key)
        logger.info(f"[GET] chat_id={chat_id}, key={key}, result={result}")
        return result if result is not None else default
    except Exception as e:
        logger.error(f"[GET] ERROR chat_id={chat_id}, key={key}: {e}")
        return default

# ==================== FLUJO CLIENTE ====================

@bot.message_handler(func=lambda m: m.text and ("Necesito" in m.text or "servicio" in m.text.lower()))
def handle_client_start(message):
    start_client_flow(message.chat.id)

def start_client_flow(chat_id: str):
    """Inicia flujo de cliente"""
    chat_id = str(chat_id)
    
    # Limpiar y empezar
    from models.user_state import clear_state
    clear_state(chat_id)
    
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
    debug_session(chat_id, "POST_START")

@bot.callback_query_handler(func=lambda c: c.data.startswith("client_svc:"))
def handle_client_service_selection(call):
    chat_id = str(call.message.chat.id)
    service_id = call.data.split(":")[1]
    
    logger.info(f"[SERVICE] chat_id={chat_id}, service_id={service_id}")
    
    # ✅ Guardar usando update_data directamente
    update_data(chat_id, service_id=service_id, service_name=SERVICES[service_id]["name"])
    
    # Verificar inmediatamente
    verify = get_data(chat_id, "service_id")
    logger.info(f"[SERVICE] Verificación inmediata: {verify}")
    
    # Cambiar estado
    set_state(chat_id, UserState.CLIENT_SELECTING_TIME)
    
    debug_session(chat_id, "POST_SERVICE")
    
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
    
    logger.info(f"[TIME] chat_id={chat_id}, time_str={time_str}")
    
    # ✅ Guardar usando update_data
    update_data(chat_id, selected_time=time_str, time_period="PM")
    
    debug_session(chat_id, "POST_TIME")
    
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
    
    logger.info(f"[TIME_FINAL] chat_id={chat_id}, time={time_str}, period={period}")
    
    # ✅ Guardar usando update_data
    update_data(chat_id, selected_time=time_str, time_period=period)
    
    debug_session(chat_id, "POST_TIME_FINAL")
    
    bot.answer_callback_query(call.id, f"✓ {time_str} {period}")
    proceed_to_location(chat_id, call.message.message_id)

def proceed_to_location(chat_id: str, message_id: int):
    """Pasa a solicitar ubicación"""
    chat_id = str(chat_id)
    
    # ✅ Recuperar datos usando get_data individualmente
    service_id = get_data(chat_id, "service_id")
    time_str = get_data(chat_id, "selected_time")
    period = get_data(chat_id, "time_period")
    
    logger.info(f"[PROCEED] chat_id={chat_id}, service={service_id}, time={time_str}, period={period}")
    
    # Debug completo
    session = debug_session(chat_id, "PROCEED_LOC")
    
    if not service_id:
        logger.error(f"[PROCEED] ERROR: service_id=None. Session: {session}")
        send_safe(chat_id, f"{Icons.ERROR} Error: sesión expirada. Usá /start de nuevo.")
        return
    
    # Cambiar estado
    set_state(chat_id, UserState.CLIENT_SHARING_LOCATION)
    
    text = f"""
{Icons.LOCATION} <b>Último paso: Ubicación</b>

📋 <b>Resumen de tu solicitud:</b>
• Servicio: {get_service_display(service_id)}
• Hora: {time_str} {period}

{Icons.INFO} Enviá tu ubicación para encontrar profesionales cercanos:
    """
    
    delete_safe(chat_id, message_id)
    send_safe(chat_id, text, get_location_keyboard())

def _is_client_sharing_location(message):
    """Verifica si el usuario está esperando compartir ubicación"""
    try:
        chat_id = str(message.chat.id)
        session = get_session(chat_id)
        
        current_state = session.get("state", "idle")
        target = UserState.CLIENT_SHARING_LOCATION.value
        
        is_match = current_state == target
        
        logger.info(f"[CHECK] chat_id={chat_id}, state={current_state}, match={is_match}")
        
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
        
        # ✅ Recuperar datos usando get_data
        service_id = get_data(chat_id, "service_id")
        time_str = get_data(chat_id, "selected_time")
        period = get_data(chat_id, "time_period")
        
        logger.info(f"[LOCATION] datos: service={service_id}, time={time_str}, period={period}")
        
        if not service_id or not time_str:
            logger.error(f"[LOCATION] Datos incompletos")
            send_safe(chat_id, f"{Icons.ERROR} Error: datos incompletos. Usá /start.")
            return
        
        # Guardar ubicación
        update_data(chat_id, lat=lat, lon=lon, location_shared=True)
        
        # Eliminar teclado
        remove_keyboard(chat_id, "📍 Ubicación recibida")
        
        # Cambiar estado
        set_state(chat_id, UserState.CLIENT_CONFIRMING)
        
        # Mostrar confirmación
        confirmation_text = f"""
{Icons.CALENDAR} <b>Confirma tu solicitud</b>

{get_service_display(service_id)}
{Icons.TIME} <b>Hora:</b> {time_str} {period}
{Icons.LOCATION} <b>Ubicación:</b> {lat:.5f}, {lon:.5f}

¿Todo correcto?
        """
        
        send_safe(chat_id, confirmation_text, get_confirmation_keyboard())
        logger.info(f"[LOCATION] Confirmación enviada")
        
    except Exception as e:
        logger.error(f"[LOCATION] Error: {e}")
        import traceback
        traceback.print_exc()
        send_safe(chat_id, f"{Icons.ERROR} Error. Usá /cancel.")
