#!/usr/bin/env python3
"""
ingest_ine_pib.py — Scraper de cuadros PIB del INE Bolivia (nimbus + nube).

V1 scope (definido en config.INE_CUADROS):
  - PIB Trimestral por actividad / por gasto / var YoY actividad (3 cuadros, nimbus)
  - PIB Anual Serie Histórica por actividad / por gasto (2 cuadros, nube)

Diferencias vs ingest_embi.py:
  - Itera múltiples cuadros en una sola corrida (5 PIB).
  - El Nextcloud/Owncloud del INE NO emite ETag/Last-Modified → reemplazamos
    el patrón `If-None-Match` por hash MD5 del body contra `ine_ingest_state`.
  - Audit segmentado por familia + namespaceado por cuadro:
    /opt/binance_p2p/ine_audit/pib/<cuadro_id>_<release_id>.xlsx
  - `release_id` para PIB = filename del XLSX (estático, ej. '01.01.01') +
    timestamp del fetch — porque la fecha del release vive DENTRO del Excel.

Healthcheck:
  - HC_INE_PIB env var (si no está seteada, log warning + seguir).
  - start / success / fail con body resumen.

Uso:
    python ingest_ine_pib.py             # corrida normal (skip si MD5 estable)
    python ingest_ine_pib.py --force     # ignora estado, re-descarga + re-parsea
    python ingest_ine_pib.py --dry-run   # parsea pero no escribe a SQLite ni audit
    python ingest_ine_pib.py --db ./test.db
    python ingest_ine_pib.py --cuadro pib_trim_01_01_01  # filtrar un solo cuadro
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sqlite3
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

import requests

from config import (
    INE_AUDIT_DIR,
    INE_CUADROS,
    NORMALIZED_DB,
    ine_url,
)
from ine_parser import parse_cuadro

# ── Constantes ────────────────────────────────────────────────────────────

FAMILY = "pib"
HEADERS = {"User-Agent": "Mozilla/5.0 (binance_p2p_ingest/ine)"}
TIMEOUT_S = 90  # PIB tarda algo más que EMBI; márgen generoso

ROTATE_DAYS = 60  # Audit retention; PIB se publica trimestralmente

CONTENT_DISPOSITION_FILENAME_RE = re.compile(
    r"""filename\*?=(?:UTF-8'')?["']?([^"';\r\n]+)["']?""", re.IGNORECASE
)

HC_INE_PIB = os.environ.get("HC_INE_PIB", "").strip()


# ── Healthcheck ───────────────────────────────────────────────────────────

def hc_ping(suffix: str = "", body: str = ""):
    if not HC_INE_PIB:
        return
    url = f"https://hc-ping.com/{HC_INE_PIB}"
    if suffix:
        url = f"{url}/{suffix}"
    try:
        if body:
            requests.post(url, data=body.encode("utf-8"), timeout=10)
        else:
            requests.get(url, timeout=10)
    except Exception as e:
        print(f"[ine-pib] WARN hc_ping_failed: {e}", file=sys.stderr)


# ── Audit folder ──────────────────────────────────────────────────────────

def ensure_audit_dir() -> Path | None:
    """Best-effort. Devuelve la subcarpeta de la familia o None si OS no es POSIX
    o si el mkdir falló. En Windows, INE_AUDIT_DIR='/opt/binance_p2p/ine_audit'
    se normaliza silenciosamente a 'C:\\opt\\...' — degradamos antes de tocar
    el FS para no contaminar el root del drive en dev/laptop."""
    if os.name != "posix":
        # Dev en laptop Windows: el audit dir vive sólo en el VPS prod.
        return None
    target = INE_AUDIT_DIR / FAMILY
    try:
        target.mkdir(parents=True, exist_ok=True)
        return target
    except OSError as e:
        print(f"[ine-pib] WARN audit_dir_unavailable: {e}", file=sys.stderr)
        return None


def rotate_audit(audit_dir: Path, days: int = ROTATE_DAYS) -> int:
    cutoff = time.time() - days * 86400
    removed = 0
    for f in audit_dir.glob("*.xlsx"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed


# ── State (ine_ingest_state) ──────────────────────────────────────────────

def get_state(conn: sqlite3.Connection, cuadro_id: str
              ) -> tuple[str | None, str | None]:
    """Devuelve (last_md5, last_filename) o (None, None) si nunca corrió."""
    cur = conn.execute(
        "SELECT last_md5, last_filename FROM ine_ingest_state WHERE cuadro = ?",
        (cuadro_id,),
    )
    row = cur.fetchone()
    return (row[0], row[1]) if row else (None, None)


def save_state(conn: sqlite3.Connection, cuadro_id: str,
               filename: str, md5: str, release_id: str):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """INSERT OR REPLACE INTO ine_ingest_state
           (cuadro, last_filename, last_md5, last_release_id, last_fetched_at)
           VALUES (?, ?, ?, ?, ?)""",
        (cuadro_id, filename, md5, release_id, now),
    )


# ── HTTP ──────────────────────────────────────────────────────────────────

def fetch_cuadro(cuadro_id: str) -> tuple[bytes, str, str]:
    """Descarga el XLSX. Retorna (content_bytes, filename_from_disposition,
    final_url). Intenta el host primario y, si 404/5xx, prueba el secundario."""
    cfg = INE_CUADROS[cuadro_id]
    primary = cfg["host"]
    secondary = "nube" if primary == "nimbus" else "nimbus"

    for host in (primary, secondary):
        url = ine_url(cuadro_id, host_override=host)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT_S,
                                allow_redirects=True)
        except Exception as e:
            print(f"[ine-pib] WARN fetch_failed host={host} cuadro={cuadro_id} "
                  f"err={e}", file=sys.stderr)
            continue
        if resp.status_code == 200:
            # Validar magic bytes ZIP (XLSX = OOXML zip container). Si el host
            # devuelve un captive HTML con 200 OK, fallar y probar el secundario.
            if resp.content[:4] != b"PK\x03\x04":
                print(f"[ine-pib] WARN host={host} cuadro={cuadro_id} "
                      f"non_xlsx_magic bytes={resp.content[:8]!r}",
                      file=sys.stderr)
                continue
            disp = resp.headers.get("Content-Disposition", "")
            m = CONTENT_DISPOSITION_FILENAME_RE.search(disp)
            filename = m.group(1) if m else f"{cuadro_id}.xlsx"
            return resp.content, filename, resp.url
        print(f"[ine-pib] WARN host={host} cuadro={cuadro_id} "
              f"http={resp.status_code}", file=sys.stderr)
    raise RuntimeError(
        f"{cuadro_id}: no se pudo descargar de {primary} ni de {secondary}"
    )


# ── Schema ────────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS ine_pib (
  periodo         TEXT NOT NULL,
  cuadro          TEXT NOT NULL,
  dimension       TEXT NOT NULL,
  valor           REAL,
  unidad          TEXT NOT NULL,
  is_preliminary  INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (cuadro, periodo, dimension)
);
CREATE INDEX IF NOT EXISTS idx_ine_pib_dim
  ON ine_pib (cuadro, dimension, periodo);
CREATE TABLE IF NOT EXISTS ine_ingest_state (
  cuadro             TEXT PRIMARY KEY,
  last_filename      TEXT,
  last_md5           TEXT,
  last_release_id    TEXT,
  last_fetched_at    TEXT NOT NULL
);
"""


def init_schema(conn: sqlite3.Connection):
    conn.executescript(DDL)
    conn.commit()


# ── Upsert ────────────────────────────────────────────────────────────────

def upsert_pib(conn: sqlite3.Connection, cuadro_id: str,
               rows: list[dict]) -> tuple[int, int, str]:
    """Devuelve (rows_upserted, n_dimensions, last_periodo).

    Pre-check: rechaza el batch si dos filas comparten (periodo, dimension)
    con valores distintos. Esto detecta typos del INE en labels de año (ej.
    '2022p)' sin paréntesis abrir) que harían que un año se atribuya
    silenciosamente al anterior. El INSERT OR REPLACE final asume que tras
    este check no hay colapsos accidentales."""
    seen: dict[tuple[str, str], float | None] = {}
    for r in rows:
        key = (r["periodo"], r["dimension"])
        v = r["valor"]
        if key in seen:
            prev = seen[key]
            if prev != v:
                raise RuntimeError(
                    f"{cuadro_id}: colapso (periodo, dimension) con valores "
                    f"distintos — periodo={key[0]!r} dim={key[1]!r} "
                    f"prev={prev!r} now={v!r}. Probable typo del INE en un "
                    f"label de año (ej. '2022p)' sin paréntesis abrir). "
                    f"Revisar el XLSX antes de insertar."
                )
        seen[key] = v
    payload = [
        (r["periodo"], cuadro_id, r["dimension"], r["valor"],
         r["unidad"], int(r["is_preliminary"]))
        for r in rows
    ]
    conn.executemany(
        """INSERT OR REPLACE INTO ine_pib
           (periodo, cuadro, dimension, valor, unidad, is_preliminary)
           VALUES (?, ?, ?, ?, ?, ?)""",
        payload,
    )
    conn.commit()
    n_dim = len({r["dimension"] for r in rows}) if rows else 0
    last_periodo = max((r["periodo"] for r in rows), default="?")
    return len(rows), n_dim, last_periodo


# ── Main ──────────────────────────────────────────────────────────────────

def process_cuadro(cuadro_id: str, conn: sqlite3.Connection,
                   audit_dir: Path | None, force: bool, dry_run: bool
                   ) -> dict:
    """Procesa UN cuadro: fetch → MD5 vs state → parse → upsert.
    Devuelve un dict resumen para el log final."""
    t0 = time.time()
    cfg = INE_CUADROS[cuadro_id]
    content, filename, final_url = fetch_cuadro(cuadro_id)
    md5 = hashlib.md5(content).hexdigest()

    last_md5, last_filename = (None, None) if force else get_state(conn, cuadro_id)
    if last_md5 == md5 and not force:
        return {
            "cuadro": cuadro_id, "mode": "skip", "reason": "md5_unchanged",
            "md5": md5, "rows": 0, "duration_s": round(time.time() - t0, 2),
        }

    # Snapshot a audit antes de parsear (si audit disponible).
    parse_target: Path
    cleanup = False
    if audit_dir is not None and not dry_run:
        release_id = md5[:10]  # Para PIB el filename es estático; usamos prefix MD5.
        snap = audit_dir / f"{cuadro_id}_{release_id}.xlsx"
        try:
            snap.write_bytes(content)
            parse_target = snap
        except OSError as e:
            print(f"[ine-pib] WARN audit_save_failed cuadro={cuadro_id} "
                  f"err={e}", file=sys.stderr)
            tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
            tmp.write(content); tmp.close()
            parse_target = Path(tmp.name); cleanup = True
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        tmp.write(content); tmp.close()
        parse_target = Path(tmp.name); cleanup = True

    try:
        rows = parse_cuadro(cuadro_id, parse_target, cfg)
    finally:
        if cleanup:
            try: parse_target.unlink()
            except OSError: pass

    if not rows:
        return {
            "cuadro": cuadro_id, "mode": "error", "reason": "zero_rows",
            "duration_s": round(time.time() - t0, 2),
        }

    if dry_run:
        n_dim = len({r["dimension"] for r in rows})
        last_p = max(r["periodo"] for r in rows)
        return {
            "cuadro": cuadro_id, "mode": "dry-run", "rows": len(rows),
            "n_dim": n_dim, "last_periodo": last_p, "md5": md5,
            "duration_s": round(time.time() - t0, 2),
        }

    n_rows, n_dim, last_p = upsert_pib(conn, cuadro_id, rows)
    save_state(conn, cuadro_id, filename, md5, md5[:10])
    conn.commit()
    return {
        "cuadro": cuadro_id, "mode": "ok", "rows": n_rows, "n_dim": n_dim,
        "last_periodo": last_p, "md5": md5,
        "duration_s": round(time.time() - t0, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest INE Bolivia PIB cuadros")
    parser.add_argument("--db", type=Path, default=NORMALIZED_DB,
                        help=f"SQLite database (default: {NORMALIZED_DB})")
    parser.add_argument("--force", action="store_true",
                        help="Ignorar md5 persistido y re-procesar")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parsea pero no escribe SQLite ni audit")
    parser.add_argument("--cuadro", type=str, default=None,
                        help="Procesar solo este cuadro_id (default: todos los PIB)")
    args = parser.parse_args()

    t0 = time.time()
    hc_ping("start")

    audit_dir = ensure_audit_dir()
    targets = [cid for cid, cfg in INE_CUADROS.items() if cfg["family"] == FAMILY]
    if args.cuadro:
        if args.cuadro not in targets:
            print(f"[ine-pib] ERROR cuadro={args.cuadro} no es de familia PIB "
                  f"(familia={INE_CUADROS.get(args.cuadro, {}).get('family')!r})",
                  file=sys.stderr)
            return 1
        targets = [args.cuadro]

    conn = sqlite3.connect(str(args.db))
    try:
        init_schema(conn)
        summaries: list[dict] = []
        any_error = False
        for cid in targets:
            try:
                s = process_cuadro(cid, conn, audit_dir, args.force, args.dry_run)
            except Exception as e:
                tb = traceback.format_exc()
                s = {"cuadro": cid, "mode": "error", "reason": str(e)}
                any_error = True
                print(f"[ine-pib] ERROR cuadro={cid} detail={e}\n{tb}",
                      file=sys.stderr)
            summaries.append(s)
            print(f"[ine-pib] {s}")
    finally:
        conn.close()

    rotated = rotate_audit(audit_dir) if audit_dir else 0

    total_rows = sum(s.get("rows", 0) for s in summaries)
    n_ok = sum(1 for s in summaries if s.get("mode") == "ok")
    n_skip = sum(1 for s in summaries if s.get("mode") == "skip")
    n_err = sum(1 for s in summaries if s.get("mode") == "error")

    summary = (f"[ine-pib] mode={'ok' if not any_error else 'partial'} "
               f"cuadros={len(summaries)} ok={n_ok} skip={n_skip} err={n_err} "
               f"rows_upserted={total_rows} rotated={rotated} "
               f"duration_s={time.time()-t0:.2f}")
    print(summary)
    if any_error:
        hc_ping("fail", body=summary)
        return 1
    hc_ping(body=summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
