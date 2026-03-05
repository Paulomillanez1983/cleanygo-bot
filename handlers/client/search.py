from telebot import types
from config import bot, logger
from services.request_service import get_request, assign_worker_to_request_safe, update_request_status
from handlers.common import send_safe, edit_safe
from utils.icons import Icons
from handlers.client.flow import get_service_display
from handlers.worker.jobs import SERVICES_PRICES

# ==================== NOTIFICAR TRABAJERO ====================
def notify_worker(worker, request_id, service_id, hora, lat, lon):
    """
    Envía mensaje al trabajador con botones Aceptar/Rechazar.
    """
    worker_id, nombre, w_lat, w_lon, rating, precio = worker[:6]
    dist = worker[6] if len(worker) > 6 else 0

    maps_url = f"https://www.google.com/maps?q={lat},{lon}"
    service_info = SERVICES_PRICES.get(service_id, {"name": service_id.capitalize(), "price": precio})

    text = f"""
{Icons.BELL} <b>¡Nuevo trabajo disponible!</b>

Servicio: {service_info['name']}
{Icons.TIME} <b>Hora:</b> {hora}
{Icons.MONEY} <b>Tu precio:</b> ${service_info['price']}/hora
{Icons.LOCATION} <b>Distancia:</b> {dist:.1f} km

{Icons.INFO} ¿Aceptás este trabajo?
    """

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(f"{Icons.SUCCESS} Aceptar", callback_data=f"job_accept:{request_id}"),
        types.InlineKeyboardButton(f"{Icons.ERROR} Rechazar", callback_data=f"job_reject:{request_id}"),
    )
    markup.add(types.InlineKeyboardButton(f"{Icons.MAP} Ver en mapa", url=maps_url))

    send_safe(worker_id, text, markup)

# ==================== ACEPTAR TRABAJO ====================
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

        # Intentar asignar de manera segura (solo el primer trabajador que acepte)
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
        service_info = SERVICES_PRICES.get(service_id, {"name": service_id.capitalize(), "price": 0})

        client_text = f"""
{Icons.PARTY} <b>¡Encontramos tu profesional!</b>

Servicio: {service_info['name']}
{Icons.MONEY} <b>Precio:</b> ${service_info['price']}
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


# ==================== RECHAZAR TRABAJO ====================
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
