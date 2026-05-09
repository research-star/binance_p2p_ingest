#!/usr/bin/env python3
"""
publish_dashboard.py — Genera index.html via dashboard.py y lo pushea a gh-pages.

Diseñado para correr vía cron cada 12 min en el VPS productivo. La rama
`gh-pages` en el remoto es orphan (sin parent en main) y GH Pages la sirve
desde root como https://research-star.github.io/binance_p2p_ingest/.

Mecánica:
- Lockfile cooperativo (PID-aware), mismo patrón que normalize.py / backup.py.
- Worktree temporal de origin/gh-pages para hacer commit aislado.
- Skip rápido cuando el dataset no avanzó: comparamos (n_snapshots, n_rows)
  contra el último publish exitoso ANTES de regenerar el HTML, ahorrando
  el gasto del dashboard.py si no hay nada nuevo. Sha256 del HTML no sirve
  como identity check porque dashboard.py embebe timestamps de generación
  que mutan run-to-run.
- Cleanup garantizado del worktree y del index temp en try/finally.
- Validación de tamaño: mínimo absoluto + chequeo secundario contra el último
  publish exitoso (ratio floor) para detectar generación severamente truncada.
"""

import contextlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Paths y constantes ────────────────────────────────────────────────────

REPO_ROOT = Path("/opt/binance_p2p")
VENV_PYTHON = REPO_ROOT / ".venv/bin/python"
DASHBOARD_SCRIPT = "dashboard.py"
DB_PATH = REPO_ROOT / "p2p_normalized.db"

WORKTREE_PATH = Path("/tmp/gh-pages-publish-wt")
TMP_INDEX_PATH = Path("/tmp/publish_dashboard_index.html")
LOCK_PATH = Path("/tmp/publish_dashboard.lock")
LAST_SIZE_STATE_PATH = Path("/var/log/binance_p2p/publish_dashboard.last_size")

MIN_INDEX_SIZE_BYTES = 500_000
SHRINK_RATIO_FLOOR = 0.50

GIT_USER_NAME = "binance VPS"
GIT_USER_EMAIL = "vps@p2p-ingest-prod"
PUBLISH_BRANCH_LOCAL = "gh-pages-publish"
REMOTE = "origin"
REMOTE_BRANCH = "gh-pages"


def emit(line: str):
    print(line, file=sys.stderr, flush=True)


# ── Lockfile ───────────────────────────────────────────────────────────────

def _pid_alive(pid: int) -> bool:
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


# ── Helpers ────────────────────────────────────────────────────────────────

def run(cmd, cwd=None, check=True):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)


def cleanup_worktree(path: Path):
    if not path.exists():
        return
    subprocess.run(["git", "worktree", "remove", "--force", str(path)],
                   cwd=str(REPO_ROOT), capture_output=True, text=True, check=False)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def db_metrics() -> tuple[int, int]:
    try:
        c = sqlite3.connect(str(DB_PATH))
        n_snap = c.execute("SELECT COUNT(DISTINCT snapshot_ts_utc) FROM ads").fetchone()[0]
        n_rows = c.execute("SELECT COUNT(*) FROM ads").fetchone()[0]
        c.close()
        return n_snap, n_rows
    except Exception:
        return 0, 0


def read_last_state():
    """Devuelve dict {size, n_snap, n_rows} o None.

    Acepta también el formato legacy v1 donde el archivo era solo un int (size).
    En ese caso devuelve {size: <int>, n_snap: None, n_rows: None}.
    """
    if not LAST_SIZE_STATE_PATH.exists():
        return None
    try:
        raw = LAST_SIZE_STATE_PATH.read_text().strip()
        if raw.startswith("{"):
            return json.loads(raw)
        return {"size": int(raw), "n_snap": None, "n_rows": None}
    except (ValueError, OSError):
        return None


def write_last_state(size: int, n_snap: int, n_rows: int):
    state = {"size": size, "n_snap": n_snap, "n_rows": n_rows}
    try:
        LAST_SIZE_STATE_PATH.write_text(json.dumps(state))
    except OSError as e:
        emit(f"[publish] WARN no pude escribir state: {e}")


# ── Main flow ──────────────────────────────────────────────────────────────

def main() -> int:
    t0 = time.time()

    cleanup_worktree(WORKTREE_PATH)
    if TMP_INDEX_PATH.exists():
        TMP_INDEX_PATH.unlink()

    with pid_lock(LOCK_PATH) as acquired:
        if not acquired:
            emit("[publish] otra instancia activa, saliendo limpio")
            return 0
        return _run(t0)


def _run(t0: float) -> int:
    # Auto-pull: traer cambios de main antes de regenerar.
    # Si falla (conflicto, otra branch, red), log warning y seguir.
    try:
        run(["git", "pull", "--ff-only", "origin", "main"], cwd=str(REPO_ROOT))
    except subprocess.CalledProcessError as e:
        emit(f"[publish] mode=warn stage=auto_pull rc={e.returncode} "
             f"stderr={(e.stderr or '')[:200]}")
        # No fallamos: seguimos con el código local.

    # Skip rápido si el dataset no avanzó (ahorra el gasto de dashboard.py)
    n_snap, n_rows = db_metrics()
    last = read_last_state()
    if (last is not None
            and last.get("n_snap") == n_snap
            and last.get("n_rows") == n_rows
            and last.get("size") is not None):
        # Refresh state mtime sin cambiar contenido (idempotente)
        write_last_state(last["size"], n_snap, n_rows)
        total_s = time.time() - t0
        emit(f"[publish] mode=skip reason=dataset_unchanged "
             f"snapshots={n_snap} rows={n_rows} "
             f"total_s={total_s:.2f}")
        return 0

    # Generar HTML
    t_gen0 = time.time()
    try:
        run([str(VENV_PYTHON), DASHBOARD_SCRIPT,
             "--output", str(TMP_INDEX_PATH)], cwd=str(REPO_ROOT))
    except subprocess.CalledProcessError as e:
        emit(f"[publish] mode=error stage=dashboard_generation rc={e.returncode} "
             f"stderr={(e.stderr or '')[:300]}")
        return 1
    gen_s = time.time() - t_gen0

    # Validación de tamaño
    if not TMP_INDEX_PATH.exists():
        emit("[publish] mode=error stage=validate detail=output_missing")
        return 1
    new_size = TMP_INDEX_PATH.stat().st_size

    if new_size < MIN_INDEX_SIZE_BYTES:
        emit(f"[publish] mode=error stage=validate detail=size_too_small "
             f"size={new_size} min={MIN_INDEX_SIZE_BYTES}")
        TMP_INDEX_PATH.unlink()
        return 1

    if last is not None and last.get("size"):
        floor = int(last["size"] * SHRINK_RATIO_FLOOR)
        if new_size < floor:
            emit(f"[publish] mode=error stage=validate detail=size_shrink "
                 f"size={new_size} last={last['size']} ratio_floor={SHRINK_RATIO_FLOOR}")
            TMP_INDEX_PATH.unlink()
            return 1

    # Worktree desde origin/gh-pages
    try:
        run(["git", "fetch", REMOTE, REMOTE_BRANCH], cwd=str(REPO_ROOT))
        run(["git", "worktree", "add", "-B", PUBLISH_BRANCH_LOCAL,
             str(WORKTREE_PATH), f"{REMOTE}/{REMOTE_BRANCH}"], cwd=str(REPO_ROOT))
    except subprocess.CalledProcessError as e:
        emit(f"[publish] mode=error stage=worktree_setup rc={e.returncode} "
             f"stderr={(e.stderr or '')[:300]}")
        if TMP_INDEX_PATH.exists():
            TMP_INDEX_PATH.unlink()
        return 1

    try:
        return _commit_and_push(t0, gen_s, new_size, n_snap, n_rows)
    finally:
        cleanup_worktree(WORKTREE_PATH)
        if TMP_INDEX_PATH.exists():
            TMP_INDEX_PATH.unlink()


def _commit_and_push(t0: float, gen_s: float, new_size: int,
                     n_snap: int, n_rows: int) -> int:
    existing_index = WORKTREE_PATH / "index.html"
    shutil.copyfile(TMP_INDEX_PATH, existing_index)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    msg = f"dashboard: {ts} snapshots={n_snap} rows={n_rows}"

    try:
        run(["git", "add", "index.html"], cwd=str(WORKTREE_PATH))
        run(["git",
             "-c", f"user.name={GIT_USER_NAME}",
             "-c", f"user.email={GIT_USER_EMAIL}",
             "commit", "-m", msg], cwd=str(WORKTREE_PATH))
    except subprocess.CalledProcessError as e:
        emit(f"[publish] mode=error stage=commit rc={e.returncode} "
             f"stderr={(e.stderr or '')[:300]}")
        return 1

    t_push0 = time.time()
    try:
        run(["git", "push", REMOTE,
             f"{PUBLISH_BRANCH_LOCAL}:{REMOTE_BRANCH}"], cwd=str(WORKTREE_PATH))
    except subprocess.CalledProcessError as e:
        emit(f"[publish] mode=error stage=push rc={e.returncode} "
             f"stderr={(e.stderr or '')[:300]}")
        return 1
    push_s = time.time() - t_push0

    try:
        r = run(["git", "rev-parse", "--short", "HEAD"], cwd=str(WORKTREE_PATH))
        commit_short = r.stdout.strip()
    except subprocess.CalledProcessError:
        commit_short = "?"

    write_last_state(new_size, n_snap, n_rows)

    total_s = time.time() - t0
    size_kb = new_size / 1024
    emit(f"[publish] mode=ok size={size_kb:.1f}KB "
         f"snapshots={n_snap} rows={n_rows} commit={commit_short} "
         f"gen_s={gen_s:.2f} push_s={push_s:.2f} total_s={total_s:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
