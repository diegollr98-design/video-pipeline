import difflib
import json
import logging
import os
import re
import time

import requests

logger = logging.getLogger(__name__)

WORDS_PER_BLOCK = 2000  # Each API call generates ~2000 words reliably

# --- Garantía de desenlace [CIERRE-01] ---------------------------------------
# La historia se quedaba sin final por DOS caminos distintos, los dos medidos:
#   (a) el bucle de `generate_story` sale por su condición de cabecera, así que
#       un bloque de "continuación" que cruce el 85% del objetivo lo termina sin
#       que se haya pedido NUNCA el desenlace. Pasó en 1 de las 3 corridas
#       largas del log (11-ago: 5334 palabras acabando a mitad de escena).
#   (b) `_truncate_to_words` se quedaba con las PRIMERAS max_words palabras, o
#       sea que tiraba el final. En la corrida del 10-ago descartó 1867 palabras
#       (26%), el epílogo entre ellas.
# Es §17 en estado puro: no había ningún `if` que forzara el cierre.
_CIERRE_PALABRAS = 500       # tamaño que se pide para el bloque de desenlace
_CIERRE_MIN_PALABRAS = 120   # por debajo de esto no es un desenlace, es un resto
# Un metadato de cola son decenas de palabras. Si el recorte se lleva más que
# esto de la historia YA CONCATENADA, no está quitando una anotación: está
# borrando narración (ver `_limpiar_bloque`).
_META_CORTE_MAX_FRAC = 0.15
# Tope POR BLOQUE (`_limpiar_bloque`). Va por fracción del bloque porque lo que
# distingue metadato de narración es la POSICIÓN del marcador: el corte llega
# hasta el final, así que uno en la cola se lleva poco y uno enterrado en el
# cuerpo se lleva casi todo. Calibrado contra el caso REAL de [BASURA-03]
# (`video_004`: 132 de 604 palabras = 22%), con margen.
_META_CORTE_MAX_FRAC_BLOQUE = 0.35
_CIERRE_PRESERVADO = 600     # palabras finales que el truncado NUNCA descarta


def _load_prompt_template(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _call_openrouter(messages, config, max_tokens=None):
    """Send messages to OpenRouter and return response text.

    Reintenta los fallos transitorios (honra `openrouter.max_retries`), incluido
    el caso de un 200 SIN 'choices': los modelos del tier gratuito devuelven a
    veces un 200 con un cuerpo de error, y sin este guardia reventaba con un
    KeyError('choices') a mitad de una historia de 8 bloques.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY") or config.get("openrouter", {}).get("api_key", "")
    if not api_key:
        raise RuntimeError(
            "Falta la API key de OpenRouter. Configúrala en .env:\n"
            "  OPENROUTER_API_KEY=sk-or-..."
        )

    or_config = config.get("openrouter", {})
    model = or_config.get("model", "nvidia/nemotron-3-ultra-550b-a55b:free")
    temperature = or_config.get("temperature", 0.9)
    max_retries = max(1, int(or_config.get("max_retries", 3)))

    payload = {"model": model, "messages": messages, "temperature": temperature}

    # Sin max_tokens, el proveedor aplica su propio tope y puede cortar la
    # respuesta a mitad. Con modelos de razonamiento es especialmente grave:
    # gastan el presupuesto pensando en voz alta y devuelven un fragmento.
    limit = max_tokens or or_config.get("max_tokens")
    if limit:
        payload["max_tokens"] = int(limit)

    last_error = None

    for attempt in range(max_retries):
        if attempt:
            delay = 5 * (2 ** (attempt - 1))
            logger.warning(f"OpenRouter: reintento {attempt + 1}/{max_retries} en {delay}s ({last_error})")
            time.sleep(delay)

        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=180,
            )
        except requests.RequestException as e:
            last_error = f"error de red: {e}"
            continue

        # 429 y 5xx son transitorios (los modelos free se saturan a menudo).
        if resp.status_code in (408, 429, 500, 502, 503, 520, 524):
            last_error = f"HTTP {resp.status_code}: {resp.text[:150]}"
            continue

        # Un 400 normalmente es culpa nuestra (petición mal formada) y
        # reintentarlo quema cuota para nada. PERO el proveedor envuelve en 400
        # fallos suyos que SÍ son transitorios. Medido el 12-ago en una corrida
        # real: `400 — "DEGRADED function cannot be invoked"` de Nvidia tumbó un
        # short. En un bloque de historia habría abortado un vídeo de 2 h.
        # Se reintenta SOLO con marcadores nombrados, no con cualquier 400.
        if resp.status_code == 400 and any(
                m in resp.text.lower() for m in
                ("degraded", "temporarily", "overloaded", "try again")):
            last_error = f"HTTP 400 transitorio del proveedor: {resp.text[:150]}"
            continue

        if resp.status_code != 200:
            raise RuntimeError(f"Error de OpenRouter: {resp.status_code} — {resp.text[:300]}")

        try:
            data = resp.json()
        except ValueError:
            last_error = f"respuesta no-JSON: {resp.text[:150]}"
            continue

        # OJO: `.get("content", "")` solo devuelve "" si la clave NO existe. Si
        # existe con valor null —que es lo que manda OpenRouter cuando el modelo
        # de razonamiento agota el presupuesto razonando y no llega a escribir la
        # respuesta— devuelve None, y `None.strip()` reventaba con un
        # AttributeError que NINGÚN `except` del bucle atrapa: subía hasta
        # main.py y mataba el vídeo entero con 1 sola petición gastada.
        # Medido: 200 OK, `content: null`, el texto en `reasoning` y
        # `finish_reason: "length"`. La línea llevaba así desde el commit inicial;
        # es el camino que nadie ejercía (§19).
        choices = data.get("choices") or []
        mensaje = (choices[0].get("message") if choices else None) or {}
        content = (mensaje.get("content") or "").strip()
        if content:
            return content

        # Ruidoso y distinguible (§13): "no escribió nada porque se le acabó el
        # presupuesto razonando" no es lo mismo que "devolvió un cuerpo de error".
        razonamiento = mensaje.get("reasoning") or ""
        fin = choices[0].get("finish_reason") if choices else None
        if razonamiento and fin == "length":
            last_error = (
                f"200 sin contenido: el modelo gastó el presupuesto razonando "
                f"({len(razonamiento)} chars de reasoning, finish_reason={fin}). "
                f"Un reintento idéntico tiene poca probabilidad de arreglarlo: si "
                f"esto se repite, sube `max_tokens` en esta llamada")
        else:
            last_error = (f"200 sin contenido (finish_reason={fin}): "
                          f"{json.dumps(data, ensure_ascii=False)[:200]}")

    raise RuntimeError(
        f"OpenRouter falló tras {max_retries} intentos con el modelo '{model}' — {last_error}"
    )


def _parse_title_and_speech(text):
    """Separa título (primera línea no vacía) del speech (resto)."""
    lines = text.strip().split("\n")
    title = ""
    speech_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped:
            title = stripped
            speech_start = i + 1
            break
    while speech_start < len(lines) and not lines[speech_start].strip():
        speech_start += 1
    speech = "\n".join(lines[speech_start:]).strip()
    return title, speech


# Marcadores de que el modelo soltó su razonamiento en vez de la historia.
# nvidia/nemotron-3-ultra es un modelo de razonamiento y lo hace de vez en
# cuando: en una corrida real, un short salió con el título "The user wants a
# viral micro-story script for YouTube Shorts/TikTok." y un vídeo de 4,5s.
#
# OJO: se buscan como SUBCADENA en cualquier parte del título, así que aquí solo
# pueden vivir marcadores que NO puedan aparecer en español narrativo normal.
# Medido sobre los 50 títulos completos de pipeline.log + casos de control:
# "vamos a" era español corrientísimo ("...Y Ahora Vamos A Juicio") y tiraba
# títulos legítimos. Un falso positivo cuesta una petición y un reintento.
_MARCADORES_RAZONAMIENTO = (
    "the user", "the assistant", "i need to", "i should", "let me", "we need",
    "okay,", "alright,", "first,", "sure,", "here's", "here is", "as an ai",
    "el usuario quiere", "necesito escribir", "voy a escribir", "```",
)

# Marcadores ambiguos: solo cuentan si el título EMPIEZA por ellos, que es la
# forma real en que se cuela la fuga ("Titulo: The user wants a viral micro-story
# script..."). Como subcadena tiraban títulos legítimos: "Mi Historia: Cómo Mi
# Hermana Me Robó El Negocio Familiar..." es del estilo del repo.
_MARCADORES_INICIO = (
    "título:", "titulo:", "historia:", "title:", "story:",
)

# Palabras funcionales españolas para confirmar que el título está en español.
_ES_FUNCIONALES = {
    "mi", "me", "mis", "la", "el", "los", "las", "de", "del", "que", "por",
    "para", "con", "un", "una", "y", "pero", "no", "se", "su", "al", "en",
    "cuando", "porque", "sin", "tras", "hasta", "desde", "lo",
}


# --- Guardia de puntuación narrativa [COMA-03] -------------------------------
# `prompts/reddit_story.txt` y `prompts/short_story.txt` YA piden "una coma cada
# 8-12 palabras" y "NUNCA pases de 30 palabras sin un punto". El modelo lo
# ignora: medido sobre las historias reales en disco (texto CRUDO, antes de
# `_ensure_breathing_commas`), la densidad de comas por 100 palabras es
#
#   BUENA (10-ago, publicable):      8.47/100 en el total; por bloque de 2000
#                                     palabras: 9.95 / 7.20 / 8.14
#   MALA  (11-ago):                  0.19/100 en el total; por bloque: 0.30 /
#                                     0.20 / 0.00
#   MALA  (12-ago, hoy):              0.02/100 en el total; por bloque: 0.00 /
#                                     0.05 / 0.00
#
# Separación limpia con margen grande en ambos lados (mínimo BUENA 7.20 vs
# máximo MALA 0.30). Se verificó que el umbral también aguanta el régimen de
# los SHORTS (~150-280 palabras, una sola llamada): con ventanas deslizantes de
# 150-200 palabras sobre los mismos tres textos, TODAS las ventanas BUENA caen
# en >=3.0/100 y TODAS las ventanas MALA en <=2.0/100 — cero falsos en ambos
# sentidos. Por debajo de 150 palabras la señal es ruido (con ventanas de 80
# palabras aparecen falsos positivos y negativos: una sola coma de más o de
# menos mueve la densidad 1,25 puntos), así que el guardia NO se aplica a
# textos más cortos que eso (ni pena ni gloria: no hay evidencia para juzgar).
#
# El umbral se fija en el punto que separa con margen simétrico ambos regímenes:
_PUNTUACION_MIN_COMAS_100 = 2.5
_PUNTUACION_MIN_PALABRAS = 150

# ⚠️ REVISADO 12-ago-2026: la densidad de comas de arriba SEPARA las corridas
# observadas, pero NO predice el defecto, y este guardia medía el artefacto
# equivocado. Las dos cosas, medidas:
#
#   (a) Artefacto equivocado. Juzgaba el guion CRUDO, y el pipeline lo reescribe
#       después (`_clean_speech_for_tts` -> `_ensure_breathing_commas`). Crudo
#       0,02 y 0,19 comas/100 -> NARRADO 3,11 y 2,74, o sea que las dos corridas
#       "malas" ya PASABAN el umbral en la forma que de verdad se oye.
#   (b) No predice. Con 10x más comas crudas (11-ago vs 12-ago) las pausas
#       inventadas medidas acústicamente fueron 102 vs 86: indistinguible.
#
# Y desde que `_ensure_breathing_periods` parte las frases, la aritmética se
# invierte: los puntos sustituyen comas, la densidad narrada cae a 0,84-1,24/100
# y el umbral de 2,5 dispararía en TODAS las generaciones — ~12 peticiones por
# vídeo del tope diario para no arreglar nada.
#
# Métrica nueva, ligada al MECANISMO: edge-tts respira cada ~5,9 s como mucho
# (tramo de habla continua más largo medido en las dos producciones) ≈ 20-23
# palabras. Si el texto no le da un signo dentro de esa ventana, se lo inventa.
# Se mide el p90 de palabras entre signos SOBRE EL TEXTO NARRADO:
#
#   texto                          p90   max
#   video_001 sin partidor          34    85
#   video_002 sin partidor          31    78
#   video_001 CON partidor          26    69
#   video_002 CON partidor          26    69
#
# Umbral 30: pasa lo que el código ya sabe arreglar y caza el texto que ni
# partiendo frases se deja puntuar (sin conectores donde cortar). Es un backstop
# del código, no un sustituto: la garantía la da el partidor (§17), y quien corta
# de verdad es la medición ACÚSTICA del auditor.
_PUNTUACION_P90_MAX = 30

# Prefijo del motivo, para que quien reintenta pueda distinguir "esto SOLO
# falló por falta de comas" de cualquier otro motivo de rechazo (razonamiento
# filtrado, basura, título vacío...) sin volver a parsear el texto.
_MOTIVO_PUNTUACION_PREFIJO = "puntuacion insuficiente"


def _densidad_comas(texto):
    """Comas por 100 palabras. Se pega a la palabra anterior, así que contar
    ',' es equivalente a contar comas de verdad (no hay comas sueltas)."""
    palabras = texto.split()
    if not palabras:
        return 0.0
    return texto.count(",") / len(palabras) * 100


def _palabras_entre_signos(texto):
    """Longitud de cada tramo de palabras sin ningún signo de puntuación."""
    tramos, n = [], 0
    for palabra in texto.split():
        n += 1
        if palabra.rstrip().endswith((".", ",", ";", ":", "!", "?")):
            tramos.append(n)
            n = 0
    if n:
        tramos.append(n)
    return tramos


def _validar_puntuacion(texto, umbral=_PUNTUACION_P90_MAX,
                         min_palabras=_PUNTUACION_MIN_PALABRAS):
    """¿Podrá narrarse esto sin que edge-tts se invente dónde respirar?

    Se mide sobre el TEXTO NARRADO (el que sale de `_clean_speech_for_tts`), no
    sobre el crudo: el pipeline le mete puntos y comas después, así que juzgar el
    crudo es juzgar un borrador que nadie oye. Ver la calibración completa junto
    a las constantes arriba.
    """
    palabras = texto.split()
    if len(palabras) < min_palabras:
        return True, ""  # sin suficiente texto para que la medida signifique algo
    try:
        from modules.tts_engine import _clean_speech_for_tts
        narrado = _clean_speech_for_tts(texto)
    except Exception:
        # Si no se puede reconstruir lo que se oirá, no se inventa un veredicto:
        # este guardia se abstiene y deja que corte el auditor, que mide el audio.
        return True, ""
    tramos = sorted(_palabras_entre_signos(narrado))
    if not tramos:
        return True, ""
    p90 = tramos[int(len(tramos) * 0.9)]
    if p90 > umbral:
        return False, (
            f"{_MOTIVO_PUNTUACION_PREFIJO}: p90 de {p90} palabras entre signos "
            f"(máximo {umbral}) sobre el texto narrado; edge-tts respira cada "
            f"~20 palabras y si no hay signo se inventa la pausa (§17 — ya falló "
            f"pidiéndolo solo en el prompt)"
        )
    return True, ""


def _es_fallo_solo_puntuacion(motivo):
    """¿El único motivo de rechazo fue la falta de comas?

    Se usa para decidir si, al agotar los reintentos, se acepta el mejor
    intento en vez de abortar la corrida entera: la basura del modelo o un
    título vacío son motivo de aborto (siempre lo fueron); la falta de comas
    empeora la narración pero no la hace impublicable, así que no vale tirar
    45 minutos de trabajo por ella.
    """
    return bool(motivo) and motivo.startswith(_MOTIVO_PUNTUACION_PREFIJO)


def _validar_salida(title, speech, min_palabras_titulo, min_palabras_speech,
                    exigir_puntuacion=True):
    """¿Esta generación es utilizable? Devuelve (bool, motivo).

    Sin esto, el razonamiento del modelo acababa como título en la miniatura y
    en la intro, y el speech quedaba en cuatro líneas.
    """
    if not title or not speech:
        return False, "título o speech vacíos"

    palabras_titulo = title.split()
    if not (min_palabras_titulo <= len(palabras_titulo) <= 45):
        return False, f"título de {len(palabras_titulo)} palabras (esperado {min_palabras_titulo}-45)"

    bajo = title.lower()
    for marcador in _MARCADORES_RAZONAMIENTO:
        if marcador in bajo:
            return False, f"el título contiene razonamiento del modelo ('{marcador}')"

    for marcador in _MARCADORES_INICIO:
        if bajo.lstrip().startswith(marcador):
            return False, f"el título empieza por un encabezado del modelo ('{marcador}')"

    # El título tiene que parecer español, no inglés.
    tokens = re.findall(r"[a-záéíóúüñ]+", bajo)
    aciertos = sum(1 for t in tokens if t in _ES_FUNCIONALES)
    if aciertos < 2 and not re.search(r"[áéíóúñü]", bajo):
        return False, "el título no parece español"

    if len(speech.split()) < min_palabras_speech:
        return False, f"speech de {len(speech.split())} palabras (mínimo {min_palabras_speech})"

    # El CUERPO, no solo la cabecera: la basura del modelo se entierra a mitad.
    hay_basura, motivo = _detectar_basura(speech)
    if hay_basura:
        return False, f"basura en el cuerpo del speech: {motivo}"

    # Última: si todo lo anterior pasó, un rechazo aquí es SOLO por puntuación
    # (lo que usa `_es_fallo_solo_puntuacion` para decidir si aceptar el mejor
    # intento en vez de abortar la corrida entera).
    if exigir_puntuacion:
        ok_punt, motivo_punt = _validar_puntuacion(speech)
        if not ok_punt:
            return False, motivo_punt

    return True, ""


# Palabras funcionales inglesas. En narración española no aparecen; en una
# ráfaga degenerada del modelo salen a puñados.
_STOPWORDS_EN = frozenset((
    "the", "and", "that", "with", "this", "was", "were", "they", "their",
    "from", "which", "would", "about", "there", "have", "has", "been", "will",
    "what", "when", "your", "you", "need", "writing", "user", "assistant",
))

# Caracteres que no pinta nada ver en una historia en español.
_RE_CHAR_EXTRANO = re.compile(r"[^\w\s.,;:!?¡¿\"'«»()\[\]\-–—…%€$/&+*=@#\n]", re.UNICODE)


# El modelo se ANOTA A SÍ MISMO al final de la historia. Caso real cazado por
# `/eval` el 12-ago-2026: el guion terminaba en
#
#     "...que pienso defender hasta el final.PALABRAS: 1558"
#
# y eso se NARRÓ y se SUBTITULÓ — el último cue del `.ass` del fixture era
# literalmente `1558.`. `_detectar_basura` no puede verlo: exige una RÁFAGA de
# >=3 tokens anómalos distintos en 60 palabras, y esto son dos tokens, uno de
# ellos un número limpio. Es la clase [BASURA-01] otra vez pero por la COLA, no
# por la cabecera ni por el cuerpo: cada vez que se ha tapado un sitio, el
# modelo ha aparecido por el siguiente (§17, 2.º corolario).
_RE_META_FINAL = re.compile(
    r"(?:^|[\s.,;:!?])(?:"
    r"palabras\s*[:=]\s*\d+"
    r"|n[úu]mero\s+de\s+palabras\s*[:=]?\s*\d+"
    r"|total\s*[:=]?\s*\d+\s*palabras?"
    r"|word\s*count\s*[:=]?\s*\d+"
    r"|words?\s*[:=]\s*\d+"
    r"|\(\s*\d+\s*palabras?\s*\)"
    r"|\[?\s*fin\s+de\s+la\s+historia\s*\]?"
    r")\s*[.\]\)]*\s*$",
    re.IGNORECASE,
)

# [BASURA-03] — el modelo se auto-audita en un BLOQUE de markdown, no en una
# línea suelta. Caso real (video_004, `data/evidence/video_004_story.txt`):
#
#     "...se fortalece.**Cuenta final de palabras: ~1,598 palabras**
#     (Perfecto, objetivo alcanzado).
#
#     **Resumen de los elementos solicitados incluidos:**
#     1.  **Plan y ejecución:** ...
#     2.  **Consecuencias:** ...
#     3.  **Epílogo/Cierre:** ..."
#
# 55,8 de 208 s (27% del vídeo) salieron narrados y subtitulados
# (`data/evidence/video_004_subs.ass`, cue 449 en adelante: "RESUMEN / DE /
# LOS / ELEMENTOS / SOLICITADOS / INCLUIDOS: / 1. / PLAN..." hasta el último
# cue). `_RE_META_FINAL` no lo caza: exige que el patrón llegue hasta `$` y
# aquí, detrás del primer marcador, hay TRES párrafos más. `_detectar_basura`
# tampoco: exige una RÁFAGA de >=3 anomalías léxicas (mezcla letra/dígito,
# inglés, carácter raro) en 60 palabras, y este texto es español CORRECTO —
# solo que habla DE la historia en vez de CONTARLA. Medido: `_detectar_basura`
# sobre el texto completo devuelve `(False, '')`.
#
# Dos firmas, ninguna basada en vocabulario NARRATIVO (para no comerse una
# historia real que hable de "un resumen" o "el plan de boda"):
#   (a) una CABECERA en negrita/almohadilla que nombra el propio texto que la
#       precede ("**Resumen...**", "**Cuenta final de palabras...**"), y
#   (b) una LISTA numerada/con viñetas con sub-cabeceras en negrita
#       ("1.  **Plan y ejecución:** ..."), que el prompt prohíbe expresamente
#       en narración fluida ("NO fragmentes en líneas cortas... narración
#       continua").
# El marcador real venía PEGADO al punto final de la última frase narrativa,
# SIN salto de párrafo ("...se fortalece.**Cuenta final..."), así que partir
# por párrafos no sirve: se busca el marcador en cualquier posición del texto
# y se corta en el ÚLTIMO fin de frase ANTES de él (`_detectar_meta_cola`).
# OJO: la keyword no puede exigir el ':' PEGADO — "Resumen de los elementos
# solicitados incluidos:" mete 4 palabras entre la keyword y el ':' que la
# cierra, y una primera versión de este regex exigía `keyword\s*[:\*]`
# (colon inmediato) y la dejaba pasar en blanco: solo cazaba el caso real
# porque "**Cuenta final de palabras:**" aparecía ANTES en el mismo bloque.
# Ahora se permite relleno (sin salto de línea ni '*', tope 60 caracteres —
# una etiqueta de encabezado no es más larga que eso) entre la keyword y el
# ':' de cierre, en cualquiera de las dos formas medidas ("...palabras:**" o
# "...palabras**:").
_RE_META_HEADER = re.compile(
    r"[#*]{1,2}\s*(?:"
    r"resumen"
    r"|elementos\s+solicitados"
    r"|notas?\s+finales?"
    r"|checklist"
    r"|estructura\s+de\s+la\s+(?:historia|respuesta)"
    r"|cuenta\s+final"
    r"|conteo\s+(?:final\s+)?de\s+palabras"
    r"|recuento\s+(?:final\s+)?de\s+palabras"
    r")[^\n*]{0,60}?:\**",
    re.IGNORECASE,
)

# El caso real ("1.  **Plan y ejecución:** Llamada al abogado...") lleva el
# ':' DENTRO de la negrita, antes del '**' de cierre — no detrás. Se aceptan
# las dos formas ("**Label:**" y "**Label**:") para no depender de en qué
# lado ponga el modelo el símbolo.
_RE_META_LISTA = re.compile(
    r"(?:^|\n)[ \t]*(?:\d+[.\)]|[-*•])[ \t]+\*\*[^\n*]{2,60}?(?::\*\*|\*\*:)",
)


def _detectar_meta_cola(texto):
    """¿Hay un bloque de auto-anotación del modelo en la COLA del texto?

    Devuelve `(bool, motivo, posición)`. Se usa desde `_strip_trailing_metadata`
    (para cortarlo durante la generación) y desde `scripts/audit_run.py` (para
    comprobar que ninguno sobrevivió en el guion YA PUBLICADO — la generación
    puede fallar en cortarlo por una forma nueva que el regex no prevea, y el
    auditor es la última red antes de que Diego lo mire).
    """
    posiciones = [m.start() for m in _RE_META_HEADER.finditer(texto)]
    posiciones += [m.start() for m in _RE_META_LISTA.finditer(texto)]
    if not posiciones:
        return False, "", -1
    primero = min(posiciones)
    fragmento = texto[primero:primero + 100].replace("\n", " ").strip()
    return True, f"auto-anotación del modelo en la cola: «{fragmento}...»", primero


def _strip_trailing_metadata(texto):
    """Quita la auto-anotación del modelo en la COLA del guion.

    Dos formas medidas, las dos SOLO en la cola:
    (a) una anotación corta pegada al final ("...PALABRAS: 1558") — la caza
        `_RE_META_FINAL`, anclada al final de la cadena.
    (b) un BLOQUE de auto-análisis en markdown, de varios párrafos
        ("**Cuenta final...** ... **Resumen...:** 1. **Plan...** ...") — lo
        caza `_detectar_meta_cola` en cualquier posición, y se corta en el
        ÚLTIMO fin de frase ANTES de su primer marcador (puede venir PEGADO
        sin separador de párrafo: ver comentario junto a los regex).

    Devuelve `(texto_limpio, quitado)`. Si (b) encuentra el marcador pero NO
    hay ningún fin de frase limpio por delante, se ABSTIENE de cortar esa
    parte (podría estar comiéndose narración real) y deja que otros guardias
    (`_detectar_basura`, el auditor) decidan.
    """
    quitado_piezas = []

    hay_meta, _, primero = _detectar_meta_cola(texto)
    if hay_meta:
        prefijo = texto[:primero]
        corte = 0
        for mm in re.finditer(r"[.!?]+(?=\s|$|[*#\n])", prefijo):
            corte = mm.end()
        if corte:
            quitado_piezas.append(texto[corte:].strip())
            texto = texto[:corte].rstrip()

    for _ in range(3):  # puede venir apilado: "FIN DE LA HISTORIA. PALABRAS: 1558"
        m = _RE_META_FINAL.search(texto)
        if not m:
            break
        quitado_piezas.append(texto[m.start():].strip())
        texto = texto[:m.start()].rstrip()

    quitado = " ".join(p for p in quitado_piezas if p).strip()
    return texto, quitado


def _detectar_basura(texto, ventana=60, umbral=3):
    """¿Hay una RÁFAGA de texto degenerado en el cuerpo? Devuelve (bool, motivo).

    Caso real medido (vídeo de producción, 10-ago-2026): a mitad de una historia
    de 5290 palabras el modelo escupió

        "de onean need that the writing plan2:en300 five the 02 0230 the0222
         0207- 01=، the 02201 the"

    y eso se NARRÓ y se SUBTITULÓ: sale en pantalla en el minuto 15:38-15:47 de
    un vídeo publicable. Los guardias anteriores (`_validar_salida`,
    `_validar_continuacion`) solo miran la CABECERA de la salida, porque el modo
    de fallo conocido era el razonamiento al principio. Este no está al
    principio: está enterrado a mitad del cuerpo, donde nadie mira.

    Se cuenta por VENTANA deslizante, no en total: una ráfaga concentrada es la
    firma, mientras que un "COVID-19" suelto en 5000 palabras no lo es.
    """
    palabras = texto.split()
    if len(palabras) < 10:
        return False, ""

    anomalias = [0] * len(palabras)
    detalle = {}
    for i, bruto in enumerate(palabras):
        limpia = bruto.strip(".,;:!?¡¿\"'«»()[]—–-").lower()
        if not limpia:
            continue
        tiene_letra = any(c.isalpha() for c in limpia)
        tiene_digito = any(c.isdigit() for c in limpia)
        if tiene_letra and tiene_digito:
            anomalias[i] = 1
            detalle[i] = f"mezcla letra/dígito ({bruto!r})"
        elif limpia in _STOPWORDS_EN:
            anomalias[i] = 1
            detalle[i] = f"palabra inglesa ({bruto!r})"
        elif _RE_CHAR_EXTRANO.search(limpia):
            anomalias[i] = 1
            detalle[i] = f"carácter fuera del español ({bruto!r})"

    # Ventana deslizante contando tokens DISTINTOS: la basura trae anomalías
    # variadas ('need', 'that', 'plan2:en300', 'the0222'…), mientras que un
    # nombre propio raro repetido ('iPhone13' tres veces) es un solo token y no
    # debe disparar.
    posiciones = [i for i, a in enumerate(anomalias) if a]
    for k, ini in enumerate(posiciones):
        distintos = {
            palabras[j].strip(".,;:!?¡¿\"'«»()[]—–-").lower()
            for j in posiciones[k:] if j < ini + ventana
        }
        if len(distintos) >= umbral:
            muestras = [detalle[j] for j in posiciones[k:k + 3]]
            fragmento = " ".join(palabras[ini:ini + 16])
            return True, (f"ráfaga de {len(distintos)} anomalías distintas en {ventana} "
                          f"palabras (palabra ~{ini}): {'; '.join(muestras)} | «{fragmento[:150]}»")

    return False, ""


def _validar_continuacion(texto, min_palabras=200):
    """¿Este bloque de continuación es narración utilizable? Devuelve (bool, motivo).

    Una continuación no trae título, así que no vale _validar_salida. El modo de
    fallo real medido es el mismo: nemotron razona en voz alta, agota el
    presupuesto y devuelve un fragmento sin formato (448 caracteres, ~70
    palabras). Se mira solo la CABECERA del bloque para los marcadores: es donde
    aparece la fuga, y buscarlos en 2000 palabras de narración da falsos
    positivos.
    """
    if not texto or not texto.strip():
        return False, "continuación vacía"

    palabras = texto.split()
    if len(palabras) < min_palabras:
        return False, f"continuación de {len(palabras)} palabras (mínimo {min_palabras})"

    cabecera = texto.strip()[:300].lower()
    for marcador in _MARCADORES_RAZONAMIENTO:
        if marcador in cabecera:
            return False, f"la continuación empieza con razonamiento del modelo ('{marcador}')"
    for marcador in _MARCADORES_INICIO:
        if cabecera.lstrip().startswith(marcador):
            return False, f"la continuación empieza por un encabezado del modelo ('{marcador}')"

    # Tiene que parecer español, no un volcado de razonamiento en inglés.
    tokens = re.findall(r"[a-záéíóúüñ]+", cabecera)
    aciertos = sum(1 for t in tokens if t in _ES_FUNCIONALES)
    if aciertos < 2 and not re.search(r"[áéíóúñü]", cabecera):
        return False, "la continuación no parece español"

    # El CUERPO entero, no solo los 300 primeros caracteres.
    hay_basura, motivo = _detectar_basura(texto)
    if hay_basura:
        return False, f"basura en el cuerpo de la continuación: {motivo}"

    # Última: si todo lo anterior pasó, un rechazo aquí es SOLO por puntuación.
    ok_punt, motivo_punt = _validar_puntuacion(texto)
    if not ok_punt:
        return False, motivo_punt

    return True, ""


def _normalize_for_compare(text):
    """Normalize text for comparison: lowercase, strip punctuation."""
    import re
    return re.sub(r'[^a-záéíóúüñ\s]', '', text.lower()).strip()


# Eco del título parafraseado [TITULO-01]. El match por PREFIJO de
# `_ensure_title_at_start` rompe en la primera palabra distinta, así que una
# paráfrasis del modelo ("Mi padrino DE BAUTISMO vendió…") deja pegada la cola
# del título, que se NARRA y se SUBTITULA justo después de decir el título.
_ECO_MAX_CHARS = 220      # hasta dónde se busca el final del fragmento inicial
_ECO_UMBRAL = 0.60        # fracción de sus palabras que deben venir del título
# Un eco tiene que ser un TROZO RECONOCIBLE del título, no una coincidencia.
# Sin estos dos mínimos, con un título de 26 palabras cualquier frase corta llega
# al 60% de solape por puro azar y se BORRA una primera frase legítima: medido,
# "La casa familiar seguía vacía." y "El juez lo perdió todo." desaparecían
# enteras. Es el falso positivo que introdujo el fix de [TITULO-01].
_ECO_MIN_COMUNES = 4      # palabras en común mínimas
_ECO_MIN_DEL_TITULO = 0.25  # y que cubran al menos este trozo del título

# Palabras del título que deben coincidir al inicio para considerarlo un título
# PARCIAL que hay que quitar. Con el umbral en 1 se comía cualquier coincidencia:
# "Mi hermano lloró." contra el título "Mi Hermano Manipuló…" perdía el sujeto y
# se narraba "<título>. lloró." en el segundo 1. Duplicar 3 palabras es feo;
# mutilar la primera frase es un defecto que va a la intro y a la miniatura.
_PREFIJO_MIN_PALABRAS = 4


# Solo espacios. A propósito NO se salta la puntuación de apertura (`¿ ¡ « " ( —`):
# un fragmento descabezado real empieza con la palabra pelada ("una madrugada…",
# "mientras yo estaba…"), mientras que `¿que hago ahora?` o `«callate», dijo.` son
# narración legítima donde el modelo solo se dejó la mayúscula. Saltarse esos
# signos hacía que la guarda se comiera una pregunta retórica y un diálogo
# enteros (medido); borrar narración es el lado caro del error (§16).
_APERTURA_CHARS = " \t\n\r"
# Hasta dónde se busca el final del fragmento mutilado. Más generoso que
# `_ECO_MAX_CHARS` porque aquí NO se compara con el título: se busca dónde
# acaba la frase que quedó descabezada, y medida real: 24 palabras (~140
# caracteres) en `short_008`.
_FRAGMENTO_MAX_CHARS = 400
# Tope duro en PALABRAS de lo que se puede descartar. Los fragmentos reales
# medidos son de 11 y 24; por encima de esto ya no es la cola del título, es
# narración nueva, y borrarla cuesta más que dejar una frase coja.
_FRAGMENTO_MAX_PALABRAS = 28


def _descartar_fragmento_inicial(story):
    """Si al quitar el prefijo del título queda la COLA de una frase, se descarta.

    [TITULO-03] `_ensure_title_at_start` borra el solapamiento literal del título
    sin comprobar que lo que queda detrás **empiece una frase**. Cuando el modelo
    escribe UNA sola frase que arranca como el título y sigue, quitarle la cabeza
    deja un fragmento subordinado sin sujeto ni verbo principal, que se narra y se
    subtitula justo después del título — en el segundo 3.

    Medido en la corrida del 14-ago: 2 de los 4 shorts. `short_006` →
    *"…Le Obligó A Reconstruirlo Entero. una madrugada para ampliar su piscina…"*;
    `short_008` → *"…Y El Comprador Lo Rastreó. mientras yo estaba en urgencias…"*.
    El guardia de eco (`_es_eco_del_titulo`) no los caza porque no son ecos puros:
    3/11 y 6/24 palabras en común, contra el umbral de 0,60.

    La señal es determinista y no necesita al modelo (§18): en español, detrás de
    un punto va mayúscula. Si va minúscula, la frase está descabezada.

    Se descarta el fragmento entero en vez de intentar repararlo: sus palabras son
    justo las que el título ya dice. Y NO se toca nada si no hay una frase completa
    detrás, o si borrarlo dejaría el speech vacío — perder narración es peor.
    """
    limpio = story.lstrip(_APERTURA_CHARS)
    if not limpio:
        return story

    # Minúscula O dígito. `isalpha()` es False para una cifra, así que
    # "400 euros al mes sin decírmelo, lo descubrí..." —una apertura
    # perfectamente normal del género, y descabezada igual— no disparaba.
    primera = limpio[0]
    if not ((primera.isalpha() and primera.islower()) or primera.isdigit()):
        return story

    corte = _fin_de_frase(limpio, limite=_FRAGMENTO_MAX_CHARS)
    if not corte:
        logger.warning(
            "Tras quitar el prefijo del titulo el speech empieza en minuscula "
            "(frase descabezada) pero NO se encuentra el final de esa frase: se "
            "deja intacto para no borrar narracion."
        )
        return story

    frag = limpio[:corte].strip()
    resto = limpio[corte:].strip()

    # TOPE DE PALABRAS. El solapamiento que se quitó antes es un match por
    # PREFIJO que rompe en la primera palabra distinta, así que en cuanto la
    # frase del modelo diverge del título lo que queda detrás YA NO son "las
    # palabras que el título dice": es narración nueva. Sin tope, esto llegó a
    # borrar el 41% del cuerpo de un short (163 -> 96 palabras), por encima del
    # mínimo de 80, así que el short se publicaba igual.
    # Los fragmentos reales medidos son de 11 y 24 palabras; el techo anterior
    # (`_FRAGMENTO_MAX_CHARS = 400` ~ 66 palabras) estaba a 2,7x de eso.
    if len(frag.split()) > _FRAGMENTO_MAX_PALABRAS:
        logger.warning(
            f"Fragmento descabezado de {len(frag.split())} palabras (máximo "
            f"{_FRAGMENTO_MAX_PALABRAS}): demasiado largo para ser la cola del "
            f"título, se deja intacto en vez de borrar narración. Empieza: "
            f"{frag[:70]!r}"
        )
        return story

    if not resto:
        logger.warning(
            f"Tras quitar el prefijo del titulo quedaria solo un fragmento "
            f"descabezado ({len(frag.split())} palabras) y nada detras: se deja "
            f"intacto en vez de vaciar el speech."
        )
        return story

    logger.warning(
        f"Descartado fragmento descabezado al inicio del speech "
        f"({len(frag.split())} palabras): {frag[:80]!r}. Era la cola de la frase "
        f"cuyo comienzo repetia el titulo."
    )
    return resto


def _fin_de_frase(texto, limite=_ECO_MAX_CHARS):
    """Posición tras el primer final de frase dentro de `limite` caracteres."""
    for m in re.finditer(r"[.!?]+(?=\s|$)", texto[:limite]):
        return m.end()
    return 0


def _es_eco_del_titulo(fragmento, titulo_palabras, umbral=_ECO_UMBRAL):
    """¿El fragmento inicial es un trozo del título, aunque esté parafraseado?

    Por solape de TOKENS, no por subcadena literal: la comprobación anterior
    exigía que el fragmento fuese subcadena del resto del título, y una sola
    letra la rompía — el caso real fue el título "…Vació Mi Carteras Fría…"
    seguido de "cartera fría, y desapareció con mis bitcoins" (singular contra
    plural), que se coló entero en el short.
    """
    frag = _normalize_for_compare(fragmento).split()
    if not frag or not titulo_palabras:
        return False
    # Un fragmento mucho más largo que el título es historia, no eco.
    if len(frag) > len(titulo_palabras) + 4:
        return False
    sm = difflib.SequenceMatcher(None, frag, titulo_palabras, autojunk=False)
    comunes = sum(b.size for b in sm.get_matching_blocks())
    if comunes < _ECO_MIN_COMUNES:
        return False
    if comunes / len(titulo_palabras) < _ECO_MIN_DEL_TITULO:
        return False
    return comunes / len(frag) >= umbral


def _ensure_title_at_start(title, story):
    """Ensure the speech starts with the full title as its first sentence.

    If the LLM didn't include the full title:
    1. Remove any partial overlap at the start of the speech
    2. Prepend the full title
    """
    # Clean title
    title_clean = title.rstrip('.').rstrip()
    while title_clean.endswith('.'):
        title_clean = title_clean[:-1].rstrip()
    title_sentence = title_clean + "."

    title_norm = _normalize_for_compare(title_clean)
    title_words = title_norm.split()

    # Check if speech already starts with the FULL title
    story_start = " ".join(story.split()[:len(title_words) + 3])
    story_start_norm = _normalize_for_compare(story_start)

    if title_norm in story_start_norm:
        logger.info("Speech ya empieza con el titulo completo")
        return story

    # Remove any partial overlap of the title at the start of the speech
    # Find how many words of the title match the start of the story
    story_words = story.split()
    story_norm_words = _normalize_for_compare(" ".join(story_words[:len(title_words)])).split()

    overlap = 0
    for i in range(min(len(title_words), len(story_norm_words))):
        if title_words[i] == story_norm_words[i]:
            overlap = i + 1
        else:
            break

    if overlap >= _PREFIJO_MIN_PALABRAS:
        # Remove the overlapping partial title from the story start
        story = " ".join(story_words[overlap:])
        logger.info(f"Eliminado solapamiento de {overlap} palabras del inicio")
        # Quitar la cabeza puede dejar la COLA de la frase del modelo, que se
        # narra descabezada en el segundo 3 [TITULO-03]. Solo aquí: si no se
        # cortó prefijo, el speech empieza donde el modelo lo escribió.
        story = _descartar_fragmento_inicial(story)
    elif overlap:
        # Coincidencia corta ("Mi hermano…"), no un título parcial. Se deja: la
        # paráfrasis de verdad la caza el guardia de eco de abajo, que sí mide
        # cuánto del título hay dentro del fragmento.
        logger.info(f"Solapamiento de {overlap} palabra(s) NO eliminado: "
                    f"es coincidencia, no un titulo parcial")

    # Segunda pasada: la COLA del título, parafraseada. El prefijo de arriba solo
    # come mientras las palabras coincidan literalmente, así que "Mi padrino DE
    # BAUTISMO vendió…" rompe en la 2.ª palabra y deja el resto pegado. Se oye en
    # el segundo 1, que en un short vertical es el producto entero.
    # Medido: 2 de los 14 shorts de la última corrida, 7 de los 48 del corpus.
    corte = _fin_de_frase(story)
    if corte and _es_eco_del_titulo(story[:corte], title_words):
        eco = story[:corte].strip()
        story = story[corte:].strip()
        logger.info(f"Eliminado eco del titulo al inicio: {eco[:70]!r}")

    logger.info("Forzando titulo al inicio del speech")
    return title_sentence + " " + story.strip()


def _generate_first_block(target_words, style, config, cerrar_historia=False):
    """Generate title + first block: hook + context + start of escalation.

    `cerrar_historia=True` (usada cuando `target_words` cabe en un solo bloque,
    ver `_UN_SOLO_BLOQUE_MAX_PALABRAS`) pide la historia COMPLETA —con
    desenlace incluido— en esta misma llamada, en vez de "corta en un punto de
    tensión": el prompt de abajo es justo el contrario del que se usa cuando SÍ
    va a haber más bloques después.
    """
    template = _load_prompt_template(config["paths"]["prompt_template"])
    prompt = template.format(target_words=target_words, style=style)

    if cerrar_historia:
        # Historia completa en UNA sola llamada. Antes, todo objetivo pasaba
        # por aquí pidiendo un bloque de "gancho, no termines" de tamaño FIJO
        # (WORDS_PER_BLOCK=2000) sin importar `target_words`, y para un
        # objetivo pequeño (p.ej. 623) el sobrante lo tiraba
        # `_truncate_to_words` (medido: 48-84% del cuerpo descartado). Con
        # `target_words <= WORDS_PER_BLOCK` no hace falta partir en bloques.
        prompt += f"""

IMPORTANTE: Esta historia debe tener aproximadamente {target_words} palabras en TOTAL, y la vas a escribir COMPLETA en esta única respuesta: desde el gancho hasta el desenlace. NO habrá un mensaje siguiente.

REGLA CRÍTICA: La primera frase del speech DEBE SER exactamente el texto del título (sin los "..."). Es la frase que aparecerá en la miniatura y la intro del video. Ejemplo: si el título es "Mi Jefe Me Humilló En La Cena De Empresa...", el speech debe empezar: "Mi jefe me humilló en la cena de empresa." y luego continuar desarrollando la escena con detalle.

Incluye TODO en esta misma respuesta: el hook inicial (escena del título con detalle), el contexto del pasado, la escalada del abuso, el plan y su ejecución (confrontaciones, pruebas, acciones legales), las consecuencias para los abusadores (pierden dinero, reputación, relaciones), y un epílogo final (meses/años después, cómo está el protagonista ahora, reflexión final).

CIERRA la historia POR COMPLETO. NO la dejes abierta ni "a punto de continuar": es el ÚNICO bloque.
Escribe aproximadamente {target_words} palabras en total. El desenlace es tan importante como el resto: no lo sacrifiques por espacio.

RECORDATORIO: Escribe en párrafos largos y fluidos. NO fragmentes en líneas cortas. NO uses comillas ni guiones de diálogo. Integra todo en narración continua."""
    else:
        # Add instruction to generate first block
        prompt += f"""

IMPORTANTE: Esta historia debe tener {target_words} palabras en TOTAL, pero la vas a generar por partes.
Ahora genera SOLO el TÍTULO + las primeras ~{WORDS_PER_BLOCK} palabras.

REGLA CRÍTICA: La primera frase del speech DEBE SER exactamente el texto del título (sin los "..."). Es la frase que aparecerá en la miniatura y la intro del video. Ejemplo: si el título es "Mi Jefe Me Humilló En La Cena De Empresa...", el speech debe empezar: "Mi jefe me humilló en la cena de empresa." y luego continuar desarrollando la escena con detalle.

Incluye: el hook inicial (escena del título con mucho detalle), el contexto del pasado, y empieza las escaladas del abuso.
NO termines la historia. Corta en un punto de tensión. La historia CONTINUARÁ en el siguiente mensaje.
Escribe MÍNIMO {WORDS_PER_BLOCK} palabras en este bloque.

RECORDATORIO: Escribe en párrafos largos y fluidos. NO fragmentes en líneas cortas. NO uses comillas ni guiones de diálogo. Integra todo en narración continua."""

    intentos = max(1, int(config.get("openrouter", {}).get("max_retries", 3)))
    motivo = ""
    mejor_puntuacion = None  # (title, speech, dens): el mejor intento que SOLO fallaba por comas
    for intento in range(intentos):
        mensaje = prompt
        if intento:
            if _es_fallo_solo_puntuacion(motivo):
                mensaje = (
                    "TU RESPUESTA ANTERIOR NO SIRVIÓ: escribiste frases larguísimas sin "
                    "comas internas y edge-tts se inventará dónde respirar. Antes de cada "
                    "'y', 'pero', 'mientras', 'porque', 'aunque', 'sin' que une dos ideas, "
                    "pon una coma. Ninguna frase de más de 20 palabras puede quedarse sin "
                    "al menos una coma en medio. Reescribe el bloque entero con esa "
                    "puntuación.\n\n"
                ) + prompt
            else:
                mensaje = (
                    "TU RESPUESTA ANTERIOR NO SIRVIÓ: escribiste tu razonamiento en vez de la "
                    "historia. Empieza directamente por el TÍTULO en español, sin ningún texto "
                    "previo, y a continuación el speech.\n\n"
                ) + prompt

        raw = _call_openrouter([{"role": "user", "content": mensaje}], config)
        title, speech = _parse_title_and_speech(raw)
        ok, motivo = _validar_salida(title, speech, min_palabras_titulo=12,
                                     min_palabras_speech=200)
        if ok:
            return title, speech
        if _es_fallo_solo_puntuacion(motivo):
            dens = _densidad_comas(speech)
            if mejor_puntuacion is None or dens > mejor_puntuacion[2]:
                mejor_puntuacion = (title, speech, dens)
        logger.warning(f"Generación descartada ({motivo}); reintento {intento + 2}/{intentos}")

    # §13: nunca fallback mudo. Pero abortar un vídeo de 30 min (45 min de
    # trabajo) porque el modelo no metió suficientes comas es desproporcionado:
    # la narración sale con más pausas inventadas de lo normal, no impublicable.
    # Se acepta el MEJOR intento (mayor densidad de comas) entre TODOS los
    # reintentos, no solo el último, y se deja constancia RUIDOSA de que salió
    # por debajo del umbral.
    if mejor_puntuacion is not None:
        title, speech, dens = mejor_puntuacion
        logger.warning(
            f"Bloque 1: {intentos} intentos, TODOS por debajo del umbral de puntuación "
            f"({_PUNTUACION_MIN_COMAS_100} comas/100 palabras). Se acepta el MEJOR intento "
            f"({dens:.2f} comas/100 palabras) en vez de abortar el vídeo. Este bloque "
            f"sonará con más pausas inventadas de lo normal."
        )
        return title, speech

    raise RuntimeError(
        f"El modelo no devolvió una historia utilizable tras {intentos} intentos. "
        f"Último motivo: {motivo}. Último título: {title[:120]!r}"
    )


def _generate_continuation(title, story_so_far, target_words, words_remaining, is_final, config):
    """Generate a continuation block of the story."""

    if is_final:
        instruction = f"""Continúa y TERMINA esta historia. Escribe las últimas ~{words_remaining} palabras.

Incluye:
- El plan y su ejecución (confrontaciones, pruebas, acciones legales)
- Las consecuencias para los abusadores (pierden dinero, reputación, relaciones)
- Un epílogo: meses/años después, cómo está el protagonista ahora, reflexión final

NO dejes la historia abierta. Ciérrala con un final satisfactorio.
Escribe MÍNIMO {words_remaining} palabras. NO escribas menos.

RECORDATORIO: Párrafos largos y fluidos. NO fragmentes. NO uses comillas ni guiones de diálogo. Narración continua."""
    else:
        instruction = f"""Continúa esta historia. Escribe las siguientes ~{WORDS_PER_BLOCK} palabras.

Continúa con:
- Más escaladas del abuso (escenas específicas, detalles concretos, cantidades, fechas)
- El momento de quiebre del protagonista
- El inicio del plan de acción

NO termines la historia todavía. Corta en un punto de tensión.
Escribe MÍNIMO {WORDS_PER_BLOCK} palabras. NO escribas menos.

RECORDATORIO: Párrafos largos y fluidos. NO fragmentes. NO uses comillas ni guiones de diálogo. Narración continua."""

    base = [
        {
            "role": "user",
            "content": f"Estás escribiendo una historia larga para YouTube titulada:\n\"{title}\"\n\nLa historia total debe tener {target_words} palabras. Llevas {len(story_so_far.split())} palabras escritas hasta ahora."
        },
        {
            "role": "assistant",
            "content": story_so_far
        },
    ]

    # El guardia contra el razonamiento del modelo vivía SOLO en el primer
    # bloque. En una historia de 30 min son 4-6 bloques: protegía el primero y
    # dejaba los demás sin red, o sea ~2 de cada 3 peticiones sin validar.
    intentos = max(1, int(config.get("openrouter", {}).get("max_retries", 3)))
    motivo = ""
    mejor_puntuacion = None  # (texto, dens): el mejor intento que SOLO fallaba por comas
    for intento in range(intentos):
        mensaje = instruction
        if intento:
            if _es_fallo_solo_puntuacion(motivo):
                mensaje = (
                    "TU RESPUESTA ANTERIOR NO SIRVIÓ: escribiste frases larguísimas sin "
                    "comas internas y edge-tts se inventará dónde respirar. Antes de cada "
                    "'y', 'pero', 'mientras', 'porque', 'aunque', 'sin' que une dos ideas, "
                    "pon una coma. Ninguna frase de más de 20 palabras puede quedarse sin "
                    "al menos una coma en medio. Reescribe el bloque entero con esa "
                    "puntuación.\n\n"
                ) + instruction
            else:
                mensaje = (
                    "TU RESPUESTA ANTERIOR NO SIRVIÓ: escribiste tu razonamiento en vez de "
                    "continuar la historia. Continúa la narración en español directamente, "
                    "sin ningún texto previo ni encabezado.\n\n"
                ) + instruction

        texto = _call_openrouter(base + [{"role": "user", "content": mensaje}], config)
        ok, motivo = _validar_continuacion(texto)
        if ok:
            return texto
        if _es_fallo_solo_puntuacion(motivo):
            dens = _densidad_comas(texto)
            if mejor_puntuacion is None or dens > mejor_puntuacion[1]:
                mejor_puntuacion = (texto, dens)
        logger.warning(f"Continuación descartada ({motivo}); reintento {intento + 2}/{intentos}")

    # Mismo criterio que en el bloque 1 (ver comentario ahí): la falta de comas
    # no es motivo de aborto, es motivo de aviso ruidoso.
    if mejor_puntuacion is not None:
        texto, dens = mejor_puntuacion
        logger.warning(
            f"Continuación: {intentos} intentos, TODOS por debajo del umbral de "
            f"puntuación ({_PUNTUACION_MIN_COMAS_100} comas/100 palabras). Se acepta el "
            f"MEJOR intento ({dens:.2f} comas/100 palabras) en vez de abortar el vídeo. "
            f"Este bloque sonará con más pausas inventadas de lo normal."
        )
        return texto

    raise RuntimeError(
        f"El modelo no devolvió una continuación utilizable tras {intentos} intentos. "
        f"Último motivo: {motivo}."
    )


_DEDUP_MIN_RUN = 12       # palabras consecutivas identicas que delatan una repeticion
_DEDUP_HEAD_WINDOW = 80   # solo se recorta si la repeticion arranca al PRINCIPIO del bloque
_DEDUP_TAIL_WINDOW = 600  # cola de la historia contra la que se compara


def _normalize_words(words):
    return [w.lower().strip('.,;:!?¿¡"\'()[]—–-…«»') for w in words]


def _strip_duplicated_opening(story, continuation):
    """Recorta del bloque nuevo el texto que REPITE literalmente lo ya narrado.

    Medido en la primera produccion real (10-ago-2026): el bloque 3 reinicio un
    parrafo entero del bloque 2 y `generate_story` lo concateno tal cual. En
    `temp/video_001_story.txt` quedaron 83 palabras repetidas palabra por palabra
    (posiciones 2687 y 2792) y 72 n-gramas de 12 duplicados. El video narro dos
    veces el mismo parrafo: no es publicable y ningun guardia lo veia, porque
    `_validar_continuacion` juzga el bloque AISLADO y no lo compara con lo previo.

    Exige {_DEDUP_MIN_RUN} palabras consecutivas identicas (normalizadas) para
    cortar: la prosa espanola no repite 12 palabras seguidas por casualidad.
    Solo mira el ARRANQUE del bloque nuevo, que es donde el modelo re-narra.
    """
    cont_words = continuation.split()
    story_words = story.split()
    if len(cont_words) < _DEDUP_MIN_RUN or len(story_words) < _DEDUP_MIN_RUN:
        return continuation, 0

    tail = _normalize_words(story_words[-_DEDUP_TAIL_WINDOW:])
    head = _normalize_words(cont_words)

    positions = {}
    for i, w in enumerate(tail):
        if w:
            positions.setdefault(w, []).append(i)

    best_run, best_end = 0, 0
    for j in range(min(_DEDUP_HEAD_WINDOW, len(head))):
        for i in positions.get(head[j], ()):
            k = 0
            while i + k < len(tail) and j + k < len(head) and tail[i + k] == head[j + k]:
                k += 1
            if k > best_run:
                best_run, best_end = k, j + k

    if best_run < _DEDUP_MIN_RUN:
        return continuation, 0

    logger.warning(
        f"Bloque duplicado: el modelo re-narro {best_run} palabras ya escritas; "
        f"se recortan las primeras {best_end} palabras del bloque nuevo"
    )
    return " ".join(cont_words[best_end:]).strip(), best_end


def _limpiar_bloque(texto, etiqueta):
    """Quita la auto-anotación del modelo de UN bloque, no de la historia entera.

    `_strip_trailing_metadata` corta desde el marcador MÁS TEMPRANO hasta el
    FINAL de la cadena (`_detectar_meta_cola` devuelve `min(posiciones)`). Eso es
    correcto sobre un bloque —ahí el metadato SÍ está en la cola, que es como se
    midió [BASURA-03]— y destructivo sobre la concatenación de 3-6 bloques, que
    es donde `generate_story` lo llamaba: el marcador del bloque 1 se lleva por
    delante todos los bloques siguientes.

    Medido sobre el guion real `data/evidence/video_001_story.txt` (5307
    palabras) con el marcador literal de `video_004` pegado al final del bloque
    1: 5307 -> 1300 palabras, **4007 borradas (76%)**, desenlace incluido. El
    único aviso era un `logger.warning` con la historia entera dentro (§12), y
    el vídeo salía "terminado".
    """
    limpio, meta = _strip_trailing_metadata(texto)
    if meta:
        antes = len(texto.split())
        borradas = antes - len(limpio.split())
        # TOPE DENTRO DE LA FUNCIÓN. Antes esto no tenía ninguno: el defecto no
        # se había cerrado, se había movido de "corta hasta el final de la
        # concatenación" a "corta hasta el final del BLOQUE" — hasta 2000
        # palabras, en silencio. Un marcador a mitad del bloque 1 borraba 826
        # palabras (31% del guion) y no abortaba nada.
        #
        # El umbral es por FRACCIÓN DEL BLOQUE porque lo que distingue un
        # metadato de la narración es su POSICIÓN: el corte va del marcador al
        # final, así que un marcador en la cola se lleva poco y uno enterrado en
        # el cuerpo se lleva casi todo. Calibrado contra el caso REAL de
        # [BASURA-03] (`video_004`: 132 de 604 palabras = 22%), no contra un
        # número inventado.
        if borradas > antes * _META_CORTE_MAX_FRAC_BLOQUE:
            raise RuntimeError(
                f"{etiqueta}: la limpieza de metadato se llevaría {borradas} de "
                f"{antes} palabras ({borradas / antes:.0%}, máximo "
                f"{_META_CORTE_MAX_FRAC_BLOQUE:.0%}). Eso no es una auto-anotación "
                f"de cola, es narración: el marcador está enterrado en el cuerpo. "
                f"Se aborta en vez de publicar el bloque mutilado. Motivo: {meta!r}"
            )
        # `meta` recortado: este warning llegó a imprimir 826 palabras de
        # narración dentro, que es el mismo anti-patrón que critica el docstring.
        logger.warning(
            f"{etiqueta}: quitado metadato del modelo ({borradas} palabras): "
            f"{meta[:120]!r}{'...' if len(meta) > 120 else ''}"
        )
    return limpio


# --- Historia completa en una sola llamada [TRUNCA-02] -----------------------
# Antes, CUALQUIER objetivo (incluidos los 623 del fixture de /eval y los 2900
# de un vídeo corto) entraba por `_generate_first_block` pidiendo un bloque de
# tamaño FIJO (WORDS_PER_BLOCK=2000, "NO termines, corta en un punto de
# tensión") sin mirar `target_words`, y lo que sobraba lo tiraba
# `_truncate_to_words`. Medido con un doble COMPLIANT (escribe justo lo que
# cada instrucción pide) sobre el código de antes de este cambio: objetivo 623
# -> bloque 1 pide 2000, el bucle nunca entra (2000 ya supera el 85% de 623) y
# el cierre pide 500 más -> 2500 pedidas contra 623, y el guardia [TRUNCA-01]
# ABORTA el vídeo entero (mutilaría el 76% del guion, por encima de su propio
# 50% máximo) — con `_TRUNCADO_CUERPO_MAX_FRAC` activo el fixture ya no podía
# ni siquiera terminar. Con 2900 el reparto natural del bucle (2000 + 868 de
# cierre escalado) ya se acerca al objetivo, así que ahí el defecto es menor.
#
# Si `target_words` cabe en una sola llamada (el propio código ya sabe que
# WORDS_PER_BLOCK es lo que el modelo escribe con fiabilidad en una llamada:
# es la constante que fija cuánto pide cada bloque en el camino multi-bloque),
# no hace falta partir nada: se pide la historia COMPLETA con desenlace en una
# única petición. Por encima de ese umbral, el camino multi-bloque queda
# EXACTAMENTE igual que antes (mismo prompt, mismo bucle): con
# `target_words > WORDS_PER_BLOCK` este umbral no cambia su plan de bloques.
_UN_SOLO_BLOQUE_MAX_PALABRAS = WORDS_PER_BLOCK


def _generar_historia_un_bloque(target_words, style, config):
    """`target_words` cabe en una sola llamada: pide la historia COMPLETA.

    Devuelve `(title, story, cierre_escrito, word_count)`, mismo contrato que
    `_generar_historia_multi_bloque`, para que `generate_story` no necesite
    saber por qué camino pasó.
    """
    logger.info(
        f"Historia de {target_words} palabras cabe en un solo bloque "
        f"(<= {_UN_SOLO_BLOQUE_MAX_PALABRAS}): pidiendo la historia COMPLETA "
        f"en una sola llamada, sin partir en bloques"
    )
    title, story = _generate_first_block(target_words, style, config, cerrar_historia=True)
    story = _limpiar_bloque(story, "Bloque único")
    story = _ensure_title_at_start(title, story)

    word_count = len(story.split())
    logger.info(f"Bloque único: {word_count} palabras, titulo: {title[:60]}...")

    # Mismo umbral (0.85) que usa el camino multi-bloque para decidir si un
    # bloque cerró la historia de verdad: si pese a pedírsele la historia
    # COMPLETA con desenlace se queda muy por debajo del objetivo, lo más
    # probable es que el modelo se haya cortado a mitad (el mismo patrón que
    # [CIERRE-01] documentó en el camino multi-bloque). Se trata igual: NO se
    # asciende a "cerrada" solo porque se pidió — hace falta que además haya
    # llegado cerca del objetivo. `generate_story` pedirá el desenlace aparte
    # si esto queda en `False`.
    cierre_escrito = word_count >= target_words * 0.85
    if not cierre_escrito:
        logger.warning(
            f"Bloque único: {word_count} palabras, por debajo del 85% del "
            f"objetivo ({target_words}) pese a habérsele pedido la historia "
            f"COMPLETA con desenlace incluido. Se trata como si el cierre NO "
            f"se hubiera escrito: se pedirá aparte."
        )
    return title, story, cierre_escrito, word_count


def _generar_historia_multi_bloque(target_words, style, config):
    """`target_words` no cabe en una sola llamada: bloque 1 + continuaciones.

    Comportamiento SIN CAMBIOS respecto al código anterior a [TRUNCA-02] (es
    literalmente el mismo prompt y el mismo bucle) — lo único que cambia es
    que ahora solo se llega aquí cuando `target_words > WORDS_PER_BLOCK`, así
    que el suelo `max(2, ...)` de `num_blocks` es redundante (ceil ya da >=2)
    y se deja en `max(1, ...)` por defensa, no porque cambie nada.

    Devuelve `(title, story, cierre_escrito, word_count)`.
    """
    num_blocks = max(1, (target_words + WORDS_PER_BLOCK - 1) // WORDS_PER_BLOCK)
    logger.info(f"Generando historia de {target_words} palabras en ~{num_blocks} bloques")

    # Block 1: Title + hook + context
    logger.info(f"Bloque 1/{num_blocks}: generando titulo + inicio...")
    title, story = _generate_first_block(target_words, style, config)

    # La limpieza del metadato va POR BLOQUE (ver `_limpiar_bloque`): sobre la
    # concatenación se lleva por delante todo lo que venga detrás del marcador.
    story = _limpiar_bloque(story, "Bloque 1")

    # FORCE: ensure speech starts with the full title sentence
    story = _ensure_title_at_start(title, story)

    word_count = len(story.split())
    logger.info(f"Bloque 1: {word_count} palabras, titulo: {title[:60]}...")

    # Blocks 2+: Continuations
    max_attempts = num_blocks + 2  # allow a couple extra attempts
    block = 2
    cierre_escrito = False  # el bloque de desenlace se pidió Y devolvió texto

    while word_count < target_words * 0.85 and block <= max_attempts:
        words_remaining = target_words - word_count
        is_final = (words_remaining <= WORDS_PER_BLOCK * 1.3) or (block >= max_attempts)

        logger.info(f"Bloque {block}/{num_blocks}: {word_count}/{target_words} palabras, pidiendo {'final' if is_final else 'continuación'}...")

        continuation = _generate_continuation(
            title, story, target_words, words_remaining, is_final, config
        )

        continuation = _limpiar_bloque(continuation, f"Bloque {block}")
        continuation, recortadas = _strip_duplicated_opening(story, continuation.strip())
        if recortadas and len(continuation.split()) < 20:
            logger.warning(
                f"Bloque {block} era casi todo texto repetido ({recortadas} palabras "
                f"recortadas, quedan {len(continuation.split())}): se descarta el bloque"
            )
            continuation = ""

        if continuation:
            story = story.strip() + "\n\n" + continuation.strip()
            # Ojo: `is_final` solo dice qué se PIDIÓ. Si el bloque se descartó por
            # duplicado, se pidió el cierre y no hay cierre.
            if is_final:
                cierre_escrito = True
        word_count = len(story.split())
        logger.info(f"Bloque {block}: total acumulado {word_count} palabras")

        block += 1

        if is_final:
            break

    return title, story, cierre_escrito, word_count


def generate_story(target_words, style, config):
    """Generate a complete story, concatenating blocks until target_words is reached.

    Dos caminos, elegidos por tamaño (ver `_UN_SOLO_BLOQUE_MAX_PALABRAS`):
    - `target_words` cabe en una llamada -> `_generar_historia_un_bloque`.
    - si no -> `_generar_historia_multi_bloque` (comportamiento sin cambios).
    Los dos devuelven el mismo contrato, así que la garantía de desenlace y la
    limpieza de cola de abajo son compartidas por los dos caminos.
    """
    if target_words <= _UN_SOLO_BLOQUE_MAX_PALABRAS:
        title, story, cierre_escrito, word_count = _generar_historia_un_bloque(
            target_words, style, config
        )
    else:
        title, story, cierre_escrito, word_count = _generar_historia_multi_bloque(
            target_words, style, config
        )

    # GARANTÍA DE DESENLACE (§17). Sin este `if`, una historia que se pasa de
    # largo en un bloque de continuación sale del bucle a mitad de escena y el
    # vídeo de 30 min se publica sin final. No es hipotético: 1 de 3 corridas.
    if not cierre_escrito:
        logger.warning(
            f"La historia llego a {word_count} palabras SIN bloque de cierre "
            f"(el modelo se paso de largo en una continuacion). Pidiendo el "
            f"desenlace: ~{_CIERRE_PALABRAS} palabras."
        )
        cierre = _generate_continuation(
            title, story, word_count + _CIERRE_PALABRAS, _CIERRE_PALABRAS, True, config
        )
        # ANTES del mínimo de palabras: un cierre que es casi todo auto-anotación
        # tiene que caer por el guardia de abajo (abortar) en vez de colarse.
        cierre = _limpiar_bloque(cierre, "Bloque de cierre")
        cierre, _ = _strip_duplicated_opening(story, cierre.strip())

        if len(cierre.split()) < _CIERRE_MIN_PALABRAS:
            # §12/§13: nada de fallback mudo. Un vídeo de 30 min sin final no es
            # publicable, y nadie mira la salida. main.py captura esto por vídeo.
            raise RuntimeError(
                f"No se pudo cerrar la historia: el bloque de desenlace devolvio "
                f"{len(cierre.split())} palabras (minimo {_CIERRE_MIN_PALABRAS}). "
                f"Se aborta el video en vez de publicarlo sin final."
            )

        story = story.strip() + "\n\n" + cierre.strip()
        word_count = len(story.split())
        logger.info(f"Cierre anadido: {len(cierre.split())} palabras -> {word_count} totales")

    # El modelo se anota a sí mismo al final ("PALABRAS: 1558") y eso se NARRA.
    # Va ANTES del truncado: si no, el metadato cuenta como palabras del objetivo
    # y además el truncado conserva justo la cola, que es donde vive.
    # BACKSTOP: en el camino normal ya no dispara (cada bloque se limpió al
    # nacer). Si llega aquí es una forma nueva, y sobre la concatenación este
    # corte llega hasta el FINAL de la cadena: puede estar borrando la historia
    # entera en vez de una anotación. Con dientes (§12): aborta, no avisa.
    antes_meta = len(story.split())
    story, meta = _strip_trailing_metadata(story)
    if meta:
        borradas = antes_meta - len(story.split())
        # Umbral ATADO A LO QUE PROTEGE, no una fracción del total. Con el 15%
        # anterior, un vídeo de 30 min (~5600 palabras) toleraba borrar **840**,
        # cuando el bloque de desenlace entero son `_CIERRE_PALABRAS` = 500 y el
        # mínimo aceptable son 120: el guardia escrito para impedir que se borre
        # el final permitía borrarlo 1,7 veces. Reproducido: 621 palabras
        # borradas = 11,7% -> no abortaba -> guion publicado SIN desenlace.
        # Ahora: cualquier corte del tamaño de un desenlace mínimo es narración.
        # A estas alturas los bloques ya se limpiaron uno a uno, así que lo que
        # aparezca aquí es una forma NUEVA y toca ser conservador.
        if borradas >= _CIERRE_MIN_PALABRAS:
            raise RuntimeError(
                f"Limpieza de metadato sobre el guion completo: el corte se lleva "
                f"{borradas} de {antes_meta} palabras "
                f"({borradas / antes_meta:.0%}; un desenlace mínimo son "
                f"{_CIERRE_MIN_PALABRAS}). "
                f"Eso no es una auto-anotación de cola, es narración — probablemente "
                f"el desenlace. Se aborta el vídeo en vez de publicarlo a medias. "
                f"Motivo: {meta!r}"
            )
        # Ruidoso a propósito (§13): esto llegó a subtitularse en el fixture.
        logger.warning(f"Quitado metadato del modelo al final del guion: {meta!r}")
        word_count = len(story.split())

    # Truncate if overshooting (conservando el desenlace: ver _truncate_to_words)
    if word_count > target_words * 1.2:
        logger.info(f"Truncando de {word_count} a ~{target_words} palabras")
        story = _truncate_to_words(story, target_words)
        word_count = len(story.split())

    logger.info(f"Historia completa: {word_count} palabras ({word_count/target_words:.0%} del objetivo)")
    return title, story


def _partir_en_frases(texto):
    """Parte en (frase, separador) de forma REVERSIBLE.

    `"".join(f + s for f, s in _partir_en_frases(t)) == t` para cualquier t.
    Importa porque la versión anterior rejuntaba con `" ".join(...)` y eso:
      - convertía "4.500" en "4. 500" (partía en el punto de millar), y
      - borraba TODOS los saltos de párrafo. edge-tts trocea el texto cada 4096
        bytes eligiendo el punto de corte y prioriza los saltos de línea; sin
        ellos los cortes caen a mitad de frase y se oyen como un parón
        (medido: 2 de 2 cortes malos sin saltos, 0 de 2 con ellos).
    El lookahead `(?=\\s|$)` es lo que impide partir el punto de millar.
    """
    piezas = []
    pos = 0
    for m in re.finditer(r"[.!?]+(?=\s|$)", texto):
        fin = m.end()
        sep = re.match(r"\s*", texto[fin:]).group(0)
        piezas.append((texto[pos:fin], sep))
        pos = fin + len(sep)
    if pos < len(texto):
        piezas.append((texto[pos:], ""))
    return piezas


# --- Guardia contra la MUTILACIÓN del cuerpo al truncar [TRUNCA-01] ----------
# `_truncate_to_words` (de arriba) ya conserva el desenlace, pero eso no
# garantiza que la trama que el TÍTULO promete siga en el vídeo: el cuerpo que
# se descarta para hacerle sitio al cierre puede llevarse la escena que
# resuelve la historia. Caso real (`video_007`, corrida del gate del
# 14-ago-2026): el título anuncia "...Pero El Notario Descubrió La Coacción Y
# Anuló Todo" y esa escena de resolución NUNCA sobrevive al truncado -- vivía
# en el bloque de cierre que se ACABABA de pedir (1059 palabras) y el recorte
# a las últimas `preservar_cierre` (238 aquí) solo conserva la cola reflexiva
# del epílogo, no la escena. `anul-` aparece CERO veces fuera del título en el
# guion publicado. El vídeo miente en su propia miniatura y nadie lo ve: nadie
# mira los 3 minutos de salida (tesis central de produccion-loop.md).
#
# Antes de este guardia, la única señal era un `logger.warning` con la propia
# palabra "SALTO" en el mensaje (línea de abajo) — y §12 de este repo es
# exactamente que un aviso que solo se imprime no defiende de nada en un
# pipeline autónomo que nadie lee en tiempo real.
#
# Umbral, medido sobre los 7 truncados reales de `pipeline.log` a fecha
# 14-ago-2026 (fracción del guion pre-truncado que NO sobrevive):
#
#   régimen                          total  conservadas  descartada
#   PRODUCCIÓN real (16-ago, único dato real)  6979    5334      23,6%
#   fixture E2E, 6 corridas (target_words diminuto frente
#   al tamaño natural de un bloque del modelo)  2144-3347       71,8%-82,3%
#
# Separación limpia con 48 puntos de margen entre el único dato de producción
# y el peor caso de fixture. El umbral se fija en el punto medio (47,7%),
# redondeado a 0.50: deja el doble de margen sobre la producción real (no
# dispara por un overshoot normal, el único que se ha medido) y queda 22
# puntos por debajo del fixture más benigno (sigue disparando en el régimen
# que lo mide). Con un `n` de producción real de 1, este umbral es una frontera
# razonada, no una ley: si aparece un segundo dato real que la contradiga, se
# recalibra (§10, no se afirma sin medir).
#
# Decisión: ABORTAR, no tomar un camino alternativo. Se consideró "conservar
# el cierre COMPLETO en vez de solo su cola" para no perder la escena de
# resolución, pero con `max_words` tan por debajo del tamaño natural de un
# bloque (caso real: un cierre de 1059 palabras contra un objetivo de 623 EN
# TOTAL) no cabe ni el cierre completo ni nada de hook: cualquier recorte que
# quepa en el presupuesto pierde la mitad de la trama por definición, así que
# "un camino que no rompa la narración" no existe en ese régimen -- inventar
# uno sería otra garantía de prosa sin un `if` detrás (§17). Publicar de todos
# modos es exactamente "un vídeo cuyo título promete algo que no está". El
# coste de abortar es una corrida perdida (peticiones + tiempo); el coste de
# no abortar es un vídeo mentiroso subido a YouTube. Mismo patrón y mismo
# estilo que `_META_CORTE_MAX_FRAC` (arriba): un umbral nombrado y un `raise`,
# no un `logger.warning`.
_TRUNCADO_CUERPO_MAX_FRAC = 0.50


def _verificar_no_mutila(total, conservadas, detalle):
    """Aborta si conservar `conservadas` de `total` palabras es MUTILAR el
    guion, no truncarlo. Ver `_TRUNCADO_CUERPO_MAX_FRAC` para la calibración
    y el porqué de abortar en vez de avisar.

    Se llama en los TRES puntos de salida de `_truncate_to_words` (el cierre
    solo ya desborda el presupuesto, ni una frase del cuerpo cabe, o el
    recorte normal) porque los tres significan lo mismo: el texto que se
    publicaría representa `conservadas`/`total` del guion original. Un solo
    punto de cálculo evita que una de las tres rutas quede sin guardia -- es
    la clase de fallo de §17, 2.º corolario ("un guardia que existe no está
    aplicado en TODAS las rutas").
    """
    if total <= 0:
        return 0.0
    frac_descartada = 1 - (conservadas / total)
    if frac_descartada > _TRUNCADO_CUERPO_MAX_FRAC:
        raise RuntimeError(
            f"Truncado: mutilaría el {frac_descartada:.0%} del guion "
            f"({total - conservadas} de {total} palabras descartadas), por "
            f"encima del {_TRUNCADO_CUERPO_MAX_FRAC:.0%} máximo ({detalle}). "
            f"Esto no es 'truncar el cuerpo', es borrarlo: la trama que el "
            f"título promete probablemente no sobrevive. Se aborta el vídeo "
            f"en vez de publicarlo con un título que miente (clase "
            f"[TRUNCA-01])."
        )
    return frac_descartada


def _truncate_to_words(text, max_words, preservar_cierre=_CIERRE_PRESERVADO):
    """Recorta a ~max_words palabras SIN decapitar la historia.

    La versión anterior se quedaba con las PRIMERAS max_words palabras, o sea
    que tiraba el final. Medido en la corrida del 10-ago: la historia llegó a
    7157 palabras, el bloque `is_final` escribió su epílogo, y esto descartó
    1867 (26%) — el epílogo dentro. Que aquello acabara en algo que parece un
    cierre fue suerte de dónde cayó el corte, no diseño.

    Ahora se recorta el CUERPO y se conservan las últimas `preservar_cierre`
    palabras (redondeadas a frase entera). Introduce un salto en la narración,
    que es peor que no recortar y mucho mejor que quedarse sin desenlace.
    """
    total = len(text.split())
    if total <= max_words:
        return text

    piezas = _partir_en_frases(text)
    if not piezas:
        return text

    # El cierre nunca puede comerse la historia. Sin este tope, el fixture de
    # /eval (3 min -> 480 palabras) se quedaba SOLO con el epílogo, porque las
    # 600 palabras preservadas ya superan su objetivo entero. Un tercio deja
    # sitio a principio y final en cualquier régimen; en producción (5344) el
    # tope no muerde y `preservar_cierre` manda.
    preservar_cierre = max(1, min(preservar_cierre, max_words // 3))

    # 1. El cierre: frases desde el final hasta juntar `preservar_cierre` palabras.
    ini_cierre = len(piezas)
    palabras_cierre = 0
    while ini_cierre > 0 and palabras_cierre < preservar_cierre:
        ini_cierre -= 1
        palabras_cierre += len(piezas[ini_cierre][0].split())

    cierre = "".join(f + s for f, s in piezas[ini_cierre:]).strip()

    # [BASURA-03] backstop: `generate_story` llama a `_strip_trailing_metadata`
    # ANTES de truncar, así que en el camino normal esto nunca dispara — pero
    # si llega aquí basura sin limpiar (otra forma que el regex de arriba no
    # reconozca, o un caller que se salte el orden), NO se asciende a
    # "desenlace" en silencio. Un warning solo no defiende (§12): esto ABORTA,
    # igual que la garantía de desenlace de más arriba, porque publicar esto
    # como final es peor que no truncar.
    hay_meta, motivo_meta, _ = _detectar_meta_cola(cierre)
    hay_basura, motivo_basura = _detectar_basura(cierre)
    if hay_meta or hay_basura:
        motivo = motivo_meta if hay_meta else motivo_basura
        raise RuntimeError(
            f"Truncado: el desenlace que se iba a conservar como final del "
            f"vídeo es basura del modelo ({motivo}). No se asciende a "
            f"desenlace: se aborta el vídeo en vez de publicarlo con esto "
            f"como cierre."
        )

    # 2. El cuerpo: lo que quepa por delante dejándole sitio al cierre.
    presupuesto = max_words - palabras_cierre
    if presupuesto <= 0:
        _verificar_no_mutila(
            total, palabras_cierre,
            f"el desenlace solo ({palabras_cierre} palabras) ya supera el "
            f"objetivo de {max_words}"
        )
        logger.warning(
            f"Truncado: el desenlace solo ({palabras_cierre} palabras) ya supera el "
            f"objetivo de {max_words}. Se conserva entero y se descarta el cuerpo."
        )
        return cierre

    fin_cuerpo = 0
    palabras_cuerpo = 0
    while fin_cuerpo < ini_cierre:
        n = len(piezas[fin_cuerpo][0].split())
        if palabras_cuerpo + n > presupuesto:
            break
        palabras_cuerpo += n
        fin_cuerpo += 1

    cuerpo = "".join(f + s for f, s in piezas[:fin_cuerpo]).rstrip()
    if not cuerpo:
        _verificar_no_mutila(
            total, palabras_cierre,
            "ni una sola frase del cuerpo cabe en el presupuesto restante"
        )
        return cierre

    _verificar_no_mutila(
        total, palabras_cuerpo + palabras_cierre,
        f"frases {fin_cuerpo}-{ini_cierre} de {len(piezas)} descartadas del CUERPO"
    )
    logger.warning(
        f"Truncado: se descartan {total - palabras_cuerpo - palabras_cierre} palabras "
        f"del CUERPO (frases {fin_cuerpo}-{ini_cierre} de {len(piezas)}). Se conservan "
        f"las ultimas {palabras_cierre} para no quedarse sin desenlace. Esto introduce "
        f"un SALTO en la narracion en ese punto."
    )
    return cuerpo + "\n\n" + cierre


# --- Título de YouTube (campo de 100 caracteres) [TITULOYT-01] ---------------
# El título LARGO (20-35 palabras, 150-191 caracteres medido) es el que se
# narra, el de la intro y el de la miniatura: eso no cambia aquí. Pero YouTube
# corta el campo de título del video en 100 caracteres, y el gancho de este
# estilo de historia va al FINAL de la frase — así que publicar el título
# largo tal cual pierde el gancho entero. `generar_titulo_youtube` deriva un
# título corto (10-14 palabras) que SÍ conserva el gancho, para ese campo.
#
# Por §17 de este repo ("una garantía prometida en prosa no está garantizada
# hasta que un `if` la fuerza"), el límite de 100 caracteres y de palabras se
# valida en código, nunca se confía en que el modelo lo obedezca.
_YT_TITULO_MAX_CHARS = 100
_YT_TITULO_MIN_PALABRAS = 6
_YT_TITULO_MAX_PALABRAS = 16

# Guardia contra el título TELEGRÁFICO [TITULOYT-02]. Medido n=2 contra la API
# real: para caber en 100 caracteres el modelo a veces comprime a lo bruto,
# comiéndose preposiciones y artículos ("Mi Hermano Me Obligó Firmar Renuncia
# Herencia Grabé Coacción Juez Anuló Todo" — falta "a" en "obligó A firmar",
# falta "la" en "LA renuncia", falta "a la" en "renuncia A LA herencia"). Por
# §17 ("una garantía prometida en prosa no está garantizada hasta que un `if`
# la fuerza"), pedirlo en el prompt no basta: se mide la proporción de
# palabras funcionales (reutilizando `_ES_FUNCIONALES`, el mismo set que ya usa
# `_validar_titulo_youtube` para el chequeo de idioma) y se rechaza por debajo
# del umbral.
#
# CALIBRACIÓN (no inventada — medida sobre los títulos largos reales en disco,
# que son español natural bien escrito y son la población de control: el
# umbral NO puede rechazar a ninguno de ellos):
#   n=51 títulos largos reales (output/*_title.txt + los 50 de
#   data/evidence/shorts_titulos/*_title.txt, 12-29 palabras cada uno)
#   ratio de palabras funcionales: min=0.308  mean=0.433  median=0.438  max=0.579
#
#   Ejemplo BUENO del propio encargo (15 palabras): ratio 0.467 (7/15) — cae
#   dentro del rango de la población real.
#   Ejemplo MALO telegráfico  (12 palabras): ratio 0.167 (2/12) — muy por
#   debajo del mínimo de la población real (0.308).
#
# Hay separación clara con margen en ambos lados: 0.308 (mínimo real) vs 0.167
# (telegráfico), hueco de 0.141. El umbral se pone en el punto medio de ese
# hueco (0.2375), redondeado a 0.24, dejando margen a los dos lados:
#   0.24 está 0.068 por debajo del mínimo real (ningún título real cerca del
#   límite) y 0.073 por encima del telegráfico medido.
_YT_TITULO_MIN_RATIO_FUNCIONALES = 0.24


def _cortar_por_palabra(texto, max_chars=_YT_TITULO_MAX_CHARS):
    """Recorta `texto` a `max_chars` sin partir ninguna palabra a la mitad.

    Es el FALLBACK que nunca puede fallar: si el modelo no da un título
    corto utilizable, este recorte determinista del título largo garantiza
    igualmente un string ≤ max_chars. Si no hay ningún espacio dentro del
    límite (un solo "palabrón" más largo que max_chars, caso degenerado),
    no hay frontera de palabra que respetar y se corta duro — es preferible
    a no devolver nada.
    """
    texto = (texto or "").strip()
    if len(texto) <= max_chars:
        return texto
    cortado = texto[:max_chars]
    ultimo_espacio = cortado.rfind(" ")
    if ultimo_espacio > 0:
        cortado = cortado[:ultimo_espacio]
    return cortado.rstrip(" .,;:-–—").strip()


def _validar_titulo_youtube(titulo):
    """¿Este título corto sirve para el campo de YouTube? Devuelve (bool, motivo).

    Reutiliza los mismos marcadores/heurísticos que `_validar_salida` (fuga de
    razonamiento, encabezados del modelo, español plausible) en vez de
    inventar otros nuevos, y añade el único límite que le importa a este
    campo: el de caracteres.
    """
    if not titulo or not titulo.strip():
        return False, "título vacío"

    titulo = titulo.strip()

    if len(titulo) > _YT_TITULO_MAX_CHARS:
        return False, f"título de {len(titulo)} caracteres (máximo {_YT_TITULO_MAX_CHARS})"

    palabras = titulo.split()
    if not (_YT_TITULO_MIN_PALABRAS <= len(palabras) <= _YT_TITULO_MAX_PALABRAS):
        return False, (
            f"título de {len(palabras)} palabras (esperado "
            f"{_YT_TITULO_MIN_PALABRAS}-{_YT_TITULO_MAX_PALABRAS})"
        )

    bajo = titulo.lower()
    for marcador in _MARCADORES_RAZONAMIENTO:
        if marcador in bajo:
            return False, f"el título contiene razonamiento del modelo ('{marcador}')"

    for marcador in _MARCADORES_INICIO:
        if bajo.lstrip().startswith(marcador):
            return False, f"el título empieza por un encabezado del modelo ('{marcador}')"

    tokens = re.findall(r"[a-záéíóúüñ]+", bajo)
    aciertos = sum(1 for t in tokens if t in _ES_FUNCIONALES)
    if aciertos < 2 and not re.search(r"[áéíóúñü]", bajo):
        return False, "el título no parece español"

    # Guardia contra el estilo telegráfico (comerse preposiciones/artículos
    # para caber en 100 caracteres). Ver calibración junto a la constante.
    if tokens:
        ratio_funcionales = aciertos / len(tokens)
        if ratio_funcionales < _YT_TITULO_MIN_RATIO_FUNCIONALES:
            return False, (
                f"título telegráfico: {aciertos}/{len(tokens)} palabras funcionales "
                f"({ratio_funcionales:.0%}, mínimo {_YT_TITULO_MIN_RATIO_FUNCIONALES:.0%}) "
                f"— se come preposiciones/artículos para caber en el límite"
            )

    return True, ""


def _ultima_linea_util(raw):
    """La ÚLTIMA línea no vacía, limpia de comillas y de prefijos del modelo.

    Un modelo de razonamiento escribe primero lo que está pensando y pone la
    respuesta al FINAL. Quedarse con `raw.strip()` entero mete el razonamiento
    completo en el título; quedarse con la primera línea, peor todavía. Medido
    contra la API real: 5 de 5 respuestas empezaban por "The user wants..." o
    "We need to produce a short title...".
    """
    lineas = [ln.strip() for ln in (raw or "").splitlines()]
    lineas = [ln for ln in lineas if ln]
    if not lineas:
        return ""
    linea = lineas[-1]

    # El modelo ENTRECOMILLA su respuesta y la etiqueta por delante. Medido
    # contra la API real: devolvió `Another option: "Mi Vecino Falsificó Mi
    # Firma Para Vender Mi Parcela Y El Registro Lo Detectó`, y eso se habría
    # publicado tal cual en el campo de título de YouTube. El guardia de
    # palabras funcionales NO lo caza (0,44: el grueso de la frase sí es
    # español), así que hay que quitar la etiqueta aquí.
    # Se prefiere el tramo ENTRECOMILLADO más largo, que es donde el modelo pone
    # la respuesta; perseguir prefijos concretos ("another option", "otra
    # opción"…) sería un juego del topo sin fin.
    # Solo si lo entrecomillado es la MAYOR PARTE de la línea. Sin ese corte se
    # destroza un título legítimo que lleve una cita dentro: `Mi Jefe Dijo "No
    # Vales Nada" Y Luego Me Suplicó Que Volviera` quedaba en `No Vales Nada`.
    # La respuesta etiquetada del modelo ocupa el 81% de su línea; una cita
    # dentro de un título, el 22%.
    comillas = re.findall(r'["“«]([^"”»]{10,})["”»]?', linea)
    if comillas:
        mejor = max(comillas, key=len).strip()
        if len(mejor) >= 0.60 * len(linea):
            linea = mejor

    # Prefijos con los que a veces etiqueta su propia respuesta.
    for pref in ("título:", "titulo:", "title:", "respuesta:", "final:", "-", "*", "#"):
        if linea.lower().startswith(pref):
            linea = linea[len(pref):].strip()
    return linea.strip().strip('"').strip("'").strip("«»").strip()


def generar_titulo_youtube(titulo_largo, config):
    """Deriva el título CORTO (≤100 caracteres) para el campo de título de YouTube.

    El título largo sigue siendo el que se narra, el de la intro y el de la
    miniatura — esta función NO lo toca ni lo sustituye en ningún otro sitio,
    solo produce un campo nuevo. Pasa por `_call_openrouter`, la única costura
    permitida a OpenRouter en este repo, así que la llamada cuenta contra el
    tope diario igual que cualquier otra.

    Garantía dura: NUNCA lanza excepción ni devuelve "" para una entrada no
    vacía. Si el modelo no da un título válido tras los reintentos, cae a un
    recorte determinista del título largo (`_cortar_por_palabra`) que siempre
    cabe en 100 caracteres.
    """
    titulo_largo = (titulo_largo or "").strip()
    if not titulo_largo:
        return ""

    # Ya cabe en el campo de YouTube: no hace falta gastar una petición.
    if len(titulo_largo) <= _YT_TITULO_MAX_CHARS:
        return titulo_largo

    prompt = f"""Convierte este título largo de un video de YouTube en un título CORTO para el campo de título del video.

Título largo original:
"{titulo_largo}"

Reglas del título corto (todas obligatorias):
- Entre 10 y 14 palabras.
- Máximo 100 caracteres en total, contando espacios.
- En español de España, GRAMATICAL Y NATURAL: con TODAS sus preposiciones ("a", "de", "en", "con"...) y artículos ("el", "la", "los", "las"...). PROHIBIDO el estilo telegrama/titular de periódico comprimido, donde se eliminan preposiciones y artículos para que quepan más sustantivos. Es preferible un título MÁS CORTO pero bien escrito que uno más largo y atropellado.
- Conserva el GANCHO de la historia (lo más impactante, aunque en el título largo esté al final), no solo el arranque.
- Mismo estilo Title Case que el original (Mayúscula Inicial En Cada Palabra).
- Responde ÚNICAMENTE con el título. Sin comillas, sin explicaciones, sin prefijos como "Título:".

Ejemplo BUENO (español natural, con sus preposiciones y artículos):
"Compré Casa, Mi Madre Me Echó Y Exige Que Pague La Boda De Mi Hermana"

Ejemplo MALO — NUNCA hagas esto (telegráfico: falta "a" en "obligó A firmar", falta "la" en "LA renuncia", falta "a la" en "renuncia A LA herencia"):
"Mi Hermano Me Obligó Firmar Renuncia Herencia Grabé Coacción Juez Anuló Todo\""""

    intentos = max(1, int(config.get("openrouter", {}).get("max_retries", 3)))
    motivo = "sin intentos"
    candidato = ""
    for intento in range(intentos):
        mensaje = prompt
        if intento:
            mensaje = (
                f"TU RESPUESTA ANTERIOR NO SIRVIÓ ({motivo}). Responde ÚNICAMENTE con el "
                "título corto en español NATURAL Y GRAMATICAL —con TODAS sus "
                "preposiciones y artículos, nada de estilo telegrama—, de 10 a 14 "
                "palabras, sin superar 100 caracteres en total, sin comillas, sin "
                "explicaciones ni razonamiento previo.\n\n"
            ) + prompt

        try:
            # max_tokens GENEROSO a propósito, aunque la salida sean 100
            # caracteres. Con 200 esto NO funcionaba NUNCA: medido contra la API
            # real, los 5 intentos devolvieron razonamiento cortado a mitad
            # ("The user wants a short title...", 599-745 caracteres = justo el
            # tope) y el título no llegaba a escribirse jamás, así que SIEMPRE
            # caía al fallback gastando 5 peticiones para nada. nvidia/nemotron
            # es un modelo de razonamiento: hay que pagarle el razonamiento para
            # que llegue a la respuesta.
            raw = _call_openrouter([{"role": "user", "content": mensaje}], config, max_tokens=2000)
        except Exception as e:
            motivo = f"error llamando a OpenRouter: {e}"
            logger.warning(f"Título YouTube: intento {intento + 1}/{intentos} falló ({motivo})")
            continue

        candidato = _ultima_linea_util(raw)
        ok, motivo = _validar_titulo_youtube(candidato)
        if ok:
            return candidato
        logger.warning(
            f"Título YouTube descartado ({motivo}); reintento {intento + 2}/{intentos}: "
            f"{candidato[:100]!r}"
        )

    # FALLBACK DETERMINISTA (§13: nunca fallback mudo — se loguea ruidosamente
    # que se está cayendo a él, no se disimula como si fuera el camino normal).
    fallback = _cortar_por_palabra(titulo_largo, _YT_TITULO_MAX_CHARS)
    logger.warning(
        f"Título YouTube: SIN título válido del modelo tras {intentos} intento(s) "
        f"(último motivo: {motivo}; último candidato: {candidato[:100]!r}). "
        f"Cayendo al FALLBACK determinista: {fallback!r} ({len(fallback)} caracteres)"
    )
    return fallback
