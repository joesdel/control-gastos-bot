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

# Inicializamos el bot al arrancar el script para que esté listo desde el primer segundo
async def setup_telegram():
    await app_telegram.initialize()
    await app_telegram.start()

asyncio.run(setup_telegram())

# Función que procesa los mensajes del usuario
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text
    chat_id = update.message.chat_id

    # Fecha de hoy por defecto en formato YYYY-MM-DD
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")

    # 1. Usar OpenAI para extraer todos los campos de tus 6 columnas de forma inteligente
    prompt = f"""
    Eres un director financiero inteligente. Extrae de la siguiente frase de gasto los siguientes datos en formato JSON estricto:
    - "fecha": (Si no se especifica otra fecha en el texto, usa exactamente "{fecha_hoy}").
    - "miembro": (Quién hace el gasto, ej: Jorge, Paloma, etc. Si no se especifica, pon "Jorge" por defecto o déjalo vacío).
    - "importe": (Número con decimales si procede, solo el número).
    - "metodo_pago": (Ej: Tarjeta, Efectivo, Bizum, etc. Si no se especifica, pon "Tarjeta").
    - "categoria": (Ej: Alimentación, Casa, Ocio, Transporte, Gastos Trabajo, Otros, etc.).
    - "concepto": (Descripción breve de qué es el gasto).

    Frase del usuario: "{texto_usuario}"
    
    Devuelve estrictamente un objeto JSON válido con estas claves exactas: fecha, miembro, importe, metodo_pago, categoria, concepto.
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

        # 2. Guardar en Google Sheets respetando estrictamente el orden de tus columnas:
        # A: Fecha, B: Miembro, C: Importe, D: Metodo_pago, E: Categoría, F: Concepto
        fila = [
            datos.get("fecha", fecha_hoy),
            datos.get("miembro", "Jorge"),
            datos.get("importe", 0),
            datos.get("metodo_pago", "Tarjeta"),
            datos.get("categoria", "Otros"),
            datos.get("concepto", texto_usuario)
        ]
        worksheet.append_row(fila)

        # 3. Confirmar al usuario por Telegram de forma limpia y detallada
        respuesta_texto = (
            f"✅ **Gasto registrado correctamente**\n"
            f"• **Fecha:** {datos.get('fecha')}\n"
            f"• **Miembro:** {datos.get('miembro')}\n"
            f"• **Importe:** {datos.get('importe')} €\n"
            f"• **Método:** {datos.get('metodo_pago')}\n"
            f"• **Categoría:** {datos.get('categoria')}\n"
            f"• **Concepto:** {datos.get('concepto')}"
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
