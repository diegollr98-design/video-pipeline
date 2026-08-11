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

# Los artefactos viven en `data/evidence/`, que esta declarado INTOCABLE. Antes
# esto apuntaba al scratchpad de la sesion que lo escribio: funcionaba por
# casualidad mientras ese directorio existiera, y tras la siguiente corrida
# habria comparado zonas de una corrida contra el audio de otra.
SCRATCH = os.environ.get("ANCHOR_BENCH_DIR", "data/evidence")
STORY = os.environ.get("ANCHOR_BENCH_STORY", "temp/video_001_story.txt")
AUDIO = os.environ.get("ANCHOR_BENCH_AUDIO", "temp/video_001_audio.mp3")
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
ASS = os.path.join(SCRATCH, "video_001_subs.ass")

# Las DOS producciones reales. El banco tiene que correr sobre las dos: un fix
# del anclaje ya dio verde en el video largo mientras rompia 3 de 16 shorts
# [ANCLA-03], y el defecto [ANCLA-05] estaba en las dos corridas, mas pequeno en
# la primera. Medir una sola no cierra nada.
#
# `control` = con que codigo se compuso el .ass publicado de esa corrida, que es
# lo unico que reproduce el banco al 0. Para el 10-ago es el anclaje viejo
# congelado aqui; el .ass del 11-ago se compuso a las 12:47 con 13aec78, ANTES
# de que ANCLA-04 entrara (13:29), asi que su control es ese commit.
CORRIDAS = {
    "10ago": {
        "raw": "raw_words.json", "sents": "sentences.json",
        "trans": "whisper_video001.json", "ass": "video_001_subs.ass",
        "control": "viejo", "zonas": "ZONAS_10AGO",
    },
    "11ago": {
        "raw": "raw_11ago.json", "sents": "sents_11ago.json",
        "trans": "whisper_v001_11ago.json", "ass": "video_001_subs_11ago.ass",
        "control": "13aec78", "zonas": "ZONAS_11AGO",
    },
}

# Zonas con veredicto YA CONOCIDO (transcripciones frescas de 40 s, 10-ago-2026).
# El banco tiene que reproducirlas ANTES de servir para juzgar nada.
# OJO con el veredicto por MEDIANA de zona: 605-645 y 1585-1625 salen sanas en
# mediana y aun asi contienen una ventana corta 1,5 s por detras. La mediana de
# una franja de 40 s la diluye. Por eso el veredicto que manda es el de VENTANA.
ZONAS_10AGO = [
    (300, 340, "control", "sana"),
    (605, 645, "sana en mediana, contiene ventana corta rota", "sana"),
    (685, 725, "rota (94 palabras)", "rota"),
    (1000, 1040, "rota (95 palabras)", "rota"),
    (1245, 1285, "control", "sana"),
    # Su etiqueta original decia "sana", pero era la MEDIANA diluyendo: contiene
    # la ventana corta de t=1592, que sigue viva tras [ANCLA-05] (4 palabras,
    # +0,776 s). Con el criterio de palabras tardias sale ROTA, que es la verdad.
    (1585, 1625, "contiene la ventana corta de t=1592, aun viva", "rota"),
]

# Las zonas son de UNA corrida: otra historia con otro audio no tiene los mismos
# instantes. Mostrar las del 10-ago mientras se juzga el 11-ago da veredictos
# "conocidos" sobre tramos que nadie ha verificado ahi — la misma clase de error
# que [INSTR-04] (comparar dos regimenes) con otra cara.
# Verdicts del 11-ago, medidos contra `whisper_v001_11ago.json`:
ZONAS_11AGO = [
    (125, 155, "las dos ventanas rotas (aplastada + interior fabricado)", "rota"),
    (300, 340, "control", "sana"),
    (605, 645, "control", "sana"),
    (1245, 1285, "control", "sana"),
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


def _informe(nombre, words, sentences, trans, zonas=(), calibrar=False):
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

    if zonas:
        # El veredicto conocido de una zona describe como estaba la corrida
        # PUBLICADA. Solo sirve de calibracion en la pasada ANTES: si el banco no
        # reproduce ahi lo ya verificado, no mide. En la pasada DESPUES esas
        # mismas zonas son el RESULTADO, no una expectativa que cumplir, y
        # marcarlas con "!!" haria leer una mejora como un fallo.
        print("  zonas de veredicto conocido:" if calibrar
              else "  esas mismas zonas, tras el cambio:")
        for a, b, etiqueta, esperado in zonas:
            es = [err[i] for i, w in enumerate(words) if a <= w["start"] <= b and i in err]
            if not es:
                continue
            med = sorted(es)[len(es) // 2]
            tarde = sum(1 for e in es if e > 0.5)
            # La mediana de una franja de 40 s DILUYE una ventana rota dentro de
            # vecinas sanas: la zona 125-155 del 11-ago da mediana -0,108 s
            # ("sana") conteniendo 23 de 94 palabras a mas de 0,5 s. Es la trampa
            # ya pagada dos veces en este repo, y el banco caia en ella. Por eso
            # el veredicto de zona necesita el segundo criterio.
            veredicto = "ROTA" if (med > 0.35 or tarde >= 0.15 * len(es)) else "sana"
            if calibrar:
                marca = "OK " if veredicto.lower() == esperado[:4] else "!! "
                cola = f" (esperado {esperado})"
            else:
                marca = "-> " if veredicto.lower() == esperado[:4] else "** "
                cola = f" (antes {esperado})"
            print(f"    {marca}{a}-{b} ({etiqueta}){cola}: mediana {med:+.3f}s, "
                  f"{tarde}/{len(es)} palabras >0.5s tarde -> {veredicto}")
        if not calibrar:
            print("       ('**' = cambio de estado respecto a la corrida publicada)")
    return malas


def _codigo_del_commit(commit):
    """Carga `modules/tts_engine.py` TAL COMO ESTABA en un commit.

    Hace falta para el control del instrumento: el `.ass` publicado de cada
    corrida se compuso con el codigo de SU dia, no con el de hoy ni con el
    anclaje viejo congelado. Reproducirlo con otro codigo es medir otra cosa.
    """
    import importlib.util
    import subprocess
    import tempfile
    fuente = subprocess.check_output(["git", "show", f"{commit}:modules/tts_engine.py"])
    ruta = os.path.join(tempfile.mkdtemp(prefix="anchor_bench_"), "tts_viejo.py")
    with open(ruta, "wb") as f:
        f.write(fuente)
    spec = importlib.util.spec_from_file_location(f"tts_{commit}", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def bench(corrida=None):
    if corrida is None:
        for nombre in CORRIDAS:
            print("\n" + "#" * 68)
            print(f"# CORRIDA {nombre}")
            print("#" * 68)
            bench(nombre)
        return

    cfg = CORRIDAS[corrida]
    d = lambda k: os.path.join(SCRATCH, cfg[k])
    raw = json.load(open(d("raw"), encoding="utf-8"))
    sentences = json.load(open(d("sents"), encoding="utf-8"))
    trans = json.load(open(d("trans"), encoding="utf-8"))
    ass_path = d("ass")
    print(f"crudas {len(raw)} palabras | {len(sentences)} SentenceBoundary | "
          f"transcripcion independiente {len(trans)} palabras")

    viejo = _anclaje_viejo(raw, sentences)
    if cfg["control"] == "viejo":
        referencia, etiqueta = viejo, "anclaje viejo reproducido"
    else:
        mod = _codigo_del_commit(cfg["control"])
        referencia = mod._enforce_monotonic(
            mod._validate_and_fix_alignment([dict(w) for w in raw], sentences))
        etiqueta = f"codigo de {cfg['control']} reproducido"

    # --- Control del INSTRUMENTO: reproducir el .ass que se publico. Si no sale
    # ~0, el banco no mide la corrida real y cualquier conclusion vale cero.
    cues = []
    for linea in open(ass_path, encoding="utf-8"):
        if linea.startswith("Dialogue:"):
            partes = linea.split(",", 9)
            h, m, s = partes[1].split(":")
            texto = partes[9].split("}")[-1].strip()
            cues.append((texto, float(h) * 3600 + float(m) * 60 + float(s)))
    # Emparejado por TEXTO, no por indice: el .ass tiene 5256 cues y las palabras
    # son 5290, asi que comparar posicion a posicion acumula un desfase falso que
    # llegaba a 22 s. Es la misma trampa que INSTR-02, en pequeno.
    difs = [abs(e) for _, e in _emparejar_local(referencia, cues)]
    media, maximo = sum(difs) / len(difs), max(difs)
    print(f"\n[control del instrumento] .ass publicado vs {etiqueta}: "
          f"{len(difs)} cues emparejados, dif media {media:.4f}s, "
          f"max {maximo:.4f}s  (si esto no es ~0, el banco NO mide la corrida real)")
    if media > 0.05:
        print("  !! CONTROL FALLIDO: el banco NO reproduce la corrida publicada. "
              "No juzgues nada con estos numeros.")

    from modules.tts_engine import _validate_and_fix_alignment, _enforce_monotonic
    nuevo = _enforce_monotonic(
        _validate_and_fix_alignment([dict(w) for w in raw], sentences))

    zonas = globals()[cfg["zonas"]]
    malas_v = _informe(f"ANTES ({etiqueta})", referencia, sentences, trans, zonas, calibrar=True)
    malas_n = _informe("DESPUES (codigo de HOY)", nuevo, sentences, trans, zonas, calibrar=False)

    sol_v = sum(1 for i in range(1, len(referencia))
                if referencia[i]["start"] < referencia[i - 1]["end"] - 1e-6)
    sol_n = sum(1 for i in range(1, len(nuevo)) if nuevo[i]["start"] < nuevo[i - 1]["end"] - 1e-6)
    print(f"\nsolapes de subtitulo: antes {sol_v} -> despues {sol_n}")
    print(f"ventanas rotas: antes {len(malas_v)} -> despues {len(malas_n)}")

    # Lo que de verdad decide: NINGUNA ventana puede empeorar. Es el A/B que
    # caza un fix que arregla el video largo mientras rompe el gemelo.
    ma = {t: m for t, m, _, _ in malas_v}
    mb = {t: m for t, m, _, _ in malas_n}
    empeoran = [(t, ma.get(t, 0.0), m) for t, m in mb.items()
                if abs(m) > abs(ma.get(t, 0.0)) + 0.05]
    print(f"ventanas que EMPEORAN >0.05s: {len(empeoran)}")
    for t, a, b in empeoran:
        print(f"   !! t={t:8.2f}s  {a:+.3f} -> {b:+.3f}")
    # Invariantes que no dependen del emparejador
    print(f"invariantes: nº de palabras {len(raw)} -> {len(nuevo)} "
          f"({'OK' if len(nuevo) == len(raw) else 'ROTO'}) | orden monotono "
          f"{'OK' if all(nuevo[i]['start'] >= nuevo[i-1]['start'] - 1e-6 for i in range(1, len(nuevo))) else 'ROTO'}")
    return len(empeoran)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "dump-raw"
    if cmd == "dump-raw":
        dump_raw()
    elif cmd == "bench":
        corrida = sys.argv[2] if len(sys.argv) > 2 else None
        if corrida and corrida not in CORRIDAS:
            print(f"corrida desconocida: {corrida}. Opciones: {', '.join(CORRIDAS)}")
            sys.exit(1)
        bench(corrida)
    else:
        print(f"comando desconocido: {cmd}")
        sys.exit(1)
