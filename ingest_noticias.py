#!/usr/bin/env python3
"""
ingest_noticias.py — Pipeline diario de la tab Noticias. Dos carriles:

BOLIVIA: scrape 13 portales (noticias_ingest/scraper.py, port de boletines)
→ score TF-IDF → filtro editorial puntaje >= 6.7 → dedupe inter-día fuzzy
→ presupuesto top-10/día → INSERT idempotente.
Fail-closed en scoring: sin modelo TF-IDF el carril NO corre (el corte 6.7
está calibrado para la escala TF-IDF; el fallback keywords la rompería en
silencio).

LATAM: sección Latinoamérica de Bloomberg Línea vía RSS
(noticias_ingest/latam.py) — SIN scoring, su criterio editorial es el
filtro. pubDate últimas 24 h, orden desc, cupo 5/día con presupuesto
INDEPENDIENTE del carril Bolivia. date/time = pubDate real.

Fail-safe por carril: si un carril falla, el otro corre igual; el body del
ping a HC_NOTICIAS reporta qué carriles corrieron y cuántas insertó cada
uno. Cualquier carril en error → ping fail + exit 1 (lo insertado por el
carril sano persiste).

Idempotencia (ambos carriles): PK = hash del link/guid normalizado
(INSERT OR IGNORE) + dedupe fuzzy por título (>= 0.70) contra los últimos
7 días de la tabla + presupuesto diario que descuenta lo ya insertado hoy.
El carril Bolivia suma su caché de URLs vistas (TTL 7 días).

Uso:
    python ingest_noticias.py                  # corrida normal
    python ingest_noticias.py --db test.db     # DB alternativa (dev)
    python ingest_noticias.py --dry-run        # sin escribir en la DB
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
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

import requests

from config import NORMALIZED_DB
from noticias_ingest import latam, scraper
from noticias_ingest.transform import build_nota, build_nota_latam

# ── Constantes ────────────────────────────────────────────────────────────

UMBRAL_PUNTAJE = 6.7   # corte editorial carril Bolivia (decisión cerrada)
TOP_N = 10             # tope diario carril Bolivia
LATAM_TOP_N = 5        # tope diario carril latam (presupuesto independiente)
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
# Nota: en filas del carril latam, puntaje=0.0 es sentinela "sin scoring"
# (la columna es NOT NULL; el piso del carril Bolivia es 6.7, no colisiona).

DDL = """
CREATE TABLE IF NOT EXISTS noticias (
    id              TEXT PRIMARY KEY,   -- hash MD5 corto del link normalizado
    date            TEXT NOT NULL,      -- YYYY-MM-DD (Bolivia UTC-4): corrida (BO) / pubDate (latam)
    time            TEXT NOT NULL,      -- HH:MM (Bolivia UTC-4): corrida (BO) / pubDate (latam)
    source          TEXT NOT NULL,      -- slug del portal (key de NOTICIAS_PORTALS)
    category        TEXT NOT NULL,      -- economia|hidrocarburos|agro|mineria|latam|politica
    title           TEXT NOT NULL,
    summary         TEXT NOT NULL DEFAULT '',
    detail          TEXT NOT NULL DEFAULT '',
    topics          TEXT NOT NULL DEFAULT '[]',  -- JSON array (tema original de boletines)
    impact          TEXT NOT NULL,      -- alto|medio|bajo (bandas sobre puntaje; latam: medio fijo)
    source_note     TEXT NOT NULL DEFAULT '',
    url             TEXT NOT NULL,
    portal          TEXT NOT NULL,      -- nombre original del portal
    tema            TEXT NOT NULL DEFAULT '',
    puntaje         REAL NOT NULL,
    score_crudo     REAL,
    score_ajustado  REAL,
    created_at_utc  TEXT NOT NULL,
    image_url       TEXT                -- og:image hotlinkeable (carril BO, FASE 2a); NULL si no hay / El Deber / latam. Última col = espejo del ALTER de 0004.
);
CREATE INDEX IF NOT EXISTS idx_noticias_date ON noticias(date);
"""


def init_schema(conn: sqlite3.Connection):
    conn.executescript(DDL)
    conn.commit()


# ── Dedupe inter-día ──────────────────────────────────────────────────────

def titulos_recientes(conn: sqlite3.Connection, dias: int = DEDUPE_DIAS) -> list:
    """Títulos de los últimos `dias` días de la tabla noticias (ambos
    carriles) para dedupe fuzzy. [] si la tabla está vacía."""
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


# ── Inserción común ───────────────────────────────────────────────────────

def insertar_notas(conn: sqlite3.Connection, notas: list) -> int:
    insertadas = 0
    for n in notas:
        cur = conn.execute(
            """INSERT OR IGNORE INTO noticias
               (id, date, time, source, category, title, summary, detail,
                topics, impact, source_note, url, portal, tema, puntaje,
                score_crudo, score_ajustado, created_at_utc, image_url)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (n["id"], n["date"], n["time"], n["source"], n["category"],
             n["title"], n["summary"], n["detail"], json.dumps(n["topics"], ensure_ascii=False),
             n["impact"], n["sourceNote"], n["url"], n["portal"], n["tema"],
             n["puntaje"], n["score_crudo"], n["score_ajustado"],
             n["created_at_utc"], n.get("image_url")))
        insertadas += cur.rowcount
    conn.commit()
    return insertadas


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


# ── Carril Bolivia ────────────────────────────────────────────────────────

def lane_bolivia(conn, args, ahora_utc, fecha_bo, previos) -> dict:
    """Scrape + score + corte 6.7 + dedupe + presupuesto top-N + insert.
    Devuelve dict-resumen; estado='error' nunca propaga excepción."""
    res = {"estado": "ok", "insertadas": 0, "candidatos": 0,
           "sobre_umbral": 0, "dedupe": 0, "detalle": "", "scoring": "desconocido"}
    try:
        # Fail-closed: sin modelo TF-IDF este carril no corre.
        modelo = scraper.get_modelo()
        res["scoring"] = "tfidf" if modelo.disponible else "keywords"
        if not modelo.disponible:
            res["estado"] = "error"
            res["detalle"] = (f"modelo_no_disponible (fail-closed): "
                              f"{modelo.motivo_rechazo or 'pkl ausente o ilegible'}")
            return res

        candidatos, descartados, ok, fail = scraper.correr_scraper()
        if not ok:
            res["estado"] = "error"
            res["detalle"] = f"scrape_total_fail: 0/{len(scraper.FUENTES)} portales ok"
            return res
        if fail:
            print(f"[noticias] WARN portales_fail: {', '.join(fail)}", file=sys.stderr)

        # El href del frontend solo admite http/https: un portal comprometido
        # no debe poder colar un scheme ejecutable (javascript:/data:).
        candidatos = [c for c in candidatos
                      if urlparse(c["link"]).scheme in ("http", "https")]
        res["candidatos"] = len(candidatos)

        notas = [build_nota(c, ahora_utc) for c in candidatos]
        escribir_csv_debug(candidatos, fecha_bo)

        seleccion = [n for n in notas if n["puntaje"] >= args.umbral]
        seleccion.sort(key=lambda n: -n["puntaje"])
        res["sobre_umbral"] = len(seleccion)

        # Presupuesto diario: descuenta lo ya insertado hoy en ESTE carril
        # (excluye latam: presupuestos independientes).
        ya_hoy = conn.execute(
            "SELECT COUNT(*) FROM noticias WHERE date = ? AND category != 'latam'",
            (fecha_bo,)).fetchone()[0]
        budget = max(0, args.top - ya_hoy)
        if ya_hoy:
            print(f"[noticias] bolivia: ya_insertadas_hoy={ya_hoy} budget_restante={budget}")

        finales = []
        for n in seleccion:
            if len(finales) >= budget:
                break
            if es_repetida(n["title"], previos):
                res["dedupe"] += 1
                continue
            finales.append(n)
            previos.append(n["title"])

        if args.dry_run:
            for n in finales:
                print(f"[noticias] dry-run bolivia: {n['puntaje']:.1f} "
                      f"[{n['category']}] {n['portal']}: {n['title'][:70]}")
        else:
            res["insertadas"] = insertar_notas(conn, finales)
    except Exception:
        conn.rollback()  # aislamiento por carril: no dejar inserts a medias
        tb = traceback.format_exc()
        print(f"[noticias] ERROR lane_bolivia:\n{tb}", file=sys.stderr)
        res["estado"] = "error"
        res["detalle"] = tb.strip().splitlines()[-1][:200]
    return res


# ── Carril Latam ──────────────────────────────────────────────────────────

def lane_latam(conn, args, ahora_utc, fecha_bo, previos) -> dict:
    """RSS Bloomberg Línea sección Latinoamérica: pubDate 24h, orden desc,
    cupo independiente, sin scoring. estado='error' solo si el feed no
    entregó nada utilizable (0 ítems en 24h con feed sano es ok)."""
    res = {"estado": "ok", "insertadas": 0, "items_24h": 0,
           "dedupe": 0, "detalle": ""}
    try:
        entries = latam.fetch_entries_latam()
        if not entries:
            res["estado"] = "error"
            res["detalle"] = "feed_sin_items: sección y fallback no entregaron nada"
            return res

        recientes = latam.entries_ultimas_24h(entries, ahora_utc)
        res["items_24h"] = len(recientes)

        notas = []
        for pub_utc, e in recientes:
            n = build_nota_latam(pub_utc, e, ahora_utc)
            if urlparse(n["url"]).scheme in ("http", "https"):
                notas.append(n)

        # Presupuesto independiente, por día de corrida (BO) sobre
        # created_at_utc: el `date` de estas filas es el pubDate, que puede
        # caer en ayer — el cupo es de inserción diaria, no de fecha visible.
        ya_hoy = conn.execute(
            "SELECT COUNT(*) FROM noticias WHERE category = 'latam' "
            "AND date(created_at_utc, '-4 hours') = ?",
            (fecha_bo,)).fetchone()[0]
        budget = max(0, args.top_latam - ya_hoy)
        if ya_hoy:
            print(f"[noticias] latam: ya_insertadas_hoy={ya_hoy} budget_restante={budget}")

        finales = []
        for n in notas:
            if len(finales) >= budget:
                break
            if es_repetida(n["title"], previos):
                res["dedupe"] += 1
                continue
            finales.append(n)
            previos.append(n["title"])

        if args.dry_run:
            for n in finales:
                print(f"[noticias] dry-run latam: {n['date']} {n['time']} "
                      f"{n['title'][:70]}")
        else:
            res["insertadas"] = insertar_notas(conn, finales)
    except Exception:
        conn.rollback()  # aislamiento por carril: no dejar inserts a medias
        tb = traceback.format_exc()
        print(f"[noticias] ERROR lane_latam:\n{tb}", file=sys.stderr)
        res["estado"] = "error"
        res["detalle"] = tb.strip().splitlines()[-1][:200]
    return res


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Ingesta diaria de noticias (tab Noticias)")
    ap.add_argument("--db", type=Path, default=NORMALIZED_DB,
                    help=f"Path a la DB (default: {NORMALIZED_DB})")
    ap.add_argument("--dry-run", action="store_true",
                    help="Corre ambos carriles sin escribir en la DB")
    ap.add_argument("--top", type=int, default=TOP_N,
                    help=f"Tope diario carril Bolivia (default: {TOP_N})")
    ap.add_argument("--top-latam", type=int, default=LATAM_TOP_N,
                    help=f"Tope diario carril latam (default: {LATAM_TOP_N})")
    ap.add_argument("--umbral", type=float, default=UMBRAL_PUNTAJE,
                    help=f"Puntaje mínimo carril Bolivia (default: {UMBRAL_PUNTAJE})")
    args = ap.parse_args()

    # El scraper portado loguea con logging; los ingest del repo hablan por
    # stdout/stderr (el cron del VPS redirige a /var/log/binance_p2p/).
    logging.basicConfig(level=logging.INFO, format="[noticias] %(message)s",
                        stream=sys.stdout)

    t0 = time.time()
    hc_ping("start")
    ahora_utc = datetime.now(timezone.utc)
    fecha_bo = (ahora_utc.astimezone(timezone(timedelta(hours=-4)))).strftime("%Y-%m-%d")

    try:
        conn = sqlite3.connect(str(args.db))
        try:
            init_schema(conn)
            previos = titulos_recientes(conn)
            res_bo = lane_bolivia(conn, args, ahora_utc, fecha_bo, previos)
            res_lt = lane_latam(conn, args, ahora_utc, fecha_bo, previos)
        finally:
            conn.close()
    except Exception:
        tb = traceback.format_exc()
        print(f"[noticias] ERROR db_crash:\n{tb}", file=sys.stderr)
        hc_ping("fail", body=tb[-1500:])
        return 1

    dur = time.time() - t0
    # El modo de scoring lo reporta el carril Bolivia (re-instanciar el
    # modelo acá podría re-lanzar la excepción que el lane ya absorbió).
    scoring = res_bo.get("scoring", "desconocido")

    def _lane_str(nombre, r, extra):
        if r["estado"] == "error":
            return f"{nombre}=ERROR({r['detalle']})"
        return f"{nombre}=ok insertadas={r['insertadas']} {extra} dedupe={r['dedupe']}"

    summary = (f"[noticias] mode={'dry-run' if args.dry_run else 'ok'} "
               f"scoring={scoring} fecha={fecha_bo} "
               + _lane_str("bolivia", res_bo,
                           f"candidatos={res_bo['candidatos']} sobre_umbral={res_bo['sobre_umbral']}")
               + " | "
               + _lane_str("latam", res_lt, f"items_24h={res_lt['items_24h']}")
               + f" duration_s={dur:.0f}")
    print(summary)

    if res_bo["estado"] == "error" or res_lt["estado"] == "error":
        hc_ping("fail", body=summary)
        return 1
    hc_ping(body=summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
