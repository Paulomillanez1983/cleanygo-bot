from telebot import types
from config import bot, logger
from models.user_state import set_state, update_data, get_data, clear_state, UserState
from models.services_data import SERVICES
from utils.icons import Icons
from utils.keyboards import get_alternative_times_keyboard, get_role_keyboard

# o desde models/services_data.py si es parte de ahí
from services.request_service import create_request, update_request_status, get_request, assign_worker_to_request_safe
from handlers.common import send_safe, edit_safe
from handlers.client.flow import get_service_display
from handlers.worker.jobs import SERVICES_PRICES

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

# ==================== NOTIFICAR TRABAJADOR ====================
def notify_worker(worker, request_id, service_id, hora, lat, lon):
    worker_id, nombre, w_lat, w_lon, rating, precio = worker[:6]
    dist = worker[6] if len(worker) > 6 else 0

    # Asegurar que precio nunca sea None
    price = precio if precio is not None else SERVICES_PRICES.get(service_id, {}).get("price", 0)
    service_info = SERVICES_PRICES.get(service_id, {"name": service_id.capitalize(), "price": price})

    price_text = format_price(service_info["price"])
    maps_url = f"https://www.google.com/maps?q={lat},{lon}"

    text = f"""
{Icons.BELL} <b>¡Nuevo trabajo disponible!</b>

Servicio: {service_info['name']}
{Icons.TIME} <b>Hora:</b> {hora}
{Icons.MONEY} <b>Tu precio:</b> {price_text}/hora
{Icons.LOCATION} <b>Distancia:</b> {dist:.1f} km

{Icons.INFO} ¿Aceptás este trabajo?
    """

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(f"{Icons.SUCCESS} Aceptar", callback_data=f"job_accept:{request_id}"),
        types.InlineKeyboardButton(f"{Icons.ERROR} Rechazar", callback_data=f"job_reject:{request_id}")
    )
    markup.add(types.InlineKeyboardButton(f"{Icons.MAP} Ver en mapa", url=maps_url))

    send_safe(worker_id, text, markup)

# ==================== CONFIRMAR SOLICITUD CLIENTE ====================
@bot.callback_query_handler(func=lambda c: c.data == "confirm_yes")
def handle_confirm_request(call):
    chat_id = call.message.chat.id

    service_id = get_data(chat_id, "service_id")
    time_str = get_data(chat_id, "selected_time")
    period = get_data(chat_id, "time_period")
    lat = get_data(chat_id, "lat")
    lon = get_data(chat_id, "lon")
    hora_completa = f"{time_str} {period}"

    request_id = create_request(chat_id, service_id, hora_completa, lat, lon, 'searching')
    if request_id is None:
        bot.answer_callback_query(call.id, "Error al crear solicitud")
        return

    bot.answer_callback_query(call.id, "¡Buscando profesionales!")
    search_text = f"""
{Icons.SEARCH} <b>Buscando profesionales disponibles...</b>

{Icons.PENDING} Verificando disponibilidad para {SERVICES[service_id]['name']} a las {hora_completa}

{Icons.TIME} Esto tomará unos segundos...
    """
    edit_safe(chat_id, call.message.message_id, search_text)

    # Buscar trabajadores disponibles
    result = find_available_workers(service_id, lat, lon, hora_completa)
    if len(result) == 3:
        workers, status, extra = result
    else:
        workers, status = result
        extra = None

    if status != "success" or not workers:
        no_workers_text = generate_no_availability_message(status, service_id, hora_completa, extra)
        markup = types.InlineKeyboardMarkup(row_width=1)
        if status == "workers_busy":
            markup.add(types.InlineKeyboardButton("⏰ Ver otros horarios disponibles", 
                                                  callback_data=f"alt_times:{service_id}:{request_id}"))
        markup.add(types.InlineKeyboardButton("🔄 Intentar de nuevo", callback_data=f"retry_search:{request_id}"))
        markup.add(types.InlineKeyboardButton("◀️ Volver al inicio", callback_data="back_start"))

        update_request_status(request_id, 'no_workers_found')
        edit_safe(chat_id, call.message.message_id, no_workers_text, markup)
        return

    # Notificar trabajadores
    notified = 0
    for worker in workers:
        try:
            notify_worker(worker, request_id, service_id, hora_completa, lat, lon)
            notified += 1
        except Exception as e:
            logger.error(f"Error notificando a {worker[0]}: {e}")

    update_request_status(request_id, 'waiting_acceptance')
    set_state(chat_id, UserState.CLIENT_WAITING_ACCEPTANCE, {"request_id": request_id})

    waiting_text = f"""
{Icons.SUCCESS} <b>¡Solicitud enviada!</b>

{Icons.INFO} Hemos notificado a <b>{notified}</b> profesionales cercanos disponibles a las {hora_completa}.

{Icons.PENDING} Esperando que acepten tu solicitud...

{Icons.TIME} Tiempo estimado: 2-3 minutos
    """
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"{Icons.ERROR} Cancelar solicitud", callback_data=f"cancel_req:{request_id}"))
    edit_safe(chat_id, call.message.message_id, waiting_text, markup)

# ==================== REINTENTAR BÚSQUEDA ====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("retry_search:"))
def handle_retry_search(call):
    chat_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])
    request = get_request(request_id)
    if not request:
        bot.answer_callback_query(call.id, "Solicitud no encontrada")
        return

    _, client_id, service_id, _, hora, lat, lon, status, *_ = request
    update_request_status(request_id, 'searching')
    bot.answer_callback_query(call.id, "Reintentando búsqueda...")

    # Actualizar sesión
    hora_parts = hora.split()
    update_data(chat_id,
        service_id=service_id,
        selected_time=hora_parts[0],
        time_period=hora_parts[1] if len(hora_parts) > 1 else "PM",
        lat=lat, lon=lon
    )
    handle_confirm_request(call)

# ==================== HORARIOS ALTERNATIVOS ====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("alt_times:"))
def handle_alternative_times(call):
    chat_id = call.message.chat.id
    parts = call.data.split(":")
    service_id = parts[1]
    request_id = int(parts[2])

    text = f"""
{Icons.CLOCK} <b>Horarios alternativos disponibles</b>

{SERVICES[service_id]['icon']} <b>{SERVICES[service_id]['name']}</b>

Seleccioná otro horario:
    """
    edit_safe(chat_id, call.message.message_id, text,
              get_alternative_times_keyboard(service_id, request_id))

# ==================== VOLVER AL INICIO ====================
@bot.callback_query_handler(func=lambda c: c.data == "back_start")
def handle_back_start(call):
    chat_id = call.message.chat.id
    clear_state(chat_id)
    bot.answer_callback_query(call.id, "Volviendo al inicio...")

    welcome_text = f"""
{Icons.WAVE} <b>¡Bienvenido a CleanyGo!</b>

Conectamos personas que necesitan servicios con profesionales confiables cerca de ti.

<b>¿Qué necesitás hacer?</b>
    """
    edit_safe(chat_id, call.message.message_id, welcome_text, get_role_keyboard())
    set_state(chat_id, UserState.SELECTING_ROLE)

# ==================== ACEPTAR TRABAJO POR TRABAJADOR ====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("job_accept:"))
def handle_job_accept(call):
    chat_id = call.message.chat.id
    try:
        request_id = int(call.data.split(":")[1])
        request = get_request(request_id)

        if not request:
            bot.answer_callback_query(call.id, "❌ Este trabajo no existe", show_alert=True)
            edit_safe(chat_id, call.message.message_id,
                      f"{Icons.ERROR} <b>Trabajo no disponible</b>\n\nNo se encontró la solicitud.")
            logger.warning(f"[JOB ACCEPT] request_id={request_id} no encontrada por worker {chat_id}")
            return

        if request["status"] != 'waiting_acceptance':
            bot.answer_callback_query(call.id, "❌ Este trabajo ya fue tomado por otro profesional", show_alert=True)
            edit_safe(chat_id, call.message.message_id,
                      f"{Icons.ERROR} <b>Trabajo no disponible</b>\n\nYa fue asignado a otro profesional.")
            logger.info(f"[JOB ACCEPT] request_id={request_id} ya asignada, worker={chat_id}")
            return

        success = assign_worker_to_request_safe(request_id, chat_id)
        if not success:
            bot.answer_callback_query(call.id, "❌ Este trabajo ya fue tomado", show_alert=True)
            edit_safe(chat_id, call.message.message_id,
                      f"{Icons.ERROR} <b>Trabajo no disponible</b>\n\nYa fue asignado a otro profesional.")
            logger.info(f"[JOB ACCEPT] request_id={request_id} fallo asignación, worker={chat_id}")
            return

        bot.answer_callback_query(call.id, "✅ ¡Trabajo asignado!")
        logger.info(f"[JOB ACCEPT] request_id={request_id} asignada a worker {chat_id}")

        # Mensaje al trabajador
        worker_text = f"""
{Icons.SUCCESS} <b>¡Trabajo confirmado!</b>

{Icons.INFO} Contactá al cliente para coordinar los detalles.

{Icons.PHONE} <b>Cliente:</b> {request['client_chat_id']}
        """
        edit_safe(chat_id, call.message.message_id, worker_text)

        # Notificar al cliente
        client_id = request["client_chat_id"]
        service_id = request["service_id"]
        hora = request["hora"]

        # Asegurar precio
        service_price = SERVICES_PRICES.get(service_id, {}).get("price", 0)
        service_info = SERVICES_PRICES.get(service_id, {"name": service_id.capitalize(), "price": service_price})
        price_text = format_price(service_info["price"])

        client_text = f"""
{Icons.PARTY} <b>¡Encontramos tu profesional!</b>

Servicio: {service_info['name']}
{Icons.MONEY} <b>Precio:</b> {price_text}
{Icons.TIME} <b>Hora:</b> {hora}

{Icons.INFO} El profesional se pondrá en contacto con vos pronto.

{Icons.CAR} <b>Estado:</b> En camino al servicio
        """
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(f"{Icons.SUCCESS} Recibí el servicio",
                                      callback_data=f"client_complete:{request_id}"),
            types.InlineKeyboardButton(f"{Icons.ERROR} Reportar problema",
                                      callback_data=f"client_issue:{request_id}")
        )
        send_safe(client_id, client_text, markup)

    except Exception as e:
        logger.error(f"[JOB ACCEPT ERROR] worker={chat_id}, request_id={request_id} -> {e}")
        bot.answer_callback_query(call.id, "❌ Ocurrió un error al aceptar el trabajo.", show_alert=True)

# ==================== RECHAZAR TRABAJO POR TRABAJADOR ====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("job_reject:"))
def handle_job_reject(call):
    chat_id = call.message.chat.id
    try:
        request_id = int(call.data.split(":")[1])
        request = get_request(request_id)

        if not request:
            bot.answer_callback_query(call.id, "❌ Este trabajo no existe", show_alert=True)
            edit_safe(chat_id, call.message.message_id,
                      f"{Icons.ERROR} <b>Trabajo no disponible</b>\n\nNo se encontró la solicitud.")
            logger.warning(f"[JOB REJECT] request_id={request_id} no encontrada por worker {chat_id}")
            return

        bot.answer_callback_query(call.id, "Trabajo rechazado")
        edit_safe(chat_id, call.message.message_id,
                  f"{Icons.INFO} <b>Trabajo rechazado</b>\n\nTe seguiremos notificando de nuevas oportunidades.")
        logger.info(f"[JOB REJECT] worker={chat_id}, request_id={request_id}")

    except Exception as e:
        logger.error(f"[JOB REJECT ERROR] worker={chat_id}, request_id={request_id} -> {e}")
        bot.answer_callback_query(call.id, "❌ Ocurrió un error al rechazar el trabajo.", show_alert=True)
