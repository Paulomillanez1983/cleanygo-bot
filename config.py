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
if not TOKEN:
    logger.error("❌ BOT_TOKEN no definido en las variables de entorno")
    raise RuntimeError("Configura BOT_TOKEN en Railway Variables o .env local")

# Directorio base del proyecto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Archivo de la base de datos SQLite unificado
DB_FILE = os.path.join(BASE_DIR, "cleanygo_ux.db")

# ==================== BOT ====================
# Se inicializa luego en bot.py y se inyecta acá
bot = None
