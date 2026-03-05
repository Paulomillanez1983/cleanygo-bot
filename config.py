import os
import logging

# ==================== LOGGING ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== VARIABLES ====================
# Token del bot (Railway o local)
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")

# Archivo de la base de datos SQLite
DB_FILE = "cleanygo_ux.db"

# ==================== BOT ====================
# Se inicializa luego en bot.py y se inyecta acá
bot = None
