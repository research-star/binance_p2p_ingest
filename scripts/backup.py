#!/usr/bin/env python3
"""
backup.py — Backup laptop-pull desde el VPS vía ssh / scp / sftp.

Diseño: la laptop hace pull desde el VPS (no el VPS push). Sin servicios
recurrentes pagos. Mismo workflow Win11 (Git Bash) y Linux.

Subcomandos:
    db          ssh sqlite3 .backup remoto -> scp -> ~/backups/db/<stamp>.db
    snapshots   ssh+find diff vs local -> sftp batch get de los nuevos
    prune       Aplica retención GFS sobre ~/backups/db/
    verify      Cuenta y tamaños de backups locales
    restore     Copia una versión a un dir destino
    status      Resumen rápido

Lee credenciales desde `backup.env` en la raíz del repo (gitignored).
Plantilla en `backup.env.example`.

Política de retención GFS (solo db/, snapshots/ se conservan forever):
    7 daily   — más reciente de cada uno de los últimos 7 días distintos con backup
    4 weekly  — más antiguo de cada una de las 4 ISO weeks anteriores al daily
    3 monthly — más antiguo de cada uno de los 3 meses anteriores al weekly
    Total: hasta 14 versiones, ~125 días de cobertura.

Notas:
- Snapshots son inmutables. Pull incremental por filename diff (sftp batch
  get). Equivalente semántico a `rsync --ignore-existing` sin requerir rsync.
- En el VPS hay que tener `sqlite3` (apt install sqlite3 — ~200 KB).
- `--port` configurable (default 22). Hetzner Storage Box usaría 23, pero acá
  el target es un VPS Linux, no Storage Box.
"""

import argparse
import contextlib
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from datetime import date
from pathlib import Path

DB_TS_FORMAT = "%Y-%m-%dT%H%M%SZ"
DB_NAME_RE = re.compile(r"^p2p_normalized_(\d{4}-\d{2}-\d{2}T\d{6}Z)\.db$")

REQUIRED_VARS = (
    "VPS_HOST", "VPS_USER", "VPS_DB_PATH", "VPS_SNAPSHOTS_PATH",
    "SSH_KEY_PATH", "LOCAL_BACKUP_ROOT",
)
OPTIONAL_VARS = ("VPS_PORT",)
DEFAULT_VPS_PORT = "22"
SSH_CONNECT_TIMEOUT = "15"  # segundos


def emit(line: str):
    print(line, file=sys.stderr, flush=True)


# ── Env loader ─────────────────────────────────────────────────────────────

def load_env(path: Path) -> dict:
    if not path.exists():
        emit(f"[backup] ERROR backup.env no existe: {path}")
        emit("[backup] copiá backup.env.example y completá los valores")
        sys.exit(2)
    env: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        ln = raw.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    missing = [k for k in REQUIRED_VARS if not env.get(k)]
    if missing:
        emit(f"[backup] ERROR variables faltantes en {path.name}: {missing}")
        sys.exit(2)
    env["SSH_KEY_PATH"] = os.path.expanduser(env["SSH_KEY_PATH"])
    env["LOCAL_BACKUP_ROOT"] = os.path.expanduser(env["LOCAL_BACKUP_ROOT"])
    env.setdefault("VPS_PORT", DEFAULT_VPS_PORT)
    if not Path(env["SSH_KEY_PATH"]).exists():
        emit(f"[backup] ERROR SSH key no existe: {env['SSH_KEY_PATH']}")
        sys.exit(2)
    return env


# ── SSH / SCP / SFTP helpers ───────────────────────────────────────────────

def _ssh_base(env: dict) -> list[str]:
    return [
        "ssh",
        "-i", env["SSH_KEY_PATH"],
        "-p", env["VPS_PORT"],
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
        "-o", "BatchMode=yes",
    ]


def _scp_base(env: dict) -> list[str]:
    return [
        "scp",
        "-i", env["SSH_KEY_PATH"],
        "-P", env["VPS_PORT"],
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
        "-o", "BatchMode=yes",
        "-q",
    ]


def _sftp_base(env: dict) -> list[str]:
    return [
        "sftp",
        "-i", env["SSH_KEY_PATH"],
        "-P", env["VPS_PORT"],
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
        "-o", "BatchMode=yes",
        "-q",
    ]


def _vps_target(env: dict) -> str:
    return f"{env['VPS_USER']}@{env['VPS_HOST']}"


def ssh_run(env: dict, remote_cmd: str, *,
            check: bool = False) -> subprocess.CompletedProcess:
    cmd = _ssh_base(env) + [_vps_target(env), remote_cmd]
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


# ── Lockfile (igual a normalize.py) ────────────────────────────────────────

def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@contextlib.contextmanager
def pid_lock(lock_path: Path):
    acquired = False
    for _ in range(2):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            try:
                old_pid = int(lock_path.read_text().strip())
            except (ValueError, OSError):
                old_pid = -1
            if old_pid > 0 and _pid_alive(old_pid):
                break
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
    try:
        yield acquired
    finally:
        if acquired:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


# ── GFS retention (igual al PR previo, testeable independiente) ────────────

def gfs_keep_set(timestamps: list[datetime],
                 daily: int = 7, weekly: int = 4, monthly: int = 3) -> set[datetime]:
    """Retorna el subconjunto de timestamps a CONSERVAR según política GFS.

    - daily: 7 más recientes días DISTINTOS con ≥1 backup; del día → keep el
      más reciente. Gaps en el calendario son saltados.
    - weekly: 4 ISO weeks más recientes que NO se cruzan con la tramo daily;
      de cada semana → keep el más antiguo.
    - monthly: 3 meses más recientes anteriores al tramo weekly; de cada mes
      → keep el más antiguo.

    No requiere `now`: deriva todo del propio dataset.
    """
    if not timestamps:
        return set()
    keep: set[datetime] = set()

    by_day: dict[date, list[datetime]] = {}
    for ts in timestamps:
        by_day.setdefault(ts.date(), []).append(ts)
    daily_days = sorted(by_day.keys(), reverse=True)[:daily]
    daily_days_set = set(daily_days)
    for d in daily_days:
        keep.add(max(by_day[d]))

    daily_weeks: set[tuple[int, int]] = set()
    for d in daily_days_set:
        iso = d.isocalendar()
        daily_weeks.add((iso.year, iso.week))
    earliest_daily_week = min(daily_weeks) if daily_weeks else None

    by_week: dict[tuple[int, int], list[datetime]] = {}
    for ts in timestamps:
        if ts in keep:
            continue
        iso = ts.isocalendar()
        wk = (iso.year, iso.week)
        if wk in daily_weeks:
            continue
        if earliest_daily_week is not None and wk >= earliest_daily_week:
            continue
        by_week.setdefault(wk, []).append(ts)
    weekly_weeks = sorted(by_week.keys(), reverse=True)[:weekly]
    for wk in weekly_weeks:
        keep.add(min(by_week[wk]))

    cutoff_month: tuple[int, int] | None = None
    if weekly_weeks:
        earliest_weekly_week = min(weekly_weeks)
        earliest_weekly_ts = min(by_week[earliest_weekly_week])
        cutoff_month = (earliest_weekly_ts.year, earliest_weekly_ts.month)
    elif daily_days_set:
        ed = min(daily_days_set)
        cutoff_month = (ed.year, ed.month)

    by_month: dict[tuple[int, int], list[datetime]] = {}
    for ts in timestamps:
        if ts in keep:
            continue
        mo = (ts.year, ts.month)
        if cutoff_month is not None and mo >= cutoff_month:
            continue
        by_month.setdefault(mo, []).append(ts)
    monthly_months = sorted(by_month.keys(), reverse=True)[:monthly]
    for mo in monthly_months:
        keep.add(min(by_month[mo]))

    return keep


# ── Listado local ──────────────────────────────────────────────────────────

def list_local_db_versions(env: dict) -> list[tuple[datetime, Path, int]]:
    """[(ts, path, size_bytes), ...] ordenado por ts ASC."""
    db_dir = Path(env["LOCAL_BACKUP_ROOT"]) / "db"
    if not db_dir.is_dir():
        return []
    out: list[tuple[datetime, Path, int]] = []
    for p in db_dir.iterdir():
        if not p.is_file():
            continue
        m = DB_NAME_RE.match(p.name)
        if not m:
            continue
        ts = datetime.strptime(m.group(1), DB_TS_FORMAT).replace(tzinfo=timezone.utc)
        out.append((ts, p, p.stat().st_size))
    return sorted(out)


# ── Subcomandos ────────────────────────────────────────────────────────────

def cmd_db(env: dict, args) -> int:
    stamp = datetime.now(timezone.utc).strftime(DB_TS_FORMAT)
    target_name = f"p2p_normalized_{stamp}.db"
    local_dir = Path(env["LOCAL_BACKUP_ROOT"]) / "db"
    local_dir.mkdir(parents=True, exist_ok=True)
    target_local = local_dir / target_name
    remote_tmp = f"/tmp/p2p_backup_{stamp}.db"

    t0 = time.time()
    # 1. ssh + sqlite3 .backup en el VPS
    src = env["VPS_DB_PATH"]
    remote_cmd = f"sqlite3 {shlex.quote(src)} \".backup '{remote_tmp}'\""
    r = ssh_run(env, remote_cmd)
    if r.returncode != 0:
        emit(f"[backup] ERROR ssh sqlite3 .backup rc={r.returncode}: "
             f"{r.stderr.strip()[:300]}")
        return 1
    backup_s = time.time() - t0

    # 2. scp pull (con cleanup garantizado en finally)
    t1 = time.time()
    scp_cmd = (_scp_base(env)
               + [f"{_vps_target(env)}:{remote_tmp}", str(target_local)])
    rc = 0
    try:
        r = subprocess.run(scp_cmd, capture_output=True, text=True)
        if r.returncode != 0:
            emit(f"[backup] ERROR scp rc={r.returncode}: {r.stderr.strip()[:300]}")
            rc = 1
    finally:
        # 3. cleanup remote tmp (best-effort)
        ssh_run(env, f"rm -f {shlex.quote(remote_tmp)}")
    upload_s = time.time() - t1

    if rc != 0:
        try:
            target_local.unlink()
        except FileNotFoundError:
            pass
        return rc

    size_mb = target_local.stat().st_size / (1024 * 1024)
    emit(f"[backup] mode=db target={target_name} size_mb={size_mb:.1f} "
         f"sqlite_backup_s={backup_s:.2f} scp_pull_s={upload_s:.2f}")
    return 0


def cmd_snapshots(env: dict, args) -> int:
    """Pull incremental: lista remoto via find, diff por filename con local,
    descarga solo los nuevos via sftp -b batch mode."""
    local_root = Path(env["LOCAL_BACKUP_ROOT"]) / "snapshots"
    local_root.mkdir(parents=True, exist_ok=True)

    # 1. Listar archivos remotos (relative paths desde VPS_SNAPSHOTS_PATH)
    remote_root = env["VPS_SNAPSHOTS_PATH"].rstrip("/")
    find_cmd = (f"cd {shlex.quote(remote_root)} && "
                f"find . -type f \\( -name '*.json.gz' -o -name '*.json' \\)")
    r = ssh_run(env, find_cmd)
    if r.returncode != 0:
        emit(f"[backup] ERROR ssh find rc={r.returncode}: {r.stderr.strip()[:300]}")
        return 1
    remote_files = sorted(
        ln[2:] if ln.startswith("./") else ln
        for ln in r.stdout.splitlines() if ln.strip()
    )

    # 2. Listar locales
    local_files = set()
    for p in local_root.rglob("*"):
        if p.is_file() and (p.suffix == ".gz" or p.suffix == ".json"):
            rel = p.relative_to(local_root).as_posix()
            local_files.add(rel)

    to_pull = [f for f in remote_files if f not in local_files]
    if not to_pull:
        emit(f"[backup] mode=snapshots remote={len(remote_files)} "
             f"local={len(local_files)} new=0 (no work)")
        return 0

    # 3. Crear directorios locales necesarios
    for rel in to_pull:
        (local_root / rel).parent.mkdir(parents=True, exist_ok=True)

    # 4. sftp batch get
    # cd al dir base remoto, luego get RELPATH LOCALPATH para cada archivo
    batch_lines = [f"cd {remote_root}"]
    for rel in to_pull:
        local_path = (local_root / rel).as_posix()
        # sftp acepta paths con espacios si están entrecomillados
        batch_lines.append(f"get \"{rel}\" \"{local_path}\"")
    batch_lines.append("bye")
    batch_input = "\n".join(batch_lines) + "\n"

    t0 = time.time()
    sftp_cmd = _sftp_base(env) + ["-b", "-", _vps_target(env)]
    r = subprocess.run(sftp_cmd, input=batch_input,
                       capture_output=True, text=True)
    dt = time.time() - t0
    if r.returncode != 0:
        emit(f"[backup] ERROR sftp batch rc={r.returncode}: "
             f"{r.stderr.strip()[:500]}")
        return 1

    # Verificar que los archivos llegaron
    pulled = sum(1 for rel in to_pull if (local_root / rel).exists())
    emit(f"[backup] mode=snapshots remote={len(remote_files)} "
         f"local_before={len(local_files)} pulled={pulled}/{len(to_pull)} "
         f"duration_s={dt:.2f}")
    return 0 if pulled == len(to_pull) else 1


def cmd_prune(env: dict, args) -> int:
    versions = list_local_db_versions(env)
    if not versions:
        emit("[backup] mode=prune total=0 keep=0 delete=0 (no versions)")
        return 0
    keep = gfs_keep_set([v[0] for v in versions])
    to_delete = [v for v in versions if v[0] not in keep]

    if args.dry_run:
        emit(f"[backup] mode=prune dry_run=1 total={len(versions)} "
             f"keep={len(keep)} delete={len(to_delete)}")
        for _, p, _ in to_delete:
            emit(f"[backup]   would delete: {p.name}")
        return 0

    t0 = time.time()
    deleted = 0
    for _, p, _ in to_delete:
        try:
            p.unlink()
            deleted += 1
        except FileNotFoundError:
            deleted += 1  # ya no estaba, idem
        except OSError as e:
            emit(f"[backup] WARN delete fallo {p.name}: {e}")
    dt = time.time() - t0
    emit(f"[backup] mode=prune total={len(versions)} keep={len(keep)} "
         f"deleted={deleted} duration_s={dt:.2f}")
    return 0 if deleted == len(to_delete) else 1


def cmd_verify(env: dict, args) -> int:
    versions = list_local_db_versions(env)
    n = len(versions)
    db_mb = sum(v[2] for v in versions) / (1024 * 1024)
    print(f"db versiones:  {n}")
    print(f"db total:      {db_mb:.1f} MB")
    if versions:
        print(f"oldest:        {versions[0][1].name}")
        print(f"newest:        {versions[-1][1].name}")
    snap_root = Path(env["LOCAL_BACKUP_ROOT"]) / "snapshots"
    if snap_root.is_dir():
        cnt = sum(1 for p in snap_root.rglob("*") if p.is_file())
        size_mb = sum(p.stat().st_size for p in snap_root.rglob("*") if p.is_file()) / (1024 * 1024)
        print(f"snapshots:     {cnt} files, {size_mb:.1f} MB")
    else:
        print("snapshots:     (sin backups todavía)")
    return 0


def cmd_restore(env: dict, args) -> int:
    target = Path(args.target)
    target.mkdir(parents=True, exist_ok=True)
    versions = list_local_db_versions(env)
    if not versions:
        emit("[backup] ERROR no hay versiones en local")
        return 1
    if args.version:
        match = [v for v in versions if v[0].strftime(DB_TS_FORMAT) == args.version]
        if not match:
            emit(f"[backup] ERROR version no encontrada: {args.version}")
            emit(f"[backup] disponibles: {[v[1].name for v in versions]}")
            return 1
        ts, src, size = match[0]
    else:
        ts, src, size = versions[-1]
    dest = target / src.name
    shutil.copy2(src, dest)
    size_mb = size / (1024 * 1024)
    emit(f"[backup] mode=restore version={src.name} target={dest} "
         f"size_mb={size_mb:.1f}")
    return 0


def cmd_status(env: dict, args) -> int:
    versions = list_local_db_versions(env)
    if not versions:
        print("no hay versiones de db en local")
        return 0
    latest_ts, latest_path, _ = versions[-1]
    age_h = (datetime.now(timezone.utc) - latest_ts).total_seconds() / 3600
    db_mb = sum(v[2] for v in versions) / (1024 * 1024)
    keep = gfs_keep_set([v[0] for v in versions])
    print(f"versiones db locales:        {len(versions)}")
    print(f"última:                      {latest_path.name}")
    print(f"edad última:                 {age_h:.1f} h")
    print(f"espacio db local:            {db_mb:.1f} MB")
    print(f"versiones a conservar (GFS): {len(keep)}")
    print(f"se borrarían en próximo prune: {len(versions) - len(keep)}")

    snap_root = Path(env["LOCAL_BACKUP_ROOT"]) / "snapshots"
    if snap_root.is_dir():
        cnt = sum(1 for p in snap_root.rglob("*") if p.is_file())
        size_mb = sum(p.stat().st_size for p in snap_root.rglob("*") if p.is_file()) / (1024 * 1024)
        print(f"snapshots locales:           {cnt} files, {size_mb:.1f} MB")
    return 0


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Backup laptop-pull desde VPS")
    parser.add_argument("--env-file", type=Path, default=Path("backup.env"))
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("db", help="Pull SQLite consistente del VPS")
    sub.add_parser("snapshots", help="Pull incremental de snapshots/")
    p_pr = sub.add_parser("prune", help="GFS sobre ~/backups/db/")
    p_pr.add_argument("--dry-run", action="store_true")
    sub.add_parser("verify", help="Lista locales y conteos")
    p_rs = sub.add_parser("restore", help="Restaurar versión")
    p_rs.add_argument("--target", type=str, required=True)
    p_rs.add_argument("--version", type=str,
                      help="Stamp YYYY-MM-DDTHHMMSSZ (default: latest)")
    sub.add_parser("status", help="Resumen del estado")

    args = parser.parse_args()
    env = load_env(args.env_file)

    lock_path = Path(f".backup.{args.cmd}.lock")
    with pid_lock(lock_path) as acquired:
        if not acquired:
            emit(f"[backup] otra instancia activa (lock={lock_path}), saliendo limpio")
            return 0
        dispatch = {
            "db": cmd_db, "snapshots": cmd_snapshots, "prune": cmd_prune,
            "verify": cmd_verify, "restore": cmd_restore, "status": cmd_status,
        }
        return dispatch[args.cmd](env, args)


if __name__ == "__main__":
    sys.exit(main())
