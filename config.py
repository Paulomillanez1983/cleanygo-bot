import os
import logging
from telebot import TeleBot

TOKEN = os.environ["BOT_TOKEN"]  # sin fallback

bot = TeleBot(TOKEN, parse_mode="HTML")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)
