from telebot import types
from config import bot
from models.user_state import set_state, UserState
from utils.icons import Icons
from handlers.common import send_safe, edit_safe
from database import db_execute

def show_worker_menu(chat_id: str, worker_data):
    """Muestra menú para trabajador ya registrado"""
    is_online = worker_data[3] if len(worker_data) > 3 else 0
    
    status_icon = Icons.ONLINE if is_online else Icons.OFFLINE
    status_text = "En línea" if is_online else "Desconectado"
    
    text = f"""
{Icons.BRIEFCASE} <b>Panel de Profesional</b>

{status_icon} <b>Estado:</b> {status_text}
⭐ <b>Rating:</b> {worker_data[7] if len(worker_data) > 7 else 5.0}/5.0

<b>¿Qué querés hacer?</b>
    """
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    if is_online:
        markup.add(types.InlineKeyboardButton(f"{Icons.OFFLINE} Desconectarme", callback_data="worker_offline"))
    else:
        markup.add(types.InlineKeyboardButton(f"{Icons.ONLINE} Conectarme", callback_data="worker_online"))
    
    markup.add(
        types.InlineKeyboardButton(f"{Icons.LOCATION} Ubicación", callback_data="worker_location"),
        types.InlineKeyboardButton(f"{Icons.MONEY} Precios", callback_data="worker_prices"),
        types.InlineKeyboardButton(f"{Icons.USER} Mi Perfil", callback_data="worker_profile")
    )
    
    send_safe(chat_id, text, markup)

@bot.callback_query_handler(func=lambda c: c.data == "worker_online")
def handle_worker_online(call):
    chat_id = call.message.chat.id
    db_execute("UPDATE workers SET disponible = 1 WHERE chat_id = ?", (str(chat_id),), commit=True)
    bot.answer_callback_query(call.id, "✅ Ahora estás en línea")
    
    worker = db_execute("SELECT * FROM workers WHERE chat_id = ?", (str(chat_id),), fetch_one=True)
    show_worker_menu(chat_id, worker)

@bot.callback_query_handler(func=lambda c: c.data == "worker_offline")
def handle_worker_offline(call):
    chat_id = call.message.chat.id
    db_execute("UPDATE workers SET disponible = 0 WHERE chat_id = ?", (str(chat_id),), commit=True)
    bot.answer_callback_query(call.id, "😴 Ahora estás desconectado")
    
    worker = db_execute("SELECT * FROM workers WHERE chat_id = ?", (str(chat_id),), fetch_one=True)
    show_worker_menu(chat_id, worker)
