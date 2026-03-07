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
            try:
                data = json.loads(data_json) if data_json else {}
                # Validar que sea dict
                if not isinstance(data, dict):
                    raise ValueError("Data no es diccionario")
                return {"state": state, "data": data}
            except Exception as e:
                logger.error(f"[SESSION] JSON corrupto para {chat_id}: {e} - reiniciando")
                # Limpieza completa: eliminar y recrear
                clear_state(chat_id)
                # Crear nueva sesión limpia
                return create_fresh_session(chat_id)

        # No existe sesión, crear nueva
        return create_fresh_session(chat_id)

    except Exception as e:
        logger.error(f"[SESSION] Error DB en get_session para {chat_id}: {e}")
        return {"state": "IDLE", "data": {}}


def create_fresh_session(chat_id):
    """Crea una sesión limpia nueva"""
    try:
        db_execute(
            "INSERT OR REPLACE INTO sessions (chat_id,state,data,last_activity) VALUES (?,?,?,?)",
            (str(chat_id), "IDLE", "{}", int(time.time()))
        )
        return {"state": "IDLE", "data": {}}
    except Exception as e:
        logger.error(f"[SESSION] Error creando sesión fresca para {chat_id}: {e}")
        return {"state": "IDLE", "data": {}}


def safe_json(data):
    if isinstance(data, dict):
        return {k: safe_json(v) for k, v in data.items()}
    if isinstance(data, list):
        return [safe_json(x) for x in data]
    if isinstance(data, (str, int, float, type(None))):
        return data
    return str(data)


def set_state(chat_id, state, data=None):
    """Establece estado con transacción atómica"""
    try:
        session = get_session(chat_id)
        new_data = session["data"] if isinstance(session["data"], dict) else {}
        
        if data and isinstance(data, dict):
            new_data.update(data)

        db_execute(
            "INSERT OR REPLACE INTO sessions (chat_id,state,data,last_activity) VALUES (?,?,?,?)",
            (
                str(chat_id),
                state,
                json.dumps(safe_json(new_data)),
                int(time.time())
            )
        )
        logger.info(f"[STATE] {chat_id} -> {state}")
    except Exception as e:
        logger.error(f"[STATE ERROR] No se pudo setear estado para {chat_id}: {e}")


def update_data(chat_id, **kwargs):
    """Actualiza datos específicos"""
    try:
        session = get_session(chat_id)
        new_data = session["data"] if isinstance(session["data"], dict) else {}
        new_data.update(kwargs)

        db_execute(
            "UPDATE sessions SET data=?, last_activity=? WHERE chat_id=?",
            (
                json.dumps(safe_json(new_data)),
                int(time.time()),
                str(chat_id)
            )
        )
    except Exception as e:
        logger.error(f"[UPDATE DATA ERROR] {chat_id}: {e}")


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
            f"{Icons.ERROR} Error iniciando registro. Intentá de nuevo con /start"
        )


# ==================== SELECTOR SERVICIOS ====================

def get_service_selector_inline(selected):
    """Genera markup de servicios. selected debe ser lista."""
    if not isinstance(selected, list):
        selected = []
    
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

        # Inicializar estado fresco
        clear_state(chat_id)
        set_state(chat_id, "WORKER_SELECTING_SERVICES", {"selected_services": []})

        text = (
            f"{Icons.BRIEFCASE} <b>Registro Profesional</b>\n\n"
            "Paso 1/5\n"
            "Seleccioná los servicios que ofrecés (podés elegir varios):"
        )

        bot.send_message(
            chat_id,
            text,
            parse_mode="HTML",
            reply_markup=get_service_selector_inline([])
        )
    except Exception as e:
        logger.error(f"[FLOW START ERROR] {chat_id}: {e}")
        bot.send_message(chat_id, f"{Icons.ERROR} Error al iniciar. Intentá /start")


@bot.callback_query_handler(func=lambda c: c.data.startswith("svc_toggle:"))
def toggle_service(call):
    """Maneja toggle de servicios con protección contra errores 400"""
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    
    try:
        # Extraer service_id
        parts = call.data.split(":")
        if len(parts) != 2:
            bot.answer_callback_query(call.id, "Error interno")
            return
            
        service_id = parts[1]
        
        # Obtener selección actual
        selected = get_data(chat_id, "selected_services", [])
        if not isinstance(selected, list):
            selected = []
            logger.warning(f"[TOGGLE] selected_services no era lista para {chat_id}, reseteando")

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
        
        # ⚠️ FIX CRÍTICO: Verificar si realmente cambió antes de editar
        try:
            current_markup = call.message.reply_markup
            if current_markup and new_markup.to_json() == current_markup.to_json():
                # No hay cambios visuales, solo ack
                bot.answer_callback_query(call.id, f"Servicio {action}")
                return
        except Exception as e:
            # Si falla la comparación, intentar editar igual
            pass
        
        # Editar mensaje
        try:
            bot.edit_message_reply_markup(
                chat_id,
                message_id,
                reply_markup=new_markup
            )
            bot.answer_callback_query(call.id, f"✅ {action}")
        except apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e):
                # Ignorar silenciosamente, es esperado a veces
                bot.answer_callback_query(call.id, "Ya actualizado")
            else:
                raise

    except Exception as e:
        logger.error(f"[TOGGLE ERROR] {chat_id}: {e}")
        logger.error(traceback.format_exc())
        try:
            bot.answer_callback_query(call.id, "❌ Error. Intentá de nuevo")
        except:
            pass


@bot.callback_query_handler(func=lambda c: c.data == "svc_confirm")
def confirm_services(call):
    chat_id = call.message.chat.id
    
    try:
        selected = get_data(chat_id, "selected_services", [])
        
        if not selected or not isinstance(selected, list) or len(selected) == 0:
            bot.answer_callback_query(
                call.id,
                "⚠️ Seleccioná al menos un servicio",
                show_alert=True
            )
            return

        # Eliminar mensaje de selección
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except Exception as e:
            logger.warning(f"[CONFIRM] No se pudo borrar mensaje: {e}")

        # Cambiar estado
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
        bot.answer_callback_query(call.id, "Error. Intentá de nuevo", show_alert=True)


# ==================== NOMBRE ====================

@bot.message_handler(func=lambda m: get_session(m.chat.id).get("state") == "WORKER_ENTERING_NAME")
def save_name(message):
    chat_id = message.chat.id
    
    if not message.text or len(message.text.strip()) < 2:
        bot.send_message(chat_id, "❌ Nombre muy corto. Intentá de nuevo:")
        return
        
    try:
        update_data(chat_id, worker_name=message.text.strip())
        set_state(chat_id, "WORKER_ENTERING_PHONE")
        bot.send_message(chat_id, "📱 <b>Paso 3/5</b>\n¿Cuál es tu número de teléfono?\n<i>(Ej: 11 1234-5678)</i>", parse_mode="HTML")
    except Exception as e:
        logger.error(f"[SAVE NAME ERROR] {chat_id}: {e}")
        bot.send_message(chat_id, f"{Icons.ERROR} Error. Intentá de nuevo:")


# ==================== TELEFONO ====================

@bot.message_handler(func=lambda m: get_session(m.chat.id).get("state") == "WORKER_ENTERING_PHONE")
def save_phone(message):
    chat_id = message.chat.id
    
    if not message.text:
        bot.send_message(chat_id, "❌ Necesito un número de teléfono. Intentá de nuevo:")
        return
        
    phone = re.sub(r"\D", "", message.text)
    
    if len(phone) < 8:
        bot.send_message(chat_id, "❌ Número muy corto. Incluí código de área (Ej: 11):")
        return
        
    try:
        update_data(chat_id, worker_phone=phone)
        set_state(chat_id, "WORKER_ENTERING_DNI")
        bot.send_message(chat_id, "🆔 <b>Paso 4/5</b>\n¿Cuál es tu número de DNI?", parse_mode="HTML")
    except Exception as e:
        logger.error(f"[SAVE PHONE ERROR] {chat_id}: {e}")
        bot.send_message(chat_id, f"{Icons.ERROR} Error. Intentá de nuevo:")


# ==================== DNI ====================

@bot.message_handler(func=lambda m: get_session(m.chat.id).get("state") == "WORKER_ENTERING_DNI")
def save_dni(message):
    chat_id = message.chat.id
    
    if not message.text:
        bot.send_message(chat_id, "❌ Necesito el número de DNI. Intentá de nuevo:")
        return
        
    dni = re.sub(r"\D", "", message.text)
    
    if len(dni) < 7 or len(dni) > 10:
        bot.send_message(chat_id, "❌ DNI inválido (debe tener 7-10 dígitos). Intentá de nuevo:")
        return
        
    try:
        save_worker_data(chat_id, dni)
        set_state(chat_id, "WORKER_SHARING_LOCATION")
        ask_location(chat_id)
    except Exception as e:
        logger.error(f"[SAVE DNI ERROR] {chat_id}: {e}")
        bot.send_message(chat_id, f"{Icons.ERROR} Error guardando datos. Intentá /start")


# ==================== UBICACION ====================

def ask_location(chat_id):
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
        "📍 <b>Paso 5/5</b>\n\nCompartí tu ubicación actual para que los clientes te encuentren.\n\n<i>Tocá el botón de abajo 👇</i>",
        parse_mode="HTML",
        reply_markup=markup
    )


@bot.message_handler(func=lambda m: m.text and "cancelar" in m.text.lower() and get_session(m.chat.id).get("state") == "WORKER_SHARING_LOCATION")
def cancel_registration(message):
    chat_id = message.chat.id
    clear_state(chat_id)
    bot.send_message(
        chat_id,
        "❌ Registro cancelado. Podés reiniciar cuando quieras con /start",
        reply_markup=types.ReplyKeyboardRemove()
    )


@bot.message_handler(content_types=["location"])
def save_location(message):
    chat_id = message.chat.id
    
    # Verificar que esté en el estado correcto
    session = get_session(chat_id)
    if session.get("state") != "WORKER_SHARING_LOCATION":
        # Ignorar ubicaciones fuera de contexto
        return
        
    try:
        lat = message.location.latitude
        lon = message.location.longitude

        # Actualizar worker con ubicación y activar
        db_execute(
            "UPDATE workers SET lat=?, lon=?, is_active=1 WHERE chat_id=?",
            (lat, lon, str(chat_id))
        )

        # Mensaje de éxito con remove markup
        bot.send_message(
            chat_id, 
            "🎉 <b>¡Registro completado!</b>\n\n"
            "Tu perfil está activo y visible para clientes.\n"
            "Te contactaremos cuando haya trabajos disponibles en tu zona.",
            parse_mode="HTML",
            reply_markup=types.ReplyKeyboardRemove()
        )
        
        clear_state(chat_id)
        logger.info(f"[WORKER COMPLETE] Registro finalizado para {chat_id}")
        
    except Exception as e:
        logger.error(f"[SAVE LOCATION ERROR] {chat_id}: {e}")
        bot.send_message(
            chat_id,
            f"{Icons.ERROR} Error guardando ubicación. Intentá de nuevo o contactá soporte.",
            reply_markup=types.ReplyKeyboardRemove()
        )


# ==================== GUARDAR WORKER ====================

def save_worker_data(chat_id, dni):
    """Guarda datos básicos del worker (sin ubicación)"""
    try:
        name = get_data(chat_id, "worker_name")
        phone = get_data(chat_id, "worker_phone")
        services = get_data(chat_id, "selected_services", [])

        if not name or not phone:
            raise ValueError("Faltan datos obligatorios")

        # Insertar worker (inactivo hasta tener ubicación)
        db_execute(
            """
            INSERT OR REPLACE INTO workers
            (chat_id, name, phone, dni, is_active, created_at)
            VALUES (?, ?, ?, ?, 0, ?)
            """,
            (str(chat_id), name, phone, dni, int(time.time()))
        )

        # Limpiar servicios anteriores e insertar nuevos
        db_execute(
            "DELETE FROM worker_services WHERE chat_id=?",
            (str(chat_id),)
        )

        for svc in services:
            if svc:  # Validar que no sea None/empty
                db_execute(
                    """
                    INSERT INTO worker_services
                    (chat_id, service_id)
                    VALUES (?, ?)
                    """,
                    (str(chat_id), svc)
                )
        
        logger.info(f"[SAVE WORKER] Datos guardados para {chat_id}, servicios: {services}")
        
    except Exception as e:
        logger.error(f"[SAVE WORKER ERROR] {chat_id}: {e}")
        raise
