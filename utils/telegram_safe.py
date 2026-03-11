from config import logger, get_bot
from telebot import types

bot = get_bot()


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
            text=text,
            chat_id=chat_id,
            message_id=message_id,
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


def answer_callback_safe(bot, callback_id, text=None, alert=False):
    try:
        return bot.answer_callback_query(
            callback_query_id=callback_id,
            text=text,
            show_alert=alert
        )
    except Exception as e:
        logger.error(f"[CALLBACK ERROR] {e}")
        return None


# ===============================
# REMOVE KEYBOARD
# ===============================

def remove_keyboard(chat_id, text="Procesando..."):
    try:
        bot.send_message(
            chat_id,
            text,
            reply_markup=types.ReplyKeyboardRemove()
        )
    except Exception as e:
        logger.error(f"[REMOVE_KB ERROR] {e}")
