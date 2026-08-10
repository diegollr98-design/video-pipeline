import json
import logging
import os
import re
import time

import requests

logger = logging.getLogger(__name__)

WORDS_PER_BLOCK = 2000  # Each API call generates ~2000 words reliably


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


def _validar_salida(title, speech, min_palabras_titulo, min_palabras_speech):
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

    return True, ""


def _normalize_for_compare(text):
    """Normalize text for comparison: lowercase, strip punctuation."""
    import re
    return re.sub(r'[^a-záéíóúüñ\s]', '', text.lower()).strip()


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
        # Also remove any leading partial sentence (until first period)
        first_period = story.find('.')
        if first_period != -1 and first_period < 100:
            # Check if the text before the period is a fragment of the title
            fragment_norm = _normalize_for_compare(story[:first_period])
            title_remainder_norm = _normalize_for_compare(" ".join(title_clean.split()[overlap:]))
            if fragment_norm and title_remainder_norm and fragment_norm not in title_remainder_norm:
                pass  # Not a title fragment, keep it
            else:
                story = story[first_period + 1:].strip()
        logger.info(f"Eliminado solapamiento de {overlap} palabras del inicio")

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
    for intento in range(intentos):
        mensaje = prompt
        if intento:
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
        logger.warning(f"Generación descartada ({motivo}); reintento {intento + 2}/{intentos}")

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
    for intento in range(intentos):
        mensaje = instruction
        if intento:
            mensaje = (
                "TU RESPUESTA ANTERIOR NO SIRVIÓ: escribiste tu razonamiento en vez de "
                "continuar la historia. Continúa la narración en español directamente, "
                "sin ningún texto previo ni encabezado.\n\n"
            ) + instruction

        texto = _call_openrouter(base + [{"role": "user", "content": mensaje}], config)
        ok, motivo = _validar_continuacion(texto)
        if ok:
            return texto
        logger.warning(f"Continuación descartada ({motivo}); reintento {intento + 2}/{intentos}")

    raise RuntimeError(
        f"El modelo no devolvió una continuación utilizable tras {intentos} intentos. "
        f"Último motivo: {motivo}."
    )


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

    while word_count < target_words * 0.85 and block <= max_attempts:
        words_remaining = target_words - word_count
        is_final = (words_remaining <= WORDS_PER_BLOCK * 1.3) or (block >= max_attempts)

        logger.info(f"Bloque {block}/{num_blocks}: {word_count}/{target_words} palabras, pidiendo {'final' if is_final else 'continuación'}...")

        continuation = _generate_continuation(
            title, story, target_words, words_remaining, is_final, config
        )

        story = story.strip() + "\n\n" + continuation.strip()
        word_count = len(story.split())
        logger.info(f"Bloque {block}: total acumulado {word_count} palabras")

        block += 1

        if is_final:
            break

    # Truncate if overshooting
    if word_count > target_words * 1.2:
        logger.info(f"Truncando de {word_count} a ~{target_words} palabras")
        story = _truncate_to_words(story, target_words)
        word_count = len(story.split())

    logger.info(f"Historia completa: {word_count} palabras ({word_count/target_words:.0%} del objetivo)")
    return title, story


def _truncate_to_words(text, max_words):
    sentences = text.replace("!", "!|").replace("?", "?|").replace(".", ".|").split("|")
    result = []
    count = 0
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        words = sentence.split()
        if count + len(words) > max_words:
            break
        result.append(sentence)
        count += len(words)
    return " ".join(result)
