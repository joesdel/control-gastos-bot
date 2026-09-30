import os
import json
import re
from flask import Flask, request
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters
from openai import OpenAI
import asyncio

# Credenciales y configuración leídas desde la nube de forma segura
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
NOMBRE_HOJA_GOOGLE = "Control_Gastos_2026"
URL_HOJA = os.environ.get("URL_HOJA")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")

# Inicializar IA y conexión con Google Sheets
client_ai = OpenAI(api_key=OPENAI_API_KEY)

cleaned_json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', GOOGLE_CREDENTIALS_JSON)
creds_dict = json.loads(cleaned_json_str)

scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
gc = gspread.authorize(creds)
sheet = gc.open_by_url(URL_HOJA).worksheet("Gastos")

# Configurar Telegram
app_telegram = Application.builder().token(TELEGRAM_TOKEN).build()

def procesar_texto_con_ia(texto_usuario):
    prompt_sistema = """
    Eres un asistente contable familiar. Analiza el mensaje recibido y extrae los datos del gasto.
    
    Categorías válidas:
    - Supermercado
    - Ocio Jorge y Paloma
    - Médico
    - Ropa
    - Gasolina
    - Limpieza / Reparaciones
    - Gastos Trabajo
    - Material escolar / Transporte / Psicólogo
    - Otros

    Métodos válidos: Efectivo, Tarjeta.
    
    Devuelve ÚNICAMENTE un objeto JSON estricto con esta estructura:
    {
        "importe": float,
        "metodo_pago": "Efectivo" o "Tarjeta",
        "categoria": "string",
        "concepto": "string"
    }
    """
    response = client_ai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": prompt_sistema},
            {"role": "user", "content": texto_usuario}
        ],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

async def responder_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_recibido = update.message.text
    usuario = update.message.from_user.first_name
    fecha_hoy = update.message.date.strftime("%Y-%m-%d")
    
    try:
        datos = procesar_texto_con_ia(texto_recibido)
        fila = [fecha_hoy, usuario, datos["importe"], datos["metodo_pago"], datos["categoria"], datos["concepto"]]
        sheet.append_row(fila)
        
        respuesta = (
            f"✅ *Gasto Registrado*\n\n"
            f"👤 *Usuario:* {usuario}\n"
            f"💰 *Importe:* {datos['importe']:.2f} €\n"
            f"💳 *Pago:* {datos['metodo_pago']}\n"
            f"📂 *Categoría:* {datos['categoria']}\n"
            f"📝 *Concepto:* {datos['concepto']}"
        )
        await update.message.reply_text(respuesta, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error al registrar: {str(e)}")

app_telegram.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), responder_mensaje))

# Servidor web Flask para escuchar a Telegram permanentemente
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "🤖 Bot de Gastos activo 24/7 en la nube."

@flask_app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), app_telegram.bot)
    asyncio.run(app_telegram.process_update(update))
    return 'ok'

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)
