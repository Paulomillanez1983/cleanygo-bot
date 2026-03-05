# handlers/worker/main.py
from config import bot
from handlers.common import send_safe
from utils.icons import Icons

def show_worker_menu(worker_id, worker_data):
    text = f"{Icons.INFO} Menú actualizado para tu trabajo"
    send_safe(worker_id, text)
