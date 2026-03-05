# wsgi.py
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info("wsgi.py cargado")

from main import app

logger.info("Flask app importada correctamente desde main.py")
