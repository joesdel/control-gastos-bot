import os
import json
import re
from datetime import datetime
from flask import Flask, request
import requests
import gspread
import openai

# 1. Variables de entorno
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
URL_HOJA = os.environ.get("URL_HOJA")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")

# Nombres exactos de las pestañas en Google Sheets
NOMBRE_PESTANA_GASTOS = "Gastos"
NOMBRE_PESTANA_PRESUPUESTO = "Presupuesto familiar 2026"

# 2. Clientes
openai.api_key = OPENAI_API_KEY
creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
gc = gspread.service_account_from_dict(creds_dict)
sh = gc.open_by_url(URL_HOJA)

# Pestaña de registro de gastos diarios
hoja_gastos = sh.worksheet(NOMBRE_PESTANA_GASTOS)

# Respaldo de seguridad por si la pestaña de presupuesto no respondiera en un momento puntual
FALLBACK_PRESUPUESTOS = {
    "Supermercados, Alimentación e Higiene": {"mensual": 1200.00, "anual": 14400.00, "regla": "Mercadona, Lidl, Charter, fruterías, carnicerías, limpieza/higiene."},
    "Ocio, Bares y Restaurantes (Jorge & Paloma)": {"mensual": 320.00, "anual": 3840.00, "regla": "Bares (ej. Bar Emiliano) y restaurantes de fin de semana."},
    "Viajes y Escapadas Anuales": {"mensual": 250.00, "anual": 3000.00, "regla": "Booking, aerolíneas, hoteles y transporte en destino."},
    "Empleada del Hogar (Salario + Seg. Social)": {"mensual": 315.00, "anual": 3780.00, "regla": "Pagos periódicos a empleada del hogar y cargos TGSS."},
    "Gastos de Trabajo Jorge": {"mensual": 100.00, "anual": 1200.00, "regla": "Partida cerrada (cafés, almuerzos, comidas entre semana de Jorge)."},
    "Gastos de Trabajo Paloma": {"mensual": 80.00, "anual": 960.00, "regla": "Partida cerrada (cafés, almuerzos, comidas entre semana de Paloma)."},
    "Asignación + Gastos Álvaro": {"mensual": 150.00, "anual": 1800.00, "regla": "Partida cerrada vía Bizum semanal; no se desglosa destino."},
    "Gastos Médicos y Farmacia": {"mensual": 125.00, "anual": 1500.00, "regla": "Farmacias, clínicas (ej. Clínica Guallart) y dentistas."},
    "Estética y Peluquería Paloma + peluquería Jorge, Adrián y Álvaro": {"mensual": 180.00, "anual": 2160.00, "regla": "Estética y peluquería familiar."},
    "Ropa": {"mensual": 245.00, "anual": 2940.00, "regla": "Ropa de Jorge, Paloma, Álvaro y Adrián."},
    "Reparaciones y Mantenimiento Casas": {"mensual": 215.00, "anual": 2580.00, "regla": "Reparaciones y mantenimiento de Massalfassar y Cortes."},
    "Suministros (Luz, Gas, Agua, Telecomunicaciones, gasolina para el coche) + Comunidad de propietarios": {"mensual": 400.00, "anual": 4800.00, "regla": "Luz, gas, agua, Digi, gasolina/recargas coche y comunidad."},
    "Seguros (Coches y Viviendas)": {"mensual": 120.00, "anual": 1440.00, "regla": "Seguros de coches (BYD) y viviendas (Zurich, Fidelidade)."},
    "Impuestos Locales (IBI y Basuras)": {"mensual": 80.00, "anual": 960.00, "regla": "IBI y basuras de Massalfassar y Cortes."},
    "Menaje, Mobiliario, Gimnasio e Imprevistos": {"mensual": 220.00, "anual": 2640.00, "regla": "Colchones, mobiliario, gimnasio de Jorge (40 €) e imprevistos."}
}

app = Flask(__name__)

def parsear_importe(valor):
    if valor is None:
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    s = str(valor).replace("€", "").replace("EUR", "").strip()
    if not s or s == "-":
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    nums = re.findall(r"[-+]?\d*\.\d+|\d+", s)
    return float(nums[0]) if nums else 0.0

def obtener_presupuestos_desde_hoja():
    """Lee dinámicamente los límites mensuales y anuales desde 'Presupuesto familiar 2026'."""
    try:
        pestana = sh.worksheet(NOMBRE_PESTANA_PRESUPUESTO)
        filas = pestana.get_all_values()
        if not filas or len(filas) < 2:
            return FALLBACK_PRESUPUESTOS

        cabeceras = [c.strip().lower() for c in filas[0]]

        idx_cat = next((i for i, h in enumerate(cabeceras) if "concepto" in h or "categor" in h), 0)
        idx_mensual = next((i for i, h in enumerate(cabeceras) if "mensual" in h or "mes" in h), 1)
        idx_anual = next((i for i, h in enumerate(cabeceras) if "anual" in h or ("a" in h and "o" in h)), 2)
        idx_regla = next((i for i, h in enumerate(cabeceras) if "criterio" in h or "automat" in h or "regla" in h or "bot" in h), None)

        presupuestos = {}
        for fila in filas[1:]:
            if len(fila) <= max(idx_cat, idx_mensual, idx_anual):
                continue
            cat = fila[idx_cat].strip()
            if not cat or cat.upper().startswith("TOTAL"):
                continue

            mensual = parsear_importe(fila[idx_mensual])
            anual = parsear_importe(fila[idx_anual])
            if anual == 0.0 and mensual > 0.0:
                anual = round(mensual * 12, 2)
            if mensual == 0.0 and anual > 0.0:
                mensual = round(anual / 12, 2)

            regla = fila[idx_regla].strip() if (idx_regla is not None and idx_regla < len(fila)) else ""
            if not regla and cat in FALLBACK_PRESUPUESTOS:
                regla = FALLBACK_PRESUPUESTOS[cat]["regla"]

            presupuestos[cat] = {
                "mensual": round(mensual, 2),
                "anual": round(anual, 2),
                "regla": regla
            }

        return presupuestos if presupuestos else FALLBACK_PRESUPUESTOS
    except Exception:
        return FALLBACK_PRESUPUESTOS

def enviar_mensaje_telegram(chat_id, texto):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload, timeout=15)

@app.route("/", methods=["GET"])
def index():
    return "Bot Control EscribaCarcel Activo (Pestaña Gastos + Presupuesto familiar 2026)", 200

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json(force=True)

    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        texto_usuario = data["message"]["text"].strip()
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        mes_actual = datetime.now().strftime("%Y-%m")
        anio_actual = datetime.now().strftime("%Y")

        presupuestos_activos = obtener_presupuestos_desde_hoja()
        cat_por_defecto = (
            "Menaje, Mobiliario, Gimnasio e Imprevistos"
            if "Menaje, Mobiliario, Gimnasio e Imprevistos" in presupuestos_activos
            else list(presupuestos_activos.keys())[-1]
        )

        catalogo_str = "\n".join(
            [f'- "{cat}" (Límite mensual: {info["mensual"]:.2f} € | Anual: {info["anual"]:.2f} €): {info["regla"]}'
             for cat, info in presupuestos_activos.items()]
        )

        prompt = f"""
Eres el director financiero familiar de Jorge y Paloma. Clasifica el siguiente gasto en UNA de las categorías oficiales.
Mensaje del usuario: "{texto_usuario}"

Reglas clave:
1. Extrae el importe en euros como número decimal (usa punto, ej. 24.50).
2. Si el mensaje menciona a "Paloma" o "Jorge" en contexto laboral/café/almuerzo/menú entre semana, prioriza "Gastos de Trabajo Jorge" o "Gastos de Trabajo Paloma" frente a "Ocio, Bares y Restaurantes (Jorge & Paloma)".
3. Si el mensaje menciona "Álvaro" con paga/bizum/asignación, usa "Asignación + Gastos Álvaro".
4. Si no encaja claramente o es un imprevisto/mobiliario/gimnasio, usa "{cat_por_defecto}".
5. El campo "categoria" DEBE ser idéntico a uno de los nombres entre comillas de la lista.

Categorías disponibles:
{catalogo_str}

Devuelve ÚNICAMENTE un JSON válido sin markdown ni explicaciones:
{{
  "fecha": "{fecha_hoy}",
  "miembro": "Jorge",
  "importe": 0.0,
  "metodo_pago": "Tarjeta",
  "categoria": "Nombre exacto de la categoría",
  "concepto": "{texto_usuario}"
}}
"""

        try:
            resp = openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )
            raw = resp.choices[0].message.content.strip()
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
            datos = json.loads(raw)

            val_fecha = str(datos.get("fecha", fecha_hoy))
            val_miembro = str(datos.get("miembro", "Jorge"))
            val_importe = round(parsear_importe(datos.get("importe", 0.0)), 2)
            val_metodo = str(datos.get("metodo_pago", "Tarjeta"))
            val_cat = str(datos.get("categoria", cat_por_defecto))
            if val_cat not in presupuestos_activos:
                val_cat = cat_por_defecto
            val_concepto = str(datos.get("concepto", texto_usuario))

            lim_mensual = presupuestos_activos[val_cat]["mensual"]
            lim_anual = presupuestos_activos[val_cat]["anual"]

            registros = hoja_gastos.get_all_records()
            gastado_mes = val_importe if val_fecha.startswith(mes_actual) else 0.0
            gastado_anio = val_importe if val_fecha.startswith(anio_actual) else 0.0

            for reg in registros:
                f_reg = str(reg.get("Fecha", reg.get("FECHA", ""))).strip()
                c_reg = str(reg.get("Categoría", reg.get("CATEGORÍA", ""))).strip()
                if c_reg == val_cat:
                    imp_reg = parsear_importe(reg.get("Importe", reg.get("IMPORTE", 0)))
                    if f_reg.startswith(mes_actual):
                        gastado_mes += imp_reg
                    if f_reg.startswith(anio_actual):
                        gastado_anio += imp_reg

            queda_mensual = round(lim_mensual - gastado_mes, 2)
            queda_anual = round(lim_anual - gastado_anio, 2)

            fila = [
                val_fecha,
                val_miembro,
                val_importe,
                val_metodo,
                val_cat,
                val_concepto,
                queda_mensual,
                queda_anual
            ]
            hoja_gastos.append_row(fila)

            emoji_m = "🟢" if queda_mensual >= 0 else "🔴"
            emoji_a = "🟢" if queda_anual >= 0 else "🔴"

            mensaje = (
                f"✅ *Gasto registrado*\n"
                f"• *Fecha:* {val_fecha}\n"
                f"• *Miembro:* {val_miembro}\n"
                f"• *Importe:* {val_importe:.2f} €\n"
                f"• *Método:* {val_metodo}\n"
                f"• *Categoría:* {val_cat}\n"
                f"• *Concepto:* {val_concepto}\n\n"
                f"📊 *Presupuesto ({mes_actual} / {anio_actual}):*\n"
                f"• *Mes:* {gastado_mes:.2f} € / {lim_mensual:.2f} € → {emoji_m} *Quedan {queda_mensual:.2f} €*\n"
                f"• *Año:* {gastado_anio:.2f} € / {lim_anual:.2f} € → {emoji_a} *Quedan {queda_anual:.2f} €*"
            )
            enviar_mensaje_telegram(chat_id, mensaje)

        except Exception as e:
            enviar_mensaje_telegram(chat_id, f"⚠️ Error al registrar el gasto: `{str(e)}`")

    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
