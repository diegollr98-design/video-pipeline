"""eval_sync.py — mide el ERROR DE SINCRONISMO voz-subtítulo de un vídeo generado.

Es la métrica primaria del gate `/eval`. Existe porque "el vídeo se generó" no
dice nada: los tres bugs graves de este repo produjeron MP4 completos y
reproducibles (subtítulos con +0,435 s de sesgo, 4 shorts con la misma historia,
historias con 0 comas). Lo que los delató fue medir.

CÓMO MIDE (y por qué así)
  - Transcribe el audio del vídeo FINAL con faster-whisper. Es una transcripción
    INDEPENDIENTE: no se comparan los timestamps del pipeline contra sí mismos,
    porque eso es auto-atestiguarse.
  - Lee el .ass generado y saca cada palabra con su `start`.
  - Empareja ambas secuencias con difflib sobre el texto normalizado.
  - error = t_ass - t_whisper.  SIGNO IMPORTANTE: negativo = el subtítulo va
    DELANTE de la voz, que es lo que el diseño quiere (el offset de audio es
    -100 ms a propósito).
  - Si se empareja menos del 85%, NO se da veredicto: el emparejado falló y el
    número no significa nada.

LÍMITE HONESTO, DECLARADO
  El referí es faster-whisper y el alineador del pipeline también usa Whisper
  (stable-ts sobre faster-whisper small). Comparten familia acústica, así que
  esta métrica NO puede arbitrar entre variantes de anclaje que solo difieran en
  cómo reparten los tiempos DENTRO de la frase — favorecería por construcción a
  la que más se parezca a Whisper. Para lo que sirve, y sirve bien, es para
  detectar REGRESIONES: un sesgo que se vuelve positivo, una media que se
  dispara, un desfase que crece. Ese es su trabajo en el gate.

USO
    python scripts/eval_sync.py <video.mp4> <subs.ass> [--model small] [--json out.json]
"""

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.utils import _find_exe  # noqa: E402


# ---------------------------------------------------------------- normalización
def _normaliza(palabra):
    """minúsculas, sin puntuación, sin tildes — para emparejar, no para mostrar."""
    txt = unicodedata.normalize("NFD", palabra.lower())
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9ñ]", "", txt)


# ---------------------------------------------------------------- lectura del ASS
_RE_DIALOGO = re.compile(
    r"^Dialogue:\s*[^,]*,([^,]*),([^,]*),(?:[^,]*,){6}(.*)$"
)


def _ass_time_a_segundos(t):
    h, m, s = t.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def lee_ass(path):
    """Devuelve [(palabra, start_segundos, end_segundos)] en orden de aparición.

    El `end` hace falta para medir HUECOS: comparar el start de un cue con el
    start del siguiente mide la DURACIÓN de la palabra, no el silencio que la
    sigue. (Ese error daba 73 "pausas fuera de puntuación" falsas.)
    """
    palabras = []
    with open(path, encoding="utf-8-sig") as f:
        for linea in f:
            m = _RE_DIALOGO.match(linea.strip())
            if not m:
                continue
            start = _ass_time_a_segundos(m.group(1))
            end = _ass_time_a_segundos(m.group(2))
            texto = m.group(3)
            texto = re.sub(r"\{[^}]*\}", "", texto)       # tags de override
            texto = texto.replace("\\N", " ").replace("\\n", " ")
            for w in texto.split():
                if _normaliza(w):
                    palabras.append((w, start, end))
    return palabras


# ---------------------------------------------------------------- transcripción
def extrae_audio(video_path):
    tmp = os.path.join(tempfile.gettempdir(), "eval_sync_audio.wav")
    cmd = [_find_exe("ffmpeg"), "-y", "-i", video_path,
           "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", tmp]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        # el final de stderr, no el principio: los primeros 500 son el banner
        raise RuntimeError(f"No se pudo extraer el audio: {r.stderr[-500:]}")
    return tmp


def transcribe(wav_path, model_size="small"):
    """Transcripción INDEPENDIENTE del audio final -> [(palabra, start)]."""
    from faster_whisper import WhisperModel

    modelo = WhisperModel(model_size, device="cpu", compute_type="int8")
    segmentos, _ = modelo.transcribe(
        wav_path, language="es", word_timestamps=True, vad_filter=False
    )
    palabras = []
    for seg in segmentos:
        for w in (seg.words or []):
            if _normaliza(w.word):
                palabras.append((w.word.strip(), float(w.start)))
    return palabras


# ---------------------------------------------------------------- emparejado
def empareja(ass_words, whisper_words):
    a = [_normaliza(w[0]) for w in ass_words]
    b = [_normaliza(w) for w, _ in whisper_words]
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    pares = []
    for i, j, n in sm.get_matching_blocks():
        for k in range(n):
            t_ass = ass_words[i + k][1]
            t_whisper = whisper_words[j + k][1]
            pares.append((ass_words[i + k][0], t_ass, t_whisper, t_ass - t_whisper))
    return pares


# ---------------------------------------------------------------- pausas del ASS
def pausas_fuera_de_puntuacion(ass_path, umbral=0.35):
    """HUECOS > umbral (fin de un cue -> inicio del siguiente) cuya palabra previa
    NO acaba en puntuación. Comprobación estructural sobre el .ass, sin audio.

    El hueco es `siguiente.start - previa.end`. Usar `siguiente.start -
    previa.start` mide la duración de la palabra y no un silencio.
    """
    palabras = lee_ass(ass_path)
    fuera = []
    for (w_prev, _, e_prev), (w_sig, s_sig, _) in zip(palabras, palabras[1:]):
        hueco = s_sig - e_prev
        if hueco > umbral and not w_prev.rstrip().endswith((",", ".", ";", ":", "!", "?", "…")):
            fuera.append({"tras": w_prev, "hueco": round(hueco, 3), "t": round(e_prev, 2)})
    return fuera


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="MP4 final del pipeline")
    ap.add_argument("ass", help="Fichero .ass de subtítulos generado")
    ap.add_argument("--model", default="small",
                    help="Modelo whisper del REFERÍ (small por defecto)")
    ap.add_argument("--json", help="Volcar el resultado a este fichero")
    ap.add_argument("--cobertura-min", type=float, default=0.85)
    args = ap.parse_args()

    for p in (args.video, args.ass):
        if not os.path.exists(p):
            print(f"ERROR: no existe {p}", file=sys.stderr)
            return 2

    ass_words = lee_ass(args.ass)
    if not ass_words:
        print(f"ERROR: no se leyó ninguna palabra de {args.ass}", file=sys.stderr)
        return 2

    wav = extrae_audio(args.video)
    whisper_words = transcribe(wav, args.model)

    pares = empareja(ass_words, whisper_words)
    n_emp, n_tot = len(pares), len(ass_words)
    cobertura = n_emp / n_tot if n_tot else 0.0

    errores = [e for _, _, _, e in pares]
    abs_err = [abs(e) for e in errores]
    res = {
        "video": args.video,
        "ass": args.ass,
        "modelo_referi": args.model,
        "n_palabras_ass": n_tot,
        "n_palabras_whisper": len(whisper_words),
        "n_emparejadas": n_emp,
        "cobertura": round(cobertura, 4),
        "error_medio_abs": round(sum(abs_err) / len(abs_err), 4) if abs_err else None,
        "error_max_abs": round(max(abs_err), 4) if abs_err else None,
        "sesgo": round(sum(errores) / len(errores), 4) if errores else None,
        "pausas_fuera_de_puntuacion": pausas_fuera_de_puntuacion(args.ass),
        "medicion_valida": cobertura >= args.cobertura_min,
    }

    print(f"palabras ASS      : {n_tot}")
    print(f"palabras Whisper  : {len(whisper_words)}")
    print(f"emparejadas       : {n_emp} ({cobertura:.1%})")
    if not res["medicion_valida"]:
        print(f"\n*** MEDICIÓN INVÁLIDA: cobertura {cobertura:.1%} < {args.cobertura_min:.0%}.")
        print("*** El emparejado falló; estos números NO significan nada. Sin veredicto.")
    else:
        print(f"\n|error| medio     : {res['error_medio_abs']:.3f}s   (objetivo <= 0.20)")
        print(f"|error| máximo    : {res['error_max_abs']:.3f}s   (objetivo <= 0.30)")
        print(f"sesgo con signo   : {res['sesgo']:+.3f}s   "
              f"({'subtítulo DELANTE de la voz, correcto' if res['sesgo'] < 0 else 'subtítulo DETRÁS de la voz, MAL'})")
    print(f"pausas fuera de puntuación: {len(res['pausas_fuera_de_puntuacion'])}")
    for p in res["pausas_fuera_de_puntuacion"][:5]:
        print(f"   {p['hueco']}s tras '{p['tras']}' en t={p['t']}s")

    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(f"\nresultado -> {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
