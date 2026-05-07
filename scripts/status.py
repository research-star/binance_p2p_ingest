#!/usr/bin/env python3
"""
status.py — Reporte rápido del estado del loop de ingesta.

Imprime:
  - Si hay un proceso pythonw/python corriendo ingest.py (PID, RAM, uptime).
  - Conteo de snapshots de los últimos 5 días + el de hoy en curso.
  - Edad del último snapshot.
  - Última fecha en bcb_referencial.json.
  - Cantidad de WARNING/ERROR en logs/ingest.log de las últimas 24 h.

Si el loop NO está corriendo y la sesión es interactiva, ofrece lanzarlo
con start_loop.ps1 vía prompt y/N.

Uso:
    python scripts\\status.py

Pensado para ejecutarse a mano cuando uno se pregunta "¿cómo va el loop?".
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import SNAPSHOTS_DIR as _SNAP, LOGS_DIR as _LOGS, BCB_REF_JSON as _BCB

SNAPSHOTS_DIR = PROJECT_ROOT / _SNAP
LOG_FILE = PROJECT_ROOT / _LOGS / "ingest.log"
BCB_FILE = PROJECT_ROOT / _BCB


def find_ingest_process():
    """Devuelve (pid, ram_mb, start_time_str) o None."""
    if not sys.platform.startswith("win"):
        return None
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" "
        "| Where-Object { $_.CommandLine -like '*ingest.py*' } "
        "| Select-Object -First 1 ProcessId, WorkingSetSize, CreationDate "
        "| ConvertTo-Json -Compress"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=10,
        )
        out = r.stdout.strip()
        if not out:
            return None
        d = json.loads(out)
        pid = d.get("ProcessId")
        ram_mb = round((d.get("WorkingSetSize") or 0) / (1024 * 1024), 1)
        cd = d.get("CreationDate")
        if isinstance(cd, dict):
            cd = cd.get("DateTime") or cd.get("value")
        # PowerShell a veces serializa fechas como "/Date(epoch_ms)/"
        if isinstance(cd, str):
            m = re.match(r"/Date\((\d+)\)/", cd)
            if m:
                ts = int(m.group(1)) / 1000
                dt = datetime.fromtimestamp(ts)
                uptime = datetime.now() - dt
                cd = f"{dt:%Y-%m-%d %H:%M} (uptime {uptime.days}d {uptime.seconds // 3600}h)"
        return pid, ram_mb, cd
    except Exception as e:
        return f"error: {e}"


def count_per_day(days_back=5):
    today = datetime.now(timezone.utc).date()
    rows = []
    for i in range(days_back, -1, -1):
        d = today - timedelta(days=i)
        folder = SNAPSHOTS_DIR / d.isoformat()
        n = sum(1 for _ in folder.glob("*.json.gz")) if folder.is_dir() else 0
        rows.append((d.isoformat(), n))
    return rows


def latest_snapshot_age_minutes():
    if not SNAPSHOTS_DIR.exists():
        return None, None
    files = list(SNAPSHOTS_DIR.rglob("*.json.gz"))
    if not files:
        return None, None
    latest = max(files, key=lambda p: p.stat().st_mtime)
    age_min = (datetime.now().timestamp() - latest.stat().st_mtime) / 60
    return latest.name, age_min


def bcb_latest():
    if not BCB_FILE.exists():
        return None
    try:
        data = json.loads(BCB_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list) and data:
            return sorted(data, key=lambda x: x.get("fecha", ""))[-1]
    except Exception:
        pass
    return None


def recent_log_issues(hours=24):
    if not LOG_FILE.exists():
        return 0, 0
    cutoff = datetime.now() - timedelta(hours=hours)
    warn = err = 0
    ts_re = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
    with LOG_FILE.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = ts_re.match(line)
            if not m:
                continue
            try:
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            if ts < cutoff:
                continue
            if "[WARNING]" in line:
                warn += 1
            elif "[ERROR]" in line:
                err += 1
    return warn, err


def offer_to_start_loop():
    """Si stdin es interactivo, pregunta si lanzar start_loop.ps1."""
    if not sys.stdin.isatty():
        return
    script = Path(__file__).resolve().parent / "start_loop.ps1"
    if not script.exists():
        print(f"  (no encontre {script.name}, no puedo ofrecer lanzarlo)")
        return
    try:
        ans = input("\n  Lanzar el loop ahora? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if ans not in ("y", "yes", "s", "si", "sí"):
        print("  OK, no lanzo nada.")
        return
    print("  Lanzando...")
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(script)],
            check=False,
        )
    except Exception as e:
        print(f"  ERROR al lanzar: {e}")


def main():
    print("=== Loop status ===")
    print(f"  Hora actual (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    print("Proceso ingest:")
    proc = find_ingest_process()
    process_down = False
    if proc is None:
        print("  [WARN] No se detecto ningun proceso ingest.py corriendo.")
        process_down = True
    elif isinstance(proc, str):
        print(f"  {proc}")
    else:
        pid, ram_mb, cd = proc
        print(f"  PID {pid} | {ram_mb} MB RAM | start: {cd}")
    print()

    name, age = latest_snapshot_age_minutes()
    print("Ultimo snapshot:")
    if name is None:
        print("  [WARN] Sin snapshots en disco.")
    else:
        marker = "[OK]" if age < 20 else ("[WARN]" if age < 60 else "[STALE]")
        print(f"  {marker} {name} (hace {age:.1f} min)")
    print()

    print("Snapshots por dia (ultimos 6):")
    for d, n in count_per_day(5):
        bar = "#" * min(n, 50)
        print(f"  {d}: {n:>3}  {bar}")
    print("  (esperado ~138/dia con cadencia de 10 min)")
    print()

    bcb = bcb_latest()
    print("BCB referencial:")
    if bcb:
        print(f"  Ultima fecha: {bcb.get('fecha')} | Compra {bcb.get('compra')} | Venta {bcb.get('venta')}")
    else:
        print("  [WARN] No se pudo leer bcb_referencial.json")
    print()

    warn, err = recent_log_issues(24)
    print(f"Logs (ultimas 24 h): {warn} WARNING, {err} ERROR")
    if warn or err:
        print(f"  Revisar: {LOG_FILE}")

    if process_down:
        offer_to_start_loop()


if __name__ == "__main__":
    main()
