import os
import time
import re
import json
import logging
import traceback
from telebot import types, apihelper
from config import get_bot
bot = get_bot()

from models.services_data import SERVICES
from utils.icons import Icons
from database import db_execute

# ==================== CONFIGURACIÓN ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger(__name__)
apihelper.SESSION_TIME_TO_LIVE = 10 * 60


# ==================== SESIONES ====================

def get_session(chat_id):
    """Obtiene sesión con manejo robusto de corrupción JSON"""
    try:
        row = db_execute(
            "SELECT state, data FROM sessions WHERE chat_id = ?",
            (str(chat_id),),
            fetch_one=True
        )

        if row:
            state, data_json = row
            
            # FIX: Manejar NULL, vacío, o string vacío
            if data_json is None or data_json == "":
                logger.warning(f"[SESSION] Data vacía/NULL para {chat_id}, inicializando")
                return reset_and_fresh_session(chat_id, state or "IDLE")
            
            try:
                data = json.loads(data_json) if data_json else {}
                # Validar que sea dict
                if not isinstance(data, dict):
                    raise ValueError("Data no es diccionario")
                return {"state": state or "IDLE", "data": data}

            except Exception as e:
                logger.error(f"[SESSION] JSON corrupto para {chat_id}: {e} - reiniciando")
                return reset_and_fresh_session(chat_id, "IDLE")

        # No existe sesión, crear nueva
        return create_fresh_session(chat_id)

    except Exception as e:
        logger.error(f"[SESSION] Error DB en get_session para {chat_id}: {e}")
        return {"state": "IDLE", "data": {}}


def reset_and_fresh_session(chat_id, state="IDLE"):
    """Limpia sesión corrupta y crea una nueva"""
    try:
        # Eliminar completamente primero
        db_execute("DELETE FROM sessions WHERE chat_id=?", (str(chat_id),))
        
        # Crear nueva con data válida
        safe_data = json.dumps({})
        db_execute(
            "INSERT INTO sessions (chat_id, state, data, last_activity) VALUES (?, ?, ?, ?)",
            (str(chat_id), state, safe_data, int(time.time()))
        )
        logger.info(f"[RESET] Sesión reseteada para {chat_id}")
        return {"state": state, "data": {}}
    except Exception as e:
        logger.error(f"[RESET ERROR] {chat_id}: {e}")
        return {"state": "IDLE", "data": {}}


def create_fresh_session(chat_id):
    """Crea una sesión limpia nueva"""
    try:
        safe_data = json.dumps({})
        db_execute(
            "INSERT OR REPLACE INTO sessions (chat_id, state, data, last_activity) VALUES (?, ?, ?, ?)",
            (str(chat_id), "IDLE", safe_data, int(time.time()))
        )
        return {"state": "IDLE", "data": {}}
    except Exception as e:
        logger.error(f"[SESSION] Error creando sesión fresca para {chat_id}: {e}")
        return {"state": "IDLE", "data": {}}


def safe_json(data):
    """Sanitiza datos para JSON"""
    if isinstance(data, dict):
        return {k: safe_json(v) for k, v in data.items()}
    if isinstance(data, list):
        return [safe_json(x) for x in data]
    if isinstance(data, (str, int, float, bool, type(None))):
        return data
    return str(data)


def set_state(chat_id, state, data=None):
    """Establece estado con transacción atómica"""
    try:
        # FIX: Asegurar que data sea dict válido
        if data is None:
            data = {}
        elif not isinstance(data, dict):
            logger.warning(f"[SET STATE] Data no era dict para {chat_id}, convirtiendo")
            data = dict(data) if hasattr(data, '__iter__') else {}
        
        # Merge con sesión existente si es actualización parcial
        current = get_session(chat_id)
        if current and isinstance(current.get("data"), dict):
            new_data = current["data"].copy()
            new_data.update(data)
        else:
            new_data = data

        safe_data_str = json.dumps(safe_json(new_data))
        
        # Verificar que el JSON es válido antes de guardar
        try:
            json.loads(safe_data_str)  # Validación
        except json.JSONDecodeError:
            logger.error(f"[SET STATE] JSON inválido generado para {chat_id}, usando vacío")
            safe_data_str = "{}"

        db_execute(
            "INSERT OR REPLACE INTO sessions (chat_id, state, data, last_activity) VALUES (?, ?, ?, ?)",
            (str(chat_id), state, safe_data_str, int(time.time()))
        )
        logger.info(f"[STATE] {chat_id} -> {state}")
    except Exception as e:
        logger.error(f"[STATE ERROR] No se pudo setear estado para {chat_id}: {e}")
        logger.error(traceback.format_exc())


def update_data(chat_id, **kwargs):
    """Actualiza datos específicos de sesión"""
    try:
        session = get_session(chat_id)
        if not isinstance(session.get("data"), dict):
            logger.warning(f"[UPDATE DATA] Sesión sin data válida para {chat_id}, reseteando data")
            new_data = {}
        else:
            new_data = session["data"].copy()
        
        # Solo actualizar kwargs válidos
        for k, v in kwargs.items():
            if v is not None:  # Ignorar None explícito
                new_data[k] = v

        safe_data_str = json.dumps(safe_json(new_data))
        
        # Validar antes de guardar
        try:
            json.loads(safe_data_str)
        except json.JSONDecodeError:
            logger.error(f"[UPDATE DATA] JSON inválido para {chat_id}")
            return

        db_execute(
            "UPDATE sessions SET data=?, last_activity=? WHERE chat_id=?",
            (safe_data_str, int(time.time()), str(chat_id))
        )
    except Exception as e:
        logger.error(f"[UPDATE DATA ERROR] {chat_id}: {e}")
        logger.error(traceback.format_exc())


def get_data(chat_id, key, default=None):
    """Obtiene dato específico de sesión"""
    try:
        session = get_session(chat_id)
        data = session.get("data", {})
        return data.get(key, default) if isinstance(data, dict) else default
    except Exception as e:
        logger.error(f"[GET DATA ERROR] {chat_id}, key={key}: {e}")
        return default


def clear_state(chat_id):
    """Elimina sesión completamente"""
    try:
        db_execute(
            "DELETE FROM sessions WHERE chat_id=?",
            (str(chat_id),)
        )
        logger.info(f"[CLEAR] Sesión eliminada para {chat_id}")
    except Exception as e:
        logger.error(f"[CLEAR ERROR] {chat_id}: {e}")


# ==================== WORKER START ====================

@bot.message_handler(func=lambda m: m.text and "trabajar" in m.text.lower())
def handle_worker_start(message):
    chat_id = message.chat.id
    try:
        logger.info(f"[START] Activado por '{message.text}' | chat_id={chat_id}")
        start_worker_flow(chat_id)
    except Exception as e:
        logger.error(f"[START ERROR] {e}")
        logger.error(traceback.format_exc())
        bot.send_message(
            chat_id,
            f"{Icons.ERROR} Error iniciando registro. Intentá /start"
        )


# ==================== SELECTOR SERVICIOS ====================

def get_service_selector_inline(selected=None):
    """Genera markup de servicios. selected debe ser lista."""
    if selected is None:
        selected = []
    if not isinstance(selected, list):
        logger.warning(f"[SELECTOR] selected no era lista: {type(selected)}")
        selected = list(selected) if hasattr(selected, '__iter__') and not isinstance(selected, (str, bytes)) else []
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []

    for svc_id, svc in SERVICES.items():
        name = svc["name"]
        text = f"✅ {name}" if svc_id in selected else name
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


# ==================== FLUJO REGISTRO ====================

def start_worker_flow(chat_id):
    """Inicia flujo de registro de worker"""
    try:
        # Verificar si ya existe
        worker = db_execute(
            "SELECT 1 FROM workers WHERE chat_id=?",
            (str(chat_id),),
            fetch_one=True
        )

        if worker:
            bot.send_message(chat_id, f"{Icons.INFO} Ya tenés perfil.")
            return

        # Limpieza explícita y estado inicial
        clear_state(chat_id)
        # FIX: Usar set_state con data inicial explícita
        set_state(chat_id, "WORKER_SELECTING_SERVICES", {"selected_services": []})

        text = (
            f"{Icons.BRIEFCASE} <b>Registro Profesional</b>\n\n"
            "Paso 1/5\n"
            "Seleccioná los servicios que ofrecés:"
        )

        bot.send_message(
            chat_id,
            text,
            parse_mode="HTML",
            reply_markup=get_service_selector_inline([])
        )
    except Exception as e:
        logger.error(f"[FLOW START ERROR] {chat_id}: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(chat_id, f"{Icons.ERROR} Error al iniciar. Intentá /start")


@bot.callback_query_handler(func=lambda c: c.data.startswith("svc_toggle:"))
def toggle_service(call):
    """Maneja toggle de servicios con protección contra errores 400"""
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    
    try:
        parts = call.data.split(":")
        if len(parts) != 2:
            bot.answer_callback_query(call.id, "Error interno")
            return
            
        service_id = parts[1]
        
        # Obtener selección actual con defensa
        selected = get_data(chat_id, "selected_services")
        if selected is None:
            selected = []
        elif not isinstance(selected, list):
            logger.warning(f"[TOGGLE] selected_services era {type(selected)}, reseteando a lista")
            selected = []
        
        # Toggle lógica
        if service_id in selected:
            selected.remove(service_id)
            action = "deseleccionado"
        else:
            selected.append(service_id)
            action = "seleccionado"

        # Guardar en BD
        update_data(chat_id, selected_services=selected)
        
        # Generar nuevo markup
        new_markup = get_service_selector_inline(selected)
        
        # FIX CRÍTICO: Comparar antes de editar
        try:
            current_markup = call.message.reply_markup
            if current_markup:
                current_json = json.dumps(current_markup.to_dict(), sort_keys=True)
                new_json = json.dumps(new_markup.to_dict(), sort_keys=True)
                if current_json == new_json:
                    bot.answer_callback_query(call.id, f"Servicio {action}")
                    return
        except Exception as e:
            logger.debug(f"[TOGGLE] Error comparando markups: {e}")
        
        # Editar mensaje
        try:
            bot.edit_message_reply_markup(
                chat_id,
                message_id,
                reply_markup=new_markup
            )
            bot.answer_callback_query(call.id, f"✅ {action}")
        except apihelper.ApiTelegramException as e:
            error_str = str(e)
            if "message is not modified" in error_str:
                bot.answer_callback_query(call.id, "Actualizado")
            elif "message to edit not found" in error_str:
                logger.warning(f"[TOGGLE] Mensaje no encontrado para {chat_id}")
            else:
                logger.error(f"[TOGGLE API ERROR] {chat_id}: {e}")
                bot.answer_callback_query(call.id, "❌ Error temporal")

    except Exception as e:
        logger.error(f"[TOGGLE ERROR] {chat_id}: {e}")
        logger.error(traceback.format_exc())
        try:
            bot.answer_callback_query(call.id, "❌ Error. Intentá de nuevo")
        except:
            pass


@bot.callback_query_handler(func=lambda c: c.data == "svc_confirm")
def confirm_services(call):
    chat_id = call.message.chat_id
    
    try:
        selected = get_data(chat_id, "selected_services", [])
        
        if not selected or not isinstance(selected, list) or len(selected) == 0:
            bot.answer_callback_query(
                call.id,
                "⚠️ Seleccioná al menos un servicio",
                show_alert=True
            )
            return

        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception as e:
            logger.warning(f"[CONFIRM] No se pudo borrar mensaje: {e}")

        set_state(
            chat_id,
            "WORKER_ENTERING_NAME",
            {"selected_services": selected}
        )

        bot.send_message(
            chat_id, 
            "📝 <b>Paso 2/5</b>\n¿Cuál es tu nombre completo?",
            parse_mode="HTML"
        )
        bot.answer_callback_query(call.id)
        
    except Exception as e:
        logger.error(f"[CONFIRM ERROR] {chat_id}: {e}")
        logger.error(traceback.format_exc())
        bot.answer_callback_query(call.id, "Error. Intentá de nuevo", show_alert=True)


# ==================== DISPATCHER CENTRALIZADO (FIX RACE CONDITIONS) ====================

# ESTADOS DEL WORKER FLOW
WORKER_STATES = [
    "WORKER_ENTERING_NAME",
    "WORKER_ENTERING_PHONE", 
    "WORKER_ENTERING_DNI",
    "WORKER_SHARING_LOCATION"
]

@bot.message_handler(func=lambda m: m.text and get_session(m.chat.id).get("state") in WORKER_STATES)
def worker_flow_dispatcher(message):
    """
    Handler ÚNICO que reemplaza los 3 handlers individuales.
    Obtiene get_session() UNA SOLA VEZ y despacha internamente.
    Elimina las race conditions de múltiples lambdas ejecutándose en paralelo.
    """
    chat_id = message.chat.id
    
    # UNA SOLA llamada a DB para todo el flujo
    session = get_session(chat_id)
    state = session.get("state")
    
    logger.info(f"[DISPATCHER] chat_id={chat_id}, state={state}")
    
    try:
        if state == "WORKER_ENTERING_NAME":
            _handle_name_step(message, chat_id)
        elif state == "WORKER_ENTERING_PHONE":
            _handle_phone_step(message, chat_id)
        elif state == "WORKER_ENTERING_DNI":
            _handle_dni_step(message, chat_id)
        elif state == "WORKER_SHARING_LOCATION":
            _handle_location_step(message, chat_id)
    except Exception as e:
        logger.error(f"[DISPATCHER ERROR] {chat_id} en estado {state}: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(chat_id, f"{Icons.ERROR} Error procesando mensaje. Intentá /start")


def _handle_name_step(message, chat_id):
    """Paso 2: Nombre"""
    if not message.text or len(message.text.strip()) < 2:
        bot.send_message(chat_id, "❌ Nombre muy corto. Intentá de nuevo:")
        return
        
    try:
        update_data(chat_id, worker_name=message.text.strip())
        set_state(chat_id, "WORKER_ENTERING_PHONE")
        bot.send_message(
            chat_id, 
            "📱 <b>Paso 3/5</b>\n¿Cuál es tu número de teléfono?",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"[NAME STEP ERROR] {chat_id}: {e}")
        bot.send_message(chat_id, f"{Icons.ERROR} Error. Intentá de nuevo:")


def _handle_phone_step(message, chat_id):
    """Paso 3: Teléfono"""
    if not message.text:
        bot.send_message(chat_id, "❌ Necesito un número de teléfono. Intentá de nuevo:")
        return
        
    phone = re.sub(r"\D", "", message.text)
    
    if len(phone) < 8:
        bot.send_message(chat_id, "❌ Número muy corto. Incluí código de área:")
        return
        
    try:
        update_data(chat_id, worker_phone=phone)
        set_state(chat_id, "WORKER_ENTERING_DNI")
        bot.send_message(
            chat_id, 
            "🆔 <b>Paso 4/5</b>\n¿Cuál es tu número de DNI?",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"[PHONE STEP ERROR] {chat_id}: {e}")
        bot.send_message(chat_id, f"{Icons.ERROR} Error. Intentá de nuevo:")


def _handle_dni_step(message, chat_id):
    """Paso 4: DNI"""
    if not message.text:
        bot.send_message(chat_id, "❌ Necesito el número de DNI. Intentá de nuevo:")
        return
        
    dni = re.sub(r"\D", "", message.text)
    
    if len(dni) < 7 or len(dni) > 10:
        bot.send_message(chat_id, "❌ DNI inválido (7-10 dígitos). Intentá de nuevo:")
        return
        
    try:
        save_worker_data(chat_id, dni)
        set_state(chat_id, "WORKER_SHARING_LOCATION")
        _ask_location_step(chat_id)
    except Exception as e:
        logger.error(f"[DNI STEP ERROR] {chat_id}: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(chat_id, f"{Icons.ERROR} Error guardando datos. Intentá /start")


def _ask_location_step(chat_id):
    """Paso 5: Solicitar ubicación"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(
        types.KeyboardButton(
            "📍 Enviar mi ubicación actual",
            request_location=True
        )
    )
    markup.add(types.KeyboardButton("❌ Cancelar registro"))

    bot.send_message(
        chat_id,
        "📍 <b>Paso 5/5</b>\n\nCompartí tu ubicación para que los clientes te encuentren.\n\n<i>Tocá el botón de abajo 👇</i>",
        parse_mode="HTML",
        reply_markup=markup
    )


def _handle_location_step(message, chat_id):
    """Maneja mensajes de texto cuando se espera ubicación"""
    if message.text and "cancelar" in message.text.lower():
        clear_state(chat_id)
        bot.send_message(
            chat_id,
            "❌ Registro cancelado. Podés reiniciar cuando quieras con /start",
            reply_markup=types.ReplyKeyboardRemove()
        )
    else:
        # No es cancelar, recordar que debe enviar ubicación
        bot.send_message(
            chat_id,
            "⚠️ Por favor, usá el botón <b>📍 Enviar mi ubicación actual</b> o tocá <b>❌ Cancelar registro</b>",
            parse_mode="HTML"
        )


# ==================== UBICACIÓN (CONTENT TYPE) ====================

@bot.message_handler(content_types=["location"])
def save_location(message):
    """Handler separado para ubicación (content_type no se puede filtrar por estado fácilmente)"""
    chat_id = message.chat.id
    
    # Verificación de estado
    session = get_session(chat_id)
    if session.get("state") != "WORKER_SHARING_LOCATION":
        # Ignorar ubicaciones fuera del flujo de registro
        return
        
    try:
        lat = message.location.latitude
        lon = message.location.longitude

        db_execute(
            "UPDATE workers SET lat=?, lon=?, is_active=1 WHERE chat_id=?",
            (lat, lon, str(chat_id))
        )

        bot.send_message(
            chat_id, 
            "🎉 <b>¡Registro completado!</b>\n\n"
            "Tu perfil está activo y visible para clientes.",
            parse_mode="HTML",
            reply_markup=types.ReplyKeyboardRemove()
        )
        
        clear_state(chat_id)
        logger.info(f"[WORKER COMPLETE] Registro finalizado para {chat_id}")
        
    except Exception as e:
        logger.error(f"[SAVE LOCATION ERROR] {chat_id}: {e}")
        bot.send_message(
            chat_id,
            f"{Icons.ERROR} Error guardando ubicación.",
            reply_markup=types.ReplyKeyboardRemove()
        )


# ==================== GUARDAR WORKER ====================

def save_worker_data(chat_id, dni):
    """Guarda datos básicos del worker"""
    try:
        name = get_data(chat_id, "worker_name")
        phone = get_data(chat_id, "worker_phone")
        services = get_data(chat_id, "selected_services", [])

        if not name or not phone:
            raise ValueError("Faltan datos obligatorios")

        db_execute(
            """
            INSERT OR REPLACE INTO workers
            (chat_id, name, phone, dni, is_active, created_at)
            VALUES (?, ?, ?, ?, 0, ?)
            """,
            (str(chat_id), name, phone, dni, int(time.time()))
        )

        db_execute(
            "DELETE FROM worker_services WHERE chat_id=?",
            (str(chat_id),)
        )

        for svc in services:
            if svc:
                db_execute(
                    "INSERT INTO worker_services (chat_id, service_id) VALUES (?, ?)",
                    (str(chat_id), svc)
                )
        
        logger.info(f"[SAVE WORKER] Datos guardados para {chat_id}")
        
    except Exception as e:
        logger.error(f"[SAVE WORKER ERROR] {chat_id}: {e}")
        raise
