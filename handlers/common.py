from models.user_state import clear_state, set_state, UserState
from utils.icons import Icons
from utils.keyboards import get_role_keyboard

def register_handlers(bot):

    @bot.message_handler(commands=['start'])
    def cmd_start(message):

        chat_id = message.chat.id

        clear_state(chat_id)

        welcome_text = f"""
{Icons.WAVE} <b>¡Bienvenido a CleanyGo!</b>

Conectamos personas que necesitan servicios con profesionales confiables cerca de ti.

<b>¿Qué necesitás hacer?</b>
"""

        bot.send_message(
            chat_id,
            welcome_text,
            reply_markup=get_role_keyboard(),
            parse_mode="HTML"
        )

        set_state(chat_id, UserState.SELECTING_ROLE)


    @bot.message_handler(commands=['cancel'])
    def cmd_cancel(message):

        chat_id = message.chat.id

        clear_state(chat_id)

        bot.send_message(
            chat_id,
            f"{Icons.SUCCESS} Cancelado. Usá /start para comenzar de nuevo."
        )


    @bot.message_handler(commands=['help','ayuda'])
    def cmd_help(message):

        text = f"""
{Icons.INFO} <b>Ayuda de CleanyGo</b>

<b>Para Clientes:</b>
/start - Solicitar un servicio
/cancel - Cancelar solicitud actual

<b>Para Profesionales:</b>
/start - Registrarte o ver panel
/online - Activar disponibilidad
/offline - Pausar notificaciones
/ubicacion - Cambiar ubicación
/precios - Modificar tarifas

<b>Soporte:</b>
@soporte_cleanygo
"""

        bot.send_message(
            message.chat.id,
            text,
            parse_mode="HTML"
        )
