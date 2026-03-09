"""
Common handlers - Start, cancel, help, menú principal
"""
import asyncio  # <-- Agregado para compatibilidad
import logging
from telebot import types

# CORREGIDO: Importar funciones desde config y UserState desde models.states
from config import logger, get_bot, notify_worker, set_state, update_data, get_data, clear_state
from models.states import UserState
from models.services_data import SERVICES
from utils.icons import Icons
from utils.keyboards import get_role_keyboard

# NUEVO: obtener instancia del bot
bot = get_bot()

logger = logging.getLogger(__name__)


# ==================== HANDLERS COMUNES ====================

@bot.message_handler(commands=["start"])
def cmd_start(message):
    """Handler de inicio"""
    chat_id = str(message.chat.id)
    
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
    """Cancela cualquier flujo activo"""
    chat_id = str(message.chat.id)
    
    clear_state(chat_id)

    send_safe(
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

    send_safe(message.chat.id, text)


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
        chat_id,
        f"{Icons.INFO} No entendí esa opción. Usá el menú o escribí /start."
    )


# ==================== SAFE UTILS ====================

def send_safe(chat_id, text, reply_markup=None, parse_mode="HTML"):
    """Envía mensaje de forma segura"""
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


def edit_safe(chat_id, message_id, text, reply_markup=None):
    """Edita mensaje de forma segura"""
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


def delete_safe(chat_id, message_id):
    """Elimina mensaje de forma segura"""
    try:
        bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.error(f"[DELETE ERROR] {e} | message_id={message_id}")


def remove_keyboard(chat_id, text="Procesando..."):
    """Remueve teclado de forma segura"""
    try:
        bot.send_message(
            chat_id,
            text,
            reply_markup=types.ReplyKeyboardRemove()
        )
    except Exception as e:
        logger.error(f"[REMOVE_KB ERROR] {e}")
