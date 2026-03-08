"""
Worker flow - Registro de trabajadores
"""
import os
import time
import re
import json
import traceback
from telebot import types, apihelper

# CAMBIO: usar get_bot
from config import logger, get_bot
from models.user_state import set_state, update_data, get_data, clear_state, UserState
from models.services_data import SERVICES
from utils.icons import Icons
from handlers.common import send_safe
from services.worker_service import db_execute

# NUEVO: obtener bot
bot = get_bot()

# ==================== CONFIGURACIÓN ====================
apihelper.SESSION_TIME_TO_LIVE = 10 * 60

# ==================== CONSTANTES DE ESTADOS ACTIVOS ====================
# Usamos los valores del Enum directamente
ACTIVE_WORKER_STATES = [
    UserState.WORKER_SELECTING_SERVICES.value,
    UserState.WORKER_ENTERING_NAME.value,
    UserState.WORKER_ENTERING_PHONE.value,
    UserState.WORKER_ENTERING_DNI.value,
    UserState.WORKER_SHARING_LOCATION.value,
]

# ===================== FUNCIÓN PÚBLICA =====================
def start_worker_flow(chat_id):
    """Inicia el flujo de registro de worker programáticamente."""
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
        clear_state(chat_id)
        set_state(chat_id, UserState.WORKER_SELECTING_SERVICES.value, {
            "selected_services": [],
            "flow_started_at": int(time.time())
        })

        _send_service_selector(chat_id, [])

    except Exception as e:
        logger.error(f"[START FLOW ERROR] {chat_id}: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(chat_id, f"{Icons.ERROR} Error iniciando. Usá /start")

# ===================== HANDLER BOTÓN "TRABAJAR" =====================
@bot.message_handler(
    func=lambda m: (
        m.text
        and "trabajar" in m.text.lower()
        and get_data(m.chat.id, "state") == UserState.SELECTING_ROLE.value
    )
)
def handle_worker_start(message):
    """Cuando el usuario toca '💼 Quiero trabajar' en menú principal."""
    chat_id = message.chat.id
    logger.info(f"[HANDLER] Botón trabajar | chat_id={chat_id}")
    start_worker_flow(chat_id)

# ===================== SELECTOR DE SERVICIOS =====================
def _send_service_selector(chat_id, selected_services):
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

# ===================== CALLBACKS =====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("svc_toggle:"))
def handle_service_toggle(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id

    try:
        parts = call.data.split(":")
        if len(parts) != 2:
            bot.answer_callback_query(call.id, "Error")
            return

        service_id = parts[1]
        selected = get_data(chat_id, "selected_services") or []
        if not isinstance(selected, list):
            selected = []

        # Toggle
        if service_id in selected:
            selected.remove(service_id)
            action_text = "deseleccionado"
        else:
            selected.append(service_id)
            action_text = "seleccionado"

        update_data(chat_id, selected_services=selected)

        # Actualizar UI
        new_markup = _build_service_markup(selected)
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
            bot.answer_callback_query(call.id, f"{'✅' if action_text=='seleccionado' else '❌'} {action_text}")

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
    try:
        return json.dumps(markup1.to_dict(), sort_keys=True) == \
               json.dumps(markup2.to_dict(), sort_keys=True)
    except:
        return False

@bot.callback_query_handler(func=lambda c: c.data == "svc_confirm")
def handle_service_confirm(call):
    chat_id = call.message.chat.id
    try:
        selected = get_data(chat_id, "selected_services") or []
        if not selected:
            bot.answer_callback_query(call.id, "⚠️ Seleccioná al menos un servicio", show_alert=True)
            return

        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception as e:
            logger.debug(f"[CONFIRM] No se pudo borrar: {e}")

        # Avanzar estado sin perder data
        update_data(chat_id, state=UserState.WORKER_ENTERING_NAME.value)

        bot.send_message(
            chat_id,
            "📝 <b>Paso 2/5</b>\n¿Cuál es tu nombre completo?",
            parse_mode="HTML"
        )
        bot.answer_callback_query(call.id)

    except Exception as e:
        logger.error(f"[CONFIRM ERROR] {chat_id}: {e}")
        bot.answer_callback_query(call.id, "Error", show_alert=True)

# ===================== DISPATCHER CENTRALIZADO =====================
@bot.message_handler(func=lambda m: get_data(m.chat.id, "state") in ACTIVE_WORKER_STATES)
def worker_flow_dispatcher(message):
    chat_id = message.chat.id
    current_state = get_data(chat_id, "state")

    logger.info(f"[DISPATCHER] chat_id={chat_id} | state={current_state}")

    try:
        if current_state == UserState.WORKER_ENTERING_NAME.value:
            _process_name_input(message, chat_id)
        elif current_state == UserState.WORKER_ENTERING_PHONE.value:
            _process_phone_input(message, chat_id)
        elif current_state == UserState.WORKER_ENTERING_DNI.value:
            _process_dni_input(message, chat_id)
        elif current_state == UserState.WORKER_SHARING_LOCATION.value:
            _process_location_text(message, chat_id)
        elif current_state == UserState.WORKER_SELECTING_SERVICES.value:
            bot.send_message(chat_id, "⚠️ Usá los botones de arriba")

    except Exception as e:
        logger.error(f"[DISPATCHER ERROR] {chat_id}: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(chat_id, f"{Icons.ERROR} Error. Escribí /start")

# ===================== PASO 2: NOMBRE =====================
def _process_name_input(message, chat_id):
    text = message.text.strip() if message.text else ""
    if len(text) < 2:
        bot.send_message(chat_id, "❌ Nombre muy corto (mínimo 2):")
        return
    if len(text) > 100:
        bot.send_message(chat_id, "❌ Nombre muy largo:")
        return

    update_data(chat_id, worker_name=text, state=UserState.WORKER_ENTERING_PHONE.value)
    bot.send_message(
        chat_id,
        f"👤 <b>Nombre:</b> {text}\n\n📱 <b>Paso 3/5</b>\n¿Cuál es tu teléfono?",
        parse_mode="HTML"
    )

# ===================== PASO 3: TELÉFONO =====================
def _process_phone_input(message, chat_id):
    if not message.text:
        bot.send_message(chat_id, "❌ Necesito un número:")
        return
    phone = re.sub(r"\D", "", message.text)
    if len(phone) < 8:
        bot.send_message(chat_id, "❌ Muy corto. Incluí código de área:")
        return

    update_data(chat_id, worker_phone=phone, state=UserState.WORKER_ENTERING_DNI.value)
    formatted = f"{phone[:2]} {phone[2:6]}-{phone[6:]}" if len(phone) >= 8 else phone
    bot.send_message(
        chat_id,
        f"📱 <b>Teléfono:</b> {formatted}\n\n🆔 <b>Paso 4/5</b>\n¿Cuál es tu DNI?",
        parse_mode="HTML"
    )

# ===================== PASO 4: DNI =====================
def _process_dni_input(message, chat_id):
    if not message.text:
        bot.send_message(chat_id, "❌ Necesito el DNI:")
        return
    dni = re.sub(r"\D", "", message.text)
    if len(dni) < 7 or len(dni) > 10:
        bot.send_message(chat_id, "❌ DNI inválido (7-10 dígitos):")
        return

    update_data(chat_id, worker_dni=dni)
    try:
        _save_worker_to_db(chat_id, dni)
        update_data(chat_id, state=UserState.WORKER_SHARING_LOCATION.value)
        _request_location(chat_id)
    except Exception as e:
        logger.error(f"[DNI ERROR] {chat_id}: {e}")
        bot.send_message(chat_id, f"{Icons.ERROR} Error. Intentá /start")

# ===================== GUARDAR WORKER EN DB =====================
def _save_worker_to_db(chat_id, dni):
    name = get_data(chat_id, "worker_name")
    phone = get_data(chat_id, "worker_phone")
    services = get_data(chat_id, "selected_services") or []

    if not name or not phone or not dni:
        raise ValueError("Faltan datos completos para guardar worker")

    now = int(time.time())
    db_execute(
        """
        INSERT OR REPLACE INTO workers
        (chat_id, name, phone, dni, is_active, created_at)
        VALUES (?, ?, ?, ?, 0, ?)
        """,
        (str(chat_id), name, phone, dni, now)
    )

    db_execute("DELETE FROM worker_services WHERE chat_id = ?", (str(chat_id),))
    for svc_id in services:
        if svc_id:
            db_execute("INSERT INTO worker_services (chat_id, service_id) VALUES (?, ?)", (str(chat_id), svc_id))

    logger.info(f"[WORKER SAVED] {chat_id}")

# ===================== PASO 5: UBICACIÓN =====================
def _request_location(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("📍 Enviar mi ubicación actual", request_location=True))
    markup.add(types.KeyboardButton("❌ Cancelar registro"))

    bot.send_message(
        chat_id,
        "📍 <b>Paso 5/5 - Ubicación</b>\n\nCompartí tu ubicación para que te encuentren.\n\n<i>Tocá el botón 👇</i>",
        parse_mode="HTML",
        reply_markup=markup
    )

def _process_location_text(message, chat_id):
    if message.text and "cancelar" in message.text.lower():
        clear_state(chat_id)
        db_execute("DELETE FROM workers WHERE chat_id = ? AND is_active = 0", (str(chat_id),))
        bot.send_message(
            chat_id,
            "❌ <b>Registro cancelado</b>\n\nReiniciá con /start",
            parse_mode="HTML",
            reply_markup=types.ReplyKeyboardRemove()
        )
        return

    bot.send_message(
        chat_id,
        "⚠️ <b>Se requiere ubicación</b>\n\nUsá <b>📍 Enviar ubicación</b> o <b>❌ Cancelar</b>",
        parse_mode="HTML"
    )

@bot.message_handler(content_types=["location"])
def handle_location_shared(message):
    chat_id = message.chat.id
    current_state = get_data(chat_id, "state")
    if current_state != UserState.WORKER_SHARING_LOCATION.value:
        return

    try:
        lat = message.location.latitude
        lon = message.location.longitude

        db_execute(
            "UPDATE workers SET lat = ?, lon = ?, is_active = 1 WHERE chat_id = ?",
            (lat, lon, str(chat_id))
        )

        clear_state(chat_id)
        bot.send_message(
            chat_id,
            f"🎉 <b>¡Registro completado!</b>\n\nTu perfil está activo y visible.\n📍 {lat:.4f}, {lon:.4f}",
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
