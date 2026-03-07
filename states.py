from enum import Enum

class UserState(Enum):

    IDLE = "idle"
    SELECTING_ROLE = "selecting_role"

    # Worker
    WORKER_SELECTING_SERVICES = "worker_selecting_services"
    WORKER_ENTERING_PRICE = "worker_entering_price"
    WORKER_ENTERING_NAME = "worker_entering_name"
    WORKER_ENTERING_PHONE = "worker_entering_phone"
    WORKER_ENTERING_DNI = "worker_entering_dni"
    WORKER_SHARING_LOCATION = "worker_sharing_location"

    # Client
    CLIENT_SELECTING_SERVICE = "client_selecting_service"
    CLIENT_SELECTING_DATE = "client_selecting_date"
    CLIENT_SELECTING_TIME = "client_selecting_time"
    CLIENT_SHARING_LOCATION = "client_sharing_location"
    CLIENT_CONFIRMING = "client_confirming"
    CLIENT_WAITING_ACCEPTANCE = "client_waiting_acceptance"

    JOB_IN_PROGRESS = "job_in_progress"
