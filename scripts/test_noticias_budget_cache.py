#!/usr/bin/env python3
"""
test_noticias_budget_cache.py — Test del fix de cacheo + budget rolling (FASE 3).

Verifica el bug que arregla la Capa 3: antes, correr_scraper marcaba como vista
TODA candidata evaluada, así que una nota calificada (>= umbral) que perdía el
top-N quedaba marcada y NUNCA se reconsideraba. El fix mueve el marcado al caller
(ingest_noticias.lane_bolivia), que marca SOLO insertadas + no-calificadas; las
calificadas-no-insertadas quedan sin marcar → reconsiderables.

Corre sobre DBs temporales (NUNCA la prod). No toca red ni el modelo real
(stubs). Uso:  python scripts/test_noticias_budget_cache.py
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ingest_noticias
from noticias_ingest import scraper


def _cand(link, titulo, puntaje):
    return {
        "portal": "El Deber", "link": link, "titulo": titulo,
        "descripcion": "", "cuerpo": "", "tema": "General",
        "puntaje": puntaje, "score_crudo": None, "score_ajustado": None,
        "image_url": "",
    }


def run():
    tmp = Path(tempfile.mkdtemp(prefix="fb_noticias_test_"))
    db_path = tmp / "test.db"
    cache_path = tmp / "cache_urls.db"

    # Stub del modelo (disponible) y del scraper (candidatos fijos).
    scraper.get_modelo = lambda: SimpleNamespace(disponible=True, motivo_rechazo="")
    scraper.CACHE_DB_PATH = cache_path  # marcar_urls_vistas lee el global en runtime

    INSERTADA = "https://eldeber.com.bo/economia/nota-top_1781800000"
    PERDIO_BUDGET = "https://eldeber.com.bo/economia/nota-segunda_1781800001"
    NO_CALIFICO = "https://eldeber.com.bo/economia/nota-baja_1781800002"
    candidatos = [
        _cand(INSERTADA, "Reservas internacionales del BCB suben tras nuevo crédito", 8.0),
        _cand(PERDIO_BUDGET, "Exportaciones de soya crecen 12% segun el IBCE", 7.0),
        _cand(NO_CALIFICO, "Nota economica de bajo puntaje sobre tramites", 4.0),
    ]
    scraper.correr_scraper = lambda *a, **k: (candidatos, [], ["El Deber"], [])
    scraper.FUENTES = scraper.FUENTES  # intacto

    conn = sqlite3.connect(str(db_path))
    ingest_noticias.init_schema(conn)

    ahora = datetime.now(timezone.utc)
    fecha_bo = ahora.astimezone(timezone(timedelta(hours=-4))).strftime("%Y-%m-%d")
    # top=1 → solo entra la de mayor puntaje (8.0); la de 7.0 califica pero pierde budget.
    args = SimpleNamespace(umbral=6.7, top=1, top_latam=8, dry_run=False)

    res = ingest_noticias.lane_bolivia(conn, args, ahora, fecha_bo, previos=[])
    conn.close()

    # ── Asserts ──
    errores = []
    if res["estado"] != "ok":
        errores.append(f"lane estado={res['estado']} detalle={res.get('detalle')}")
    if res["insertadas"] != 1:
        errores.append(f"insertadas={res['insertadas']} (esperado 1)")
    if res["sobre_umbral"] != 2:
        errores.append(f"sobre_umbral={res['sobre_umbral']} (esperado 2)")

    cache = sqlite3.connect(str(cache_path))
    vistas = {r[0] for r in cache.execute("SELECT url FROM urls_vistas").fetchall()}
    cache.close()

    if INSERTADA not in vistas:
        errores.append("la INSERTADA deberia estar marcada como vista")
    if NO_CALIFICO not in vistas:
        errores.append("la NO_CALIFICO (< umbral) deberia estar marcada como vista")
    if PERDIO_BUDGET in vistas:
        errores.append("BUG: la calificada que perdio budget quedo marcada → "
                       "no seria reconsiderable (esto es justo lo que el fix evita)")

    if errores:
        print("FAIL test_noticias_budget_cache:")
        for e in errores:
            print("  -", e)
        return 1
    print("OK test_noticias_budget_cache: insertada+no_calificada marcadas; "
          "calificada-no-insertada SIN marcar (reconsiderable).")
    return 0


if __name__ == "__main__":
    sys.exit(run())
