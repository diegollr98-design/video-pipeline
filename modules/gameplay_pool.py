"""
gameplay_pool.py — Gestiona una cola de segmentos de gameplay limpio.

- Recibe gameplays limpios (sin pausa/escritorio) y los almacena en pool/
- Cuando hay suficiente material (>= target_duration_min), genera chunks de 20-30 min
- Si un gameplay es demasiado largo, lo corta y guarda el sobrante
- Si es demasiado corto, lo guarda hasta que haya suficiente

Pool dir contiene archivos .mp4 numerados cronológicamente.
"""

import logging
import os
import glob
import shutil
import subprocess
import time

from modules.utils import _find_exe, get_video_duration

logger = logging.getLogger(__name__)


def _next_pool_name(pool_dir):
    """Generate next sequential filename for pool."""
    existing = glob.glob(os.path.join(pool_dir, "pool_*.mp4"))
    if not existing:
        return os.path.join(pool_dir, "pool_0001.mp4")
    nums = []
    for f in existing:
        base = os.path.splitext(os.path.basename(f))[0]
        try:
            nums.append(int(base.split("_")[1]))
        except (IndexError, ValueError):
            pass
    next_num = max(nums) + 1 if nums else 1
    return os.path.join(pool_dir, f"pool_{next_num:04d}.mp4")


def devolver_al_pool(chunk_path, config):
    """Devuelve al pool un chunk cuya producción falló. [CHUNK-01]

    `take_chunk` saca el material del pool ANTES de que se genere la historia,
    así que cualquier fallo aguas abajo (el proveedor del modelo caído, un TTS
    que revienta, una composición que falla) destruía una ingesta entera. El
    chunk ya está en el formato del pool: devolverlo es un `move`, no un
    reprocesado, y la siguiente corrida lo retoma como si nada.

    Se le da un nombre NUEVO en vez de reutilizar el suyo para no pisar un
    `pool_XXXX.mp4` que exista (el sobrante de un `take_chunk` que sí partió el
    fichero vive ahí con esa misma numeración).

    Devuelve la ruta destino. Propaga si no puede: perder el chunk en silencio
    es exactamente lo que esta función viene a evitar.
    """
    pool_dir = config["paths"]["pool_dir"]
    os.makedirs(pool_dir, exist_ok=True)
    destino = _next_pool_name(pool_dir)
    shutil.move(chunk_path, destino)
    logger.info(f"Chunk devuelto al pool: {os.path.basename(destino)}")
    return destino


def _split_video(video_path, split_at_seconds, part1_path, part2_path):
    """Split a video at a given timestamp into two parts."""
    ffmpeg = _find_exe("ffmpeg")

    # Part 1: start to split point
    cmd1 = [
        ffmpeg, "-i", video_path,
        "-t", str(split_at_seconds),
        "-c", "copy", "-avoid_negative_ts", "make_zero",
        "-y", part1_path,
    ]
    r1 = subprocess.run(cmd1, capture_output=True, text=True)
    if r1.returncode != 0:
        raise RuntimeError(f"Error splitting part 1: {r1.stderr[-500:]}")

    # Part 2: split point to end
    cmd2 = [
        ffmpeg, "-ss", str(split_at_seconds),
        "-i", video_path,
        "-c", "copy", "-avoid_negative_ts", "make_zero",
        "-y", part2_path,
    ]
    r2 = subprocess.run(cmd2, capture_output=True, text=True)
    if r2.returncode != 0:
        raise RuntimeError(f"Error splitting part 2: {r2.stderr[-500:]}")


def _concat_videos(video_paths, output_path):
    """Concatenate multiple videos into one."""
    ffmpeg = _find_exe("ffmpeg")
    temp_dir = os.path.dirname(output_path)
    concat_file = os.path.join(temp_dir, f"concat_{int(time.time())}.txt")

    # Rutas ABSOLUTAS: el demuxer concat resuelve las relativas respecto al
    # directorio del PROPIO fichero de lista, no respecto al cwd. Con el pool en
    # './pool' y la lista en './temp', 'file ./pool/x.mp4' se resolvía como
    # './temp/./pool/x.mp4' y fallaba siempre. Es el gemelo del bug ya arreglado
    # en video_cleaner._concat_segments; aquí seguía vivo y solo se dispara con
    # 2+ ficheros en el pool, que es el caso normal en producción real.
    with open(concat_file, "w", encoding="utf-8") as f:
        for p in video_paths:
            safe = os.path.abspath(p).replace("\\", "/")
            f.write(f"file '{safe}'\n")

    cmd = [
        ffmpeg, "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c", "copy", "-y", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    os.remove(concat_file)

    if result.returncode != 0:
        raise RuntimeError(f"Error concatenating: {result.stderr[-500:]}")


def add_to_pool(video_path, config, is_original=False):
    """Add a gameplay video to the pool, re-encoding to reduce filesize.

    Re-encodes with CRF 23 + medium preset -> typically 5-10x smaller
    with no visible quality loss for gameplay footage.
    """
    pool_dir = config["paths"]["pool_dir"]
    os.makedirs(pool_dir, exist_ok=True)

    dest = _next_pool_name(pool_dir)
    ffmpeg = _find_exe("ffmpeg")

    # Re-encode to reduce size (13GB -> ~2-3GB typically)
    codec = config.get("video", {}).get("output_codec", "libx264")
    crf = config.get("video", {}).get("crf", 23)
    preset = config.get("video", {}).get("preset", "medium")
    is_nvenc = "nvenc" in codec

    if is_nvenc:
        quality_args = ["-c:v", codec, "-cq", str(crf), "-preset", preset]
        logger.info(f"Recodificando para pool (GPU {codec}, CQ {crf})...")
    else:
        quality_args = ["-c:v", codec, "-crf", str(crf), "-preset", preset]
        logger.info(f"Recodificando para pool (CPU {codec}, CRF {crf}, {preset})...")

    cmd = [
        ffmpeg, "-threads", "4",
        "-i", video_path,
        *quality_args,
        "-c:a", "aac", "-b:a", "128k",
        "-y", dest,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Error re-encoding to pool: {result.stderr[-500:]}")

    duration = get_video_duration(dest)
    src_size = os.path.getsize(video_path) / (1024 * 1024)
    dst_size = os.path.getsize(dest) / (1024 * 1024)
    logger.info(f"Pool: {os.path.basename(dest)} ({duration:.0f}s / {duration/60:.1f} min) — {src_size:.0f}MB -> {dst_size:.0f}MB")
    return dest


def get_pool_status(config):
    """Return list of (path, duration) for all pool files, sorted by name."""
    pool_dir = config["paths"]["pool_dir"]
    if not os.path.isdir(pool_dir):
        return []

    files = sorted(glob.glob(os.path.join(pool_dir, "pool_*.mp4")))
    status = []
    for f in files:
        try:
            dur = get_video_duration(f)
            status.append((f, dur))
        except Exception as e:
            logger.warning(f"Error leyendo duración de {f}: {e}")
    return status


# Ruta falsa que se devuelve en dry-run. NO existe en disco a propósito: el
# `finally` de `main.py` hace `os.remove` sobre el chunk, y así ese borrado no
# encuentra nada que borrar. Se ve en los logs, que es justo lo que se quiere.
DRY_RUN_CHUNK = "<dry-run: el pool NO se ha consumido>"


def take_chunk(config, dry_run=False):
    """
    Take a chunk of gameplay from the pool for one video.

    Returns (chunk_path, duration) if enough material, or (None, 0) if not.

    [DRYRUN-01] Con `dry_run=True` calcula la MISMA duración pero **sin tocar el
    disco**: ni parte ficheros, ni mueve el sobrante, ni borra nada del pool, y
    devuelve `DRY_RUN_CHUNK` como ruta. Esto existe porque `--dry-run` está
    documentado como "solo genera historia sin video" y en realidad **consumía y
    borraba el pool** (los `os.remove` de más abajo), destruyendo horas de
    grabación sin producir ni un vídeo. El pool no se recupera.

    Logic:
    - < 20 min in pool: wait for more gameplay
    - 20-39 min: use it all as one video (don't waste time splitting)
    - >= 40 min: take a 30-min chunk, save the rest
    """
    pool_status = get_pool_status(config)
    if not pool_status:
        return None, 0

    target_min = config["story"]["target_duration_min"]    # 20 min
    target_max = config["story"]["target_duration_max"]    # 40 min
    chunk_size = config["story"].get("chunk_size", 1800)   # 30 min
    temp_dir = config["paths"]["temp_dir"]
    os.makedirs(temp_dir, exist_ok=True)

    total_duration = sum(d for _, d in pool_status)
    if total_duration < target_min:
        logger.info(f"Pool tiene {total_duration:.0f}s, necesita {target_min}s. Esperando mas gameplay.")
        return None, 0

    # Select files for this chunk
    selected = []
    accumulated = 0
    files_to_remove = []

    for path, dur in pool_status:
        if accumulated + dur <= target_max:
            # Use entire file — don't split if total stays under 40 min
            selected.append(path)
            accumulated += dur
            files_to_remove.append(path)
        else:
            # Adding this file would exceed 40 min — split at chunk_size (30 min)
            needed = chunk_size - accumulated
            if needed < 30:
                break

            if dry_run:
                # Misma aritmética, cero efectos: no se parte el fichero ni se
                # mueve el sobrante al pool.
                accumulated += needed
                break

            part1 = os.path.join(temp_dir, "chunk_part.mp4")
            part2 = os.path.join(temp_dir, "chunk_remainder.mp4")

            _split_video(path, needed, part1, part2)

            selected.append(part1)
            accumulated += needed
            files_to_remove.append(path)

            # Move remainder to pool
            final_remainder = _next_pool_name(config["paths"]["pool_dir"])
            os.replace(part2, final_remainder)
            logger.info(f"Sobrante guardado en pool: {os.path.basename(final_remainder)} ({dur - needed:.0f}s)")
            break

        # Con material de sobra NO se corta aquí: quien decide es la siguiente
        # vuelta, que o mete el fichero entero (si cabe bajo target_max) o parte
        # en chunk_size. El bloque que había aquí calculaba `remaining_pool` y
        # terminaba en un `pass`: no hacía nada.

    if accumulated < target_min:
        logger.info(f"No hay suficiente gameplay seleccionable ({accumulated:.0f}s < {target_min}s)")
        return None, 0

    if dry_run:
        # Se sale ANTES de concatenar y, sobre todo, antes de los `os.remove`
        # del pool que hay al final de esta función.
        logger.info(
            f"dry-run: se usarian {accumulated:.0f}s ({accumulated/60:.1f} min) de "
            f"{len(selected)} fichero(s). El pool NO se toca."
        )
        return DRY_RUN_CHUNK, accumulated

    # Concatenate selected files into one chunk
    chunk_id = int(time.time())
    chunk_path = os.path.join(temp_dir, f"chunk_{chunk_id}.mp4")

    if len(selected) == 1:
        # Just copy/rename, no need to concat
        os.rename(selected[0], chunk_path) if selected[0].startswith(temp_dir) else \
            subprocess.run([_find_exe("ffmpeg"), "-i", selected[0], "-c", "copy", "-y", chunk_path],
                           capture_output=True)
    else:
        _concat_videos(selected, chunk_path)
        # Clean up temp part files
        for s in selected:
            if s.startswith(temp_dir) and os.path.exists(s):
                os.remove(s)

    # Remove used files from pool
    for f in files_to_remove:
        if os.path.exists(f):
            os.remove(f)
            logger.info(f"Removido del pool: {os.path.basename(f)}")

    final_dur = get_video_duration(chunk_path)
    logger.info(f"Chunk generado: {final_dur:.0f}s ({final_dur/60:.1f} min)")
    return chunk_path, final_dur
