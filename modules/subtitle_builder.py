import logging
import re

logger = logging.getLogger(__name__)


def _parse_srt(srt_path):
    """Parse SRT file into list of {start_ms, end_ms, text} cues."""
    cues = []
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = r"\d+\s*\n(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n(.+?)(?:\n\n|\n$|\Z)"
    matches = re.findall(pattern, content, re.DOTALL)

    for start_str, end_str, text in matches:
        cues.append({
            "start_ms": _timestamp_to_ms(start_str),
            "end_ms": _timestamp_to_ms(end_str),
            "text": text.strip(),
        })

    logger.info(f"Parsed {len(cues)} cues from SRT")
    return cues


def _timestamp_to_ms(ts):
    """Convert HH:MM:SS,mmm to milliseconds."""
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms)


def _ms_to_ass_time(ms):
    """Convert milliseconds to ASS timestamp H:MM:SS.cc."""
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    cs = (ms % 1000) // 10
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _split_cues_into_words(cues):
    """Split sentence-level cues into individual words with character-proportional timing.

    Uses character length (not word count) for timing since longer words
    take longer to pronounce, making the sync more accurate.
    """
    word_cues = []
    for cue in cues:
        words = cue["text"].split()
        if len(words) == 1:
            word_cues.append(cue)
            continue

        total_ms = cue["end_ms"] - cue["start_ms"]
        # Weight each word by its character length
        char_lengths = [len(w) for w in words]
        total_chars = sum(char_lengths)
        if total_chars == 0:
            continue

        cursor_ms = cue["start_ms"]
        for i, word in enumerate(words):
            # Duration proportional to character length
            word_duration = int(total_ms * char_lengths[i] / total_chars)
            word_cues.append({
                "start_ms": cursor_ms,
                "end_ms": cursor_ms + word_duration,
                "text": word,
            })
            cursor_ms += word_duration

    return word_cues


def _escape_ass(text):
    """Escape special ASS characters."""
    text = text.replace("\\", "\\\\")
    text = text.replace("{", "\\{")
    text = text.replace("}", "\\}")
    return text


def vtt_to_ass(vtt_path, ass_path, config, skip_until=0):
    """Convert SRT to styled ASS subtitle file with word-by-word display.

    Args:
        skip_until: don't show subtitles before this timestamp (seconds).
                    Used to hide subs during intro animation.
    """
    sub_cfg = config["subtitles"]
    cues = _parse_srt(vtt_path)

    if not cues:
        logger.warning("No se encontraron cues en el VTT")
        return

    # SRT already has one word per cue from tts_engine
    # Skip subtitles that fall during the intro
    skip_ms = int(skip_until * 1000)
    if skip_ms > 0:
        word_cues = [c for c in cues if c["start_ms"] >= skip_ms]
        skipped = len(cues) - len(word_cues)
        logger.info(f"Saltadas {skipped} palabras durante intro ({skip_until:.1f}s)")
    else:
        word_cues = cues

    logger.info(f"Procesando {len(word_cues)} palabras")

    uppercase = sub_cfg.get("uppercase", False)

    # Build ASS file
    font = sub_cfg["font_name"]
    size = sub_cfg["font_size"]
    primary = sub_cfg["primary_color"]
    outline_c = sub_cfg["outline_color"]
    outline_w = sub_cfg["outline_width"]
    shadow = sub_cfg["shadow_depth"]
    align = sub_cfg["alignment"]
    margin_v = sub_cfg["margin_v"]
    play_res_x = sub_cfg.get("play_res_x", 1920)
    play_res_y = sub_cfg.get("play_res_y", 1080)
    pos_x = play_res_x // 2
    pos_y = play_res_y // 2

    header = f"""[Script Info]
Title: Reddit Story Subtitles
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},{primary},&H000000FF,{outline_c},&H80000000,-1,0,0,0,100,100,0,0,1,{outline_w},{shadow},{align},10,10,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    for wc in word_cues:
        start = _ms_to_ass_time(wc["start_ms"])
        end = _ms_to_ass_time(wc["end_ms"])
        text = wc["text"]
        if uppercase:
            text = text.upper()
        text = _escape_ass(text)
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{{\\pos({pos_x},{pos_y})}}{text}")

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(events))
        f.write("\n")

    logger.info(f"Subtítulos ASS guardados en {ass_path}")
