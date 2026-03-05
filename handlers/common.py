from config import bot, logger
from models.user_state import clear_state, set_state, UserState
from utils.icons import Icons
from utils.keyboards import get_role_keyboard
from database import db_execute

def send_safe(chat_id, text, reply_markup=None, parse_mode="HTML"):
"""Envía mensaje de forma segura"""
try:
return bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
except Exception as e:
logger.error(f"Error sending to {chat_id}: {e}")
return None

def edit_safe(chat_id, message_id, text, reply_markup=None):
"""Edita mensaje de forma segura"""
try:
return bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup, parse_mode="HTML")
except Exception as e:
logger.error(f"Error editing message {message_id}: {e}")
return None

def delete_safe(chat_id, message_id):
"""Elimina mensaje de forma segura"""
try:
bot.delete_message(chat_id, message_id)
except:
pass

def remove_keyboard(chat_id, text=None):
"""Elimina el teclado reply"""
from telebot import types
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

==================== HANDLERS COMUNES ====================

@bot.message_handler(commands=['start'])
def cmd_start(message):
chat_id = message.chat.id
clear_state(chat_id)

welcome_text = f"""

{Icons.WAVE} <b>¡Bienvenido a CleanyGo!</b>

Conectamos personas que necesitan servicios con profesionales confiables cerca de ti.

<b>¿Qué necesitás hacer?</b>
"""

send_safe(chat_id, welcome_text, get_role_keyboard())  
set_state(chat_id, UserState.SELECTING_ROLE)

@bot.message_handler(commands=['cancel'])
def cmd_cancel(message):
from telebot import types
chat_id = message.chat.id
clear_state(chat_id)
remove_keyboard(chat_id, f"{Icons.SUCCESS} Cancelado. Usá /start para comenzar de nuevo.")

@bot.message_handler(commands=['ayuda', 'help'])
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
send_safe(message.chat.id, text)
