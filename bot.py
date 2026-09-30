import os
import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import gspread
import json
import openai

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

# Inicializamos el bot al arrancar el script para que esté listo desde el primer segundo
async def setup_telegram():
    await app_telegram.initialize()
    await app_telegram.start()

asyncio.run(setup_telegram())

# Función que procesa los mensajes del usuario
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    chat_id = update.message.chat_id

    # 1. Usar OpenAI para extraer los datos estructurados del gasto
    prompt = f"""
    Extrae de la siguiente frase de gasto los siguientes datos en formato JSON:
    - "fecha" (si no se especifica, pon la de hoy o déjala vacía)
    - "concepto" (descripción breve)
    - "categoria" (ej: Alimentación, Casa, Ocio, Transporte, etc.)
    - "importe" (número con decimales si procede)

    Frase: "{texto_usuario}"
    Devuelve estrictamente un objeto JSON válido con las claves: fecha, concepto, categoria, importe.
    """

    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        resultado_json = response.choices[0].message.content.strip()
        
        # Limpiar posibles bloques de código markdown en la respuesta de OpenAI
        if resultado_json.startswith("```json"):
            resultado_json = resultado_json[7:-3].strip()
        elif resultado_json.startswith("```"):
            resultado_json = resultado_json[3:-3].strip()

        datos = json.loads(resultado_json)

        # 2. Guardar en Google Sheets
        fila = [
            datos.get("fecha", ""),
            datos.get("concepto", ""),
            datos.get("categoria", ""),
            datos.get("importe", 0)
        ]
        worksheet.append_row(fila)

        # 3. Confirmar al usuario por Telegram
        respuesta_texto = (
            f"✅ **Gasto registrado con éxito**\n"
            f"• Concepto: {datos.get('concepto')}\n"
            f"• Categoría: {datos.get('categoria')}\n"
            f"• Importe: {datos.get('importe')} €"
        )
        await context.bot.send_message(chat_id=chat_id, text=respuesta_texto, parse_mode="Markdown")

    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Hubo un error procesando el gasto: {str(e)}")

# Registrar el manejador de mensajes en Telegram
app_telegram.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# Ruta principal de comprobación web
@app.route("/", methods=["GET"])
def index():
    return "Bot de Gastos Activo y en Línea", 200

# Ruta del Webhook que recibe las peticiones de Telegram
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
