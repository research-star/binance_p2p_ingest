#!/usr/bin/env python3
"""
ingest_noticias.py — Pipeline diario de la tab Noticias. Dos carriles:

BOLIVIA: scrape 13 portales (noticias_ingest/scraper.py, port de boletines)
→ score TF-IDF → filtro editorial puntaje >= 6.7 → dedupe inter-día fuzzy
→ presupuesto top-10/día → INSERT idempotente.
Resiliencia en scoring: con modelo TF-IDF, score normal. Sin modelo, modo
DEGRADADO por keywords (NO fail-closed): solo pasan las notas con keyword
forzada institucional (puntaje=10 > corte 6.7) — feed reducido pero curado y
anclado en Bolivia. El ping reporta scoring=keywords (no es silencioso).

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

from config import NORMALIZED_DB, NOTICIAS_TOP_BOLIVIA, NOTICIAS_TOP_LATAM
from noticias_ingest import latam, resumen_ia, scraper
from noticias_ingest.transform import build_nota, build_nota_latam

# ── Constantes ────────────────────────────────────────────────────────────

UMBRAL_PUNTAJE = 6.7   # corte editorial carril Bolivia (decisión cerrada)
TOP_N = NOTICIAS_TOP_BOLIVIA    # tope diario carril Bolivia (config.py)
LATAM_TOP_N = NOTICIAS_TOP_LATAM  # tope diario carril latam (config.py, presupuesto independiente)
DEDUPE_DIAS = 7        # ventana de dedupe inter-día contra la tabla noticias
UMBRAL_DEDUP_DB = 0.70
# Agrupación por EVENTO dentro de una corrida ("También en…"): título muy similar,
# o moderadamente similar + entidades compartidas. Conservador (calibración
# 2026-06-21): preferimos NO fusionar de más (un falso merge esconde una nota).
UMBRAL_EVENTO_TIT = 0.70   # solo por título (igual al dedupe inter-día)
UMBRAL_EVENTO_ENT = 0.50   # título moderado, exige ≥1 entidad compartida

# Expresión SQL del carril, robusta a filas legacy (col `carril` aún NULL antes de
# aplicar 0005 / backfill): usa la columna nueva con fallback a la category vieja
# ('latam' legacy). Las filas de HOY siempre traen carril (código nuevo), así que
# el fallback solo afecta a filas viejas — fuera de la ventana de los budgets.
CARRIL_SQL = ("COALESCE(carril, CASE WHEN category = 'latam' "
              "THEN 'latam' ELSE 'bolivia' END)")

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
    category        TEXT NOT NULL,      -- economia|politica (colapsada FASE 3; el carril Latam va en la col carril)
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
    image_url       TEXT,               -- og:image hotlinkeable (carril BO, FASE 2a); NULL si no hay / El Deber / latam (col del ALTER de 0004).
    carril          TEXT,               -- 'bolivia'|'latam': carril del feed (antes implícito en category=='latam'). Col del ALTER de 0005.
    tema_hits       INTEGER,            -- confianza del tema (clasificación v1; strong*10 + weak-con-contexto). Col del ALTER de 0005.
    entidades       TEXT,               -- JSON array de entidades canónicas (BCB, YPFB, YLB…). Col del ALTER de 0005.
    tambien_en      TEXT                -- JSON [{source,portal,url}] del mismo evento en otros medios (calibración 2026-06-21).
);
CREATE INDEX IF NOT EXISTS idx_noticias_date ON noticias(date);
"""

# Columnas añadidas por ALTER (0005): no las crea CREATE TABLE IF NOT EXISTS sobre
# una tabla preexistente. (col, decl) — el self-migrate de init_schema las agrega
# idempotente; tema/puntaje ya existen de 0002.
_COLS_V1 = (("carril", "TEXT"), ("tema_hits", "INTEGER"), ("entidades", "TEXT"),
            ("tambien_en", "TEXT"))  # tambien_en: calibración 2026-06-21 ("También en…")


def init_schema(conn: sqlite3.Connection):
    conn.executescript(DDL)
    # Self-migrate idempotente de columnas nuevas sobre DB con la tabla vieja:
    # SQLite no tiene ADD COLUMN IF NOT EXISTS → se traga el "duplicate column"
    # por columna. Desacopla el INSERT de cuándo se aplica 0005 a mano en el VPS
    # (mismo patrón que el self-migrate de image_url en dashboard.py).
    for col, decl in _COLS_V1:
        try:
            conn.execute(f"ALTER TABLE noticias ADD COLUMN {col} {decl}")
        except sqlite3.OperationalError:
            pass  # columna ya existe (idempotente)
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


# ── Agrupación por evento + tier de fuente ("También en…") ──────────────────

# Tier de autoridad para elegir la REPRESENTANTE de un grupo del mismo evento
# (calibración 2026-06-21: oficiales/gremios = T1). Los slugs oficiales/gremios
# todavía NO se ingieren (ver "fuentes nuevas"); quedan listados para cuando se
# sumen. Default = T3. Es solo desempate de representante: NO altera el ranking
# por relevancia (los grupos se ordenan por su puntaje máximo).
SOURCE_TIER = {
    # T1 — fuentes primarias: oficiales + gremios (forward-looking).
    "bcb": 1, "ine": 1, "mefp": 1, "aduana": 1, "ypfb": 1,
    "cainco": 1, "ibce": 1, "cepb": 1, "cni": 1, "cao": 1, "anapo": 1,
    # T2 — periódicos grandes / agencia premium.
    "bloomberg": 2, "eldeber": 2, "lostiempos": 2, "larazon": 2,
    "eldia": 2, "correosur": 2, "brujula": 2,
    # T3 (default) — resto: unitel, eju, fides, erbol, urgente, opinion.
}


def source_tier(slug: str) -> int:
    return SOURCE_TIER.get(slug, 3)


def _mismo_evento(a: dict, b: dict) -> bool:
    """¿a y b cubren el mismo evento? Título muy similar, o moderadamente similar
    + al menos una entidad canónica compartida."""
    sim = scraper.similitud(scraper._titulo_limpio(a["title"]),
                            scraper._titulo_limpio(b["title"]))
    if sim >= UMBRAL_EVENTO_TIT:
        return True
    if sim >= UMBRAL_EVENTO_ENT:
        return bool(set(a.get("entidades") or []) & set(b.get("entidades") or []))
    return False


def agrupar_eventos(notas: list) -> list:
    """Colapsa notas del MISMO evento (misma corrida) a UNA representante que lleva
    `tambien_en` = [{source, portal, url}] de las demás. La representante es la de
    MENOR tier (desempate: mayor puntaje). Los grupos se devuelven ordenados por su
    puntaje MÁXIMO (relevancia del evento), no por el de la representante. NO hace
    dedupe inter-día (eso sigue en es_repetida). Asume `notas` pre-ordenadas por
    puntaje desc (así grp[0], usado para el match, es la de mayor puntaje del grupo)."""
    grupos = []  # list[list[nota]]
    for n in notas:
        g = next((grp for grp in grupos if _mismo_evento(n, grp[0])), None)
        if g is None:
            grupos.append([n])
        else:
            g.append(n)
    reps = []
    for g in grupos:
        gmax = max(x["puntaje"] for x in g)
        g.sort(key=lambda x: (source_tier(x["source"]), -x["puntaje"]))
        rep = g[0]
        vistos, te = {rep["source"]}, []
        for o in g[1:]:
            if o["source"] in vistos:
                continue
            vistos.add(o["source"])
            te.append({"source": o["source"], "portal": o["portal"], "url": o["url"]})
        if te:
            rep["tambien_en"] = te
        reps.append((gmax, rep))
    reps.sort(key=lambda x: -x[0])
    return [r for _, r in reps]


# ── Inserción común ───────────────────────────────────────────────────────

def insertar_notas(conn: sqlite3.Connection, notas: list) -> int:
    insertadas = 0
    for n in notas:
        cur = conn.execute(
            """INSERT OR IGNORE INTO noticias
               (id, date, time, source, category, title, summary, detail,
                topics, impact, source_note, url, portal, tema, puntaje,
                score_crudo, score_ajustado, created_at_utc, image_url, carril,
                tema_hits, entidades, tambien_en)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (n["id"], n["date"], n["time"], n["source"], n["category"],
             n["title"], n["summary"], n["detail"], json.dumps(n["topics"], ensure_ascii=False),
             n["impact"], n["sourceNote"], n["url"], n["portal"], n["tema"],
             n["puntaje"], n["score_crudo"], n["score_ajustado"],
             n["created_at_utc"], n.get("image_url"), n.get("carril"),
             n.get("tema_hits"), json.dumps(n.get("entidades") or [], ensure_ascii=False),
             json.dumps(n.get("tambien_en") or [], ensure_ascii=False)))
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
        # Resiliencia: modo DEGRADADO por keywords si el modelo TF-IDF no carga
        # (calibración 2026-06-21: antes era fail-closed y el carril Bolivia no
        # corría → feed en blanco). En degradado, evaluar() cae a score_keywords:
        # solo pasan las notas con KEYWORDS_FORZADO (institucional: YPFB/BCB/dólar/…)
        # porque su puntaje=10 supera el corte editorial; las de conteo (0-3) no.
        # Feed reducido pero curado y ANCLADO en Bolivia (el geo-gate universal de
        # evaluar() corre igual). NO es silencioso: el ping reporta scoring=keywords.
        modelo = scraper.get_modelo()
        res["scoring"] = "tfidf" if modelo.disponible else "keywords"
        if not modelo.disponible:
            print(f"[noticias] WARN modelo_degradado: usando keywords — "
                  f"{modelo.motivo_rechazo or 'pkl ausente o ilegible'}", file=sys.stderr)

        candidatos, descartados, ok, fail = scraper.correr_scraper()
        if not ok:
            res["estado"] = "error"
            res["detalle"] = f"scrape_total_fail: 0/{len(scraper.FUENTES)} portales ok"
            return res
        if fail:
            print(f"[noticias] WARN portales_fail: {', '.join(fail)}", file=sys.stderr)

        # El href del frontend solo admite http/https: un portal comprometido
        # no debe poder colar un scheme ejecutable (javascript:/data:). Y se
        # excluye el contenido patrocinado por sección/URL (calibración 2026-06-21).
        candidatos = [c for c in candidatos
                      if urlparse(c["link"]).scheme in ("http", "https")
                      and not scraper.es_url_patrocinada(c["link"])]
        res["candidatos"] = len(candidatos)

        notas = [build_nota(c, ahora_utc) for c in candidatos]
        escribir_csv_debug(candidatos, fecha_bo)

        seleccion = [n for n in notas if n["puntaje"] >= args.umbral]
        seleccion.sort(key=lambda n: -n["puntaje"])
        res["sobre_umbral"] = len(seleccion)
        # Agrupa por evento ("También en…"): colapsa la misma noticia cubierta por
        # varios medios a UNA representante (tier de fuente manda) que lleva las
        # otras fuentes en tambien_en. Antes del presupuesto → menos casi-duplicados
        # en el feed. Calibración 2026-06-21.
        seleccion = agrupar_eventos(seleccion)
        res["eventos"] = len(seleccion)

        # Presupuesto diario: descuenta lo ya insertado hoy en ESTE carril
        # (excluye latam: presupuestos independientes). El carril ya no se deriva
        # de category (colapsada) sino de la col `carril` (CARRIL_SQL = robusto a
        # legacy). Budget rolling: las corridas del día llenan hasta el cupo.
        ya_hoy = conn.execute(
            f"SELECT COUNT(*) FROM noticias WHERE date = ? AND {CARRIL_SQL} != 'latam'",
            (fecha_bo,)).fetchone()[0]
        budget = max(0, args.top - ya_hoy)
        if ya_hoy:
            print(f"[noticias] bolivia: ya_insertadas_hoy={ya_hoy} budget_restante={budget}")

        finales = []
        dedupe_losers = []
        for n in seleccion:
            if len(finales) >= budget:
                break  # budget-loser: queda SIN marcar (reconsiderable, yield real)
            if es_repetida(n["title"], previos):
                res["dedupe"] += 1
                dedupe_losers.append(n)  # gemelo de una nota ya publicada (no insertable ~7d)
                continue
            finales.append(n)
            previos.append(n["title"])

        if args.dry_run:
            for n in finales:
                print(f"[noticias] dry-run bolivia: {n['puntaje']:.1f} "
                      f"[{n['category']}] {n['portal']}: {n['title'][:70]}")
        else:
            n_resumen = resumen_ia.aplicar(finales)
            if n_resumen:
                print(f"[noticias] bolivia: resumen_ia aplicado a {n_resumen}/{len(finales)}")
            res["insertadas"] = insertar_notas(conn, finales)
            # Fix de cacheo (FASE 3): marcar como vistas lo que NO debe reconsiderarse:
            #  - insertadas (`finales`)
            #  - no-calificadas (puntaje < umbral): deterministas, no van a calificar
            #  - dedupe-losers: gemelos de una nota YA publicada; pierden el mismo
            #    dedupe de título mientras su par viva en titulos_recientes (~7d), así
            #    que NO son insertables — marcarlos evita re-scrapear su cuerpo cada
            #    corrida (clave con cadencia diurna cada 3h).
            # El budget-loser (calificado, perdió el cupo) queda SIN marcar: SÍ es
            # reconsiderable en una corrida posterior (budget rolling / día siguiente).
            # Antes correr_scraper marcaba TODO lo evaluado → las que perdían el top-N
            # se descartaban para siempre (bug de yield).
            vistas = [(n["url"], n["portal"]) for n in finales]
            vistas += [(n["url"], n["portal"]) for n in notas if n["puntaje"] < args.umbral]
            vistas += [(n["url"], n["portal"]) for n in dedupe_losers]
            scraper.marcar_urls_vistas(vistas)
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
            f"SELECT COUNT(*) FROM noticias WHERE {CARRIL_SQL} = 'latam' "
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
            n_resumen = resumen_ia.aplicar(finales)
            if n_resumen:
                print(f"[noticias] latam: resumen_ia aplicado a {n_resumen}/{len(finales)}")
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
