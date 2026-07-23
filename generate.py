# -*- coding: utf-8 -*-
"""
Generador de Shorts de economía (100% gratis, sin servicios de pago).
Flujo: guion -> voz (edge-tts o espeak) -> subtítulos sincronizados ->
fondo con movimiento + gráfica -> vídeo vertical 1080x1920.

TTS_ENGINE=edge  -> voz neuronal (para GitHub Actions, buena calidad)
TTS_ENGINE=espeak-> voz offline (prueba de formato en local)
"""
import os, sys, json, subprocess, asyncio, tempfile, textwrap, math, hashlib
import urllib.request, urllib.parse, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
OUTPUT = os.path.join(BASE, "output")
MUSIC = os.path.join(BASE, "music")
os.makedirs(OUTPUT, exist_ok=True)

TTS_ENGINE = os.environ.get("TTS_ENGINE", "espeak")
EDGE_VOICE = os.environ.get("EDGE_VOICE", "es-ES-AlvaroNeural")
GAP = 0.07          # silencio entre frases (s) — ritmo ágil
FONT = "DejaVu Sans"

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write("CMD FAIL: " + " ".join(cmd[:6]) + "...\n" + r.stderr[-1500:] + "\n")
        raise SystemExit(1)
    return r

def dur_of(path):
    r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                        "-of","csv=p=0", path], capture_output=True, text=True)
    return float(r.stdout.strip())

# ---------- TTS ----------
def synth_espeak(text, out_wav):
    tmp = out_wav + ".raw.wav"
    run(["espeak-ng","-v","es","-s","166","-p","38","-w",tmp,text])
    run(["ffmpeg","-y","-loglevel","error","-i",tmp,"-ar","44100","-ac","2",out_wav])
    os.remove(tmp)

def synth_edge(text, out_wav):
    import edge_tts
    tmp_mp3 = out_wav + ".mp3"
    async def _go():
        c = edge_tts.Communicate(text, EDGE_VOICE, rate="+12%")
        await c.save(tmp_mp3)
    asyncio.run(_go())
    run(["ffmpeg","-y","-loglevel","error","-i",tmp_mp3,"-ar","44100","-ac","2",out_wav])
    os.remove(tmp_mp3)

def synth(text, out_wav):
    if TTS_ENGINE == "edge":
        synth_edge(text, out_wav)
    else:
        synth_espeak(text, out_wav)

# ---------- Subtítulos ASS ----------
def ass_time(t):
    cs = int(round(t*100))
    h = cs//360000; cs -= h*360000
    m = cs//6000;   cs -= m*6000
    s = cs//100;    cs -= s*100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def esc(t):
    return t.replace("\\","\\\\").replace("{","(").replace("}",")")

HL = "&H0037B6FF&"   # amarillo/ámbar para la palabra activa (BBGGRR)
WHITE = "&H00FFFFFF&"

def cap_word_events(cap, st, en, words_per_line=3):
    """Subtítulos animados: la palabra que se pronuncia se resalta y crece."""
    words = cap.split()
    if not words:
        return []
    weights = [len(w) + 1 for w in words]
    tot = sum(weights)
    dur = max(0.001, en - st)
    slices = []
    cur = st
    for wt in weights:
        wd = dur * wt / tot
        slices.append((cur, cur + wd))
        cur += wd
    evts = []
    for i, (ws, we) in enumerate(slices):
        toks = []
        for j, w in enumerate(words):
            if j > 0 and j % words_per_line == 0:
                toks.append("\\N")
            wtxt = esc(w.upper())
            if j == i:
                toks.append("{\\c" + HL + "\\fscx116\\fscy116}" + wtxt + "{\\c" + WHITE + "\\fscx100\\fscy100}")
            else:
                toks.append(wtxt)
        # unir con espacios pero sin espacio extra tras un salto de línea
        s = ""
        for k, tk in enumerate(toks):
            if tk == "\\N":
                s += "\\N"
            else:
                s += ("" if (k == 0 or toks[k-1] == "\\N") else " ") + tk
        fad = "{\\fad(90,0)}" if i == 0 else ""
        evts.append((ws, we, fad + s))
    return evts

def build_ass(events, path):
    # events: list of (start, end, caption_text, hidden)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{FONT},80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,1,0,1,6,3,2,80,80,720,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for (st, en, cap, hidden) in events:
        if hidden or not cap.strip():
            continue
        for (ws, we, txt) in cap_word_events(cap, st, en):
            lines.append(f"Dialogue: 0,{ass_time(ws)},{ass_time(we)},Main,,0,0,0,,{txt}")
    with open(path,"w",encoding="utf-8") as f:
        f.write("\n".join(lines))

# ---------- B-roll (Pexels, opcional y con reserva) ----------
def get_broll(query, workdir):
    """Descarga un vídeo vertical de Pexels si hay PEXELS_API_KEY.
    Devuelve la ruta local o None (si no hay clave, no hay red o falla algo)."""
    key = os.environ.get("PEXELS_API_KEY")
    if not key or not query:
        return None
    try:
        url = ("https://api.pexels.com/videos/search?"
               + urllib.parse.urlencode({"query": query, "orientation": "portrait",
                                         "per_page": 15, "size": "medium"}))
        req = urllib.request.Request(url, headers={"Authorization": key})
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode())
        vids = data.get("videos", [])
        if not vids:
            return None
        idx = datetime.date.today().timetuple().tm_yday % len(vids)
        vid = vids[idx]
        # elige un fichero vertical de ancho <= 1080 (o el menor disponible)
        files = [f for f in vid.get("video_files", []) if (f.get("height") or 0) >= (f.get("width") or 0)]
        files = files or vid.get("video_files", [])
        files.sort(key=lambda f: abs((f.get("width") or 1080) - 1080))
        link = files[0]["link"]
        dst = os.path.join(workdir, "broll.mp4")
        with urllib.request.urlopen(link, timeout=60) as r, open(dst, "wb") as f:
            f.write(r.read())
        if os.path.getsize(dst) > 10000:
            print(f"[broll] usando vídeo de Pexels: {query}")
            return dst
    except Exception as e:
        sys.stderr.write(f"[broll] aviso: no se pudo usar b-roll ({e}); uso degradado.\n")
    return None

# ---------- Render ----------
def build_video(script, out_path, workdir):
    lines = script["lines"]
    seg_wavs = []
    events = []
    t = 0.0
    sil = os.path.join(workdir,"sil.wav")
    run(["ffmpeg","-y","-loglevel","error","-f","lavfi","-i",
         "anullsrc=r=44100:cl=stereo","-t",str(GAP),sil])
    concat_list = os.path.join(workdir,"list.txt")
    parts = []
    for i, ln in enumerate(lines):
        voice = ln["voice"]
        cap = ln.get("cap", voice)
        w = os.path.join(workdir,f"seg{i:02d}.wav")
        synth(voice, w)
        d = dur_of(w)
        hidden = bool(ln.get("hide_caption"))
        events.append((t, t+d+GAP*0.6, cap, hidden))
        t += d + GAP
        parts.append(w); parts.append(sil)
    for p in parts:
        concat_list  # keep ref
    with open(concat_list,"w") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    full_wav = os.path.join(workdir,"full.wav")
    run(["ffmpeg","-y","-loglevel","error","-f","concat","-safe","0","-i",concat_list,
         "-c","copy",full_wav])
    total = dur_of(full_wav)

    ass = os.path.join(workdir,"caps.ass")
    build_ass(events, ass)

    bg = os.path.join(ASSETS, f"bg_{script.get('bg','blue')}.jpg")
    if not os.path.exists(bg):
        bg = os.path.join(ASSETS,"bg_blue.jpg")
    broll = get_broll(script.get("broll"), workdir)

    # gráfica opcional
    chart = script.get("chart")
    chart_path = os.path.join(ASSETS, chart) if chart else None
    has_chart = chart_path and os.path.exists(chart_path)

    # música opcional
    music_file = None
    if os.path.isdir(MUSIC):
        for fn in sorted(os.listdir(MUSIC)):
            if fn.lower().endswith((".mp3",".m4a",".wav",".ogg")):
                music_file = os.path.join(MUSIC, fn); break

    ass_esc = ass.replace("\\","/").replace(":","\\:")
    if broll:
        inputs = ["-stream_loop","-1","-i",broll]
    else:
        inputs = ["-loop","1","-i",bg]
    if has_chart:
        inputs += ["-loop","1","-i",chart_path]
    inputs += ["-i",full_wav]
    if music_file:
        inputs += ["-stream_loop","-1","-i",music_file]

    if broll:
        vf = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
              "eq=brightness=-0.06:saturation=1.08,"
              "drawbox=0:0:1080:1920:color=black@0.42:t=fill,"
              f"subtitles='{ass_esc}',setsar=1,fps=30")
    else:
        vf = (f"scale=1188:2112,zoompan=z='min(1.0+0.00045*in,1.12)':d=1:"
              f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30,"
              f"subtitles='{ass_esc}',setsar=1")

    fc = f"[0:v]{vf}[base];"
    if has_chart:
        cl = script.get("chart_lines")
        if cl:
            i0 = max(0, min(int(cl[0]), len(events)-1))
            i1 = max(0, min(int(cl[1]), len(events)-1))
            cs, ce = events[i0][0], events[i1][1]
        else:
            c = script.get("chart_window",[0,total])
            cs, ce = float(c[0]), float(c[1])
        fc += (f"[1:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
               f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,format=rgba,"
               f"fade=in:st={cs:.2f}:d=0.4:alpha=1,fade=out:st={ce-0.4:.2f}:d=0.4:alpha=1[cv];"
               f"[base][cv]overlay=0:0:enable='between(t,{cs:.2f},{ce:.2f})'[v]")
    else:
        fc += "[base]null[v]"

    # audio
    ai_voice = 2 if has_chart else 1
    if music_file:
        ai_mus = ai_voice + 1
        fc += (f";[{ai_voice}:a]volume=1.0[vo];[{ai_mus}:a]volume=0.10[mu];"
               f"[vo][mu]amix=inputs=2:duration=first:dropout_transition=0[a]")
        amap = "[a]"
    else:
        amap = f"{ai_voice}:a"

    cmd = ["ffmpeg","-y","-loglevel","error"] + inputs + [
        "-filter_complex",fc,"-map","[v]","-map",amap,
        "-t",f"{total:.2f}","-r","30",
        "-c:v","libx264","-preset","medium","-crf","20","-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","192k","-movflags","+faststart", out_path]
    run(cmd)
    return total

def pick_script(scripts, arg=None):
    if arg:
        for s in scripts:
            if s["id"] == arg:
                return s
    # rotación por día del año (sin estado): un guion distinto cada día,
    # recorriendo el banco en bucle. Añade más guiones para no repetir tan seguido.
    import datetime
    yday = datetime.date.today().timetuple().tm_yday
    return scripts[yday % len(scripts)]

def main():
    with open(os.path.join(BASE,"scripts.json"),encoding="utf-8") as f:
        scripts = json.load(f)
    arg = sys.argv[1] if len(sys.argv)>1 else None
    s = None
    if not arg and os.environ.get("GEMINI_API_KEY"):
        try:
            import generate_script
            s = generate_script.generate()
            if s:
                print("[generate] guion escrito por IA (Gemini)")
        except Exception as e:
            sys.stderr.write(f"[ai] error IA ({e}); uso banco.\n")
    if not s:
        s = pick_script(scripts, arg)
    print(f"[generate] guion: {s['id']}  voz: {TTS_ENGINE}")
    out = os.path.join(OUTPUT, f"{s['id']}.mp4")
    with tempfile.TemporaryDirectory() as wd:
        total = build_video(s, out, wd)
    meta = {
        "video": out,
        "title": s["title"],
        "description": s["description"].rstrip() + "\n\n" + " ".join("#"+h for h in s.get("hashtags",[])),
        "tags": s.get("hashtags",[]),
    }
    with open(os.path.join(OUTPUT, f"{s['id']}.json"),"w",encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUTPUT, "_latest.txt"),"w",encoding="utf-8") as f:
        f.write(s["id"])
    print(f"[generate] listo: {out}  ({total:.1f}s)")

if __name__ == "__main__":
    main()
