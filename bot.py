#!/usr/bin/env python3
"""
CleanyGo Bot - Punto de entrada principal
"""

import os
import signal
import sys
import time
from config import bot, logger
from utils.icons import Icons

# Inicializar base de datos primero
from database import init_db
init_db()

# Importar handlers (registran sus decorators con el bot)
from handlers import common

# Handlers de cliente
from handlers.client import flow as client_flow
from handlers.client import search
from handlers.client import callbacks as client_callbacks

# Handlers de trabajador
from handlers.worker import flow as worker_flow
from handlers.worker import jobs
from handlers.worker import profile


def signal_handler(signum, frame):
    """Maneja señales de terminación graceful"""
    logger.info(f"{Icons.INFO} Señal recibida: {signum}. Cerrando bot...")
    bot.stop_polling()
    sys.exit(0)


# Registrar manejadores de señales
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


if __name__ == "__main__":
    logger.info(f"{Icons.SUCCESS} Bot CleanyGo iniciado en modo POLLING")
    
    # Esperar un poco si hay otro contenedor corriendo (evita conflicto 409)
    time.sleep(2)

    try:
        # Eliminar webhook si existe
        bot.remove_webhook()
        logger.info("Webhook eliminado correctamente")

        # Intentar polling con reintentos
        retry_count = 0
        max_retries = 3
        
        while retry_count < max_retries:
            try:
                logger.info(f"Intento {retry_count + 1}/{max_retries} de polling...")
                
                bot.infinity_polling(
                    timeout=60,
                    long_polling_timeout=60,
                    skip_pending=True,
                    none_stop=False  # Permite que se detenga con señales
                )
                
                # Si llega aquí, el polling terminó normalmente
                break
                
            except Exception as e:
                retry_count += 1
                logger.error(f"Error en polling: {e}")
                
                if retry_count < max_retries:
                    wait_time = 5 * retry_count
                    logger.info(f"Reintentando en {wait_time} segundos...")
                    time.sleep(wait_time)
                else:
                    logger.error("Máximo de reintentos alcanzado")
                    raise

    except Exception as e:
        logger.error(f"Error crítico: {e}")
        sys.exit(1)
