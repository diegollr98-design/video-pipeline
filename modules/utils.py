import os
import shutil
import subprocess
import yaml

# Find FFmpeg winget package directory dynamically
def _find_ffmpeg_dir():
    base = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    if os.path.isdir(base):
        for d in os.listdir(base):
            if d.startswith("Gyan.FFmpeg"):
                # Look for bin dir inside
                pkg = os.path.join(base, d)
                for sub in os.listdir(pkg):
                    bindir = os.path.join(pkg, sub, "bin")
                    if os.path.isdir(bindir):
                        return bindir
    return None

_FFMPEG_DIR = _find_ffmpeg_dir()

# Known installation paths (winget defaults on Windows)
_KNOWN_PATHS = {
    "ffmpeg": [
        os.path.join(_FFMPEG_DIR, "ffmpeg.exe") if _FFMPEG_DIR else "",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe"),
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ],
    "ffprobe": [
        os.path.join(_FFMPEG_DIR, "ffprobe.exe") if _FFMPEG_DIR else "",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\ffprobe.exe"),
        r"C:\ffmpeg\bin\ffprobe.exe",
    ],
}


def _find_exe(name):
    """Find executable: first check PATH, then known install locations."""
    found = shutil.which(name)
    if found:
        return found
    for path in _KNOWN_PATHS.get(name, []):
        if os.path.isfile(path):
            return path
    return name  # fallback to bare name (will fail if not in PATH)


def load_dotenv(path=".env"):
    """Carga variables de entorno desde un archivo .env sin dependencias externas."""
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_dirs(config):
    for key in ("input_dir", "output_dir", "temp_dir", "pool_dir", "shorts_dir", "data_dir"):
        path = config["paths"].get(key)
        if path:
            os.makedirs(path, exist_ok=True)


def cleanup_temp(config):
    temp_dir = config["paths"]["temp_dir"]
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
        os.makedirs(temp_dir, exist_ok=True)


def get_video_duration(video_path):
    ffprobe = _find_exe("ffprobe")
    result = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe falló para {video_path}: {result.stderr.strip()}")
    return float(result.stdout.strip())


def calculate_target_words(duration_seconds, config):
    wpm = config["story"]["target_wpm"]
    target = int(duration_seconds / 60 * wpm)
    min_w = config["story"]["min_words"]
    max_w = config["story"]["max_words"]
    return max(min_w, min(target, max_w))


def check_dependencies():
    missing = []
    for name in ("ffmpeg", "ffprobe"):
        exe = _find_exe(name)
        if exe == name and not shutil.which(name):
            missing.append(name)
    return missing
