#!/usr/bin/env python3
"""
CleanyGo Bot - Punto de entrada principal
"""

# Inicializar base de datos primero
from database import init_db
init_db()

# Importar handlers (registran sus decorators con el bot)
from handlers import common

# Handlers de cliente
from handlers.client import flow as client_flow
from handlers.client import search
from handlers.client import callbacks as client_callbacks

# Handlers de trabajador (flow.py tiene TODO el registro)
from handlers.worker import flow as worker_flow      # ✅ Registro completo
from handlers.worker import jobs                     # ✅ Aceptar/rechazar trabajos
from handlers.worker import profile                  # ✅ Menú del trabajador

from config import bot, logger
from utils.icons import Icons

if __name__ == "__main__":
    logger.info(f"{Icons.SUCCESS} Bot CleanyGo iniciado en modo modular")
    
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except Exception as e:
        logger.error(f"Error crítico: {e}")
