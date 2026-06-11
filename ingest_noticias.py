#!/usr/bin/env python3
"""
ingest_noticias.py — Pipeline diario de la tab Noticias.

Flujo: scrape 13 portales (noticias_ingest/scraper.py, port de boletines)
→ score TF-IDF → filtro editorial puntaje >= 6.7 → dedupe inter-día fuzzy
contra los últimos 7 días de la tabla `noticias` → top-10 desc → INSERT
idempotente en p2p_normalized.db.

Idempotencia (tres capas):
  1. Caché de URLs vistas (TTL 7 días, noticias_ingest/data/cache_urls.db):
     una re-corrida del mismo día no re-procesa URLs ya vistas.
  2. PRIMARY KEY = hash del link normalizado → INSERT OR IGNORE.
  3. Dedupe fuzzy por título (token_sort_ratio >= 0.70) contra la DB.

Healthcheck: HC_NOTICIAS (env var, en VPS via /opt/binance_p2p/.env).
Graceful si falta: warning y sigue, patrón HC_INE_*.

Fail-closed en scoring: si el modelo TF-IDF no está disponible (pkl
ausente/ilegible o descartado por sus umbrales de calidad), la corrida
pingea fail y sale 1 SIN scrapear ni insertar — el corte editorial 6.7
está calibrado para la escala TF-IDF y el fallback keywords (conteos
enteros) la rompería en silencio.

Uso:
    python ingest_noticias.py                  # corrida normal contra p2p_normalized.db
    python ingest_noticias.py --db test.db     # DB alternativa (dev)
    python ingest_noticias.py --dry-run        # scrape + score + dedupe, sin escribir
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sqlite3
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

import requests

from config import NORMALIZED_DB
from noticias_ingest import scraper
from noticias_ingest.transform import build_nota

# ── Constantes ────────────────────────────────────────────────────────────

UMBRAL_PUNTAJE = 6.7   # corte editorial de la tab (decisión cerrada del brief)
TOP_N = 10             # tope diario
DEDUPE_DIAS = 7        # ventana de dedupe inter-día contra la tabla noticias
UMBRAL_DEDUP_DB = 0.70

HC_NOTICIAS = os.environ.get("HC_NOTICIAS", "").strip()


# ── Healthcheck ───────────────────────────────────────────────────────────

def hc_ping(suffix: str = "", body: str = ""):
    if not HC_NOTICIAS:
        return
    url = f"https://hc-ping.com/{HC_NOTICIAS}"
    if suffix:
        url = f"{url}/{suffix}"
    try:
        if body:
            requests.post(url, data=body.encode("utf-8"), timeout=10)
        else:
            requests.get(url, timeout=10)
    except Exception as e:
        print(f"[noticias] WARN hc_ping_failed: {e}", file=sys.stderr)


# ── Schema ────────────────────────────────────────────────────────────────
# Espejo versionado en scripts/migrations/0002_noticias.sql (se aplica a
# mano en el VPS); este DDL idempotente cubre dev y re-corridas.

DDL = """
CREATE TABLE IF NOT EXISTS noticias (
    id              TEXT PRIMARY KEY,   -- hash MD5 corto del link normalizado
    date            TEXT NOT NULL,      -- YYYY-MM-DD de la corrida (hora Bolivia, UTC-4)
    time            TEXT NOT NULL,      -- HH:MM de la corrida (hora Bolivia, UTC-4)
    source          TEXT NOT NULL,      -- slug del portal (key de NOTICIAS_PORTALS)
    category        TEXT NOT NULL,      -- economia|hidrocarburos|agro|mineria|mundo|politica
    title           TEXT NOT NULL,
    summary         TEXT NOT NULL DEFAULT '',
    detail          TEXT NOT NULL DEFAULT '',
    topics          TEXT NOT NULL DEFAULT '[]',  -- JSON array (tema original de boletines)
    impact          TEXT NOT NULL,      -- alto|medio|bajo (bandas sobre puntaje)
    source_note     TEXT NOT NULL DEFAULT '',
    url             TEXT NOT NULL,
    portal          TEXT NOT NULL,      -- nombre original del portal
    tema            TEXT NOT NULL DEFAULT '',
    puntaje         REAL NOT NULL,
    score_crudo     REAL,
    score_ajustado  REAL,
    created_at_utc  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_noticias_date ON noticias(date);
"""


def init_schema(conn: sqlite3.Connection):
    conn.executescript(DDL)
    conn.commit()


# ── Dedupe inter-día ──────────────────────────────────────────────────────

def titulos_recientes(conn: sqlite3.Connection, dias: int = DEDUPE_DIAS) -> list:
    """Títulos de los últimos `dias` días de la tabla noticias (para dedupe
    fuzzy). Si la tabla está vacía devuelve []."""
    rows = conn.execute(
        "SELECT title FROM noticias WHERE date >= date('now', '-4 hours', ?)",
        (f"-{dias} days",)
    ).fetchall()
    return [r[0] for r in rows]


def es_repetida(titulo: str, titulos_previos: list) -> bool:
    limpio = scraper._titulo_limpio(titulo)
    for previo in titulos_previos:
        if scraper.similitud(limpio, scraper._titulo_limpio(previo)) >= UMBRAL_DEDUP_DB:
            return True
    return False


# ── Debug CSV (gitignored; diagnóstico de la corrida y tuning de bandas) ──

def escribir_csv_debug(candidatos: list, fecha: str):
    out = scraper.DATA_DIR / f"candidatos_{fecha}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    columnas = ["puntaje", "tema", "portal", "titulo", "link",
                "score_crudo", "score_ajustado", "ajuste_aplicado"]
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        writer.writeheader()
        for c in candidatos:
            writer.writerow(c)
    return out


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Ingesta diaria de noticias (tab Noticias)")
    ap.add_argument("--db", type=Path, default=NORMALIZED_DB,
                    help=f"Path a la DB (default: {NORMALIZED_DB})")
    ap.add_argument("--dry-run", action="store_true",
                    help="Scrape + score + dedupe, sin escribir en la DB")
    ap.add_argument("--top", type=int, default=TOP_N,
                    help=f"Tope de notas a insertar (default: {TOP_N})")
    ap.add_argument("--umbral", type=float, default=UMBRAL_PUNTAJE,
                    help=f"Puntaje mínimo de selección (default: {UMBRAL_PUNTAJE})")
    args = ap.parse_args()

    # El scraper portado loguea con logging; los ingest del repo hablan por
    # stdout/stderr (el cron del VPS redirige a /var/log/binance_p2p/).
    logging.basicConfig(level=logging.INFO, format="[noticias] %(message)s",
                        stream=sys.stdout)

    t0 = time.time()
    hc_ping("start")
    ahora_utc = datetime.now(timezone.utc)

    # Fail-closed (addendum del brief): sin modelo TF-IDF no hay corrida.
    modelo = scraper.get_modelo()
    if not modelo.disponible:
        msg = (f"[noticias] ERROR modelo_no_disponible (fail-closed): "
               f"{modelo.motivo_rechazo or 'pkl ausente o ilegible'} — "
               f"no se scrapea ni inserta")
        print(msg, file=sys.stderr)
        hc_ping("fail", body=msg)
        return 1

    try:
        candidatos, descartados, ok, fail = scraper.correr_scraper()
    except Exception:
        tb = traceback.format_exc()
        print(f"[noticias] ERROR scraper_crash:\n{tb}", file=sys.stderr)
        hc_ping("fail", body=tb[-1500:])
        return 1

    # Fallo total de scrape (red caída, IP bloqueada, markup rot masivo):
    # correr_scraper no lanza — lo acumula en `fail`. Sin esto la corrida
    # pingearía éxito y el feed se congelaría en silencio.
    if not ok:
        msg = f"[noticias] ERROR scrape_total_fail: 0/{len(scraper.FUENTES)} portales ok"
        print(msg, file=sys.stderr)
        hc_ping("fail", body=msg)
        return 1

    # El href del frontend solo admite http/https: un portal comprometido no
    # debe poder colar un scheme ejecutable (javascript:/data:) vía link.
    candidatos = [c for c in candidatos
                  if urlparse(c["link"]).scheme in ("http", "https")]

    notas = [build_nota(c, ahora_utc) for c in candidatos]
    fecha = notas[0]["date"] if notas else ahora_utc.strftime("%Y-%m-%d")
    csv_path = escribir_csv_debug(candidatos, fecha)

    seleccion = [n for n in notas if n["puntaje"] >= args.umbral]
    seleccion.sort(key=lambda n: -n["puntaje"])
    print(f"[noticias] candidatos={len(candidatos)} descartados_scoring={len(descartados)} "
          f"sobre_umbral={len(seleccion)} umbral={args.umbral}")

    insertadas = 0
    repetidas = 0
    try:
        conn = sqlite3.connect(str(args.db))
        try:
            init_schema(conn)
            previos = titulos_recientes(conn)

            # Tope DIARIO: el presupuesto descuenta lo ya insertado hoy, así
            # una re-corrida (recovery manual, doble disparo) no infla el día
            # más allá de `--top` aunque los portales hayan publicado nuevo.
            ya_hoy = conn.execute(
                "SELECT COUNT(*) FROM noticias WHERE date = ?", (fecha,)
            ).fetchone()[0]
            budget = max(0, args.top - ya_hoy)
            if ya_hoy:
                print(f"[noticias] ya_insertadas_hoy={ya_hoy} budget_restante={budget}")

            finales = []
            for n in seleccion:
                if len(finales) >= budget:
                    break
                if es_repetida(n["title"], previos):
                    repetidas += 1
                    continue
                finales.append(n)
                previos.append(n["title"])  # dedupe también dentro de la selección

            if args.dry_run:
                for n in finales:
                    print(f"[noticias] dry-run: {n['puntaje']:.1f} [{n['category']}] "
                          f"{n['portal']}: {n['title'][:70]}")
            else:
                for n in finales:
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO noticias
                           (id, date, time, source, category, title, summary, detail,
                            topics, impact, source_note, url, portal, tema, puntaje,
                            score_crudo, score_ajustado, created_at_utc)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (n["id"], n["date"], n["time"], n["source"], n["category"],
                         n["title"], n["summary"], n["detail"], json.dumps(n["topics"], ensure_ascii=False),
                         n["impact"], n["sourceNote"], n["url"], n["portal"], n["tema"],
                         n["puntaje"], n["score_crudo"], n["score_ajustado"],
                         n["created_at_utc"]))
                    insertadas += cur.rowcount
                conn.commit()
        finally:
            conn.close()
    except Exception:
        tb = traceback.format_exc()
        print(f"[noticias] ERROR db_crash:\n{tb}", file=sys.stderr)
        hc_ping("fail", body=tb[-1500:])
        return 1

    dur = time.time() - t0
    # `scoring` viaja en el body del hc_ping. Con el fail-closed de arriba
    # siempre será tfidf; se mantiene como invariante observable.
    scoring = "tfidf" if scraper.get_modelo().disponible else "keywords"
    summary = (f"[noticias] mode={'dry-run' if args.dry_run else 'ok'} "
               f"scoring={scoring} "
               f"fecha={fecha} candidatos={len(candidatos)} sobre_umbral={len(seleccion)} "
               f"dedupe_interdia={repetidas} insertadas={insertadas} "
               f"portales_ok={len(ok)} portales_fail={len(fail)} "
               f"csv={csv_path.name} duration_s={dur:.0f}")
    print(summary)
    if fail:
        print(f"[noticias] WARN portales_fail: {', '.join(fail)}", file=sys.stderr)

    hc_ping(body=summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
