# handlers/worker/main.py
from telebot import types
from config import bot
from handlers.common import send_safe
from utils.icons import Icons

def show_worker_menu(worker_id, worker_data):
    request_id = worker_data.get("request_id")
    service = worker_data.get("service_id", "Servicio")
    hora = worker_data.get("hora", "Hora no definida")
    client_id = worker_data.get("client_id", "Cliente desconocido")

    text = f"""
{Icons.INFO} Menú de trabajo

Servicio: {service}
Hora: {hora}
Cliente: {client_id}
"""

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(f"{Icons.PLAY} Iniciar servicio", callback_data=f"start_job:{request_id}")
    )

    send_safe(worker_id, text, markup)
