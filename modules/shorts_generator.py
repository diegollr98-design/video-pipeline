"""
shorts_generator.py — Genera YouTube Shorts / TikToks desde gameplay.

Formato 9:16, ~60-90s, velocidad x1.5, subtítulos adaptados, intro animada.
"""

import logging
import os
import re
import subprocess

from modules.utils import _find_exe, load_config, get_video_duration
from modules.script_generator import (
    _call_openrouter, _parse_title_and_speech, _ensure_title_at_start, _validar_salida,
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
    lineas = "\n".join(f"  {i}. {t}" for i, t in enumerate(avoid[-40:], 1))
    return f"""

PROHIBIDO REPETIR. Ya has escrito estas historias en esta misma tanda:
{lineas}

La tuya debe ser CLARAMENTE distinta de todas ellas: otro parentesco (si arriba
sale un hermano, usa suegra, jefe, vecina, cuñado, socio...), otro objeto o bien
en disputa, otro escenario y otro tipo de desenlace. No basta con cambiar el
final ni con cambiar el sexo del culpable: cambia el CONFLICTO entero."""


# Cuántos títulos seguidos con la MISMA palabra inicial se toleran antes de
# exigir otra apertura. Medido sobre los 50 títulos de la primera tanda real:
# 50/50 empezaban por "Mi", 33/50 con "vendió"/"robó". Los títulos eran distintos
# entre sí (Jaccard máx 0,210, 24 parentescos), pero la PLANTILLA era una sola, y
# una pared de 50 miniaturas que empiezan igual lee como granja de contenido. En
# el corpus de competencia escaneado el ratio de primera persona era 0% en un
# competidor real de 124k subs y 25% en el líder, frente al 75% de la granja de
# drama doblado. No se prohíbe la primera persona (es el formato del nicho): solo
# se corta la racha.
RACHA_MAX_APERTURA = 5


def _apertura(titulo):
    palabras = titulo.strip().split()
    return palabras[0].lower().strip('¿¡"\'') if palabras else ""


def _apertura_agotada(avoid):
    """True si los últimos títulos empiezan TODOS por la misma palabra."""
    if not avoid or len(avoid) < RACHA_MAX_APERTURA:
        return None
    ultimas = [_apertura(t) for t in avoid[-RACHA_MAX_APERTURA:]]
    return ultimas[0] if ultimas[0] and len(set(ultimas)) == 1 else None


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
        prompt += (
            f"\n\nAPERTURA OBLIGATORIAMENTE DISTINTA: los {RACHA_MAX_APERTURA} últimos "
            f"títulos empiezan por «{racha}». El tuyo NO puede empezar por esa palabra. "
            f"Empieza por otra cosa — el hecho, el momento o el lugar: «Descubrí que...», "
            f"«El día que...», «Cuando...», «Me echaron de...», «Nadie sabía que...». "
            f"La historia sigue siendo en primera persona; lo que cambia es por dónde "
            f"empieza el título."
        )

    # Mismo guardia que en las historias largas: nemotron suelta a veces su
    # razonamiento y acababa como título del short, con un vídeo de 4,5s.
    intentos = max(1, int(config.get("openrouter", {}).get("max_retries", 3)))
    for intento in range(intentos):
        mensaje = prompt
        if intento:
            mensaje = (
                "TU RESPUESTA ANTERIOR NO SIRVIÓ: escribiste tu razonamiento en vez de la "
                "historia. Empieza directamente por el TÍTULO en español, sin ningún texto "
                "previo.\n\n"
            ) + prompt

        raw = _call_openrouter([{"role": "user", "content": mensaje}], config)
        title, speech = _parse_title_and_speech(raw)
        ok, motivo = _validar_salida(title, speech, min_palabras_titulo=8,
                                     min_palabras_speech=80)
        # La apertura se PIDE en el prompt y se IMPONE aquí. Pedirla no basta:
        # es la cuarta vez en este repo que una garantía en prosa no se cumple
        # (comas, título, variedad de shorts). El último intento se acepta igual
        # —un título repetitivo es mucho menos grave que quedarse sin short—.
        if ok and racha and _apertura(title) == racha and intento < intentos - 1:
            ok, motivo = False, f"vuelve a empezar por «{racha}» (racha de {RACHA_MAX_APERTURA})"
        if ok:
            break
        logger.warning(f"Short descartado ({motivo}); reintento {intento + 2}/{intentos}")
    else:
        raise RuntimeError(
            f"El modelo no devolvió un short utilizable tras {intentos} intentos. "
            f"Último motivo: {motivo}"
        )

    speech = _ensure_title_at_start(title, speech)

    # Truncate if too long
    words = speech.split()
    if len(words) > 280:
        # Truncate at last sentence before limit
        text = " ".join(words[:280])
        last_period = max(text.rfind("."), text.rfind("!"), text.rfind("?"))
        if last_period > 0:
            speech = text[:last_period + 1]

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


def _premix_woosh_short(audio_path, output_path):
    """Mix woosh into short audio."""
    ffmpeg = _find_exe("ffmpeg")
    if not os.path.isfile(WOOSH_PATH):
        return audio_path

    cmd = [
        ffmpeg,
        "-i", audio_path,
        "-i", WOOSH_PATH,
        "-filter_complex",
        (
            "[0:a]aformat=sample_fmts=fltp:sample_rates=24000:channel_layouts=mono[tts];"
            "[1:a]adelay=0|0,volume=0.4,"
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
        settle_time = 0.25
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

    # Calculate title end
    title_clean = re.sub(r'[.!?,;:\-\"\'\u2026]', '', title.lower()).split()
    title_wc = len(title_clean)
    title_end = words[min(title_wc - 1, len(words) - 1)]["end"] if words else 4.0

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
    final_audio = _premix_woosh_short(audio_path, mixed_audio)

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
