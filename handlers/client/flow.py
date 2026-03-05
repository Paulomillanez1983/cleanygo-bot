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

# ==================== FUNCIONES AUXILIARES DE DATOS ====================

def get_session_data(chat_id: str) -> dict:
    """Obtiene TODOS los datos de la sesión de forma segura"""
    session = get_session(chat_id)
    if not session:
        return {}
    return session.get("data", {}) or {}

def save_session_data(chat_id: str, data: dict):
    """Guarda datos en sesión manteniendo el estado actual"""
    session = get_session(chat_id)
    current_state_str = session.get("state", "idle") if session else "idle"
    try:
        current_state = UserState(current_state_str)
    except ValueError:
        current_state = UserState.IDLE
    set_state(chat_id, current_state, data)

def get_flow_data(chat_id: str, key: str, default=None):
    """Obtiene un dato específico del flujo"""
    data = get_session_data(str(chat_id))
    return data.get(key, default)

def update_flow_data(chat_id: str, **kwargs):
    """Actualiza múltiples datos en el flujo"""
    chat_id = str(chat_id)
    data = get_session_data(chat_id)
    data.update(kwargs)
    save_session_data(chat_id, data)
    logger.info(f"[FLOW DATA] chat_id={chat_id}, updated: {list(kwargs.keys())}")

# ==================== FLUJO CLIENTE ====================

@bot.message_handler(func=lambda m: m.text and ("Necesito" in m.text or "servicio" in m.text.lower()))
def handle_client_start(message):
    start_client_flow(message.chat.id)

def start_client_flow(chat_id: str):
    """Inicia flujo de cliente"""
    chat_id = str(chat_id)
    set_state(chat_id, UserState.CLIENT_SELECTING_SERVICE)
    
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
    
    # ✅ CORREGIDO: Guardar datos inmediatamente usando update_flow_data
    update_flow_data(chat_id, 
        service_id=service_id,
        service_name=SERVICES[service_id]["name"]
    )
    
    # ✅ Cambiar estado DESPUÉS de guardar datos
    set_state(chat_id, UserState.CLIENT_SELECTING_TIME)
    
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
    
    # ✅ CORREGIDO: Usar update_flow_data
    update_flow_data(chat_id, selected_time=time_str, time_period="PM")
    
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
    
    # ✅ CORREGIDO: Usar update_flow_data
    update_flow_data(chat_id, selected_time=time_str, time_period=period)
    bot.answer_callback_query(call.id, f"✓ {time_str} {period}")
    proceed_to_location(chat_id, call.message.message_id)

def proceed_to_location(chat_id: str, message_id: int):
    """Pasa a solicitar ubicación"""
    chat_id = str(chat_id)
    
    # ✅ CORREGIDO: Verificar datos antes de cambiar estado usando get_flow_data
    service_id = get_flow_data(chat_id, "service_id")
    time_str = get_flow_data(chat_id, "selected_time")
    period = get_flow_data(chat_id, "time_period")
    
    logger.info(f"[PROCEED_LOCATION] chat_id={chat_id}, service={service_id}, time={time_str} {period}")
    
    if not service_id:
        logger.error(f"[PROCEED_LOCATION] ERROR: service_id es None para {chat_id}")
        send_safe(chat_id, f"{Icons.ERROR} Error: no se encontró el servicio seleccionado. Usá /start de nuevo.")
        return
    
    # ✅ Cambiar estado DESPUÉS de verificar datos
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

# ✅ CORREGIDO: Verifica que el estado sea CLIENT_SHARING_LOCATION específicamente
def _is_client_sharing_location(message):
    """
    Verifica si el usuario está en estado de compartir ubicación.
    CRÍTICO: Debe detectar específicamente CLIENT_SHARING_LOCATION.
    """
    try:
        chat_id = str(message.chat.id)
        session = get_session(chat_id)
        
        if not session:
            logger.debug(f"[LOCATION CHECK] No session para {chat_id}")
            return False
        
        current_state = session.get("state", "idle")
        target_state = UserState.CLIENT_SHARING_LOCATION.value
        
        is_match = current_state == target_state
        
        logger.info(f"[LOCATION CHECK] chat_id={chat_id}, current={current_state}, target={target_state}, match={is_match}")
        
        return is_match
            
    except Exception as e:
        logger.error(f"[LOCATION CHECK] Error: {e}")
        import traceback
        traceback.print_exc()
        return False

@bot.message_handler(content_types=['location'], func=_is_client_sharing_location)
def handle_client_location(message):
    """
    Handler para ubicación del cliente.
    Procesa la ubicación y muestra pantalla de confirmación.
    """
    chat_id = str(message.chat.id)
    
    try:
        lat = message.location.latitude
        lon = message.location.longitude
        
        logger.info(f"[CLIENT LOCATION] Recibida de chat_id={chat_id}: lat={lat}, lon={lon}")
        
        # ✅ CORREGIDO: Recuperar TODOS los datos usando get_flow_data
        service_id = get_flow_data(chat_id, "service_id")
        time_str = get_flow_data(chat_id, "selected_time") 
        period = get_flow_data(chat_id, "time_period")
        
        logger.info(f"[CLIENT LOCATION] Datos recuperados: service={service_id}, time={time_str}, period={period}")
        
        # ✅ Validar datos antes de continuar
        if not service_id:
            logger.error(f"[CLIENT LOCATION] ERROR: service_id es None")
            send_safe(chat_id, f"{Icons.ERROR} Error: no se encontró el servicio. Usá /start.")
            return
            
        if not time_str:
            logger.error(f"[CLIENT LOCATION] ERROR: time_str es None")
            send_safe(chat_id, f"{Icons.ERROR} Error: no se encontró la hora. Usá /start.")
            return
        
        # ✅ Guardar ubicación
        update_flow_data(chat_id, lat=lat, lon=lon, location_shared=True)
        
        # Eliminar teclado
        remove_keyboard(chat_id, "📍 Ubicación recibida")
        
        # ✅ CAMBIAR ESTADO ANTES de enviar confirmación
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
        logger.info(f"[CLIENT LOCATION] Confirmación enviada a {chat_id}")
        
    except Exception as e:
        logger.error(f"[CLIENT LOCATION] Error procesando ubicación: {e}")
        import traceback
        traceback.print_exc()
        send_safe(chat_id, f"{Icons.ERROR} Error al procesar ubicación. Intentá de nuevo o usá /cancel.")
