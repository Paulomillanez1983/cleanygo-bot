import os
import logging
from telebot import TeleBot

# ---------------- LOGGING ----------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# ---------------- VARIABLES ----------------
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")  # Soporta ambos nombres
DB_FILE = "cleanygo_ux.db"

# ---------------- BOT (Lazy Initialization) ----------------
_bot_instance = None

def get_bot():
    """Obtiene instancia del bot, inicializándola si es necesario"""
    global _bot_instance
    if _bot_instance is None:
        token = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            raise RuntimeError("BOT_TOKEN no definido. Configúralo en Railway Variables.")
        _bot_instance = TeleBot(token, parse_mode="HTML")
        logger.info("Bot inicializado correctamente")
    return _bot_instance

# Compatibilidad hacia atrás (opcional, para código que usa `bot` directamente)
bot = None
if TOKEN:
    bot = TeleBot(TOKEN, parse_mode="HTML")
    logger.info("Bot inicializado en importación")
else:
    logger.warning("BOT_TOKEN no disponible en importación - se inicializará lazy")
