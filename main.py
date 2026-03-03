import os
import telebot

# Obtener el token desde la variable de entorno
TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

# Diccionarios simples para almacenar datos en memoria
workers = {}
clients = {}

# Comando /start
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(
        message,
        "👋 Bienvenido a Clean&Go Córdoba\n\n"
        "Opciones:\n"
        "/soytrabajador - Registrarte como trabajador\n"
        "/pedirservicio - Hacer un pedido de servicio"
    )

# Comando /soytrabajador
@bot.message_handler(commands=['soytrabajador'])
def register_worker(message):
    workers[message.chat.id] = {"disponible": True}
    bot.reply_to(message, "✅ Registrado como trabajador. Recibirás pedidos disponibles.")

# Comando /pedirservicio
@bot.message_handler(commands=['pedirservicio'])
def request_service(message):
    clients[message.chat.id] = True
    bot.reply_to(message, "📝 Pedido recibido. Buscando trabajadores disponibles...")

    # Notificar a todos los trabajadores disponibles
    for worker_id in workers:
        bot.send_message(worker_id,
                         "🚨 Nuevo pedido disponible.\nEscribí /aceptar para tomar el trabajo.")

# Comando /aceptar para trabajadores
@bot.message_handler(commands=['aceptar'])
def accept_job(message):
    if message.chat.id in workers:
        bot.reply_to(message, "🎉 Tomaste el trabajo.")
    else:
        bot.reply_to(message, "❌ No estás registrado como trabajador.")

# Mantener el bot en ejecución
bot.polling()
