import asyncio
import logging
import re
import subprocess
import edge_tts
import stable_whisper
from modules.utils import get_video_duration, _find_exe

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


def _cuenta_palabras_reales(t):
    """Palabras que LLEVAN letra o dígito. Un '—' o un '***' suelto no cuenta.

    Se cuenta así, y no con `len(t.split())`, para que la guarda de
    `_clean_speech_for_tts` no salte por un token de solo puntuación que la
    limpieza elimina legítimamente.
    """
    return sum(1 for w in t.split() if re.search(r'\w', w, re.UNICODE))


def _clean_speech_for_tts(text):
    """Clean text for natural TTS narration.

    - Remove block headers/titles
    - Join lines within paragraphs into continuous text
    - Preserve paragraph breaks (double newline) for natural pauses
    - Fix punctuation issues that cause unnatural pauses
    """
    original = text
    lines = text.split("\n")
    cleaned = []
    palabras_saltadas = 0   # las que se quitan A PROPÓSITO (cabeceras, título)
    hay_contenido = False   # ¿ya salió alguna línea de narración?

    for line in lines:
        stripped = line.strip()

        # Skip empty lines (paragraph breaks)
        if not stripped:
            cleaned.append("")
            continue

        # Skip block headers
        if re.match(r'^(BLOQUE|PARTE|SECCION|CONTINUACION|TITULO)\s*\d*', stripped, re.IGNORECASE):
            palabras_saltadas += _cuenta_palabras_reales(stripped)
            continue

        # Skip story titles — SOLO en la cabecera, antes de que empiece la
        # narración. Sin `not hay_contenido` esto se aplicaba a TODAS las líneas
        # y se comía párrafos del cuerpo: cualquiera que empiece por "Mi ",
        # mida <200 caracteres y lleve "..." desaparecía de la narración. Medido:
        # 3 párrafos / 41 palabras -> 2 / 24, y como los subtítulos se generan
        # del MISMO texto ya mutilado, audio y subtítulos quedan coherentes
        # entre sí: ninguna métrica de sincronismo puede verlo.
        if (not hay_contenido
                and re.match(r'^(Mi |Fui |Rechace |Hui |Compre |Regrese )', stripped)
                and len(stripped) < 200 and '...' in stripped):
            palabras_saltadas += _cuenta_palabras_reales(stripped)
            continue

        cleaned.append(stripped)
        hay_contenido = True

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
    # Em dash -> ESPACIO, no cadena vacía. `r'—\s*'` se llevaba también el
    # espacio siguiente y fusionaba las dos palabras: "mi padre— era" salía
    # "mi padreera", que se pronuncia mal Y baja el conteo de palabras (21 -> 20
    # medido). Ese conteo es el invariante que `main.py` usa para saber cuándo
    # acaba el título: descuadrarlo mueve el fin de la intro en silencio.
    text = re.sub(r'\s*—\s*', ' ', text)           # em dashes
    text = re.sub(r'-\s*-', ',', text)             # double hyphens -> comma
    # Limpieza final SIN tocar los saltos de línea (los necesita el troceo).
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r' *\n *', '\n', text)
    text = re.sub(r'\n{2,}', '\n', text)
    text = text.strip()

    # Últimos pasos: garantizar la respiración. Van aquí, después de toda la
    # normalización, para contar sobre el texto exacto que oirá el TTS.
    # ORDEN IMPORTANTE: primero los PUNTOS y luego las comas. Al partir una
    # frase de 60 palabras en tres, el contador de las comas se resetea en cada
    # punto nuevo y deja de meter comas que ya no hacen falta. Al revés, las
    # comas se colocarían pensando en una frase que luego deja de existir.
    text = _ensure_breathing_periods(text)
    text = _ensure_breathing_commas(text)

    # INVARIANTE CON DIENTES (§12/§17): la limpieza NO pierde narración. Lo único
    # que puede desaparecer son las líneas que se saltan a propósito (cabeceras
    # de bloque, el título en la cabecera) y los tokens de solo puntuación.
    #
    # Es el único sitio del pipeline capaz de BORRAR contenido dejando audio y
    # subtítulos perfectamente coherentes entre sí — los dos salen de este mismo
    # texto — así que ninguna métrica de sincronismo ni el auditor pueden verlo.
    # Un warning no defendería (§12): esto aborta el vídeo, que es el lado barato
    # (§16). `main.py` lo captura por vídeo y sigue con el siguiente.
    #
    # Calibrado sobre los 5 guiones reales en disco (16.896 palabras): delta 0 en
    # los 5. No es un umbral inventado.
    esperadas = _cuenta_palabras_reales(original) - palabras_saltadas
    obtenidas = _cuenta_palabras_reales(text)
    if obtenidas != esperadas:
        raise RuntimeError(
            f"La limpieza para TTS perdió narración: {esperadas} palabras "
            f"esperadas y {obtenidas} obtenidas ({esperadas - obtenidas:+d}). "
            f"Se aborta el vídeo: audio y subtítulos saldrían de este mismo texto "
            f"mutilado, así que serían coherentes entre sí y el defecto sería "
            f"invisible para todas las métricas."
        )

    return text


# Conectores que en español admiten coma delante cuando unen dos ideas. Los del
# primer grupo la admiten casi siempre; los del segundo solo se usan si el tramo
# sin puntuación ya es muy largo, porque ahí sí que hay riesgo de coma incorrecta
# ("el olor a mosto, y a madera vieja" estaría mal).
# AUDITADO sobre 7.399 palabras de texto español real (ago 2026). El grupo largo
# original ("que", "para", "sin", "con", "desde", "hasta", "si") producía comas
# GRAMATICALMENTE INCORRECTAS, que es peor que no meter ninguna: una coma dentro
# de un sintagma hace que edge-tts pause justo donde no toca, que es el problema
# que esta función existe para evitar. Casos reales medidos:
#   "...asegurar la sucesión antes de, que yo me diera..."  (parte "antes de que")
#   "...mi madre amenazando, con destruir mi carrera..."    (verbo y complemento)
#   "...pagado con el primer sueldo, que mi padre ganó..."  (relativa especificativa
#                                                            -> explicativa: CAMBIA
#                                                            el significado)
# Se quedan solo los coordinantes, donde la coma cierra una cláusula.
_CONECTORES_SEGUROS = (
    "pero", "aunque", "mientras", "porque", "sino", "pues", "salvo",
)
_CONECTORES_LARGOS = ("y", "o", "ni", "cuando")

# Nunca se mete coma detrás de estas: encabezan locuciones ("antes de que",
# "a salvo", "junto con") y la coma las parte por la mitad.
_NO_CORTAR_TRAS = frozenset((
    "a", "de", "en", "con", "por", "para", "sin", "sobre", "tras", "hasta",
    "desde", "entre", "hacia", "segun", "según", "antes", "después", "despues",
    "junto", "además", "ademas", "cerca", "lejos", "dentro", "fuera", "acerca",
))

# Coordinantes: la coma delante solo es correcta si lo que sigue es una CLÁUSULA,
# no otro sintagma de una enumeración. Medido: "...medía en horas de fábrica, y
# en renuncias a..." está mal, "...la gente empezaba a mirar, y no quería..."
# está bien. Señal determinista barata: si tras el coordinante viene una
# preposición o un artículo, está coordinando sintagmas -> no se mete coma.
_COORDINANTES = frozenset(("y", "e", "o", "u", "ni"))
_ARRANQUE_DE_SINTAGMA = frozenset((
    "a", "de", "en", "con", "por", "para", "sin", "sobre", "tras", "hasta",
    "desde", "entre", "hacia", "el", "la", "los", "las", "un", "una", "unos",
    "unas", "lo", "al", "del", "su", "sus", "mi", "mis", "tu", "tus",
))

# Umbrales: se mete coma en un conector seguro a partir de PALABRAS_RESPIRO
# palabras sin puntuación, y en uno dudoso solo a partir de PALABRAS_LIMITE.
PALABRAS_RESPIRO = 10
PALABRAS_LIMITE = 16


# Conectores que pueden ABRIR frase en español narrado. Empezar una frase por
# "Y", "Pero", "Porque", "Cuando"… es normal al narrar; por "que" o "del" no.
_CONECTORES_PUNTO = frozenset((
    "y", "pero", "porque", "aunque", "mientras", "cuando", "entonces",
    "luego", "despues", "después", "sino", "pues",
))

# Máximo de palabras sin PUNTO.
#
# ⚠️ ESTA CONSTANTE ESTUVO EN 12 Y ERA UN ERROR DE MEDICIÓN MÍO. La elegí
# minimizando `EXCESO = nº silencios − nº signos`… y meter puntos AÑADE SIGNOS,
# así que bajar el umbral mejoraba la métrica de forma mecánica, no porque
# sonara mejor. Es la trampa de [SYNC-01] otra vez: la variable que manipulas
# metida dentro del instrumento con el que eliges.
#
# Lo cazó el oído de Diego, no una métrica: "parece que haya puntos donde
# debería haber comas, se hacen muchas pausas como si fueran puntos y eso hace
# que se pierda un poco el hilo". Medido después con métricas que NO contienen
# la variable manipulada (pausas largas ≥0,7 s y silencio total), sobre el mismo
# pasaje de producción:
#
#   cada    frase mediana   pausas LARGAS   silencio   wpm
#   -----   -------------   -------------   --------   -----
#   (sin)        142              7          13,1%     227,8
#    12           17             24  ← ×3,4  19,8%     206,9
#    20           26             17          17,6%     214,5
#    30           32             13          15,5%     221,4
#    40           43             12          15,0%     222,2
#
# Con 12 se cuadruplicaban las pausas de punto (1,1-1,3 s cada una) y ADEMÁS
# caían las comas de 21 a 12, porque cada punto resetea el contador de
# `_ensure_breathing_commas`: le quitaba respiraciones cortas para ponerle
# frenazos. Justo lo contrario de lo que hace falta.
#
# El criterio NO es la mediana sino la COLA: sobre las dos historias completas
# de producción, partir deja la mediana casi igual (48→31, 42→32) pero aplasta
# el p90 de **127→51** y **79→46**. Mueren las frases monstruo, que son las que
# hacen perder el hilo, y las frases normales se tocan lo mínimo.
#
# Se elige 30 —y no el 40 que Diego prefirió de oído— porque es el único ajuste
# bueno en los DOS ejes. A/B controlado de sincronismo (mismo texto, cuatro
# ajustes, contra transcripción independiente):
#
#   cada   |err| medio   p95     peor tramo   >0,5 s tarde
#   ----   -----------   -----   ----------   ------------
#    12       0,177      0,280     -0,213           6
#    20       0,196      0,496     +0,421          22
#    30       0,164      0,200     -0,198           0     <- elegido
#    40       0,191      0,484     +0,415          22
#
# ⚠️ Léase con cuidado: esto NO es monótono, así que la longitud de frase NO es
# la causa del desfase. Lo que hay debajo es una patología LOCAL del alineador
# ("Ventana aplastada en t=110,14 s: 57 palabras en 10,32 s = 331 wpm") que unos
# cortes rompen y otros no. Con n=1 historia estos números NO ordenan la
# constante: solo dicen que 30 es el único que sale bien en audio y en
# sincronismo a la vez. Diego, de oído, no distinguía 26 / 32 / 43 palabras de
# mediana, así que 30 no le cuesta nada perceptible.
PALABRAS_FRASE_MAX = 30


def _ensure_breathing_periods(text, cada=PALABRAS_FRASE_MAX):
    """Parte las frases kilométricas metiendo PUNTOS, no comas.

    MEDIDO (12-ago 2026, A/B controlado con edge-tts real sobre la peor frase del
    vídeo — 197 palabras): la longitud de frase es la palanca dominante y las
    comas NO la sustituyen.

        variante                        pausas inventadas   cortes de frase falsos
        1 frase, 4,57 comas/100 (la publicada)      +2              1
        1 frase, 13,20 comas/100 (3x la corrida buena)  -3          1
        frases cortas, CERO comas                    0              0

    Es decir: con el triple de comas que la mejor corrida, una sola frase larga
    SIGUE partiéndose sola; con frases cortas y ni una coma, no se parte nunca.
    Por eso `_ensure_breathing_commas` metió 165 comas en el vídeo del 12-ago y
    Diego siguió oyendo "muchas pausas, en sitios que no debería": las comas dan
    0,44 s donde toca, pero no impiden el corte de 1,1 s donde no toca.

    Las dos son necesarias y atacan defectos distintos:
      - sin punto  -> edge-tts inventa un FIN DE FRASE (1,1 s) a mitad de idea
      - sin coma   -> edge-tts inventa una RESPIRACIÓN (0,44 s) a mitad de idea

    Se impone en código por la misma razón que las comas y el título: el prompt
    lleva pidiendo "entre 15 y 25 palabras, nunca más de 30" desde siempre y el
    modelo entregó frases de mediana 48, p90 127 y máximo 197 (§17).

    La PRIMERA frase se deja intacta a propósito: es el título forzado, y es lo
    que se narra mientras la intro está en pantalla. Un punto ahí metería 1,1 s
    de silencio en mitad de la intro.
    """
    resultado = []
    # FUERA del bucle a propósito: el título es la primera frase del TEXTO, no la
    # de cada párrafo. Estando dentro, la exención se aplicaba a la primera frase
    # de CADA párrafo y esas frases no se partían con NINGÚN valor de `cada`
    # (medido: la de 57 palabras de `video_004` salía igual con 12, 20, 30 y 40, y
    # es la que se convirtió en la ventana aplastada de [ANCLA-06]). Además dejaba
    # `ANCLA_WPM_TIPICO` fuera de su régimen: el tope crece con n y el silencio de
    # la ventana no, así que en las ventanas largas no mordía nunca.
    titulo_en_curso = True
    for parrafo in text.split("\n"):
        palabras = parrafo.split()
        salida = []
        desde_punto = 0
        for palabra in palabras:
            limpia = re.sub(r"[^a-záéíóúüñ]", "", palabra.lower())
            if (salida and not titulo_en_curso and desde_punto >= cada
                    and limpia in _CONECTORES_PUNTO):
                previa_raw = salida[-1].rstrip()
                previa = re.sub(r"[^a-záéíóúüñ]", "", previa_raw.lower())
                # Mismo criterio que las comas: nunca partir una locución
                # ("antes de que", "junto con") por la mitad.
                if previa not in _NO_CORTAR_TRAS and not previa_raw.endswith(
                        (".", "!", "?", ";", ":")):
                    # El punto sustituye a una coma si ya la había, para no
                    # dejar ",." — y se PEGA a la palabra previa, que es lo que
                    # mantiene intacto el número de palabras.
                    salida[-1] = previa_raw.rstrip(",") + "."
                    palabra = palabra[:1].upper() + palabra[1:]
                    desde_punto = 0

            salida.append(palabra)
            if palabra.rstrip().endswith((".", "!", "?")):
                desde_punto = 0
                titulo_en_curso = False
            else:
                desde_punto += 1

        resultado.append(" ".join(salida))

    final = "\n".join(resultado)

    # MISMO INVARIANTE CON DIENTES que su gemelo: main.py indexa `aligned_words`
    # por el número de palabras del título para saber cuándo arranca la intro.
    # Los puntos se pegan a la palabra anterior y poner una mayúscula no divide
    # nada, así que el conteo no puede moverse.
    if len(final.split()) != len(text.split()):
        raise RuntimeError(
            "_ensure_breathing_periods cambió el número de palabras "
            f"({len(text.split())} -> {len(final.split())}). Rompe el cálculo de "
            "la intro en main.py; se aborta antes de generar nada."
        )

    return final


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
        for i, palabra in enumerate(palabras):
            limpia = re.sub(r"[^a-záéíóúüñ]", "", palabra.lower())
            # ¿Toca respirar aquí?
            if salida and not salida[-1].rstrip().endswith((",", ".", ";", ":", "!", "?")):
                previa = re.sub(r"[^a-záéíóúüñ]", "", salida[-1].lower())
                siguiente = re.sub(r"[^a-záéíóúüñ]", "", palabras[i + 1].lower()) if i + 1 < len(palabras) else ""
                coordina_sintagma = limpia in _COORDINANTES and siguiente in _ARRANQUE_DE_SINTAGMA
                if previa not in _NO_CORTAR_TRAS and not coordina_sintagma and (
                    (limpia in _CONECTORES_SEGUROS and desde_pausa >= PALABRAS_RESPIRO)
                    or (limpia in _CONECTORES_LARGOS and desde_pausa >= PALABRAS_LIMITE)
                ):
                    salida[-1] = salida[-1] + ","
                    desde_pausa = 0

            salida.append(palabra)
            if palabra.rstrip().endswith((",", ".", ";", ":", "!", "?")):
                desde_pausa = 0
            else:
                desde_pausa += 1

        resultado.append(" ".join(salida))

    final = "\n".join(resultado)

    # INVARIANTE CON DIENTES: main.py cuenta palabras para saber cuándo acaba la
    # frase del título y arrancar la intro. Si esta función cambiase el número de
    # palabras, la intro se descuadraría en TODOS los vídeos y en silencio. Las
    # comas se pegan a la palabra anterior, así que el conteo no puede moverse:
    # un comentario que lo afirma no lo implementa (decision-making.md §17).
    if len(final.split()) != len(text.split()):
        raise RuntimeError(
            "_ensure_breathing_commas cambió el número de palabras "
            f"({len(text.split())} -> {len(final.split())}). Rompe el cálculo de "
            "la intro en main.py; se aborta antes de generar nada."
        )

    return final


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


# Anclaje robusto (ANCLA-01, medido en la produccion real del 10-ago-2026).
# Vecindario de ventanas sobre el que se calcula la mediana de residuos y
# desviacion maxima tolerada antes de declarar el ancla de una ventana corrupta.
ANCLA_VECINDARIO = 3
ANCLA_TOL = 0.40
# Silencio maximo PLAUSIBLE dentro de una misma frase. edge-tts pausa 0,3-0,6 s
# en una coma (medido, CLAUDE.md); un hueco mayor DENTRO de la ventana es un
# silencio que Whisper se invento, y arrastra tarde a todo lo que viene detras.
# Barrido sobre la produccion real (214 ventanas, contra transcripcion
# independiente): 1.0 -> 20 palabras malas / p95 0,289; 0.8 -> 20 / p95 0,286;
# 0.7 -> 15 / p95 0,327; 0.6 -> ya adelanta de mas dos ventanas largas SANAS
# (-0,517 s en una de 76 palabras). 0.8 es el punto donde deja de haber dano
# colateral en ventanas largas, que son las que dominan el tiempo en pantalla.
ANCLA_HUECO_MAX = 0.80
# Velocidad IMPOSIBLE de pronunciar. Si el alineador mete las palabras de una
# ventana a más de esto, su ritmo no es una medida: es un aplastamiento, y
# trasladarlo deja los subtítulos vaciándose muy por delante de la voz.
# Medido sobre dos producciones reales (110 y 214 ventanas): lo normal es p50
# 209-225 wpm y p99 268-300; las patológicas fueron 530 wpm (44 palabras en 4,98 s
# cuando edge-tts dice que la frase dura 13,49 s) y 833 wpm. El corte a 330
# separa esas dos sin tocar ninguna ventana sana.
ANCLA_WPM_MAX = 330
# Velocidad típica medida, para repartir una ventana aplastada sobre una
# duración creíble en vez de estirarla hasta llenar la ventana entera (que
# incluye el silencio final y empujaría los subtítulos por detrás de la voz).
ANCLA_WPM_TIPICO = 210
# Ventana con el INTERIOR FABRICADO [ANCLA-05]. Distinta de la aplastada: aquí
# el ancla es CORRECTA y lo inservible es el ritmo de dentro, porque stable-ts
# no midió esas palabras — las rellenó. La firma es una duración que se repite
# idéntica en medio texto de la ventana MÁS al menos un hueco interno inventado.
# Se exigen las dos cosas: el relleno uniforme solo es dañino cuando además trae
# huecos, que son los que el cierre de abajo no puede quitar del todo.
# Barrido sobre 268 ventanas de las dos producciones reales: marca 2, y las 2
# son las realmente rotas (11-ago +1,450 s; 10-ago +0,507 s). 0 falsos positivos.
ANCLA_UNIFORMIDAD_MIN = 0.50
ANCLA_MIN_PALABRAS_FABRICADA = 5


def _mediana(valores):
    v = sorted(valores)
    n = len(v)
    if not n:
        return 0.0
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


# Cuánto puede alargarse como mucho el cue de una palabra que cierra frase.
_FINAL_EXT_MAX = 0.80


def _tramos_de_voz(audio_path, umbral_db=-35, dur_min=0.25):
    """Tramos con voz del audio, como complemento de `silencedetect`.

    Instrumento independiente del alineador, que es justo lo que hace falta aquí:
    el problema es que el alineador cree que la palabra ya terminó.
    """
    r = subprocess.run(
        [_find_exe("ffmpeg"), "-nostdin", "-i", audio_path, "-af",
         f"silencedetect=noise={umbral_db}dB:d={dur_min}", "-f", "null", "-"],
        capture_output=True, text=True)
    ini = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", r.stderr)]
    fin = [float(x) for x in re.findall(r"silence_end:\s*(-?[\d.]+)", r.stderr)]
    tramos, cursor = [], 0.0
    for i, s in enumerate(ini):
        if s > cursor:
            tramos.append((cursor, s))
        cursor = fin[i] if i < len(fin) else s
    tramos.append((cursor, float("inf")))
    return tramos


def _voz_en_ventana(tramos, ini, fin):
    """Los tramos de voz que caen dentro de [ini, fin], recortados a la ventana.

    Devuelve [] si no hay voz medible ahí: el que llama TIENE que tratar ese caso
    en voz alta, nunca inventando (§13).
    """
    segs = []
    for a, b in tramos or []:
        a2, b2 = max(a, ini), min(b, fin)
        if b2 - a2 > 0.01:
            segs.append((a2, b2))
    return segs


def _reloj_de_voz(offset, segs):
    """Convierte un instante del 'reloj de voz' (silencios colapsados) a tiempo real.

    Repartir por caracteres sobre la ventana entera aplana los silencios INTERNOS:
    medido en la ventana t=110,13 de `video_004`, 1,196 s repartidos en 3 pausas que
    el reparto lineal se comía, y el error salía en diente de sierra reiniciándose
    en cada pausa (+0,65 -> +0,04 -> +0,75 -> +0,30 -> ...). Caminando por el reloj
    de voz, las pausas dejan de consumir presupuesto de palabras.
    """
    for a, b in segs:
        d = b - a
        if offset <= d:
            return a + offset
        offset -= d
    return segs[-1][1] if segs else 0.0


def _extend_sentence_final_words(words, audio_path, tramos=None):
    """Alarga el cue de la última palabra de cada frase MIENTRAS siga sonando.

    Medido con `/eval` el 12-ago-2026, después de meter `_ensure_breathing_periods`:
    la voz sonaba **1,60 s en 3 tramos SIN ningún subtítulo en pantalla** (antes
    0,00 s), y los tres huecos caían justo detrás de una palabra que cierra frase
    (`LEGADO.` en 76,40 s, `TIMBRADO.` en 150,71 s, `1558.` en 179,49 s).

    Causa: al final de frase el TTS ALARGA la última palabra (final lengthening)
    y el alineador le da la duración de siempre, así que el subtítulo se va de
    pantalla mientras la voz todavía la está diciendo. No es nuevo — lo que hizo
    el partidor de frases fue multiplicar los sitios donde ocurre, de 13 a 28
    ventanas en el fixture, y ahí se hizo visible.

    Solo se alarga **dentro del tramo de voz**: si ya empezó el silencio, no se
    toca. Eso preserva la especificación de que los subtítulos desaparecen en las
    pausas (solo gameplay), que es una propiedad querida, no un efecto colateral.
    """
    if not words:
        return words
    if tramos is None:
        try:
            tramos = _tramos_de_voz(audio_path)
        except Exception as e:
            # Sin el instrumento no se inventa nada: se deja la alineación como está
            # y se dice en voz alta (§13), en vez de estirar a ciegas.
            logger.warning(f"No se pudieron medir los tramos de voz ({e}); "
                           f"los cues de fin de frase se dejan sin alargar")
            return words
    if not tramos:
        logger.warning("Sin tramos de voz: los cues de fin de frase se dejan sin alargar")
        return words

    alargadas = 0
    for i, w in enumerate(words):
        if not w["text"].rstrip().endswith((".", "!", "?")):
            continue
        fin_voz = None
        for a, b in tramos:
            if a <= w["end"] < b:
                fin_voz = b
                break
        if fin_voz is None or fin_voz == float("inf"):
            continue
        tope = min(fin_voz, w["end"] + _FINAL_EXT_MAX)
        if i + 1 < len(words):
            tope = min(tope, words[i + 1]["start"] - 0.01)
        if tope > w["end"] + 0.02:
            w["end"] = tope
            alargadas += 1

    if alargadas:
        logger.info(f"Cues de fin de frase alargados mientras seguia sonando la "
                    f"voz: {alargadas}")
    return words


def _enforce_monotonic(words):
    """Ningun subtitulo puede empezar antes de que acabe el anterior.

    El anclaje mueve ventanas enteras y puede dejar dos palabras solapadas en la
    misma `\\pos(960,540)` (dos palabras a la vez en pantalla). Medido en el .ass
    de la primera produccion real: 2 solapes y 1 arranque desordenado ya existian
    ANTES de tocar nada, sin que ninguna guarda los cortase.
    """
    paso_min = 0.05
    solapes = desordenes = 0
    for i in range(1, len(words)):
        prev, cur = words[i - 1], words[i]
        if cur["start"] < prev["start"] + paso_min:
            # Palabra que arranca ANTES que la anterior: el orden de lectura
            # queda invertido en pantalla. Ya pasaba en el .ass publicado.
            desordenes += 1
            cur["start"] = prev["start"] + paso_min
        if cur["end"] <= cur["start"]:
            # Solo el caso degenerado. NO imponer aqui una duracion minima de
            # visualizacion: a 200 wpm hay palabras de menos de 0,12 s, y el
            # suelo las estiraba para que el recorte de la iteracion siguiente
            # las volviera a encoger. Medido en el fixture de 3 min: 61 "solapes"
            # que se los inventaba esta misma guarda.
            cur["end"] = cur["start"] + 0.05
        if prev["end"] > cur["start"]:
            solapes += 1
            prev["end"] = cur["start"]
    if solapes or desordenes:
        logger.warning(
            f"Anclaje: {solapes} solapes recortados y {desordenes} palabras "
            f"desordenadas reubicadas"
        )
    return words


def _validate_and_fix_alignment(words, sentences, tramos_voz=None):
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

    ANCLA-01 (medido en la primera produccion real, 10-ago-2026): anclar cada
    ventana con UNA sola palabra (`offset = s_start - w_first`) es fragil. Si el
    alineador coloca esa primera palabra dentro del silencio anterior, el silencio
    entero se convierte en retraso RIGIDO para las hasta ~95 palabras de la
    ventana. Salieron 204 palabras (60,3 s de video) a ~+1 s por detras de la voz
    en un video por lo demas sano, y la media global —0,151 s— no lo delataba.

    Por eso el offset ahora es la MEDIANA de los residuos del vecindario y el
    residuo propio solo se usa si concuerda con sus vecinos; ademas se cierran los
    silencios que el alineador se inventa DENTRO de la ventana. Medido despues:
    20 palabras / 7,2 s, p95 1,010 -> 0,286 s, sesgo +0,005 -> -0,040 s.
    Banco de pruebas reproducible: `scripts/anchor_bench.py bench`.

    Result:
    - Sentence-level sync: anclado al tiempo real de la TTS, con ancla robusta
    - Word-level sync within sentence: el ritmo medido por Whisper, trasladado
    - Drift between sentences: IMPOSSIBLE
    - Natural pauses between sentences: preserved (gaps between windows)
    """
    if not sentences or not words:
        return words

    # --- Paso 1: repartir las palabras en ventanas y medir el residuo de cada una.
    # El residuo r = s_start - w_first es lo que la version anterior aplicaba tal
    # cual a TODA la ventana. Si stable-ts coloca la PRIMERA palabra dentro del
    # silencio anterior, r se contamina con la longitud de ese silencio y las
    # hasta ~95 palabras de la ventana se van ese tanto por detras de la voz, en
    # bloque. Medido en la produccion real: 4 ventanas de 214 a +1,05 s de media,
    # con error PLANO dentro de la ventana (no deriva) = firma de un offset malo.
    ventanas = []
    word_idx = 0
    for sent in sentences:
        if sent["duration"] <= 0:
            continue
        sent_word_count = len(sent["text"].split())
        end_idx = min(word_idx + sent_word_count, len(words))
        indices = list(range(word_idx, end_idx))
        word_idx = end_idx
        if not indices:
            continue
        ventanas.append({
            "s_start": sent["start"],
            "s_dur": sent["duration"],
            "indices": indices,
            "residuo": sent["start"] - words[indices[0]]["start"],
        })

    residuos = [v["residuo"] for v in ventanas]
    corregidas = 0

    anchored = 0
    rescaled = 0
    repartidas_voz = 0
    repartidas_ciegas = 0

    for pos, v in enumerate(ventanas):
        s_start = v["s_start"]
        s_dur = v["s_dur"]
        indices = v["indices"]

        # Offset ROBUSTO: la mediana de los residuos del vecindario. El residuo
        # propio solo se usa si concuerda con sus vecinos; si se desvia mas de
        # ANCLA_TOL es que la primera palabra de ESTA ventana esta mal colocada,
        # no que la voz se haya movido.
        ini = max(0, pos - ANCLA_VECINDARIO)
        fin = min(len(residuos), pos + ANCLA_VECINDARIO + 1)
        mediana = _mediana(residuos[ini:fin])
        offset_ventana = v["residuo"]

        # Un residuo grande tiene DOS causas opuestas y hay que distinguirlas o
        # se rompe justo lo que se quería arreglar (medido el 11-ago-2026 en 3
        # de 16 shorts de producción, con tramos enteros a 2 s de la voz):
        #   (a) ANCLA CORRUPTA -> outlier AISLADO: los vecinos concuerdan con la
        #       mediana. La ventana está mal y el vecindario es de fiar.
        #   (b) DERIVA DE WHISPER -> residuos que crecen en ventanas SEGUIDAS
        #       (-3,47 s y luego -5,39 s). Ahí el ancla de edge-tts es la CURA:
        #       verificado con `silencedetect` sobre el audio, que no depende de
        #       Whisper — los silencios reales acaban en 39,596 s y 45,918 s,
        #       justo donde edge-tts dice que arrancan esas frases (39,41/45,75),
        #       mientras Whisper las colocaba en 42,88 y 51,14.
        # Solo (a) se corrige; en (b) se respeta el ancla.
        def _concuerda(j):
            return j < 0 or j >= len(residuos) or abs(residuos[j] - mediana) <= ANCLA_TOL

        aislada = _concuerda(pos - 1) and _concuerda(pos + 1)
        ancla_corrupta = abs(v["residuo"] - mediana) > ANCLA_TOL and aislada
        if ancla_corrupta:
            offset_ventana = mediana
            corregidas += 1
            logger.warning(
                f"Ancla descartada en t={s_start:.2f}s ({len(indices)} palabras): "
                f"residuo {v['residuo']:+.3f}s frente a {mediana:+.3f}s del vecindario"
            )

        s_end = s_start + s_dur
        w_first = words[indices[0]]["start"]
        w_last = words[indices[-1]]["end"]
        span = w_last - w_first

        # Ventana APLASTADA: el alineador metió las palabras a una velocidad que
        # nadie puede pronunciar. Su ritmo no vale, así que se reparte sobre una
        # duración creíble anclada al inicio real de la frase.
        aplastada = span > 0.05 and len(indices) >= 5 and \
            len(indices) / span * 60 > ANCLA_WPM_MAX
        if aplastada:
            logger.warning(
                f"Ventana aplastada en t={s_start:.2f}s: {len(indices)} palabras en "
                f"{span:.2f}s ({len(indices)/span*60:.0f} wpm). Se reparte."
            )

        # Ventana con el INTERIOR FABRICADO [ANCLA-05]. El ancla acierta (residuo
        # −0,010 s contra transcripción independiente) pero el ritmo de dentro no
        # es una medida: stable-ts rellenó. Medido en la producción del 11-ago,
        # ventana t=128,55: 26 de 29 palabras con duración IDÉNTICA de 0,200 s
        # (90%) y dos huecos internos inventados de 2,82 s y 2,62 s. El cierre de
        # huecos de más abajo recorta el exceso pero RETIENE ANCLA_HUECO_MAX por
        # hueco: 1,60 s de silencio inexistente que empujan tarde a las 27
        # palabras siguientes (+1,45 s de mediana, 23 de 27 a más de 0,5 s).
        # Ningún guardia lo cazaba: 143 wpm queda muy por debajo de
        # ANCLA_WPM_MAX (que mide el lado contrario, el aplastado) y el ancla no
        # está corrupta, así que la guarda del vecindario hace bien en no tocarla.
        # Bajar ANCLA_HUECO_MAX no vale: barrido ya descartado (0,7 sube el p95 a
        # 0,327; 0,6 mete −0,517 s en una ventana sana de 76 palabras).
        durs = [round(words[i]["end"] - words[i]["start"], 3) for i in indices]
        modal = max(set(durs), key=durs.count) if durs else 0.0
        uniformidad = durs.count(modal) / len(durs) if durs else 0.0
        huecos_inventados = sum(
            1 for j in range(1, len(indices))
            if words[indices[j]]["start"] - words[indices[j - 1]]["end"] > ANCLA_HUECO_MAX
        )
        fabricada = (
            span > 0.05
            and len(indices) >= ANCLA_MIN_PALABRAS_FABRICADA
            and uniformidad >= ANCLA_UNIFORMIDAD_MIN
            and huecos_inventados >= 1
        )
        if fabricada and not aplastada:
            logger.warning(
                f"Ventana con interior fabricado en t={s_start:.2f}s: {len(indices)} "
                f"palabras, {uniformidad:.0%} con duracion identica de {modal:.3f}s y "
                f"{huecos_inventados} hueco(s) inventado(s). Se reparte."
            )

        # El ritmo de Whisper no sirve ni aplastado ni fabricado: en los dos casos
        # se reparte sobre una duración creíble en vez de trasladar su ritmo.
        ritmo_inservible = aplastada or fabricada

        if span > 0.05 and not ritmo_inservible:
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
            for idx in indices:
                words[idx]["start"] += offset_ventana
                words[idx]["end"] += offset_ventana

            if ancla_corrupta:
                # El residuo propio era basura para TODA la ventana, pero
                # `s_start` sigue siendo el instante exacto en que edge-tts
                # empieza la frase: la primera palabra se clava ahi a mano, sin
                # arrastrar a las demas. Su fin se recorta contra la palabra
                # siguiente para no dejar dos subtitulos a la vez en pantalla.
                primera = words[indices[0]]
                dur = max(0.12, primera["end"] - primera["start"])
                primera["start"] = s_start
                limite = words[indices[1]]["start"] if len(indices) > 1 else s_end
                primera["end"] = max(s_start + 0.12, min(s_start + dur, limite))

            # Silencios INVENTADOS dentro de la ventana. Es el segundo modo de
            # fallo, distinto del ancla corrupta y que ningun offset arregla:
            # medido en la produccion real, la frase 'El silencio que siguio fue
            # absoluto.' (6 palabras, 2,91 s segun edge-tts) salio de Whisper con
            # un hueco de 2,09 s entre la 1.ª y la 2.ª palabra, cuando la voz las
            # dice a 0,36 s de distancia. Ahi el ancla es correcta y lo roto es el
            # ritmo interior, asi que se cierra el exceso y se adelanta el resto.
            for j in range(1, len(indices)):
                previa = words[indices[j - 1]]
                actual = words[indices[j]]
                hueco = actual["start"] - previa["end"]
                if hueco > ANCLA_HUECO_MAX:
                    exceso = hueco - ANCLA_HUECO_MAX
                    for idx in indices[j:]:
                        words[idx]["start"] -= exceso
                        words[idx]["end"] -= exceso

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
            segs = _voz_en_ventana(tramos_voz, s_start, s_end)
            voz_util = sum(b - a for a, b in segs)

            if voz_util > 0.05:
                # REPARTO SOBRE LOS TRAMOS DE VOZ MEDIDOS [ANCLA-06].
                # El `min(s_dur, n/210*60)` de antes NO limitaba nunca en las
                # ventanas largas —que son las que más daño hacen—, porque el tope
                # crece linealmente con n y el silencio de la ventana no: para
                # n=57 hacían falta 1,42 s de silencio y solo había 1,13, así que
                # `util` degeneraba en `s_dur`, la ventana ENTERA de edge-tts.
                # Medido en `video_004` (t=110,13, 57 palabras) contra
                # transcripción independiente: mediana +0,460 y 21 palabras a más
                # de 0,5 s POR DETRÁS de la voz, las 21 de toda la corrida.
                # Y no bastaba con elegir mejor el escalar: el error era un diente
                # de sierra que se reiniciaba en cada pausa interna, así que la
                # otra mitad venía de aplanar los silencios de DENTRO.
                for j, idx in enumerate(indices):
                    ini_voz = voz_util * sum(char_lens[:j]) / total_chars
                    fin_voz = voz_util * sum(char_lens[:j + 1]) / total_chars
                    t_ini = _reloj_de_voz(ini_voz, segs)
                    t_fin = _reloj_de_voz(fin_voz, segs)
                    # El cue no cruza un silencio: se corta al final del tramo en
                    # el que empieza. Es la especificación de siempre (el
                    # subtítulo desaparece en las pausas), y aquí además evita
                    # dejarlo en pantalla mientras no suena nada.
                    for a, b in segs:
                        if a <= t_ini <= b:
                            t_fin = min(t_fin, b)
                            break
                    words[idx]["start"] = t_ini
                    words[idx]["end"] = max(t_ini + 0.02, t_fin)
                repartidas_voz += 1
            else:
                # Sin medida de voz NO se inventa: se conserva el comportamiento
                # viejo y se dice en voz alta (§13). Un fallback mudo aquí daría
                # verde en el banco sin haber ejercido nada.
                logger.warning(
                    f"Ventana en t={s_start:.2f}s repartida SIN medida de voz "
                    f"({len(indices)} palabras): "
                    + ("no hay tramos de voz en la ventana"
                       if tramos_voz else "no se pasó el audio")
                    + ". Reparto sobre la ventana entera, silencio incluido."
                )
                cursor = s_start
                util = min(s_dur, len(indices) / ANCLA_WPM_TIPICO * 60) \
                    if ritmo_inservible else s_dur
                for j, idx in enumerate(indices):
                    w_dur = util * char_lens[j] / total_chars
                    words[idx]["start"] = cursor
                    words[idx]["end"] = cursor + w_dur
                    cursor += w_dur
                repartidas_ciegas += 1

        anchored += 1

    logger.info(
        f"Anclas duras: {anchored}/{len(sentences)} frases ancladas a SentenceBoundary "
        f"({rescaled} reescaladas sobre el ritmo de Whisper, "
        f"{repartidas_voz} repartidas sobre los tramos de voz medidos, "
        f"{repartidas_ciegas} repartidas A CIEGAS sobre la ventana entera, "
        f"{corregidas} anclas corruptas sustituidas por la mediana del vecindario)"
    )
    if repartidas_ciegas:
        logger.warning(
            f"{repartidas_ciegas} ventana(s) repartidas sin medida de voz: esos "
            f"subtitulos pueden ir por detras de la voz [ANCLA-06]"
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

    # UNA sola medida de voz, compartida por el anclaje y por la extensión de los
    # cues finales: `silencedetect` sobre 30 min no es gratis y las dos la quieren.
    try:
        tramos = _tramos_de_voz(audio_path)
    except Exception as e:
        logger.warning(f"No se pudieron medir los tramos de voz ({e}): el anclaje "
                       f"repartira a ciegas si alguna ventana lo necesita")
        tramos = None

    # Validate per-sentence: fix clustered words using sentence anchors
    words = _validate_and_fix_alignment(words, sentences, tramos_voz=tramos)
    # Va DESPUÉS del anclaje (que mueve ventanas enteras) y ANTES de la guarda de
    # monotonía, que es la que corta cualquier solape que esto pudiera crear.
    words = _extend_sentence_final_words(words, audio_path, tramos=tramos)
    words = _enforce_monotonic(words)

    # Build SRT
    srt_content = _build_word_srt(words)
    with open(vtt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    duration = get_video_duration(audio_path)
    logger.info(f"Duracion del audio: {duration:.1f}s")
    return duration, words
