"""Common handlers - Start, cancel, help, menú principal"""

import logging
from telebot import types

from config import logger, get_bot, set_state, update_data, get_data, clear_state, get_session
from models.states import UserState
from utils.icons import Icons
from utils.keyboards import get_role_keyboard
from utils.telegram_safe import send_safe, edit_safe, delete_safe, remove_keyboard
bot = get_bot()
logger = logging.getLogger(__name__)


# ==================== HANDLERS COMUNES ====================

@bot.message_handler(commands=["start"])
def cmd_start(message):

    chat_id = message.chat.id

    clear_state(chat_id)

    welcome_text = f"""
{Icons.WAVE} <b>¡Bienvenido a CleanyGo!</b>

Conectamos personas que necesitan servicios con profesionales confiables cerca de ti.

<b>¿Qué necesitás hacer?</b>
"""

    send_safe(chat_id, welcome_text, get_role_keyboard())

    set_state(chat_id, UserState.SELECTING_ROLE.value)

    logger.info(f"[START] Usuario inició bot | chat_id={chat_id}")


@bot.message_handler(commands=["cancel"])
def cmd_cancel(message):

    chat_id = message.chat.id

    clear_state(chat_id)

    send_safe(
        chat_id,
        f"{Icons.SUCCESS} Cancelado. Usá /start para comenzar de nuevo."
    )

    logger.info(f"[CANCEL] Flujo cancelado | chat_id={chat_id}")


@bot.message_handler(commands=["help", "ayuda"])
def cmd_help(message):

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

    send_safe(message.chat.id, text)


# ==================== MENU PRINCIPAL ====================

@bot.message_handler(
    func=lambda message: get_session(message.chat.id).get("state") == UserState.SELECTING_ROLE.value,
    content_types=["text"]
)
def handle_main_menu(message):
    chat_id = message.chat.id
    text = (message.text or "").strip().lower()

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
        chat_id,
        f"{Icons.INFO} No entendí esa opción. Usá el menú o escribí /start."
    )


