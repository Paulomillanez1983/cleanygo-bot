# services/request_service.py

def create_request(client_id, service_id, hora, lat, lon, status):
    # lógica para crear la solicitud en la DB
    return 1  # por ejemplo, devolver request_id

def get_request(request_id):
    # lógica para obtener la solicitud
    return {
        "request_id": request_id,
        "client_chat_id": 12345,
        "service_id": "limpieza",
        "hora": "10:00 AM",
        "status": "searching"
    }

def assign_worker_to_request_safe(request_id, worker_id):
    # lógica para asignar trabajador de forma segura
    return True

def update_request_status(request_id, status):
    # actualizar estado en la DB
    pass

def find_available_workers(service_id, lat, lon, hora):
    # devolver lista de trabajadores o status
    return [], "no_workers_online", None
