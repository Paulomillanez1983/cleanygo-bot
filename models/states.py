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


_state_store = {}
_data_store = {}


def set_state(user_id: int, state: UserState | str, data: dict | None = None):
    """
    Set the current state for a user.
    Accepts either UserState enum or string for compatibility.
    """
    # Convertir a string si es enum
    if isinstance(state, UserState):
        _state_store[user_id] = state.value
    else:
        _state_store[user_id] = state

    if data:
        if user_id not in _data_store:
            _data_store[user_id] = {}
        _data_store[user_id].update(data)


def update_data(user_id: int, **kwargs):
    """Update stored data for a user."""
    if user_id not in _data_store:
        _data_store[user_id] = {}
    _data_store[user_id].update(kwargs)


def get_data(user_id: int, key: str = None):
    """Get stored data for a user."""
    data = _data_store.get(user_id, {})
    if key:
        return data.get(key)
    return data


def clear_state(user_id: int):
    """Clear state and data for a user."""
    _state_store.pop(user_id, None)
    _data_store.pop(user_id, None)


def get_state(user_id: int) -> str | None:
    """Obtener estado actual del usuario (como string)"""
    return _state_store.get(user_id)
