from config import bot, logger
from models.user_state import clear_state, set_state, UserState
from utils.icons import Icons
from utils.keyboards import get_role_keyboard

def send_safe(chat_id, text, reply_markup=None, parse_mode="HTML"):
    """Envía mensaje de forma segura con log de errores"""
    try:
        return bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"[SEND_SAFE ERROR] chat_id={chat_id} | error={e}")
        return None

@bot.message_handler(commands=['start'])
def cmd_start(message):
    chat_id = message.chat.id
    logger.info(f"[HANDLER /start] Recibido mensaje de {chat_id}: {message.text}")
    clear_state(chat_id)

    # Escape seguro de HTML
    welcome_text = f"{Icons.WAVE} <b>¡Bienvenido a CleanyGo!</b>\n\nConectamos personas que necesitan servicios con profesionales confiables cerca de ti.\n\n<b>¿Qué necesitás hacer?</b>"

    result = send_safe(chat_id, welcome_text, get_role_keyboard())
    if result is None:
        logger.error(f"[HANDLER /start] Error enviando mensaje a {chat_id}")

    set_state(chat_id, UserState.SELECTING_ROLE)
