from config import logger

from config import logger

def send_safe(bot, chat_id, text, reply_markup=None, parse_mode="HTML"):
    try:
        return bot.send_message(
            chat_id,
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except Exception as e:
        logger.error(f"[SEND ERROR] {e} | ChatID: {chat_id}")
        return None


def edit_safe(bot, chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
    try:
        return bot.edit_message_text(
            text,
            chat_id,
            message_id,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except Exception as e:
        logger.error(f"[EDIT ERROR] {e} | MessageID: {message_id}")
        return None


def delete_safe(bot, chat_id, message_id):
    try:
        return bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.error(f"[DELETE ERROR] {e} | MessageID: {message_id}")
        return None
def edit_safe(bot, chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
"""
Edita un mensaje de forma segura
"""
try:
return bot.edit_message_text(
text,
chat_id,
message_id,
reply_markup=reply_markup,
parse_mode=parse_mode
)
except Exception as e:
logger.error(f"[EDIT ERROR] {e} | MessageID: {message_id}")
return None

def delete_safe(bot, chat_id, message_id):
"""
Elimina un mensaje sin romper el bot
"""
try:
return bot.delete_message(chat_id, message_id)
except Exception as e:
logger.error(f"[DELETE ERROR] {e} | MessageID: {message_id}")
return None

def answer_callback_safe(bot, callback_id, text=None, alert=False):
"""
Responde callbacks de botones inline sin romper el bot
"""
try:
return bot.answer_callback_query(
callback_id,
text=text,
show_alert=alert
)
except Exception as e:
logger.error(f"[CALLBACK ERROR] {e}")
return None
