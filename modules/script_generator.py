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

        choices = data.get("choices") or []
        content = choices[0].get("message", {}).get("content", "").strip() if choices else ""
        if content:
            return content

        last_error = f"200 sin contenido: {json.dumps(data, ensure_ascii=False)[:200]}"

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

# Prefijo del motivo, para que quien reintenta pueda distinguir "esto SOLO
# falló por falta de comas" de cualquier otro motivo de rechazo (razonamiento
# filtrado, basura, título vacío...) sin volver a parsear el texto.
_MOTIVO_PUNTUACION_PREFIJO = "densidad de comas insuficiente"


def _densidad_comas(texto):
    """Comas por 100 palabras. Se pega a la palabra anterior, así que contar
    ',' es equivalente a contar comas de verdad (no hay comas sueltas)."""
    palabras = texto.split()
    if not palabras:
        return 0.0
    return texto.count(",") / len(palabras) * 100


def _validar_puntuacion(texto, umbral=_PUNTUACION_MIN_COMAS_100,
                         min_palabras=_PUNTUACION_MIN_PALABRAS):
    """¿Tiene este bloque suficiente puntuación interna para narrarse bien?

    Sin comas, edge-tts se inventa dónde respirar (medido: 88 pausas fuera de
    puntuación en la corrida del 12-ago, 1 sola coma en 5334 palabras). Ver
    calibración completa junto a las constantes arriba.
    """
    palabras = texto.split()
    if len(palabras) < min_palabras:
        return True, ""  # sin suficiente texto para que la densidad signifique algo
    dens = _densidad_comas(texto)
    if dens < umbral:
        return False, (
            f"{_MOTIVO_PUNTUACION_PREFIJO}: {dens:.2f} comas/100 palabras "
            f"(mínimo {umbral}); sin puntuación interna, edge-tts se inventa "
            f"dónde respirar (§17 — ya falló pidiéndolo solo en el prompt)"
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
    return comunes / len(frag) >= umbral


def _ensure_title_at_start(title, story):
    """Ensure the speech starts with the full title as its first sentence.

    If the LLM didn't include the full title:
    1. Remove any partial overlap at the start of the speech
    2. Prepend the full title
    """
    import re as _re

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

    if overlap > 0:
        # Remove the overlapping partial title from the story start
        story = " ".join(story_words[overlap:])
        logger.info(f"Eliminado solapamiento de {overlap} palabras del inicio")

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


def _generate_first_block(target_words, style, config):
    """Generate title + first block (~2000 words): hook + context + start of escalation."""
    template = _load_prompt_template(config["paths"]["prompt_template"])
    prompt = template.format(target_words=target_words, style=style)

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


def generate_story(target_words, style, config):
    """Generate a complete story in blocks, concatenating until target_words is reached."""

    num_blocks = max(2, (target_words + WORDS_PER_BLOCK - 1) // WORDS_PER_BLOCK)
    logger.info(f"Generando historia de {target_words} palabras en ~{num_blocks} bloques")

    # Block 1: Title + hook + context
    logger.info(f"Bloque 1/{num_blocks}: generando titulo + inicio...")
    title, story = _generate_first_block(target_words, style, config)

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

    # 2. El cuerpo: lo que quepa por delante dejándole sitio al cierre.
    presupuesto = max_words - palabras_cierre
    if presupuesto <= 0:
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
        return cierre

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
