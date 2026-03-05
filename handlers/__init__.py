"""
Módulo de handlers - Punto de entrada principal.
Evita imports circulares importando solo lo necesario.
VERSIÓN CORREGIDA: Importa main.py para handlers de callbacks del worker
"""

# Handlers comunes (sin dependencias problemáticas)
from . import common

# Handlers de worker - importar desde el subpaquete worker
from .worker import jobs
from .worker import profile
from .worker import main  # ✅ AGREGADO: Importar main para handlers de callbacks

# Handlers de client - importar desde el subpaquete client
from .client import search
from .client import callbacks
# flow se importa lazy cuando se necesita para evitar ciclos

# No importar nada más aquí - los handlers se registran vía decoradores @bot.message_handler
