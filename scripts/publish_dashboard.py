#!/usr/bin/env python3
"""
publish_dashboard.py — Genera index.html (ES) + en/index.html (EN) via
dashboard.py, los pushea a gh-pages y hace dual-publish del mismo bake a
Cloudflare Pages.

Diseñado para correr vía cron cada 12 min en el VPS productivo. La rama
`gh-pages` en el remoto es orphan (sin parent en main) y GH Pages la sirve
desde root como https://research-star.github.io/binance_p2p_ingest/.

Dual-publish (cutover 2026-07-06): tras el push OK a gh-pages, se deploya el
mismo worktree a Cloudflare Pages vía wrangler Direct Upload — edge productivo
de finanzasbo.com. Ese deploy es NO-FATAL (si falla, gh-pages ya quedó
publicado como fallback) y está gateado por la env-var CF_DEPLOY_ENABLED
(default "1"; "0" pausa el espejo CF sin tocar el push a gh-pages). Ver
deploy_cf_pages() más abajo.

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
- Salida dual-idioma: el EN es fail-SOFT — si falta o viene truncado se
  publica solo el ES (warn), nunca bloquea el publish (misma filosofía
  fail-safe que _inject_riesgo). dashboard.py cubre la otra mitad: si el
  bake EN falla (clave faltante / en.json roto) omite el output EN con warn
  y sale 0, de modo que acá degrada al mismo camino output_missing.
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

# Punto de control del desbake vive en config.py (raíz del repo). Este script
# corre desde scripts/, así que REPO_ROOT va a sys.path para importarlo. Mismo
# set que usa dashboard.py para strippear el markup → sin lista paralela.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from config import assets_no_publicados  # noqa: E402
import boletin  # noqa: E402  (solo para BOLETIN_DIRNAME; top-level no importa dashboard)

WORKTREE_PATH = Path("/tmp/gh-pages-publish-wt")
TMP_INDEX_PATH = Path("/tmp/publish_dashboard_index.html")
TMP_INDEX_EN_PATH = Path("/tmp/publish_dashboard_index_en.html")
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

# Dual-publish F1 (migración hosting): espejo a Cloudflare Pages vía wrangler
# Direct Upload, SOLO tras push OK a gh-pages (que sigue siendo el fallback
# vivo hasta el cutover de dominio). wrangler vive en node_modules/ del repo
# (package.json pinea la versión); credenciales en .env del VPS.
CF_PAGES_PROJECT = "finanzasbo"
CF_DEPLOY_TIMEOUT_S = 180

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass  # graceful: sin dotenv, CLOUDFLARE_* deben venir del entorno (si faltan → cf=skip)


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

def _inject_riesgo(index_paths: "list[Path]") -> None:
    """Compute the live own-math riesgo-país number, rebuild the historical
    series, and inject the panels into the freshly-built index files.

    Strictly fail-safe: ANY error is logged and swallowed so the normal
    dashboard still publishes (worst case the panels are absent this cycle).
    Each sub-step runs with check=False; live_bolivia.py degrades to the
    snapshot if Playwright/venue is unavailable, so this never blocks publish.

    Los cómputos (live + historical) corren UNA vez; la inyección corre una
    vez por index (ES y, si en_ok, EN) — misma data, dos HTMLs.
    """
    try:
        if not RIESGO_DIR.exists():
            return
        py = str(VENV_PYTHON)
        run([py, str(RIESGO_DIR / "live_bolivia.py")], check=False)       # live point
        run([py, str(RIESGO_DIR / "build_historical.py")], check=False)   # history
        for index_path in index_paths:                                    # panels
            r = run([py, str(RIESGO_DIR / "inject_into_site.py"),
                     str(index_path)], check=False)
            emit(f"[publish] mode=ok stage=riesgo_inject "
                 f"target={index_path.name} rc={r.returncode}")
    except Exception as e:
        emit(f"[publish] mode=warn stage=riesgo_inject detail=skipped "
             f"err={type(e).__name__}:{str(e)[:160]}")


# ── Main flow ──────────────────────────────────────────────────────────────

def main() -> int:
    t0 = time.time()

    with pid_lock(LOCK_PATH) as acquired:
        if not acquired:
            emit("[publish] otra instancia activa, saliendo limpio")
            return 0
        # Cleanup DENTRO del lock. Si se hiciera antes (como estaba), un segundo
        # proceso —p.ej. el cron */12 que arranca mientras este publish está en
        # el inject lento de riesgo (Playwright, ~2 min) y cruza un tick— borraría
        # el worktree y el index temporal de la corrida EN CURSO antes de chequear
        # el lock, y luego saldría limpio por lock-fail. La corrida en vuelo
        # crasheaba después en _commit_and_push con FileNotFoundError sobre
        # /tmp/publish_dashboard_index.html. Dentro del lock, solo el dueño limpia
        # (su propio leftover de un crash previo); el perdedor no toca nada.
        cleanup_worktree(WORKTREE_PATH)
        if TMP_INDEX_PATH.exists():
            TMP_INDEX_PATH.unlink()
        if TMP_INDEX_EN_PATH.exists():
            TMP_INDEX_EN_PATH.unlink()
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

    # Generar HTML (ES + EN en la misma corrida de dashboard.py)
    t_gen0 = time.time()
    try:
        run([str(VENV_PYTHON), DASHBOARD_SCRIPT,
             "--output", str(TMP_INDEX_PATH),
             "--output-en", str(TMP_INDEX_EN_PATH)], cwd=str(REPO_ROOT))
    except subprocess.CalledProcessError as e:
        emit(f"[publish] mode=error stage=dashboard_generation rc={e.returncode} "
             f"stderr={(e.stderr or '')[:300]}")
        return 1
    gen_s = time.time() - t_gen0

    # Validación de tamaño (ES: fail-hard, igual que siempre)
    if not TMP_INDEX_PATH.exists():
        emit("[publish] mode=error stage=validate detail=output_missing")
        return 1
    new_size = TMP_INDEX_PATH.stat().st_size

    if new_size < MIN_INDEX_SIZE_BYTES:
        emit(f"[publish] mode=error stage=validate detail=size_too_small "
             f"size={new_size} min={MIN_INDEX_SIZE_BYTES}")
        TMP_INDEX_PATH.unlink()
        if TMP_INDEX_EN_PATH.exists():
            TMP_INDEX_EN_PATH.unlink()
        return 1

    if last is not None and last.get("size"):
        floor = int(last["size"] * SHRINK_RATIO_FLOOR)
        if new_size < floor:
            emit(f"[publish] mode=error stage=validate detail=size_shrink "
                 f"size={new_size} last={last['size']} ratio_floor={SHRINK_RATIO_FLOOR}")
            TMP_INDEX_PATH.unlink()
            if TMP_INDEX_EN_PATH.exists():
                TMP_INDEX_EN_PATH.unlink()
            return 1

    # Validación EN: fail-SOFT (misma filosofía que _inject_riesgo). Un EN
    # ausente o truncado NUNCA bloquea el publish del ES — se loguea warn y
    # se publica solo ES este ciclo.
    en_ok = True
    if not TMP_INDEX_EN_PATH.exists():
        emit("[publish] mode=warn stage=validate_en detail=output_missing")
        en_ok = False
    else:
        en_size = TMP_INDEX_EN_PATH.stat().st_size
        if en_size < MIN_INDEX_SIZE_BYTES:
            emit(f"[publish] mode=warn stage=validate_en detail=size_too_small "
                 f"size={en_size} min={MIN_INDEX_SIZE_BYTES}")
            en_ok = False

    # Inyectar los paneles riesgo-país own-math en los HTML ya validados
    # (fail-safe: si falla, se publica el dashboard normal sin los paneles).
    # Cómputo único; inyección por idioma.
    riesgo_targets = [TMP_INDEX_PATH]
    if en_ok:
        riesgo_targets.append(TMP_INDEX_EN_PATH)
    _inject_riesgo(riesgo_targets)

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
        if TMP_INDEX_EN_PATH.exists():
            TMP_INDEX_EN_PATH.unlink()
        return 1

    try:
        return _commit_and_push(t0, gen_s, new_size, n_snap, n_rows,
                                embi_max, ipc_max, ipp_max, hidden_v, en_ok)
    finally:
        cleanup_worktree(WORKTREE_PATH)
        if TMP_INDEX_PATH.exists():
            TMP_INDEX_PATH.unlink()
        if TMP_INDEX_EN_PATH.exists():
            TMP_INDEX_EN_PATH.unlink()


def deploy_cf_pages():
    """Espejo del worktree a Cloudflare Pages (wrangler Direct Upload).

    NO-FATAL por contrato: cuando esto corre, gh-pages ya quedó publicado
    (fallback vivo). Acá solo se loguea cf=ok/skip/error y se retorna —
    jamás propaga excepción al publish (todo el cuerpo está envuelto).
    Direct Upload no consume cuota de builds de CF Pages (límite 500/mes
    aplica solo a builds Git-integrados).
    """
    # Kill-switch reversible por env-var (default ON): CF_DEPLOY_ENABLED=0 en el
    # .env del VPS pausa el espejo CF sin tocar el push a gh-pages ni revertir
    # código. Reactivar = CF_DEPLOY_ENABLED=1 (o quitar la línea), sin merge.
    if os.environ.get("CF_DEPLOY_ENABLED", "1").strip().lower() in ("0", "false", "no", "off"):
        emit("[publish] cf=skip reason=disabled")
        return
    try:
        token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
        account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
        if not token or not account:
            emit("[publish] cf=skip reason=no_credentials")
            return
        t_cf0 = time.time()
        try:
            # --no-install: si node_modules falta, fallar rápido y visible en
            # vez de dejar que npx descargue wrangler de la red en pleno cron.
            r = subprocess.run(
                ["npx", "--no-install", "wrangler", "pages", "deploy",
                 str(WORKTREE_PATH),
                 f"--project-name={CF_PAGES_PROJECT}", "--branch=main"],
                cwd=str(REPO_ROOT),
                env={**os.environ, "WRANGLER_SEND_METRICS": "false"},
                capture_output=True, text=True,
                timeout=CF_DEPLOY_TIMEOUT_S, check=False)
        except subprocess.TimeoutExpired:
            emit(f"[publish] cf=error stage=timeout timeout_s={CF_DEPLOY_TIMEOUT_S}")
            return
        cf_s = time.time() - t_cf0
        if r.returncode != 0:
            # tail, no head: wrangler pone la causa al final, tras el progreso
            detail = " ".join(((r.stderr or "") + " " + (r.stdout or "")).split())[-300:]
            emit(f"[publish] cf=error stage=deploy rc={r.returncode} "
                 f"cf_s={cf_s:.2f} detail={detail}")
            return
        urls = re.findall(r"https://[^\s]+\.pages\.dev", r.stdout or "")
        emit(f"[publish] cf=ok url={urls[-1] if urls else '?'} cf_s={cf_s:.2f}")
    except Exception as e:
        emit(f"[publish] cf=error stage=internal "
             f"detail={type(e).__name__}:{str(e)[:200]}")


# ── Stubs de ruta para deep-links compartibles (Open Graph) ─────────────────
# Las rutas de la SPA (/dolar, ...) no tienen archivo propio: 404.html las
# rebota por JS a /?path=… y activa el tab. Pero los crawlers (Facebook,
# WhatsApp, Twitter, …) NO ejecutan JS y ven el 404.html pelado, sin tags OG →
# sin preview. Este stub es un index.html REAL en la ruta: da 200 + tags OG a
# los bots, y a los humanos los manda a la SPA con el mismo bounce que 404.html.
_ROUTE_STUBS = (
    # (subdir, lang, redirect_js, canonical, og_title, og_description)
    ("dolar", "es", "/?path=/dolar", "https://finanzasbo.com/dolar",
     "FinanzasBo — Dólar paralelo (USDT/BOB) en Bolivia",
     "Cotización del dólar paralelo en Bolivia: compra/venta USDT, tipo de "
     "cambio oficial y evolución histórica, actualizado en tiempo real."),
    ("en/dolar", "en", "/en/?path=/dolar", "https://finanzasbo.com/en/dolar",
     "FinanzasBo — Parallel USD (USDT/BOB) in Bolivia",
     "Bolivia's parallel USD rate: USDT buy/sell, official exchange rate and "
     "historical trend, updated in real time."),
)


def _route_stub_html(lang: str, og_title: str, og_desc: str,
                     canonical: str, redirect: str) -> str:
    """HTML mínimo con tags OG para una ruta SPA. Sin JS pesado: solo un
    location.replace() que los crawlers ignoran (leen los tags) y los humanos
    siguen hacia la SPA. og:image reusa el og.png global (1200×630)."""
    locale = "es_BO" if lang == "es" else "en_US"
    loading = "Cargando FinanzasBo…" if lang == "es" else "Loading FinanzasBo…"
    return (
        '<!DOCTYPE html>\n'
        f'<html lang="{lang}"><head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f'<title>{og_title}</title>\n'
        f'<meta name="description" content="{og_desc}">\n'
        f'<meta property="og:title" content="{og_title}">\n'
        f'<meta property="og:description" content="{og_desc}">\n'
        '<meta property="og:type" content="website">\n'
        '<meta property="og:site_name" content="FinanzasBo">\n'
        f'<meta property="og:locale" content="{locale}">\n'
        '<meta property="og:image" content="https://finanzasbo.com/og.png">\n'
        '<meta property="og:image:width" content="1200">\n'
        '<meta property="og:image:height" content="630">\n'
        f'<meta property="og:url" content="{canonical}">\n'
        '<meta name="twitter:card" content="summary_large_image">\n'
        f'<meta name="twitter:title" content="{og_title}">\n'
        f'<meta name="twitter:description" content="{og_desc}">\n'
        '<meta name="twitter:image" content="https://finanzasbo.com/og.png">\n'
        f'<link rel="canonical" href="{canonical}">\n'
        '<style>html,body{margin:0;background:#F7E4D7;color:#211E1B;'
        'font:14px/1.4 system-ui,sans-serif}.w{padding:40px 20px;text-align:center}</style>\n'
        '</head><body>\n'
        f'<div class="w">{loading}</div>\n'
        f"<script>location.replace({redirect!r});</script>\n"
        '</body></html>\n'
    )


def _commit_and_push(t0: float, gen_s: float, new_size: int,
                     n_snap: int, n_rows: int, embi_max: str | None,
                     ipc_max: str | None, ipp_max: str | None,
                     hidden_v: str | None, en_ok: bool) -> int:
    existing_index = WORKTREE_PATH / "index.html"
    shutil.copyfile(TMP_INDEX_PATH, existing_index)

    # EN: solo si validó OK. Si no, se deja el en/ stale del publish anterior
    # en su lugar (fail-toward-stale, igual que la mirror de ocultos) — un EN
    # viejo es mejor que un 404 en /en/.
    if en_ok:
        en_dir = WORKTREE_PATH / "en"
        en_dir.mkdir(exist_ok=True)
        shutil.copyfile(TMP_INDEX_EN_PATH, en_dir / "index.html")
    else:
        emit("[publish] mode=warn stage=commit_en detail=stale_en_preserved")

    # Boletín diario standalone (/boletin-4k9x/index.html). dashboard.py lo
    # escribió junto al index temporal (TMP_INDEX_PATH.parent). Se copia al
    # worktree → git add -A lo sube a gh-pages y deploy_cf_pages() (que despliega
    # el worktree completo) lo espeja a CF Pages, sin tocar el dual-publish ni el
    # guard de tamaño (que valida SOLO el index.html, no este archivo). Condicional:
    # si el boletín no se generó (build falló → dashboard.py omitió la escritura),
    # NO hay fuente y se preserva el boletín anterior del worktree (fail-toward-stale).
    boletin_src = TMP_INDEX_PATH.parent / boletin.BOLETIN_DIRNAME / "index.html"
    if boletin_src.exists():
        boletin_dst_dir = WORKTREE_PATH / boletin.BOLETIN_DIRNAME
        boletin_dst_dir.mkdir(exist_ok=True)
        shutil.copyfile(boletin_src, boletin_dst_dir / "index.html")
    else:
        emit("[publish] mode=warn stage=boletin detail=source_missing_stale_preserved")

    # Stubs de ruta (deep-links compartibles con Open Graph). Ver _ROUTE_STUBS.
    for seg, lang, redirect, canon, otit, odesc in _ROUTE_STUBS:
        stub_dir = WORKTREE_PATH / seg
        stub_dir.mkdir(parents=True, exist_ok=True)
        (stub_dir / "index.html").write_text(
            _route_stub_html(lang, otit, odesc, canon, redirect),
            encoding="utf-8")

    if STATIC_DIR.exists():
        # Assets de módulos desbakeados (ej. mercado247-tab.js) NO se copian a
        # prod mientras el módulo esté en config.MODULOS_NO_BAKEADOS.
        no_publicar = assets_no_publicados()
        for asset in STATIC_DIR.iterdir():
            if asset.is_file() and asset.name not in no_publicar:
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

    # version.json: señal de frescura barata para el poller del front. El edge
    # (Cloudflare Pages) NO expone Last-Modified/ETag en el HTML, así que el poller
    # compara este valor, que cambia en cada publish. Best-effort: un fallo acá NO
    # rompe el publish (git add -A lo recoge si se escribió; si no, el poller degrada
    # a no-op y la pestaña simplemente no se auto-refresca).
    try:
        (WORKTREE_PATH / "version.json").write_text(
            '{"generated_at": "' + ts + '"}\n', encoding="utf-8")
    except Exception as e:
        emit(f"[publish] mode=warn stage=version_json detail={type(e).__name__}")

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

    # Dual-publish F1: recién acá, con gh-pages ya publicado. El worktree
    # sigue vivo (cleanup en el finally del caller). No-fatal.
    deploy_cf_pages()

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
