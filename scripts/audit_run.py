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
  python scripts/audit_run.py --shorts-stems short_005,short_006  # [GATE-05]
      # acota TODA la auditoría de shorts (pares, huérfanos, variedad,
      # arranque, sincronismo) a esos stems, en vez del directorio entero
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.eval_sync import (  # noqa: E402
    lee_ass, extrae_audio, transcribe, empareja, peor_tramo,
    pausas_fuera_de_puntuacion,
)
from modules.utils import huella_auditor  # noqa: E402

OK, MAL, AVISO = "  OK  ", " FALLA", " AVISO"

_RE_NORM = re.compile(r"[^\wáéíóúñüÁÉÍÓÚÑÜ]+", re.UNICODE)


def _norm_pal(w):
    return _RE_NORM.sub("", w.lower())


def _ffprobe(path, campos, stream=False):
    """Devuelve los valores pedidos, o `None` si ffprobe NO pudo medirlos.

    [GATE-02]: antes devolvía `r.stdout.split()` sin mirar `returncode`. Con un
    fichero inexistente o corrupto, ffprobe termina con error y stdout viene
    VACÍO -> `[]` -> los consumidores hacían `float(...[0])` y reventaban con
    IndexError SIN mensaje sobre qué falló, o (peor, si el campo pedido tenía
    varios valores) tomaban un resultado parcial por bueno. `None` es explícito:
    "no se pudo medir", nunca "0" ni una lista vacía silenciosa (§16).
    """
    sel = ["-select_streams", "v:0"] if stream else []
    ent = f"stream={campos}" if stream else f"format={campos}"
    r = subprocess.run(
        ["ffprobe", "-v", "error", *sel, "-show_entries", ent,
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True)
    valores = r.stdout.split()
    n_esperado = len(campos.split(","))
    if r.returncode != 0 or len(valores) < n_esperado:
        return None
    return valores


def loudness(path):
    """LUFS integrados, medidos con ebur128 (el estándar que usa YouTube).

    `None, None` si ffmpeg no pudo medir (returncode != 0): antes solo se
    miraba si el patrón aparecía en stderr, así que un ffmpeg que fallaba
    ANTES de llegar al filtro `ebur128` daba el mismo `None` que uno que
    terminaba bien y no encontraba el patrón — resultado correcto por
    casualidad, pero sin la guarda explícita cualquier salida parcial de
    stderr con texto parecido lo habría colado como medido.
    """
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-i", path, "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
        capture_output=True, text=True)
    if r.returncode != 0:
        return None, None
    m = re.findall(r"I:\s+(-?\d+\.\d+)\s+LUFS", r.stderr)
    p = re.findall(r"Peak:\s+(-?\d+\.\d+)\s+dBFS", r.stderr)
    return (float(m[-1]) if m else None), (float(p[-1]) if p else None)


def _silencios(path, umbral_db=-35, dur_min=0.25):
    """Tramos de silencio del audio, medidos con `silencedetect`.

    Instrumento que NO depende de Whisper: cuando el alineador y edge-tts se
    contradijeron en 5 s, esto fue lo que decidió quién mentía [ANCLA-03].

    Devuelve `None` si ffmpeg NO pudo medir (returncode != 0) — [GATE-02]:
    antes ignoraba el `returncode` y devolvía `[]` en ese caso, INDISTINGUIBLE
    de "medí el audio y no hay silencios". Eso es lo que hacía que
    `pausas_inventadas` diera `exceso = max(0, 0 - signos) = 0` -> "0,0 pausas
    por 1000 palabras", la nota perfecta, con un audio que ni se pudo abrir.
    `[]` (lista vacía) sigue significando "medido, 0 silencios"; `None`
    significa "no se sabe". El llamador NUNCA puede tratar el segundo como el
    primero.
    """
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-i", path, "-af",
         f"silencedetect=noise={umbral_db}dB:d={dur_min}", "-f", "null", "-"],
        capture_output=True, text=True)
    if r.returncode != 0:
        return None
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

    Devuelve `(None, None)` si ffprobe o `_silencios` no pudieron medir sobre
    `media` [GATE-02]. Antes se indexaba `_ffprobe(...)[0]` sin comprobar
    nada (IndexError sin contexto con un fichero corrupto) y se iteraba
    `_silencios(media)` dando por hecho que SIEMPRE era una lista: con el
    fix de abajo eso ahora puede ser `None`, y `None` NUNCA se trata como
    "cero huecos" en el llamador.
    """
    if not ass_words:
        return [], 0.0
    dur_campos = _ffprobe(media, "duration")
    if dur_campos is None:
        return None, None
    dur = float(dur_campos[0])
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
    sil = _silencios(media)
    if sil is None:
        return None, None
    voz, prev = [], inicio
    for s, e in sil:
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
    # [GATE-06] El camino de un solo bloque (`_generar_historia_un_bloque`, para
    # historias que caben en WORDS_PER_BLOCK) pide la historia COMPLETA —con
    # desenlace— en la MISMA llamada, así que no hay ningún bloque de cierre que
    # pedir aparte y no emite ninguna de las dos líneas de arriba. Sin esta rama
    # el check FALLA sobre toda historia corta, incluida una que sí tiene final
    # (`video_008`, verificado: termina en "Ahora duermo tranquilo...").
    #
    # Se comprueba por MARCADOR, no leyendo el guion: "¿este texto tiene un final
    # satisfactorio?" es el juicio que §18 prohíbe pedirle a un heurístico, y un
    # check que lo intentara pasaría siempre (clase [GATE-04]/[GATE-05]: fallar
    # ABIERTO). El hecho determinista es el simétrico al del camino multi-bloque:
    # allí se comprueba que el desenlace SE PIDIÓ; aquí, que se pidió COMPLETA en
    # una sola llamada. Si además se hubiera quedado por debajo del 85% del
    # objetivo, `generate_story` pide el cierre aparte y emite "Cierre anadido"
    # (o aborta con RuntimeError y no hay vídeo que auditar), así que ese caso ya
    # lo caza la rama de arriba.
    #
    # OJO: esto NO ablanda [CIERRE-01]. Esa clase vive en el bucle multi-bloque,
    # que nunca emite esta línea, y allí el check conserva los dientes intactos.
    if "cabe en un solo bloque" in tramo:
        return True, ("la historia cabia en un bloque: se pidio COMPLETA con "
                      "desenlace en una sola llamada")
    return False, ("la historia se cerro SIN bloque de desenlace: el bucle salio "
                   "por el 85% del objetivo (clase [CIERRE-01])")


_RE_TRUNCANDO = re.compile(r"Truncando de (\d+) a ~?(\d+) palabras")
_RE_TRUNCADO_DESCARTA = re.compile(r"Truncado: se descartan (\d+) palabras del CUERPO")


def truncado_narrativo(log_path, stem):
    """[TRUNCA-01] ¿El truncado de esta historia mutiló el CUERPO?

    `_truncate_to_words` (script_generator.py) deja constancia en el log de
    CUÁNTO descarta cada vez que trunca, pero hasta este check NADA leía ese
    WARNING: es "el aviso más ruidoso del log" y ningún gate lo comprobaba
    (§12 -- un aviso que solo se imprime no defiende de nada en un pipeline
    que nadie lee en tiempo real). Caso real: `video_007` descartó el 73,4%
    del guion y salió con el gate en verde.

    Reusa el MISMO umbral que la defensa de generación
    (`_TRUNCADO_CUERPO_MAX_FRAC` de `script_generator`, importado aquí en vez
    de duplicado) para que auditor y generador midan con la misma vara: un
    vídeo producido ANTES de que el `if` existiera puede seguir superando el
    umbral y esta es la red que lo caza en la salida ya publicada.

    Devuelve `(bool|None, motivo, fraccion|None)`. `None` cuando no se pudo
    comprobar (sin log, sin tramo) -- nunca se lee como "sano" (§16).
    """
    if not os.path.exists(log_path):
        return None, "sin pipeline.log: no se puede comprobar el truncado", None
    texto = open(log_path, encoding="utf-8", errors="replace").read()
    bloques = texto.split("=== Produciendo ")
    tramo = next((b for b in reversed(bloques) if b.startswith(stem)), None)
    if tramo is None:
        return None, f"no hay tramo de {stem} en el log", None
    tramo = tramo.split("=== Completado")[0]

    m_total = _RE_TRUNCANDO.search(tramo)
    m_desc = _RE_TRUNCADO_DESCARTA.search(tramo)
    if not m_total or not m_desc:
        return True, "esta historia no se truncó", None

    total = int(m_total.group(1))
    if total <= 0:
        return None, f"log con total={total}: no se puede calcular la fracción", None
    descartadas = int(m_desc.group(1))
    frac = descartadas / total

    from modules.script_generator import _TRUNCADO_CUERPO_MAX_FRAC
    if frac > _TRUNCADO_CUERPO_MAX_FRAC:
        return False, (
            f"el truncado descartó el {frac:.0%} del guion ({descartadas}/{total} "
            f"palabras) -- por encima del {_TRUNCADO_CUERPO_MAX_FRAC:.0%} máximo. "
            f"La versión actual del generador ABORTARÍA esta corrida en vez de "
            f"publicarla (clase [TRUNCA-01])"
        ), frac
    return True, f"truncado dentro del umbral ({frac:.0%} del guion descartado)", frac


# --- Coherencia título <-> cuerpo narrado [TRUNCA-01] ------------------------
# `truncado_narrativo` (arriba) mide la CAUSA (cuánto se descartó); esto mide
# la CONSECUENCIA sobre el texto que de verdad se publicó: ¿lo que el título
# promete en su cláusula resolutiva se narra en algún sitio del cuerpo?
#
# Caso real: `video_007` anuncia "...Pero El Notario Descubrió La Coacción Y
# Anuló Todo" y `anul-` aparece CERO veces fuera del título.
#
# Determinista (§18 -- un juicio que el modelo no puede dar se vuelve
# determinista o hueco): se aísla la cláusula tras el ÚLTIMO conector
# adversativo/temporal del título (acotada a `_COHERENCIA_MAX_PALABRAS` para
# no arrastrar la descripción de ambiente que a veces sigue a la cláusula
# real -- medido: sin este tope, un título con "...pero no sabía que había
# grabado la conversación... Y ESA FRASE RETUMBÓ EN MI CABEZA MIENTRAS EL
# SILENCIO SE APODERABA DE LA SALA DECORADA CON LUCES... Y EL OLOR A PAVO
# ASADO..." diluye el ratio con palabras de atrezzo que nunca se repiten ni
# en una historia SANA). Se comparan RAÍCES (prefijo de 5, no forma exacta:
# "anuló"/"anulación"/"anular" comparten raíz), y solo se cuentan las que
# reaparecen FUERA de la frase-título.
#
# CALIBRACIÓN (medida sobre el corpus real en disco, 14-ago-2026):
#   historias SANAS (título forzado al inicio, resolución confirmada a mano
#   palabra por palabra vía grep -- `data/evidence/video_001_story.txt` y las
#   dos historias de PRODUCCIÓN real que quedan en `temp/`):
#     ratio  0.67 / 1.00 / 1.00
#   `video_007` (el caso roto que motiva este check):
#     ratio  0.50
#   Otros truncados severos del mismo fixture E2E (test_e2e/temp/video_00{1,2,4,6}),
#   con la MISMA forma del defecto (descarte >70% del CUERPO), para contraste:
#     ratio  0.50 / 0.20 / 0.50 / 0.00
# Separación con margen de 0.17 (0.67 sano vs 0.50 roto). Umbral en el punto
# medio, 0.60. Con menos de `_COHERENCIA_MIN_CLAVES` palabras de contenido
# extraídas de la cláusula (título sin conector reconocible, o cláusula muy
# corta -- 2 de los casos anteriores caen aquí) el check SE ABSTIENE: no hay
# señal suficiente para juzgar, mismo patrón que `_validar_puntuacion` en
# `script_generator` cuando el texto es demasiado corto.
_RE_CONECTOR_RESOLUCION = re.compile(r"\b(pero|aunque|hasta que)\b", re.IGNORECASE)
_COHERENCIA_MAX_PALABRAS = 12
_COHERENCIA_MIN_CLAVES = 3
_COHERENCIA_MIN_RATIO = 0.60
# Auxiliares/relleno narrativo que aparecen en CASI cualquier frase de este
# género (verbos "haber"/"saber"/"tener" en pasado, atrezzo de escena) y que
# NO discriminan si la escena de resolución se narró o no -- medido: sin
# excluirlos, una historia SANA caía al mismo ratio que una rota porque
# ambas comparten "mientras", "cabeza", "siempre"... en cualquier párrafo.
_COHERENCIA_STOP_EXTRA = frozenset((
    "habia", "sabia", "tenia", "contaba", "aquello", "aquella", "completo",
    "siempre", "cara", "mientras", "cabeza", "frase", "frases", "momento",
    "instante", "esa", "ese", "esta", "este", "ante", "donde",
    "toda", "todo", "todos", "todas",
))


def _coherencia_norm_stem(w):
    import unicodedata
    w = w.lower()
    w = "".join(c for c in unicodedata.normalize("NFD", w) if unicodedata.category(c) != "Mn")
    w = re.sub(r"[^a-z]", "", w)
    return w[:5] if len(w) > 5 else w


def _clausula_resolutiva(titulo, max_palabras=_COHERENCIA_MAX_PALABRAS):
    """La cláusula tras el ÚLTIMO conector adversativo/temporal del título,
    acotada a `max_palabras`. `None` si no hay conector reconocible."""
    matches = list(_RE_CONECTOR_RESOLUCION.finditer(titulo))
    if not matches:
        return None
    resto = titulo[matches[-1].end():]
    palabras = resto.split()[:max_palabras]
    return " ".join(palabras) if palabras else None


def coherencia_titulo_cuerpo(story_path):
    """¿Lo que el título promete en su cláusula resolutiva se narra en el cuerpo?

    Devuelve `(bool|None, motivo, ratio|None)`. Ver la calibración completa
    junto a las constantes de arriba.
    """
    from modules.script_generator import _ES_FUNCIONALES

    texto = open(story_path, encoding="utf-8").read()
    m = re.search(r"[.!?]", texto)
    if not m:
        return None, "el guion no tiene ni una frase completa: no se puede aislar el título", None
    titulo = texto[:m.end()].rstrip(".!?")
    cuerpo = texto[m.end():]

    clausula = _clausula_resolutiva(titulo)
    if clausula is None:
        return None, ("título sin cláusula resolutiva reconocible (sin "
                      "'pero'/'aunque'/'hasta que'): no se puede comprobar"), None

    claves = [
        w for w in re.findall(r"[a-záéíóúñü]+", clausula.lower())
        if w not in _ES_FUNCIONALES and w not in _COHERENCIA_STOP_EXTRA and len(w) >= 4
    ]
    if len(claves) < _COHERENCIA_MIN_CLAVES:
        return None, (
            f"cláusula resolutiva con solo {len(claves)} palabra(s) de contenido "
            f"(mínimo {_COHERENCIA_MIN_CLAVES}): no hay señal suficiente para juzgar"
        ), None

    stems_clave = {_coherencia_norm_stem(w) for w in claves}
    stems_cuerpo = {_coherencia_norm_stem(w) for w in re.findall(r"[a-záéíóúñü]+", cuerpo.lower())}
    encontrados = stems_clave & stems_cuerpo
    ratio = len(encontrados) / len(stems_clave)

    if ratio < _COHERENCIA_MIN_RATIO:
        faltan = sorted(stems_clave - encontrados)
        return False, (
            f"el título promete «...{clausula.strip()}» pero solo el {ratio:.0%} de sus "
            f"palabras de contenido reaparece en el cuerpo narrado (raíces ausentes: "
            f"{', '.join(faltan)}) -- la resolución probablemente NO se narra "
            f"(clase [TRUNCA-01])"
        ), ratio
    return True, f"{ratio:.0%} de la cláusula resolutiva reaparece en el cuerpo narrado", ratio


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


# Tope de pausas que edge-tts se inventa (no hay ningún signo detrás), por cada
# 1000 palabras. Calibrado sobre las producciones reales, no sobre el fixture:
#   12-ago, el vídeo que Diego rechazó de oído ............ 16,1  -> FALLA
#   el mismo guion con el partidor de frases puesto ....... 8,8   -> OK
# Es un detector de REGRESIÓN con dos puntos de anclaje, no una vara absoluta de
# calidad: dice "esto se parece al vídeo que Diego rechazó", que es exactamente
# lo que el gate no supo decir el 12-ago.
PAUSAS_INVENTADAS_POR_1000 = 12.0


def pausas_inventadas(wav, story_path):
    """Silencios que NO tienen ningún signo de puntuación detrás.

    Devuelve (exceso_absoluto, por_1000_palabras). `None` si no se puede medir,
    que NO es lo mismo que cero: el llamador debe tratarlo como desconocido.
    """
    try:
        with open(story_path, encoding="utf-8") as f:
            crudo = f.read()
        from modules.tts_engine import _clean_speech_for_tts
        # El texto que de verdad oyó el TTS, no el guion crudo: la limpieza mete
        # comas y puntos de respiración, así que juzgar el crudo es juzgar un
        # artefacto que el pipeline sobrescribe aguas abajo.
        texto = _clean_speech_for_tts(crudo)
    except Exception as e:
        print(f"{AVISO} no se pudo reconstruir el texto narrado: {e}")
        return None, None
    palabras = len(texto.split())
    if palabras < 500:
        return None, None
    signos = sum(texto.count(c) for c in ".,;:!?")
    sil = _silencios(wav)
    if sil is None:
        # [GATE-02]: esta es la fuga real. `_silencios` fallando (ffmpeg no
        # pudo abrir `wav`) daba ANTES `[]`, y `max(0, 0 - signos) = 0` ->
        # "0,0 pausas por 1000 palabras", indistinguible de un audio limpio.
        print(f"{AVISO} no se pudieron medir los silencios de {wav}: ffmpeg falló")
        return None, None
    exceso = max(0, len(sil) - signos)
    return exceso, exceso / palabras * 1000


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

    # `pt` es None con menos de 40 pares (`eval_sync.peor_tramo`). El gemelo de
    # shorts (`audita_shorts`) ya tenía la guarda `if pt and ...`; aquí faltaba, y
    # un vídeo corto reventaba con TypeError llevándose por delante las otras 13
    # mediciones y sustituyéndolas por un traceback.
    est = OK if (pt and abs(pt["mediana"]) <= 0.35) else MAL
    if est == MAL and pt:
        fallos.append(f"peor tramo {pt['mediana']:+.3f}s en t={pt['t']}s")
    elif not pt:
        fallos.append("sincronismo: sin tramo medible (menos de 40 palabras "
                      "emparejadas), no se sabe si está sincronizado")
    tramo = (f"PEOR TRAMO {pt['mediana']:+.3f}s en t={pt['t']}s" if pt
             else "PEOR TRAMO: sin tramo medible")
    print(f"{est} sincronismo: medio {med:.3f}s  p95 {p95:.3f}s  sesgo {sesgo:+.3f}s  "
          f"{tramo}  ({tarde} palabras >0,5 s tarde)")
    if sesgo > 0:
        print(f"{AVISO} sesgo POSITIVO: el subtítulo va por detrás de la voz (se busca negativo)")

    pausas = pausas_fuera_de_puntuacion(ass)
    print(f"{OK if not pausas else AVISO} pausas fuera de puntuación (sobre el .ass, "
          f"CIRCULAR — informativo): {len(pausas)}")

    # --- pausas inventadas, ACÚSTICAMENTE. Esta es la que tiene dientes.
    #
    # La de arriba mide huecos en el .ass, o sea la alineación que este mismo
    # auditor está juzgando: es la trampa de medición circular de §D, y además
    # solo imprimía un AVISO. Diego escuchó el vídeo del 12-ago y dijo "hay
    # muchas pausas, además en sitios que no debería, y cuesta de entender"
    # mientras el veredicto salía en VERDE.
    #
    # Instrumento: silencedetect sobre el audio + recuento de signos sobre el
    # texto EXACTO que recibió edge-tts. Es libre de emparejador (no hay que
    # decidir qué silencio va con qué signo, solo contarlos), que es justo lo
    # que salvó esta medición: el emparejador por reloj de habla falló su
    # calibración al 8% sobre 26 min y sus números eran basura plausible.
    exceso, por_mil = pausas_inventadas(wav, story)
    if por_mil is not None:
        est = OK if por_mil <= PAUSAS_INVENTADAS_POR_1000 else MAL
        print(f"{est} pausas inventadas (acústico): {exceso} = {por_mil:.1f} por 1000 "
              f"palabras (máximo {PAUSAS_INVENTADAS_POR_1000})")
        if est == MAL:
            fallos.append(
                f"{exceso} pausas inventadas ({por_mil:.1f} por 1000 palabras, máximo "
                f"{PAUSAS_INVENTADAS_POR_1000}): edge-tts respira donde no hay signo, "
                f"que es lo que suena a 'pausas en sitios que no debería'")
    else:
        # No medible NO es sano, es desconocido, y el default cae del lado
        # barato (§16). Antes esta rama no existía y el vídeo pasaba en silencio.
        print(f"{MAL} pausas inventadas: NO se han podido medir (¿falta el guion "
              f"en temp/, o es demasiado corto?)")
        fallos.append("pausas inventadas: no medibles, así que no se sabe si suena bien")

    # --- COBERTURA: lo que ninguna métrica de desfase puede ver
    huecos, total_hueco = voz_sin_subtitulo(video, ass_words)
    if total_hueco is None:
        # [GATE-02]: no medible NUNCA es "0 huecos". ffprobe/ffmpeg fallaron
        # sobre este vídeo.
        print(f"{MAL} voz SIN subtítulo: NO se pudo medir (ffprobe/ffmpeg "
              f"fallaron sobre {os.path.basename(video)})")
        fallos.append("voz sin subtítulo: no medible (ffprobe/ffmpeg fallaron), "
                      "no se sabe si hay tramos sin subtitular")
    else:
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

    # --- [TRUNCA-01] el truncado mutiló el CUERPO (la causa)
    truncado_ok, motivo_trunc, _frac_trunc = truncado_narrativo(
        _busca_pipeline_log(os.path.dirname(ass) or "."),
        os.path.basename(video)[: -len("_final.mp4")])
    if truncado_ok is None:
        print(f"{AVISO} truncado narrativo: {motivo_trunc}")
    else:
        print(f"{OK if truncado_ok else MAL} truncado narrativo: {motivo_trunc}")
        if not truncado_ok:
            fallos.append(f"truncado mutilante: {motivo_trunc}")

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

        # --- [TRUNCA-01] coherencia título <-> cuerpo (la consecuencia)
        try:
            coherente, motivo_coh, _ratio_coh = coherencia_titulo_cuerpo(story)
            if coherente is None:
                print(f"{AVISO} coherencia título/cuerpo: {motivo_coh}")
            elif coherente:
                print(f"{OK} coherencia título/cuerpo: {motivo_coh}")
            # Este check mide la CONSECUENCIA de [TRUNCA-01]: el truncado se
            # llevó la resolución. Su señal es que las palabras de la cláusula
            # resolutiva del título no reaparecen en el cuerpo... y esa señal
            # NO distingue "no lo narra" de "lo narra con otras palabras".
            # Medido sobre `video_009` (18-ago): el título prometía «el juez
            # descubrió la estafa y lo mandó a la cárcel», el cuerpo narra «el
            # magistrado leyó el dictamen pericial», «las grabaciones llegaron
            # al juez» y «leyeron la sentencia de tres años de prisión» — la
            # resolución se narra ENTERA, y el check cantó 40% porque el
            # emparejado es por raíz de 5 caracteres y no sabe que prisión es
            # cárcel. Falso positivo con `truncado narrativo` en OK y el log
            # diciendo "esta historia no se truncó".
            #
            # Por eso BLOQUEA solo cuando hubo truncado, que es cuando el
            # mecanismo que este check persigue puede haber ocurrido. Sin
            # truncado no se puede haber comido nada, así que la discrepancia
            # es paráfrasis mientras no se demuestre lo contrario: se AVISA.
            # No es ablandar el gate — sigue bloqueando `video_008` (truncado
            # del 21%, resolución de verdad ausente) y los 6 casos históricos,
            # que son TODOS los verdaderos positivos observados.
            elif not _frac_trunc:
                print(f"{AVISO} coherencia título/cuerpo: {motivo_coh}")
                print(f"{AVISO}   ...pero esta historia NO se truncó, así que no "
                      f"bloquea: sin truncado la causa de [TRUNCA-01] no puede "
                      f"haber ocurrido y el check no distingue paráfrasis")
            else:
                print(f"{MAL} coherencia título/cuerpo: {motivo_coh}")
                fallos.append(f"coherencia título/cuerpo: {motivo_coh}")
        except Exception as e:
            print(f"{AVISO} no se pudo comprobar la coherencia título/cuerpo: {e}")

        # [BASURA-03]: el modelo se auto-audita en un BLOQUE de markdown al
        # final ("**Resumen de los elementos solicitados incluidos:** 1.
        # **Plan...**"), que es español CORRECTO y `_detectar_basura` no lo
        # ve (no es una ráfaga léxica). Se mide EL FINAL del guion publicado,
        # no solo la cabecera: si `_strip_trailing_metadata` falló en
        # generación por una forma nueva, esta es la última red antes de que
        # Diego lo mire.
        try:
            from modules.script_generator import _detectar_meta_cola
            hay_meta, motivo_meta, _pos = _detectar_meta_cola(texto)
            print(f"{MAL if hay_meta else OK} auto-anotación en la cola: "
                  f"{motivo_meta if hay_meta else 'ninguna'}")
            if hay_meta:
                fallos.append(f"auto-anotación del modelo en la cola: {motivo_meta}")
        except Exception as e:
            print(f"{AVISO} no se pudo comprobar la auto-anotación en la cola: {e}")

        n_dup, largo = ngramas_repetidos(texto)
        print(f"{MAL if n_dup else OK} párrafos repetidos: {n_dup} n-gramas de 12 "
              f"(tramo más largo: {largo} palabras)")
        if n_dup:
            fallos.append(f"{largo} palabras narradas dos veces")

        # --- puntuación narrativa [COMA-03]: el mismo guardia que ya corre en
        # generación (`script_generator._validar_puntuacion`), aplicado sobre
        # el guion COMPLETO. Sin comas, edge-tts inventa dónde respirar (medido:
        # 88 pausas fuera de puntuación en la corrida del 12-ago con 1 sola
        # coma en 5334 palabras). El guardia de generación acepta el MEJOR
        # intento tras agotar reintentos en vez de abortar el vídeo — esta
        # comprobación es la que le pone dientes: si ese "mejor intento" sigue
        # por debajo del umbral, el vídeo NO entra en la cola de subida.
        try:
            from modules.script_generator import (
                _densidad_comas, _PUNTUACION_MIN_COMAS_100, _PUNTUACION_MIN_PALABRAS,
            )
            from modules.tts_engine import _clean_speech_for_tts
            # SOBRE EL TEXTO NARRADO, no sobre el guion crudo. Medido: el guion
            # del 12-ago tiene 0,02 comas/100 en crudo pero 3,11 después de la
            # limpieza, y el del 11-ago 0,19 -> 2,74. Las dos PASAN el umbral en
            # cuanto se mide lo que de verdad se oye, así que juzgar el crudo
            # rechazaba guiones cuya forma hablada ya cumplía.
            narrado = _clean_speech_for_tts(texto)
            n_texto = len(narrado.split())
            if n_texto >= _PUNTUACION_MIN_PALABRAS:
                dens = _densidad_comas(narrado)
                # Sin dientes A PROPÓSITO: la densidad de comas no predice el
                # defecto. Con 10x más comas crudas (11-ago vs 12-ago) las
                # pausas inventadas fueron 102 vs 86, indistinguible. Quien
                # corta es la métrica acústica de arriba, que mide la
                # consecuencia en vez del correlato.
                print(f"{OK if dens >= _PUNTUACION_MIN_COMAS_100 else AVISO} "
                      f"puntuación narrativa (informativo): {dens:.2f} comas/100 "
                      f"palabras sobre el texto NARRADO")
            else:
                print(f"{AVISO} puntuación narrativa: guion de {n_texto} palabras, "
                      f"insuficiente para medir densidad de comas con fiabilidad "
                      f"(mínimo {_PUNTUACION_MIN_PALABRAS})")
        except Exception as e:
            print(f"{AVISO} no se pudo comprobar la puntuación: {e}")

    # --- artefactos, duración y peso
    #
    # [GATE-02]: antes se indexaba `_ffprobe(...)[0]` a pelo, así que un vídeo
    # corrupto o inaccesible reventaba con IndexError sin decir qué falló (y,
    # con el `_ffprobe` viejo, un campo parcialmente leído se tomaba por
    # bueno). `None` bloquea explícitamente en vez de fallar en silencio.
    dur_f = _ffprobe(video, "duration")
    br_f = _ffprobe(video, "bit_rate")
    wh_f = _ffprobe(video, "width,height", stream=True)
    if dur_f is None or br_f is None or wh_f is None:
        print(f"{MAL} artefactos: ffprobe NO pudo medir duración/bitrate/resolución "
              f"de {os.path.basename(video)} (¿archivo corrupto o inaccesible?)")
        fallos.append(f"ffprobe no pudo medir {os.path.basename(video)}: "
                      f"no se sabe si el vídeo está sano")
        dur = None
    else:
        dur = float(dur_f[0])
        size_gb = os.path.getsize(video) / 1024**3
        br = float(br_f[0]) / 1e6
        w, h = wh_f[:2]
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
    else:
        # Antes esto se saltaba en silencio si `loudness()` no encontraba el
        # patrón en stderr, indistinguible de "no hizo falta comprobarlo".
        print(f"{AVISO} loudness: NO se pudo medir (ffmpeg falló sobre "
              f"{os.path.basename(video)}) — informativo, no bloquea la subida")

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


def audita_shorts(shorts_dir, temp_dir, n_medir=0, model="small", stems=None):
    """Audita `shorts_dir` -- o, si se pasa `stems`, SOLO esa corrida.

    [GATE-05]: por defecto este auditor mira el DIRECTORIO, que acumula
    artefactos de corridas anteriores. Eso produce dos fallos de medición
    distintos y opuestos, medidos en la corrida de las 17:50-18:05 de hoy:

    1. FALSO POSITIVO: un `<stem>_title.txt` cuyo `<stem>.mp4` ya no existe
       (huérfano de una corrida previa) se contaba como "falta el mp4 de
       ESTA corrida". No es lo mismo: nadie va a publicar ese título sin
       vídeo, pero tampoco es un defecto de la corrida de hoy.
    2. FALSO NEGATIVO por contaminación: "títulos únicos" y "aperturas"
       (variedad de los shorts) se calculaban sobre la MEZCLA de huérfanos +
       pares nuevos + pares de otra corrida vieja, así que no miden la
       variedad de ningún conjunto real.

    Un PAR completo es un stem con `<stem>.mp4` Y `<stem>_title.txt` a la
    vez. Solo los pares completos entran en las métricas de variedad, en el
    check de arranque mutilado y en la medición de sincronismo.
    - `_title.txt` SIN su `.mp4`: huérfano. AVISO informativo, nombrado.
      NUNCA entra en `fallos` -- no bloquea nada, porque no hay vídeo que
      publicar con ese título de todos modos.
    - `.mp4` SIN su `_title.txt`: sigue siendo un fallo real -- un short se
      compuso y no tiene título para publicar. Sigue bloqueando.

    `stems`, si se pasa (p.ej. los stems que acaba de producir ESTA
    corrida), restringe TODO -- pares, huérfanos, métricas, arranque y
    sincronismo -- a esos stems, para que lo que hubiera antes en el
    directorio no contamine la medida.
    """
    print(f"\n=== SHORTS: {shorts_dir} ===")
    fallos = []
    titulos_f_todos = sorted(glob.glob(os.path.join(shorts_dir, "*_title.txt")))
    mp4s_todos = sorted(glob.glob(os.path.join(shorts_dir, "*.mp4")))

    def _stem_de(path, sufijo):
        return os.path.basename(path)[: -len(sufijo)]

    titulos_por_stem = {_stem_de(f, "_title.txt"): f for f in titulos_f_todos}
    mp4_por_stem = {_stem_de(f, ".mp4"): f for f in mp4s_todos}

    if stems is not None:
        print(f"       acotado a --shorts-stems: {len(stems)} stem(s) pedido(s)")
        # Simétrico al `--stem` de vídeos: un stem pedido que no aparece NI
        # como título NI como mp4 no es un huérfano de otra corrida, es que
        # ese short no se produjo. Eso bloquea (MAL), no es informativo.
        no_encontrados = stems - (set(titulos_por_stem) | set(mp4_por_stem))
        if no_encontrados:
            msg = (f"--shorts-stems pidió {len(no_encontrados)} stem(s) que no "
                  f"existen en {shorts_dir}: {', '.join(sorted(no_encontrados))}")
            print(f"{MAL} {msg}")
            fallos.append(msg)
        titulos_por_stem = {s: f for s, f in titulos_por_stem.items() if s in stems}
        mp4_por_stem = {s: f for s, f in mp4_por_stem.items() if s in stems}

    stems_titulo, stems_mp4 = set(titulos_por_stem), set(mp4_por_stem)
    pares_stems = sorted(stems_titulo & stems_mp4)
    huerfanos_titulo = sorted(stems_titulo - stems_mp4)
    huerfanos_mp4 = sorted(stems_mp4 - stems_titulo)

    titulos_f = [titulos_por_stem[s] for s in pares_stems]
    mp4s = [mp4_por_stem[s] for s in pares_stems]

    # [GATE-02]: "0 pares" NO es lo mismo que "medí y están todos bien" — es
    # "no hay nada que auditar aquí". Antes salía en OK, idéntico a la nota
    # perfecta de un directorio con shorts sanos.
    est_artefactos = AVISO if not pares_stems else OK
    print(f"{est_artefactos} artefactos: {len(pares_stems)} par(es) completos "
          f"(mp4 + título)" + ("  (nada que auditar)" if est_artefactos == AVISO else ""))
    if huerfanos_titulo and stems is not None:
        # Si el caller AFIRMA que estos stems son de esta corrida, un título sin
        # su mp4 no puede ser "de otra corrida": es un short que se pidió y no
        # se compuso. Eso bloquea.
        msg = (f"{len(huerfanos_titulo)} short(s) de ESTA corrida con título pero "
               f"SIN mp4 (no se compusieron): {', '.join(huerfanos_titulo)}")
        print(f"{MAL} {msg}")
        fallos.append(msg)
    elif huerfanos_titulo:
        print(f"{AVISO} títulos huérfanos (sin su .mp4, de otra corrida): "
              f"{len(huerfanos_titulo)} -> {', '.join(huerfanos_titulo)}")
    if huerfanos_mp4:
        # Este SÍ bloquea: un .mp4 compuesto sin título no tiene qué publicar.
        print(f"{MAL} mp4 SIN título (nada que publicar): "
              f"{len(huerfanos_mp4)} -> {', '.join(huerfanos_mp4)}")
        fallos.append(f"{len(huerfanos_mp4)} short(s) compuesto(s) sin título: "
                      f"{', '.join(huerfanos_mp4)}")

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
    if titulos_f and not medidos:
        # Sin ni un short medido, `mutilados` está vacío POR NO HABER MIRADO. La
        # línea de abajo decía `OK ... 0 narran un trozo repetido` y el veredicto
        # salía verde: el mismo short defectuoso pasaba de FALLA a OK solo con
        # que faltara su `.srt`.
        print(f"{AVISO} arranque de shorts: NO se pudo medir en ninguno de los "
              f"{len(titulos_f)} (falta su .srt/.ass, o el título es demasiado "
              f"corto): NO se sabe si narran un trozo repetido de su título")
    elif medidos:
        est = OK if not mutilados else MAL
        if medidos < len(titulos_f):
            print(f"{AVISO} arranque medido sobre {medidos}/{len(titulos_f)} shorts "
                  f"-- los otros {len(titulos_f) - medidos} NO se comprobaron")
        else:
            print(f"{OK} arranque medido sobre {medidos}/{len(titulos_f)} shorts")
        print(f"{est} arranque de shorts: {len(mutilados)} narran un trozo repetido "
              f"de su propio título")
        for stem, g in mutilados[:3]:
            print(f"       {stem}: ...{g}...")
        if mutilados:
            fallos.append(f"{len(mutilados)} shorts empiezan repitiendo un fragmento "
                          f"de su título")

    # sincronismo de una muestra de shorts (el gemelo que nadie mira)
    # Se acumulan los que de VERDAD se midieron, no los que se pidieron: los
    # `continue` de abajo (sin .ass, emparejado bajo) saltan shorts, y contar lo
    # pedido hacía que la línea de cobertura dijera "2/2 medidos (todos)" con
    # CERO medidos, justo debajo de dos avisos que decían lo contrario.
    medidos_sync = []
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
        medidos_sync.append(stem)   # aquí sí: el sincronismo se ha medido
        if est == MAL:
            fallos.append(f"{stem} desincronizado")

        # el mismo agujero de cobertura, en el gemelo: 3 de los 20 shorts del
        # 11-ago tenían voz sonando con la pantalla sin subtítulo
        huecos, total = voz_sin_subtitulo(mp4, aw)
        if total is None:
            # [GATE-02]: el mismo fallo abierto, en el gemelo. `None` nunca
            # es "0 huecos".
            print(f"{MAL} {stem}: voz SIN subtítulo NO se pudo medir "
                  f"(ffprobe/ffmpeg fallaron)")
            fallos.append(f"{stem}: voz sin subtítulo no medible")
            continue
        est = OK if total < 0.5 else MAL
        print(f"{est} {stem}: voz SIN subtítulo {total:.2f}s en {len(huecos)} tramo(s)")
        if est == MAL:
            fallos.append(f"{stem}: {total:.1f}s de voz sin subtítulo")

    # --- cobertura del sincronismo: cuántos de los pares se midieron.
    # "No medido" NO puede leerse como "sano" (§16): `--shorts N` con N
    # menor que el número de pares deja el resto SIN verificar, y sin esta
    # línea el informe no lo dice en ningún sitio -- el silencio se lee como
    # "todo bien".
    # Se cuenta lo MEDIDO (`medidos_sync`), no lo pedido: contar lo pedido hacía
    # que esta misma línea dijera "2/2 shorts medidos (todos)" justo debajo de
    # dos avisos de "NO se ha medido su sincronismo". La línea escrita para que
    # "no medido" no se leyera como "sano" decía exactamente eso.
    n_pares = len(mp4s)
    stems_todos = [os.path.splitext(os.path.basename(m))[0] for m in mp4s]
    sin_medir = [s for s in stems_todos if s not in medidos_sync]
    n_medidos = len(medidos_sync)
    if n_pares == 0:
        pass  # ya cubierto por "artefactos: 0 pares"
    elif n_medidos == 0 and n_medir > 0:
        # Se PIDIÓ medir y no se midió ni uno: eso es un fallo de medición, no
        # una elección. Con `--shorts 0` (nadie lo pidió) basta el aviso.
        msg = (f"se pidió medir el sincronismo de {min(n_medir, n_pares)} short(s) "
               f"y NO se pudo medir ninguno (falta su .ass o emparejado bajo): "
               f"no se sabe si están sincronizados")
        print(f"{MAL} cobertura de sincronismo: {msg}")
        fallos.append(msg)
    elif n_medidos == 0:
        print(f"{AVISO} cobertura de sincronismo: 0/{n_pares} shorts medidos "
              f"-- NINGÚN short se verificó (`--shorts 0`: nadie lo pidió). "
              f"Eso no es 'sano', es 'sin comprobar'")
    elif sin_medir:
        print(f"{AVISO} cobertura de sincronismo: {n_medidos}/{n_pares} shorts medidos "
              f"-- SIN medir ({len(sin_medir)}): {', '.join(sin_medir)}")
    else:
        print(f"{OK} cobertura de sincronismo: {n_medidos}/{n_pares} shorts medidos "
              f"(todos)")
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
            # Con qué CRITERIOS se emitió. Sin esto un veredicto en verde
            # sobrevive a un auditor que ya no existe: pasó con video_002.
            "auditor": huella_auditor(),
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
    ap.add_argument("--shorts-stems", help="[GATE-05] auditar SOLO estos shorts, "
                                   "separados por comas (ej: short_005,short_006). Sin "
                                   "esto audita TODO --shorts-dir, que acumula pares y "
                                   "huerfanos de corridas anteriores. main.py todavia NO "
                                   "pasa este flag: pendiente cablearlo con los stems que "
                                   "acaba de producir la corrida (ver informe)")
    args = ap.parse_args()

    solo = {s.strip() for s in args.stem.split(",")} if args.stem else None
    # `is not None`, NO truthiness: con `--shorts-stems ""` —que es lo que produce
    # `",".join(stems)` cuando la corrida no generó ningún short— la cadena vacía
    # es falsy y el acotamiento se desactivaba EN SILENCIO, auditando el
    # directorio entero como si nadie lo hubiera pedido.
    solo_shorts = (
        {s.strip() for s in args.shorts_stems.split(",") if s.strip()}
        if args.shorts_stems is not None else None
    )

    fallos = []

    # [GATE-02] ida 1: `--stem` que no casa con NINGÚN vídeo de `--output` se
    # tragaba en silencio (el `continue` del bucle no deja rastro) y el gate
    # podía terminar en verde sin haber auditado ni un solo vídeo de los
    # pedidos. Se calcula ANTES del bucle, sobre el glob completo, para no
    # depender de qué stems sobrevivan al filtro.
    videos_disponibles = sorted(glob.glob(os.path.join(args.output, "*_final.mp4")))
    stems_disponibles = {os.path.basename(v)[: -len("_final.mp4")] for v in videos_disponibles}
    if solo:
        faltantes = solo - stems_disponibles
        if faltantes:
            msg = (f"--stem pidió auditar {', '.join(sorted(faltantes))} pero no "
                  f"existe(n) en {args.output}: no hay .mp4 que auditar para "
                  f"ese/os stem(s), no se sabe si son publicables")
            print(f"{MAL} {msg}")
            fallos.append(msg)

    n_video_procesados = 0
    for video in videos_disponibles:
        stem = os.path.basename(video)[: -len("_final.mp4")]
        if solo and stem not in solo:
            continue
        n_video_procesados += 1
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
        # [GATE-02] ida 2: `audita_video` corría SIN try/except. Un vídeo que
        # petaba (fichero corrupto, excepción de instrumento, lo que sea) se
        # llevaba por delante TODOS los vídeos siguientes del bucle Y la
        # auditoría de shorts entera (estaba fuera del bucle, después). Cada
        # vídeo se aísla: si peta, ese vídeo queda NO PUBLICABLE con el motivo
        # y el bucle sigue con los demás.
        try:
            f_video = audita_video(video, ass, story, args.chunk_dur, args.model)
            escribe_veredicto(video, f_video)
            fallos += f_video
        except Exception as e:
            traceback.print_exc()
            msg = (f"excepción auditando {stem}: {type(e).__name__}: {e}")
            print(f"{MAL} {msg}")
            escribe_veredicto(video, [msg])
            fallos.append(msg)

    # SIEMPRE corre, aunque algún vídeo largo haya petado arriba: antes vivía
    # fuera del bucle sin protección, así que una excepción en un solo vídeo
    # se llevaba por delante la auditoría ENTERA de shorts.
    try:
        fallos += audita_shorts(args.shorts_dir, args.temp, args.shorts, args.model,
                                stems=solo_shorts)
    except Exception as e:
        traceback.print_exc()
        msg = f"excepción auditando shorts en {args.shorts_dir}: {type(e).__name__}: {e}"
        print(f"{MAL} {msg}")
        fallos.append(msg)

    # [GATE-02] ida 3: conjunto vacío. Sin ningún vídeo ni ningún short en los
    # directorios (el caso por defecto de un `--output`/`--shorts-dir` recién
    # creados, o de una corrida que no ha producido nada todavía) el bucle no
    # itera nunca, `audita_shorts` imprime "0 mp4 y 0 títulos" y `fallos`
    # seguía vacío: EXIT=0, "sin defectos MEDIBLES" — la nota perfecta de no
    # haber medido NADA. Solo se dispara sin `--stem`: con `--stem` puesto, un
    # 0 ya generó su propio fallo explícito arriba (la ida 1), y no hace falta
    # duplicar el mensaje.
    n_mp4_shorts = len(glob.glob(os.path.join(args.shorts_dir, "*.mp4")))
    if solo is None and n_video_procesados == 0 and n_mp4_shorts == 0:
        msg = (f"no se ha auditado NADA: 0 vídeos en {args.output} y 0 shorts en "
              f"{args.shorts_dir} — un conjunto vacío no es una salida sana, es "
              f"una salida sin medir")
        print(f"{MAL} {msg}")
        fallos.append(msg)

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
