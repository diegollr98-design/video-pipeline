"""
thumbnail_generator.py — Genera miniaturas para YouTube.

1. Toma un frame del gameplay
2. Aplica blur de fondo
3. Superpone la plantilla PNG
4. Escribe el título del video en la zona central
"""

import logging
import os
import subprocess

import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from modules.utils import _find_exe

logger = logging.getLogger(__name__)

# Text area within the template (relative to 1280x720)
TEXT_LEFT = 80
TEXT_TOP = 250
TEXT_RIGHT = 1200
TEXT_BOTTOM = 530
TEXT_COLOR = (0, 0, 0)  # black

# Tint rotation state file — persists between runs
_TINT_STATE_FILE = "./assets/.tint_index"
_GOLDEN_ANGLE = 137.508  # degrees — maximally separates consecutive hues


def _get_next_tint():
    """Get the next tint color using golden angle rotation through the hue wheel.

    Golden angle ensures each consecutive color is maximally different from
    all previous ones. Never repeats pattern even after dozens of thumbnails.
    """
    import colorsys

    # Read current index
    index = 0
    if os.path.isfile(_TINT_STATE_FILE):
        try:
            index = int(open(_TINT_STATE_FILE).read().strip())
        except (ValueError, OSError):
            index = 0

    # Golden angle rotation: hue = (index * 137.508) mod 360
    hue = (index * _GOLDEN_ANGLE) % 360
    # High saturation + medium value for vibrant colors
    saturation = 0.85 + random.uniform(-0.05, 0.05)
    value = 0.90 + random.uniform(-0.05, 0.05)

    r, g, b = colorsys.hsv_to_rgb(hue / 360, saturation, value)
    color = (int(r * 255), int(g * 255), int(b * 255))

    # Save next index
    index += 1
    os.makedirs(os.path.dirname(_TINT_STATE_FILE), exist_ok=True)
    with open(_TINT_STATE_FILE, "w") as f:
        f.write(str(index))

    logger.info(f"Tint #{index}: hue={hue:.0f} -> RGB{color}")
    return color


def _extract_frame(video_path, output_path, timestamp=30):
    """Extract a single frame from video at given timestamp."""
    ffmpeg = _find_exe("ffmpeg")
    cmd = [
        ffmpeg, "-ss", str(timestamp),
        "-i", video_path,
        "-frames:v", "1", "-q:v", "2",
        "-y", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Error extracting frame: {result.stderr[:200]}")


def _find_font(preferred_fonts=None):
    """Find a bold font on the system."""
    if preferred_fonts is None:
        preferred_fonts = [
            "arialbd.ttf",      # Arial Bold — legible y limpia
            "Arial Black",
            "ariblk.ttf",
        ]

    # Windows font directories
    font_dirs = [
        os.path.expandvars(r"%WINDIR%\Fonts"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts"),
    ]

    for font_name in preferred_fonts:
        # Try as full path first
        if os.path.isfile(font_name):
            return font_name
        # Search in font dirs
        for d in font_dirs:
            for ext in ["", ".ttf", ".otf"]:
                path = os.path.join(d, font_name + ext)
                if os.path.isfile(path):
                    return path

    return None


def _wrap_text(text, font, max_width, draw):
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test_line, font=font)
        width = bbox[2] - bbox[0]

        if width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines


def generate_thumbnail(video_path, title, output_path, config):
    """Generate a YouTube thumbnail.

    Args:
        video_path: gameplay video to extract frame from
        title: video title to write on thumbnail
        output_path: where to save the thumbnail (JPG)
        config: pipeline config
    """
    template_path = config.get("paths", {}).get(
        "thumbnail_template", "./assets/3.png"
    )

    if not os.path.isfile(template_path):
        logger.warning(f"Template no encontrado: {template_path}, saltando thumbnail")
        return

    temp_dir = config["paths"]["temp_dir"]
    os.makedirs(temp_dir, exist_ok=True)
    frame_path = os.path.join(temp_dir, "thumb_frame.jpg")

    # 1. Extract a frame from gameplay (at 30 seconds to avoid menus)
    logger.info("Extrayendo frame para miniatura...")
    _extract_frame(video_path, frame_path, timestamp=30)

    # 2. Load, blur, and add vibrant color tint
    background = Image.open(frame_path).convert("RGB")
    background = background.resize((1280, 720), Image.LANCZOS)
    background = background.filter(ImageFilter.GaussianBlur(radius=20))

    # Boost saturation
    background = ImageEnhance.Color(background).enhance(2.5)
    background = ImageEnhance.Brightness(background).enhance(0.8)

    # Vibrant color tint — cycles through distinct hues, never repeats consecutively
    tint_color = _get_next_tint()
    tint_layer = Image.new("RGB", (1280, 720), tint_color)
    background = Image.blend(background, tint_layer, 0.35)

    # 3. Load and overlay the template
    template = Image.open(template_path).convert("RGBA")
    template = template.resize((1280, 720), Image.LANCZOS)
    background.paste(template, (0, 0), template)

    # 4. Draw the title text
    draw = ImageDraw.Draw(background)
    max_width = TEXT_RIGHT - TEXT_LEFT
    available_height = TEXT_BOTTOM - TEXT_TOP

    # Find font and size that fits
    font_path = _find_font()
    if not font_path:
        logger.warning("No se encontró fuente bold, usando default")
        font = ImageFont.load_default()
    else:
        # Start with large font, reduce until text fits
        title_upper = title.upper()

        # Auto-size: find the largest font that fits the area
        # Try from large to small, pick the one that fills ~70-90% of available height
        best_font_size = 30
        for try_size in range(80, 20, -2):
            font = ImageFont.truetype(font_path, try_size)
            lines = _wrap_text(title_upper, font, max_width, draw)
            line_height = try_size * 1.3
            total_height = len(lines) * line_height

            if total_height <= available_height:
                best_font_size = try_size
                break

        font_size = best_font_size
        font = ImageFont.truetype(font_path, font_size)

    # Draw centered text
    lines = _wrap_text(title_upper, font, max_width, draw)
    line_height = font_size * 1.3
    total_height = len(lines) * line_height
    y_start = TEXT_TOP + (available_height - total_height) / 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        line_width = bbox[2] - bbox[0]
        x = TEXT_LEFT + (max_width - line_width) / 2
        y = y_start + i * line_height

        draw.text((x, y), line, font=font, fill=TEXT_COLOR)

    # 5. Save
    background.save(output_path, "JPEG", quality=95)
    logger.info(f"Miniatura guardada en {output_path}")

    # Cleanup
    if os.path.exists(frame_path):
        os.remove(frame_path)


def generate_title_card(title, output_path, config):
    """Generate a transparent PNG with template + title (no background).

    Used for the intro overlay animation in the video.
    """
    template_path = config.get("paths", {}).get(
        "thumbnail_template", "./assets/3.png"
    )

    if not os.path.isfile(template_path):
        logger.warning(f"Template no encontrado: {template_path}")
        return

    # Load template (RGBA with transparency)
    card = Image.open(template_path).convert("RGBA")
    card = card.resize((1280, 720), Image.LANCZOS)

    # Draw title text on it
    draw = ImageDraw.Draw(card)
    max_width = TEXT_RIGHT - TEXT_LEFT
    available_height = TEXT_BOTTOM - TEXT_TOP

    font_path = _find_font()
    if not font_path:
        return

    title_upper = title.upper()

    # Auto-size font
    best_font_size = 30
    for try_size in range(80, 20, -2):
        font = ImageFont.truetype(font_path, try_size)
        lines = _wrap_text(title_upper, font, max_width, draw)
        line_height = try_size * 1.3
        total_height = len(lines) * line_height
        if total_height <= available_height:
            best_font_size = try_size
            break

    font_size = best_font_size
    font = ImageFont.truetype(font_path, font_size)

    lines = _wrap_text(title_upper, font, max_width, draw)
    line_height = font_size * 1.3
    total_height = len(lines) * line_height
    y_start = TEXT_TOP + (available_height - total_height) / 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        line_width = bbox[2] - bbox[0]
        x = TEXT_LEFT + (max_width - line_width) / 2
        y = y_start + i * line_height
        draw.text((x, y), line, font=font, fill=TEXT_COLOR)

    card.save(output_path, "PNG")
    logger.info(f"Title card guardado en {output_path}")
