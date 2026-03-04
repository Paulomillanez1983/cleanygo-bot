# handlers/worker/__init__.py
"""
Módulo de handlers para trabajadores/profesionales.
"""

# Importar módulos de worker
from . import jobs
from . import profile

# No importar desde client aquí - evita ciclos circulares
# Las funciones compartidas se importan lazy dentro de las funciones que las necesitan
