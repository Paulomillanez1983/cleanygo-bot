# handlers/__init__.py
# Esto está bien si los subpaquetes no tienen circularidad
from .worker import flow as worker_flow
from .client import flow as client_flow
