from enum import Enum
from dataclasses import dataclass, field
from typing import Dict
import time

class UserState(Enum):
    IDLE = "idle"
    SELECTING_ROLE = "selecting_role"
    WORKER_SELECTING_SERVICES = "worker_selecting_services"
    WORKER_ENTERING_PRICE = "worker_entering_price"
    WORKER_ENTERING_NAME = "worker_entering_name"
    WORKER_ENTERING_PHONE = "worker_entering_phone"
    WORKER_UPLOADING_DNI = "worker_uploading_dni"
    WORKER_SHARING_LOCATION = "worker_sharing_location"
    CLIENT_SELECTING_SERVICE = "client_selecting_service"
    CLIENT_SELECTING_DATE = "client_selecting_date"
    CLIENT_SELECTING_TIME = "client_selecting_time"
    CLIENT_SHARING_LOCATION = "client_sharing_location"
    CLIENT_CONFIRMING = "client_confirming"
    CLIENT_WAITING_ACCEPTANCE = "client_waiting_acceptance"
    JOB_IN_PROGRESS = "job_in_progress"

@dataclass
class UserSession:
    state: UserState = field(default=UserState.IDLE)
    data: Dict = field(default_factory=dict)
    last_activity: float = field(default_factory=time.time)

# Gestión de sesiones global
user_sessions: Dict[str, UserSession] = {}

def get_session(chat_id: str) -> UserSession:
    chat_id = str(chat_id)
    if chat_id not in user_sessions:
        user_sessions[chat_id] = UserSession()
    return user_sessions[chat_id]

def set_state(chat_id: str, state: UserState, data: Dict = None):
    session = get_session(chat_id)
    session.state = state
    if data:
        session.data.update(data)
    session.last_activity = time.time()

def clear_state(chat_id: str):
    user_sessions.pop(str(chat_id), None)

def update_data(chat_id: str, **kwargs):
    session = get_session(chat_id)
    session.data.update(kwargs)

def get_data(chat_id: str, key: str, default=None):
    return get_session(chat_id).data.get(key, default)
