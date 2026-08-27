# -*- coding: utf-8 -*-
"""
Escribe el guion del dia con IA (Gemini) siguiendo PROMPT-MAESTRO.md.
Se activa solo si existe GEMINI_API_KEY. Si falla algo, devuelve None
y el sistema usa el banco de guiones (scripts.json) como reserva.
Devuelve un dict con el mismo formato que usa generate.py.
"""
import os, sys, json, datetime, random, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("GEMINI_MODEL", "").strip()  # vacio = autodetectar modelo valido
# Candidatos por si ListModels no responde (de mas nuevo a mas compatible).
_MODEL_CANDIDATES = [
    "gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash",
    "gemini-2.5-flash-lite", "gemini-2.0-flash-001", "gemini-1.5-flash",
]
BGS = ["blue", "green", "orange", "purple", "teal", "red"]
# AMBITOS del dinero que rotan por dia (se usan como "a evitar hoy" para forzar variedad)
TEMAS = [
    "la inflacion", "los bancos", "el ahorro", "las deudas", "el interes compuesto",
    "el precio de la vivienda", "las criptomonedas", "la psicologia del gasto",
    "los impuestos", "la jubilacion", "el dinero y la felicidad", "las burbujas economicas",
    "el credito y las tarjetas", "el marketing que te hace gastar", "los ricos y la clase media",
    "el valor del dinero con el tiempo", "las suscripciones que no usas",
]
# ESTILOS que se intercalan cada dia (asombro y aspiracion, no consejo)
FORMATOS = [
    "por que sube el precio de algo cotidiano, explicado con asombro",
    "como piensan los ricos con el dinero (mentalidad, no consejo)",
    "el truco psicologico que te hace gastar de mas sin darte cuenta",
    "la historia sorprendente detras de un billete, una crisis o una moneda",
    "el dato economico que asusta, contado con intriga",
    "como funciona DE VERDAD algo del dinero que todos usamos",
]

SCHEMA_INSTRUCCION = """
Devuelve UNICAMENTE un JSON valido (sin texto alrededor) con esta forma exacta:
{
  "title": "titulo intrigante y fiel, max 90 caracteres, puede llevar 1 emoji y #shorts",
  "description": "1-2 frases que despierten curiosidad. Anade al final: 'Contenido divulgativo, no es consejo financiero.'",
  "hashtags": ["Shorts", "economia", "dinero", "finanzas"],  // 3 a 5, sin '#', el primero SIEMPRE 'Shorts'
  "bg": "uno de: blue, teal, purple, green (tonos sobrios y modernos)",
  "broll": "2-4 palabras EN INGLES de escena de dinero/ciudad (ej: 'money city finance')",
  "broll_list": ["3 o 4 escenas EN INGLES, en orden (ej: 'stacks of coins closeup', 'city skyscrapers dusk', 'stock chart screen glow')"],
  "ai_disclosure": false,
  "lines": [
    {"voice": "frase corta y clara (numeros en palabras: 'mil euros', no '1000')",
     "cap": "subtitulo MUY corto en pantalla (2-4 palabras, puede llevar cifras)"}
  ]
}
Reglas del guion (formato 'Lo que el dinero esconde'):
- Entre 8 y 11 lineas. Explica UNA idea del dinero con asombro y aspiracion (el video dura 30-45 s).
- NO ES UNA LISTA NI UN CONSEJO: prohibido 'sabias que', 'top 3', y prohibido recomendar inversiones o decir a la gente que hacer con su dinero. Se revela como funciona algo, no se aconseja.
- RIGOR: datos ciertos y generales; nada de promesas de hacerse rico ni recomendaciones concretas de inversion.
- APERTURA (linea 1, VARIADA cada dia, nunca identica a la de ayer): un gancho de curiosidad sobre el dinero. Ej: 'Nadie te explica esto del dinero, y lo cambia todo.'
- CIERRE (ultima linea, VARIADO cada dia): remata con una idea que invite a pensar. Ej: 'El dinero funciona asi. Lo sabias?'
- Tono divulgativo, con autoridad e intriga. 'cap' sin emojis. 'voice' con numeros en letras.
- Espanol de Espana. NUNCA consejo financiero personalizado.
"""
def _run_seed():
    try:
        return int(os.environ.get("GITHUB_RUN_NUMBER", "0"))
    except ValueError:
        return 0

def _pick(lst, salt=0):
    y = datetime.date.today().timetuple().tm_yday
    return lst[(y + _run_seed() + salt) % len(lst)]

def _list_models(key):
    """Pregunta a Google que modelos existen de verdad para esta clave."""
    try:
        url = ("https://generativelanguage.googleapis.com/v1beta/models"
               f"?key={key}&pageSize=200")
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.loads(r.read().decode())
        out = []
        for m in data.get("models", []):
            if "generateContent" in (m.get("supportedGenerationMethods") or []):
                out.append(m.get("name", "").replace("models/", ""))
        return out
    except Exception:
        return []

def _model_order(key):
    """Orden a probar: modelo forzado por env -> candidatos -> los reales
    de la cuenta (priorizando 'flash')."""
    order = []
    if MODEL:
        order.append(MODEL)
    for m in _MODEL_CANDIDATES:
        if m not in order:
            order.append(m)
    disc = _list_models(key)
    for m in disc:
        if "flash" in m and m not in order:
            order.append(m)
    for m in disc:
        if m not in order:
            order.append(m)
    return order

def _post_generate(model, prompt, key):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.95, "responseMimeType": "application/json"},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode())
    return data["candidates"][0]["content"]["parts"][0]["text"]

def _call_gemini(prompt, key):
    """Prueba varios modelos y usa el primero que responda (sobrevive a que
    Google jubile un modelo). Solo falla si NINGUNO funciona."""
    last = None
    for model in _model_order(key):
        try:
            txt = _post_generate(model, prompt, key)
            sys.stderr.write(f"[ai] modelo usado: {model}\n")
            return txt
        except Exception as e:
            last = e
    raise RuntimeError(f"ningun modelo Gemini respondio: {last}")

def _validate(s):
    assert isinstance(s.get("lines"), list) and 6 <= len(s["lines"]) <= 16, "lineas fuera de rango"
    for ln in s["lines"]:
        assert ln.get("voice"), "linea sin voz"
        ln.setdefault("cap", "")
    s.setdefault("bg", "blue")
    if s["bg"] not in BGS:
        s["bg"] = "blue"
    hs = [h.lstrip("#") for h in s.get("hashtags", []) if h.strip()]
    if not hs or hs[0].lower() != "shorts":
        hs = ["Shorts"] + [h for h in hs if h.lower() != "shorts"]
    s["hashtags"] = hs[:5]
    assert s.get("title"), "sin titulo"
    s.setdefault("description", "Lo que nadie te explica del dinero. Contenido divulgativo, no es consejo financiero.")
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
        master = "Eres un divulgador de economia para YouTube Shorts en espanol que revela como funciona el dinero con asombro, sin dar consejo financiero."
    formato = random.choice(FORMATOS)
    hoy = datetime.date.today().isoformat()
    # Usamos TEMAS solo como "lo obvio a EVITAR", para empujar novedad
    evitar = ", ".join(random.sample(TEMAS, min(6, len(TEMAS)))) if TEMAS else ""
    seed = _run_seed()
    prompt = (master
              + f"\n\n---\nTAREA DE HOY ({hoy}):\n"
              + "REVELA algo sorprendente sobre el dinero o la economia, con asombro y "
                "aspiracion. Elige tu mismo el tema; nada de aconsejar que hacer con el dinero.\n"
              + (f"Para forzar variedad, HOY evita estos ambitos (elige otro): {evitar}.\n" if evitar else "")
              + f"Desarrollalo con este ESTILO de hoy: {formato}.\n"
              + "Apertura y cierre VARIADOS (nunca los de ayer); titulo y descripcion UNICOS de hoy. Que HOY se note claramente distinto a cualquier dia anterior. Divulgacion con intriga, NO consejo financiero.\n"
              + SCHEMA_INSTRUCCION)
    try:
        raw = _call_gemini(prompt, key)
        s = json.loads(raw)
        s = _validate(s)
        return s
    except Exception as e:
        sys.stderr.write(f"[ai] no se pudo generar con IA ({e}); se usara el banco.\n")
        return None

if __name__ == "__main__":
    import json as _j
    s = generate()
    print(_j.dumps(s, ensure_ascii=False, indent=2) if s else "None (sin GEMINI_API_KEY o error)")
