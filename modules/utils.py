import logging
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


def _deep_merge(base, over):
    """Mezcla `over` sobre `base` sin perder las claves que `over` no menciona."""
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config_raw(path="config.yaml"):
    """El fichero TAL CUAL, SIN el overlay `.local.yaml` superpuesto.

    Lo usa el editor de config del dashboard: si editara el dict fusionado y
    lo volcara a `config.yaml`, hornearia en el fichero VERSIONADO los valores
    locales de esta maquina (rutas de otro disco, y una clave de API si
    alguien la pusiera ahi, que el codigo admite). Es decir: guardar desde el
    dashboard publicaria secretos y destruiria el proposito del overlay.
    """
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def local_overlay_path(path="config.yaml"):
    """Ruta del overlay de esta maquina, exista o no."""
    base, ext = os.path.splitext(path)
    return base + ".local" + (ext or ".yaml")


def load_config(path="config.yaml"):
    """Carga la config y le superpone `<nombre>.local.yaml` si existe.

    El fichero versionado lleva rutas RELATIVAS para que un clon arranque sin
    tocar nada. Cada maquina pone sus rutas reales (aqui el gameplay vive en
    otro disco) en el `.local.yaml`, que esta gitignored: asi la config del
    repo deja de ser un fichero que cada uno tiene modificado en su copia.
    El overlay es opcional; si no existe, el comportamiento es el de antes.
    """
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    local_path = local_overlay_path(path)
    if os.path.isfile(local_path):
        with open(local_path, "r", encoding="utf-8") as f:
            overlay = yaml.safe_load(f) or {}
        if not isinstance(overlay, dict):
            # §13: nada de fallback mudo. Un overlay malformado se dice.
            raise ValueError(
                f"{local_path} no contiene un mapa YAML (leido: {type(overlay).__name__}). "
                f"Corrigelo o borralo."
            )
        _deep_merge(config, overlay)
        logging.getLogger(__name__).info(
            f"Config: overlay local aplicado desde {local_path}"
        )

    return config


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


_HUELLA_FUENTES = ("scripts/audit_run.py", "scripts/eval_sync.py")


def huella_auditor():
    """Huella de los CRITERIOS con los que se emitió un veredicto de auditoría.

    Un veredicto en verde no caducaba al cambiar el auditor, y eso ya pasó de
    verdad: `output/video_002_audit.json` decía `ok:true` (12-ago 16:43) sobre un
    vídeo del que Diego se quejó, porque la comprobación que lo habría cazado se
    escribió 47 minutos DESPUÉS (17:30). El dashboard seguía ofreciendo ese vídeo
    para subir a YouTube — con el certificado de un auditor que ya no existía.

    Se hashea el fichero entero, no un número de versión a mano: un `VERSION = 3`
    que hay que acordarse de subir es una garantía en prosa, y aquí las garantías
    en prosa fallan (§17). El precio es que tocar el auditor obliga a re-auditar;
    es el lado barato del default (§16) y cuesta tiempo, no cuota.
    """
    import hashlib
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    h = hashlib.sha256()
    for rel in _HUELLA_FUENTES:
        ruta = os.path.join(raiz, rel.replace("/", os.sep))
        try:
            with open(ruta, "rb") as f:
                h.update(f.read())
        except OSError:
            # Sin poder leer los criterios NO se puede afirmar que un veredicto
            # siga valiendo. Se devuelve una huella imposible de casar en vez de
            # un valor por defecto que haría pasar cualquier veredicto viejo.
            return "ilegible"
    return h.hexdigest()[:12]


def check_dependencies():
    missing = []
    for name in ("ffmpeg", "ffprobe"):
        exe = _find_exe(name)
        if exe == name and not shutil.which(name):
            missing.append(name)
    return missing
