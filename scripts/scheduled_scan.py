"""Disparador PROGRAMADO del escaneo de competencia (Fase 3) — SOLO escaneo.

Por qué solo escaneo y no producción: un panel adversarial evaluó programar la
producción y la refutó — el pipeline tiene gates humanos por decisión explícita
de Diego (la subida a YouTube sale de una cola con su OK en el dashboard), así
que un disparo de producción desatendido entrega un MP4 a una cola que espera
un click (autonomía ganada ~= 0) y a cambio gasta disco y cuota sin
supervisión. El escaneo es barato (~470 unidades medidas de 10.000/día), no
toca `pool/`, `input/` ni `output/`, y no requiere ningún gate humano.

Este script NUNCA importa funciones de fase (`main.py` en el mismo proceso):
lanza `python main.py --scan-competition [...]` como SUBPROCESO, igual que
`dashboard_runner.py` — es la convención del repo, no una casualidad: `main.py`
duplica handlers de logging en cada llamada y varios módulos cachean estado
global (modelos, clientes) que no se quiere compartir entre corridas.

Defensas con dientes (una comprobación que solo avisa no defiende de nada —
regla del repo §12):

  1. DISCO: si el libre cae por debajo de `--min-free-gb`, el script NO
     arranca el subproceso. Se registra y sale con código != 0. El disco es
     el riesgo dominante de esta máquina (97% usado en la última medición) y
     un disparo desatendido no puede ser quien lo remate.
  2. UN SOLO ESCANEO A LA VEZ: lock de fichero con PID + timestamp. NO hace
     polling ni espera indefinidamente — comprueba una vez; si el lock está
     tomado por un proceso vivo y no ha caducado (`--lock-stale-hours`), sale
     sin arrancar. Si el proceso dueño del lock ya murió o el lock lleva más
     tiempo del umbral, se considera abandonado y se sobrescribe. Este lock
     SOLO serializa instancias de ESTE script entre sí — no reimplementa la
     protección de `data/competitors.json` (el contador de cuota), que ya
     tiene lock + escritura atómica propios en `competitor_scout.py`
     (`_state_lock` / `_atomic_write_json`, commit 935e269) y también los usa
     `youtube_uploader.py`. No hay que duplicar eso aquí; lo que este script
     SÍ hace es loguear las unidades de cuota antes/después para que una
     escritura concurrente de otro proceso sea visible en el delta.
  3. UTF-8 FORZADO en el subproceso: `main.py:207-210` hace `print()` crudo
     del texto del LLM (que puede traer p.ej. '→', U+2192). Bajo el
     Programador de tareas de Windows, `sys.stdout.encoding` del hijo es
     `cp1252` si no se fuerza lo contrario, y ese `print()` revienta con
     `UnicodeEncodeError` antes de aplicar nada. Se fuerza `PYTHONUTF8=1` y
     `PYTHONIOENCODING=utf-8` en el ENTORNO DEL HIJO — esto es necesario
     además de (no en vez de) capturar la salida con `encoding="utf-8"` en
     este proceso: el crash ocurre dentro del hijo, al codificar SU propio
     stdout, antes de que este proceso lea nada.
  4. LOG PROPIO CON ROTACIÓN: `RotatingFileHandler` con tamaño máximo y N
     backups — el log no crece sin límite bajo un Task Scheduler diario que
     nadie vigila.
  5. NUNCA fallback silencioso: un subproceso que falla se registra con el
     FINAL de su stderr (no los primeros 500 caracteres — en este repo esos
     son el banner de compilación de FFmpeg y el error real queda fuera del
     log; el mismo patrón aplica a cualquier traceback largo de Python).

Decisión sobre `--apply-trends` (requisito 6): por DEFECTO el escaneo
programado NO aplica ("apply-trends" reescribe `prompts/*.txt`, y esos
prompts se releen EN CALIENTE — `shorts_generator.py` abre el fichero una vez
POR SHORT). Si una tanda de shorts está a mitad de generarse cuando el
escaneo programado decide aplicar directrices nuevas, los shorts de esa misma
tanda usarían prompts distintos entre sí: incoherencia dentro de una tanda,
no corrupción (la escritura ya es atómica). Ante la duda, la opción
conservadora es escanear sin aplicar y dejar el "aplicar" a Diego, que además
es quien tiene que dar el OK a que el análisis de competencia cambie el
prompt (ver `CLAUDE.md`: "con el OK del usuario"). `--apply-trends` existe
como flag explícito para quien quiera activarlo con conocimiento de causa,
pero el comando de `schtasks` que se entrega NO lo incluye.

Uso:
  python scripts/scheduled_scan.py                       # escaneo normal
  python scripts/scheduled_scan.py --no-discover          # solo re-mide conocidos
  python scripts/scheduled_scan.py --min-free-gb 15       # umbral de disco más estricto
  python scripts/scheduled_scan.py --override-cmd "python -c \"print('ok')\""
                                                            # para pruebas: sustituye el
                                                            # comando real por uno falso
"""
from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

from modules.utils import load_config  # noqa: E402

DEFAULT_LOCK_STALE_HOURS = 2.0
DEFAULT_MIN_FREE_GB = 10.0
DEFAULT_TIMEOUT_SECONDS = 1800  # 30 min: el escaneo mide minutos, no horas; guarda de red colgada
DEFAULT_MAX_LOG_BYTES = 5_000_000
DEFAULT_LOG_BACKUPS = 3
STDERR_TAIL_CHARS = 4000

EXIT_OK = 0
EXIT_DISK_LOW = 2
EXIT_LOCKED = 3
EXIT_SUBPROCESS_FAILED = 4
EXIT_CONFIG_ERROR = 5


# --------------------------------------------------------------------------
# Config / paths
# --------------------------------------------------------------------------

def _resolve_data_dir(config_path: str) -> str:
    """Lee `paths.data_dir` de config.yaml. Si el config falta o es ilegible,
    NO aborta el disparador por eso (el escaneo real hará su propia
    validación) — cae a "./data" y lo dice, en vez de fallar de forma opaca
    en un sitio que no es su responsabilidad."""
    try:
        cfg = load_config(os.path.join(PROJECT_DIR, config_path))
        data_dir = cfg.get("paths", {}).get("data_dir") or "./data"
    except Exception as e:  # noqa: BLE001 - se loguea, no se traga (ver docstring de la función)
        logging.getLogger("scheduled_scan").warning(
            "No se pudo leer '%s' (%s); uso './data' como data_dir por defecto.",
            config_path, e,
        )
        data_dir = "./data"
    return os.path.normpath(os.path.join(PROJECT_DIR, data_dir))


# --------------------------------------------------------------------------
# Logging con rotación
# --------------------------------------------------------------------------

def build_logger(log_path: str, max_bytes: int, backups: int) -> logging.Logger:
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    logger = logging.getLogger("scheduled_scan")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # Evita duplicar handlers si build_logger se llama más de una vez en el
    # mismo proceso (tests).
    for h in list(logger.handlers):
        logger.removeHandler(h)
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(handler)
    # También a consola (útil en pruebas manuales; en Task Scheduler no hay consola).
    console = logging.StreamHandler()
    console.setFormatter(handler.formatter)
    logger.addHandler(console)
    return logger


# --------------------------------------------------------------------------
# Precondición de disco — CON DIENTES
# --------------------------------------------------------------------------

def check_disk(path: str, min_free_gb: float) -> tuple[float, bool]:
    usage = shutil.disk_usage(path)
    free_gb = usage.free / (1024 ** 3)
    return free_gb, free_gb >= min_free_gb


# --------------------------------------------------------------------------
# Lock de un solo proceso — NO se cuelga para siempre (check único, no polling)
# --------------------------------------------------------------------------

def _pid_alive(pid: int) -> bool:
    """True si `pid` corresponde a un proceso vivo. Conservador: si no se
    puede determinar, se asume vivo (mejor negarse a arrancar de más que
    lanzar dos escaneos en paralelo)."""
    if pid is None or pid <= 0:
        return False
    if os.name == "nt":
        try:
            # encoding/errors EXPLÍCITOS: `tasklist` en Windows en español
            # escribe en cp1252 (acentos de "ejecución" etc). Sin fijarlo, el
            # encoding se hereda del modo del proceso padre (p.ej. bajo
            # PYTHONUTF8=1 intenta decodificar como UTF-8) y una tilde
            # revienta el hilo lector interno de subprocess.run con
            # UnicodeDecodeError, dejando `out.stdout` en None. Reproducido.
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
        except (OSError, subprocess.TimeoutExpired):
            return True
        return str(pid) in (out.stdout or "")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    else:
        return True


def acquire_lock(lock_path: str, stale_seconds: float, logger: logging.Logger) -> bool:
    """Intenta tomar el lock. Devuelve True si lo consigue (y lo escribe con
    nuestro PID), False si ya está tomado por un proceso vivo y no caducado.

    No hace polling: es un check-and-set único. "No cuelgues para siempre" se
    cumple por construcción, no por un timeout que espera."""
    if os.path.isfile(lock_path):
        pid = None
        age = None
        try:
            with open(lock_path, "r", encoding="utf-8") as f:
                info = json.load(f)
            pid = int(info.get("pid", -1))
            started = info.get("started_at")
            if started:
                age = time.time() - datetime.fromisoformat(started).timestamp()
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as e:
            logger.warning(
                "Lock '%s' ilegible (%s); se trata como abandonado.", lock_path, e,
            )
            pid, age = None, None

        alive = _pid_alive(pid) if pid else False
        if alive and (age is None or age < stale_seconds):
            logger.warning(
                "Lock tomado por PID %s (edad %s) < umbral %.0fs; no arranco.",
                pid, f"{age:.0f}s" if age is not None else "desconocida",
                stale_seconds,
            )
            return False
        logger.warning(
            "Lock '%s' abandonado (pid=%s alive=%s age=%s) — lo tomo.",
            lock_path, pid, alive, age,
        )

    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump(
            {"pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat()},
            f,
        )
    return True


def release_lock(lock_path: str, own_pid: int, logger: logging.Logger) -> None:
    """Borra el lock SOLO si sigue siendo nuestro (nadie lo sobrescribió por
    considerarlo abandonado mientras corríamos). Nunca falla en silencio."""
    try:
        with open(lock_path, "r", encoding="utf-8") as f:
            info = json.load(f)
        if int(info.get("pid", -1)) == own_pid:
            os.remove(lock_path)
    except FileNotFoundError:
        pass  # ya no estaba: nada que liberar, no es un error
    except (OSError, ValueError, json.JSONDecodeError) as e:
        logger.warning("No se pudo liberar el lock '%s' limpiamente: %s", lock_path, e)


# --------------------------------------------------------------------------
# Cuota — solo LECTURA, best-effort (el contador real lo escribe competitor_scout)
# --------------------------------------------------------------------------

def read_quota_units(data_dir: str) -> int | None:
    """Unidades de cuota gastadas HOY (UTC), o None si no se puede saber
    (fichero ausente/ilegible, o de un día distinto -> 0, no None)."""
    path = os.path.join(data_dir, "competitors.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    quota = state.get("quota") or {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if quota.get("date") != today:
        return 0
    try:
        return int(quota.get("units", 0))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Comando + ejecución del subproceso
# --------------------------------------------------------------------------

def build_scan_command(python_exe: str, no_discover: bool, apply_trends: bool,
                        config_path: str) -> list:
    cmd = [python_exe, "main.py", "--config", config_path, "--scan-competition"]
    if no_discover:
        cmd.append("--no-discover")
    if apply_trends:
        cmd.append("--apply-trends")
    return cmd


def subprocess_env() -> dict:
    """Entorno del hijo con UTF-8 forzado — ver punto 3 del docstring del
    módulo. Sin esto, `main.py` revienta con UnicodeEncodeError bajo el
    Programador de tareas de Windows en cuanto el consejo cacheado trae un
    carácter fuera de cp1252 (reproducido con '→', U+2192)."""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_scan(cmd: list, timeout_seconds: float | None) -> tuple[int, str, str]:
    """Ejecuta `cmd` como subproceso. Devuelve (returncode, stdout, stderr).

    returncode == -1 con stderr describiendo un timeout si se excede
    `timeout_seconds` (no es un código real de proceso, pero se distingue de
    cualquier returncode real que main.py pueda devolver, que son >= 0)."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=PROJECT_DIR,
            env=subprocess_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout or ""
        stderr = (e.stderr or "") + f"\n[scheduled_scan] TIMEOUT tras {timeout_seconds}s"
        return -1, stdout, stderr


def _split_override_cmd(raw: str) -> list:
    """Parte `--override-cmd` en argv. En Windows, `shlex.split` en modo
    POSIX (el default) trata la barra invertida como escape y destroza
    rutas tipo `C:\\Users\\...\\python.exe` (reproducido: las convierte en
    `C:UsersPython.exe`, y el subproceso muere con FileNotFoundError). En
    Windows se usa `posix=False` (preserva backslashes) y se pela a mano UN
    par de comillas envolventes por token, que es lo único que `posix=False`
    deja de más."""
    if os.name != "nt":
        return shlex.split(raw)
    tokens = shlex.split(raw, posix=False)
    cleaned = []
    for t in tokens:
        if len(t) >= 2 and t[0] == t[-1] and t[0] in ('"', "'"):
            t = t[1:-1]
        cleaned.append(t)
    return cleaned


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Disparador programado del ESCANEO de competencia (nunca produce vídeos).",
    )
    p.add_argument("--config", default="config.yaml",
                   help="Ruta a config.yaml relativa al repo (se pasa también a main.py)")
    p.add_argument("--min-free-gb", type=float, default=DEFAULT_MIN_FREE_GB,
                   help="Disco libre mínimo (GB) para arrancar. Por debajo, no arranca.")
    p.add_argument("--lock-stale-hours", type=float, default=DEFAULT_LOCK_STALE_HOURS,
                   help="Un lock más viejo que esto se considera abandonado y se sobrescribe.")
    p.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS,
                   help="Mata el subproceso si tarda más que esto (guarda contra red colgada).")
    p.add_argument("--no-discover", action="store_true",
                   help="Pasa --no-discover a main.py: solo re-mide canales conocidos (~0 unidades de búsqueda).")
    p.add_argument("--apply-trends", action="store_true",
                   help="Pasa --apply-trends a main.py. Por defecto NO se activa (ver docstring).")
    p.add_argument("--log-dir", default=None,
                   help="Directorio del log propio. Por defecto: paths.data_dir de config.yaml.")
    p.add_argument("--data-dir", default=None,
                   help="Directorio donde vive competitors.json (para leer la cuota antes/después). "
                        "Por defecto: paths.data_dir de config.yaml. Override explícito para pruebas "
                        "sin depender del config.yaml real del repo.")
    p.add_argument("--log-name", default="scheduled_scan.log")
    p.add_argument("--max-log-bytes", type=int, default=DEFAULT_MAX_LOG_BYTES)
    p.add_argument("--log-backups", type=int, default=DEFAULT_LOG_BACKUPS)
    p.add_argument("--lock-path", default=None,
                   help="Ruta del fichero de lock. Por defecto: <log-dir>/scheduled_scan.lock")
    p.add_argument("--python-exe", default=sys.executable,
                   help="Intérprete usado para lanzar main.py como subproceso.")
    p.add_argument("--override-cmd", default=None,
                   help="SOLO para pruebas: sustituye el comando real de escaneo por este "
                        "(se parte con shlex). Nunca lo uses en la tarea programada real.")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    data_dir = args.data_dir or _resolve_data_dir(args.config)
    log_dir = args.log_dir or data_dir
    log_path = os.path.join(log_dir, args.log_name)
    lock_path = args.lock_path or os.path.join(log_dir, "scheduled_scan.lock")

    logger = build_logger(log_path, args.max_log_bytes, args.log_backups)
    logger.info("=== scheduled_scan arranca (pid=%s) ===", os.getpid())

    # 1) Disco — precondición con dientes.
    free_gb, disk_ok = check_disk(PROJECT_DIR, args.min_free_gb)
    logger.info("Disco libre: %.2f GB (umbral %.2f GB)", free_gb, args.min_free_gb)
    if not disk_ok:
        logger.error(
            "Disco por debajo del umbral (%.2f < %.2f GB) — NO arranco el escaneo.",
            free_gb, args.min_free_gb,
        )
        return EXIT_DISK_LOW

    # 2) Lock — un solo escaneo a la vez, sin polling.
    if not acquire_lock(lock_path, args.lock_stale_hours * 3600, logger):
        logger.error("Ya hay un escaneo en curso (lock tomado) — NO arranco otro.")
        return EXIT_LOCKED

    try:
        units_before = read_quota_units(data_dir)
        logger.info(
            "Cuota YouTube antes: %s",
            units_before if units_before is not None else "desconocida (competitors.json ausente/ilegible)",
        )

        if args.override_cmd:
            cmd = _split_override_cmd(args.override_cmd)
            logger.warning("Usando --override-cmd (SOLO pruebas): %s", cmd)
        else:
            cmd = build_scan_command(
                args.python_exe, args.no_discover, args.apply_trends, args.config,
            )
        logger.info(
            "apply_trends=%s no_discover=%s -> comando: %s",
            args.apply_trends, args.no_discover, cmd,
        )

        t0 = time.time()
        returncode, stdout, stderr = run_scan(cmd, args.timeout_seconds)
        elapsed = time.time() - t0

        units_after = read_quota_units(data_dir)
        delta = (
            units_after - units_before
            if units_before is not None and units_after is not None
            else None
        )
        logger.info(
            "Cuota YouTube después: %s (delta: %s)",
            units_after if units_after is not None else "desconocida",
            delta if delta is not None else "no calculable",
        )
        logger.info("Subproceso terminó en %.1fs con código %s", elapsed, returncode)

        if returncode != 0:
            # NUNCA los primeros N caracteres de stderr (el bug ya conocido en
            # este repo con FFmpeg): el final es donde vive el error real.
            tail = (stderr or "")[-STDERR_TAIL_CHARS:]
            logger.error(
                "ESCANEO FALLÓ (código %s). Cola de stderr (últimos %d chars):\n%s",
                returncode, STDERR_TAIL_CHARS, tail,
            )
            return EXIT_SUBPROCESS_FAILED

        logger.info("Escaneo OK.")
        # stdout normal se registra a nivel INFO solo si no es enorme; el log
        # ya rota, así que no hace falta recortarlo agresivamente.
        if stdout.strip():
            logger.info("stdout del escaneo:\n%s", stdout.strip()[-STDERR_TAIL_CHARS:])
        return EXIT_OK
    finally:
        release_lock(lock_path, os.getpid(), logger)
        logger.info("=== scheduled_scan termina ===")


if __name__ == "__main__":
    sys.exit(main())
