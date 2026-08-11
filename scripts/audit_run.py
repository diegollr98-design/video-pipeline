"""Auditoría de UNA corrida completa: ¿es publicable esta salida?

El modo de fallo de este proyecto no es que el pipeline pete, sino que entregue
un vídeo que PARECE terminado. Este script mide de golpe todo lo que se puede
medir de una corrida, para que el ojo de Diego se gaste solo en lo que no es
medible (si la historia engancha, si la voz suena natural).

Cada comprobación existe porque un defecto REAL se coló por ahí:
  sincronismo por tramos  -> [ANCLA-01] 60 s de vídeo a +1,05 s de la voz que
                             la media global (0,153 s) daba por bueno
  basura del modelo       -> [BASURA-01] 'ONEAN 0230 0207-' narrado y subtitulado
  párrafos repetidos      -> [DEDUP-01] 83 palabras narradas dos veces
  aperturas de títulos    -> 50/50 shorts empezaban por "Mi <alguien>"
  loudness                -> YouTube normaliza a -14 LUFS y SOLO BAJA: un vídeo
                             a -21 suena 7 dB por debajo de la competencia
  ratio de duración       -> gameplay desperdiciado o repetido

Uso:
  python scripts/audit_run.py                    # audita output/ y shorts_tiktok/
  python scripts/audit_run.py --shorts 3         # mide el sincronismo de 3 shorts
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.eval_sync import (  # noqa: E402
    lee_ass, extrae_audio, transcribe, empareja, peor_tramo,
    pausas_fuera_de_puntuacion,
)

OK, MAL, AVISO = "  OK  ", " FALLA", " AVISO"

_RE_NORM = re.compile(r"[^\wáéíóúñüÁÉÍÓÚÑÜ]+", re.UNICODE)


def _norm_pal(w):
    return _RE_NORM.sub("", w.lower())


def _ffprobe(path, campos, stream=False):
    sel = ["-select_streams", "v:0"] if stream else []
    ent = f"stream={campos}" if stream else f"format={campos}"
    r = subprocess.run(
        ["ffprobe", "-v", "error", *sel, "-show_entries", ent,
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True)
    return r.stdout.split()


def loudness(path):
    """LUFS integrados, medidos con ebur128 (el estándar que usa YouTube)."""
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-i", path, "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
        capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?\d+\.\d+)\s+LUFS", r.stderr)
    p = re.findall(r"Peak:\s+(-?\d+\.\d+)\s+dBFS", r.stderr)
    return (float(m[-1]) if m else None), (float(p[-1]) if p else None)


def _silencios(path, umbral_db=-35, dur_min=0.25):
    """Tramos de silencio del audio, medidos con `silencedetect`.

    Instrumento que NO depende de Whisper: cuando el alineador y edge-tts se
    contradijeron en 5 s, esto fue lo que decidió quién mentía [ANCLA-03].
    """
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-i", path, "-af",
         f"silencedetect=noise={umbral_db}dB:d={dur_min}", "-f", "null", "-"],
        capture_output=True, text=True)
    inicios = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", r.stderr)]
    finales = [float(x) for x in re.findall(r"silence_end:\s*(-?[\d.]+)", r.stderr)]
    return list(zip(inicios, finales))


def voz_sin_subtitulo(media, ass_words, holgura=0.15, umbral=0.35):
    """Tramos con VOZ SONANDO y NINGÚN subtítulo en pantalla.

    Es el agujero estructural de todo lo demás que mide este script: un
    subtítulo que NO EXISTE no genera par de error, así que ninguna métrica de
    DESFASE puede verlo, con ningún umbral. En la corrida del 11-ago eran 8,5 s
    seguidos de narración con la pantalla en blanco y el gate lo dio por bueno.

    Se ignora todo lo anterior al primer cue: durante la intro el narrador dice
    la frase del título y los subtítulos están suprimidos A PROPÓSITO
    (`skip_until`), así que contarlo sería un falso positivo garantizado.
    """
    if not ass_words:
        return [], 0.0
    dur = float(_ffprobe(media, "duration")[0])
    inicio = min(s for _, s, _ in ass_words)      # fin de la intro

    # Intervalos CON subtítulo, fundidos y dilatados: los huecos de milisegundos
    # entre dos palabras seguidas son del formato, no pantallas en blanco.
    cues = sorted((s, e) for _, s, e in ass_words)
    cubierto = []
    for s, e in cues:
        s, e = s - holgura, e + holgura
        if cubierto and s <= cubierto[-1][1]:
            cubierto[-1][1] = max(cubierto[-1][1], e)
        else:
            cubierto.append([s, e])

    # Voz = complemento del silencio
    voz, prev = [], inicio
    for s, e in _silencios(media):
        if s > prev:
            voz.append((prev, min(s, dur)))
        prev = max(prev, e)
    if prev < dur:
        voz.append((prev, dur))

    huecos = []
    for vs, ve in voz:
        vs = max(vs, inicio)
        if ve <= vs:
            continue
        cursor = vs
        for cs, ce in cubierto:
            if ce <= cursor or cs >= ve:
                continue
            if cs > cursor:
                huecos.append((cursor, min(cs, ve)))
            cursor = max(cursor, ce)
            if cursor >= ve:
                break
        if cursor < ve:
            huecos.append((cursor, ve))

    huecos = [(a, b) for a, b in huecos if b - a >= umbral]
    return huecos, sum(b - a for a, b in huecos)


def rachas_aplastadas(ass_words, dur_max=0.09, racha_min=4):
    """Palabras seguidas en el SUELO de duración: subtítulo ilegible.

    `_enforce_monotonic` resuelve un desorden del alineador empujando cada
    palabra `paso_min = 0,05 s`. Eso no falla: produce 28 palabras en 1,40 s
    (1200 wpm en pantalla), lo escribe en un WARNING que nadie lee y el vídeo
    sale igual. Aquí se convierte en veredicto.
    """
    peor, racha, inicio, salida = 0, 0, None, []
    for w, s, e in ass_words:
        if e - s <= dur_max:
            if racha == 0:
                inicio = s
            racha += 1
        else:
            if racha >= racha_min:
                salida.append((inicio, racha))
            peor, racha = max(peor, racha), 0
    if racha >= racha_min:
        salida.append((inicio, racha))
    peor = max(peor, racha)
    return peor, salida


def _busca_pipeline_log(desde):
    """`pipeline.log` mirando hacia arriba desde el directorio temporal."""
    candidatos = [
        os.path.join(desde, "..", "pipeline.log"),      # temp_dir = ./temp
        os.path.join(desde, "..", "..", "pipeline.log"),  # temp_dir = ./test_e2e/temp
        "pipeline.log",
    ]
    for c in candidatos:
        if os.path.exists(c):
            return c
    return candidatos[0]


def cierre_narrativo(log_path, stem):
    """¿Se pidió y se escribió el bloque de DESENLACE de esta historia?

    No se puede detectar "final satisfactorio" leyendo el texto: es un juicio, y
    §18 dice que un juicio que el modelo no puede dar se vuelve determinista o
    hueco. Lo determinista es el hecho que falló [CIERRE-01]: el bucle salió sin
    pedir nunca el bloque final y el vídeo se publicó a mitad de escena. Eso el
    log SÍ lo dice, así que se comprueba ahí.
    """
    if not os.path.exists(log_path):
        return None, "sin pipeline.log: no se puede comprobar el cierre"
    texto = open(log_path, encoding="utf-8", errors="replace").read()
    bloques = texto.split("=== Produciendo ")
    tramo = next((b for b in reversed(bloques) if b.startswith(stem)), None)
    if tramo is None:
        return None, f"no hay tramo de {stem} en el log"
    tramo = tramo.split("=== Completado")[0]
    if "pidiendo final" in tramo or "Cierre anadido" in tramo:
        return True, "el bloque de desenlace se pidio y se escribio"
    return False, ("la historia se cerro SIN bloque de desenlace: el bucle salio "
                   "por el 85% del objetivo (clase [CIERRE-01])")


def ngramas_repetidos(texto, n=12):
    w = texto.split()
    vistos, dups = {}, []
    for i in range(len(w) - n):
        k = " ".join(x.lower() for x in w[i:i + n])
        if k in vistos:
            dups.append((vistos[k], i))
        else:
            vistos[k] = i
    if not dups:
        return 0, 0
    a, b = dups[0]
    largo = 0
    while a + largo < len(w) and b + largo < len(w) and w[a + largo].lower() == w[b + largo].lower():
        largo += 1
    return len(dups), largo


def evalua_titulo_youtube(video):
    """El título contra el campo REAL de YouTube (el que se PUBLICARÍA).

    Contrato: `<stem>_title_yt.txt` es el título corto para el campo de
    YouTube (<=100 caracteres), y puede no existir todavía. Si existe, es la
    fuente de verdad de lo que se publica: se mide el CRUDO, sin aplicar el
    recorte defensivo del uploader, porque un corto que ya nace >100
    caracteres es un contrato roto aguas arriba, no algo sano que el recorte
    "arregla". Si no existe, cae al largo (siempre recortado por el
    uploader) y eso es esperado -> AVISO, no FALLA.

    Devuelve (lineas_para_imprimir, fallos).
    """
    from modules.youtube_uploader import titulo_corto_path
    titulo_f = video[: -len("_final.mp4")] + "_title.txt"
    yt_f = titulo_corto_path(video)
    t_yt = open(yt_f, encoding="utf-8").read().strip() if os.path.exists(yt_f) else ""

    lineas, fallos = [], []
    if t_yt:
        est = OK if len(t_yt) <= 100 else MAL
        lineas.append(f"{est} título YouTube (corto, se publica): {len(t_yt)} caracteres, "
                      f"{len(t_yt.split())} palabras")
        if est == MAL:
            lineas.append(f"       se publicaría (crudo): {t_yt}")
            fallos.append(f"título corto de {len(t_yt)} caracteres: supera el "
                          f"límite de 100 de YouTube (contrato roto en "
                          f"{os.path.basename(yt_f)})")
    elif os.path.exists(titulo_f):
        t = open(titulo_f, encoding="utf-8").read().strip()
        lineas.append(f"{AVISO} sin título corto ({os.path.basename(yt_f)}): se publicaría "
                      f"el largo recortado ({len(t)} caracteres, {len(t.split())} palabras)")
    else:
        lineas.append(f"{AVISO} sin título largo ni corto: no se puede comprobar qué se "
                      f"publicaría")
    return lineas, fallos


def audita_video(video, ass, story, chunk_dur=None, model="small"):
    print(f"\n=== VÍDEO LARGO: {os.path.basename(video)} ===")
    fallos = []

    # --- sincronismo contra transcripción INDEPENDIENTE
    ass_words = lee_ass(ass)
    wav = extrae_audio(video)
    pares = empareja(ass_words, transcribe(wav, model))
    cob = len(pares) / max(1, len(ass_words))
    if cob < 0.85:
        print(f"{AVISO} emparejado {cob:.1%} < 85%: la medición NO vale")
        return ["medición inválida"]
    errs = [e for *_, e in pares]
    abs_e = sorted(abs(e) for e in errs)
    p95 = abs_e[int(0.95 * (len(abs_e) - 1))]
    tarde = sum(1 for e in errs if e > 0.5)
    pt = peor_tramo(pares)
    med = sum(abs_e) / len(abs_e)
    sesgo = sum(errs) / len(errs)

    est = OK if abs(pt["mediana"]) <= 0.35 else MAL
    if est == MAL:
        fallos.append(f"peor tramo {pt['mediana']:+.3f}s en t={pt['t']}s")
    print(f"{est} sincronismo: medio {med:.3f}s  p95 {p95:.3f}s  sesgo {sesgo:+.3f}s  "
          f"PEOR TRAMO {pt['mediana']:+.3f}s en t={pt['t']}s  ({tarde} palabras >0,5 s tarde)")
    if sesgo > 0:
        print(f"{AVISO} sesgo POSITIVO: el subtítulo va por detrás de la voz (se busca negativo)")

    pausas = pausas_fuera_de_puntuacion(ass)
    print(f"{OK if not pausas else AVISO} pausas fuera de puntuación: {len(pausas)}")

    # --- COBERTURA: lo que ninguna métrica de desfase puede ver
    huecos, total_hueco = voz_sin_subtitulo(video, ass_words)
    est = OK if total_hueco < 1.0 else MAL
    peor = max(huecos, key=lambda h: h[1] - h[0]) if huecos else None
    detalle = (f"peor {peor[1]-peor[0]:.2f}s en t={peor[0]:.1f}s" if peor else "ninguno")
    print(f"{est} voz SIN subtítulo: {total_hueco:.2f}s en {len(huecos)} tramo(s), {detalle}")
    if est == MAL:
        fallos.append(f"{total_hueco:.1f}s de voz sin subtítulo en pantalla ({detalle})")

    # --- palabras aplastadas en el suelo de duración
    peor_racha, rachas = rachas_aplastadas(ass_words)
    est = OK if peor_racha < 4 else MAL
    print(f"{est} palabras aplastadas: racha máxima {peor_racha} "
          f"(<=0,09 s cada una){'; tramos: ' + ', '.join(f't={t:.1f}s x{n}' for t, n in rachas[:3]) if rachas else ''}")
    if est == MAL:
        fallos.append(f"racha de {peor_racha} palabras ilegibles (subtítulo en el suelo)")

    # --- cierre narrativo [CIERRE-01]
    # El log vive en la RAÍZ del repo, no junto al temp. Con `temp_dir: ./temp`
    # el `..` acertaba por casualidad; con el del fixture (`./test_e2e/temp`)
    # apuntaba a `test_e2e/pipeline.log`, que no existe, y la comprobación salía
    # como "no se puede comprobar" en todas las corridas del gate.
    cerrado, motivo = cierre_narrativo(
        _busca_pipeline_log(os.path.dirname(ass) or "."),
        os.path.basename(video)[: -len("_final.mp4")])
    if cerrado is None:
        print(f"{AVISO} cierre narrativo: {motivo}")
    else:
        print(f"{OK if cerrado else MAL} cierre narrativo: {motivo}")
        if not cerrado:
            fallos.append("la historia se publicó SIN desenlace")

    # --- basura del modelo y párrafos repetidos, sobre el guion real
    if story and os.path.exists(story):
        texto = open(story, encoding="utf-8").read()
        try:
            from modules.script_generator import _detectar_basura
            hay, motivo = _detectar_basura(texto)
            print(f"{MAL if hay else OK} basura del modelo: "
                  f"{motivo if hay else 'ninguna'}")
            if hay:
                fallos.append(f"basura del modelo: {motivo}")
        except Exception as e:
            print(f"{AVISO} no se pudo comprobar la basura: {e}")
        n_dup, largo = ngramas_repetidos(texto)
        print(f"{MAL if n_dup else OK} párrafos repetidos: {n_dup} n-gramas de 12 "
              f"(tramo más largo: {largo} palabras)")
        if n_dup:
            fallos.append(f"{largo} palabras narradas dos veces")

    # --- artefactos, duración y peso
    dur = float(_ffprobe(video, "duration")[0])
    size_gb = os.path.getsize(video) / 1024**3
    br = float(_ffprobe(video, "bit_rate")[0]) / 1e6
    w, h = _ffprobe(video, "width,height", stream=True)[:2]
    print(f"{OK} vídeo: {dur/60:.2f} min  {w}x{h}  {br:.1f} Mbps  {size_gb:.2f} GB")
    if chunk_dur:
        ratio = dur / chunk_dur
        est = OK if 0.9 <= ratio <= 1.1 else AVISO
        print(f"{est} ratio vídeo/chunk: {ratio:.3f}  "
              f"({'gameplay repetido' if ratio > 1.1 else 'gameplay desperdiciado' if ratio < 0.9 else 'ajustado'})")

    i, tp = loudness(video)
    if i is not None:
        est = OK if i >= -16 else AVISO
        pico = f", pico {tp:.1f} dBFS" if tp is not None else ""
        print(f"{est} loudness: {i:.1f} LUFS{pico}. YouTube normaliza "
              f"a -14 y SOLO BAJA: por debajo suena más flojo que la competencia")

    # --- el título contra el campo REAL de YouTube (el que se PUBLICARÍA)
    lineas_titulo, fallos_titulo = evalua_titulo_youtube(video)
    for linea in lineas_titulo:
        print(linea)
    fallos += fallos_titulo

    ass_txt = open(ass, encoding="utf-8").read()
    geo = "1920" in ass_txt.split("PlayResY")[0] and "pos(960,540)" in ass_txt
    print(f"{OK if geo else MAL} geometría: PlayRes 1920x1080 + pos(960,540)")
    if not geo:
        fallos.append("geometría de subtítulos incorrecta")
    return fallos


def audita_shorts(shorts_dir, temp_dir, n_medir=0, model="small"):
    print(f"\n=== SHORTS: {shorts_dir} ===")
    fallos = []
    titulos_f = sorted(glob.glob(os.path.join(shorts_dir, "*_title.txt")))
    mp4s = sorted(glob.glob(os.path.join(shorts_dir, "*.mp4")))
    print(f"{OK} artefactos: {len(mp4s)} mp4 y {len(titulos_f)} títulos")
    if len(mp4s) != len(titulos_f):
        fallos.append("faltan artefactos de shorts")

    titulos = [open(f, encoding="utf-8").read().strip() for f in titulos_f]
    if titulos:
        unicos = len(set(titulos))
        print(f"{OK if unicos == len(titulos) else MAL} títulos únicos: {unicos}/{len(titulos)}")

        # Los shorts NO se suben automáticamente todavía, así que esto es
        # informativo (AVISO), nunca FALLA. Y no se tocan los títulos: se
        # narran, y recortarlos cambiaría la narración (medido: 4/30 lo superan).
        largos = [(os.path.basename(f)[: -len("_title.txt")], len(t))
                  for f, t in zip(titulos_f, titulos) if len(t) > 100]
        print(f"{AVISO if largos else OK} títulos de shorts >100 caracteres: "
              f"{len(largos)}/{len(titulos)} (informativo: los shorts no se suben "
              f"automáticamente)")
        for stem, n in largos[:5]:
            print(f"       {stem}: {n} caracteres")
        aperturas = [t.split()[0].lower() for t in titulos if t.split()]
        distintas = len(set(aperturas))
        racha = maxracha = 1
        for a, b in zip(aperturas, aperturas[1:]):
            racha = racha + 1 if a == b else 1
            maxracha = max(maxracha, racha)
        est = OK if maxracha <= 6 else AVISO
        print(f"{est} aperturas: {distintas} palabras iniciales distintas, "
              f"racha máxima {maxracha} títulos seguidos con la misma")

    # --- arranque MUTILADO: el short narra un trozo roto de su propio título
    # `_ensure_title_at_start` recorta el solape por PREFIJO palabra a palabra.
    # Si el modelo parafraseó ("Mi padrino DE BAUTISMO vendió..."), el match
    # rompe en la 2.ª palabra y la cola del título se queda pegada detrás: se
    # oye en el segundo 1, que en vertical es el producto entero. Medido: 7 de
    # 48 shorts del corpus, 2 de los 14 de la última corrida.
    mutilados, medidos = [], 0
    for f in titulos_f:
        stem = os.path.basename(f)[: -len("_title.txt")]
        srt = os.path.join(temp_dir, f"{stem}_subs.srt")
        ass = os.path.join(temp_dir, f"{stem}_subs.ass")
        titulo = [_norm_pal(w) for w in open(f, encoding="utf-8").read().split()]
        if len(titulo) < 5:
            continue
        # El .srt trae la narración ENTERA; el .ass de un short arranca DESPUÉS
        # del título (`skip_until`), así que en él la cola mutilada está en la
        # posición 0. Medirlo sobre el .ass sin tener esto en cuenta da 0
        # detecciones sobre un corpus donde el defecto sí existe.
        if os.path.exists(srt):
            narrado = [_norm_pal(w) for w in re.sub(r"\d+\n[\d:,]+ --> [\d:,]+", " ",
                                                    open(srt, encoding="utf-8-sig").read()).split()]
            despues = narrado[len(titulo):len(titulo) + 40]
        elif os.path.exists(ass):
            despues = [_norm_pal(w) for w, _, _ in lee_ass(ass)][:40]
        else:
            continue
        medidos += 1
        if len(despues) < 6:
            continue
        # 4-gramas de la COLA del título que reaparecen justo después de él
        cola = {" ".join(titulo[i:i + 4]) for i in range(max(0, len(titulo) - 8), len(titulo) - 3)}
        eco = [g for g in (" ".join(despues[i:i + 4]) for i in range(max(0, len(despues) - 3)))
               if g in cola]
        if eco:
            mutilados.append((stem, eco[0]))
    if medidos:
        print(f"{OK} arranque medido sobre {medidos}/{len(titulos_f)} shorts")
    if titulos_f:
        est = OK if not mutilados else MAL
        print(f"{est} arranque de shorts: {len(mutilados)} narran un trozo repetido "
              f"de su propio título")
        for stem, g in mutilados[:3]:
            print(f"       {stem}: ...{g}...")
        if mutilados:
            fallos.append(f"{len(mutilados)} shorts empiezan repitiendo un fragmento "
                          f"de su título")

    # sincronismo de una muestra de shorts (el gemelo que nadie mira)
    for mp4 in mp4s[:n_medir]:
        stem = os.path.splitext(os.path.basename(mp4))[0]
        ass = os.path.join(temp_dir, f"{stem}_subs.ass")
        if not os.path.exists(ass):
            # Nunca en silencio: un short que no se mide parece un short sano.
            print(f"{AVISO} {stem}: sin {os.path.basename(ass)}, NO se ha medido "
                  f"su sincronismo")
            continue
        aw = lee_ass(ass)
        pares = empareja(aw, transcribe(extrae_audio(mp4), model))
        if len(pares) / max(1, len(aw)) < 0.85:
            print(f"{AVISO} {stem}: emparejado bajo, sin veredicto")
            continue
        pt = peor_tramo(pares)
        errs = [e for *_, e in pares]
        med = sum(abs(e) for e in errs) / len(errs)
        est = OK if pt and abs(pt["mediana"]) <= 0.35 else MAL
        detalle = f"  peor tramo {pt['mediana']:+.3f}s" if pt else " (sin tramo medible)"
        print(f"{est} {stem}: medio {med:.3f}s{detalle}")
        if est == MAL:
            fallos.append(f"{stem} desincronizado")

        # el mismo agujero de cobertura, en el gemelo: 3 de los 20 shorts del
        # 11-ago tenían voz sonando con la pantalla sin subtítulo
        huecos, total = voz_sin_subtitulo(mp4, aw)
        est = OK if total < 0.5 else MAL
        print(f"{est} {stem}: voz SIN subtítulo {total:.2f}s en {len(huecos)} tramo(s)")
        if est == MAL:
            fallos.append(f"{stem}: {total:.1f}s de voz sin subtítulo")
    return fallos


def escribe_veredicto(video, fallos, medido=True):
    """Deja el veredicto JUNTO al vídeo, para que algo pueda actuar sobre él.

    Un aviso impreso en un log no defiende de nada: este pipeline es autónomo y
    nadie lee el log en tiempo real (§12). El dashboard lee este fichero y no
    ofrece para subir un vídeo que no lo tenga en verde.
    """
    destino = video[: -len("_final.mp4")] + "_audit.json"
    with open(destino, "w", encoding="utf-8") as f:
        json.dump({
            "ok": medido and not fallos,
            "medido": medido,
            "fallos": fallos,
            "fecha": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        }, f, ensure_ascii=False, indent=2)
    return destino


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output", default="./output")
    ap.add_argument("--shorts-dir", default="./shorts_tiktok")
    ap.add_argument("--temp", default="./temp")
    ap.add_argument("--shorts", type=int, default=2,
                    help="cuántos shorts medir de sincronismo (0 = ninguno)")
    ap.add_argument("--chunk-dur", type=float, help="duración del chunk, para el ratio")
    ap.add_argument("--model", default="small")
    ap.add_argument("--stem", help="auditar SOLO estos vídeos, separados por comas "
                                   "(ej: video_007,video_008). Sin esto audita todos "
                                   "los de output/, que en produccion es re-transcribir "
                                   "el catalogo entero con whisper")
    args = ap.parse_args()

    solo = {s.strip() for s in args.stem.split(",")} if args.stem else None

    fallos = []
    for video in sorted(glob.glob(os.path.join(args.output, "*_final.mp4"))):
        stem = os.path.basename(video)[: -len("_final.mp4")]
        if solo and stem not in solo:
            continue
        ass = os.path.join(args.temp, f"{stem}_subs.ass")
        story = os.path.join(args.temp, f"{stem}_story.txt")
        if not os.path.exists(ass):
            # Sin .ass no se ha MEDIDO nada. Eso no es "sano": es desconocido, y
            # el default tiene que caer del lado barato (§16).
            print(f"{AVISO} sin .ass para {stem}: ¿corriste sin --keep-temp? "
                  f"NO se ha auditado, así que NO entra en la cola de subida")
            escribe_veredicto(video, ["no auditado: falta el .ass (¿sin --keep-temp?)"],
                              medido=False)
            fallos.append(f"{stem} sin auditar")
            continue
        f_video = audita_video(video, ass, story, args.chunk_dur, args.model)
        escribe_veredicto(video, f_video)
        fallos += f_video

    fallos += audita_shorts(args.shorts_dir, args.temp, args.shorts, args.model)

    print("\n" + "=" * 62)
    if fallos:
        print(f"VEREDICTO: NO PUBLICABLE — {len(fallos)} problema(s)")
        for f in fallos:
            print(f"  - {f}")
        return 1
    print("VEREDICTO: sin defectos MEDIBLES.")
    print("Ojo: esto NO dice que sea bueno. Si la historia engancha, si la voz")
    print("suena natural y si la miniatura llama, eso lo juzga Diego.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
