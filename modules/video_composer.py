import logging
import math
import os
import subprocess

from modules.utils import _find_exe

logger = logging.getLogger(__name__)

# Woosh sound config
WOOSH_PATH = "./assets/stereogenicstudio-swish-swoosh-woosh-sfx-27-357164.mp3"
WOOSH_PEAK = 0.483  # seconds into the woosh where the peak is


def _premix_woosh(audio_path, output_path, settle_time):
    """Pre-mix woosh sound into TTS audio. Returns path to mixed audio."""
    ffmpeg = _find_exe("ffmpeg")

    if not os.path.isfile(WOOSH_PATH):
        return audio_path

    woosh_offset = max(0, settle_time - WOOSH_PEAK)

    cmd = [
        ffmpeg,
        "-i", audio_path,
        "-i", WOOSH_PATH,
        "-filter_complex",
        f"[1:a]adelay={int(woosh_offset * 1000)}|{int(woosh_offset * 1000)},volume=0.4[w];"
        f"[0:a][w]overlay=format=auto",  # wrong filter, use amix with apad
        "-y", output_path,
    ]

    # Actually, simplest: use ffmpeg to overlay woosh at low volume on the TTS
    # The key is to pad the woosh to match TTS duration first
    cmd = [
        ffmpeg,
        "-i", audio_path,
        "-i", WOOSH_PATH,
        "-filter_complex",
        (
            f"[0:a]aformat=sample_fmts=fltp:sample_rates=24000:channel_layouts=mono[tts];"
            f"[1:a]adelay={int(woosh_offset * 1000)}|{int(woosh_offset * 1000)},"
            f"volume=0.4,"
            f"aformat=sample_fmts=fltp:sample_rates=24000:channel_layouts=mono,"
            f"apad[woosh];"
            f"[tts][woosh]amix=inputs=2:duration=first:normalize=0[out]"
        ),
        "-map", "[out]",
        "-c:a", "libmp3lame", "-b:a", "192k",
        "-y", output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning(f"Woosh mix failed, using original audio: {result.stderr[-200:]}")
        return audio_path

    logger.info("Woosh mezclado en audio")
    return output_path


def compose(video_path, audio_path, ass_path, output_path, config,
            title_card_path=None, title_end_time=0):
    """Compose final video with optional animated intro overlay.

    Args:
        title_card_path: PNG with template + title for intro animation
        title_end_time: when the narrator finishes the title sentence (seconds)
    """
    vid_cfg = config["video"]
    ffmpeg = _find_exe("ffmpeg")

    ass_ffmpeg = ass_path.replace("\\", "/").replace(":", "\\:")

    input_args = ["-threads", "4"]
    if vid_cfg.get("loop_gameplay", False):
        input_args += ["-stream_loop", "-1"]

    # Pre-mix woosh into audio if we have an intro
    final_audio = audio_path
    if title_card_path and os.path.isfile(title_card_path) and os.path.isfile(WOOSH_PATH):
        mixed_path = audio_path.replace(".mp3", "_mixed.mp3")
        final_audio = _premix_woosh(audio_path, mixed_path, settle_time=0.25)

    # Shift audio 100ms earlier so voice always plays before subtitle appears
    # (subtitles are burned into video track, audio is separate — this fixes a/v sync)
    inputs = [*input_args, "-i", video_path, "-itsoffset", "-0.10", "-i", final_audio]

    if title_card_path and os.path.isfile(title_card_path):
        # Animation timing
        settle_time = 0.25   # time for card to reach center
        bounce_decay = 12    # damping factor (higher = faster settle)
        bounce_freq = 18     # oscillation frequency
        fade_dur = 0.8       # fade out duration

        # Fade starts when narrator finishes title, or after 6s fallback
        fade_start = max(title_end_time - 0.3, 3.0) if title_end_time > 0 else 6.0
        total = fade_start + fade_dur

        # Inputs: [0]=video, [1]=audio, [2]=title card, [3]=woosh
        inputs += ["-loop", "1", "-t", str(total + 1), "-i", title_card_path]

        # Bounce animation: elastic/spring effect
        # x(t) = W * exp(-decay * t) * cos(freq * t)
        # This starts at x=W (off screen right) and oscillates to 0 with damping
        x_expr = (
            f"if(lt(t,{total}),"
            f"W*exp(-{bounce_decay}*t)*cos({bounce_freq}*t),"
            f"W)"  # move off screen after total
        )

        filter_complex = (
            f"[0:v]ass='{ass_ffmpeg}'[base];"
            f"[2:v]format=rgba,"
            f"fade=t=out:st={fade_start}:d={fade_dur}:alpha=1"
            f"[card];"
            f"[base][card]overlay="
            f"x='{x_expr}':"
            f"y=0:"
            f"enable='lt(t,{total})':"
            f"format=auto,"
            f"format=yuv420p"
            f"[v]"
        )

        # Audio already pre-mixed with woosh
        map_audio = ["-map", "1:a"]

    else:
        # Without intro overlay
        filter_complex = f"[0:v]ass='{ass_ffmpeg}',format=yuv420p[v]"
        map_audio = ["-map", "1:a"]

    # Build encoding args (support both libx264 and h264_nvenc)
    codec = vid_cfg["output_codec"]
    is_nvenc = "nvenc" in codec
    if is_nvenc:
        quality_args = ["-cq", str(vid_cfg["crf"]), "-preset", vid_cfg["preset"]]
    else:
        quality_args = ["-crf", str(vid_cfg["crf"]), "-preset", vid_cfg["preset"]]

    cmd = [
        ffmpeg,
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        *map_audio,
        "-c:v", codec,
        *quality_args,
        "-c:a", vid_cfg["audio_codec"],
        "-b:a", vid_cfg["audio_bitrate"],
        "-shortest",
        "-y",
        output_path,
    ]

    logger.info(f"Componiendo video: {os.path.basename(output_path)}")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg fallo:\n{result.stderr[-500:]}")

    if not os.path.exists(output_path):
        raise RuntimeError(f"FFmpeg no genero el archivo de salida: {output_path}")

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    logger.info(f"Video generado: {output_path} ({size_mb:.1f} MB)")
