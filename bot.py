import os
from flask import Flask, request
import requests
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

# Diccionario oficial de Presupuestos 2026
PRESUPUESTOS_2026 = {
    "Supermercados + frutería + carnicería": {"mensual": 800.00, "anual": 9600.00},
    "Prestamo coche": {"mensual": 525.83, "anual": 6309.96},
    "Ocio Jorge y Paloma (juntos los fines de semana)": {"mensual": 336.00, "anual": 4032.00},
    "Viaje anual 1 semana": {"mensual": 250.00, "anual": 3000.00},
    "Limpieza": {"mensual": 240.00, "anual": 2880.00},
    "Reparaciones Cortes": {"mensual": 120.00, "anual": 1440.00},
    "Gastos trabajo Jorge": {"mensual": 96.25, "anual": 962.50},
    "Gastos médicos, incluye dentista y medicamentos de todo tipo": {"mensual": 125.00, "anual": 1500.00},
    "Estética y otros Paloma": {"mensual": 125.00, "anual": 1500.00},
    "Reparaciones Massalfassar": {"mensual": 100.00, "anual": 1200.00},
    "Otros": {"mensual": 50.00, "anual": 600.00},
    "Seguridad Social": {"mensual": 83.50, "anual": 1002.00},
    "Gas Massalfassar": {"mensual": 100.00, "anual": 1200.00},
    "Sueldo Álvaro": {"mensual": 126.00, "anual": 1512.00},
    "Inglés Álvaro": {"mensual": 90.00, "anual": 900.00},
    "Ropa Paloma": {"mensual": 100.00, "anual": 1200.00},
    "Ropa Álvaro": {"mensual": 75.00, "anual": 900.00},
    "Gastos trabajo Paloma": {"mensual": 80.00, "anual": 960.00},
    "Teléfonos, WIFI y TV": {"mensual": 70.00, "anual": 840.00},
    "Psicólogo Álvaro": {"mensual": 40.00, "anual": 400.00},
    "Regalos cumpleaños / navidad varios": {"mensual": 120.00, "anual": 1440.00},
    "Seguro BYD": {"mensual": 54.17, "anual": 650.00},
    "Electricidad Massalfassar": {"mensual": 50.00, "anual": 600.00},
    "Agua Massalfassar": {"mensual": 50.00, "anual": 600.00},
    "Electricidad Cortes": {"mensual": 50.00, "anual": 600.00},
    "Gasolina Jorge": {"mensual": 50.00, "anual": 600.00},
    "Ropa Jorge": {"mensual": 50.00, "anual": 600.00},
    "IBI Massalfassar": {"mensual": 32.00, "anual": 384.00},
    "Peluquería Alvaro y Adrian": {"mensual": 30.00, "anual": 360.00},
    "Ropa Adrián": {"mensual": 50.00, "anual": 600.00},
    "Música Adrián": {"mensual": 70.00, "anual": 840.00},
    "Comunidad Massalfassar": {"mensual": 20.00, "anual": 240.00},
    "IBI Cortes": {"mensual": 18.70, "anual": 224.40},
    "Seguro casa Massalfassar": {"mensual": 25.00, "anual": 300.00},
    "Seguro casa Cortes": {"mensual": 20.00, "anual": 240.00},
    "Basura Massalfassar": {"mensual": 15.00, "anual": 180.00},
    "Peluqueria Jorge": {"mensual": 15.00, "anual": 180.00},
    "Ropa deporte Álvaro": {"mensual": 20.00, "anual": 240.00},
    "Material escolar Álvaro": {"mensual": 15.00, "anual": 180.00},
    "Transporte Álvaro": {"mensual": 20.00, "anual": 240.00},
    "Basura Cortes": {"mensual": 10.00, "anual": 120.00}
}

def enviar_mensaje_telegram(chat_id, texto):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

@app.route("/", methods=["GET"])
def index():
    return "Bot de Gastos Activo y en Línea", 200

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    
    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        texto_usuario = data["message"]["text"]
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        mes_actual = datetime.now().strftime("%Y-%m")
        anio_actual = datetime.now().strftime("%Y")

        lista_categorias_str = "\n".join([f"- {cat}" for cat in PRESUPUESTOS_2026.keys()])

        prompt = f"""
        Eres un director financiero experto. Analiza el siguiente texto de gasto: "{texto_usuario}"
        Elige OBLIGATORIAMENTE una categoría exacta de esta lista oficial:
        {lista_categorias_str}

        Devuelve un JSON estrictamente con estas claves:
        {{
          "fecha": "{fecha_hoy}",
          "miembro": "Jorge",
          "importe": 0.0,
          "metodo_pago": "Tarjeta",
          "categoria": "Categoría exacta de la lista",
          "concepto": "{texto_usuario}"
        }}
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

            val_fecha = str(datos.get("fecha", fecha_hoy))
            val_miembro = str(datos.get("miembro", "Jorge"))
            
            try:
                val_importe = float(datos.get("importe", 0))
            except:
                val_importe = 0.0

            val_metodo = str(datos.get("metodo_pago", "Tarjeta"))
            val_cat = str(datos.get("categoria", "Otros"))
            val_concepto = str(datos.get("concepto", texto_usuario))

            # 1. Leer registros previos para calcular acumulados
            registros = worksheet.get_all_records()
            gastado_mes = val_importe
            gastado_anual = val_importe

            for reg in registros:
                f_reg = str(reg.get("Fecha", ""))
                c_reg = str(reg.get("Categoría", ""))
                if c_reg.strip().lower() == val_cat.strip().lower():
                    try:
                        imp_reg = float(reg.get("Importe", 0))
                    except:
                        imp_reg = 0.0
                    
                    if f_reg.startswith(anio_actual):
                        gastado_anual += imp_reg
                    if f_reg.startswith(mes_actual):
                        gastado_mes += imp_reg

            presupuesto_info = PRESUPUESTOS_2026.get(val_cat, {"mensual": 50.0, "anual": 600.0})
            limite_mensual = presupuesto_info["mensual"]
            limite_anual = presupuesto_info["anual"]

            remanente_mensual = limite_mensual - gastado_mes
            remanente_anual = limite_anual - gastado_anual

            # 2. Guardar en las 8 columnas exactas de tu Google Sheet (A a H)
            fila = [
                val_fecha, 
                val_miembro, 
                val_importe, 
                val_metodo, 
                val_cat, 
                val_concepto, 
                round(remanente_mensual, 2), 
                round(remanente_anual, 2)
            ]
            worksheet.append_row(fila)

            # 3. Respuesta por Telegram
            estado_mes_emoji = "🟢" if remanente_mensual >= 0 else "🔴"
            estado_anual_emoji = "🟢" if remanente_anual >= 0 else "🔴"

            respuesta_texto = (
                f"✅ *Gasto registrado correctamente*\n\n"
                f"• *Fecha:* {val_fecha}\n"
                f"• *Miembro:* {val_miembro}\n"
                f"• *Importe:* {val_importe:.2f} €\n"
                f"• *Método:* {val_metodo}\n"
                f"• *Categoría:* {val_cat}\n"
                f"• *Concepto:* {val_concepto}\n\n"
                f"📊 *Estado Presupuestario ({val_cat}):*\n"
                f"• *Mes ({mes_actual}):* Gastado {gastado_mes:.2f}€ / Límite {limite_mensual:.2f}€\n"
                f"  Queda mensual: {estado_mes_emoji} *{remanente_mensual:.2f} €*\n"
                f"• *Año ({anio_actual}):* Gastado {gastado_anual:.2f}€ / Límite {limite_anual:.2f}€\n"
                f"  Queda anual: {estado_anual_emoji} *{remanente_anual:.2f} €*"
            )
            enviar_mensaje_telegram(chat_id, respuesta_texto)

        except Exception as e:
            enviar_mensaje_telegram(chat_id, f"Hubo un error procesando el gasto: {str(e)}")

    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
