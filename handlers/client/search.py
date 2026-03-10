from telebot import types
from config import logger
# CORREGIDO: Importar funciones desde config y UserState desde models.states
from config import set_state, update_data, get_data, clear_state
from models.states import UserState
from models.services_data import SERVICES
from utils.icons import Icons
from utils.keyboards import get_alternative_times_keyboard, get_role_keyboard

from services.request_service import (
    create_request,
    get_request,
    assign_worker_to_request_safe,
    update_request_status,
    find_available_workers
)

from handlers.common import send_safe, edit_safe
from handlers.client.flow import get_service_display
from handlers.worker.jobs import SERVICES_PRICES


bot = None


# ==================== UTILIDADES ====================

def format_price(price: float) -> str:
    if price is None:
        price = 0
    return f"${int(price):,}".replace(",", ".")


def generate_no_availability_message(status: str, service_id: str, hora: str, extra=None) -> str:

    svc_name = SERVICES[service_id]['name']
    svc_icon = SERVICES[service_id]['icon']

    if status == "no_workers_online":
        return f"""
{Icons.WARNING} <b>No hay profesionales conectados</b>

{svc_icon} No hay {svc_name}s online en este momento.

{Icons.INFO} <b>¿Qué podés hacer?</b>
• Intentá en otro horario
• Dejá tu solicitud programada
"""

    elif status == "workers_far":
        return f"""
{Icons.WARNING} <b>No hay {svc_name}s cercanos</b>

{svc_icon} Hay profesionales conectados pero están fuera de tu zona.

Intentá nuevamente más tarde.
"""

    elif status == "workers_busy":

        busy_count = len(extra) if extra else 0

        return f"""
{Icons.WARNING} <b>Todos están ocupados</b>

{svc_icon} Encontramos <b>{busy_count}</b> {svc_name}s cerca tuyo
pero ya tienen trabajo a las <b>{hora}</b>.

Probá con otro horario.
"""

    return f"""
{Icons.WARNING} <b>No encontramos disponibilidad</b>

Intentá con otro horario.
"""


# ==================== NOTIFICAR TRABAJADOR ====================

def notify_worker(worker, request_id, service_id, hora, lat, lon):

    worker_id, nombre, w_lat, w_lon, rating, precio = worker[:6]
    dist = worker[6] if len(worker) > 6 else 0

    price = precio if precio is not None else SERVICES_PRICES.get(service_id, {}).get("price", 0)

    service_info = SERVICES_PRICES.get(
        service_id,
        {"name": service_id.capitalize(), "price": price}
    )

    price_text = format_price(service_info["price"])

    maps_url = f"https://www.google.com/maps?q={lat},{lon}"

    text = f"""
{Icons.BELL} <b>¡Nuevo trabajo disponible!</b>

Servicio: {service_info['name']}
{Icons.TIME} <b>Hora:</b> {hora}
{Icons.MONEY} <b>Tu precio:</b> {price_text}/hora
{Icons.LOCATION} <b>Distancia:</b> {dist:.1f} km
"""

    markup = types.InlineKeyboardMarkup(row_width=2)

    markup.add(
        types.InlineKeyboardButton(
            f"{Icons.SUCCESS} Aceptar",
            callback_data=f"job_accept:{request_id}"
        ),
        types.InlineKeyboardButton(
            f"{Icons.ERROR} Rechazar",
            callback_data=f"job_reject:{request_id}"
        )
    )

    markup.add(
        types.InlineKeyboardButton(
            f"{Icons.MAP} Ver en mapa",
            url=maps_url
        )
    )

    send_safe(worker_id, text, markup)


# ==================== REGISTER HANDLERS ====================

def register_handlers(bot_instance):

    global bot
    bot = bot_instance

    # ==================== CONFIRMAR SOLICITUD ====================

    @bot.callback_query_handler(func=lambda c: c.data == "confirm_yes")
    def handle_confirm_request(call):

        chat_id = call.message.chat.id

        service_id = get_data(chat_id, "service_id")
        time_str = get_data(chat_id, "selected_time")
        period = get_data(chat_id, "time_period")
        lat = get_data(chat_id, "lat")
        lon = get_data(chat_id, "lon")

        hora_completa = f"{time_str} {period}"

        request_id = create_request(
            chat_id,
            service_id,
            hora_completa,
            lat,
            lon,
            'searching'
        )

        if request_id is None:
            bot.answer_callback_query(call.id, "Error al crear solicitud")
            return

        bot.answer_callback_query(call.id, "¡Buscando profesionales!")

        search_text = f"""
{Icons.SEARCH} <b>Buscando profesionales...</b>

{SERVICES[service_id]['name']} a las {hora_completa}
"""

        edit_safe(chat_id, call.message.message_id, search_text)

        result = find_available_workers(service_id, lat, lon, hora_completa)

        if len(result) == 3:
            workers, status, extra = result
        else:
            workers, status = result
            extra = None

        if status != "success" or not workers:

            no_workers_text = generate_no_availability_message(
                status,
                service_id,
                hora_completa,
                extra
            )

            markup = types.InlineKeyboardMarkup()

            markup.add(
                types.InlineKeyboardButton(
                    "🔄 Intentar de nuevo",
                    callback_data=f"retry_search:{request_id}"
                )
            )

            markup.add(
                types.InlineKeyboardButton(
                    "◀️ Volver al inicio",
                    callback_data="back_start"
                )
            )

            update_request_status(request_id, 'no_workers_found')

            edit_safe(
                chat_id,
                call.message.message_id,
                no_workers_text,
                markup
            )

            return

        notified = 0

        for worker in workers:

            try:
                notify_worker(worker, request_id, service_id, hora_completa, lat, lon)
                notified += 1

            except Exception as e:
                logger.error(f"Error notificando worker {worker[0]}: {e}")

        update_request_status(request_id, 'waiting_acceptance')

        set_state(
            chat_id,
            UserState.CLIENT_WAITING_ACCEPTANCE,
            {"request_id": request_id}
        )

        waiting_text = f"""
{Icons.SUCCESS} <b>Solicitud enviada</b>

Notificamos a <b>{notified}</b> profesionales cercanos.

Esperando aceptación...
"""

        markup = types.InlineKeyboardMarkup()

        markup.add(
            types.InlineKeyboardButton(
                "❌ Cancelar solicitud",
                callback_data=f"cancel_req:{request_id}"
            )
        )

        edit_safe(chat_id, call.message.message_id, waiting_text, markup)

    # ==================== REINTENTAR ====================

    @bot.callback_query_handler(func=lambda c: c.data.startswith("retry_search:"))
    def handle_retry_search(call):

        chat_id = call.message.chat.id

        request_id = int(call.data.split(":")[1])

        request = get_request(request_id)

        if not request:
            bot.answer_callback_query(call.id, "Solicitud no encontrada")
            return

        bot.answer_callback_query(call.id, "Reintentando búsqueda...")

        update_request_status(request_id, 'searching')

        handle_confirm_request(call)

    # ==================== VOLVER AL INICIO ====================

    @bot.callback_query_handler(func=lambda c: c.data == "back_start")
    def handle_back_start(call):

        chat_id = call.message.chat.id

        clear_state(chat_id)

        bot.answer_callback_query(call.id, "Volviendo al inicio")

        welcome_text = f"""
{Icons.WAVE} <b>¡Bienvenido a CleanyGo!</b>

¿Qué necesitás hacer?
"""

        edit_safe(
            chat_id,
            call.message.message_id,
            welcome_text,
            get_role_keyboard()
        )

        set_state(chat_id, UserState.SELECTING_ROLE)
