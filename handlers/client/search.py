from config import bot, logger
from models.user_state import set_state, update_data, get_data, clear_state, UserState, get_session
from models.services_data import SERVICES
from utils.icons import Icons
from services.worker_service import find_available_workers
from services.request_service import create_request, update_request_status
from handlers.common import send_safe, edit_safe, remove_keyboard
from handlers.client.flow import get_service_display

def format_price(price: float) -> str:
    return f"${price:,.0f}".replace(",", ".")

def generate_no_availability_message(status: str, service_id: str, hora: str, extra=None) -> str:
    """Genera mensaje específico según el tipo de indisponibilidad"""
    
    svc_name = SERVICES[service_id]['name']
    svc_icon = SERVICES[service_id]['icon']
    
    if status == "no_workers_online":
        return f"""
{Icons.WARNING} <b>No hay profesionales conectados</b>

{svc_icon} No hay {svc_name}s online en este momento.

{Icons.INFO} <b>¿Qué podés hacer?</b>
• Intentá en otro horario (más temprano o más tarde)
• Dejá tu solicitud programada y te avisamos cuando haya disponibilidad
        """
    
    elif status == "workers_far":
        return f"""
{Icons.WARNING} <b>No hay {svc_name}s cercanos</b>

{svc_icon} Hay profesionales conectados, pero están fuera de tu zona (más de 10km).

{Icons.INFO} <b>¿Qué podés hacer?</b>
• Ampliaremos la búsqueda próximamente
• Intentá con otro servicio similar
        """
    
    elif status == "workers_busy":
        busy_count = len(extra) if extra else 0
        return f"""
{Icons.WARNING} <b>Todos los profesionales están ocupados a esta hora</b>

{svc_icon} Encontramos <b>{busy_count}</b> {svc_name}s cerca tuyo, 
pero ya tienen trabajo asignado a las <b>{hora}</b>.

{Icons.INFO} <b>¿Qué podés hacer?</b>
• Elegir otro horario (1-2 horas antes o después)
• Intentar para mañana a la misma hora
• Dejar solicitud y avisarte cuando se liberen
        """
    
    else:
        return f"""
{Icons.WARNING} <b>No encontramos disponibilidad</b>

{svc_icon} No hay {svc_name}s disponibles en este momento.

{Icons.INFO} Intentá con otro horario o servicio.
        """

def notify_worker(worker, request_id, service_id, hora, lat, lon):
    """Notifica al trabajador de nuevo trabajo"""
    from telebot import types
    from utils.keyboards import get_job_response_keyboard
    
    worker_id, nombre, w_lat, w_lon, rating, precio = worker[:6]
    dist = worker[6] if len(worker) > 6 else 0
    
    maps_url = f"https://www.google.com/maps?q={lat},{lon}"
    
    text = f"""
{Icons.BELL} <b>¡Nuevo trabajo disponible!</b>

{get_service_display(service_id)}
{Icons.TIME} <b>Hora:</b> {hora}
{Icons.MONEY} <b>Tu precio:</b> {format_price(precio)}/hora
{Icons.LOCATION} <b>Distancia:</b> {dist:.1f} km

{Icons.INFO} ¿Aceptás este trabajo?
    """
    
    markup = get_job_response_keyboard(request_id)
    markup.add(types.InlineKeyboardButton(f"{Icons.MAP} Ver en mapa", url=maps_url))
    
    send_safe(worker_id, text, markup)
