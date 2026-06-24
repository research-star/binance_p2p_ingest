"""Baseline capture — criterio-iteración-2 / FASE 1 (medición prod-fiel del funnel-v2).

Captura UNA corrida live, prod-fiel, del carril Bolivia sobre el seed refrescado del VPS,
CONGELA un fixture de replay determinista, y computa las métricas de diagnóstico que el IJ
necesita para decidir el próximo ajuste de criterio.

REGLA DURA (igual que el resto del inspector): NO reimplementa criterio. Importa y LLAMA el
funnel real (scraper.correr_scraper + ingest_noticias.lane_bolivia + el mirror del inspector).
Lo único propio es el arnés de captura/congelado.

Dos vistas, ambas deterministas desde el snapshot congelado:
  - CANONICAL  (top real=14): corre el lane_bolivia REAL con correr_scraper parcheado al
    snapshot + LAST_FUNNEL inyectado → res["funnel"] de 15 llaves, idéntico a prod. Es el
    baseline byte-estable (baseline_replay.py lo reproduce offline).
  - DIAGNÓSTICO (top=∞): corre el mirror del inspector sin que el budget diario enmascare la
    etapa de dedup ni el set de criterio. Base de las métricas del paso 4.

Uso:
    cd tools/noticias-inspector
    python baseline_capture.py            # requiere sandbox/vps-seed.json (seed-refresh previo)

El snapshot live es por red (~60-90s, IP residencial). Hermético: nunca escribe los DB reales
(prueba: fingerprint antes/después). Idempotente sobre el fixture (lo sobrescribe).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

import insp_config as cfg
import sandbox
import inspector_core as core

import ingest_noticias as ing
from noticias_ingest import scraper

BOLIVIA_TZ = timezone(timedelta(hours=-4))
FIXTURE_NAME = "baseline-2026-06-24"
FIXTURE_DIR = cfg.TOOL_DIR / "fixtures" / FIXTURE_NAME

# 15 llaves canónicas del embudo (orden = res["funnel"] de lane_bolivia).
FUNNEL_KEYS = [
    "entran", "cache_skip", "evaluados", "kill_keyword_excluida", "kill_falta_bolivia",
    "kill_umbral_modelo", "kill_sin_razon", "sobreviven", "unicos", "scheme_patrocinado",
    "candidatos", "sobre_umbral", "eventos", "dedupe", "insertadas",
]


# ── Núcleo reutilizable (lo usa también baseline_replay.py) ───────────────────
def _fresh_sandbox_conn():
    """Reconstruye el sandbox desde sandbox/vps-seed.json (seed prod-fiel) y abre la conn.
    build_sandbox borra+resiembra cada vez → estado de arranque idéntico y determinista."""
    info = sandbox.build_sandbox()
    if info.get("seed_source") != "vps":
        raise SystemExit(
            f"ABORT: seed_source={info.get('seed_source')} (esperado 'vps'). "
            "Corré el seed-refresh primero (sandbox/vps-seed.json ausente). "
            "Sin seed VPS las etapas 14/15 NO son prod-fieles.")
    return sqlite3.connect(str(info["db_path"])), info


def frozen_previos():
    """La ventana de dedup inter-día (títulos de los últimos 7d en el seed). DEBE congelarse:
    titulos_recientes() usa SQLite date('now') = reloj del SISTEMA, no el ahora_utc pinneado, así
    que sin congelarla el replay >7d después de la captura veria una ventana vacía y el embudo
    dejaría de ser byte-estable. La capturamos hoy (in-window) y la inyectamos en replay."""
    conn, _ = _fresh_sandbox_conn()
    try:
        return ing.titulos_recientes(conn)
    finally:
        conn.close()


def run_canonical(snap, funnel, ahora_utc, fecha_bo, top, previos=None):
    """Corre el lane_bolivia REAL sobre el snapshot congelado (correr_scraper parcheado),
    con LAST_FUNNEL inyectado (los escalares upstream no son derivables del snapshot).
    `previos` = ventana de dedup congelada (None → la computa desde el seed, solo en captura).
    Devuelve el res del lane (incluye res['funnel'] de 15 llaves) — prod-fiel, byte-estable."""
    conn, info = _fresh_sandbox_conn()
    try:
        args = SimpleNamespace(umbral=ing.UMBRAL_PUNTAJE, top=top, dry_run=False)
        with core.harness(info["cache_path"], snapshot=snap):
            scraper.LAST_FUNNEL.clear()
            scraper.LAST_FUNNEL.update(funnel)   # upstream real de la captura live
            prev = list(previos) if previos is not None else ing.titulos_recientes(conn)
            res = ing.lane_bolivia(conn, args, ahora_utc, fecha_bo, prev)
        return res
    finally:
        conn.close()


def run_mirror(snap, ahora_utc, fecha_bo, top, previos=None):
    """Corre el mirror del inspector (read-only, devuelve finales = set X + stages con kills).
    top=∞ expone dedup + set de criterio sin el cap del budget diario.
    `previos` = ventana de dedup congelada (None → la computa desde el seed, solo en captura)."""
    conn, info = _fresh_sandbox_conn()
    try:
        args = SimpleNamespace(umbral=ing.UMBRAL_PUNTAJE, top=top, top_latam=ing.LATAM_TOP_N,
                               dry_run=False)
        with core.harness(info["cache_path"], snapshot=snap):
            prev = list(previos) if previos is not None else ing.titulos_recientes(conn)
            return core.mirror_bolivia(snap, conn, args, ahora_utc, fecha_bo, prev)
    finally:
        conn.close()


# ── Métricas de diagnóstico (paso 4) ─────────────────────────────────────────
def _ancla_bo(titulo, descripcion, entidades):
    """Recomputa el geo-gate ancla (scraper.py:975-976) con las constantes/funciones VIVAS —
    clasificación, no reimplementación de criterio."""
    texto = (str(titulo) + " " + str(descripcion)).lower()
    return (any(t in texto for t in scraper.TERMINOS_BOLIVIA)
            or any(e in scraper.ENTIDADES_BOLIVIANAS for e in (entidades or [])))


def compute_metrics(snap, mirror_diag, mirror_parity, canonical_res):
    candidatos, descartados, portales_ok, portales_fail = snap
    funnel = canonical_res.get("funnel", {})

    # (2) volumen de muestra
    evaluados = funnel.get("evaluados", 0)

    # (6) histograma de razones de muerte por etapa
    kill_hist = {"keyword_excluida": 0, "falta_bolivia": 0, "umbral": 0, "sin_razon_o_vacio": 0}
    for d in descartados:
        r = d.get("descartado_por") or ""
        if r in ("keyword_excluida", "falta_bolivia", "umbral"):
            kill_hist[r] += 1
        else:
            kill_hist["sin_razon_o_vacio"] += 1
    stages_diag = mirror_diag.get("stages", {})

    def _killn(i):
        return len(stages_diag.get(i, {}).get("killed", []) or [])

    death_by_stage = {
        "etapa4_evaluar(keyword_excluida)": kill_hist["keyword_excluida"],
        "etapa4_evaluar(falta_bolivia)": kill_hist["falta_bolivia"],
        "etapa4_evaluar(umbral_modelo<0.33)": kill_hist["umbral"],
        "etapa4_evaluar(sin_razon/degradado)": kill_hist["sin_razon_o_vacio"],
        "etapa10_scheme_patrocinado": _killn(10),
        "etapa12_bajo_umbral_editorial(<6.7)": _killn(12),
        "etapa13_agrupado(Tambien_en)": _killn(13),
        "etapa14_budget(diag_inflado=irrelevante)": _killn(14),
        "etapa15_dedup_inter_dia": _killn(15),
    }

    finales_diag = mirror_diag.get("finales", []) or []

    # (3) share [otros]/General — sobre el set de criterio (diagnóstico) y sobre insertadas (prod)
    def _share_otros(notas):
        n = len(notas)
        otros_cat = sum(1 for x in notas if (x.get("category") == "otros"))
        general_tema = sum(1 for x in notas if (x.get("tema") in ("General", "", None)))
        return {"n": n,
                "category_otros": otros_cat, "category_otros_pct": (round(100 * otros_cat / n, 1) if n else None),
                "tema_General": general_tema, "tema_General_pct": (round(100 * general_tema / n, 1) if n else None)}

    share_criterio = _share_otros(finales_diag)

    # (4) opinión: es_opinion en candidatos + cuántas sobreviven >=6.7 pese al ×0.7
    op_cands = [c for c in candidatos if c.get("es_opinion")]
    op_sobre_umbral = [c for c in op_cands if (c.get("puntaje") or 0) >= ing.UMBRAL_PUNTAJE]
    # opinión que llegó a ser FINAL de criterio (set diagnóstico): join por url
    op_urls = {c.get("link") for c in op_cands}
    op_en_finales = [n for n in finales_diag if n.get("url") in op_urls]

    # (5) geo-gate: de las que pasaron el gate, cuántas por ancla vs rescatadas por tema≠General.
    # Gate-survivors = candidatos (pasaron todo) + descartados que murieron en 'umbral'
    # (pasaron el gate, cayeron luego por score). Recompute ancla/tema con funciones vivas.
    gate_survivors = []
    for c in candidatos:
        gate_survivors.append({"titulo": c.get("titulo"), "descripcion": c.get("descripcion"),
                               "entidades": c.get("entidades"), "tema": c.get("tema"),
                               "fuente": "candidato"})
    for d in descartados:
        if (d.get("descartado_por") or "") == "umbral":
            ent = scraper.detectar_entidades(d.get("titulo", ""), d.get("descripcion", ""))
            tema, _ = scraper._tema(d.get("titulo", ""), d.get("descripcion", ""))
            gate_survivors.append({"titulo": d.get("titulo"), "descripcion": d.get("descripcion"),
                                   "entidades": ent, "tema": tema, "fuente": "umbral_death"})
    gate_ancla = gate_rescate_tema = gate_anomalia = 0
    for g in gate_survivors:
        ancla = _ancla_bo(g["titulo"], g["descripcion"], g["entidades"])
        tema = g.get("tema") or "General"
        if ancla:
            gate_ancla += 1
        elif tema != "General":
            gate_rescate_tema += 1
        else:
            gate_anomalia += 1  # no debería pasar (no ancla + General no pasa el gate)

    # Reconciliación precisa: los gate-survivors VERDADEROS son evaluados − keyword_excluida −
    # falta_bolivia. Los clasificables desde el snapshot son candidatos (post intra-dedup) +
    # umbral-deaths; la diferencia son los perdedores del dedup intra-corrida (sobreviven −
    # unicos), que pasaron el gate pero se dropean PRE-seam y NO están en el snapshot.
    gate_true = (funnel.get("evaluados", 0) - kill_hist["keyword_excluida"]
                 - kill_hist["falta_bolivia"])
    pre_seam_dedup_losers = funnel.get("sobreviven", 0) - funnel.get("unicos", 0)

    # mismo desglose pero solo sobre el set de criterio final (lo que realmente importa al feed)
    fin_ancla = fin_rescate = fin_anom = 0
    cand_by_url = {c.get("link"): c for c in candidatos}
    for n in finales_diag:
        c = cand_by_url.get(n.get("url"))
        ent = (c or {}).get("entidades")
        ancla = _ancla_bo(n.get("title"), (c or {}).get("descripcion", ""), ent)
        tema = n.get("tema") or "General"
        if ancla:
            fin_ancla += 1
        elif tema != "General":
            fin_rescate += 1
        else:
            fin_anom += 1

    return {
        "funnel_bolivia_canonical_15": {k: funnel.get(k) for k in FUNNEL_KEYS},
        "volumen_muestra": {
            "evaluados": evaluados, "entran": funnel.get("entran"),
            "candidatos_post_scrape": len(candidatos), "descartados": len(descartados),
            "portales_ok": len(portales_ok), "portales_fail": len(portales_fail),
            "finales_set_criterio_diag": len(finales_diag),
        },
        "share_otros_General": {
            "set_criterio_diagnostico": share_criterio,
            "insertadas_prod_faithful": _share_otros(_canonical_finales_placeholder(canonical_res)),
            "nota": "insertadas prod-faithful puede ser 0 si el budget del día ya estaba lleno; "
                    "el set de criterio diagnóstico (top=∞) es la lectura relevante de dominancia.",
        },
        "opinion": {
            "candidatos_es_opinion": len(op_cands),
            "es_opinion_sobre_umbral_6.7": len(op_sobre_umbral),
            "es_opinion_en_finales_criterio": len(op_en_finales),
            "esperado": "~0 sobre 6.7 (la penalización ×0.7 debería tirarlas bajo el corte)",
            "ejemplos_sobre_umbral": [{"titulo": c.get("titulo"), "puntaje": c.get("puntaje"),
                                       "portal": c.get("portal")} for c in op_sobre_umbral[:8]],
        },
        "geo_gate": {
            "gate_survivors_true": gate_true,
            "gate_survivors_classifiable_from_snapshot": len(gate_survivors),
            "pre_seam_intra_dedup_losers_unclassifiable": pre_seam_dedup_losers,
            "por_ancla_bolivia": gate_ancla,
            "rescatadas_por_tema": gate_rescate_tema,
            "anomalia_sin_ancla_General": gate_anomalia,
            "rescate_tema_pct_de_classifiable": (round(100 * gate_rescate_tema / len(gate_survivors), 1)
                                                 if gate_survivors else None),
            "en_finales_criterio": {"por_ancla": fin_ancla, "rescatadas_por_tema": fin_rescate,
                                    "anomalia": fin_anom, "total": len(finales_diag)},
            "nota": "gate_survivors_true = evaluados − keyword_excluida − falta_bolivia; "
                    "los clasificables (candidatos + umbral-deaths) excluyen los "
                    "pre_seam_intra_dedup_losers (no están en el snapshot). El % de rescate por "
                    "tema es sobre el set clasificable.",
        },
        "histograma_muerte_por_etapa": death_by_stage,
    }


def _canonical_finales_placeholder(canonical_res):
    """El lane real inserta sin devolver la lista; devolvemos [] y reportamos solo el count
    (insertadas) — el share prod-faithful se reporta sobre el set diagnóstico, más informativo."""
    return []


# ── Congelado del fixture ─────────────────────────────────────────────────────
def freeze_fixture(snap, funnel, ahora_utc, fecha_bo, canonical_res, metrics, previos_frozen):
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    core.save_snapshot(snap, FIXTURE_DIR / "snapshot.json")
    # seed VPS congelado (para que budget/dedup del replay sean idénticos)
    seed_src = cfg.SANDBOX_DIR / "vps-seed.json"
    (FIXTURE_DIR / "vps-seed.json").write_text(seed_src.read_text(encoding="utf-8"),
                                               encoding="utf-8")
    # Ventana de dedup inter-día CONGELADA: independiza el embudo del reloj del sistema
    # (titulos_recientes usa SQLite date('now'), no ahora_utc) → replay byte-estable a
    # cualquier fecha futura, no solo dentro de los 7d de la captura.
    (FIXTURE_DIR / "previos.json").write_text(
        json.dumps(previos_frozen, ensure_ascii=False), encoding="utf-8")
    meta = {
        "fixture": FIXTURE_NAME,
        "captured_at_utc": ahora_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ahora_utc_pinned": ahora_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fecha_bo": fecha_bo,
        "umbral": ing.UMBRAL_PUNTAJE,
        "top_n_canonical": ing.TOP_N,
        "scraper_LAST_FUNNEL": funnel,   # escalares upstream NO derivables del snapshot
        "previos_n": len(previos_frozen),
        "scoring": canonical_res.get("scoring"),
        "nota_byte_estable": "El contrato byte-estable es res['funnel'] (15 llaves) reproducido "
                             "por baseline_replay.py desde snapshot.json + vps-seed.json + "
                             "ahora_utc_pinned + previos.json. INDEPENDIENTE de la fecha de "
                             "replay: la ventana de dedup inter-día va congelada en previos.json "
                             "(titulos_recientes usa date('now') del sistema, NO el ahora_utc "
                             "pinneado → sin congelarla el embudo solo sería estable <7d). La "
                             "galería/prod-preview NO entra al contrato (date-windowed por diseño).",
    }
    (FIXTURE_DIR / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    expected = {
        "funnel_bolivia_canonical_15": {k: canonical_res.get("funnel", {}).get(k) for k in FUNNEL_KEYS},
        "insertadas": canonical_res.get("insertadas"),
        "candidatos": canonical_res.get("candidatos"),
        "sobre_umbral": canonical_res.get("sobre_umbral"),
        "eventos": canonical_res.get("eventos"),
        "dedupe": canonical_res.get("dedupe"),
    }
    (FIXTURE_DIR / "expected_embudo.json").write_text(json.dumps(expected, ensure_ascii=False, indent=1),
                                                      encoding="utf-8")
    (FIXTURE_DIR / "metrics_baseline.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=1),
                                                       encoding="utf-8")
    return FIXTURE_DIR


def main():
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ahora_utc = datetime.now(timezone.utc)
    fecha_bo = ahora_utc.astimezone(BOLIVIA_TZ).strftime("%Y-%m-%d")
    print(f"[baseline] ahora_utc(pinned)={ahora_utc:%Y-%m-%dT%H:%M:%SZ} fecha_bo={fecha_bo}")

    # ── Captura live (red) — hermético, cache → sandbox ──────────────────────
    fp_before = sandbox.real_db_fingerprints(full_hash=True)
    info0 = sandbox.build_sandbox()
    if info0.get("seed_source") != "vps":
        raise SystemExit("ABORT: seed VPS ausente — corré el seed-refresh antes.")
    print(f"[baseline] sandbox seed: source={info0['seed_source']} max_date={info0['seed_max_date']} "
          f"noticias={info0['seeded']['noticias']}")
    print("[baseline] capturando snapshot LIVE (red, ~60-90s)...")
    with core.harness(info0["cache_path"]):  # sin snapshot → correr_scraper real
        snap = scraper.correr_scraper(cache_db_path=Path(info0["cache_path"]))
        funnel_upstream = dict(scraper.LAST_FUNNEL)  # entran/cache_skip/evaluados/sobreviven/unicos
    cands, descs, ok, fail = snap
    print(f"[baseline] snapshot: candidatos={len(cands)} descartados={len(descs)} "
          f"portales_ok={len(ok)} fail={len(fail)} | upstream={funnel_upstream}")

    # Ventana de dedup inter-día congelada (in-window hoy = la real de la captura).
    previos_frozen = frozen_previos()
    print(f"[baseline] previos congelados (dedup window): {len(previos_frozen)} títulos")

    # ── Canonical (prod-fiel, top=14) → res['funnel'] de 15 llaves ───────────
    canonical = run_canonical(snap, funnel_upstream, ahora_utc, fecha_bo, top=ing.TOP_N,
                              previos=previos_frozen)
    print(f"[baseline] CANONICAL funnel: {json.dumps(canonical.get('funnel'), ensure_ascii=False)}")

    # ── Diagnóstico (top=∞) + parity (top=14) vía mirror ─────────────────────
    mirror_diag = run_mirror(snap, ahora_utc, fecha_bo, top=10**9, previos=previos_frozen)
    mirror_parity = run_mirror(snap, ahora_utc, fecha_bo, top=ing.TOP_N, previos=previos_frozen)

    metrics = compute_metrics(snap, mirror_diag, mirror_parity, canonical)

    fp_after = sandbox.real_db_fingerprints(full_hash=True)
    hermetic_ok = (fp_before == fp_after)
    metrics["_hermetic_ok"] = hermetic_ok
    print(f"[baseline] hermetic_ok={hermetic_ok}")

    fdir = freeze_fixture(snap, funnel_upstream, ahora_utc, fecha_bo, canonical, metrics,
                          previos_frozen)
    print(f"[baseline] fixture congelado en {fdir}")
    print("\n==== METRICS ====")
    print(json.dumps(metrics, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
