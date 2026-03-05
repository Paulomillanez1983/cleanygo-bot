# handlers/worker/main.py
from telebot import types
from config import bot
from handlers.common import send_safe
from utils.icons import Icons

def show_worker_menu(worker_id, worker_data, extra_buttons=None):
    """
    Muestra el menú principal del trabajador.
    
    Parámetros:
    - worker_id: chat_id del trabajador
    - worker_data: diccionario con datos del trabajador
    - extra_buttons: lista opcional de InlineKeyboardButton adicionales
    """
    request_id = worker_data.get("request_id", 0)
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

    # Botón de iniciar servicio solo si hay un request activo
    if request_id:
        markup.add(
            types.InlineKeyboardButton(f"{Icons.PLAY} Iniciar servicio", callback_data=f"start_job:{request_id}")
        )

    # Agregar botones extra si se pasaron
    if extra_buttons and isinstance(extra_buttons, list):
        for btn in extra_buttons:
            markup.add(btn)

    send_safe(worker_id, text, markup)
