from config import bot, logger
from models.user_state import clear_state, set_state, UserState
from utils.icons import Icons
from utils.keyboards import get_role_keyboard
from database import db_execute
from telebot import types


# ==================== UTILIDADES ====================

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
        logger.error(f"[SEND ERROR] chat_id={chat_id} error={e}")
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
        logger.error(f"[EDIT ERROR] message_id={message_id} error={e}")
        return None


def delete_safe(chat_id, message_id):
    """Elimina mensaje de forma segura"""
    try:
        bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.warning(f"[DELETE ERROR] message_id={message_id} error={e}")


def remove_keyboard(chat_id, text=None):
    """Elimina el teclado reply"""
    markup = types.ReplyKeyboardRemove(selective=False)

    if text and text.strip():
        return send_safe(chat_id, text, markup)

    return None


def format_price(price):
    """Formatea un precio numérico a string legible"""
    try:
        price = float(price)
        return f"${price:,.0f}".replace(",", ".")
    except (ValueError, TypeError):
        return f"${price}"


# ==================== HANDLERS COMUNES ====================

@bot.message_handler(commands=["start"])
def cmd_start(message):

    chat_id = message.chat.id

    logger.info(f"/start recibido de {chat_id}")

    clear_state(chat_id)

    welcome_text = (
        f"{Icons.WAVE} <b>¡Bienvenido a CleanyGo!</b>\n\n"
        "Conectamos personas que necesitan servicios con profesionales confiables cerca de ti.\n\n"
        "<b>¿Qué necesitás hacer?</b>"
    )

    send_safe(
        chat_id,
        welcome_text,
        reply_markup=get_role_keyboard()
    )

    set_state(chat_id, UserState.SELECTING_ROLE)


@bot.message_handler(commands=["cancel"])
def cmd_cancel(message):

    chat_id = message.chat.id

    logger.info(f"/cancel recibido de {chat_id}")

    clear_state(chat_id)

    remove_keyboard(
        chat_id,
        f"{Icons.SUCCESS} Cancelado. Usá /start para comenzar de nuevo."
    )


@bot.message_handler(commands=["ayuda", "help"])
def cmd_help(message):

    chat_id = message.chat.id

    logger.info(f"/help recibido de {chat_id}")

    text = (
        f"{Icons.INFO} <b>Ayuda de CleanyGo</b>\n\n"
        "<b>Para Clientes:</b>\n"
        "/start - Solicitar un servicio\n"
        "/cancel - Cancelar solicitud actual\n\n"
        "<b>Para Profesionales:</b>\n"
        "/start - Registrarte o ver panel\n"
        "/online - Activar disponibilidad\n"
        "/offline - Pausar notificaciones\n"
        "/ubicacion - Cambiar ubicación\n"
        "/precios - Modificar tarifas\n\n"
        "<b>Soporte:</b>\n"
        "@soporte_cleanygo"
    )

    send_safe(chat_id, text)
