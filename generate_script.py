# -*- coding: utf-8 -*-
"""
Escribe el guion del día con IA (Gemini) siguiendo PROMPT-MAESTRO.md.
Se activa solo si existe GEMINI_API_KEY. Si falla algo, devuelve None
y el sistema usa el banco de guiones (scripts.json) como reserva.
Devuelve un dict con el mismo formato que usa generate.py.
"""
import os, sys, json, datetime, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
BGS = ["blue", "green", "orange", "purple", "teal", "red"]

# Temas y formatos que rotan por día para no repetir (anti "contenido inauténtico")
TEMAS = [
    "el interés compuesto", "la inflación y por qué el dinero pierde valor",
    "el fondo de emergencia", "deuda buena vs deuda mala", "el gasto hormiga",
    "activos vs pasivos", "el peligro del pago aplazado de la tarjeta",
    "la diversificación al invertir", "pagarse a uno mismo primero",
    "la regla 50/30/20", "el coste de oportunidad", "qué es un ETF (fácil)",
    "por qué empezar a invertir pronto", "presupuesto mensual sencillo",
    "cómo funcionan los impuestos básicos", "ahorrar en pequeñas fugas de dinero",
    "la mentalidad de los que ahorran", "qué es la rentabilidad",
    "por qué no hay que endeudarse para aparentar", "la magia de automatizar el ahorro",
]
FORMATOS = [
    "mito vs realidad", "un dato sorprendente con ejemplo numérico",
    "el error común que casi todos cometen", "top 3 rápido",
    "esto no te lo cuentan", "comparativa antes vs después",
    "una pregunta que pica la curiosidad y su respuesta",
]

SCHEMA_INSTRUCCION = """
Devuelve ÚNICAMENTE un JSON válido (sin texto alrededor) con esta forma exacta:
{
  "title": "título honesto y con gancho, máx 90 caracteres, puede llevar 1 emoji y #shorts",
  "description": "1-2 frases de valor + CTA. Incluye SIEMPRE al final: '⚠️ Contenido educativo, no es asesoramiento financiero.'",
  "hashtags": ["Shorts", "economia", "...", "..."],  // 3 a 5, sin '#', el primero SIEMPRE 'Shorts'
  "bg": "uno de: blue, green, orange, purple, teal, red",
  "broll": "2-4 palabras EN INGLÉS para buscar metraje de archivo (ej: 'money coins saving')",
  "ai_disclosure": false,  // true solo si el contenido simula algo real que pueda confundir
  "lines": [
    {"voice": "frase corta que se narra (con números en palabras: 'cien euros', no '100')",
     "cap": "subtítulo MUY corto en pantalla (2-4 palabras, puede llevar cifras: '100€')"}
  ]
}
Reglas del guion:
- Entre 10 y 13 líneas. Cada 'voice' es una frase corta y natural (el vídeo debe durar 20-40 s).
- La PRIMERA línea es el gancho: sin saludos ni intro, engancha en el primer segundo.
- La ÚLTIMA línea es el CTA: invita a seguir ("Sígueme para más economía sin humo") o a comentar.
- 'cap' nunca lleva emojis (la fuente no los dibuja). 'voice' escribe los números con letras.
- Español de España, cercano y claro. Aporta un dato o ejemplo concreto.
"""

def _pick(lst):
    y = datetime.date.today().timetuple().tm_yday
    return lst[y % len(lst)]

def _call_gemini(prompt, key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={key}"
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.95, "responseMimeType": "application/json"},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode())
    return data["candidates"][0]["content"]["parts"][0]["text"]

def _validate(s):
    assert isinstance(s.get("lines"), list) and 6 <= len(s["lines"]) <= 16, "líneas fuera de rango"
    for ln in s["lines"]:
        assert ln.get("voice"), "línea sin voz"
        ln.setdefault("cap", "")
    s.setdefault("bg", "blue")
    if s["bg"] not in BGS:
        s["bg"] = "blue"
    hs = [h.lstrip("#") for h in s.get("hashtags", []) if h.strip()]
    if not hs or hs[0].lower() != "shorts":
        hs = ["Shorts"] + [h for h in hs if h.lower() != "shorts"]
    s["hashtags"] = hs[:5]
    assert s.get("title"), "sin título"
    s.setdefault("description", "⚠️ Contenido educativo, no es asesoramiento financiero.")
    s["id"] = "ia-" + datetime.date.today().isoformat()
    s.pop("chart", None)
    return s

def generate():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    try:
        master = open(os.path.join(BASE, "PROMPT-MAESTRO.md"), encoding="utf-8").read()
    except Exception:
        master = "Eres un productor experto de YouTube Shorts de economía en español."
    tema, formato = _pick(TEMAS), _pick(FORMATOS)
    prompt = (master
              + "\n\n---\nTAREA DE HOY:\n"
              + f"Crea el Short de hoy sobre: {tema}. Formato: {formato}.\n"
              + "Cumple TODAS las reglas de arriba (cumplimiento primero, luego viralidad).\n"
              + SCHEMA_INSTRUCCION)
    try:
        raw = _call_gemini(prompt, key)
        s = json.loads(raw)
        s = _validate(s)
        return s
    except Exception as e:
        sys.stderr.write(f"[ai] no se pudo generar con IA ({e}); se usará el banco.\n")
        return None

if __name__ == "__main__":
    import json as _j
    s = generate()
    print(_j.dumps(s, ensure_ascii=False, indent=2) if s else "None (sin GEMINI_API_KEY o error)")
