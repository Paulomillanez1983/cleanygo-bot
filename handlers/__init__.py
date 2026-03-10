"""
Inicialización de handlers - Carga todos los módulos para registrar handlers
"""
import logging

logger = logging.getLogger(__name__)

def register_all_handlers():
    """Registra todos los handlers del bot"""
    logger.info("🔄 Registrando handlers...")
    
    # Importar en orden específico para evitar dependencias circulares
    # 1. Comunes primero
    from handlers import common
    
    # 2. Cliente
    from handlers.client import flow
    from handlers.client import callbacks
    
    # 3. Worker
    from handlers.worker import flow as worker_flow
    from handlers.worker import jobs
    
    logger.info("✅ Todos los handlers registrados")
