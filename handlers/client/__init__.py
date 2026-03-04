# handlers/client/__init__.py
"""
Módulo de handlers para clientes.
"""

# Dejar vacío o con imports mínimos que no causen ciclos
# Los handlers se registran automáticamente vía decoradores @bot.message_handler

# Exponer get_service_display para uso interno del módulo client
from .flow import get_service_display

# La variable flow se expone desde flow.py directamente
# from .flow import flow  # Solo si realmente se necesita fuera del módulo
