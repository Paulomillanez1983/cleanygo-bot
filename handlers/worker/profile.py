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

# ==================== CONECTARSE / DESCONECTARSE ====================
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

# ==================== VER PERFIL ====================
@bot.callback_query_handler(func=lambda c: c.data == "worker_profile")
def handle_worker_profile(call):
    chat_id = call.message.chat.id
    worker = db_execute("SELECT * FROM workers WHERE chat_id = ?", (str(chat_id),), fetch_one=True)
    if not worker:
        bot.answer_callback_query(call.id, "❌ Perfil no encontrado.", show_alert=True)
        return

    bot.answer_callback_query(call.id)  # Quita la “carga” del botón
    # Mostramos la info principal del trabajador
    info_text = (
        f"{Icons.USER} <b>Mi Perfil</b>\n\n"
        f"Nombre: {worker[1]}\n"
        f"Teléfono: {worker[2]}\n"
        f"DNI: {worker[4]}\n"
        f"Disponible: {'Sí' if worker[3] else 'No'}\n"
        f"Lat/Lon: {worker[5] or 'No definido'}/{worker[6] or 'No definido'}\n"
        f"Última actualización: {worker[7] or 'No definida'}"
    )
    bot.send_message(chat_id, info_text, parse_mode="HTML")

# ==================== PRECIOS (Opcional ver precios) ====================
@bot.callback_query_handler(func=lambda c: c.data == "worker_prices")
def handle_worker_prices(call):
    chat_id = call.message.chat.id
    services = db_execute("SELECT service_id, precio FROM worker_services WHERE chat_id=?", (str(chat_id),), fetch_all=True)
    if not services:
        bot.answer_callback_query(call.id, "❌ No hay servicios registrados.", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    text = f"{Icons.MONEY} <b>Mis Precios</b>\n\n"
    for svc_id, precio in services:
        svc_name = SERVICES.get(svc_id, {}).get("name", svc_id)
        text += f"{Icons.BULLET} {svc_name}: ${precio}/hora\n"
    bot.send_message(chat_id, text, parse_mode="HTML")

# ==================== UBICACIÓN ====================
@bot.callback_query_handler(func=lambda c: c.data == "worker_location")
def handle_worker_location(call):
    chat_id = call.message.chat.id
    worker = db_execute("SELECT lat, lon FROM workers WHERE chat_id=?", (str(chat_id),), fetch_one=True)
    if not worker or not worker[0] or not worker[1]:
        bot.answer_callback_query(call.id, "❌ Ubicación no registrada.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    bot.send_location(chat_id, latitude=worker[0], longitude=worker[1])
