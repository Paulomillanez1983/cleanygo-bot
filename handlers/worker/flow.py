"""
Worker registration flow - Versión corregida y unificada
Usa ÚNICAMENTE UserSession desde config (elimina duplicación)
"""
import os
import time
import re
import json
import logging
import traceback
from telebot import types, apihelper

# Importar TODO desde database (que re-exporta desde config)
from database import (
    get_bot, 
    db_execute,
    Icons, 
    logger,
    UserSession,  # <-- USAR ESTO EXCLUSIVAMENTE
)

bot = get_bot()

from models.services_data import SERVICES

# Configuración
apihelper.SESSION_TIME_TO_LIVE = 10 * 60

# ==================== CONSTANTES ====================

class WorkerStates:
    SELECTING_SERVICES = "WORKER_SELECTING_SERVICES"
    ENTERING_NAME = "WORKER_ENTERING_NAME"
    ENTERING_PHONE = "WORKER_ENTERING_PHONE"
    ENTERING_DNI = "WORKER_ENTERING_DNI"
    SHARING_LOCATION = "WORKER_SHARING_LOCATION"

ACTIVE_WORKER_STATES = [
    WorkerStates.SELECTING_SERVICES,
    WorkerStates.ENTERING_NAME,
    WorkerStates.ENTERING_PHONE,
    WorkerStates.ENTERING_DNI,
    WorkerStates.SHARING_LOCATION,
]

# ==================== FUNCIÓN PÚBLICA PARA IMPORTACIÓN EXTERNA ====================

def start_worker_flow(chat_id):
    """
    FUNCIÓN PÚBLICA que puede ser importada desde otros handlers (ej: common.py).
    Inicia el flujo de registro de worker programáticamente.
    """
    try:
        logger.info(f"[START FLOW] chat_id={chat_id}")
        
        # Verificar si ya tiene perfil
        existing = db_execute(
            "SELECT 1 FROM workers WHERE chat_id = ?",
            (str(chat_id),),
            fetch_one=True
        )
        
        if existing:
            bot.send_message(chat_id, f"{Icons.INFO} Ya tenés un perfil registrado.")
            return
        
        # Limpiar y empezar
        UserSession.clear(chat_id)
        UserSession.set(chat_id, WorkerStates.SELECTING_SERVICES, {
            "selected_services": [],
            "flow_started_at": int(time.time())
        })
        
        _send_service_selector(chat_id, [])
        
    except Exception as e:
        logger.error(f"[START FLOW ERROR] {chat_id}: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(chat_id, f"{Icons.ERROR} Error iniciando. Usá /start")


# ==================== HANDLER PARA BOTÓN "TRABAJAR" ====================

from models.states import UserState

@bot.message_handler(
    func=lambda m: (
        m.text
        and "trabajar" in m.text.lower()
        and UserSession.get(m.chat.id).get("state") == UserState.SELECTING_ROLE.value
    )
)
def handle_worker_start(message):
    """
    Handler para cuando el usuario toca el botón "💼 Quiero trabajar".
    SOLO funciona cuando el usuario está en el menú principal.
    """
    chat_id = message.chat.id

    logger.info(f"[HANDLER] Botón trabajar | chat_id={chat_id}")

    start_worker_flow(chat_id)

# ==================== SELECTOR DE SERVICIOS ====================

def _send_service_selector(chat_id, selected_services):
    """Envía selector de servicios"""
    text = (
        f"{Icons.BRIEFCASE} <b>Registro Profesional</b>\n\n"
        f"Paso 1/5\n"
        f"Seleccioná los servicios que ofrecés:"
    )
    
    markup = _build_service_markup(selected_services)
    
    bot.send_message(
        chat_id,
        text,
        parse_mode="HTML",
        reply_markup=markup
    )


def _build_service_markup(selected_services):
    """Construye inline keyboard"""
    if not isinstance(selected_services, list):
        selected_services = []
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []

    for svc_id, svc in SERVICES.items():
        name = svc["name"]
        is_selected = svc_id in selected_services
        text = f"{'✅ ' if is_selected else ''}{name}"
        buttons.append(
            types.InlineKeyboardButton(
                text=text,
                callback_data=f"svc_toggle:{svc_id}"
            )
        )

    buttons.append(
        types.InlineKeyboardButton(
            "Confirmar ✅",
            callback_data="svc_confirm"
        )
    )

    markup.add(*buttons)
    return markup

# ==================== CALLBACKS ====================

@bot.callback_query_handler(func=lambda c: c.data.startswith("svc_toggle:"))
def handle_service_toggle(call):
    """Toggle de servicios"""
    # CORREGIDO: call.message.chat.id (no chat_id)
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    
    try:
        parts = call.data.split(":")
        if len(parts) != 2:
            bot.answer_callback_query(call.id, "Error")
            return
            
        service_id = parts[1]
        
        # Usar UserSession
        selected = UserSession.get_data(chat_id, "selected_services", [])
        if not isinstance(selected, list):
            selected = []
        
        # Toggle
        if service_id in selected:
            selected.remove(service_id)
            action_text = "deseleccionado"
        else:
            selected.append(service_id)
            action_text = "seleccionado"
        
        # Guardar
        UserSession.update(chat_id, selected_services=selected)
        
        # Actualizar UI
        new_markup = _build_service_markup(selected)
        
        # Comparar antes de editar (optimización)
        try:
            current = call.message.reply_markup
            if current and _markup_equal(current, new_markup):
                bot.answer_callback_query(call.id, f"Servicio {action_text}")
                return
        except Exception as e:
            logger.debug(f"[TOGGLE] Error comparando: {e}")
        
        try:
            bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=new_markup
            )
            bot.answer_callback_query(call.id, f"{'✅' if action_text == 'seleccionado' else '❌'} {action_text}")
            
        except apihelper.ApiTelegramException as e:
            error_str = str(e).lower()
            if "message is not modified" in error_str:
                bot.answer_callback_query(call.id, "Actualizado")
            elif "message to edit not found" in error_str:
                logger.warning(f"[TOGGLE] Mensaje no encontrado")
            else:
                raise
                
    except Exception as e:
        logger.error(f"[TOGGLE ERROR] {chat_id}: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Error")
        except:
            pass


def _markup_equal(markup1, markup2):
    """Compara markups"""
    try:
        return json.dumps(markup1.to_dict(), sort_keys=True) == \
               json.dumps(markup2.to_dict(), sort_keys=True)
    except:
        return False


@bot.callback_query_handler(func=lambda c: c.data == "svc_confirm")
def handle_service_confirm(call):
    """Confirmación de servicios"""
    # CORREGIDO: call.message.chat.id (no chat_id)
    chat_id = call.message.chat.id
    
    try:
        selected = UserSession.get_data(chat_id, "selected_services", [])
        
        if not selected or len(selected) == 0:
            bot.answer_callback_query(
                call.id,
                "⚠️ Seleccioná al menos un servicio",
                show_alert=True
            )
            return
        
        # Borrar mensaje
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception as e:
            logger.debug(f"[CONFIRM] No se pudo borrar: {e}")
        
        # Avanzar estado
        UserSession.set(chat_id, WorkerStates.ENTERING_NAME, {
            "selected_services": selected
        })
        
        bot.send_message(
            chat_id,
            "📝 <b>Paso 2/5</b>\n¿Cuál es tu nombre completo?",
            parse_mode="HTML"
        )
        bot.answer_callback_query(call.id)
        
    except Exception as e:
        logger.error(f"[CONFIRM ERROR] {chat_id}: {e}")
        bot.answer_callback_query(call.id, "Error", show_alert=True)

# ==================== DISPATCHER CENTRALIZADO ====================

@bot.message_handler(func=lambda m: UserSession.get(m.chat.id).get("state") in ACTIVE_WORKER_STATES)
def worker_flow_dispatcher(message):
    """
    HANDLER ÚNICO Y CENTRALIZADO.
    
    CRÍTICO: Usa UserSession.get() UNA SOLA VEZ por mensaje.
    Elimina race conditions de múltiples lambdas en paralelo.
    """
    chat_id = message.chat.id
    
    # UNA SOLA consulta a DB para todo el flujo
    session = UserSession.get(chat_id)
    current_state = session.get("state")
    
    logger.info(f"[DISPATCHER] chat_id={chat_id} | state={current_state}")
    
    try:
        if current_state == WorkerStates.ENTERING_NAME:
            _process_name_input(message, chat_id)
        elif current_state == WorkerStates.ENTERING_PHONE:
            _process_phone_input(message, chat_id)
        elif current_state == WorkerStates.ENTERING_DNI:
            _process_dni_input(message, chat_id)
        elif current_state == WorkerStates.SHARING_LOCATION:
            _process_location_text(message, chat_id)
        elif current_state == WorkerStates.SELECTING_SERVICES:
            bot.send_message(chat_id, "⚠️ Usá los botones de arriba")
            
    except Exception as e:
        logger.error(f"[DISPATCHER ERROR] {chat_id}: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(chat_id, f"{Icons.ERROR} Error. Escribí /start")


def _process_name_input(message, chat_id):
    """Paso 2: Nombre"""
    text = message.text.strip() if message.text else ""
    
    if len(text) < 2:
        bot.send_message(chat_id, "❌ Nombre muy corto (mínimo 2):")
        return
    
    if len(text) > 100:
        bot.send_message(chat_id, "❌ Nombre muy largo:")
        return
    
    # Usar UserSession
    UserSession.update(chat_id, worker_name=text)
    UserSession.set(chat_id, WorkerStates.ENTERING_PHONE)
    
    bot.send_message(
        chat_id,
        f"👤 <b>Nombre:</b> {text}\n\n"
        f"📱 <b>Paso 3/5</b>\n¿Cuál es tu teléfono?",
        parse_mode="HTML"
    )


def _process_phone_input(message, chat_id):
    """Paso 3: Teléfono"""
    if not message.text:
        bot.send_message(chat_id, "❌ Necesito un número:")
        return
    
    phone = re.sub(r"\D", "", message.text)
    
    if len(phone) < 8:
        bot.send_message(chat_id, "❌ Muy corto. Incluí código de área:")
        return
    
    UserSession.update(chat_id, worker_phone=phone)
    UserSession.set(chat_id, WorkerStates.ENTERING_DNI)
    
    formatted = f"{phone[:2]} {phone[2:6]}-{phone[6:]}" if len(phone) >= 8 else phone
    
    bot.send_message(
        chat_id,
        f"📱 <b>Teléfono:</b> {formatted}\n\n"
        f"🆔 <b>Paso 4/5</b>\n¿Cuál es tu DNI?",
        parse_mode="HTML"
    )


def _process_dni_input(message, chat_id):
    """Paso 4: DNI"""
    if not message.text:
        bot.send_message(chat_id, "❌ Necesito el DNI:")
        return
    
    dni = re.sub(r"\D", "", message.text)
    
    if len(dni) < 7 or len(dni) > 10:
        bot.send_message(chat_id, "❌ DNI inválido (7-10 dígitos):")
        return
    
    try:
        _save_worker_to_db(chat_id, dni)
        UserSession.set(chat_id, WorkerStates.SHARING_LOCATION)
        _request_location(chat_id)
    except Exception as e:
        logger.error(f"[DNI ERROR] {chat_id}: {e}")
        bot.send_message(chat_id, f"{Icons.ERROR} Error. Intentá /start")


def _save_worker_to_db(chat_id, dni):
    """Guarda worker en BD"""
    # Obtener datos de sesión
    session = UserSession.get(chat_id)
    data = session.get("data", {})
    
    name = data.get("worker_name")
    phone = data.get("worker_phone")
    services = data.get("selected_services", [])
    
    if not name or not phone:
        raise ValueError("Faltan datos")
    
    now = int(time.time())
    
    db_execute(
        """
        INSERT OR REPLACE INTO workers 
        (chat_id, name, phone, dni, is_active, created_at) 
        VALUES (?, ?, ?, ?, 0, ?)
        """,
        (str(chat_id), name, phone, dni, now)
    )
    
    db_execute(
        "DELETE FROM worker_services WHERE chat_id = ?",
        (str(chat_id),)
    )
    
    for svc_id in services:
        if svc_id:
            db_execute(
                "INSERT INTO worker_services (chat_id, service_id) VALUES (?, ?)",
                (str(chat_id), svc_id)
            )
    
    logger.info(f"[WORKER SAVED] {chat_id}")


def _request_location(chat_id):
    """Paso 5: Ubicación"""
    markup = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        one_time_keyboard=True,
        row_width=1
    )
    markup.add(
        types.KeyboardButton(
            "📍 Enviar mi ubicación actual",
            request_location=True
        )
    )
    markup.add(types.KeyboardButton("❌ Cancelar registro"))

    bot.send_message(
        chat_id,
        "📍 <b>Paso 5/5 - Ubicación</b>\n\n"
        "Compartí tu ubicación para que te encuentren.\n\n"
        "<i>Tocá el botón 👇</i>",
        parse_mode="HTML",
        reply_markup=markup
    )


def _process_location_text(message, chat_id):
    """Texto cuando se espera ubicación"""
    if message.text and "cancelar" in message.text.lower():
        UserSession.clear(chat_id)
        db_execute(
            "DELETE FROM workers WHERE chat_id = ? AND is_active = 0",
            (str(chat_id),)
        )
        
        bot.send_message(
            chat_id,
            "❌ <b>Registro cancelado</b>\n\nReiniciá con /start",
            parse_mode="HTML",
            reply_markup=types.ReplyKeyboardRemove()
        )
        return
    
    bot.send_message(
        chat_id,
        "⚠️ <b>Se requiere ubicación</b>\n\n"
        "Usá <b>📍 Enviar ubicación</b> o <b>❌ Cancelar</b>",
        parse_mode="HTML"
    )

# ==================== UBICACIÓN ====================

@bot.message_handler(content_types=["location"])
def handle_location_shared(message):
    """Procesa ubicación compartida"""
    chat_id = message.chat.id
    
    # Verificar estado
    session = UserSession.get(chat_id)
    if session.get("state") != WorkerStates.SHARING_LOCATION:
        return  # No estamos en registro, ignorar
    
    try:
        lat = message.location.latitude
        lon = message.location.longitude
        
        # Activar worker
        db_execute(
            "UPDATE workers SET lat = ?, lon = ?, is_active = 1 WHERE chat_id = ?",
            (lat, lon, str(chat_id))
        )
        
        UserSession.clear(chat_id)
        
        bot.send_message(
            chat_id,
            "🎉 <b>¡Registro completado!</b>\n\n"
            "Tu perfil está activo y visible.\n"
            f"📍 {lat:.4f}, {lon:.4f}",
            parse_mode="HTML",
            reply_markup=types.ReplyKeyboardRemove()
        )
        
        logger.info(f"[COMPLETE] {chat_id}")
        
    except Exception as e:
        logger.error(f"[LOCATION ERROR] {chat_id}: {e}")
        bot.send_message(
            chat_id,
            f"{Icons.ERROR} Error guardando ubicación.",
            reply_markup=types.ReplyKeyboardRemove()
        )
