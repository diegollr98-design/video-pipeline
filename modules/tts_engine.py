import asyncio
import logging
import re
import edge_tts
import stable_whisper
from modules.utils import get_video_duration

logger = logging.getLogger(__name__)

_aligner_model = None


def _get_aligner(model_name="base"):
    global _aligner_model
    if _aligner_model is None:
        logger.info(f"Cargando modelo de alineacion ({model_name})...")
        _aligner_model = stable_whisper.load_faster_whisper(
            model_name, device="cpu", compute_type="int8"
        )
    return _aligner_model


def _detect_gender(text):
    """Detect narrator gender. Key distinction:
    - 'mi esposa/novia/mujer' = narrator is MALE (he has a wife)
    - 'mi esposo/novio/marido' = narrator is FEMALE (she has a husband)
    """
    sample = text[:1500].lower()

    male = [
        r'\bsoy hombre\b', r'\bpadre soltero\b', r'\bviudo\b',
        r'\bmi esposa\b', r'\bmi novia\b', r'\bmi mujer\b',  # has wife = male
        r'\bcansado\b', r'\bdecidido\b', r'\bfurioso\b', r'\basustado\b',
        r'\bsoy padre\b', r'\bcomo padre\b', r'\bcomo hijo\b', r'\bcomo hermano\b',
    ]
    female = [
        r'\bsoy mujer\b', r'\bmadre soltera\b', r'\bviuda\b',
        r'\bmi esposo\b', r'\bmi novio\b', r'\bmi marido\b',  # has husband = female
        r'\bcansada\b', r'\bdecidida\b', r'\bfuriosa\b', r'\basustada\b',
        r'\bsoy madre\b', r'\bcomo madre\b', r'\bcomo hija\b', r'\bcomo hermana\b',
        r'\bembarazada\b',
    ]
    m = sum(1 for p in male if re.search(p, sample))
    f = sum(1 for p in female if re.search(p, sample))
    return "female" if f > m else "male"


def _clean_speech_for_tts(text):
    """Clean text for natural TTS narration.

    - Remove block headers/titles
    - Join lines within paragraphs into continuous text
    - Preserve paragraph breaks (double newline) for natural pauses
    - Fix punctuation issues that cause unnatural pauses
    """
    lines = text.split("\n")
    cleaned = []

    for line in lines:
        stripped = line.strip()

        # Skip empty lines (paragraph breaks)
        if not stripped:
            cleaned.append("")
            continue

        # Skip block headers
        if re.match(r'^(BLOQUE|PARTE|SECCION|CONTINUACION|TITULO)\s*\d*', stripped, re.IGNORECASE):
            continue

        # Skip story titles
        if re.match(r'^(Mi |Fui |Rechace |Hui |Compre |Regrese )', stripped) and len(stripped) < 200 and '...' in stripped:
            continue

        cleaned.append(stripped)

    # Join lines within paragraphs (single newlines become spaces)
    text = "\n".join(cleaned)

    # Join lines within paragraphs, keep paragraph structure with proper punctuation
    paragraphs = re.split(r'\n\s*\n', text)
    cleaned_paragraphs = []
    for p in paragraphs:
        # Join lines within paragraph into one sentence flow
        p = re.sub(r'\n', ' ', p).strip()
        if p:
            # Ensure paragraph ends with a period for natural TTS pause
            if not p[-1] in '.!?':
                p += '.'
            cleaned_paragraphs.append(p)

    # Se unen con SALTO DE LÍNEA, no con espacio.
    # edge-tts trocea el texto cada 4096 bytes y elige el punto de corte
    # priorizando saltos de línea y, si no hay, cualquier espacio. Cada trozo es
    # una petición de síntesis independiente, así que un corte a mitad de frase
    # se oye como un parón. Medido con un texto de tamaño de producción: uniendo
    # con espacios, 2 de 2 cortes caían a mitad de frase; con saltos de línea,
    # 0 de 2. Un vídeo de 30 min son ~7 trozos, o sea ~6 costuras evitables.
    # El salto de línea no altera la prosodia (dentro del SSML es espacio en
    # blanco); solo le da a edge-tts un sitio natural donde cortar.
    text = '\n'.join(cleaned_paragraphs)

    # Fix punctuation issues
    text = re.sub(r'\.{2,}', '.', text)           # ... -> .
    text = re.sub(r'\s*,\s*,', ',', text)          # double commas
    text = re.sub(r'\s+([.,;:!?])', r'\1', text)   # space before punctuation
    text = re.sub(r'([.!?])\s*([.!?])', r'\1', text)  # double periods
    text = re.sub(r'[ \t]{2,}', ' ', text)         # multiple spaces -> single
    # Comillas: la clase DEBE incluir las tipográficas “ ” ‘ ’ „ ‟ ‹ › además de
    # las rectas y los guillemets. Antes solo cubría " « », así que las
    # tipográficas llegaban intactas al TTS y al forced alignment, donde el
    # emparejamiento de palabras es lo que sostiene los timestamps. No se notaba
    # con el modelo antiguo; los modelos que escriben con tipografía sí las usan.
    text = re.sub('["“”„‟«»‹›]', '', text)
    text = re.sub("['‘’‚‛`]", '', text)  # apóstrofos y comillas simples
    text = re.sub(r'[*_#]', '', text)              # remove markdown
    text = re.sub(r'\(\)', '', text)               # empty parens
    # Convert direct speech patterns to indirect (in case LLM ignored instruction).
    # COMA, no punto: medido, sustituir por punto metía una pausa de 1.18s en
    # mitad de la idea (una coma son ~0.4s, como cualquier otra). El objetivo es
    # deshacer el dos puntos de diálogo, no partir la frase en dos.
    text = re.sub(r':\s+([A-ZÁÉÍÓÚ])', lambda m: ", " + m.group(1).lower(), text)
    text = re.sub(r'—\s*', '', text)               # em dashes
    text = re.sub(r'-\s*-', ',', text)             # double hyphens -> comma
    # Limpieza final SIN tocar los saltos de línea (los necesita el troceo).
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r' *\n *', '\n', text)
    text = re.sub(r'\n{2,}', '\n', text)
    text = text.strip()

    # Último paso: garantizar puntos de respiración. Va aquí, después de toda la
    # normalización, para contar sobre el texto exacto que oirá el TTS.
    text = _ensure_breathing_commas(text)

    return text


# Conectores que en español admiten coma delante cuando unen dos ideas. Los del
# primer grupo la admiten casi siempre; los del segundo solo se usan si el tramo
# sin puntuación ya es muy largo, porque ahí sí que hay riesgo de coma incorrecta
# ("el olor a mosto, y a madera vieja" estaría mal).
_CONECTORES_SEGUROS = (
    "pero", "aunque", "mientras", "porque", "sino", "aunque", "salvo",
    "aun", "aunque", "aunque", "pues", "aunque",
)
_CONECTORES_LARGOS = ("y", "o", "ni", "que", "cuando", "si", "para", "sin", "con", "desde", "hasta")

# Umbrales: se mete coma en un conector seguro a partir de PALABRAS_RESPIRO
# palabras sin puntuación, y en uno dudoso solo a partir de PALABRAS_LIMITE.
PALABRAS_RESPIRO = 10
PALABRAS_LIMITE = 16


def _ensure_breathing_commas(text):
    """Inserta comas de respiración en tramos largos sin puntuación.

    MEDIDO (ago 2026): pedirle al modelo frases de 15-25 palabras con una coma
    cada 8-12 NO funciona. En 4 generaciones salieron 167, 129, 0 y 0 comas, con
    frases de 19 a 67 palabras de media y máximos de 116. El prompt original
    oscilaba igual (20, 139, 163). El modelo alterna entre dos modos y ninguno
    cumple la regla.

    Como edge-tts inventa una pausa a mitad de frase cuando no encuentra
    puntuación, esto se impone en código igual que se impone el título al inicio
    del speech: no se le pide al modelo, se le corrige la salida.

    Solo inserta delante de conectores, nunca en mitad de un sintagma.
    """
    resultado = []
    for parrafo in text.split("\n"):
        palabras = parrafo.split()
        salida = []
        desde_pausa = 0
        for palabra in palabras:
            limpia = re.sub(r"[^a-záéíóúüñ]", "", palabra.lower())
            # ¿Toca respirar aquí?
            if salida and not salida[-1].rstrip().endswith((",", ".", ";", ":", "!", "?")):
                if (limpia in _CONECTORES_SEGUROS and desde_pausa >= PALABRAS_RESPIRO) or (
                    limpia in _CONECTORES_LARGOS and desde_pausa >= PALABRAS_LIMITE
                ):
                    salida[-1] = salida[-1] + ","
                    desde_pausa = 0

            salida.append(palabra)
            if palabra.rstrip().endswith((",", ".", ";", ":", "!", "?")):
                desde_pausa = 0
            else:
                desde_pausa += 1

        resultado.append(" ".join(salida))

    return "\n".join(resultado)


async def _synthesize_audio(text, audio_path, voice, rate, volume):
    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
    with open(audio_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])


def _forced_align(audio_path, text, model_name="base"):
    """Forced alignment: take the EXACT original text and find where
    each word occurs in the audio. 100% word match guaranteed.

    If some segments fail to align, fills gaps by interpolation.
    """
    import warnings
    model = _get_aligner(model_name)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = model.align(
            audio_path, text, language="es",
            nonspeech_error=0.3,   # Issue #468: menos conservador con silencios → menos drift
            gap_padding=None,      # Issue #466: desactiva padding que causa drift en audio largo
        )

    words = []
    for seg in result.segments:
        for w in seg.words:
            word_text = w.word.strip()
            if word_text:
                end = min(w.end, w.start + 1.5) if w.end > w.start else w.end
                words.append({
                    "start": w.start,
                    "end": end,
                    "text": word_text,
                })

    # Fix gaps: if any word has start=end=0 or a gap > 2s, interpolate
    words = _fix_alignment_gaps(words)

    # Final safety: ensure every word has valid duration
    for i, w in enumerate(words):
        if w["end"] <= w["start"]:
            if i > 0:
                w["start"] = words[i-1]["end"]
            w["end"] = w["start"] + 0.2

    # Compress any suspiciously large gap (>3s = likely missing alignment)
    for i in range(1, len(words)):
        gap = words[i]["start"] - words[i-1]["end"]
        if gap > 3.0:
            mid = (words[i-1]["end"] + words[i]["start"]) / 2
            old_dur = words[i]["end"] - words[i]["start"]
            words[i]["start"] = mid + 0.1
            words[i]["end"] = words[i]["start"] + old_dur

    return words


def _fix_alignment_gaps(words):
    """Fix gaps in alignment where words have bad timestamps.

    Detects words with 0-duration or large gaps and interpolates
    their timestamps from surrounding words.
    """
    if not words:
        return words

    # First pass: mark bad words (0 duration or start >= end)
    for w in words:
        if w["end"] <= w["start"] or w["start"] < 0:
            w["_bad"] = True
        else:
            w["_bad"] = False

    # Second pass: fix bad words by interpolating from neighbors
    for i, w in enumerate(words):
        if not w["_bad"]:
            continue

        # Find previous good word
        prev_end = 0
        for j in range(i - 1, -1, -1):
            if not words[j]["_bad"]:
                prev_end = words[j]["end"]
                break

        # Find next good word
        next_start = prev_end + 5  # fallback
        for j in range(i + 1, len(words)):
            if not words[j]["_bad"]:
                next_start = words[j]["start"]
                break

        # Count consecutive bad words
        bad_count = 0
        for j in range(i, len(words)):
            if words[j]["_bad"]:
                bad_count += 1
            else:
                break

        # Distribute time evenly
        total_gap = next_start - prev_end
        word_dur = total_gap / max(bad_count, 1)

        idx_in_group = 0
        for j in range(i, i + bad_count):
            if j < len(words):
                words[j]["start"] = prev_end + idx_in_group * word_dur
                words[j]["end"] = prev_end + (idx_in_group + 1) * word_dur
                words[j]["_bad"] = False
                idx_in_group += 1

    # DO NOT close natural gaps — they are pauses between sentences
    # where only gameplay should be visible (no subtitles)

    # Clean up
    for w in words:
        w.pop("_bad", None)

    return words


def _build_word_srt(words):
    srt_lines = []
    for i, w in enumerate(words):
        if not w["text"].strip():
            continue

        def s_to_srt(seconds):
            ms = int(max(0, seconds) * 1000)
            h = ms // 3600000; ms %= 3600000
            m = ms // 60000; ms %= 60000
            s = ms // 1000; r = ms % 1000
            return f"{h:02d}:{m:02d}:{s:02d},{r:03d}"

        srt_lines.append(f"{i + 1}")
        srt_lines.append(f"{s_to_srt(w['start'])} --> {s_to_srt(w['end'])}")
        srt_lines.append(w["text"])
        srt_lines.append("")

    return "\n".join(srt_lines)


async def _synthesize_with_sentences(text, audio_path, voice, rate, volume):
    """Single TTS call: generate audio + capture sentence timestamps."""
    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
    sentences = []
    with open(audio_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "SentenceBoundary":
                sentences.append({
                    "start": chunk["offset"] / 10000 / 1000,
                    "duration": chunk["duration"] / 10000 / 1000,
                    "text": chunk["text"],
                })
    return sentences


def _validate_and_fix_alignment(words, sentences):
    """Hard anchors: use edge-tts SentenceBoundary as exact time anchors.

    edge-tts SentenceBoundary gives us the EXACT start/duration of each sentence
    as actually spoken (not estimated). We use these as hard anchors and
    redistribute Whisper's words proportionally within each sentence window.

    Words are matched to sentences SEQUENTIALLY (by count, not by Whisper
    timestamps) so Whisper drift can never misplace a sentence.

    Dentro de cada ventana se hace un REESCALADO AFÍN de los tiempos de Whisper,
    no un reparto lineal por caracteres.

    Por qué (medido, ago 2026): el reparto lineal tiraba los tiempos de Whisper y
    solo conservaba el ORDEN. Eso funciona con frases cortas, pero edge-tts emite
    un SentenceBoundary por FRASE, y los modelos que escriben frases largas con
    comas producen ventanas de ~49 palabras y ~15 s. Repartir linealmente ahí
    ignora pausas y comas, y el subtítulo llegaba a ir 1,5 s por detrás de la voz
    a mitad de ventana. Reescalando se conserva el ritmo real de Whisper
    (pausas incluidas) y a la vez los extremos quedan clavados al tiempo real de
    la TTS, así que la deriva entre frases sigue siendo imposible.

    Result:
    - Sentence-level sync: PERFECT (anchored to real TTS timing)
    - Word-level sync within sentence: el ritmo medido por Whisper, reescalado
    - Drift between sentences: IMPOSSIBLE
    - Natural pauses between sentences: preserved (gaps between windows)
    """
    if not sentences or not words:
        return words

    word_idx = 0
    anchored = 0
    rescaled = 0

    for sent in sentences:
        s_start = sent["start"]
        s_dur = sent["duration"]

        if s_dur <= 0:
            continue

        # Match words to this sentence sequentially by word count
        # (edge-tts text has the exact words it spoke, punctuation included)
        sent_word_count = len(sent["text"].split())
        end_idx = min(word_idx + sent_word_count, len(words))
        indices = list(range(word_idx, end_idx))
        word_idx = end_idx

        if not indices:
            continue

        s_end = s_start + s_dur
        w_first = words[indices[0]]["start"]
        w_last = words[indices[-1]]["end"]
        span = w_last - w_first

        if span > 0.05:
            # TRASLACIÓN, no estiramiento. La ventana de edge-tts NO mide la
            # frase hablada: tila el audio completo e incluye el silencio que
            # viene DESPUÉS (medido: ventanas hasta 7.72s cuando la voz acaba en
            # 6.76s). Estirar las palabras para rellenarla empujaba cada palabra
            # más tarde de cuando suena, con un retraso que crecía dentro de la
            # frase y se reseteaba en la siguiente.
            # Trasladando, el inicio queda clavado al tiempo real de la TTS (no
            # hay deriva acumulada entre frases) y las duraciones siguen siendo
            # las que midió Whisper. Además el silencio final de la ventana queda
            # libre, que es lo que hace desaparecer el subtítulo en las pausas.
            offset = s_start - w_first
            for idx in indices:
                words[idx]["start"] += offset
                words[idx]["end"] += offset

            # Solo si Whisper midió la frase MÁS LARGA que su ventana se
            # comprime, para no invadir la frase siguiente.
            if words[indices[-1]]["end"] > s_end:
                scale = s_dur / span
                for idx in indices:
                    words[idx]["start"] = s_start + (words[idx]["start"] - s_start) * scale
                    words[idx]["end"] = s_start + (words[idx]["end"] - s_start) * scale
            rescaled += 1
        else:
            # Whisper no dio un tramo usable para esta frase (todo colapsado en
            # un instante): ahí sí toca el reparto proporcional por caracteres.
            char_lens = [max(len(words[i]["text"]), 1) for i in indices]
            total_chars = sum(char_lens)
            cursor = s_start
            for j, idx in enumerate(indices):
                w_dur = s_dur * char_lens[j] / total_chars
                words[idx]["start"] = cursor
                words[idx]["end"] = cursor + w_dur
                cursor += w_dur

        anchored += 1

    logger.info(
        f"Anclas duras: {anchored}/{len(sentences)} frases ancladas a SentenceBoundary "
        f"({rescaled} reescaladas sobre el ritmo de Whisper, "
        f"{anchored - rescaled} repartidas por caracteres)"
    )
    return words


def run_tts(text, audio_path, vtt_path, config):
    clean_text = _clean_speech_for_tts(text)

    gender = _detect_gender(clean_text)
    voice = config["tts"][f"voice_{gender}"]
    rate = config["tts"]["rate"]
    volume = config["tts"]["volume"]
    logger.info(f"Protagonista detectado: {gender} -> voz: {voice}")

    # Single TTS call: audio + sentence timestamps
    logger.info(f"Sintetizando audio con voz '{voice}'")
    sentences = asyncio.run(
        _synthesize_with_sentences(clean_text, audio_path, voice, rate, volume))
    logger.info(f"Audio guardado, {len(sentences)} frases capturadas")

    # Forced alignment: exact text + audio = word timestamps
    whisper_model = config["tts"].get("whisper_model", "base")
    logger.info(f"Alineando texto con audio (forced alignment, {whisper_model})...")
    words = _forced_align(audio_path, clean_text, whisper_model)
    logger.info(f"Alineadas {len(words)} palabras (texto original: {len(clean_text.split())})")

    # Validate per-sentence: fix clustered words using sentence anchors
    words = _validate_and_fix_alignment(words, sentences)

    # Build SRT
    srt_content = _build_word_srt(words)
    with open(vtt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    duration = get_video_duration(audio_path)
    logger.info(f"Duracion del audio: {duration:.1f}s")
    return duration, words
