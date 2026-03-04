# handlers/__init__.py
"""
Módulo de handlers - Punto de entrada principal.
Evita imports circulares importando solo lo necesario.
"""

# Handlers comunes (sin dependencias problemáticas)
from . import common

# Handlers de worker - importar módulos, no objetos flow
from .worker import jobs
from .worker import profile

# Handlers de client - importar módulos, no objetos flow
# Nota: Se importan como módulos para evitar inicialización circular
from .client import search
from .client import callbacks

# El flujo de client se importa lazy cuando se necesita
# from .client import flow  # No importar aquí - usar lazy import
