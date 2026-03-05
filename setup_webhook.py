import os
from config import bot, logger

railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
if not railway_domain:
    logger.error("❌ RAILWAY_PUBLIC_DOMAIN no está configurado")
    exit(1)

webhook_url = f"https://{railway_domain}/webhook"

current = bot.get_webhook_info()
if current.url != webhook_url:
    bot.remove_webhook(drop_pending_updates=True)
    bot.set_webhook(url=webhook_url, drop_pending_updates=True)
    logger.info(f"✅ Webhook configurado: {webhook_url}")
else:
    logger.info(f"Webhook ya configurado: {webhook_url}")
