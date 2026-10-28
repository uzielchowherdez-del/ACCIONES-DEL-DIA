
# bot_interactivo.py - Para correr en tu PC o en Render.com gratis y tener comandos /top desde Telegram
# Uso: python bot_interactivo.py
# Deja esto corriendo y en Telegram escribe /top
import os
os.environ["TELEGRAM_TOKEN"] = os.getenv("TELEGRAM_TOKEN") or "PON_AQUI_TU_TOKEN"
os.environ["CHAT_ID"] = os.getenv("CHAT_ID") or "PON_AQUI_TU_CHAT_ID"
import bot
# bot.py ya contiene el loop interactivo si se llama con 'interactive'
# Este archivo solo es un launcher
import sys
sys.argv.append("interactive")
exec(open("bot.py").read())
