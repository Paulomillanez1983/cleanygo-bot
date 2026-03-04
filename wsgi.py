# wsgi.py
from bot import app  # importa tu Flask app

# Opcional: logging básico si falla import
import logging
logging.basicConfig(level=logging.INFO)
logging.info("wsgi.py cargado - app importada")
