import os
import time
import re
import logging
from telebot import types, apihelper
from config import bot
from models.user_state import (
    set_state, update_data, get_data,
    clear_state, UserState, get_session
)
from models.services_data import SERVICES
from utils.icons import Icons
from utils.keyboards import get_service_selector
from handlers.common import send_safe, edit_safe
from database import db_execute

# ==================== CONFIGURACIÓN ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)
apihelper.SESSION_TIME_TO_LIVE = 10 * 60

# ======================================================
# ==================== FLUJO WORKER ====================
# ======================================================
@bot.message_handler(regexp=r'(?i)(trabajar|prestador|quiero trabajar)')
def handle_worker_start(message):
    chat_id = message.chat.id
    try:
        logger.info(f"[START] Activado por '{message.text}' | chat_id: {chat_id}")
        start_worker_flow(chat_id)
    except Exception as e:
        logger.error(f"[START ERROR] chat_id={chat_id} -> {e}")
        try:
            bot.send_message(chat_id, "❌ Ocurrió un error iniciando tu registro. Intentá de nuevo.")
        except:
            pass

def start_worker_flow(chat_id: int):
    try:
        worker = db_execute(
            "SELECT * FROM workers WHERE chat_id = ?",
            (str(chat_id),),
            fetch_one=True
        )

        if worker:
            try:
                from handlers.worker.profile import show_worker_menu
                bot.send_chat_action(chat_id, 'typing')
                show_worker_menu(chat_id, worker)
            except Exception as e:
                logger.error(f"[SHOW MENU ERROR] {e}")
                bot.send_message(chat_id, "Perfil activo. Función de menú no disponible.")
            return

        set_state(chat_id, UserState.WORKER_SELECTING_SERVICES, {"selected_services": []})

        text = f"""
{Icons.BRIEFCASE} <b>Registro de Profesional</b>

Vamos a configurar tu perfil.

<b>Paso 1/5:</b> ¿Qué servicios ofrecés?
{Icons.INFO} Podés seleccionar varios.
        """
        send_safe(chat_id, text, get_service_selector([]))
    except Exception as e:
        logger.error(f"[FLOW START ERROR] chat_id={chat_id} -> {e}")
        try:
            bot.send_message(chat_id, "❌ Error iniciando flujo de registro.")
        except:
            pass

# ======================================================
# ==================== SERVICIOS =======================
# ======================================================
@bot.callback_query_handler(func=lambda c: c.data.startswith("svc_toggle:"))
def handle_service_toggle(call):
    try:
        chat_id = call.message.chat.id
        service_id = call.data.split(":")[1]

        session = get_session(chat_id)
        if not session:
            bot.answer_callback_query(call.id, "Sesión perdida. Iniciá de nuevo.", show_alert=True)
            return

        selected = session.data.get("selected_services", [])
        if service_id in selected:
            selected.remove(service_id)
            bot.answer_callback_query(call.id, f"❌ {SERVICES[service_id]['name']} removido")
        else:
            selected.append(service_id)
            bot.answer_callback_query(call.id, f"✅ {SERVICES[service_id]['name']} agregado")

        update_data(chat_id, selected_services=selected)
        edit_safe(chat_id, call.message.message_id, call.message.text, get_service_selector(selected))
    except Exception as e:
        logger.error(f"[SERVICE TOGGLE ERROR] chat_id={call.message.chat.id} -> {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Ocurrió un error.", show_alert=True)
        except:
            pass

@bot.callback_query_handler(func=lambda c: c.data == "svc_confirm")
def handle_service_confirm(call):
    try:
        chat_id = call.message.chat.id
        selected = get_data(chat_id, "selected_services", [])
        if not selected:
            bot.answer_callback_query(call.id, "Seleccioná al menos un servicio", show_alert=True)
            return

        try:
            bot.answer_callback_query(call.id)
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass

        set_state(chat_id, UserState.WORKER_ENTERING_PRICE, {
            "services_to_price": selected[:],
            "current_service_idx": 0,
            "prices": {}
        })
        ask_next_price(chat_id)
    except Exception as e:
        logger.error(f"[SERVICE CONFIRM ERROR] chat_id={call.message.chat.id} -> {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Error confirmando servicios.", show_alert=True)
        except:
            pass

# ======================================================
# ==================== PRECIOS =========================
# ======================================================
def ask_next_price(chat_id: int):
    try:
        services = get_data(chat_id, "services_to_price", [])
        idx = get_data(chat_id, "current_service_idx", 0)

        if idx >= len(services):
            set_state(chat_id, UserState.WORKER_ENTERING_NAME)
            ask_worker_name(chat_id)
            return

        service_id = services[idx]
        service_name = SERVICES.get(service_id, {}).get("name", service_id)

        text = f"""
{Icons.MONEY} <b>Precio para {service_name} ({idx+1}/{len(services)})</b>
Ingresá tarifa por hora (solo números)
        """
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("⏭️ Saltar")
        markup.add("❌ Cancelar")
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"[ASK PRICE ERROR] chat_id={chat_id} -> {e}")
        try:
            bot.send_message(chat_id, "❌ Error pidiendo precio.")
        except:
            pass

@bot.message_handler(func=lambda m: get_session(m.chat.id) and get_session(m.chat.id).state == UserState.WORKER_ENTERING_PRICE)
def handle_price_input(message):
    try:
        chat_id = message.chat.id
        text = message.text.strip()
        if text == "❌ Cancelar":
            cancel_flow(chat_id)
            return

        services = get_data(chat_id, "services_to_price", [])
        idx = get_data(chat_id, "current_service_idx", 0)

        if text == "⏭️ Saltar":
            prices = get_data(chat_id, "prices", {})
            prices[services[idx]] = None
            update_data(chat_id, prices=prices, current_service_idx=idx + 1)
            ask_next_price(chat_id)
            return

        if not text.isdigit():
            bot.send_message(chat_id, "❌ Ingresá solo números.")
            return

        price = int(text)
        prices = get_data(chat_id, "prices", {})
        prices[services[idx]] = price
        update_data(chat_id, prices=prices, current_service_idx=idx + 1)

        bot.send_message(chat_id, f"✅ Precio guardado: ${price}/hora")
        ask_next_price(chat_id)
    except Exception as e:
        logger.error(f"[PRICE INPUT ERROR] chat_id={message.chat.id} -> {e}")
        try:
            bot.send_message(message.chat.id, "❌ Error guardando precio.")
        except:
            pass

# ======================================================
# ==================== NOMBRE ==========================
# ======================================================
def ask_worker_name(chat_id: int):
    try:
        text = f"{Icons.USER} <b>Paso 2/5: Tu nombre</b>\n¿Cómo te llaman los clientes?"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("❌ Cancelar")
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"[ASK NAME ERROR] chat_id={chat_id} -> {e}")

@bot.message_handler(func=lambda m: get_session(m.chat.id) and get_session(m.chat.id).state == UserState.WORKER_ENTERING_NAME)
def handle_name_input(message):
    try:
        chat_id = message.chat.id
        name = message.text.strip()
        if name == "❌ Cancelar":
            cancel_flow(chat_id)
            return
        if len(name) < 2:
            bot.send_message(chat_id, "❌ Nombre muy corto.")
            return

        update_data(chat_id, worker_name=name)
        set_state(chat_id, UserState.WORKER_ENTERING_PHONE)
        ask_worker_phone(chat_id)
    except Exception as e:
        logger.error(f"[NAME INPUT ERROR] chat_id={message.chat.id} -> {e}")
        try:
            bot.send_message(message.chat.id, "❌ Error guardando nombre.")
        except:
            pass

# ======================================================
# ==================== TELÉFONO ========================
# ======================================================
def ask_worker_phone(chat_id: int):
    try:
        text = f"{Icons.PHONE} <b>Paso 3/5: Teléfono</b>\nIngresá tu número de contacto."
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton("❌ Cancelar"))
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"[ASK PHONE ERROR] chat_id={chat_id} -> {e}")

@bot.message_handler(func=lambda m: m.text and get_session(m.chat.id) and get_session(m.chat.id).state == UserState.WORKER_ENTERING_PHONE)
def handle_phone_input(message):
    try:
        chat_id = message.chat.id
        phone = re.sub(r"\D", "", message.text.strip())
        if message.text == "❌ Cancelar":
            cancel_flow(chat_id)
            return
        if len(phone) < 8:
            bot.send_message(chat_id, "❌ Número inválido. Ingresá al menos 8 dígitos.")
            return

        update_data(chat_id, worker_phone=phone)
        set_state(chat_id, UserState.WORKER_ENTERING_DNI)
        ask_worker_dni(chat_id)
    except Exception as e:
        logger.error(f"[PHONE INPUT ERROR] chat_id={message.chat.id} -> {e}")
        try:
            bot.send_message(message.chat.id, "❌ Error guardando teléfono.")
        except:
            pass

# ======================================================
# ==================== DNI =============================
# ======================================================
def ask_worker_dni(chat_id: int):
    try:
        text = f"{Icons.USER} <b>Paso 4/5: DNI</b>\nIngresá tu documento (7 u 8 dígitos)."
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton("❌ Cancelar"))
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"[ASK DNI ERROR] chat_id={chat_id} -> {e}")

@bot.message_handler(func=lambda m: m.text and get_session(m.chat.id) and get_session(m.chat.id).state == UserState.WORKER_ENTERING_DNI)
def handle_dni_input(message):
    try:
        chat_id = message.chat.id
        dni = re.sub(r"\D", "", message.text.strip())
        if message.text == "❌ Cancelar":
            cancel_flow(chat_id)
            return
        if not (7 <= len(dni) <= 8):
            bot.send_message(chat_id, "❌ DNI inválido. Debe tener 7 u 8 dígitos.")
            return

        save_worker_data(chat_id, dni)
        set_state(chat_id, UserState.WORKER_SHARING_LOCATION)
        ask_worker_location(chat_id)
    except Exception as e:
        logger.error(f"[DNI INPUT ERROR] chat_id={message.chat.id} -> {e}")
        try:
            bot.send_message(message.chat.id, "❌ Error guardando DNI.")
        except:
            pass

# ======================================================
# ==================== UBICACIÓN =======================
# ======================================================
def ask_worker_location(chat_id: int):
    try:
        text = f"{Icons.LOCATION} <b>Paso 5/5: Ubicación</b>\nTocá el botón azul para enviar tu ubicación."
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(types.KeyboardButton("📍 Enviar ubicación", request_location=True))
        markup.add("❌ Cancelar")
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"[ASK LOCATION ERROR] chat_id={chat_id} -> {e}")

# ======================================================
# HANDLER DE UBICACIÓN - REGISTRADO AL FINAL PARA PRIORIDAD
# ======================================================
logger.info("[INIT] Registrando handler de ubicación...")

@bot.message_handler(content_types=['location'])
def handle_location(message):
    """Handler para mensajes de ubicación - debe estar registrado después de los handlers de texto"""
    chat_id = message.chat.id
    
    logger.info(f"[LOCATION] Recibida ubicación de chat_id={chat_id}")
    
    try:
        # Obtener sesión con manejo seguro
        session = get_session(chat_id)
        
        if not session:
            logger.warning(f"[LOCATION] No hay sesión activa para chat_id={chat_id}")
            return
            
        current_state = getattr(session, 'state', None)
        logger.info(f"[LOCATION] Estado actual: {current_state}")
        
        # Verificar que esté en el paso correcto
        if current_state != UserState.WORKER_SHARING_LOCATION:
            logger.info(f"[LOCATION] Ignorado - estado incorrecto: {current_state}")
            return

        # Validar ubicación
        if not message.location:
            logger.error(f"[LOCATION] Mensaje sin objeto location")
            bot.send_message(
                chat_id, 
                "❌ Error al recibir ubicación. Intentá de nuevo.",
                reply_markup=types.ReplyKeyboardRemove()
            )
            return

        lat = message.location.latitude
        lon = message.location.longitude
        timestamp = int(time.time())

        logger.info(f"[LOCATION] Procesando: lat={lat}, lon={lon}")

        # Verificar worker en DB
        worker = db_execute(
            "SELECT chat_id FROM workers WHERE chat_id = ?",
            (str(chat_id),),
            fetch_one=True
        )
        
        if not worker:
            logger.error(f"[LOCATION] Worker no existe: {chat_id}")
            bot.send_message(
                chat_id,
                "❌ Error: Perfil no encontrado. Reiniciá con /start",
                reply_markup=types.ReplyKeyboardRemove()
            )
            return

        # Actualizar DB
        try:
            db_execute("""
                UPDATE workers
                SET lat = ?, lon = ?, last_update = ?, disponible = 1
                WHERE chat_id = ?
            """, (lat, lon, timestamp, str(chat_id)), commit=True)
            logger.info(f"[LOCATION] DB actualizada para {chat_id}")
        except Exception as db_error:
            logger.error(f"[LOCATION] Error DB: {db_error}")
            bot.send_message(
                chat_id,
                "❌ Error guardando ubicación. Intentá de nuevo.",
                reply_markup=types.ReplyKeyboardRemove()
            )
            return

        # ÉXITO: Remover teclado y confirmar
        try:
            bot.send_message(
                chat_id,
                f"{Icons.PARTY} <b>¡Registro completado!</b>\n\nYa estás activo 💪",
                parse_mode="HTML",
                reply_markup=types.ReplyKeyboardRemove()
            )
            logger.info(f"[LOCATION] Mensaje de éxito enviado a {chat_id}")
        except Exception as send_error:
            logger.error(f"[LOCATION] Error enviando confirmación: {send_error}")
            return

        # Mostrar menú del worker
        try:
            time.sleep(0.3)  # Pequeña pausa
            from handlers.worker.profile import show_worker_menu
            bot.send_chat_action(chat_id, 'typing')
            
            worker_data = db_execute(
                "SELECT * FROM workers WHERE chat_id = ?",
                (str(chat_id),),
                fetch_one=True
            )
            
            if worker_data:
                show_worker_menu(chat_id, worker_data)
                logger.info(f"[LOCATION] Menú mostrado para {chat_id}")
                
        except Exception as menu_error:
            logger.error(f"[LOCATION] Error mostrando menú: {menu_error}")
            # No crítico, el registro ya está completo

        # Limpiar sesión
        try:
            clear_state(chat_id)
            logger.info(f"[LOCATION] Sesión limpiada para {chat_id}")
        except Exception as clear_error:
            logger.error(f"[LOCATION] Error limpiando sesión: {clear_error}")

    except Exception as e:
        logger.error(f"[LOCATION] Error crítico: {e}", exc_info=True)
        try:
            bot.send_message(
                chat_id,
                "❌ Error procesando ubicación. Contactá soporte.",
                reply_markup=types.ReplyKeyboardRemove()
            )
        except:
            pass

logger.info("[INIT] Handler de ubicación registrado")

# ======================================================
# ================= GUARDAR WORKER =====================
# ======================================================
def save_worker_data(chat_id: int, dni: str):
    try:
        name = get_data(chat_id, "worker_name")
        phone = get_data(chat_id, "worker_phone")
        prices = get_data(chat_id, "prices", {})
        selected_services = get_data(chat_id, "selected_services", [])

        logger.info(f"[SAVE] Guardando worker {chat_id}: {name}")

        db_execute("""
            INSERT OR REPLACE INTO workers 
            (chat_id, nombre, telefono, dni_file_id, services, prices, disponible, lat, lon, last_update)
            VALUES (?, ?, ?, ?, ?, ?, 0, NULL, NULL, NULL)
        """, (
            str(chat_id),
            name,
            phone,
            dni,
            ",".join(selected_services),
            str(prices)
        ), commit=True)
        
        logger.info(f"[SAVE] Worker {chat_id} guardado exitosamente")
        
    except Exception as e:
        logger.error(f"[SAVE ERROR] {chat_id}: {e}")
        raise

def cancel_flow(chat_id: int):
    """Cancela el flujo de registro"""
    try:
        clear_state(chat_id)
        bot.send_message(
            chat_id,
            "❌ Registro cancelado. Escribí 'trabajar' para reiniciar.",
            reply_markup=types.ReplyKeyboardRemove()
        )
        logger.info(f"[CANCEL] Flujo cancelado para {chat_id}")
    except Exception as e:
        logger.error(f"[CANCEL ERROR] {chat_id}: {e}")

# ======================================================
# ==================== POLLING =========================
# ======================================================
if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("Bot CleanyGo iniciando...")
    logger.info("=" * 50)
    
    while True:
        try:
            logger.info("Iniciando infinity_polling...")
            bot.infinity_polling(
                timeout=60,
                long_polling_timeout=30,
                skip_pending=True,
                none_stop=True  # No detenerse ante errores de conexión
            )
        except Exception as e:
            logger.error(f"Error en polling: {e}")
            time.sleep(5)
