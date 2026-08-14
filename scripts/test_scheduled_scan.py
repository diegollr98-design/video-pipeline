"""Tests de scripts/scheduled_scan.py — casos degenerados incluidos (§16).

NO hace ninguna llamada real a la YouTube API ni a OpenRouter: el subproceso
real (`main.py --scan-competition`) se sustituye SIEMPRE por `--override-cmd`
con comandos Python de una línea que simulan éxito/fallo/timeout/UTF-8.

Ejecutar: python -m pytest scripts/test_scheduled_scan.py -v
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import scheduled_scan as ss  # noqa: E402

PY = sys.executable


def _cmd(code: str) -> str:
    """Construye un --override-cmd que ejecuta `code` con -c, entrecomillado
    para shlex.split (usa comillas simples fuera, dobles dentro)."""
    return f'{PY} -c "{code}"'


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return str(d)


# --------------------------------------------------------------------------
# _resolve_data_dir: config.yaml real y config.yaml ausente
# --------------------------------------------------------------------------

def test_resolve_data_dir_reads_real_config():
    # el config.yaml real del repo declara paths.data_dir: "./data"
    resolved = ss._resolve_data_dir("config.yaml")
    assert resolved == os.path.normpath(os.path.join(ss.PROJECT_DIR, "data"))


def test_resolve_data_dir_missing_config_falls_back_without_raising():
    resolved = ss._resolve_data_dir("no_existe_este_config_de_verdad.yaml")
    assert resolved == os.path.normpath(os.path.join(ss.PROJECT_DIR, "data"))


# --------------------------------------------------------------------------
# check_disk
# --------------------------------------------------------------------------

def test_check_disk_reports_free_and_ok_flag(tmp_path):
    free_gb, ok = ss.check_disk(str(tmp_path), min_free_gb=0.0)
    assert free_gb > 0
    assert ok is True


def test_check_disk_below_threshold_is_not_ok(tmp_path):
    # ningún disco real tiene un exabyte libre
    free_gb, ok = ss.check_disk(str(tmp_path), min_free_gb=10 ** 9)
    assert ok is False
    assert free_gb < 10 ** 9


# --------------------------------------------------------------------------
# lock: caso feliz, caso tomado, caso abandonado (stale), caso ilegible
# --------------------------------------------------------------------------

def test_lock_acquire_and_release(tmp_path, caplog):
    logger = ss.build_logger(str(tmp_path / "log.txt"), 10_000, 1)
    lock_path = str(tmp_path / "scan.lock")

    assert ss.acquire_lock(lock_path, stale_seconds=3600, logger=logger) is True
    assert os.path.isfile(lock_path)

    ss.release_lock(lock_path, os.getpid(), logger)
    assert not os.path.isfile(lock_path)


def test_lock_held_by_self_pid_blocks_second_acquire(tmp_path):
    logger = ss.build_logger(str(tmp_path / "log.txt"), 10_000, 1)
    lock_path = str(tmp_path / "scan.lock")

    # Escribe un lock con NUESTRO PROPIO pid (proceso vivo por definición)
    # y timestamp reciente -> debe bloquear un segundo acquire.
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump({"pid": os.getpid(), "started_at": ss.datetime.now(ss.timezone.utc).isoformat()}, f)

    assert ss.acquire_lock(lock_path, stale_seconds=3600, logger=logger) is False


def test_lock_stale_by_age_is_overridden(tmp_path):
    logger = ss.build_logger(str(tmp_path / "log.txt"), 10_000, 1)
    lock_path = str(tmp_path / "scan.lock")

    old_ts = ss.datetime.now(ss.timezone.utc).timestamp() - 999999
    old_iso = ss.datetime.fromtimestamp(old_ts, tz=ss.timezone.utc).isoformat()
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump({"pid": os.getpid(), "started_at": old_iso}, f)

    # aunque el pid siga vivo (es el nuestro), la edad supera el umbral -> se sobreescribe
    assert ss.acquire_lock(lock_path, stale_seconds=1.0, logger=logger) is True


def test_lock_dead_pid_is_overridden(tmp_path):
    logger = ss.build_logger(str(tmp_path / "log.txt"), 10_000, 1)
    lock_path = str(tmp_path / "scan.lock")

    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump({"pid": 999999999, "started_at": ss.datetime.now(ss.timezone.utc).isoformat()}, f)

    assert ss.acquire_lock(lock_path, stale_seconds=3600, logger=logger) is True


def test_lock_illegible_is_treated_as_abandoned(tmp_path):
    logger = ss.build_logger(str(tmp_path / "log.txt"), 10_000, 1)
    lock_path = str(tmp_path / "scan.lock")

    with open(lock_path, "w", encoding="utf-8") as f:
        f.write("{esto no es json valido")

    assert ss.acquire_lock(lock_path, stale_seconds=3600, logger=logger) is True


def test_release_does_not_delete_lock_owned_by_another_process(tmp_path):
    logger = ss.build_logger(str(tmp_path / "log.txt"), 10_000, 1)
    lock_path = str(tmp_path / "scan.lock")
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump({"pid": 424242, "started_at": ss.datetime.now(ss.timezone.utc).isoformat()}, f)

    ss.release_lock(lock_path, os.getpid(), logger)  # no somos el dueño
    assert os.path.isfile(lock_path)  # sigue ahí: no se borra un lock ajeno


def test_release_lock_missing_file_does_not_raise(tmp_path):
    logger = ss.build_logger(str(tmp_path / "log.txt"), 10_000, 1)
    lock_path = str(tmp_path / "scan.lock")
    ss.release_lock(lock_path, os.getpid(), logger)  # no existe: no debe reventar


# --------------------------------------------------------------------------
# cuota: fichero ausente, ilegible, día distinto
# --------------------------------------------------------------------------

def test_read_quota_units_missing_file(data_dir):
    assert ss.read_quota_units(data_dir) is None


def test_read_quota_units_illegible_file(data_dir):
    path = os.path.join(data_dir, "competitors.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{roto")
    assert ss.read_quota_units(data_dir) is None


def test_read_quota_units_today(data_dir):
    path = os.path.join(data_dir, "competitors.json")
    today = ss.datetime.now(ss.timezone.utc).strftime("%Y-%m-%d")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"quota": {"date": today, "units": 123}}, f)
    assert ss.read_quota_units(data_dir) == 123


def test_read_quota_units_stale_date_is_zero(data_dir):
    path = os.path.join(data_dir, "competitors.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"quota": {"date": "2020-01-01", "units": 999}}, f)
    assert ss.read_quota_units(data_dir) == 0


# --------------------------------------------------------------------------
# build_scan_command
# --------------------------------------------------------------------------

def test_build_scan_command_default():
    cmd = ss.build_scan_command("python", no_discover=False, apply_trends=False,
                                 config_path="config.yaml")
    assert cmd == ["python", "main.py", "--config", "config.yaml", "--scan-competition"]


def test_build_scan_command_never_includes_apply_trends_unless_asked():
    cmd = ss.build_scan_command("python", no_discover=False, apply_trends=False,
                                 config_path="config.yaml")
    assert "--apply-trends" not in cmd


def test_build_scan_command_with_flags():
    cmd = ss.build_scan_command("python", no_discover=True, apply_trends=True,
                                 config_path="config.yaml")
    assert "--no-discover" in cmd
    assert "--apply-trends" in cmd


# --------------------------------------------------------------------------
# end-to-end de main() con --override-cmd (SIN tocar la API real)
# --------------------------------------------------------------------------

def _run_main(tmp_path, override_cmd, **extra_args):
    log_dir = str(tmp_path / "logdir")
    data_dir = str(tmp_path / "datadir")
    os.makedirs(data_dir, exist_ok=True)
    args = [
        "--log-dir", log_dir,
        "--data-dir", data_dir,  # aislado del data/ real del repo, no del control del test
        "--min-free-gb", "0",  # no queremos que el disco real bloquee el test
        "--override-cmd", override_cmd,
        "--timeout-seconds", "10",
    ]
    for k, v in extra_args.items():
        args += [f"--{k.replace('_', '-')}", str(v)]
    code = ss.main(args)
    log_path = os.path.join(log_dir, "scheduled_scan.log")
    log_text = ""
    if os.path.isfile(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            log_text = f.read()
    return code, log_text, log_dir


def test_main_success_writes_log_and_exits_zero(tmp_path):
    code, log_text, log_dir = _run_main(tmp_path, _cmd("print('ok simulado')"))
    assert code == ss.EXIT_OK
    assert "Escaneo OK" in log_text
    assert not os.path.isfile(os.path.join(log_dir, "scheduled_scan.lock"))  # liberado


def test_main_failure_logs_stderr_tail_and_exits_nonzero(tmp_path):
    code, log_text, _ = _run_main(
        tmp_path,
        _cmd("import sys; sys.stderr.write('boom real error'); sys.exit(1)"),
    )
    assert code == ss.EXIT_SUBPROCESS_FAILED
    assert "ESCANEO FALLÓ" in log_text
    assert "boom real error" in log_text


def test_main_failure_logs_end_of_stderr_not_head(tmp_path):
    """Replica el bug de FFmpeg de este repo: el error real vive al FINAL de
    stderr, detrás de un 'banner' largo. Si el disparador solo mirara los
    primeros N caracteres, este test lo cazaría."""
    banner = "X" * 6000
    code, log_text, _ = _run_main(
        tmp_path,
        _cmd(
            f"import sys; sys.stderr.write('{banner}'); "
            "sys.stderr.write('ERROR_REAL_AL_FINAL'); sys.exit(1)"
        ),
    )
    assert code == ss.EXIT_SUBPROCESS_FAILED
    assert "ERROR_REAL_AL_FINAL" in log_text


def test_main_utf8_stdout_does_not_crash_the_wrapper(tmp_path):
    """El caso que mata al escaneo real hoy: un print() con un caracter fuera
    de cp1252 (el consejo cacheado trae '→', U+2192). Bajo PYTHONUTF8=1 en el
    entorno del hijo, esto NO debe reventar."""
    code, log_text, _ = _run_main(
        tmp_path,
        _cmd("print('directrices \\u2192 aplicadas')"),
    )
    assert code == ss.EXIT_OK
    assert "directrices" in log_text


def test_main_disk_below_threshold_does_not_run_subprocess(tmp_path):
    code, log_text, log_dir = _run_main(
        tmp_path, _cmd("print('no debería ejecutarse')"),
        min_free_gb=10 ** 9,
    )
    assert code == ss.EXIT_DISK_LOW
    assert "NO arranco el escaneo" in log_text
    # ni siquiera se tomó el lock
    assert not os.path.isfile(os.path.join(log_dir, "scheduled_scan.lock"))


def test_main_second_instance_blocked_by_lock(tmp_path):
    log_dir = str(tmp_path / "logdir")
    lock_path = os.path.join(log_dir, "scheduled_scan.lock")
    os.makedirs(log_dir, exist_ok=True)
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump({"pid": os.getpid(), "started_at": ss.datetime.now(ss.timezone.utc).isoformat()}, f)

    code = ss.main([
        "--log-dir", log_dir,
        "--min-free-gb", "0",
        "--override-cmd", _cmd("print('no debería ejecutarse')"),
    ])
    assert code == ss.EXIT_LOCKED


def test_main_missing_competitors_json_is_not_fatal(tmp_path):
    """data/competitors.json ausente: el escaneo debe poder arrancar igual
    (main.py real lo crearía); solo se registra la cuota como 'desconocida'."""
    code, log_text, _ = _run_main(tmp_path, _cmd("print('ok')"))
    assert code == ss.EXIT_OK
    assert "desconocida" in log_text


def test_main_timeout_is_reported_and_fails(tmp_path):
    code, log_text, _ = _run_main(
        tmp_path,
        _cmd("import time; time.sleep(5)"),
        timeout_seconds=1,
    )
    assert code == ss.EXIT_SUBPROCESS_FAILED
    assert "TIMEOUT" in log_text


def test_log_rotates_when_over_limit(tmp_path):
    log_dir = str(tmp_path / "logdir")
    # max_log_bytes muy bajo para forzar rotación en pocas corridas
    for i in range(6):
        _run_main(
            tmp_path, _cmd(f"print('corrida {i} ' + 'x' * 2000)"),
            max_log_bytes=3000, log_backups=2,
        )
        # cada _run_main usa el mismo tmp_path/logdir por defecto
    files = os.listdir(log_dir)
    rotated = [f for f in files if f.startswith("scheduled_scan.log.")]
    assert len(rotated) >= 1, f"esperaba backups rotados, encontré: {files}"
    # nunca más backups que los configurados
    assert len(rotated) <= 2


def test_pid_alive_for_current_process():
    assert ss._pid_alive(os.getpid()) is True


def test_pid_alive_false_for_bogus_pid():
    assert ss._pid_alive(999999999) is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
