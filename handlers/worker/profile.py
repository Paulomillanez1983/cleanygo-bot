from telebot import types
from config import bot
from models.user_state import set_state, UserState
from utils.icons import Icons
from handlers.common import send_safe
from database import db_execute
from models.services_data import SERVICES

# ==================== MENÚ PRINCIPAL ====================
def show_worker_menu(chat_id: str, worker_data):
    is_online = worker_data[3] if len(worker_data) > 3 else 0
    status_icon = Icons.ONLINE if is_online else Icons.OFFLINE
    status_text = "En línea" if is_online else "Desconectado"

    text = (
        f"{Icons.BRIEFCASE} <b>Panel de Profesional</b>\n\n"
        f"{status_icon} <b>Estado:</b> {status_text}\n"
        f"⭐ <b>Rating:</b> {worker_data[7] if len(worker_data) > 7 else 5.0}/5.0\n\n"
        f"<b>¿Qué querés hacer?</b>"
    )

    markup = types.InlineKeyboardMarkup(row_width=2)

    # Conectar / Desconectar
    markup.add(
        types.InlineKeyboardButton(f"{Icons.ONLINE if not is_online else Icons.OFFLINE} {'Conectarme' if not is_online else 'Desconectarme'}",
                                   callback_data="worker_online" if not is_online else "worker_offline")
    )

    # Funciones principales
    markup.add(
        types.InlineKeyboardButton(f"{Icons.USER} Mi Perfil", callback_data="worker_profile"),
        types.InlineKeyboardButton(f"{Icons.MONEY} Precios", callback_data="worker_prices"),
        types.InlineKeyboardButton(f"{Icons.LOCATION} Ubicación", callback_data="worker_location")
    )

    # Servicio activo / iniciar servicio
    active_request = db_execute(
        "SELECT id, status FROM requests WHERE worker_id=? AND status IN ('accepted','in_progress')", 
        (str(chat_id),), fetch_one=True
    )
    if active_request:
        req_id, status = active_request
        if status == "accepted":
            markup.add(types.InlineKeyboardButton("🚀 Iniciar Servicio", callback_data="start_service"))
        elif status == "in_progress":
            markup.add(types.InlineKeyboardButton("🟢 Servicio en progreso", callback_data="in_progress_disabled"))

    send_safe(chat_id, text, markup)


# ==================== CONECTARSE / DESCONECTARSE ====================
@bot.callback_query_handler(func=lambda c: c.data in ["worker_online", "worker_offline"])
def handle_worker_toggle(call):
    chat_id = call.message.chat.id
    new_status = 1 if call.data == "worker_online" else 0
    db_execute("UPDATE workers SET disponible = ? WHERE chat_id = ?", (new_status, str(chat_id)), commit=True)
    bot.answer_callback_query(call.id, "✅ Estado actualizado" if new_status else "😴 Ahora estás desconectado")
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
    bot.answer_callback_query(call.id)

    info_text = (
        f"{Icons.USER} <b>Mi Perfil</b>\n\n"
        f"Nombre: {worker[1]}\n"
        f"Teléfono: {worker[2]}\n"
        f"DNI: {worker[4]}\n"
        f"Disponible: {'Sí' if worker[3] else 'No'}\n"
        f"Lat/Lon: {worker[5] or 'No definido'}/{worker[6] or 'No definido'}\n"
        f"Última actualización: {worker[7] or 'No definida'}"
    )

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✏️ Editar Nombre", callback_data="edit_name"),
        types.InlineKeyboardButton("✏️ Editar Teléfono", callback_data="edit_phone"),
        types.InlineKeyboardButton("💰 Editar Precios", callback_data="edit_prices")
    )
    send_safe(chat_id, info_text, markup)


# ==================== EDITAR PERFIL ====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_"))
def handle_edit_profile(call):
    chat_id = call.message.chat.id
    action = call.data

    if action == "edit_name":
        set_state(chat_id, "WORKER_EDITING_NAME")
        bot.send_message(chat_id, "✏️ Ingresá tu nuevo nombre:", reply_markup=types.ReplyKeyboardRemove())
    elif action == "edit_phone":
        set_state(chat_id, "WORKER_EDITING_PHONE")
        bot.send_message(chat_id, "✏️ Ingresá tu nuevo teléfono:", reply_markup=types.ReplyKeyboardRemove())
    elif action == "edit_prices":
        worker = db_execute("SELECT * FROM workers WHERE chat_id=?", (str(chat_id),), fetch_one=True)
        if worker:
            from handlers.worker.prices import ask_next_price
            set_state(chat_id, "WORKER_ENTERING_PRICE")
            ask_next_price(chat_id)
    bot.answer_callback_query(call.id)


# ==================== PRECIOS ====================
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

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✏️ Editar Precios", callback_data="edit_prices"))
    send_safe(chat_id, text, markup)


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


# ==================== INICIAR SERVICIO ====================
@bot.callback_query_handler(func=lambda c: c.data == "start_service")
def handle_start_service(call):
    chat_id = call.message.chat.id
    request = db_execute(
        "SELECT id, client_id, lat, lon FROM requests WHERE worker_id=? AND status='accepted'",
        (str(chat_id),), fetch_one=True
    )
    if not request:
        bot.answer_callback_query(call.id, "❌ No tenés un servicio activo.", show_alert=True)
        return

    request_id, client_id, lat, lon = request
    db_execute("UPDATE requests SET status='in_progress' WHERE id=?", (request_id,), commit=True)
    bot.answer_callback_query(call.id, "✅ Servicio iniciado. Enviando ubicación al cliente...")

    bot.send_location(client_id, latitude=lat, longitude=lon)
    set_state(chat_id, UserState.WORKER_IN_SERVICE, {"request_id": request_id})
