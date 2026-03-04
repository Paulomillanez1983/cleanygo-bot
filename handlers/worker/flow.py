import re
import time
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)
apihelper.SESSION_TIME_TO_LIVE = 10 * 60

# ==================== FLUJO WORKER ====================
@bot.message_handler(regexp=r'(?i)(trabajar|prestador|quiero trabajar)')
def handle_worker_start(message):
    chat_id = message.chat.id
    try:
        logger.info(f"[START] Activado por '{message.text}' | chat_id: {chat_id}")
        start_worker_flow(chat_id)
    except Exception as e:
        logger.error(f"[START ERROR] chat_id={chat_id} -> {e}")
        bot.send_message(chat_id, "❌ Ocurrió un error iniciando tu registro. Intentá de nuevo.")

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
            except Exception:
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
        bot.send_message(chat_id, "❌ Error iniciando flujo de registro.")

# ==================== SERVICIOS =======================
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
        bot.answer_callback_query(call.id, "❌ Ocurrió un error.", show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data == "svc_confirm")
def handle_service_confirm(call):
    try:
        chat_id = call.message.chat.id
        selected = get_data(chat_id, "selected_services", [])
        if not selected:
            bot.answer_callback_query(call.id, "Seleccioná al menos un servicio", show_alert=True)
            return

        bot.answer_callback_query(call.id)
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass

        db_execute(
            "INSERT OR IGNORE INTO workers (chat_id, disponible) VALUES (?, 0)",
            (str(chat_id),),
            commit=True
        )

        # iniciar flujo refactorizado
        set_state(chat_id, UserState.WORKER_FLOW, {
            "step": "price",
            "services_to_price": selected[:],
            "current_service_idx": 0,
            "prices": {},
            "worker_name": "",
            "worker_phone": "",
            "worker_dni": "",
            "location": None
        })
        send_next_step(chat_id)
    except Exception as e:
        logger.error(f"[SERVICE CONFIRM ERROR] chat_id={call.message.chat.id} -> {e}")
        bot.answer_callback_query(call.id, "❌ Ocurrió un error confirmando servicios.", show_alert=True)

# ==================== FLUJO ÚNICO =======================
FLOW_STEPS = {
    "price": {
        "prompt": lambda chat_id: f"{Icons.MONEY} <b>Precio para {SERVICES.get(get_current_service(chat_id), {}).get('name', get_current_service(chat_id))}</b>\nIngresá tarifa por hora (solo números)",
        "keyboard": lambda: ["⏭️ Saltar", "❌ Cancelar"],
        "validator": lambda text: text.isdigit() or text in ["⏭️ Saltar", "❌ Cancelar"],
        "save": lambda chat_id, text: save_price(chat_id, text),
        "next": lambda chat_id: next_price_or_name(chat_id)
    },
    "name": {
        "prompt": lambda chat_id: f"{Icons.USER} <b>Paso 2/5: Tu nombre</b>\n¿Cómo te llaman los clientes?",
        "keyboard": lambda: ["❌ Cancelar"],
        "validator": lambda text: len(text) >= 2 or text == "❌ Cancelar",
        "save": lambda chat_id, text: update_data(chat_id, worker_name=text),
        "next": lambda chat_id: set_state(chat_id, UserState.WORKER_FLOW, {"step": "phone"} ) or send_next_step(chat_id)
    },
    "phone": {
        "prompt": lambda chat_id: f"{Icons.PHONE} <b>Paso 3/5: Teléfono</b>\nIngresá tu número de contacto.",
        "keyboard": lambda: ["❌ Cancelar"],
        "validator": lambda text: (text.isdigit() and len(re.sub(r"\D", "", text)) >= 8) or text == "❌ Cancelar",
        "save": lambda chat_id, text: update_data(chat_id, worker_phone=re.sub(r"\D","",text)),
        "next": lambda chat_id: set_state(chat_id, UserState.WORKER_FLOW, {"step": "dni"} ) or send_next_step(chat_id)
    },
    "dni": {
        "prompt": lambda chat_id: f"{Icons.USER} <b>Paso 4/5: DNI</b>\nIngresá tu documento (7 u 8 dígitos).",
        "keyboard": lambda: ["❌ Cancelar"],
        "validator": lambda text: (text.isdigit() and 7 <= len(text) <= 8) or text == "❌ Cancelar",
        "save": lambda chat_id, text: update_data(chat_id, worker_dni=text),
        "next": lambda chat_id: set_state(chat_id, UserState.WORKER_FLOW, {"step": "location"} ) or send_next_step(chat_id)
    },
    "location": {
        "prompt": lambda chat_id: f"{Icons.LOCATION} <b>Paso 5/5: Ubicación</b>\nTocá el botón azul para enviar tu ubicación.",
        "keyboard": lambda: ["📍 Enviar ubicación", "❌ Cancelar"]
    }
}

def get_current_service(chat_id):
    session = get_session(chat_id)
    idx = session.data.get("current_service_idx", 0)
    return session.data.get("services_to_price", [])[idx]

def save_price(chat_id, text):
    session = get_session(chat_id)
    idx = session.data.get("current_service_idx",0)
    prices = session.data.get("prices",{})
    if text == "⏭️ Saltar":
        prices[get_current_service(chat_id)] = None
    else:
        prices[get_current_service(chat_id)] = int(text)
    update_data(chat_id, prices=prices, current_service_idx=idx+1)

def next_price_or_name(chat_id):
    session = get_session(chat_id)
    if session.data.get("current_service_idx",0) >= len(session.data.get("services_to_price",[])):
        set_state(chat_id, UserState.WORKER_FLOW, {"step":"name"})
    send_next_step(chat_id)

def send_next_step(chat_id):
    session = get_session(chat_id)
    step = session.data.get("step")
    step_conf = FLOW_STEPS.get(step)
    if not step_conf:
        return
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for btn in step_conf["keyboard"]():
        if isinstance(btn,str):
            markup.add(btn)
        else:
            markup.add(types.KeyboardButton(btn))
    bot.send_message(chat_id, step_conf["prompt"](chat_id), reply_markup=markup, parse_mode="HTML")

@bot.message_handler(func=lambda m: get_session(m.chat.id) and get_session(m.chat.id).state == UserState.WORKER_FLOW)
def handle_flow(message):
    chat_id = message.chat.id
    session = get_session(chat_id)
    step = session.data.get("step")
    if message.text == "❌ Cancelar":
        cancel_flow(chat_id)
        return
    step_conf = FLOW_STEPS.get(step)
    if not step_conf:
        bot.send_message(chat_id,"❌ Paso inválido")
        return
    if not step_conf["validator"](message.text):
        bot.send_message(chat_id,"❌ Valor inválido")
        return
    step_conf["save"](chat_id,message.text)
    if step_conf.get("next"):
        step_conf["next"](chat_id)

# ==================== UBICACIÓN =======================
@bot.message_handler(content_types=['location'])
def handle_location(message):
    chat_id = message.chat.id
    session = get_session(chat_id)
    if not session or session.data.get("step") != "location":
        return
    if not message.location:
        bot.send_message(chat_id,"❌ No se detectó ubicación.")
        return
    lat, lon = message.location.latitude, message.location.longitude
    timestamp = int(time.time())
    update_data(chat_id, location=(lat,lon))
    worker_data = get_session(chat_id).data
    # Guardar en DB
    db_execute("""
        UPDATE workers
        SET lat=?, lon=?, last_update=?, disponible=1,
            nombre=?, telefono=?, dni_file_id=?, services=?, prices=?
        WHERE chat_id=?
    """,(
        lat, lon, timestamp,
        worker_data.get("worker_name"),
        worker_data.get("worker_phone"),
        worker_data.get("worker_dni"),
        ",".join(worker_data.get("services_to_price",[])),
        str(worker_data.get("prices",{})),
        str(chat_id)
    ), commit=True)
    bot.send_message(chat_id,f"{Icons.PARTY} <b>¡Registro completado!</b>\n\nYa estás activo 💪",
                     parse_mode="HTML", reply_markup=types.ReplyKeyboardRemove())
    try:
        from handlers.worker.profile import show_worker_menu
        bot.send_chat_action(chat_id,'typing')
        worker = db_execute("SELECT * FROM workers WHERE chat_id=?",(str(chat_id),),fetch_one=True)
        if worker: show_worker_menu(chat_id,worker)
    except Exception as e:
        logger.error(f"[MENU ERROR] chat_id={chat_id} -> {e}")
        bot.send_message(chat_id,"Tu registro se completó, pero hubo un error mostrando el menú.")
    clear_state(chat_id)
    logger.info(f"[SESSION CLEARED] chat_id={chat_id}")

# ==================== POLLING =========================
if __name__=="__main__":
    logger.info("Bot iniciado en modo POLLING")
    while True:
        try:
            bot.infinity_polling(timeout=60,long_polling_timeout=30,skip_pending=True)
        except Exception as e:
            logger.error(f"Error en polling: {e}")
            time.sleep(10)
