#!/usr/bin/env python3
"""
watchdog.py — Vigila el loop de ingesta y lo relanza si está caído.

Chequea el último snapshot en snapshots/. Si tiene más de 15 min de antigüedad,
verifica si hay un proceso python.exe corriendo ingest.py. Si no hay, relanza
`ingest.py --loop` como subproceso desacoplado. Loguea todo a logs/watchdog.log.

Uso (manual):
    python watchdog.py

Uso (Task Scheduler cada 5 min): ver README.
"""

import logging
import os
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import SNAPSHOTS_DIR as _SNAP, LOGS_DIR as _LOGS, WATCHDOG_STALE_MIN

SNAPSHOTS_DIR = PROJECT_ROOT / _SNAP
LOG_FILE = PROJECT_ROOT / _LOGS / "watchdog.log"
STALE_MINUTES = WATCHDOG_STALE_MIN

# UUID se pasa via env var desde el crontab (NO hardcodear: el repo es público).
# Sin env var → no ping, comportamiento silencioso (e.g. corrida manual).
HC_INGEST = os.environ.get("HC_INGEST", "")


def ping_healthcheck():
    """Ping a healthchecks.io señalando ingest sano. No-op si HC_INGEST no seteado.

    Falla silenciosa por diseño: si la red está rara o el servicio caído,
    no debe crashear el watchdog. La ausencia del ping ya dispara la alerta
    tras el grace time configurado en healthchecks.io.
    """
    if not HC_INGEST:
        return
    try:
        urllib.request.urlopen(f"https://hc-ping.com/{HC_INGEST}", timeout=5)
    except Exception as e:
        logging.warning(f"healthcheck ping failed: {e}")


def latest_snapshot_age_minutes():
    if not SNAPSHOTS_DIR.exists():
        return None
    files = list(SNAPSHOTS_DIR.rglob("*.json.gz"))
    if not files:
        return None
    latest = max(files, key=lambda p: p.stat().st_mtime)
    age_sec = datetime.now().timestamp() - latest.stat().st_mtime
    return age_sec / 60


def ingest_running():
    """True si hay un proceso Python ejecutando ingest.py."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" "
             "| Where-Object { $_.CommandLine -like '*ingest.py*' } "
             "| Select-Object -First 1 -ExpandProperty ProcessId"],
            capture_output=True, text=True, timeout=10)
        return bool(r.stdout.strip())
    except Exception as e:
        logging.error(f"No pude chequear procesos: {e}")
        return False


def relaunch_loop():
    flags = 0
    if sys.platform.startswith("win"):
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [sys.executable, "ingest.py", "--loop"],
        cwd=str(PROJECT_ROOT),
        creationflags=flags,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        close_fds=True,
    )


def main():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        filename=str(LOG_FILE),
        format="%(asctime)s [%(levelname)s] %(message)s",
        encoding="utf-8",
    )

    age = latest_snapshot_age_minutes()
    if age is not None and age < STALE_MINUTES:
        ping_healthcheck()
        return  # Todo OK, silencio.

    age_str = f"{age:.1f}min" if age is not None else "nunca"
    if ingest_running():
        logging.info(f"Ultimo snapshot hace {age_str}, pero proceso ingest activo. No relanzo.")
        return

    try:
        relaunch_loop()
        logging.warning(f"Ultimo snapshot hace {age_str}. Relancé ingest.py --loop.")
    except Exception as e:
        logging.error(f"Fallo al relanzar ingest: {e}")


if __name__ == "__main__":
    main()
