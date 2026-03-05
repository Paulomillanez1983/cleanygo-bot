import os
import logging
from telebot import TeleBot

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")  # ✅ no rompe si no existe

bot = None

if TOKEN:
    bot = TeleBot(TOKEN, parse_mode="HTML")
    logger.info("Bot inicializado correctamente")
else:
    logger.warning("BOT_TOKEN no definido (probablemente en build phase)")
