# handlers/client/__init__.py
# ❌ ELIMINAR esta línea:
# from .worker import flow  # Primero worker

# ✅ SOLO importar lo que existe en client/
from .flow import flow
from . import search
from . import callbacks
