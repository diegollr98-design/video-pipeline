"""
video_cleaner.py — Detecta y elimina segmentos no-gameplay de grabaciones de Minecraft.

Analiza frames a 1fps buscando la hotbar de Minecraft (barra de inventario inferior).
Si la hotbar está presente → gameplay. Si no → pausa, escritorio, menú, etc.

Flujo: input.mp4 → extraer frames → detectar hotbar → segmentos gameplay → concat → output.mp4
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image
import numpy as np

from modules.utils import _find_exe

logger = logging.getLogger(__name__)

# --- Hotbar detection constants ---
# The Minecraft hotbar is at the bottom-center of the screen.
# It's a row of 9 slots with dark gray background (~RGB 70-110).
# We analyze the bottom ~6% of the frame, center ~45% width.

HOTBAR_BOTTOM_RATIO = 0.06      # bottom 6% of frame height
HOTBAR_CENTER_WIDTH_RATIO = 0.45  # center 45% of frame width
HOTBAR_GRAY_LOW = (50, 50, 50)
HOTBAR_GRAY_HIGH = (130, 130, 130)
HOTBAR_GRAY_MIN_RATIO = 0.15    # at least 15% of the region should be hotbar-gray
HOTBAR_EDGE_THRESHOLD = 15      # minimum edge density for slot structure


def _extract_frames(video_path, frames_dir, fps=1):
    """Extract frames from video at given fps using FFmpeg."""
    os.makedirs(frames_dir, exist_ok=True)
    ffmpeg = _find_exe("ffmpeg")
    cmd = [
        ffmpeg, "-i", video_path,
        "-vf", f"fps={fps}",
        "-q:v", "3",
        os.path.join(frames_dir, "frame_%06d.jpg"),
        "-y",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg frame extraction failed: {result.stderr[:500]}")

    frames = sorted(Path(frames_dir).glob("frame_*.jpg"))
    logger.info(f"Extraídos {len(frames)} frames a {fps}fps")
    return frames


def _has_hotbar(frame_path):
    """
    Detect if a frame contains the Minecraft hotbar.

    Strategy:
    1. Crop the bottom-center region where the hotbar lives.
    2. Check if enough pixels are in the dark-gray range typical of hotbar slots.
    3. Check for horizontal edge structure (slot borders create edges).

    Returns True if hotbar is detected (= gameplay), False otherwise.
    """
    img = Image.open(frame_path)
    w, h = img.size

    # Crop hotbar region: bottom 6%, center 45%
    hotbar_h = int(h * HOTBAR_BOTTOM_RATIO)
    hotbar_w = int(w * HOTBAR_CENTER_WIDTH_RATIO)
    left = (w - hotbar_w) // 2
    top = h - hotbar_h

    crop = img.crop((left, top, left + hotbar_w, h))
    pixels = np.array(crop)

    # Check 1: Gray pixel ratio
    # Hotbar slots are dark gray. Count pixels in the gray range.
    in_range = (
        (pixels[:, :, 0] >= HOTBAR_GRAY_LOW[0]) & (pixels[:, :, 0] <= HOTBAR_GRAY_HIGH[0]) &
        (pixels[:, :, 1] >= HOTBAR_GRAY_LOW[1]) & (pixels[:, :, 1] <= HOTBAR_GRAY_HIGH[1]) &
        (pixels[:, :, 2] >= HOTBAR_GRAY_LOW[2]) & (pixels[:, :, 2] <= HOTBAR_GRAY_HIGH[2])
    )
    gray_ratio = in_range.sum() / in_range.size

    if gray_ratio < HOTBAR_GRAY_MIN_RATIO:
        return False

    # Check 2: Horizontal edge structure (slot borders)
    # Convert to grayscale and compute horizontal gradient
    gray = np.mean(pixels, axis=2)
    h_diff = np.abs(np.diff(gray, axis=1))
    edge_ratio = (h_diff > HOTBAR_EDGE_THRESHOLD).sum() / h_diff.size

    # Hotbar has distinct slot borders → edge ratio should be noticeable
    return edge_ratio > 0.02


def _find_gameplay_segments(frames, fps=0.1, min_gap_seconds=30, min_segment_seconds=20):
    """
    Analyze frames and return list of (start_sec, end_sec) gameplay segments.

    Args:
        frames: sorted list of frame paths
        fps: frames per second used during extraction
        min_gap_seconds: ignore non-gameplay gaps shorter than this (smoothing)
        min_segment_seconds: discard gameplay segments shorter than this
    """
    is_gameplay = []

    for i, frame_path in enumerate(frames):
        try:
            result = _has_hotbar(frame_path)
        except Exception as e:
            logger.warning(f"Error analizando frame {i}: {e}")
            result = False
        is_gameplay.append(result)

        if (i + 1) % 60 == 0:
            logger.info(f"Analizados {i + 1}/{len(frames)} frames...")

    logger.info(f"Frames gameplay: {sum(is_gameplay)}/{len(is_gameplay)}")

    # Smooth: fill small gaps (non-gameplay surrounded by gameplay)
    smoothed = list(is_gameplay)
    for i in range(len(smoothed)):
        if not smoothed[i]:
            # Look ahead to see if this gap is short
            gap_start = i
            while i < len(smoothed) and not smoothed[i]:
                i += 1
            gap_length = i - gap_start
            if gap_length <= min_gap_seconds * fps and gap_start > 0 and i < len(smoothed):
                for j in range(gap_start, i):
                    smoothed[j] = True

    # Build segments
    segments = []
    in_segment = False
    start = 0

    for i, gp in enumerate(smoothed):
        if gp and not in_segment:
            start = i
            in_segment = True
        elif not gp and in_segment:
            end = i
            duration = (end - start) / fps
            if duration >= min_segment_seconds:
                segments.append((start / fps, end / fps))
            in_segment = False

    # Close last segment
    if in_segment:
        end = len(smoothed)
        duration = (end - start) / fps
        if duration >= min_segment_seconds:
            segments.append((start / fps, end / fps))

    logger.info(f"Encontrados {len(segments)} segmentos de gameplay")
    for i, (s, e) in enumerate(segments):
        logger.info(f"  Segmento {i+1}: {s:.0f}s - {e:.0f}s ({e-s:.0f}s)")

    return segments


def _concat_segments(video_path, segments, output_path):
    """Use FFmpeg to extract and concatenate gameplay segments."""
    ffmpeg = _find_exe("ffmpeg")
    temp_dir = os.path.dirname(output_path)
    concat_file = os.path.join(temp_dir, "concat_list.txt")
    part_files = []

    # Extract each segment
    for i, (start, end) in enumerate(segments):
        part_path = os.path.join(temp_dir, f"segment_{i:03d}.mp4")
        cmd = [
            ffmpeg, "-ss", str(start), "-to", str(end),
            "-i", video_path,
            "-c", "copy", "-avoid_negative_ts", "make_zero",
            "-y", part_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            # Antes se añadía igualmente a la lista y el concat fallaba después
            # con un error incomprensible. Mejor saltarlo y decirlo.
            logger.warning(f"Error extrayendo segmento {i}, se omite: {result.stderr[-200:]}")
            continue
        part_files.append(part_path)

    if not part_files:
        raise RuntimeError("Ningún segmento de gameplay pudo extraerse")

    # Write concat file.
    # CRÍTICO: rutas ABSOLUTAS. El demuxer concat resuelve las rutas relativas
    # respecto al directorio del PROPIO fichero de lista, no respecto al cwd,
    # así que './temp/segment_000.mp4' dentro de './temp/concat_list.txt' se
    # resolvía como './temp/./temp/segment_000.mp4' y fallaba siempre. Con el
    # `temp_dir: "./temp"` de config.yaml esto no funcionó nunca: solo se
    # salvaban los videos >95% gameplay, que toman el atajo de recorte simple.
    with open(concat_file, "w", encoding="utf-8") as f:
        for p in part_files:
            safe_path = os.path.abspath(p).replace("\\", "/")
            f.write(f"file '{safe_path}'\n")

    # Concatenate
    cmd = [
        ffmpeg, "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c", "copy", "-y", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # El final de stderr, no el principio: los primeros 500 caracteres son
        # el banner de FFmpeg y el error real quedaba fuera del log.
        raise RuntimeError(f"FFmpeg concat failed: ...{result.stderr[-500:]}")

    # Cleanup parts
    for p in part_files:
        os.remove(p)
    os.remove(concat_file)

    logger.info(f"Gameplay limpio guardado en {output_path}")


def clean_gameplay(video_path, output_path, config):
    """
    Main entry point: detect and remove non-gameplay segments.

    Returns the path to the cleaned video, or the original if no cleaning needed.
    """
    temp_dir = config["paths"]["temp_dir"]
    frames_dir = os.path.join(temp_dir, "frames_analysis")

    try:
        # Step 1: Extract frames at 0.1fps (1 frame every 10 seconds)
        logger.info("Extrayendo frames para análisis (1 cada 10s)...")
        frames = _extract_frames(video_path, frames_dir, fps=0.1)

        if not frames:
            logger.warning("No se pudieron extraer frames, usando video original")
            return video_path

        # Step 2: Detect gameplay segments (fps=0.1 → 1 frame per 10 seconds)
        logger.info("Detectando segmentos de gameplay...")
        segments = _find_gameplay_segments(frames, fps=0.1)

        if not segments:
            logger.warning("No se detectó gameplay, usando video original")
            return video_path

        # Always trim first 5s and last 5s to remove pause menus
        # that fall between frame samples (10s resolution)
        from modules.utils import get_video_duration as _get_dur
        total_dur = _get_dur(video_path)
        trimmed = []
        for s, e in segments:
            s = max(s, 5)          # skip first 5 seconds
            e = min(e, total_dur - 5)  # skip last 5 seconds
            if e > s:
                trimmed.append((s, e))
        segments = trimmed

        if not segments:
            logger.warning("No quedan segmentos tras recorte, usando video original")
            return video_path

        # Check if cleaning is actually needed
        total_frames = len(frames)
        gameplay_seconds = sum(e - s for s, e in segments)
        ratio = gameplay_seconds / total_dur if total_dur > 0 else 1

        if ratio > 0.95:
            logger.info(f"Video es {ratio:.0%} gameplay, recortando inicio/final")
            # Simple trim with -ss/-to (no concat needed for single segment)
            if len(segments) == 1:
                s, e = segments[0]
                ffmpeg = _find_exe("ffmpeg")
                cmd = [
                    ffmpeg, "-ss", str(s), "-to", str(e),
                    "-i", video_path,
                    "-c", "copy", "-avoid_negative_ts", "make_zero",
                    "-y", output_path,
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    logger.warning("Trim failed, using original")
                    return video_path
                return output_path
            else:
                _concat_segments(video_path, segments, output_path)
                return output_path

        logger.info(f"Video es {ratio:.0%} gameplay, limpiando...")

        # Step 3: Concatenate gameplay segments
        _concat_segments(video_path, segments, output_path)

        return output_path

    finally:
        # Cleanup frames
        if os.path.exists(frames_dir):
            shutil.rmtree(frames_dir)
