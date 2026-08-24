"""
shorts_generator.py — Genera YouTube Shorts / TikToks desde gameplay.

Formato 9:16, ~60-90s, velocidad x1.5, subtítulos adaptados, intro animada.
"""

import logging
import os
import re
import subprocess
from collections import Counter

from modules.utils import _find_exe, load_config, get_video_duration
from modules.script_generator import (
    _call_openrouter, _parse_title_and_speech, _ensure_title_at_start, _validar_salida,
    _es_fallo_solo_puntuacion, _palabras_entre_signos, _PUNTUACION_P90_MAX,
    _strip_trailing_metadata,
)
from modules.tts_engine import run_tts
from modules.subtitle_builder import vtt_to_ass
from modules.thumbnail_generator import generate_title_card, _get_next_tint

logger = logging.getLogger(__name__)

# Short-specific subtitle config overrides
SHORT_SUB_CONFIG = {
    "font_name": "Impact",
    "font_size": 80,
    "primary_color": "&H00FFFFFF",
    "outline_color": "&H00000000",
    "outline_width": 5,
    "shadow_depth": 0,
    "alignment": 5,
    "margin_v": 0,
    "max_chars_per_line": 20,
    "words_per_subtitle": 1,
    "uppercase": True,
    "play_res_x": 1080,
    "play_res_y": 1920,
}

WOOSH_PATH = "./assets/stereogenicstudio-swish-swoosh-woosh-sfx-27-357164.mp3"
# Mismo valor medido que video_composer.py:12 (mismo fichero de audio) — el
# instante donde cae el pico del woosh dentro del propio mp3.
WOOSH_PEAK = 0.483
# Mismo valor que el `settle_time` local de `_compose_short` (tiempo hasta que
# la tarjeta de título llega al centro). Un solo sitio para que no diverjan.
SETTLE_TIME = 0.25

# Mínimo de palabras que un short tiene que conservar DESPUÉS de
# `_strip_trailing_metadata` y del truncado a 280 palabras. Es el mismo umbral
# que `_validar_salida` exige al generarlo (`min_palabras_speech=80` más
# abajo); sin re-comprobarlo tras esas dos operaciones, un recorte agresivo
# puede dejar el speech en ~47 palabras (~15s de narración: la clase "short de
# 4,5 segundos" de CLAUDE.md) sin que nada lo detecte.
_MIN_PALABRAS_SPEECH_SHORT = 80

# [TITULO-LARGO-01] `prompts/short_story.txt` pide 10-18 palabras de título
# ("Los shorts necesitan títulos que se lean en 2 segundos"), pero el único
# guardia en código (`_validar_salida`, script_generator.py:339) acepta
# 8-45 porque ese rango es COMPARTIDO con la historia larga (títulos de
# 20-35 palabras allí). Pedirlo solo en el prompt no basta —es la misma
# clase de fallo que las comas y la variedad de shorts (§17)—: medido en
# disco había títulos de 20 palabras, y un A/B dio medianas de 17-18 con
# picos de 24. El título entra en la INTRO del short y su duración depende
# del número de palabras (`title_wc` más abajo, ~línea 470): un título de
# 24 palabras alarga la intro ~1,7 s sobre un short de ~40 s.
#
# El máximo aquí NO es 18 a secas: 18+margen. Un título de 19-21 palabras
# sigue siendo corto y forzar el límite exacto del prompt solo produce
# reintentos por redondeos de 1-2 palabras sin mejorar nada perceptible.
# 21 es el máximo que un A/B midió como "todavía se lee en ~2s" (mediana
# real 17-18); por encima de eso el modelo entra en el modo "subtítulo
# largo" que sí alarga la intro de forma medible.
_MAX_PALABRAS_TITULO_SHORT = 21

# Prefijos de motivo para las dos comprobaciones impuestas en ESTE módulo
# (apertura repetida, título demasiado largo). Mismo patrón que
# `_MOTIVO_PUNTUACION_PREFIJO` en script_generator.py: sirven para que el
# mensaje de reintento sea específico en vez de caer en el genérico
# "escribiste tu razonamiento", que no describe el fallo real y no ayuda al
# modelo a corregirlo.
#
# OJO: "título de" a secas colisionaría con el motivo que YA emite
# `_validar_salida` cuando el título viola el rango 8-45 que ella misma exige
# (script_generator.py:340: f"título de {n} palabras (esperado {min}-45)").
# Ese caso llega aquí con `ok=False` desde el principio (nunca entra en el
# bloque `if ok:` de abajo), así que hoy no hay bug funcional — pero el
# prefijo compartido lo dejaría a un cambio de distancia de confundir un
# motivo con otro. Prefijo propio para que no dependa de esa casualidad.
_MOTIVO_LONGITUD_PREFIJO = "short: título de"
_MOTIVO_APERTURA_PREFIJO = "vuelve a empezar por"


def _es_fallo_local(motivo):
    """¿El rechazo vino de un guardia de ESTE módulo (apertura/longitud) y no
    de `_validar_salida`? Determina qué mensaje de reintento se usa."""
    return bool(motivo) and (
        motivo.startswith(_MOTIVO_LONGITUD_PREFIJO)
        or motivo.startswith(_MOTIVO_APERTURA_PREFIJO)
    )


# Ventana de la lista anti-repeticion, EN UN SOLO SITIO a proposito.
# `main.py` siembra esta lista con los titulos que ya hay en disco y esta
# funcion la consume. El 2026-08-18 se descubrio que el consumidor se habia
# ensanchado a 40 y el sembrador seguia en 8 (`sorted(...)[-8:]`), asi que la
# proteccion ENTRE corridas era de 8 titulos y no de 40: `short_032` repitio el
# argumento de `short_017` (mismo boleto premiado robado por un familiar varon,
# mismo desenlace policial, misma CTA) porque `short_017` nunca llego a entrar
# en el prompt. Clase "fix no propagado al gemelo" (decision-making.md 11).
# Ahora los dos leen esta constante y no se pueden desincronizar.
AVOID_VENTANA = 40


def _build_avoid_block(avoid):
    """Bloque de prompt que lista lo ya generado para que no se repita.

    MEDIDO (ago 2026): sin esto, los 4 shorts de una misma corrida salieron con
    la MISMA historia ("Mi Hermano Vendió Mi Coche Clásico Para Pagar Sus
    Deudas", con finales distintos). Cada short es una llamada independiente con
    un prompt idéntico, así que la regla del prompt "la historia debe ser
    DISTINTA a cualquier otra" no significaba nada: el modelo no podía saber
    cuáles eran las otras. En un vídeo de 30 min se generan ~30 shorts.
    """
    if not avoid:
        return ""

    # La ventana era de 12. Con 45 shorts por vídeo de 30 min eso significa que
    # el short nº 40 ya no ve los 28 primeros y puede repetir su argumento: el
    # modelo no puede evitar lo que no se le enseña. Y como main.py siembra la
    # lista con los títulos del disco AL PRINCIPIO, con ventana de 12 salían
    # fuera en cuanto se generaban 12 shorts nuevos, así que la protección
    # ENTRE corridas solo cubría los primeros.
    # 40 entradas × ~15 palabras ≈ 600 palabras de prompt: despreciable frente a
    # la historia, y cubre una tanda entera.
    lineas = "\n".join(f"  {i}. {t}" for i, t in enumerate(avoid[-AVOID_VENTANA:], 1))
    return f"""

PROHIBIDO REPETIR. Ya has escrito estas historias en esta misma tanda:
{lineas}

La tuya debe ser CLARAMENTE distinta de todas ellas: otro parentesco (si arriba
sale un hermano, usa suegra, jefe, vecina, cuñado, socio...), otro objeto o bien
en disputa, otro escenario y otro tipo de desenlace. No basta con cambiar el
final ni con cambiar el sexo del culpable: cambia el CONFLICTO entero."""


# [APERTURA-01] La versión anterior exigía UNANIMIDAD exacta de las últimas 5
# (`len(set(ultimas)) == 1`). Eso se anula a sí misma: basta con que el propio
# guardia funcione una vez para que la palabra distinta que él mismo produjo
# entre en la ventana de 5 y la deje unánime-falsa. Medido en disco: el título
# "Descubrí Que Mi Tío Falsificó..." (generado por el guardia) sembró la tanda
# siguiente y dejó el guardia INERTE durante exactamente 4 shorts — el tamaño
# de la ventana menos uno. Resultado: 12 de 12 títulos "Mi ...".
#
# Ahora se mide DOMINANCIA sobre una ventana más larga en vez de unanimidad
# sobre una corta: no hace falta que TODOS compartan apertura, basta con que
# una sola supere el umbral. Un acierto aislado del guardia (una apertura
# distinta entre 9 iguales) ya no apaga la detección.
_APERTURA_VENTANA = 10
# Mínimo de títulos para que "dominancia" signifique algo. Con menos de 5 no
# hay tanda que evaluar (al arrancar una corrida puede haber 0-4 en `avoid`):
# el guardia se abstiene en vez de fallar sobre una muestra ruidosa, igual que
# `_validar_puntuacion` se abstiene con poco texto (script_generator.py:293).
_APERTURA_MIN_MUESTRA = 5
# Fracción de la ventana que una misma apertura tiene que ocupar para
# considerarse "racha". 0.6 sobre ventana=10 dispara con 6/10; sobre una
# muestra corta de 5 (el mínimo) dispara con 3/5 — sigue exigiendo mayoría
# clara, no un empate.
#
# Cota estructural (verificada con un mock adversarial en scratchpad, no solo
# argumentada): con estos dos valores, una única apertura NUNCA puede
# encadenar más de ceil(_APERTURA_DOMINANCIA * _APERTURA_VENTANA) = 6 títulos
# seguidos sin que el guardia la corte — la vieja unanimidad de 5 no tenía
# cota: una vez apagada por su propio acierto, corría LIBRE el resto de la
# tanda (12/12 medido). Esta ventana no promete "0 repeticiones nunca": un
# modelo cuyo default sin restricción es SIEMPRE la misma palabra puede
# oscilar (racha de 6 -> corrige 5 -> vuelve a subir a 6...). Eso es MEJOR que
# sin cota, y es exactamente el comportamiento que hay evidencia real de que
# NO ocurre (medido: el modelo obedeció a la 1.ª llamada en 3/3 disparos
# reales, no hay oscilación de vaivén observada en disco).
_APERTURA_DOMINANCIA = 0.6

# Familias de apertura que son la MISMA plantilla y no deberían contar como
# dos aperturas distintas para efectos de "cortar la racha": "Mis Padres Me
# Desheredaron" y "Mi Padre Me Desheredó" leen igual en una pared de
# miniaturas. Solo se funde esta familia (no se generaliza a otras palabras,
# para no fundir aperturas genuinamente distintas por accidente).
_APERTURA_FAMILIAS = {"mi": "mi", "mis": "mi", "mí": "mi"}


def _apertura(titulo):
    palabras = titulo.strip().split()
    if not palabras:
        return ""
    palabra = palabras[0].lower().strip('¿¡"\'.,;:!?')
    return _APERTURA_FAMILIAS.get(palabra, palabra)


def _apertura_agotada(avoid):
    """Apertura dominante de la ventana reciente, o None si no hay racha.

    Sustituye la unanimidad exacta (ver comentario arriba) por dominancia:
    la apertura más frecuente de las últimas `_APERTURA_VENTANA` tiene que
    superar `_APERTURA_DOMINANCIA` del total de la ventana. Un único acierto
    del guardia ya no lo apaga.
    """
    if not avoid or len(avoid) < _APERTURA_MIN_MUESTRA:
        return None
    ventana = avoid[-_APERTURA_VENTANA:]
    aperturas = [_apertura(t) for t in ventana]
    conteo = Counter(a for a in aperturas if a)
    if not conteo:
        return None
    apertura, n = conteo.most_common(1)[0]
    if n / len(ventana) >= _APERTURA_DOMINANCIA:
        return apertura
    return None


# Diseño DESCARTADO, documentado a propósito (no lo dejes a medias): prescribir
# la apertura por ROTACIÓN en código —una plantilla fija por short_num ("Mi
# X...", "El día que...", "Descubrí que...", "Cuando...", "Nadie sabía
# que...") en vez de reaccionar a una racha— y exigir que el título devuelto
# encaje con la plantilla asignada.
#
# Es TÉCNICAMENTE viable sin tocar main.py ni script_generator.py:
# `short_num` ya es monótono creciente entre corridas (main.py:129,
# `short_num_base = max(nums_shorts) + 1`), así que `short_num % len(plantillas)`
# da una rotación estable sin nuevo estado persistido.
#
# Se descarta por tres motivos, no por pereza:
#   1. Coste MEDIDO vs SIN MEDIR. El guardia reactivo (dominancia sobre la
#      ventana) cierra el defecto REAL observado ([APERTURA-01]) con coste
#      medido ~0 (los 3 disparos observados obedecieron a la 1.ª llamada). La
#      obediencia del modelo a una plantilla ARBITRARIA asignada por índice
#      —que puede no encajar con la historia que le tocó escribir— no está
#      medida, y §17 ya enseñó tres veces que una garantía de prosa que
#      "debería" cumplirse no se puede asumir sin medirla.
#   2. Encaje narrativo. "Nadie sabía que..." forzado sobre una historia donde
#      SÍ se sospechaba, o "Cuando..." sobre un conflicto que no arranca con
#      un instante puntual, es un remiendo peor que el problema: cambia el
#      enganche de la historia por una regla de índice, y eso es juicio de
#      calidad (Diego, §"El ojo de Diego"), no algo que este cambio deba
#      decidir por su cuenta.
#   3. Un patrón cíclico exacto es DETECTABLE igual que la racha que se quiere
#      evitar: un espectador que ve varios shorts seguidos notaría que la
#      apertura predice el short_num tan claramente como notaría 12/12 "Mi".
#      La dominancia por mayoría dentro de una ventana no impone un ciclo
#      fijo, solo evita que una sola apertura se coma la tanda.
#
# Si en el futuro se mide que la dominancia reactiva sigue sin bastar (nuevo
# incidente con id, `produccion-loop.md` §E), la rotación prescrita es la
# siguiente palanca a probar — con su propio guardia de encaje narrativo.


def _generate_short_story(style, config, avoid=None):
    """Generate a micro-story for a short (~200 words).

    `avoid`: títulos ya generados en esta tanda, para no repetir la historia.
    """
    prompt_path = config["paths"].get("short_prompt", "./prompts/short_story.txt")
    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()

    target_words = 200
    prompt = template.format(target_words=target_words, style=style) + _build_avoid_block(avoid)

    racha = _apertura_agotada(avoid)
    if racha:
        # §13: el guardia era MUDO. Su único canal era la inyección de texto en
        # el prompt (que no logea nada), así que parecía "nunca dispararse"
        # aunque estuviera activo — o inerte por [APERTURA-01] y nadie podía
        # distinguir un caso del otro sin leer el .ass o contar títulos a mano.
        logger.info(
            f"Short: racha de apertura detectada («{racha}» domina la ventana "
            f"de {min(len(avoid), _APERTURA_VENTANA)}); pidiendo variación al modelo"
        )
        prompt += (
            f"\n\nAPERTURA OBLIGATORIAMENTE DISTINTA: la mayoría de los últimos "
            f"títulos empiezan por «{racha}». El tuyo NO puede empezar por esa palabra. "
            f"Empieza por otra cosa — el hecho, el momento o el lugar: «Descubrí que...», "
            f"«El día que...», «Cuando...», «Me echaron de...», «Nadie sabía que...». "
            f"La historia sigue siendo en primera persona; lo que cambia es por dónde "
            f"empieza el título."
        )

    # Mismo guardia que en las historias largas: nemotron suelta a veces su
    # razonamiento y acababa como título del short, con un vídeo de 4,5s.
    #
    # También comparte el guardia de puntuación, y desde el 12-ago SÍ se le
    # aplica. Antes se dejaba fuera por COSTE: con la métrica vieja (densidad de
    # comas sobre el texto crudo) 27 de 50 shorts caían bajo el umbral y activarlo
    # costaba ~108 peticiones extra por vídeo. Ese coste era un artefacto de la
    # métrica: medida la nueva —p90 de palabras entre signos sobre el texto
    # NARRADO— los 4 shorts de la corrida del 12-ago dan p90 21, 21, 22 y 22
    # contra un máximo de 30, así que pasan todos y el coste real es ~0.
    # Tiene sentido: los shorts ya escriben frases cortas (mediana 18-21
    # palabras), que es justo la propiedad que el guardia mide.
    intentos = max(1, int(config.get("openrouter", {}).get("max_retries", 3)))
    motivo = ""
    mejor_puntuacion = None  # (title, speech, dens): mejor intento que SOLO fallaba por comas
    for intento in range(intentos):
        mensaje = prompt
        if intento:
            if _es_fallo_solo_puntuacion(motivo):
                mensaje = (
                    "TU RESPUESTA ANTERIOR NO SIRVIÓ: escribiste frases larguísimas sin "
                    "comas internas y edge-tts se inventará dónde respirar. Antes de cada "
                    "'y', 'pero', 'mientras', 'porque', 'aunque', 'sin' que une dos ideas, "
                    "pon una coma. Ninguna frase de más de 20 palabras puede quedarse sin "
                    "al menos una coma en medio. Reescribe la historia entera con esa "
                    "puntuación.\n\n"
                ) + prompt
            elif _es_fallo_local(motivo):
                # Mensaje específico en vez del genérico de "razonamiento": el
                # modelo SÍ escribió una historia válida, solo hay que ajustar
                # el título. Repetir el motivo exacto evita reintentos ciegos.
                mensaje = (
                    f"TU RESPUESTA ANTERIOR NO SIRVIÓ: {motivo}. Mantén la misma "
                    f"historia y corrige SOLO el título para que cumpla.\n\n"
                ) + prompt
            else:
                mensaje = (
                    "TU RESPUESTA ANTERIOR NO SIRVIÓ: escribiste tu razonamiento en vez de la "
                    "historia. Empieza directamente por el TÍTULO en español, sin ningún texto "
                    "previo.\n\n"
                ) + prompt

        raw = _call_openrouter([{"role": "user", "content": mensaje}], config)
        title, speech = _parse_title_and_speech(raw)
        ok, motivo = _validar_salida(title, speech, min_palabras_titulo=8,
                                     exigir_puntuacion=True,
                                     min_palabras_speech=_MIN_PALABRAS_SPEECH_SHORT)

        # La apertura y la longitud del título se PIDEN en el prompt y se
        # IMPONEN aquí. Pedirlo no basta: son el 4.º y 5.º episodio de este
        # repo donde una garantía en prosa no se cumple (comas, título al
        # inicio, variedad de historia, y ahora apertura + longitud). En el
        # último intento se acepta igual —un título repetitivo o largo es
        # mucho menos grave que quedarse sin short— pero con log RUIDOSO
        # (§13): antes ese camino era un fallback mudo.
        motivo_extra = None
        if ok:
            n_titulo = len(title.split())
            if n_titulo > _MAX_PALABRAS_TITULO_SHORT:
                motivo_extra = (
                    f"{_MOTIVO_LONGITUD_PREFIJO} {n_titulo} palabras (máximo "
                    f"{_MAX_PALABRAS_TITULO_SHORT} en shorts; el prompt pide 10-18)"
                )
            elif racha and _apertura(title) == racha:
                motivo_extra = f"{_MOTIVO_APERTURA_PREFIJO} «{racha}» (racha de apertura)"

        if motivo_extra:
            if intento < intentos - 1:
                ok, motivo = False, motivo_extra
            else:
                logger.warning(
                    f"Short: tras {intentos} intentos sigue fallando ({motivo_extra}); "
                    f"se acepta igual (mejor un short imperfecto que ninguno)."
                )
        if ok:
            break
        if _es_fallo_solo_puntuacion(motivo):
            # Con la métrica nueva el MEJOR intento es el de p90 más BAJO
            # (palabras seguidas sin signo), no el de más comas.
            tramos = sorted(_palabras_entre_signos(speech))
            p90 = tramos[int(len(tramos) * 0.9)] if tramos else 999
            if mejor_puntuacion is None or p90 < mejor_puntuacion[2]:
                mejor_puntuacion = (title, speech, p90)
        logger.warning(f"Short descartado ({motivo}); reintento {intento + 2}/{intentos}")
    else:
        # Mismo criterio que en la historia larga: la falta de comas no
        # justifica descartar el short entero (§13: nunca fallback mudo, así
        # que se deja constancia ruidosa de que salió por debajo del umbral).
        if mejor_puntuacion is not None:
            title, speech, p90 = mejor_puntuacion
            logger.warning(
                f"Short: {intentos} intentos, TODOS por encima del máximo de puntuación "
                f"({_PUNTUACION_P90_MAX} palabras entre signos). Se acepta el MEJOR "
                f"intento (p90 {p90}) en vez de descartar el short."
            )
        else:
            raise RuntimeError(
                f"El modelo no devolvió un short utilizable tras {intentos} intentos. "
                f"Último motivo: {motivo}"
            )

    # El gemelo comparte el defecto: el modelo se anota a sí mismo al final
    # ("PALABRAS: 1558") y eso se narra y se subtitula. Cazado en el vídeo largo
    # por `/eval`; aquí se aplica igual porque es la MISMA llamada al mismo
    # modelo con el mismo tipo de prompt (§11: fix no propagado al gemelo).
    speech, meta = _strip_trailing_metadata(speech)
    if meta:
        logger.warning(f"Short: quitado metadato del modelo al final: {meta!r}")

    speech = _ensure_title_at_start(title, speech)

    # Truncate if too long
    words = speech.split()
    if len(words) > 280:
        # Truncate at last sentence before limit
        text = " ".join(words[:280])
        last_period = max(text.rfind("."), text.rfind("!"), text.rfind("?"))
        if last_period > 0:
            speech = text[:last_period + 1]
        else:
            # Sin NINGÚN '.'/'!'/'?' en las primeras 280 palabras, el `if` de
            # arriba nunca entraba y el speech se quedaba ENTERO sin truncar
            # (no-op mudo: nada avisaba de que el "truncado" no truncó nada).
            # Corta igualmente, por palabras, y que quede constancia ruidosa.
            logger.warning(
                f"Short: sin punto/exclamación/interrogación en las primeras "
                f"280 palabras ({len(words)} en total); el truncado por FRASE "
                f"no puede aplicarse. Truncando por PALABRAS en su lugar."
            )
            speech = text

    # Re-validar DESPUÉS de `_strip_trailing_metadata` y del truncado: los dos
    # pueden dejar el speech por debajo del mínimo que se exigió al generarlo
    # sin que nada lo vuelva a comprobar (§13: nunca fallback silencioso).
    speech_wc = len(speech.split())
    if speech_wc < _MIN_PALABRAS_SPEECH_SHORT:
        raise RuntimeError(
            f"Short inutilizable tras limpiar metadatos/truncar: {speech_wc} "
            f"palabras de speech (minimo {_MIN_PALABRAS_SPEECH_SHORT}). "
            f"Titulo: {title!r}"
        )

    return title, speech


def _crop_to_vertical(input_path, output_path):
    """Crop 16:9 gameplay to 9:16 (center crop)."""
    ffmpeg = _find_exe("ffmpeg")
    # From 1280x720, crop center to 405x720, then scale to 1080x1920
    cmd = [
        ffmpeg, "-i", input_path,
        "-vf", "crop=405:720:437:0,scale=1080:1920",
        "-c:v", "h264_nvenc", "-cq", "23", "-preset", "p4",
        "-c:a", "copy",
        "-y", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Crop failed: {result.stderr[-300:]}")


def _premix_woosh_short(audio_path, output_path, settle_time=SETTLE_TIME):
    """Mix woosh into short audio, sincronizado con la llegada de la tarjeta al centro.

    Gemelo de `video_composer._premix_woosh` (video_composer.py:15). Hasta
    ahora el offset SIEMPRE era 0 (`adelay=0|0`), así que el pico del woosh
    (WOOSH_PEAK) sonaba en t=0 del audio en vez de cuando la tarjeta de título
    llega al centro (t=settle_time). El gemelo largo sí lo calcula
    (`woosh_offset = max(0, settle_time - WOOSH_PEAK)`, video_composer.py:84).
    """
    ffmpeg = _find_exe("ffmpeg")
    if not os.path.isfile(WOOSH_PATH):
        # §13: nada de fallback mudo. Antes esto devolvía el audio sin woosh
        # sin dejar ningún rastro — el short salía sin sonido de intro y nadie
        # se enteraba.
        logger.warning(
            f"Woosh no encontrado en {WOOSH_PATH!r}: el short se compone SIN "
            f"sonido de intro. Es material de terceros y no se distribuye con "
            f"el repo: ver assets/README.md"
        )
        return audio_path

    woosh_offset = max(0, settle_time - WOOSH_PEAK)

    cmd = [
        ffmpeg,
        "-i", audio_path,
        "-i", WOOSH_PATH,
        "-filter_complex",
        (
            "[0:a]aformat=sample_fmts=fltp:sample_rates=24000:channel_layouts=mono[tts];"
            f"[1:a]adelay={int(woosh_offset * 1000)}|{int(woosh_offset * 1000)},volume=0.4,"
            "aformat=sample_fmts=fltp:sample_rates=24000:channel_layouts=mono,"
            "apad[woosh];"
            "[tts][woosh]amix=inputs=2:duration=first:normalize=0[out]"
        ),
        "-map", "[out]",
        "-c:a", "libmp3lame", "-b:a", "192k",
        "-y", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning(f"Woosh mix failed: {result.stderr[-200:]}")
        return audio_path
    return output_path


def _compose_short(gameplay_path, audio_path, ass_path, output_path,
                   title_card_path=None, title_end_time=0, speed=1.5,
                   tint_color=None, offset=0):
    """Compose a vertical short with speed-up, intro, and subtitles.

    Uses live gameplay blur with dynamic golden-angle tint (not static PNG).
    """
    ffmpeg = _find_exe("ffmpeg")

    ass_ffmpeg = ass_path.replace("\\", "/").replace(":", "\\:")

    seek_args = ["-ss", str(offset)] if offset > 0 else []
    inputs = ["-threads", "4", "-stream_loop", "-1", *seek_args, "-i", gameplay_path,
              "-itsoffset", "-0.10", "-i", audio_path]

    if title_card_path and os.path.isfile(title_card_path):
        settle_time = SETTLE_TIME
        bounce_decay = 12
        bounce_freq = 18
        fade_start = max(title_end_time - 0.3, 2.0) if title_end_time > 0 else 4.0
        fade_dur = 0.8
        total = fade_start + fade_dur

        # Input 2: title card
        inputs += ["-loop", "1", "-t", str(total + 1), "-i", title_card_path]

        x_expr = (
            f"if(lt(t,{total}),"
            f"W*exp(-{bounce_decay}*t)*cos({bounce_freq}*t),"
            f"W)"
        )

        # Dynamic tint from golden angle rotation applied to live gameplay blur
        if tint_color:
            r, g, b = tint_color
            rm = max(-1.0, min(1.0, (r / 255.0 - 0.5) * 1.6))
            gm = max(-1.0, min(1.0, (g / 255.0 - 0.5) * 1.6))
            bm = max(-1.0, min(1.0, (b / 255.0 - 0.5) * 1.6))
            colorbal = f"colorbalance=rm={rm:.2f}:gm={gm:.2f}:bm={bm:.2f}"
        else:
            colorbal = "colorbalance=rs=0.4:gs=-0.2:bs=0.5"

        filter_complex = (
            # Split gameplay: one clean, one for blurred+tinted intro background
            f"[0:v]crop=405:720:437:0,scale=1080:1920,split[gameplay][forbg];"
            # Live blurred background: scale down 1/6 before blur (36x faster), scale back up
            f"[forbg]scale=iw/6:-1,gblur=sigma=20,scale=1080:1920,"
            f"{colorbal},"
            f"eq=brightness=0.05:saturation=2.5,"
            f"fade=t=out:st={fade_start}:d={fade_dur}:alpha=1"
            f"[livebg];"
            # Overlay tinted blur on gameplay (fades out to reveal clean gameplay)
            f"[gameplay][livebg]overlay=0:0:format=auto,"
            f"ass='{ass_ffmpeg}'[base];"
            # Title card overlay with bounce animation
            f"[2:v]format=rgba,scale=1080:1920,"
            f"fade=t=out:st={fade_start}:d={fade_dur}:alpha=1"
            f"[card];"
            f"[base][card]overlay="
            f"x='{x_expr}':"
            f"y=0:"
            f"enable='lt(t,{total})':"
            f"format=auto,"
            f"format=yuv420p[v]"
        )
    else:
        filter_complex = (
            f"[0:v]crop=405:720:437:0,scale=1080:1920,"
            f"ass='{ass_ffmpeg}',format=yuv420p[v]"
        )

    cmd = [
        ffmpeg,
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "1:a",
        # Techo de bitrate: medido, un short de 39 s salía a 23,6 Mbps y pesaba
        # 110 MB. Son 5,5 GB por tanda de 50 con el disco al 99%, y el doble de
        # lo que YouTube recomienda para 1080p60 vertical. Ver video_composer.
        "-c:v", "h264_nvenc", "-cq", "23", "-preset", "p4",
        "-maxrate", "12M", "-bufsize", "24M",
        # Mismo motivo que en video_composer: YouTube y TikTok normalizan a -14
        # LUFS BAJANDO, nunca subiendo. Medido en el audio real de un short:
        # -22,2 -> -14,8 LUFS.
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-y", output_path,
    ]

    logger.info(f"Componiendo short: {os.path.basename(output_path)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Short compose failed:\n{result.stderr[-500:]}")

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    logger.info(f"Short generado: {output_path} ({size_mb:.1f} MB)")


def _compute_title_end(title, words, short_num=None):
    """Instante en el que termina la frase del titulo dentro del audio narrado.

    NOTA sobre el regex de limpieza: este incluye \u2026 (puntos suspensivos
    tipograficos) y el del gemelo largo (main.py:275) NO. Es divergencia real
    entre gemelos (regla 11 de decision-making.md): el mismo titulo da un
    `title_wc` distinto en cada rama. Se documenta aqui para propagarlo en otra
    sesion (no se toca main.py desde este cambio). Criterio para decidir cual
    version es la correcta: `title_wc` tiene que contar lo mismo que cuentan
    las palabras ALINEADAS por el TTS, y edge-tts no pronuncia un "\u2026" como
    palabra propia -- asi que la version que lo QUITA (esta, la de shorts) es
    la que no se desincroniza si el titulo trae una elipsis suelta como token
    independiente.

    [SHORT-GUARD-01] Antes: `words[min(title_wc - 1, len(words) - 1)]`. Con
    `title_wc == 0` (titulo que limpia a SOLO puntuacion -- la clase [BASURA]
    ya vista en este repo para el titulo largo), `min(-1, ...)` da **-1**, que
    en Python indexa la ULTIMA palabra alineada: title_end pasaba a ser el FIN
    DE TODA LA NARRACION y `vtt_to_ass(skip_until=title_end)` tiraba TODOS los
    subtitulos del short, sin ningun error. El gemelo largo SI se abstiene en
    este caso (main.py:278: `title_word_count > 0 and title_word_count <
    len(aligned_words)`) -- aqui faltaba la guardia equivalente.
    """
    title_clean = re.sub(r'[.!?,;:\-\"\'\u2026]', '', title.lower()).split()
    title_wc = len(title_clean)

    if words and 0 < title_wc < len(words):
        return words[title_wc - 1]["end"]
    if not words:
        return 4.0

    # title_wc <= 0 (titulo vacio tras limpiar) o title_wc >= len(words) (el
    # "titulo" consumiria la narracion entera): ninguno de los dos es
    # localizable de forma fiable. Comportamiento SEGURO, igual que el gemelo
    # largo: no suprimir subtitulos (title_end=0.0 -> skip_until=0 en
    # vtt_to_ass) en vez de indexar fuera de rango. Y RUIDOSO (regla 13): el
    # bug real fue que esto pasaba sin dejar rastro.
    logger.warning(
        f"Short #{short_num}: no se pudo localizar el fin del titulo en las "
        f"palabras alineadas (title_wc={title_wc} tras limpiar {title!r}, "
        f"{len(words)} palabras alineadas). Usando title_end=0.0 (los "
        f"subtitulos NO se suprimen) en vez de indexar fuera de rango."
    )
    return 0.0


def generate_short(gameplay_path, short_num, config, style="dramatic", speed=1.5, offset=0,
                   avoid=None):
    """Generate one complete YouTube Short / TikTok.

    Args:
        gameplay_path: source gameplay video (16:9)
        short_num: sequential number for naming
        config: pipeline config
        style: story style
        speed: playback speed (1.5x recommended)
        offset: start position in gameplay (seconds), so each short uses a different segment
        avoid: títulos ya generados en esta tanda, para no repetir la historia

    Devuelve el título generado, para que quien orquesta lo acumule en `avoid`.
    """
    temp_dir = config["paths"]["temp_dir"]
    output_dir = config["paths"].get("shorts_dir", "./shorts_tiktok")
    os.makedirs(temp_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    stem = f"short_{short_num:03d}"

    # 1. Generate micro-story
    logger.info(f"=== Generando Short #{short_num} ===")
    title, story = _generate_short_story(style, config, avoid=avoid)
    logger.info(f"Titulo: {title}")
    logger.info(f"Palabras: {len(story.split())}")

    # Persistir el guion, igual que main.py hace con `{stem}_story.txt` para el
    # vídeo largo. Antes el `story` moría en memoria: sin él no hay forma de
    # reproducir offline lo que de verdad se sintetizó (saltos de párrafo
    # incluidos, que es la variable que toca `_ensure_breathing_periods`), y
    # cualquier medición futura exigía una petición nueva de OpenRouter.
    story_path = os.path.join(temp_dir, f"{stem}_story.txt")
    with open(story_path, "w", encoding="utf-8") as f:
        f.write(story)

    # 2. Generate NORMAL speed audio + perfect forced alignment
    audio_normal = os.path.join(temp_dir, f"{stem}_audio_normal.mp3")
    srt_path = os.path.join(temp_dir, f"{stem}_subs.srt")
    audio_dur, words = run_tts(story, audio_normal, srt_path, config)

    # 3. Speed up audio with FFmpeg atempo (preserves quality)
    audio_path = os.path.join(temp_dir, f"{stem}_audio.mp3")
    ffmpeg = _find_exe("ffmpeg")
    subprocess.run([
        ffmpeg, "-i", audio_normal,
        "-filter:a", f"atempo={speed}",
        "-c:a", "libmp3lame", "-b:a", "192k",
        "-y", audio_path,
    ], capture_output=True)
    fast_dur = get_video_duration(audio_path)
    logger.info(f"Audio: normal={audio_dur:.1f}s -> x{speed}={fast_dur:.1f}s")

    # 4. Scale all timestamps by 1/speed
    for w in words:
        w["start"] /= speed
        w["end"] /= speed

    # Rewrite SRT with scaled timestamps
    from modules.tts_engine import _build_word_srt
    srt_content = _build_word_srt(words)
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)
    logger.info(f"SRT: {len(words)} palabras (timestamps escalados x{speed})")

    title_end = _compute_title_end(title, words, short_num)

    ass_path = os.path.join(temp_dir, f"{stem}_subs.ass")
    short_config = {**config, "subtitles": SHORT_SUB_CONFIG}
    vtt_to_ass(srt_path, ass_path, short_config, skip_until=title_end)

    # 5. Title card + blur background (vertical 1080x1920)
    title_card_path = os.path.join(temp_dir, f"{stem}_titlecard.png")
    _generate_vertical_title_card(title, title_card_path, config)

    # 5b. Get tint color for intro (golden angle rotation)
    tint_color = _get_next_tint()

    # 6. Pre-mix woosh
    mixed_audio = os.path.join(temp_dir, f"{stem}_audio_mixed.mp3")
    final_audio = _premix_woosh_short(audio_path, mixed_audio, settle_time=SETTLE_TIME)

    # 7. Compose short
    output_path = os.path.join(output_dir, f"{stem}.mp4")
    _compose_short(gameplay_path, final_audio, ass_path, output_path,
                   title_card_path, title_end, speed, tint_color=tint_color, offset=offset)

    # 8. Save title
    title_path = os.path.join(output_dir, f"{stem}_title.txt")
    with open(title_path, "w", encoding="utf-8") as f:
        f.write(title)

    logger.info(f"=== Short #{short_num} completado ===\n")
    return title
    return output_path


def _generate_vertical_title_card(title, output_path, config):
    """Generate a vertical (1080x1920) title card for short intro."""
    from PIL import Image, ImageDraw, ImageFont
    from modules.thumbnail_generator import _find_font, _wrap_text

    template_path = config.get("paths", {}).get("thumbnail_template", "./assets/3.png")
    if not os.path.isfile(template_path):
        return

    # Load template and scale to vertical
    template = Image.open(template_path).convert("RGBA")
    # Scale template to fit 1080 width, maintain aspect ratio
    t_w, t_h = template.size
    scale = 1080 / t_w
    new_h = int(t_h * scale)
    template = template.resize((1080, new_h), Image.LANCZOS)

    # Create vertical canvas
    card = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    # Center template vertically
    y_offset = (1920 - new_h) // 2
    card.paste(template, (0, y_offset), template)

    # Draw title
    draw = ImageDraw.Draw(card)
    text_left = int(80 * scale)
    text_right = int(1200 * scale)
    text_top = y_offset + int(250 * scale)
    text_bottom = y_offset + int(530 * scale)
    max_width = text_right - text_left
    available_height = text_bottom - text_top

    font_path = _find_font()
    if not font_path:
        return

    title_upper = title.upper()
    best_size = 30
    for try_size in range(70, 20, -2):
        font = ImageFont.truetype(font_path, try_size)
        lines = _wrap_text(title_upper, font, max_width, draw)
        if len(lines) * try_size * 1.3 <= available_height:
            best_size = try_size
            break

    font = ImageFont.truetype(font_path, best_size)
    lines = _wrap_text(title_upper, font, max_width, draw)
    total_h = len(lines) * best_size * 1.3
    y_start = text_top + (available_height - total_h) / 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        lw = bbox[2] - bbox[0]
        x = text_left + (max_width - lw) / 2
        y = y_start + i * best_size * 1.3
        draw.text((x, y), line, font=font, fill=(0, 0, 0))

    card.save(output_path, "PNG")
    logger.info(f"Title card vertical guardado")
