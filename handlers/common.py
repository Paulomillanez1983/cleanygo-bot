from models.user_state import clear_state, set_state, UserState
from utils.icons import Icons
from utils.keyboards import get_role_keyboard
from config import logger
from telebot.types import ReplyKeyboardRemove

================= SAFE MESSAGES =================

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

def remove_keyboard():
return ReplyKeyboardRemove()

================= HANDLERS =================

def register_handlers(bot):

# ================= START =================

@bot.message_handler(commands=["start"])
def cmd_start(message):

    chat_id = message.chat.id
    clear_state(chat_id)

    welcome_text = f"""

{Icons.WAVE} <b>¡Bienvenido a CleanyGo!</b>

Conectamos personas que necesitan servicios con profesionales confiables cerca de ti.

<b>¿Qué necesitás hacer?</b>
"""

    send_safe(
        bot,
        chat_id,
        welcome_text,
        reply_markup=get_role_keyboard()
    )

    set_state(chat_id, UserState.SELECTING_ROLE)

    logger.info(f"[START] Usuario inició bot | chat_id={chat_id}")


# ================= CANCEL =================

@bot.message_handler(commands=["cancel"])
def cmd_cancel(message):

    chat_id = message.chat.id
    clear_state(chat_id)

    send_safe(
        bot,
        chat_id,
        f"{Icons.SUCCESS} Cancelado. Usá /start para comenzar de nuevo."
    )

    logger.info(f"[CANCEL] Flujo cancelado | chat_id={chat_id}")


# ================= HELP =================

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
/ubicacion - Cambiar ubicación
/precios - Modificar tarifas

<b>Soporte:</b>
@soporte_cleanygo
"""

    send_safe(
        bot,
        message.chat.id,
        text
    )


# ================= MENU PRINCIPAL =================

@bot.message_handler(func=lambda message: True, content_types=["text"])
def handle_main_menu(message):

    chat_id = message.chat.id
    text = message.text.strip().lower()

    logger.info(f"[MENU] Texto recibido: {text} | chat_id={chat_id}")

    # Cliente
    if "necesito un servicio" in text:
        from handlers.client.flow import start_client_flow
        start_client_flow(message)
        return

    # Trabajador
    if "quiero trabajar" in text:
        from handlers.worker.main import show_worker_menu
        show_worker_menu(message)
        return

    # Ayuda
    if "ayuda" in text:
        cmd_help(message)
        return

    # Texto desconocido
    send_safe(
        bot,
        chat_id,
        f"{Icons.INFO} No entendí esa opción. Usá el menú o escribí /start."
    )
