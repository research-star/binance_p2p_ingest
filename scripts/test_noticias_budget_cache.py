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

    INSERTADA1 = "https://eldeber.com.bo/economia/nota-top_1781800000"
    DEDUPE_LOSER = "https://eldeber.com.bo/economia/nota-dup_1781800001"
    INSERTADA2 = "https://eldeber.com.bo/economia/nota-tercera_1781800002"
    PERDIO_BUDGET = "https://eldeber.com.bo/economia/nota-cuarta_1781800003"
    NO_CALIFICO = "https://eldeber.com.bo/economia/nota-baja_1781800004"
    DUP_TITLE = "Exportaciones de soya crecen 12% segun el IBCE"
    candidatos = [
        _cand(INSERTADA1, "Reservas internacionales del BCB suben tras nuevo credito", 8.0),
        _cand(DEDUPE_LOSER, DUP_TITLE, 7.9),     # gemelo de una ya publicada (previos)
        _cand(INSERTADA2, "El FMI proyecta el deficit fiscal de Bolivia en 2026", 7.5),
        _cand(PERDIO_BUDGET, "Bolivia coloca bonos soberanos en el mercado de capitales", 7.0),
        _cand(NO_CALIFICO, "Nota economica de bajo puntaje sobre tramites varios", 4.0),
    ]
    scraper.correr_scraper = lambda *a, **k: (candidatos, [], ["El Deber"], [])

    conn = sqlite3.connect(str(db_path))
    ingest_noticias.init_schema(conn)

    ahora = datetime.now(timezone.utc)
    fecha_bo = ahora.astimezone(timezone(timedelta(hours=-4))).strftime("%Y-%m-%d")
    # top=2 → entran 8.0 y 7.5; la 7.9 se va por dedupe (dup de previos); la 7.0
    # califica pero pierde budget; la 4.0 no califica.
    args = SimpleNamespace(umbral=6.7, top=2, top_latam=8, dry_run=False)

    res = ingest_noticias.lane_bolivia(conn, args, ahora, fecha_bo, previos=[(DUP_TITLE, set())])
    conn.close()

    # ── Asserts ──
    errores = []
    if res["estado"] != "ok":
        errores.append(f"lane estado={res['estado']} detalle={res.get('detalle')}")
    if res["insertadas"] != 2:
        errores.append(f"insertadas={res['insertadas']} (esperado 2)")
    if res["sobre_umbral"] != 4:
        errores.append(f"sobre_umbral={res['sobre_umbral']} (esperado 4)")
    if res["dedupe"] != 1:
        errores.append(f"dedupe={res['dedupe']} (esperado 1)")

    cache = sqlite3.connect(str(cache_path))
    vistas = {r[0] for r in cache.execute("SELECT url FROM urls_vistas").fetchall()}
    cache.close()

    for url, etiq in ((INSERTADA1, "INSERTADA1"), (INSERTADA2, "INSERTADA2"),
                      (NO_CALIFICO, "NO_CALIFICO (< umbral)"),
                      (DEDUPE_LOSER, "DEDUPE_LOSER (gemelo, no insertable)")):
        if url not in vistas:
            errores.append(f"la {etiq} deberia estar marcada como vista")
    if PERDIO_BUDGET in vistas:
        errores.append("BUG: la calificada que perdio budget quedo marcada → "
                       "no seria reconsiderable (esto es justo lo que el fix evita)")

    if errores:
        print("FAIL test_noticias_budget_cache:")
        for e in errores:
            print("  -", e)
        return 1
    print("OK test_noticias_budget_cache: insertadas + no-calificada + dedupe-loser marcadas; "
          "budget-loser SIN marcar (reconsiderable).")
    return 0


if __name__ == "__main__":
    sys.exit(run())
