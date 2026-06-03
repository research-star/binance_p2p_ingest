#!/usr/bin/env python3
"""
ingest_ine_ipc.py — Scraper de cuadros IPC del INE Bolivia (host nube).

V1 scope (definido en config.INE_CUADROS):
  - IPC Nacional general (índice + var mensual/acumulada/12m)
  - IPC por División COICOP (12 divisiones + total)
  - IPC Serie Histórica Empalmada (1937-presente)

Diferencias vs ingest_ine_pib.py:
  - Content-Disposition trae 'Nal-YYYY_MM_...' (versioned) → la detección de
    release puede usar el filename ANTES de hacer GET completo. Hoy hacemos
    GET directo (los XLSX son ~300 KB, no compensa una HEAD adicional con
    redirect Nextcloud). Si el dataset crece, se puede pasar a HEAD-first.
  - `release_id` = 'YYYY_MM' extraído del Content-Disposition (más informativo
    que el MD5 prefix usado en PIB).
  - Audit folder: /opt/binance_p2p/ine_audit/ipc/<cuadro_id>_<release_id>.xlsx.

Uso: idéntica CLI a ingest_ine_pib.py.
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

FAMILY = "ipc"
HEADERS = {"User-Agent": "Mozilla/5.0 (binance_p2p_ingest/ine)"}
TIMEOUT_S = 90
ROTATE_DAYS = 60

CONTENT_DISPOSITION_FILENAME_RE = re.compile(
    r"""filename\*?=(?:UTF-8'')?["']?([^"';\r\n]+)["']?""", re.IGNORECASE
)
# IPC filename embeds 'YYYY_MM' (ej 'Nal-2026_05_1_Bolivia...'). Extraerlo
# como release_id permite logear el mes publicado sin abrir el XLSX.
RELEASE_YM_RE = re.compile(r"(\d{4})_(\d{2})")

HC_INE_IPC = os.environ.get("HC_INE_IPC", "").strip()


# ── Healthcheck ───────────────────────────────────────────────────────────

def hc_ping(suffix: str = "", body: str = ""):
    if not HC_INE_IPC:
        return
    url = f"https://hc-ping.com/{HC_INE_IPC}"
    if suffix:
        url = f"{url}/{suffix}"
    try:
        if body:
            requests.post(url, data=body.encode("utf-8"), timeout=10)
        else:
            requests.get(url, timeout=10)
    except Exception as e:
        print(f"[ine-ipc] WARN hc_ping_failed: {e}", file=sys.stderr)


# ── Audit folder ──────────────────────────────────────────────────────────

def ensure_audit_dir() -> Path | None:
    target = INE_AUDIT_DIR / FAMILY
    try:
        target.mkdir(parents=True, exist_ok=True)
        return target
    except OSError as e:
        print(f"[ine-ipc] WARN audit_dir_unavailable: {e}", file=sys.stderr)
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


# ── State ────────────────────────────────────────────────────────────────

def get_state(conn: sqlite3.Connection, cuadro_id: str
              ) -> tuple[str | None, str | None, str | None]:
    cur = conn.execute(
        """SELECT last_md5, last_filename, last_release_id
           FROM ine_ingest_state WHERE cuadro = ?""",
        (cuadro_id,),
    )
    row = cur.fetchone()
    return (row[0], row[1], row[2]) if row else (None, None, None)


def save_state(conn: sqlite3.Connection, cuadro_id: str,
               filename: str, md5: str, release_id: str):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """INSERT OR REPLACE INTO ine_ingest_state
           (cuadro, last_filename, last_md5, last_release_id, last_fetched_at)
           VALUES (?, ?, ?, ?, ?)""",
        (cuadro_id, filename, md5, release_id, now),
    )


# ── HTTP ─────────────────────────────────────────────────────────────────

def fetch_cuadro(cuadro_id: str) -> tuple[bytes, str, str]:
    cfg = INE_CUADROS[cuadro_id]
    primary = cfg["host"]
    secondary = "nube" if primary == "nimbus" else "nimbus"

    for host in (primary, secondary):
        url = ine_url(cuadro_id, host_override=host)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT_S,
                                allow_redirects=True)
        except Exception as e:
            print(f"[ine-ipc] WARN fetch_failed host={host} cuadro={cuadro_id} "
                  f"err={e}", file=sys.stderr)
            continue
        if resp.status_code == 200:
            disp = resp.headers.get("Content-Disposition", "")
            m = CONTENT_DISPOSITION_FILENAME_RE.search(disp)
            filename = m.group(1) if m else f"{cuadro_id}.xlsx"
            return resp.content, filename, resp.url
        print(f"[ine-ipc] WARN host={host} cuadro={cuadro_id} "
              f"http={resp.status_code}", file=sys.stderr)
    raise RuntimeError(
        f"{cuadro_id}: no se pudo descargar de {primary} ni de {secondary}"
    )


def extract_release_id(filename: str, fallback_md5: str) -> str:
    """Para IPC, 'YYYY_MM' del filename. Si no parsea, prefix MD5 (PIB-style)."""
    m = RELEASE_YM_RE.search(filename)
    if m:
        return f"{m.group(1)}_{m.group(2)}"
    return fallback_md5[:10]


# ── Schema ───────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS ine_ipc (
  periodo     TEXT NOT NULL,
  cuadro      TEXT NOT NULL,
  indicador   TEXT NOT NULL,
  valor       REAL,
  unidad      TEXT NOT NULL,
  base_year   TEXT,
  PRIMARY KEY (cuadro, periodo, indicador)
);
CREATE INDEX IF NOT EXISTS idx_ine_ipc_ind
  ON ine_ipc (cuadro, indicador, periodo);
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


# ── Upsert ───────────────────────────────────────────────────────────────

def upsert_ipc(conn: sqlite3.Connection, cuadro_id: str,
               rows: list[dict]) -> tuple[int, int, str]:
    payload = [
        (r["periodo"], cuadro_id, r["indicador"], r["valor"],
         r["unidad"], r.get("base_year"))
        for r in rows
    ]
    conn.executemany(
        """INSERT OR REPLACE INTO ine_ipc
           (periodo, cuadro, indicador, valor, unidad, base_year)
           VALUES (?, ?, ?, ?, ?, ?)""",
        payload,
    )
    conn.commit()
    n_ind = len({r["indicador"] for r in rows}) if rows else 0
    last_p = max((r["periodo"] for r in rows), default="?")
    return len(rows), n_ind, last_p


# ── Main ─────────────────────────────────────────────────────────────────

def process_cuadro(cuadro_id: str, conn: sqlite3.Connection,
                   audit_dir: Path | None, force: bool, dry_run: bool
                   ) -> dict:
    t0 = time.time()
    cfg = INE_CUADROS[cuadro_id]
    content, filename, _ = fetch_cuadro(cuadro_id)
    md5 = hashlib.md5(content).hexdigest()
    release_id = extract_release_id(filename, md5)

    last_md5, last_filename, last_release = (
        (None, None, None) if force else get_state(conn, cuadro_id)
    )
    if last_md5 == md5 and not force:
        return {
            "cuadro": cuadro_id, "mode": "skip", "reason": "md5_unchanged",
            "release": last_release, "rows": 0,
            "duration_s": round(time.time() - t0, 2),
        }

    parse_target: Path
    cleanup = False
    if audit_dir is not None and not dry_run:
        snap = audit_dir / f"{cuadro_id}_{release_id}.xlsx"
        try:
            snap.write_bytes(content)
            parse_target = snap
        except OSError as e:
            print(f"[ine-ipc] WARN audit_save_failed cuadro={cuadro_id} "
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
        n_ind = len({r["indicador"] for r in rows})
        last_p = max(r["periodo"] for r in rows)
        return {
            "cuadro": cuadro_id, "mode": "dry-run", "rows": len(rows),
            "n_ind": n_ind, "last_periodo": last_p, "release": release_id,
            "md5": md5, "duration_s": round(time.time() - t0, 2),
        }

    n_rows, n_ind, last_p = upsert_ipc(conn, cuadro_id, rows)
    save_state(conn, cuadro_id, filename, md5, release_id)
    conn.commit()
    return {
        "cuadro": cuadro_id, "mode": "ok", "rows": n_rows, "n_ind": n_ind,
        "last_periodo": last_p, "release": release_id, "md5": md5,
        "duration_s": round(time.time() - t0, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest INE Bolivia IPC cuadros")
    parser.add_argument("--db", type=Path, default=NORMALIZED_DB)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cuadro", type=str, default=None,
                        help="Procesar solo este cuadro (default: todos los IPC)")
    args = parser.parse_args()

    t0 = time.time()
    hc_ping("start")

    audit_dir = ensure_audit_dir()
    targets = [cid for cid, cfg in INE_CUADROS.items() if cfg["family"] == FAMILY]
    if args.cuadro:
        if args.cuadro not in targets:
            print(f"[ine-ipc] ERROR cuadro={args.cuadro} no es familia IPC "
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
                print(f"[ine-ipc] ERROR cuadro={cid} detail={e}\n{tb}",
                      file=sys.stderr)
            summaries.append(s)
            print(f"[ine-ipc] {s}")
    finally:
        conn.close()

    rotated = rotate_audit(audit_dir) if audit_dir else 0

    total_rows = sum(s.get("rows", 0) for s in summaries)
    n_ok = sum(1 for s in summaries if s.get("mode") == "ok")
    n_skip = sum(1 for s in summaries if s.get("mode") == "skip")
    n_err = sum(1 for s in summaries if s.get("mode") == "error")

    summary = (f"[ine-ipc] mode={'ok' if not any_error else 'partial'} "
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
