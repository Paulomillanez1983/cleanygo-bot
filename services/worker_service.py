# services/worker_service.py
def find_available_workers(service_id, lat, lon, hora_completa):
    """
    Devuelve:
      - lista de workers
      - status: "success" / "no_workers_online" / "workers_far" / "workers_busy"
      - extra: opcional, puede ser lista de trabajadores ocupados
    """
    # MOCK: 1 trabajador disponible
    workers = [
        [123456789, "Juan Pérez", lat+0.001, lon+0.001, 5.0, 500, 0.5]
    ]
    status = "success"
    extra = None
    return workers, status, extra
