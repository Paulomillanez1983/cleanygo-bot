import threading
import time
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
    markup.add(
        types.InlineKeyboardButton(f"{Icons.ONLINE if not is_online else Icons.OFFLINE} {'Conectarme' if not is_online else 'Desconectarme'}",
                                   callback_data="worker_online" if not is_online else "worker_offline")
    )

    markup.add(
        types.InlineKeyboardButton(f"{Icons.USER} Mi Perfil", callback_data="worker_profile"),
        types.InlineKeyboardButton(f"{Icons.MONEY} Precios", callback_data="worker_prices"),
        types.InlineKeyboardButton(f"{Icons.LOCATION} Ubicación", callback_data="worker_location")
    )

    # Botón servicio activo / iniciar servicio
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


# ==================== INICIAR SERVICIO CON UBICACIÓN EN TIEMPO REAL ====================
def send_live_location(worker_id: str, client_id: str, interval=15):
    """
    Envía la ubicación cada `interval` segundos mientras el servicio esté activo.
    """
    while True:
        req = db_execute(
            "SELECT id, lat, lon, status FROM requests WHERE worker_id=? AND status='in_progress'", 
            (str(worker_id),), fetch_one=True
        )
        if not req:
            break  # Servicio finalizado
        _, lat, lon, status = req
        if not lat or not lon:
            break
        try:
            bot.send_location(client_id, latitude=lat, longitude=lon)
        except Exception as e:
            print(f"Error enviando ubicación: {e}")
        time.sleep(interval)


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

    # Enviar ubicación inicial
    bot.send_location(client_id, latitude=lat, longitude=lon)

    # Guardar estado
    set_state(chat_id, UserState.WORKER_IN_SERVICE, {"request_id": request_id})

    # Iniciar thread de ubicación en tiempo real
    threading.Thread(target=send_live_location, args=(chat_id, client_id), daemon=True).start()
