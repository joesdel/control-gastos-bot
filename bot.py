import os
import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import gspread
import json
import openai
from datetime import datetime

# 1. Cargar variables de entorno
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
URL_HOJA = os.environ.get("URL_HOJA")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")

# Configurar OpenAI
openai.api_key = OPENAI_API_KEY

# Configurar Google Sheets
creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
gc = gspread.service_account_from_dict(creds_dict)
sh = gc.open_by_url(URL_HOJA)
worksheet = sh.get_worksheet(0)

# Inicializar Flask
app = Flask(__name__)

# Inicializar Telegram Application
app_telegram = Application.builder().token(TELEGRAM_TOKEN).build()

# Inicializamos el bot al arrancar el script
async def setup_telegram():
    await app_telegram.initialize()
    await app_telegram.start()

asyncio.run(setup_telegram())

# Función que procesa los mensajes del usuario
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    chat_id = update.message.chat_id
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")

    # Prompt ultra estructurado para asegurar un JSON impecable
    prompt = f"""
    Eres un asistente contable. Analiza el siguiente texto de gasto: "{texto_usuario}"
    Devuelve un JSON estrictamente con estas 6 claves y tipos de datos:
    {{
      "fecha": "{fecha_hoy}",
      "miembro": "Jorge",
      "importe": 0.0,
      "metodo_pago": "Tarjeta",
      "categoria": "Otros",
      "concepto": "{texto_usuario}"
    }}
    Rellena los valores correctamente extrayéndolos del texto. Si falta el importe, pon 0. Si falta el método de pago, pon Tarjeta. Si falta el miembro, pon Jorge.
    """

    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        resultado_json = response.choices[0].message.content.strip()
        
        if resultado_json.startswith("```json"):
            resultado_json = resultado_json[7:-3].strip()
        elif resultado_json.startswith("```"):
            resultado_json = resultado_json[3:-3].strip()

        datos = json.loads(resultado_json)

        # Forzar valores limpios y orden estricto para las 6 columnas:
        # A: Fecha, B: Miembro, C: Importe, D: Metodo_pago, E: Categoría, F: Concepto
        val_fecha = str(datos.get("fecha", fecha_hoy))
        val_miembro = str(datos.get("miembro", "Jorge"))
        
        # Asegurar que el importe sea un número limpio
        try:
            val_importe = float(datos.get("importe", 0))
        except:
            val_importe = 0.0

        val_metodo = str(datos.get("metodo_pago", "Tarjeta"))
        val_cat = str(datos.get("categoria", "Otros"))
        val_concepto = str(datos.get("concepto", texto_usuario))

        fila = [val_fecha, val_miembro, val_importe, val_metodo, val_cat, val_concepto]
        worksheet.append_row(fila)

        # Confirmación por Telegram
        respuesta_texto = (
            f"✅ **Gasto registrado**\n"
            f"• **Fecha:** {val_fecha}\n"
            f"• **Miembro:** {val_miembro}\n"
            f"• **Importe:** {val_importe} €\n"
            f"• **Método:** {val_metodo}\n"
            f"• **Categoría:** {val_cat}\n"
            f"• **Concepto:** {val_concepto}"
        )
        await context.bot.send_message(chat_id=chat_id, text=respuesta_texto, parse_mode="Markdown")

    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Hubo un error procesando el gasto: {str(e)}")

# Registrar manejador
app_telegram.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

@app.route("/", methods=["GET"])
def index():
    return "Bot de Gastos Activo y en Línea", 200

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True), app_telegram.bot)
        
        async def run_update():
            await app_telegram.process_update(update)

        asyncio.run(run_update())
        return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
