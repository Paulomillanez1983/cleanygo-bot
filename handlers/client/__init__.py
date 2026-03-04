# handlers/client/__init__.py
"""
Módulo de handlers para clientes.
"""

# Importar el módulo flow completo (no solo 'flow')
# Esto permite acceder a flow.flow, flow.get_service_display, etc.
from . import flow
from . import search
from . import callbacks

# Exportar get_service_display para uso interno del módulo client
# (worker/jobs.py debe importarlo directamente desde flow)
from .flow import get_service_display
