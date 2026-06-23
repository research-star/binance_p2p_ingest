"""Canonical ordered map of the REAL noticias pipeline (the inspector's funnel skeleton).

This is the ONE place that hardcodes the *structure* (which stages exist and in what
order) — exactly the Sync-MANUAL surface the brief calls out (item 1: add/quitar/reorder
a stage -> update here). Everything else (thresholds, keyword lists, slug rules) is
imported LIVE below so it auto-syncs; this module never copies a threshold's value, it
imports the constant and displays it.

Stage source of truth: the recon synthesis over HEAD (post-ef1b76d). If the real
correr_scraper / lane_bolivia / lane_latam sequence changes, update STAGES here and the
mirror in inspector_core.py.
"""
from __future__ import annotations

import insp_config as cfg  # noqa: F401  (ensures repo root on sys.path)

# kind: "scraper" = inside correr_scraper, upstream of the replay seam (per-item kills not
#       separable on replay; counts come from the snapshot's candidatos/descartados).
#       "lane" = inside lane_bolivia/lane_latam, downstream of the seam — fully instrumented.
# seam=True marks the snapshot boundary (correr_scraper return).
BOLIVIA_STAGES = [
    {"i": 1, "name": "init modelo + cache", "fn": "scraper.get_modelo / CacheURLs.__init__", "kind": "scraper", "ref": "scraper.py:189,199"},
    {"i": 2, "name": "fetch RSS por portal (28h)", "fn": "scraper.procesar_portal / fetch_rss / es_reciente", "kind": "scraper", "ref": "scraper.py:1277,1164,1146"},
    {"i": 3, "name": "cache ya_vista skip (TTL 7d)", "fn": "scraper.CacheURLs.ya_vista", "kind": "scraper", "ref": "scraper.py:220"},
    {"i": 4, "name": "score + criterio (evaluar)", "fn": "scraper.evaluar (KEYWORDS_EXCLUIR -> geo-gate -> TF-IDF/keywords -> tema)", "kind": "scraper", "ref": "scraper.py:881", "kills_reasons": ["keyword_excluida", "falta_bolivia", "umbral"]},
    {"i": 5, "name": "dedup intra-corrida", "fn": "scraper.deduplicar (similitud >= UMBRAL_DEDUP)", "kind": "scraper", "ref": "scraper.py:1246"},
    {"i": 6, "name": "decode URL Google News", "fn": "googlenewsdecoder.new_decoderv1", "kind": "scraper", "ref": "scraper.py:1400"},
    {"i": 7, "name": "scrape cuerpo + og:image", "fn": "scraper.scrape_cuerpo / _og_image", "kind": "scraper", "ref": "scraper.py:1082,1061", "note": "og:image consumido SOLO por prod-preview; no mata"},
    {"i": 8, "name": "correr_scraper return (SEAM)", "fn": "scraper.correr_scraper", "kind": "scraper", "ref": "scraper.py:1320", "seam": True},
    {"i": 9, "name": "guard scrape-total-fail", "fn": "lane_bolivia (portales_ok)", "kind": "lane", "ref": "ingest_noticias.py:304"},
    {"i": 10, "name": "filtro scheme + patrocinado", "fn": "urlparse scheme + scraper.es_url_patrocinada", "kind": "lane", "ref": "ingest_noticias.py:314"},
    {"i": 11, "name": "build_nota (candidato -> fila)", "fn": "transform.build_nota", "kind": "lane", "ref": "transform.py:173"},
    {"i": 12, "name": "umbral editorial (>= 6.7)", "fn": "puntaje >= UMBRAL_PUNTAJE", "kind": "lane", "ref": "ingest_noticias.py:322"},
    {"i": 13, "name": "agrupar por evento", "fn": "ingest.agrupar_eventos (+ También en)", "kind": "lane", "ref": "ingest_noticias.py:329"},
    {"i": 14, "name": "presupuesto diario (top-N)", "fn": "budget = TOP_N - ya_hoy", "kind": "lane", "ref": "ingest_noticias.py:336"},
    {"i": 15, "name": "dedup inter-día (7d)", "fn": "ingest.es_repetida (>= UMBRAL_DEDUP_DB)", "kind": "lane", "ref": "ingest_noticias.py:348"},
    {"i": 16, "name": "resumen IA (opt-in, stub)", "fn": "resumen_ia.aplicar", "kind": "lane", "ref": "ingest_noticias.py:360", "note": "stub no-op en el inspector (sin API, determinista)"},
    {"i": 17, "name": "insert idempotente", "fn": "ingest.insertar_notas (INSERT OR IGNORE)", "kind": "lane", "ref": "ingest_noticias.py:245"},
    {"i": 18, "name": "marcar URLs vistas", "fn": "scraper.marcar_urls_vistas", "kind": "lane", "ref": "scraper.py:239"},
]

LATAM_STAGES = [
    {"i": 1, "name": "fetch RSS latam", "fn": "latam.fetch_entries_latam", "kind": "scraper", "ref": "latam.py:65", "seam": True},
    {"i": 2, "name": "ventana 24h + orden desc", "fn": "latam.entries_ultimas_24h", "kind": "lane", "ref": "latam.py:91"},
    {"i": 3, "name": "build_nota_latam + scheme", "fn": "transform.build_nota_latam", "kind": "lane", "ref": "transform.py:225"},
    {"i": 4, "name": "presupuesto diario (top-N)", "fn": "budget = LATAM_TOP_N - ya_hoy", "kind": "lane", "ref": "ingest_noticias.py:415"},
    {"i": 5, "name": "dedup inter-día (previos compartidos)", "fn": "ingest.es_repetida", "kind": "lane", "ref": "ingest_noticias.py:427"},
    {"i": 6, "name": "insert idempotente", "fn": "ingest.insertar_notas", "kind": "lane", "ref": "ingest_noticias.py:441"},
]

# Stages where, on a replay snapshot (post-seam), the inspector cannot enumerate per-item
# deaths because they happened inside correr_scraper before the snapshot was taken.
SCRAPER_OPAQUE_ON_REPLAY = {1, 2, 3, 5, 6, 7}  # stage 4 deaths ARE visible via `descartados`


def live_constants() -> dict:
    """Import the REAL constants and report their live values (auto-sync display). If a
    constant moves/disappears, this surfaces it instead of lying with a stale copy."""
    out = {"importable": [], "manual_sync": [], "errors": []}

    def grab(label, getter, sync=False):
        try:
            val = getter()
            rec = {"name": label, "value": _short(val)}
            (out["manual_sync"] if sync else out["importable"]).append(rec)
        except Exception as e:  # noqa: BLE001
            out["errors"].append({"name": label, "error": f"{type(e).__name__}: {e}"})

    import ingest_noticias as ing
    from noticias_ingest import scraper, transform
    import dashboard

    grab("UMBRAL_PUNTAJE (corte editorial)", lambda: ing.UMBRAL_PUNTAJE)
    grab("TOP_N bolivia", lambda: ing.TOP_N)
    grab("LATAM_TOP_N", lambda: ing.LATAM_TOP_N)
    grab("DEDUPE_DIAS", lambda: ing.DEDUPE_DIAS)
    grab("UMBRAL_DEDUP_DB", lambda: ing.UMBRAL_DEDUP_DB)
    grab("UMBRAL_EVENTO_TIT", lambda: ing.UMBRAL_EVENTO_TIT)
    grab("UMBRAL_EVENTO_ENT", lambda: ing.UMBRAL_EVENTO_ENT)
    grab("UMBRAL_MODELO (scraper)", lambda: scraper.UMBRAL_MODELO)
    grab("UMBRAL_DEDUP (scraper)", lambda: scraper.UMBRAL_DEDUP)
    grab("HORAS_ATRAS", lambda: scraper.HORAS_ATRAS)
    grab("CACHE_DIAS", lambda: scraper.CACHE_DIAS)
    grab("KEYWORDS_EXCLUIR (n)", lambda: len(scraper.KEYWORDS_EXCLUIR))
    grab("SECCIONES_PATROCINADAS (n)", lambda: len(scraper.SECCIONES_PATROCINADAS))
    grab("FUENTES (n portales)", lambda: len(scraper.FUENTES))
    grab("TEMA_CATEGORIA (n temas)", lambda: len(transform.TEMA_CATEGORIA))
    grab("SUMMARY_MAX", lambda: transform.SUMMARY_MAX)
    grab("GALLERY_KEYWORD_PRIORITY (n reglas)", lambda: len(dashboard.GALLERY_KEYWORD_PRIORITY))
    grab("VALID_GALLERY_SLUGS (n)", lambda: len(dashboard.VALID_GALLERY_SLUGS))
    grab("TIENE_GNEWS_DECODER / RAPIDFUZZ / TRAFILATURA", lambda: (scraper.TIENE_GNEWS_DECODER, scraper.TIENE_RAPIDFUZZ, scraper.TIENE_TRAFILATURA))

    # Manual-sync: inline literals (no importable constant) — call the function, never re-derive.
    grab("impact bands (8.0/7.0 inline)", lambda: "impact_de_puntaje() — bandas inline en transform.py:~162; el inspector LLAMA la función, no las re-deriva", sync=True)
    grab("PROD_IMG_UNAVAILABLE", lambda: sorted(cfg.PROD_IMG_UNAVAILABLE), sync=True)
    return out


def _short(v) -> str:
    s = repr(v)
    return s if len(s) <= 80 else s[:77] + "..."
