import telebot

# ==============================
# 🔑 Configuración del token
# ==============================
# Pone tu token directamente aquí
TOKEN = "TU_TOKEN_AQUI"  # Reemplazá con el token que te dio @BotFather

# Verificar que el token no esté vacío
if not TOKEN:
    raise ValueError("❌ No se encontró el token. Por favor poné el token de tu bot.")

# Crear el bot
bot = telebot.TeleBot(TOKEN)

# ==============================
# 💾 Datos en memoria
# ==============================
workers = {}  # Trabajadores registrados
clients = {}  # Clientes que piden servicios

# ==============================
# /start
# ==============================
@bot.message_handler(commands=['start'])
def start(message):
    try:
        bot.reply_to(
            message,
            "👋 Bienvenido a Clean&Go Córdoba\n\n"
            "Opciones:\n"
            "/soytrabajador - Registrarte como trabajador\n"
            "/pedirservicio - Hacer un pedido de servicio"
        )
    except Exception as e:
        print("Error en /start:", e)

# ==============================
# /soytrabajador
# ==============================
@bot.message_handler(commands=['soytrabajador'])
def register_worker(message):
    try:
        workers[message.chat.id] = {"disponible": True}
        bot.reply_to(message, "✅ Registrado como trabajador. Recibirás pedidos disponibles.")
    except Exception as e:
        bot.reply_to(message, "❌ Ocurrió un error al registrarte como trabajador.")
        print("Error en /soytrabajador:", e)

# ==============================
# /pedirservicio
# ==============================
@bot.message_handler(commands=['pedirservicio'])
def request_service(message):
    try:
        clients[message.chat.id] = True
        bot.reply_to(message, "📝 Pedido recibido. Buscando trabajadores disponibles...")

        # Notificar a todos los trabajadores disponibles
        for worker_id in workers:
            try:
                bot.send_message(worker_id,
                                 "🚨 Nuevo pedido disponible.\nEscribí /aceptar para tomar el trabajo.")
            except Exception as e:
                print(f"No se pudo notificar al trabajador {worker_id}: {e}")

    except Exception as e:
        bot.reply_to(message, "❌ Ocurrió un error al realizar el pedido.")
        print("Error en /pedirservicio:", e)

# ==============================
# /aceptar
# ==============================
@bot.message_handler(commands=['aceptar'])
def accept_job(message):
    try:
        if message.chat.id in workers:
            bot.reply_to(message, "🎉 Tomaste el trabajo.")
        else:
            bot.reply_to(message, "❌ No estás registrado como trabajador.")
    except Exception as e:
        bot.reply_to(message, "❌ Ocurrió un error al aceptar el trabajo.")
        print("Error en /aceptar:", e)

# ==============================
# 🔄 Mantener el bot en ejecución
# ==============================
print("🤖 Bot iniciado y listo para usar...")
bot.polling(non_stop=True)
