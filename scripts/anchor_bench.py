"""Banco de pruebas del ANCLAJE (offline, 0 peticiones, 0 GB).

Reproduce la cadena real de `run_tts` sobre los artefactos ya en disco de una
corrida de produccion, y permite comparar variantes de
`_validate_and_fix_alignment` contra una transcripcion INDEPENDIENTE.

Por que existe: el defecto ANCLA-01 (ventanas enteras ~1 s por detras de la voz)
solo aparece a escala de produccion (214 ventanas), y el fixture de 3 min del
gate tiene 12. Regenerar una corrida larga cuesta ~2h40 y ~7 GB de disco; este
banco mide el mismo fenomeno sobre datos ya pagados.

Uso:
  python scripts/anchor_bench.py dump-raw   # alineacion CRUDA -> raw_words.json
  python scripts/anchor_bench.py bench      # compara anclaje VIEJO vs NUEVO
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.tts_engine import _clean_speech_for_tts, _forced_align  # noqa: E402

SCRATCH = os.environ.get(
    "ANCHOR_BENCH_DIR",
    r"C:/Users/diego/AppData/Local/Temp/claude/c--Users-diego-Desktop-YOUTUBE/660ffde3-b160-422c-9358-f619be252dc5/scratchpad",
)
STORY = "temp/video_001_story.txt"
AUDIO = "temp/video_001_audio.mp3"
RAW = os.path.join(SCRATCH, "raw_words.json")


def dump_raw():
    """Alineacion forzada CRUDA (antes del anclaje) sobre el audio real."""
    text = open(STORY, encoding="utf-8").read()
    clean = _clean_speech_for_tts(text)
    print(f"texto limpio: {len(clean.split())} palabras")
    words = _forced_align(AUDIO, clean, "small")
    print(f"alineadas: {len(words)} palabras")
    with open(RAW, "w", encoding="utf-8") as f:
        json.dump(words, f)
    print(f"escrito: {RAW}")


SENTENCES = os.path.join(SCRATCH, "sentences.json")
TRANSCRIPT = os.path.join(SCRATCH, "whisper_video001.json")
ASS = "temp/video_001_subs.ass"

# Zonas con veredicto YA CONOCIDO (transcripciones frescas de 40 s, 10-ago-2026).
# El banco tiene que reproducirlas ANTES de servir para juzgar nada.
# OJO con el veredicto por MEDIANA de zona: 605-645 y 1585-1625 salen sanas en
# mediana y aun asi contienen una ventana corta 1,5 s por detras. La mediana de
# una franja de 40 s la diluye. Por eso el veredicto que manda es el de VENTANA.
ZONAS = [
    (300, 340, "control", "sana"),
    (605, 645, "sana en mediana, contiene ventana corta rota", "sana"),
    (685, 725, "rota (94 palabras)", "rota"),
    (1000, 1040, "rota (95 palabras)", "rota"),
    (1245, 1285, "control", "sana"),
    (1585, 1625, "sana en mediana, contiene ventana corta rota", "sana"),
]


def _anclaje_viejo(words, sentences):
    """Copia CONGELADA del anclaje anterior (offset con UNA sola palabra).

    Vive aqui para que el A/B siga siendo reproducible cuando el modulo cambie.
    """
    words = [dict(w) for w in words]
    word_idx = 0
    for sent in sentences:
        s_dur = sent.get("duration", sent.get("dur", 0))
        s_start = sent["start"]
        if s_dur <= 0:
            continue
        end_idx = min(word_idx + len(sent["text"].split()), len(words))
        indices = list(range(word_idx, end_idx))
        word_idx = end_idx
        if not indices:
            continue
        s_end = s_start + s_dur
        w_first = words[indices[0]]["start"]
        span = words[indices[-1]]["end"] - w_first
        if span > 0.05:
            offset = s_start - w_first
            for idx in indices:
                words[idx]["start"] += offset
                words[idx]["end"] += offset
            if words[indices[-1]]["end"] > s_end:
                scale = s_dur / span
                for idx in indices:
                    words[idx]["start"] = s_start + (words[idx]["start"] - s_start) * scale
                    words[idx]["end"] = s_start + (words[idx]["end"] - s_start) * scale
        else:
            char_lens = [max(len(words[i]["text"]), 1) for i in indices]
            total = sum(char_lens)
            cursor = s_start
            for j, idx in enumerate(indices):
                d = s_dur * char_lens[j] / total
                words[idx]["start"] = cursor
                words[idx]["end"] = cursor + d
                cursor += d
    return words


def _norm(w):
    return "".join(c for c in w.lower() if c.isalnum() or c in "áéíóúüñ")


def _ventanas(words, sentences):
    """Indices de palabra por ventana de SentenceBoundary (mismo reparto que el modulo)."""
    out, idx = [], 0
    for sent in sentences:
        if sent.get("duration", sent.get("dur", 0)) <= 0:
            continue
        end = min(idx + len(sent["text"].split()), len(words))
        if end > idx:
            out.append((sent["start"], list(range(idx, end))))
        idx = end
    return out


def _emparejar_local(cand, trans, chunk=100, holgura=150):
    """Empareja por VENTANAS LOCALES, no con un difflib global.

    INSTR-02: un `difflib` global sobre 5000+ palabras engancha la ocurrencia
    equivocada donde el texto se repite y FABRICA retraso. Medido: inflaba la
    media de 0,072 a 0,153 s y volteaba el sesgo. Aqui la busqueda se restringe a
    una franja alrededor de la posicion esperada, asi que una repeticion lejana
    no puede capturar el emparejado.
    """
    import difflib
    tn = [_norm(t[0]) for t in trans]
    pares = []
    cursor = 0
    for ini in range(0, len(cand), chunk):
        bloque = cand[ini:ini + chunk]
        cn = [_norm(w["text"]) for w in bloque]
        lo = max(0, cursor - 40)
        hi = min(len(trans), cursor + len(bloque) + holgura)
        sm = difflib.SequenceMatcher(None, cn, tn[lo:hi], autojunk=False)
        ultimo = cursor
        for a, b, n in sm.get_matching_blocks():
            for k in range(n):
                ci, ti = ini + a + k, lo + b + k
                pares.append((ci, cand[ci]["start"] - trans[ti][1]))
                ultimo = ti + 1
        cursor = ultimo
    return pares


def _percentil(v, p):
    if not v:
        return float("nan")
    s = sorted(v)
    return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]


def _informe(nombre, words, sentences, trans):
    pares = _emparejar_local(words, trans)
    err = {i: e for i, e in pares}
    vent = _ventanas(words, sentences)

    malas, medianas_v = [], []
    palabras_malas, segundos_malos = 0, 0.0
    for s_start, idxs in vent:
        es = [err[i] for i in idxs if i in err]
        if len(es) < 3:
            continue
        m = sorted(es)[len(es) // 2]
        medianas_v.append(m)
        if abs(m) > 0.35:
            malas.append((s_start, m, len(idxs), words[idxs[0]]["text"]))
            palabras_malas += len(idxs)
            segundos_malos += words[idxs[-1]]["end"] - words[idxs[0]]["start"]

    todos = [abs(e) for _, e in pares]
    print(f"\n### {nombre}")
    print(f"  emparejadas {len(pares)}/{len(words)}  |err| medio {sum(todos)/len(todos):.3f}s  "
          f"p95 {_percentil(todos, 95):.3f}s  max {max(todos):.3f}s")
    print(f"  VENTANAS con |mediana| > 0.35 s: {len(malas)} de {len(medianas_v)} medibles")
    # La metrica que importa es cuanto VIDEO sale desincronizado, no cuantas
    # ventanas: una ventana de 95 palabras son 27 s de pantalla y una de 4 son 2.
    print(f"  --> PALABRAS afectadas: {palabras_malas}   SEGUNDOS de video: {segundos_malos:.1f}s")
    for s, m, n, t in sorted(malas, key=lambda x: -abs(x[1]))[:8]:
        print(f"     t={s:8.2f}s  mediana {m:+.3f}s  {n:3d} palabras  '{t}'")

    print("  zonas de veredicto conocido:")
    for a, b, etiqueta, esperado in ZONAS:
        es = [err[i] for i, w in enumerate(words) if a <= w["start"] <= b and i in err]
        if not es:
            continue
        med = sorted(es)[len(es) // 2]
        tarde = sum(1 for e in es if e > 0.5)
        veredicto = "ROTA" if med > 0.35 else "sana"
        marca = "OK " if veredicto.lower() == esperado[:4] else "!! "
        print(f"    {marca}{a}-{b} ({etiqueta}, esperado {esperado}): mediana {med:+.3f}s, "
              f"{tarde}/{len(es)} palabras >0.5s tarde -> {veredicto}")
    return malas


def bench():
    raw = json.load(open(RAW, encoding="utf-8"))
    sentences = json.load(open(SENTENCES, encoding="utf-8"))
    trans = json.load(open(TRANSCRIPT, encoding="utf-8"))
    print(f"crudas {len(raw)} palabras | {len(sentences)} SentenceBoundary | "
          f"transcripcion independiente {len(trans)} palabras")

    viejo = _anclaje_viejo(raw, sentences)

    # --- Control del INSTRUMENTO: el anclaje viejo sobre las palabras crudas
    # tiene que reproducir el .ass que se publico. Si no, el banco no mide la
    # corrida real y cualquier conclusion vale cero.
    cues = []
    for linea in open(ASS, encoding="utf-8"):
        if linea.startswith("Dialogue:"):
            partes = linea.split(",", 9)
            h, m, s = partes[1].split(":")
            texto = partes[9].split("}")[-1].strip()
            cues.append((texto, float(h) * 3600 + float(m) * 60 + float(s)))
    # Emparejado por TEXTO, no por indice: el .ass tiene 5256 cues y las palabras
    # son 5290, asi que comparar posicion a posicion acumula un desfase falso que
    # llegaba a 22 s. Es la misma trampa que INSTR-02, en pequeno.
    difs = [abs(e) for _, e in _emparejar_local(viejo, cues)]
    print(f"\n[control del instrumento] .ass publicado vs anclaje viejo reproducido: "
          f"{len(difs)} cues emparejados, dif media {sum(difs)/len(difs):.4f}s, "
          f"max {max(difs):.4f}s  (si esto no es ~0, el banco NO mide la corrida real)")

    from modules.tts_engine import _validate_and_fix_alignment, _enforce_monotonic
    nuevo = _enforce_monotonic(
        _validate_and_fix_alignment([dict(w) for w in raw], sentences))

    malas_v = _informe("ANCLAJE VIEJO (offset con 1 palabra)", viejo, sentences, trans)
    malas_n = _informe("ANCLAJE NUEVO (mediana del vecindario)", nuevo, sentences, trans)

    sol_v = sum(1 for i in range(1, len(viejo)) if viejo[i]["start"] < viejo[i - 1]["end"] - 1e-6)
    sol_n = sum(1 for i in range(1, len(nuevo)) if nuevo[i]["start"] < nuevo[i - 1]["end"] - 1e-6)
    print(f"\nsolapes de subtitulo: viejo {sol_v} -> nuevo {sol_n}")
    print(f"ventanas rotas: viejo {len(malas_v)} -> nuevo {len(malas_n)}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "dump-raw"
    if cmd == "dump-raw":
        dump_raw()
    elif cmd == "bench":
        bench()
    else:
        print(f"comando desconocido: {cmd}")
        sys.exit(1)
