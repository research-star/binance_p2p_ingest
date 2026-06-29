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
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── Paths y constantes ────────────────────────────────────────────────────

REPO_ROOT = Path("/opt/binance_p2p")
VENV_PYTHON = REPO_ROOT / ".venv/bin/python"
DASHBOARD_SCRIPT = "dashboard.py"
DB_PATH = REPO_ROOT / "p2p_normalized.db"
STATIC_DIR = REPO_ROOT / "static"
RIESGO_DIR = REPO_ROOT / "riesgo_propio"   # own-math riesgo-país calculator + panels

WORKTREE_PATH = Path("/tmp/gh-pages-publish-wt")
TMP_INDEX_PATH = Path("/tmp/publish_dashboard_index.html")
LOCK_PATH = Path("/tmp/publish_dashboard.lock")
LAST_SIZE_STATE_PATH = Path("/var/log/binance_p2p/publish_dashboard.last_size")

MIN_INDEX_SIZE_BYTES = 200_000
SHRINK_RATIO_FLOOR = 0.20

# Mirror de ocultos: el worker Cloudflare /v1/hidden es la fuente de verdad;
# noticias_hidden (en la DB) es solo cache local para el filtro de dashboard.py.
HIDDEN_API_URL = "https://api.finanzasbo.com/v1/hidden"
HIDDEN_FETCH_TIMEOUT_S = 5  # corto: el publish no debe colgarse por el fetch
# UA explícito: Cloudflare delante del worker devuelve 403 al UA default de
# urllib ("Python-urllib/x.y"). Cualquier UA identificable pasa (200).
HIDDEN_USER_AGENT = "finanzasbo-publish/1.0"
_HEX16_RE = re.compile(r"^[0-9a-f]{16}$")

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


def db_metrics() -> tuple[int, int, str | None, str | None, str | None]:
    """Devuelve (n_snapshots_ads, n_rows_ads, max_fecha_embi, max_periodo_ipc,
    max_periodo_ipp).

    `max_fecha_embi` se incluye en la cache key porque embi_spreads se puebla
    desde un cron independiente y, sin esto, un publish puede skipear cuando
    `ads` no avanzó pero embi sí. Elegimos max(fecha) por simpleza vs hash del
    payload completo: cualquier append de día nuevo dispara republish, y el
    parser UPSERT no produce overwrites silenciosos del mismo (fecha,pais) (los
    valores históricos son inmutables salvo correcciones — y una corrección
    igual debe disparar republish, lo cual implica chequear más que max(fecha)
    en un fix futuro si surge el caso).

    `max_periodo_ipc` / `max_periodo_ipp` (tablas ine_ipc / ine_ipp): misma
    lógica para los releases mensuales del INE. El MAX exige `valor IS NOT
    NULL` porque el parser INE persiste filas placeholder (valor NULL) para
    los meses futuros del año en curso — sin el filtro, la key quedaría
    clavada en diciembre y un release nuevo no republicaría. Mismo caveat que
    EMBI: una revisión retroactiva sin mes nuevo no cambia la key.
    """
    try:
        c = sqlite3.connect(str(DB_PATH))
        n_snap = c.execute("SELECT COUNT(DISTINCT snapshot_ts_utc) FROM ads").fetchone()[0]
        n_rows = c.execute("SELECT COUNT(*) FROM ads").fetchone()[0]
        try:
            embi_max = c.execute("SELECT MAX(fecha) FROM embi_spreads").fetchone()[0]
        except sqlite3.OperationalError:
            embi_max = None  # tabla aún no existe

        def _ine_max(table: str) -> str | None:
            try:
                return c.execute(
                    f"SELECT MAX(periodo) FROM {table} WHERE valor IS NOT NULL"
                ).fetchone()[0]
            except sqlite3.OperationalError:
                return None  # tabla aún no existe

        ipc_max = _ine_max("ine_ipc")
        ipp_max = _ine_max("ine_ipp")
        c.close()
        return n_snap, n_rows, embi_max, ipc_max, ipp_max
    except Exception:
        return 0, 0, None, None, None


def read_last_state():
    """Devuelve dict {size, n_snap, n_rows, embi_max, ipc_max, ipp_max,
    hidden_v} o None.

    Acepta también los formatos legacy v1 (int), v2 (sin embi_max), v3 (sin
    ipc_max/ipp_max) y v4 (sin hidden_v). En esos casos los campos faltantes
    quedan en None, lo cual fuerza un republish la primera vez que la fuente
    correspondiente cambia. Para hidden_v: un fetch exitoso de /v1/hidden
    devuelve un string (incluso "" para el set vacío), distinto de None → la
    primera corrida tras este deploy republica una vez.
    """
    if not LAST_SIZE_STATE_PATH.exists():
        return None
    try:
        raw = LAST_SIZE_STATE_PATH.read_text().strip()
        if raw.startswith("{"):
            state = json.loads(raw)
            state.setdefault("embi_max", None)
            state.setdefault("ipc_max", None)
            state.setdefault("ipp_max", None)
            state.setdefault("hidden_v", None)
            return state
        return {"size": int(raw), "n_snap": None, "n_rows": None,
                "embi_max": None, "ipc_max": None, "ipp_max": None,
                "hidden_v": None}
    except (ValueError, OSError):
        return None


def write_last_state(size: int, n_snap: int, n_rows: int, embi_max: str | None,
                     ipc_max: str | None, ipp_max: str | None,
                     hidden_v: str | None):
    state = {"size": size, "n_snap": n_snap, "n_rows": n_rows,
             "embi_max": embi_max, "ipc_max": ipc_max, "ipp_max": ipp_max,
             "hidden_v": hidden_v}
    try:
        LAST_SIZE_STATE_PATH.write_text(json.dumps(state))
    except OSError as e:
        emit(f"[publish] WARN no pude escribir state: {e}")


# ── Mirror de ocultos (/v1/hidden → noticias_hidden) ─────────────────────────

def fetch_hidden() -> "tuple[list[str], str] | None":
    """GET /v1/hidden (worker Cloudflare) → (ids_16hex, v).

    Devuelve None ante CUALQUIER anomalía (red, timeout, status != 200, JSON
    inválido, shape inesperado). El caller trata None como fail-toward-stale:
    preserva la mirror y reusa el hidden_v previo. Mismo espíritu que el
    try/except del git pull de _run().

    Filtra ids que no sean strings de 16 hex (defensa en profundidad): el
    worker es la fuente de verdad y solo emite ids 16-hex, pero la mirror no
    debe poblarse con basura aunque el contrato se rompa. `v` se devuelve tal
    cual lo dio el worker (no se recomputa): es la fuente de verdad de la
    versión del set.
    """
    try:
        req = urllib.request.Request(
            HIDDEN_API_URL,
            headers={"Accept": "application/json",
                     "User-Agent": HIDDEN_USER_AGENT})
        with urllib.request.urlopen(req, timeout=HIDDEN_FETCH_TIMEOUT_S) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            if status != 200:
                emit(f"[publish] mode=warn stage=fetch_hidden detail=status "
                     f"status={status}")
                return None
            raw = resp.read()
    except Exception as e:  # URLError, timeout socket, etc.
        emit(f"[publish] mode=warn stage=fetch_hidden detail=net "
             f"err={type(e).__name__}:{str(e)[:120]}")
        return None

    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as e:
        emit(f"[publish] mode=warn stage=fetch_hidden detail=bad_json "
             f"err={str(e)[:120]}")
        return None

    if not isinstance(payload, dict):
        emit("[publish] mode=warn stage=fetch_hidden detail=shape root_not_object")
        return None
    ids = payload.get("ids")
    v = payload.get("v")
    if not isinstance(ids, list) or not isinstance(v, str):
        emit("[publish] mode=warn stage=fetch_hidden detail=shape ids_or_v")
        return None

    valid = [x for x in ids if isinstance(x, str) and _HEX16_RE.match(x)]
    skipped = len(ids) - len(valid)
    if skipped:
        emit(f"[publish] mode=warn stage=fetch_hidden detail=skipped_invalid "
             f"n={skipped}")
    return valid, v


def sync_hidden_mirror(ids):
    """Reemplaza el contenido de noticias_hidden por exactamente `ids`.

    Transaccional: o queda el set nuevo completo, o la mirror no se toca
    (ROLLBACK ante cualquier error — nunca a medias). Self-create idempotente
    con el MISMO DDL que dashboard.py y la migración 0003: en el VPS no corre
    runner de migraciones, así que esta función no puede asumir que la tabla
    exista. Re-filtra a 16-hex (defensa en profundidad, aunque fetch_hidden ya
    valida) — el PK NOT NULL es el último backstop contra ids nulos.
    """
    clean = [(x,) for x in ids if isinstance(x, str) and _HEX16_RE.match(x)]
    conn = sqlite3.connect(str(DB_PATH), isolation_level=None)  # autocommit; tx manual
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS noticias_hidden "
                     "(id TEXT NOT NULL PRIMARY KEY)")
        conn.execute("BEGIN")
        conn.execute("DELETE FROM noticias_hidden")
        conn.executemany(
            "INSERT OR IGNORE INTO noticias_hidden(id) VALUES (?)", clean)
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass
        raise
    finally:
        conn.close()


# ── Riesgo-país own-math injection (fail-safe) ───────────────────────────────

def _inject_riesgo(index_path: Path) -> None:
    """Compute the live own-math riesgo-país number, rebuild the historical
    series, and inject the panels into the freshly-built index.html.

    Strictly fail-safe: ANY error is logged and swallowed so the normal
    dashboard still publishes (worst case the panels are absent this cycle).
    Each sub-step runs with check=False; live_bolivia.py degrades to the
    snapshot if Playwright/venue is unavailable, so this never blocks publish.
    """
    try:
        if not RIESGO_DIR.exists():
            return
        py = str(VENV_PYTHON)
        run([py, str(RIESGO_DIR / "live_bolivia.py")], check=False)       # live point
        run([py, str(RIESGO_DIR / "build_historical.py")], check=False)   # history
        r = run([py, str(RIESGO_DIR / "inject_into_site.py"),
                 str(index_path)], check=False)                           # panels
        emit(f"[publish] mode=ok stage=riesgo_inject rc={r.returncode}")
    except Exception as e:
        emit(f"[publish] mode=warn stage=riesgo_inject detail=skipped "
             f"err={type(e).__name__}:{str(e)[:160]}")


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

    n_snap, n_rows, embi_max, ipc_max, ipp_max = db_metrics()
    last = read_last_state()

    # Sync de la mirror de ocultos: DESPUÉS del git pull, ANTES del skip-fast,
    # para que el skip-fast decida con hidden_v y la mirror ya actualizados.
    # hidden_v entra a la cache key → un cambio en el set de ocultos fuerza
    # republish aunque ads no avance. Fail-toward-stale ESTRICTO: si el fetch
    # (o el sync) falla, NO se toca la mirror y hidden_v queda en el último
    # valor conocido → skip-fast neutral (ni republish forzado ni blanqueo).
    hidden_v = (last or {}).get("hidden_v")  # default: último conocido (stale-safe)
    fetched = fetch_hidden()
    if fetched is not None:
        ids, v = fetched
        try:
            sync_hidden_mirror(ids)
            hidden_v = v  # solo avanza si fetch Y sync salieron OK
            emit(f"[publish] mode=ok stage=hidden_sync n_ids={len(ids)} "
                 f"hidden_v={v or '∅'}")
        except Exception as e:
            emit(f"[publish] mode=warn stage=hidden_sync detail=mirror_preserved "
                 f"err={type(e).__name__}:{str(e)[:120]}")
    # (si fetched is None, fetch_hidden ya logueó; hidden_v queda en el previo)

    # Skip rápido si el dataset no avanzó (ahorra el gasto de dashboard.py)
    if (last is not None
            and last.get("n_snap") == n_snap
            and last.get("n_rows") == n_rows
            and last.get("embi_max") == embi_max
            and last.get("ipc_max") == ipc_max
            and last.get("ipp_max") == ipp_max
            and last.get("hidden_v") == hidden_v
            and last.get("size") is not None):
        # Refresh state mtime sin cambiar contenido (idempotente)
        write_last_state(last["size"], n_snap, n_rows, embi_max, ipc_max,
                         ipp_max, hidden_v)
        total_s = time.time() - t0
        emit(f"[publish] mode=skip reason=dataset_unchanged "
             f"snapshots={n_snap} rows={n_rows} embi_max={embi_max} "
             f"ipc_max={ipc_max} ipp_max={ipp_max} hidden_v={hidden_v or '∅'} "
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

    # Inyectar los paneles riesgo-país own-math en el HTML ya validado (fail-safe:
    # si falla, se publica el dashboard normal sin los paneles).
    _inject_riesgo(TMP_INDEX_PATH)

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
        return _commit_and_push(t0, gen_s, new_size, n_snap, n_rows,
                                embi_max, ipc_max, ipp_max, hidden_v)
    finally:
        cleanup_worktree(WORKTREE_PATH)
        if TMP_INDEX_PATH.exists():
            TMP_INDEX_PATH.unlink()


def _commit_and_push(t0: float, gen_s: float, new_size: int,
                     n_snap: int, n_rows: int, embi_max: str | None,
                     ipc_max: str | None, ipp_max: str | None,
                     hidden_v: str | None) -> int:
    existing_index = WORKTREE_PATH / "index.html"
    shutil.copyfile(TMP_INDEX_PATH, existing_index)

    if STATIC_DIR.exists():
        for asset in STATIC_DIR.iterdir():
            if asset.is_file():
                shutil.copyfile(asset, WORKTREE_PATH / asset.name)

    # Feeds de datos riesgo-país (servidos como /riesgo_propio_live.json etc.).
    for jn in ("riesgo_propio_live.json", "riesgo_propio.json"):
        src = RIESGO_DIR / jn
        if src.exists():
            try:
                shutil.copyfile(src, WORKTREE_PATH / jn)
            except OSError:
                pass

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    msg = f"dashboard: {ts} snapshots={n_snap} rows={n_rows}"

    try:
        run(["git", "add", "-A"], cwd=str(WORKTREE_PATH))
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

    write_last_state(new_size, n_snap, n_rows, embi_max, ipc_max, ipp_max,
                     hidden_v)

    total_s = time.time() - t0
    size_kb = new_size / 1024
    emit(f"[publish] mode=ok size={size_kb:.1f}KB "
         f"snapshots={n_snap} rows={n_rows} hidden_v={hidden_v or '∅'} "
         f"commit={commit_short} "
         f"gen_s={gen_s:.2f} push_s={push_s:.2f} total_s={total_s:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
