import os
import logging
from telebot import TeleBot

# ==================== CONFIGURACIÓN ====================
TOKEN = os.getenv("BOT_TOKEN", "8534288619:AAG1i5-PdjUABerTQCp_y84XubBfVNJ34FU")
DB_FILE = "cleanygo_ux.db"

# Inicializar bot
bot = TeleBot(TOKEN, parse_mode="HTML")

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
