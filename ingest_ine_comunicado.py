#!/usr/bin/env python3
"""
ingest_ine_comunicado.py — Scraper de los comunicados de prensa del IPC del INE.

Fuente RÁPIDA y PROVISIONAL del IPC: el INE publica el comunicado (con var
mensual/acumulada/12m) DÍAS antes de refrescar el cuadro XLSX descargable
(el que baja `ingest_ine_ipc.py`). Este ingest scrapea el titular+cuerpo del
comunicado — SIN LLM/API, puro regex — y lo guarda en `ine_ipc_comunicado`.

El dashboard usa esos valores SOLO para los meses que `ine_ipc` (Excel) aún no
tiene, marcándolos "provisional". Cuando el XLSX llega, `ine_ipc` tiene el dato
oficial (precisión completa) y el overlay provisional deja de aplicar: el Excel
PISA al comunicado. `ine_ipc` (verdad oficial) NUNCA se toca acá.

Validado 2026-07-07: reproduce el Excel EXACTO (2 decimales) en 17/17 celdas
comparables (2026 ene–may, 2025 mar–may), 0 discrepancias.

Uso:
    python3 ingest_ine_comunicado.py                # fetch + upsert
    python3 ingest_ine_comunicado.py --dry-run      # imprime sin escribir
    python3 ingest_ine_comunicado.py --db otra.db
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone

from config import NORMALIZED_DB

WPJSON = ("https://www.ine.gob.bo/index.php/wp-json/wp/v2/posts"
          "?search=variaci%C3%B3n%20%C3%8Dndice%20de%20Precios%20al%20Consumidor"
          "&per_page=30&_fields=date,link,title,content")
HEADERS = {"User-Agent": "Mozilla/5.0 (binance_p2p_ingest/ine)"}
TIMEOUT_S = 40
HC_INE_COMUNICADO = os.environ.get("HC_INE_COMUNICADO", "").strip()

MESES = {m: i for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
     "septiembre", "octubre", "noviembre", "diciembre"], start=1)}

DDL = """
CREATE TABLE IF NOT EXISTS ine_ipc_comunicado (
  periodo          TEXT PRIMARY KEY,
  var_mensual      REAL,
  var_acumulada    REAL,
  var_12m          REAL,
  fecha_comunicado TEXT,
  url              TEXT,
  fetched_at_utc   TEXT NOT NULL
);
"""


def _clean(h: str) -> str:
    return re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", html.unescape(h))).strip()


def _num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def fetch_posts() -> list[dict]:
    req = urllib.request.Request(WPJSON, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_post(p: dict) -> dict | None:
    """Devuelve {periodo, var_mensual, var_acumulada, var_12m, fecha, url} o None
    si el post no es un comunicado mensual del IPC al consumidor parseable."""
    title = _clean(p.get("title", {}).get("rendered", ""))
    body = _clean(p.get("content", {}).get("rendered", ""))
    if "Consumidor" not in title or "Productor" in title or "por Mayor" in title:
        return None
    md = re.search(r"\ben\s+([a-záéíóú]+)\s+(?:de\s+)?(\d{4})", title, re.I)
    if not md or md.group(1).lower() not in MESES:
        return None
    periodo = f"{int(md.group(2)):04d}-{MESES[md.group(1).lower()]:02d}"
    mt = re.search(r"variaci[oó]n\s+(?:(positiva|negativa)\s+)?de\s+(-?\d+,\d+)\s*%",
                   title, re.I)
    if not mt:
        return None
    mensual = _num(mt.group(2))
    if (mt.group(1) or "").lower() == "negativa":
        mensual = -abs(mensual)
    ma = re.search(r"acumulad\w*.{0,80}?(-?\d+,\d+)\s*%", body, re.I)
    m12 = re.search(r"(?:doce meses|12 meses).{0,60}?(-?\d+,\d+)\s*%", body, re.I)
    return {
        "periodo": periodo,
        "var_mensual": mensual,
        "var_acumulada": _num(ma.group(1)) if ma else None,
        "var_12m": _num(m12.group(1)) if m12 else None,
        "fecha": (p.get("date") or "")[:10],
        "url": p.get("link", ""),
    }


def upsert(conn: sqlite3.Connection, e: dict, now: str) -> str:
    """Upsert preservando valores no-null previos (un parse transitorio con un
    campo faltante no borra uno bueno). Devuelve 'nuevo' | 'actualizado' | 'igual'."""
    cur = conn.execute(
        "SELECT var_mensual, var_acumulada, var_12m FROM ine_ipc_comunicado "
        "WHERE periodo = ?", (e["periodo"],)).fetchone()
    new = {k: e[k] for k in ("var_mensual", "var_acumulada", "var_12m")}
    if cur is not None:
        prev = {"var_mensual": cur[0], "var_acumulada": cur[1], "var_12m": cur[2]}
        merged = {k: (new[k] if new[k] is not None else prev[k]) for k in new}
        if merged == prev:
            return "igual"
        new = merged
        verdict = "actualizado"
    else:
        verdict = "nuevo"
    conn.execute(
        "INSERT OR REPLACE INTO ine_ipc_comunicado "
        "(periodo, var_mensual, var_acumulada, var_12m, fecha_comunicado, url, fetched_at_utc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (e["periodo"], new["var_mensual"], new["var_acumulada"], new["var_12m"],
         e["fecha"], e["url"], now))
    return verdict


def hc_ping(suffix: str = "", body: str = ""):
    if not HC_INE_COMUNICADO:
        return
    url = f"https://hc-ping.com/{HC_INE_COMUNICADO}" + (f"/{suffix}" if suffix else "")
    try:
        req = urllib.request.Request(
            url, data=body.encode("utf-8") if body else None, headers=HEADERS)
        urllib.request.urlopen(req, timeout=10)
    except Exception as ex:
        print(f"[ine-com] WARN hc_ping_failed: {ex}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="Scraper comunicados IPC del INE")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=str(NORMALIZED_DB))
    args = ap.parse_args()

    hc_ping("start")
    try:
        posts = fetch_posts()
    except Exception as ex:
        print(f"[ine-com] ERROR fetch: {ex}", file=sys.stderr)
        hc_ping("fail", f"fetch: {ex}")
        sys.exit(1)

    parsed, seen = [], set()
    for p in posts:
        e = parse_post(p)
        if e and e["periodo"] not in seen:  # dedup por periodo (1er match = más reciente)
            seen.add(e["periodo"])
            parsed.append(e)
    parsed.sort(key=lambda e: e["periodo"], reverse=True)

    if not parsed:
        print("[ine-com] WARN sin comunicados IPC parseables", file=sys.stderr)
        hc_ping("fail", "0 parseables")
        sys.exit(1)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    if args.dry_run:
        for e in parsed:
            print(f"[DRY] {e['periodo']} (com {e['fecha']}): "
                  f"mensual={e['var_mensual']} acum={e['var_acumulada']} 12m={e['var_12m']}")
        print(f"[ine-com] DRY RUN: {len(parsed)} comunicados no escritos")
        return

    conn = sqlite3.connect(args.db)
    conn.executescript(DDL)
    counts = {"nuevo": 0, "actualizado": 0, "igual": 0}
    for e in parsed:
        counts[upsert(conn, e, now)] += 1
    conn.commit()
    conn.close()
    msg = (f"{counts['nuevo']} nuevos, {counts['actualizado']} actualizados, "
           f"{counts['igual']} sin cambio (último: {parsed[0]['periodo']} "
           f"mensual={parsed[0]['var_mensual']})")
    print(f"[ine-com] {msg}")
    hc_ping("", msg)


if __name__ == "__main__":
    main()
