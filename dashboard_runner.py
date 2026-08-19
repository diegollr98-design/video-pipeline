"""Runner del dashboard: encapsula el pipeline como SUBPROCESO.

Módulo de funciones puras, SIN Streamlit. El dashboard lanza el pipeline
mediante `python main.py [flags]` con Popen, nunca importando las funciones
de fase (produce_video, run_tts, etc.) dentro del proceso de Streamlit.

Motivos de la decisión de arquitectura:
- main.py duplica handlers de logging en cada llamada.
- tts_engine cachea un modelo Whisper en un global de módulo.
- produce_video espera un objeto `args`.
"""

import os
import re
import sys
import glob
import subprocess

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


def build_command(options: dict) -> list:
    """Construye la lista de args para Popen a partir de `options`.

    options puede traer: video_path (str|None), style (str|None),
    dry_run (bool), skip_ingest (bool), no_shorts (bool).
    """
    cmd = [sys.executable, "main.py"]

    video_path = options.get("video_path")
    if video_path:
        cmd += ["--video", video_path]

    style = options.get("style")
    if style:
        cmd += ["--style", style]

    if options.get("dry_run"):
        cmd += ["--dry-run"]

    if options.get("skip_ingest"):
        cmd += ["--skip-ingest"]

    if options.get("no_shorts"):
        cmd += ["--no-shorts"]

    # SIEMPRE. El auditor corre al final de `main.py` y mide sobre el `.ass` y
    # el `_story.txt` de `temp/`; sin esto `cleanup_temp` los borra ANTES de
    # que se midan los shorts y el veredicto sale con
    # `FALLA cobertura de sincronismo ... falta su .ass` aunque el video este
    # perfecto -- medido el 19-ago en `video_004`. Ademas dejaba el video
    # recien producido IMPOSIBLE de re-auditar (clase [GATE-08]): sin
    # artefactos no hay nada que medir, y sin veredicto el dashboard no lo
    # ofrece para subir. `temp_dir` vive en D:, asi que el coste es disco
    # barato a cambio de que la salida sea auditable.
    cmd += ["--keep-temp"]

    return cmd


def _next_log_path() -> str:
    """Devuelve la ruta de un run-log nuevo, incremental, sin sobrescribir."""
    temp_dir = os.path.join(PROJECT_DIR, "temp")
    os.makedirs(temp_dir, exist_ok=True)

    existing = glob.glob(os.path.join(temp_dir, "dashboard_run_*.log"))
    max_n = 0
    for path in existing:
        base = os.path.splitext(os.path.basename(path))[0]  # dashboard_run_<n>
        try:
            n = int(base.rsplit("_", 1)[1])
            max_n = max(max_n, n)
        except (IndexError, ValueError):
            pass

    return os.path.join(temp_dir, f"dashboard_run_{max_n + 1}.log")


def launch_run(options: dict) -> dict:
    """Lanza el pipeline como subproceso y devuelve un handle dict.

    handle = {"proc": Popen, "log_path": str, "cmd": list, "pid": int}
    """
    cmd = build_command(options)
    log_path = _next_log_path()

    log_file = open(log_path, "w", encoding="utf-8")

    # El log se abre en UTF-8, pero eso no basta: el proceso HIJO elige su
    # codificacion de stdout por el locale de Windows (cp1252), y el auditor
    # imprime tildes, comillas angulares y flechas. Cada una de esas lineas
    # reventaba el StreamHandler de logging y Python escupia un
    # `UnicodeEncodeError` con su traceback ENTERO dentro del log -- que es
    # justo lo que la pestana Progreso ensena en vivo. Medido el 19-ago: una
    # corrida normal metia ~20 tracebacks entre las lineas del veredicto.
    # PYTHONUTF8=1 fuerza el modo UTF-8 del hijo (mismo flag que ya usan los
    # comandos manuales del repo y la tarea programada del escaneo).
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")

    proc = subprocess.Popen(
        cmd,
        cwd=PROJECT_DIR,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )

    return {
        "proc": proc,
        "log_path": log_path,
        "cmd": cmd,
        "pid": proc.pid,
    }


def is_running(handle: dict) -> bool:
    """True si el subproceso sigue vivo."""
    return handle["proc"].poll() is None


def exit_code(handle: dict):
    """Código de salida del subproceso (None si sigue vivo)."""
    return handle["proc"].poll()


def read_log(handle: dict) -> str:
    """Lee y devuelve el contenido completo del run-log.

    Si el archivo aún no existe, devuelve "".
    """
    log_path = handle["log_path"]
    if not os.path.exists(log_path):
        return ""
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def current_phase(log_text: str) -> str:
    """Heurística por marcadores del log para etiquetar la fase actual.

    "Generando shorts" es una super-fase PEGAJOSA: una vez que arranca la
    generación de shorts (su último marcador aparece después del último
    "=== Produciendo"), nos mantenemos ahí aunque cada short re-emita sus
    sub-pasos (Sintetizando audio / forced alignment / Componiendo). Sin esto,
    el escaneo en reversa reportaría "Sintetizando voz" / "Componiendo video"
    mientras realmente se están haciendo shorts (verificado contra pipeline.log
    real: al 50% del log, en short_006, devolvía "Sintetizando voz").

    Para las fases de video largo se usa el escaneo en reversa por líneas: la
    última línea con un marcador define la fase.
    """
    lines = log_text.splitlines()

    # Terminal: gana sobre todo lo demás.
    if any("Pipeline finalizado" in l for l in lines):
        return "Terminado"

    # ¿Estamos en la super-fase de shorts? (último marcador de short posterior
    # al último inicio de producción de video largo).
    last_short = -1
    last_produce = -1
    for i, l in enumerate(lines):
        if "Generando Short" in l or "--- Generando short" in l:
            last_short = i
        if "=== Produciendo" in l:
            last_produce = i
    if last_short > last_produce:
        return "Generando shorts"

    # Fallback: fases de video largo, última línea con marcador.
    line_markers = [
        ("--- Ingesting:", "Ingestando"),
        ("Recodificando para pool", "Ingestando"),
        ("Sintetizando audio", "Sintetizando voz"),
        ("forced alignment", "Sintetizando voz"),
        ("Componiendo", "Componiendo video"),
        ("=== Produciendo", "Generando historia"),
        ("Título:", "Generando historia"),
        ("Generando", "Generando historia"),
    ]
    for line in reversed(lines):
        for marker, label in line_markers:
            if marker in line:
                return label

    return "Iniciando…"


def produced_count(log_text: str):
    """Devuelve el nº de videos producidos según 'Pipeline finalizado: N videos',
    o None si la corrida aún no ha llegado a esa línea final.
    """
    m = None
    for match in re.finditer(r"Pipeline finalizado:\s*(\d+)\s+videos", log_text):
        m = match
    return int(m.group(1)) if m else None


def stop_run(handle: dict) -> None:
    """Mata el árbol de procesos (incluye ffmpeg hijo) en Windows.

    Tolera que el proceso ya haya muerto.
    """
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(handle["pid"])],
            capture_output=True,
        )
    except Exception:
        pass
