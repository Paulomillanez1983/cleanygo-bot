from telebot import types
from utils.icons import Icons
from models.services_data import SERVICES

def get_role_keyboard():
    """Teclado de selección de rol"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(
        types.KeyboardButton(f"{Icons.BELL} Necesito un servicio"),
        types.KeyboardButton(f"{Icons.BRIEFCASE} Quiero trabajar"),
        types.KeyboardButton(f"{Icons.INFO} Ayuda")
    )
    return markup

def get_cancel_keyboard(text="Cancelar"):
    """Teclado de cancelación"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton(f"{Icons.ERROR} {text}"))
    return markup

def get_location_keyboard(text="📍 Enviar mi ubicación"):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton(text, request_location=True))
    markup.add(types.KeyboardButton(f"{Icons.ERROR} Cancelar"))
    return markup

def get_service_selector(selected_services=None):
    """Selector de servicios con toggles"""
    if selected_services is None:
        selected_services = []
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for svc_id, svc in SERVICES.items():
        is_selected = svc_id in selected_services
        icon = Icons.CHECK if is_selected else Icons.CROSS
        text = f"{icon} {svc['icon']} {svc['name']}"
        callback = f"svc_toggle:{svc_id}"
        markup.add(types.InlineKeyboardButton(text, callback_data=callback))
    
    if selected_services:
        markup.add(types.InlineKeyboardButton(
            f"{Icons.SUCCESS} Confirmar ({len(selected_services)})", 
            callback_data="svc_confirm"
        ))
    
    return markup

def get_time_selector():
    """Selector de hora rápida"""
    markup = types.InlineKeyboardMarkup(row_width=4)
    
    popular_hours = [8, 9, 10, 14, 15, 16, 17, 18]
    hour_buttons = []
    for h in popular_hours:
        hour_buttons.append(types.InlineKeyboardButton(
            f"{h:02d}:00", callback_data=f"time_quick:{h}:00"
        ))
    markup.add(*hour_buttons)
    
    markup.add(types.InlineKeyboardButton(
        f"{Icons.CLOCK} Elegir otra hora...", callback_data="time_custom"
    ))
    
    return markup

def get_confirmation_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(f"{Icons.SUCCESS} Sí, confirmar", callback_data="confirm_yes"),
        types.InlineKeyboardButton(f"{Icons.ERROR} No, corregir", callback_data="confirm_no")
    )
    return markup

def get_worker_request_keyboard(request_id: int):
    """Teclado para que worker acepte/rechace solicitud"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(f"{Icons.SUCCESS} Aceptar", callback_data=f"job_accept:{request_id}"),
        types.InlineKeyboardButton(f"{Icons.ERROR} Rechazar", callback_data=f"job_reject:{request_id}"),
        types.InlineKeyboardButton(f"{Icons.INFO} Ver detalles", callback_data=f"view_request:{request_id}")
    )
    return markup

def get_alternative_times_keyboard(service_id: str, request_id: int):
    """Teclado para horarios alternativos"""
    horas_posibles = [8, 10, 12, 14, 16, 18, 20]
    
    markup = types.InlineKeyboardMarkup(row_width=3)
    
    buttons = []
    for h in horas_posibles:
        hora_str = f"{h:02d}:00"
        buttons.append(types.InlineKeyboardButton(
            f"{hora_str}", 
            callback_data=f"change_time:{request_id}:{hora_str}"
        ))
    
    for i in range(0, len(buttons), 3):
        markup.row(*buttons[i:i+3])
    
    markup.add(types.InlineKeyboardButton(
        f"{Icons.BACK} Volver", callback_data=f"retry_search:{request_id}"
    ))
    
    return markup
