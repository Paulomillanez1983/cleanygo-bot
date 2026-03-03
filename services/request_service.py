from database import db_execute
import time

def create_request(client_chat_id: str, service_id: str, hora: str, 
                 lat: float, lon: float, status: str = 'searching'):
    """Crea una nueva solicitud"""
    result = db_execute(
        """INSERT INTO requests (client_chat_id, service_id, hora, lat, lon, status) 
           VALUES (?, ?, ?, ?, ?, ?)""",
        (str(client_chat_id), service_id, hora, lat, lon, status),
        commit=True
    )
    
    if result is not None:
        return db_execute("SELECT last_insert_rowid()", fetch_one=True)[0]
    return None

def get_request(request_id: int):
    """Obtiene una solicitud por ID"""
    return db_execute(
        "SELECT * FROM requests WHERE id = ?", 
        (request_id,), 
        fetch_one=True
    )

def update_request_status(request_id: int, status: str, worker_chat_id: str = None):
    """Actualiza estado de una solicitud"""
    if worker_chat_id:
        return db_execute(
            """UPDATE requests SET status = ?, worker_chat_id = ?, accepted_at = ? 
               WHERE id = ?""",
            (status, str(worker_chat_id), int(time.time()), request_id),
            commit=True
        )
    return db_execute(
        "UPDATE requests SET status = ? WHERE id = ?",
        (status, request_id),
        commit=True
    )

def assign_worker_to_request(request_id: int, worker_chat_id: str):
    """Asigna un trabajador a una solicitud"""
    return db_execute(
        """UPDATE requests 
           SET worker_chat_id = ?, status = 'assigned', accepted_at = ? 
           WHERE id = ?""",
        (str(worker_chat_id), int(time.time()), request_id),
        commit=True
    )
