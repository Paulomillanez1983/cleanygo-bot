"""
Handlers para gestión de trabajos/asignaciones para profesionales.
VERSIÓN CORREGIDA: Integración con requests_db.py y esquema unificado
"""

from telebot import types
from config import bot, logger, get_db_connection
from models.user_state import set_state, UserState
from utils.icons import Icons
# ✅ CORREGIDO: Importar desde requests_db en lugar de services.request_service
from requests_db import (
    get_request, 
    update_request_status, 
    assign_worker_to_request,
    reject_request,
    complete_request
)
from handlers.common import send_safe, edit_safe
import time
import sqlite3
from threading import Thread

# ===================== PRECIOS DE SERVICIOS =====================
SERVICES_PRICES = {
    "niñera": {"name": "Niñera", "price": 1500},
    "limpieza": {"name": "Limpieza", "price": 2000},
    "plomeria": {"name": "Plomería", "price": 2500},
}

# ===================== FUNCIONES AUXILIARES =====================
def find_available_workers(service_id, lat, lon, hora):
    """
    Busca workers disponibles para un servicio cercanos a una ubicación.
    ✅ CORREGIDO: Usa nuevo esquema de DB (user_id en lugar de chat_id)
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Buscar workers con el servicio y activos
            cursor.execute('''
                SELECT w.user_id, w.lat, w.lon 
                FROM workers w
                JOIN worker_services ws ON w.user_id = ws.user_id
                WHERE ws.service_id = ? 
                AND w.is_active = 1
                AND (w.current_request_id IS NULL OR w.current_request_id = 0)
            ''', (service_id,))
            
            workers = cursor.fetchall()
            
        if not workers:
            return [], "no_workers", {}
            
        available = []
        for w in workers:
            w_id, w_lat, w_lon = w['user_id'], w['lat'], w['lon']
            if w_id and w_lat is not None and w_lon is not None:
                # Calcular distancia simple (Euclidean)
                distance = ((lat - w_lat)**2 + (lon - w_lon)**2)**0.5
                available.append((w_id, distance))
        
        available.sort(key=lambda x: x[1])
        return available, "ok", {"total": len(available)}
        
    except Exception as e:
        logger.error(f"[FIND_WORKERS ERROR]: {e}")
        return [], "error", {}

def assign_worker_to_request_safe(request_id, worker_id):
    """
    Asigna un worker a una request de forma segura (concurrencia).
    ✅ CORREGIDO: Usa assign_worker_to_request de requests_db
    """
    # Convertir a int si es string
    worker_id = int(worker_id) if isinstance(worker_id, str) else worker_id
    
    result = assign_worker_to_request(request_id, worker_id)
    
    if result:
        logger.info(f"[ASSIGN_SAFE] request_id={request_id} asignada a worker={worker_id}")
        return True
    else:
        logger.warning(f"[ASSIGN_SAFE] Fallo asignación request_id={request_id} a worker={worker_id}")
        return False

# ===================== HANDLER: TRABAJADOR ACEPTA TRABAJO =====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("job_accept:"))
def handle_job_accept(call):
    worker_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])
    logger.info(f"[JOB_ACCEPT] worker={worker_id} intenta aceptar request_id={request_id}")

    # Obtener request
    request = get_request(request_id)
    if not request:
        bot.answer_callback_query(call.id, "❌ Este trabajo no existe")
        edit_safe(worker_id, call.message.message_id, f"{Icons.ERROR} <b>Trabajo no disponible</b>")
        return

    # Verificar estado
    if request["status"] not in ('pending', 'searching', 'waiting_acceptance'):
        bot.answer_callback_query(call.id, "❌ Este trabajo ya fue tomado")
        edit_safe(worker_id, call.message.message_id, f"{Icons.ERROR} <b>Trabajo no disponible</b>")
        return

    # Intentar asignar
    success = assign_worker_to_request_safe(request_id, worker_id)
    if not success:
        bot.answer_callback_query(call.id, "❌ No se pudo asignar")
        edit_safe(worker_id, call.message.message_id, f"{Icons.ERROR} <b>Trabajo no disponible</b>")
        return

    # Actualizar sesión del worker
    set_state(worker_id, UserState.JOB_IN_PROGRESS, {
        "request_id": request_id,
        "client_id": request.get("client_id") or request.get("client_chat_id"),
        "service_id": request.get("service_id"),
        "hora": request.get("request_time") or request.get("hora")
    })

    bot.answer_callback_query(call.id, "✅ ¡Trabajo asignado!")
    edit_safe(worker_id, call.message.message_id, f"""
{Icons.SUCCESS} <b>¡Trabajo confirmado!</b>
{Icons.INFO} Contactá al cliente para coordinar.
{Icons.PHONE} <b>Cliente:</b> {request.get('client_id') or request.get('client_chat_id')}
""")

    # Notificar al cliente
    client_id = request.get("client_id") or request.get("client_chat_id")
    service_id = request.get("service_id")
    hora = request.get("request_time") or request.get("hora")
    
    if not client_id:
        logger.error(f"[JOB_ACCEPT] No se pudo notificar: client_id es None request_id={request_id}")
        return

    # Obtener precio del worker
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT precio FROM worker_services WHERE user_id = ? AND service_id = ?",
                (worker_id, service_id)
            )
            price_row = cursor.fetchone()
            price = price_row[0] if price_row else None
    except Exception as e:
        logger.error(f"[JOB_ACCEPT] Error obteniendo precio: {e}")
        price = None

    if price is None:
        price = SERVICES_PRICES.get(service_id, {}).get("price", 0)
    
    service_name = SERVICES_PRICES.get(service_id, {"name": service_id.capitalize()})["name"]

    client_text = f"""
{Icons.PARTY} <b>¡Encontramos tu profesional!</b>

Servicio: {service_name}
{Icons.MONEY} <b>Precio:</b> ${price}
{Icons.TIME} <b>Hora:</b> {hora}

{Icons.INFO} Confirmá si aceptás el servicio.
"""

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(f"{Icons.SUCCESS} Acepto", callback_data=f"client_accept:{request_id}"),
        types.InlineKeyboardButton(f"{Icons.ERROR} No acepto", callback_data=f"client_reject:{request_id}")
    )

    send_safe(client_id, client_text, markup)
    logger.info(f"[JOB_ACCEPT] request_id={request_id} enviado al cliente para aceptación")

# ===================== HANDLER: CLIENTE ACEPTA =====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("client_accept:"))
def handle_client_accept(call):
    client_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])

    request = get_request(request_id)
    if not request:
        bot.answer_callback_query(call.id, "❌ Esta solicitud no existe")
        edit_safe(client_id, call.message.message_id, f"{Icons.ERROR} Solicitud no encontrada")
        return

    # Actualizar estado
    success = update_request_status(request_id, "accepted")
    if not success:
        bot.answer_callback_query(call.id, "❌ Error al actualizar")
        return

    edit_safe(client_id, call.message.message_id, f"{Icons.SUCCESS} Gracias, aceptaste el servicio ✅")

    worker_id = request.get("worker_id") or request.get("worker_chat_id")
    if not worker_id:
        logger.error(f"[CLIENT_ACCEPT] No hay worker asignado para request_id={request_id}")
        send_safe(client_id, f"{Icons.ERROR} No hay profesional asignado aún.")
        return

    # Notificar al worker
    send_safe(worker_id, f"{Icons.SUCCESS} El cliente aceptó el servicio. ¡Podés realizarlo!")
    
    # Actualizar estado del worker
    set_state(worker_id, UserState.JOB_IN_PROGRESS, {
        "request_id": request_id,
        "client_id": client_id,
        "service_id": request.get("service_id"),
        "hora": request.get("request_time") or request.get("hora")
    })

    # Mostrar botón de iniciar
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton(f"{Icons.PLAY} Iniciar servicio", callback_data=f"start_job:{request_id}"))
    send_safe(worker_id, f"{Icons.INFO} Podés iniciar el servicio ahora.", markup)

    # Mostrar menú del worker
    try:
        from handlers.worker.main import show_worker_menu
        show_worker_menu(worker_id, request, extra_buttons=[
            types.InlineKeyboardButton(f"{Icons.PLAY} Iniciar servicio", callback_data=f"start_job:{request_id}")
        ])
    except Exception as e:
        logger.error(f"[CLIENT_ACCEPT] error mostrando menú worker_id={worker_id}: {e}")

# ===================== HANDLER: CLIENTE RECHAZA =====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("client_reject:"))
def handle_client_reject(call):
    client_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])

    request = get_request(request_id)
    if not request:
        bot.answer_callback_query(call.id, "❌ Esta solicitud no existe")
        edit_safe(client_id, call.message.message_id, f"{Icons.ERROR} Solicitud no encontrada")
        return

    # Cancelar request
    from requests_db import cancel_request
    cancel_request(request_id, reason="Cliente rechazó el servicio")
    
    edit_safe(client_id, call.message.message_id, f"{Icons.ERROR} Cancelaste el servicio ❌")
    
    worker_id = request.get("worker_id") or request.get("worker_chat_id")
    if worker_id:
        send_safe(worker_id, f"{Icons.ERROR} El cliente rechazó el servicio. No se realizará.")

# ===================== HANDLER: TRABAJADOR RECHAZA =====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("job_reject:"))
def handle_job_reject(call):
    worker_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])

    bot.answer_callback_query(call.id, "Trabajo rechazado")
    edit_safe(worker_id, call.message.message_id,
              f"{Icons.INFO} <b>Trabajo rechazado</b>\nTe seguiremos notificando.")
    
    # Usar función de requests_db
    reject_request(request_id, worker_id)
    logger.info(f"[JOB_REJECT] Registro de rechazo guardado: request_id={request_id}, worker={worker_id}")

# ===================== HANDLER: TRABAJADOR INICIA SERVICIO =====================
active_tracking = {}

@bot.callback_query_handler(func=lambda c: c.data.startswith("start_job:"))
def handle_start_job(call):
    worker_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])
    
    request = get_request(request_id)
    if not request:
        edit_safe(worker_id, call.message.message_id, f"{Icons.ERROR} Trabajo no encontrado")
        return

    client_id = request.get("client_id") or request.get("client_chat_id")
    
    # Actualizar estado
    update_request_status(request_id, "in_progress")
    
    edit_safe(worker_id, call.message.message_id, f"{Icons.SUCCESS} Servicio iniciado. Enviando ubicación al cliente...")

    set_state(worker_id, UserState.JOB_IN_PROGRESS, {
        "request_id": request_id,
        "client_id": client_id
    })

    send_safe(client_id, f"{Icons.INFO} El profesional comenzó el servicio. Recibirás ubicación en tiempo real.")

    def location_loop(worker_id, client_id):
        while active_tracking.get(worker_id, {}).get("running"):
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT lat, lon FROM workers WHERE user_id = ?",
                        (worker_id,)
                    )
                    worker_data = cursor.fetchone()
                    
                if worker_data and worker_data['lat'] is not None and worker_data['lon'] is not None:
                    lat, lon = worker_data['lat'], worker_data['lon']
                    bot.send_location(client_id, latitude=lat, longitude=lon)
                else:
                    bot.send_message(client_id, f"{Icons.ERROR} Ubicación no disponible")
            except Exception as e:
                logger.error(f"[LOCATION LOOP ERROR]: {e}")
            time.sleep(10)

    active_tracking[worker_id] = {"thread": None, "running": True}
    thread = Thread(target=location_loop, args=(worker_id, client_id), daemon=True)
    thread.start()
    active_tracking[worker_id]["thread"] = thread

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton(f"{Icons.STOP} Finalizar servicio", callback_data=f"finish_job:{request_id}"))
    send_safe(worker_id, f"{Icons.INFO} Podés finalizar el servicio cuando termines.", markup)

# ===================== HANDLER: TRABAJADOR FINALIZA SERVICIO =====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("finish_job:"))
def handle_finish_job(call):
    worker_id = call.message.chat.id
    request_id = int(call.data.split(":")[1])
    
    request = get_request(request_id)
    if not request:
        edit_safe(worker_id, call.message.message_id, f"{Icons.ERROR} Trabajo no encontrado")
        return

    client_id = request.get("client_id") or request.get("client_chat_id")

    # Detener tracking
    if worker_id in active_tracking:
        active_tracking[worker_id]["running"] = False
        active_tracking.pop(worker_id, None)

    # Liberar worker y completar
    set_state(worker_id, UserState.SELECTING_ROLE)
    complete_request(request_id)

    send_safe(client_id, f"{Icons.SUCCESS} El profesional finalizó el servicio ✅")
    send_safe(worker_id, f"{Icons.SUCCESS} Servicio finalizado. Gracias por tu trabajo ✅")

    # Mostrar menú del worker
    try:
        from handlers.worker.main import show_worker_menu
        show_worker_menu(worker_id, request)
    except Exception as e:
        logger.error(f"[FINISH_JOB] error mostrando menú worker_id={worker_id}: {e}")
