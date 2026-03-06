"""
Database module - Re-exporta desde config.py para compatibilidad.
NO contiene lógica de inicialización propia.
"""

# Importar TODO desde config.py para mantener compatibilidad
from config import (
    # Inicialización
    init_db,
    
    # Conexión
    get_db_connection,
    DB_FILE,
    BASE_DIR,
    
    # Utilidades
    db_execute,
    logger,
    Icons,
    
    # Sesiones (funciones)
    get_session,
    set_state,
    update_data,
    clear_state,
    
    # Sesiones (clase)
    UserSession,
    
    # Workers
    ensure_worker_exists,
    
    # Notificaciones
    Notifier,
    notify_worker,
    broadcast_to_workers,
    notify_client,
    
    # Bot
    inject_bot,
    get_bot,
    TOKEN,
)

# No hay código propio aquí - todo viene de config.py
# Esto evita la doble inicialización y race conditions
