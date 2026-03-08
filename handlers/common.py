import asyncio
import logging
from telebot import types, apihelper

from config import bot, logger, notify_client
from models.user_state import (
    set_state, update_data, get_data, get_session, clear_state, UserState
)
from models.services_data import SERVICES
from utils.icons import Icons
from utils.keyboards import (
    get_time_selector,
    get_location_keyboard,
    get_confirmation_keyboard,
    get_role_keyboard
)
from utils.telegram_safe import send_safe, edit_safe, delete_safe, remove_keyboard

logger = logging.getLogger(__name__)


# ==================== AUXILIARES ====================
def safe_json(data):
    if isinstance(data, dict):
        return {k: safe_json(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [safe_json(x) for x in data]
    elif isinstance(data, (str, int, float, type(None))):
        return data
    else:
        return str(data)


def debug_session(chat_id: str, label: str):
    try:
        session = get_session(chat_id)
        logger.info(f"[DEBUG {label}] chat_id={chat_id}, session={session}")
        return session
    except Exception as e:
        logger.error(f"[DEBUG {label}] ERROR: {e}")
        return {"state": "error", "data": {}}


def save_state_and_data(chat_id: str, state: UserState, data_updates: dict = None):
    chat_id = str(chat_id)
    if data_updates:
        update_data(chat_id, **safe_json(data_updates))
    set_state(chat_id, state.value)
    logger.info(f"[STATE] chat_id={chat_id} -> {state.value}")


def get_service_display(service_id: str, with_price: bool = False) -> str:
    svc = SERVICES.get(service_id, {})
    text = f"{svc.get('icon','🔹')} <b>{svc.get('name', service_id)}</b>"
    if with_price:
        # Evitar import circular
        from handlers.worker import jobs as worker_jobs
        price = worker_jobs.SERVICES_PRICES.get(service_id, {}).get("price", 0)
        text += f"\n<code>${price}</code>"
    return text


# ==================== HANDLERS COMUNES ====================

@bot.message_handler(commands=["start"])
def cmd_start(message):
    """Handler de inicio - Limpia estado y muestra menú principal"""
    chat_id = str(message.chat.id)
    
    # Limpiar estado usando el sistema unificado
    clear_state(chat_id)

    welcome_text = f"""
{Icons.WAVE} <b>¡Bienvenido a CleanyGo!</b>

Conectamos personas que necesitan servicios con profesionales confiables cerca de ti.

<b>¿Qué necesitás hacer?</b>
"""

    send_safe(bot, chat_id, welcome_text, get_role_keyboard())
    set_state(chat_id, UserState.SELECTING_ROLE.value)

    logger.info(f"[START] Usuario inició bot | chat_id={chat_id}")


@bot.message_handler(commands=["cancel"])
def cmd_cancel(message):
    """Cancela cualquier flujo activo"""
    chat_id = str(message.chat.id)
    
    clear_state(chat_id)

    send_safe(
        bot,
        chat_id,
        f"{Icons.SUCCESS} Cancelado. Usá /start para comenzar de nuevo."
    )

    logger.info(f"[CANCEL] Flujo cancelado | chat_id={chat_id}")


@bot.message_handler(commands=["help", "ayuda"])
def cmd_help(message):
    """Muestra ayuda"""
    text = f"""
{Icons.INFO} <b>Ayuda de CleanyGo</b>

<b>Para Clientes:</b>
/start - Solicitar un servicio
/cancel - Cancelar solicitud actual

<b>Para Profesionales:</b>
/start - Registrarte o ver panel
/online - Activar disponibilidad
/offline - Pausar notificaciones

<b>Soporte:</b>
@soporte_cleanygo
"""

    send_safe(bot, message.chat.id, text)


# ==================== MENU PRINCIPAL ====================

@bot.message_handler(
    func=lambda message: get_data(message.chat.id, "state") == UserState.SELECTING_ROLE.value,
    content_types=["text"]
)
def handle_main_menu(message):
    """
    Handler del menú principal.
    Solo se activa cuando el estado es SELECTING_ROLE.
    """
    chat_id = message.chat.id
    text = message.text.strip().lower()

    logger.info(f"[MENU] Texto recibido: {text} | chat_id={chat_id}")

    if "necesito" in text or "servicio" in text:
        from handlers.client.flow import start_client_flow
        start_client_flow(chat_id)
        return

    if "trabajar" in text:
        from handlers.worker.flow import start_worker_flow
        start_worker_flow(chat_id)
        return

    if "ayuda" in text:
        cmd_help(message)
        return

    send_safe(
        bot,
        chat_id,
        f"{Icons.INFO} No entendí esa opción. Usá el menú o escribí /start."
    )


# ==================== SAFE UTILS (movidos aquí para evitar circular imports) ====================

def send_safe(bot, chat_id, text, reply_markup=None, parse_mode="HTML"):
    try:
        return bot.send_message(
            chat_id,
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except Exception as e:
        logger.error(f"[SEND ERROR] {e} | chat_id={chat_id}")
        return None


def edit_safe(bot, chat_id, message_id, text, reply_markup=None):
    try:
        return bot.edit_message_text(
            text,
            chat_id,
            message_id,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"[EDIT ERROR] {e} | message_id={message_id}")
        return None


def delete_safe(bot, chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.error(f"[DELETE ERROR] {e} | message_id={message_id}")


def remove_keyboard(bot, chat_id, text="Procesando..."):
    try:
        bot.send_message(
            chat_id,
            text,
            reply_markup=types.ReplyKeyboardRemove()
        )
    except Exception as e:
        logger.error(f"[REMOVE_KB ERROR] {e}")
