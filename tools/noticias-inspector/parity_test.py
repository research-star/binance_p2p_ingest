"""PARITY TEST (acceptance #1).

Replays ONE captured candidate snapshot through (a) the REAL ingest_noticias.lane_bolivia
and (b) the inspector's mirror, over identical fresh DBs, and asserts the set X (the IDs
that survive to insert) is identical. If the mirror ever drifts from the real lane
sequence, this fails — that's the manual-sync alarm.

Offline: monkeypatches scraper.correr_scraper to return the snapshot (no network), exactly
like scripts/test_noticias_budget_cache.py. Run:  python parity_test.py
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

import insp_config as cfg  # noqa: F401  (sys.path -> repo root)
import inspector_core as core
import ingest_noticias as ing


def _cand(link, titulo, puntaje, tema="Deuda / Finanzas", entidades=None, descripcion=""):
    return {"portal": "El Deber", "link": link, "titulo": titulo, "descripcion": descripcion,
            "cuerpo": "", "tema": tema, "tema_hits": 1, "entidades": entidades or [],
            "puntaje": puntaje, "score_crudo": None, "score_ajustado": None, "image_url": ""}


def build_snapshot():
    """A candidate set that exercises every Bolivia lane gate: threshold, event-grouping,
    rolling budget (top=3), inter-day dedupe, sponsored + bad-scheme filters."""
    DUP = "Exportaciones de soya crecen 12% según el IBCE"
    cands = [
        _cand("https://eldeber.com.bo/eco/a_1", "Reservas del BCB suben tras nuevo crédito del FMI", 8.6, "Deuda / Finanzas", ["BCB", "FMI"]),
        _cand("https://eldeber.com.bo/eco/a_2", "El FMI proyecta el déficit fiscal de Bolivia en 2026", 8.1, "Deuda / Finanzas", ["FMI"]),
        _cand("https://eldeber.com.bo/eco/a_3", "YPFB anuncia nueva inversión en exploración de gas", 7.8, "Combustibles / YPFB", ["YPFB"]),
        _cand("https://eldeber.com.bo/eco/a_4", "Bolivia coloca bonos soberanos en el mercado de capitales", 7.2, "Deuda / Finanzas", ["Gobierno"]),
        _cand("https://eldeber.com.bo/eco/a_5", DUP, 7.9, "Exportaciones / Comercio", ["IBCE"]),       # dup of `previos`
        _cand("https://eldeber.com.bo/eco/a_6", "Nota de bajo puntaje sobre trámites varios", 4.0),     # < umbral
        _cand("javascript:alert(1)", "Inyección de scheme no http", 9.0),                               # scheme filter
        _cand("https://eldeber.com.bo/publirreportaje/promo", "Contenido patrocinado de un banco", 9.0),  # sponsored
    ]
    return (cands, [], ["El Deber"], [])


def _fresh_db():
    tmp = Path(tempfile.mkdtemp(prefix="fb_inspector_parity_"))
    db = tmp / "noticias.db"
    cache = tmp / "cache_urls.db"
    conn = sqlite3.connect(str(db))
    ing.init_schema(conn)
    conn.commit()
    return conn, db, cache


def run():
    snap = build_snapshot()
    DUP = "Exportaciones de soya crecen 12% según el IBCE"
    ahora = datetime(2026, 6, 23, 16, 0, 0, tzinfo=timezone.utc)
    fecha_bo = ahora.astimezone(timezone(timedelta(hours=-4))).strftime("%Y-%m-%d")
    args = SimpleNamespace(umbral=ing.UMBRAL_PUNTAJE, top=3, top_latam=8, dry_run=False)

    # ── (a) REAL lane_bolivia ────────────────────────────────────────────────
    connA, dbA, cacheA = _fresh_db()
    pre_ids = {r[0] for r in connA.execute("SELECT id FROM noticias").fetchall()}
    with core.harness(cacheA, snapshot=snap):
        resA = ing.lane_bolivia(connA, args, ahora, fecha_bo, previos=[(DUP, set())])
    real_ids = {r[0] for r in connA.execute("SELECT id FROM noticias").fetchall()} - pre_ids
    real_titles = {r[0] for r in connA.execute(
        "SELECT title FROM noticias WHERE id IN ({})".format(
            ",".join("?" * len(real_ids))), tuple(real_ids)).fetchall()} if real_ids else set()
    connA.close()

    # ── (b) inspector mirror ─────────────────────────────────────────────────
    connB, dbB, cacheB = _fresh_db()
    with core.harness(cacheB, snapshot=snap):
        previosB = [(DUP, set())]
        mir = core.mirror_bolivia(snap, connB, args, ahora, fecha_bo, previosB)
    connB.close()
    mir_ids = {n["id"] for n in mir["finales"]}
    mir_titles = {n["title"] for n in mir["finales"]}

    # ── Assert parity ────────────────────────────────────────────────────────
    errors = []
    if resA["estado"] != "ok":
        errors.append(f"real lane estado={resA['estado']} detalle={resA.get('detalle')}")
    if real_ids != mir_ids:
        errors.append(f"SET X MISMATCH:\n    real-only ids: {real_ids - mir_ids}\n    mirror-only ids: {mir_ids - real_ids}")
    if real_titles != mir_titles:
        errors.append(f"title mismatch:\n    real-only: {real_titles - mir_titles}\n    mirror-only: {mir_titles - real_titles}")
    if resA.get("insertadas") != len(mir_ids):
        errors.append(f"count: real insertadas={resA.get('insertadas')} vs mirror finales={len(mir_ids)}")

    print("── PARITY: real lane_bolivia vs inspector mirror ──")
    print(f"  real inserted : {resA.get('insertadas')}  ids={sorted(i[:12] for i in real_ids)}")
    print(f"  mirror set X  : {len(mir_ids)}  ids={sorted(i[:12] for i in mir_ids)}")
    print(f"  budget={mir.get('budget')} ya_hoy={mir.get('ya_hoy')}  (top={args.top})")
    print("  funnel (mirror):")
    for s in core.pipeline_map.BOLIVIA_STAGES:
        st = mir["stages"].get(s["i"], {})
        if st.get("out") is not None or st.get("killed"):
            print(f"     {s['i']:>2}. {s['name']:<34} out={st.get('out')}  killed={len(st.get('killed', []))}")

    if errors:
        print("\nFAIL parity_test:")
        for e in errors:
            print("  -", e)
        return 1
    print("\nOK parity_test: inspector set X == real lane_bolivia set X (mismos IDs + títulos + conteo).")
    return 0


if __name__ == "__main__":
    sys.exit(run())
