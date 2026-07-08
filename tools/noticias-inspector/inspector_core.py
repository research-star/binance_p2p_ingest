"""Instrumented pipeline loop — the parity core (FASE A).

REGLA DURA: this module imports the REAL criterion functions (evaluar already ran inside
correr_scraper; build_nota / agrupar_eventos / es_repetida / insertar_notas / gallery_slug
are imported and called). The inspector OWNS only the *sequencing loop* (mirroring
lane_bolivia stages 9..18) so it can capture survivors + death-reason between stages. The
parity test (parity_test.py) asserts this mirror's set X == the real lane_bolivia's inserts.

Replay seam = scraper.correr_scraper's return tuple (the snapshot). Capture once (live,
network) -> replay offline by monkeypatching correr_scraper. Exactly the proven pattern in
scripts/test_noticias_budget_cache.py.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import insp_config as cfg
import sandbox
import pipeline_map

import ingest_noticias as ing
from noticias_ingest import scraper, transform
from noticias_ingest import resumen_ia
import dashboard

BOLIVIA_TZ = timezone(timedelta(hours=-4))


# ── Harness: hermetic monkeypatches (saved + restored) ───────────────────────
@contextmanager
def harness(sandbox_cache_path, snapshot=None, model_available=True):
    """Patch the live modules so a run is hermetic + deterministic, then restore.
      - scraper.CACHE_DB_PATH -> sandbox cache (marcar_urls_vistas reads this global)
      - ingest.escribir_csv_debug -> no-op (it writes a CSV into the REAL data dir)
      - resumen_ia.aplicar -> no-op (no API cost, deterministic summaries)
      - if snapshot: correr_scraper -> returns it; get_modelo -> stub (replay, no network)
    """
    saved = {}

    def save(mod, name):
        saved[(mod, name)] = getattr(mod, name, _MISSING)

    def restore():
        for (mod, name), val in saved.items():
            if val is _MISSING:
                if hasattr(mod, name):
                    delattr(mod, name)
            else:
                setattr(mod, name, val)

    for mod, name in [(scraper, "CACHE_DB_PATH"), (resumen_ia, "aplicar")]:
        save(mod, name)
    has_csv = hasattr(ing, "escribir_csv_debug")
    if has_csv:
        save(ing, "escribir_csv_debug")
    if snapshot is not None:
        save(scraper, "correr_scraper")
        save(scraper, "get_modelo")
    try:
        scraper.CACHE_DB_PATH = Path(sandbox_cache_path)
        # *a,**k: el stub es un no-op deliberado (sin API, determinista); NO debe
        # depender de la firma real. El call vivo pasa (finales, autorizado=, conn=)
        # desde el candado de API + captura de usage; con la firma vieja `lambda finales`
        # la lane real crashea con TypeError y tumba parity_test/baseline_replay. Igual
        # que los stubs hermanos (escribir_csv_debug / correr_scraper) de este bloque.
        resumen_ia.aplicar = lambda *a, **k: 0
        if has_csv:
            ing.escribir_csv_debug = lambda *a, **k: None
        if snapshot is not None:
            snap = tuple(snapshot)
            scraper.correr_scraper = lambda *a, **k: snap
            scraper.get_modelo = lambda: SimpleNamespace(disponible=model_available, motivo_rechazo="")
        yield
    finally:
        restore()


_MISSING = object()


# ── Snapshot capture / persistence (fetch-once-replay) ───────────────────────
def capture_live_snapshot(sandbox_cache_path) -> tuple:
    """REAL correr_scraper (network) with cache pointed at the sandbox copy. Returns the
    full (candidatos, descartados, portales_ok, portales_fail) tuple."""
    with harness(sandbox_cache_path):  # no snapshot -> real correr_scraper
        # MUST be a Path (CacheURLs.__init__ does db_path.parent.mkdir) — a str crashes.
        return scraper.correr_scraper(cache_db_path=Path(sandbox_cache_path))


def save_snapshot(snap, path: Path):
    cands, descs, ok, fail = snap
    path.write_text(json.dumps(
        {"candidatos": cands, "descartados": descs, "portales_ok": ok, "portales_fail": fail},
        ensure_ascii=False, default=str), encoding="utf-8")


def load_snapshot(path: Path) -> tuple:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return (d["candidatos"], d.get("descartados", []), d.get("portales_ok", []), d.get("portales_fail", []))


# ── Funnel item briefs ───────────────────────────────────────────────────────
def _cand_brief(c, reason):
    return {"title": c.get("titulo", ""), "source": c.get("portal", ""),
            "puntaje": c.get("puntaje"), "tema": c.get("tema"), "reason": reason,
            "url": c.get("link", "")}


def _nota_brief(n, reason):
    return {"id": n.get("id"), "title": n.get("title", ""), "source": n.get("source", ""),
            "puntaje": n.get("puntaje"), "tema": n.get("tema"), "category": n.get("category"),
            "reason": reason, "url": n.get("url", "")}


def _descartados_breakdown(descartados):
    out = []
    for d in descartados:
        out.append({
            "title": d.get("titulo") or d.get("title") or "",
            "source": d.get("portal") or d.get("source") or "",
            "reason": d.get("descartado_por") or d.get("motivo") or "evaluar",
            "puntaje": d.get("puntaje"),
        })
    return out


# ── Bolivia mirror (stages 9..18 of lane_bolivia, instrumented) ──────────────
def mirror_bolivia(snapshot, conn, args, ahora_utc, fecha_bo, previos):
    """Faithful mirror of ingest_noticias.lane_bolivia stages 9..18, capturing per-stage
    survivors/kills. Calls the REAL functions. Does NOT insert (read-only): `finales` IS
    set X; the parity test compares it to the real lane_bolivia's inserts."""
    cands, descartados, portales_ok, portales_fail = snapshot
    stages = {s["i"]: {"out": None, "killed": []} for s in pipeline_map.BOLIVIA_STAGES}

    # Stages 1..8 (scraper, upstream of the seam): only stage 4 deaths are visible (descartados).
    evaluated = len(cands) + len(descartados)
    stages[4]["killed"] = _descartados_breakdown(descartados)
    stages[4]["out"] = evaluated - len(descartados)
    stages[8]["out"] = len(cands)  # survivors entering the lane (post dedup/decode/scrape)

    # Stage 9: scrape-total-fail guard
    if not portales_ok:
        stages[9]["out"] = 0
        return {"error": "scrape_total_fail", "stages": stages, "finales": [],
                "portales_ok": portales_ok, "portales_fail": portales_fail}
    stages[9]["out"] = len(cands)

    # Stage 10: scheme + sponsored filter
    kept, killed = [], []
    for c in cands:
        ok_scheme = urlparse(c["link"]).scheme in ("http", "https")
        sponsored = scraper.es_url_patrocinada(c["link"])
        if ok_scheme and not sponsored:
            kept.append(c)
        else:
            killed.append(_cand_brief(c, "patrocinado" if sponsored else "scheme_no_http"))
    stages[10]["out"] = len(kept)
    stages[10]["killed"] = killed

    # Stage 11: build_nota (no kills)
    notas = [transform.build_nota(c, ahora_utc) for c in kept]
    stages[11]["out"] = len(notas)

    # Stage 12: editorial threshold (>= UMBRAL_PUNTAJE via args.umbral) + boost institucional M2
    seleccion = [n for n in notas if n["puntaje"] >= args.umbral]
    stages[12]["killed"] = [_nota_brief(n, "bajo_umbral") for n in notas if n["puntaje"] < args.umbral]
    stages[12]["out"] = len(seleccion)
    # M2: mismo helper que la lane real (reordena, no mata; DESPUÉS del corte → no rescata).
    ing._boost_institucional(seleccion)
    seleccion.sort(key=lambda n: -n["puntaje"])

    # Stage 13: agrupar_eventos (collapses same-event into representative + tambien_en)
    grouped = ing.agrupar_eventos(seleccion)
    kept_ids = {n["id"] for n in grouped}
    stages[13]["killed"] = [_nota_brief(n, "agrupado(También en)") for n in seleccion if n["id"] not in kept_ids]
    stages[13]["out"] = len(grouped)

    # Stage 14: rolling daily budget
    ya_hoy = conn.execute(
        f"SELECT COUNT(*) FROM noticias WHERE date = ? AND {ing.CARRIL_SQL} != 'latam'",
        (fecha_bo,)).fetchone()[0]
    budget = max(0, args.top - ya_hoy)

    # Stage 15: budget break + inter-day dedupe (faithful to lane_bolivia's loop)
    finales, dedupe_losers, budget_losers = [], [], []
    for idx, n in enumerate(grouped):
        if len(finales) >= budget:
            budget_losers = grouped[idx:]
            break
        if ing.es_repetida(n["title"], previos):
            dedupe_losers.append(n)
            continue
        finales.append(n)
        previos.append(n["title"])  # mutate shared previos (cross-lane coupling, like prod)
    stages[14]["out"] = len(grouped) - len(budget_losers)
    stages[14]["killed"] = [_nota_brief(n, "budget") for n in budget_losers]
    stages[15]["out"] = len(finales)
    stages[15]["killed"] = [_nota_brief(n, "dedup_inter_dia") for n in dedupe_losers]

    # Stages 16..18: resumen_ia (stub no-op), insert (set X), marcar — no further kills
    for i in (16, 17, 18):
        stages[i]["out"] = len(finales)

    return {"stages": stages, "finales": finales, "budget": budget, "ya_hoy": ya_hoy,
            "portales_ok": portales_ok, "portales_fail": portales_fail,
            "evaluated": evaluated, "entered_lane": len(cands)}


# ── Latam mirror (live: real fetch; 6 stages, no scoring) ────────────────────
def mirror_latam(conn, args, ahora_utc, fecha_bo, previos, entries=None):
    """Mirror of lane_latam. If `entries` is None, fetches live (network). Shares `previos`
    with Bolivia (cross-lane dedupe coupling)."""
    from noticias_ingest import latam
    stages = {s["i"]: {"out": None, "killed": []} for s in pipeline_map.LATAM_STAGES}
    if entries is None:
        entries = latam.fetch_entries_latam()
    stages[1]["out"] = len(entries)
    if not entries:
        return {"error": "feed_sin_items", "stages": stages, "finales": []}

    recientes = latam.entries_ultimas_24h(entries, ahora_utc)
    stages[2]["out"] = len(recientes)

    notas = []
    killed3 = []
    for pub_utc, e in recientes:
        n = transform.build_nota_latam(pub_utc, e, ahora_utc)
        if urlparse(n["url"]).scheme in ("http", "https"):
            notas.append(n)
        else:
            killed3.append(_nota_brief(n, "scheme_no_http"))
    stages[3]["out"] = len(notas)
    stages[3]["killed"] = killed3

    ya_hoy = conn.execute(
        f"SELECT COUNT(*) FROM noticias WHERE {ing.CARRIL_SQL} = 'latam' "
        "AND date(created_at_utc, '-4 hours') = ?", (fecha_bo,)).fetchone()[0]
    budget = max(0, args.top_latam - ya_hoy)

    finales, dedupe_losers, budget_losers = [], [], []
    for idx, n in enumerate(notas):
        if len(finales) >= budget:
            budget_losers = notas[idx:]
            break
        if ing.es_repetida(n["title"], previos):
            dedupe_losers.append(n)
            continue
        finales.append(n)
        previos.append(n["title"])
    stages[4]["out"] = len(notas) - len(budget_losers)
    stages[4]["killed"] = [_nota_brief(n, "budget") for n in budget_losers]
    stages[5]["out"] = len(finales)
    stages[5]["killed"] = [_nota_brief(n, "dedup_inter_dia") for n in dedupe_losers]
    stages[6]["out"] = len(finales)
    return {"stages": stages, "finales": finales, "budget": budget, "ya_hoy": ya_hoy}


# ── Prod-preview: image cascade (npImg) with PROD parity + section marker ─────
def _gallery_slug(n):
    """Call the REAL gallery slug logic, live signatures:
        gallery_slug_v2(title, summary, detail, tema, category, carril)
        gallery_slug(tema, category, carril)
    (If these signatures change in dashboard.py, that's a Sync-MANUAL point.)"""
    carril = n.get("carril") or "bolivia"
    f2 = getattr(dashboard, "gallery_slug_v2", None)
    if f2:
        try:
            s = f2(n.get("title", ""), n.get("summary", ""), n.get("detail", ""),
                   n.get("tema", ""), n.get("category", ""), carril)
            if isinstance(s, str) and s:
                return s
        except Exception:
            pass
    f1 = getattr(dashboard, "gallery_slug", None)
    if f1:
        try:
            s = f1(n.get("tema", ""), n.get("category", ""), carril)
            if isinstance(s, str) and s:
                return s
        except Exception:
            pass
    return ""


def prod_image(n):
    """Replica del cascade npImg del frontend: og:image -> galería webp -> placeholder.
    PARIDAD PROD: para fuentes en PROD_IMG_UNAVAILABLE se ANULA el og:image (prod no puede
    servirlo), cayendo a la galería. La imagen de galería es la ROTADA (galleryImg, 'slug-k'),
    asignada por dashboard.assign_gallery_images en prod_preview (cooldown v2)."""
    src = (n.get("source") or "").lower()
    og = n.get("image_url") or ""
    prod_nulled = False
    if src in cfg.PROD_IMG_UNAVAILABLE:
        og, prod_nulled = "", True
    if og and og.startswith(("http://", "https://")):
        return {"kind": "og:image", "url": og}
    img = n.get("galleryImg")            # 'slug-k' (rotada); None -> placeholder
    if img:
        webp = f"gal-{img}.webp"
        if (cfg.GALLERY_DIR / webp).exists():
            return {"kind": "galeria", "slug": n.get("gallerySlug"), "img": img,
                    "file": webp, "prod_nulled_og": prod_nulled}
    return {"kind": "placeholder", "prod_nulled_og": prod_nulled}


def _assign_gallery(notas):
    """Asigna gallerySlug + galleryImg (rotada, cooldown) a cada nota llamando a las
    funciones REALES de dashboard.py (regla dura: no se reimplementa el criterio)."""
    for n in notas:
        n["gallerySlug"] = _gallery_slug(n)
    af = getattr(dashboard, "assign_gallery_images", None)
    if af:
        try:
            af(notas)
            return
        except Exception:
            pass
    for n in notas:                      # fallback defensivo: sin rotación, 1 imagen
        s = n.get("gallerySlug")
        n["galleryImg"] = f"{s}-1" if s else None


def _section_marker(idx, carril):
    if carril == "latam":
        return "Latam / Internacional (banda)"
    if idx == 0:
        return "Primera plana (hero)"
    if idx <= 5:
        return "Ranking «Lo más relevante» + Feed"
    return "Feed «Las noticias de hoy»"


def prod_preview(bolivia_finales, latam_finales):
    # Etiquetar carril (para que _gallery_slug rute latam -> 'internacional') y asignar
    # la imagen rotada con cooldown sobre el set X combinado, usando la función real.
    for n in bolivia_finales:
        n["carril"] = n.get("carril") or "bolivia"
    for n in latam_finales:
        n["carril"] = "latam"
    _assign_gallery(list(bolivia_finales) + list(latam_finales))
    out = []
    for idx, n in enumerate(bolivia_finales):
        out.append({"carril": "bolivia", "section": _section_marker(idx, "bolivia"),
                    "title": n.get("title"), "source": n.get("source"),
                    "category": n.get("category"), "tema": n.get("tema"),
                    "puntaje": n.get("puntaje"), "image": prod_image(n)})
    for idx, n in enumerate(latam_finales):
        out.append({"carril": "latam", "section": _section_marker(idx, "latam"),
                    "title": n.get("title"), "source": n.get("source"),
                    "category": n.get("category"), "tema": n.get("tema"),
                    "image": prod_image(n)})
    return out


# ── Orchestrator: one full run ───────────────────────────────────────────────
def run(mode="live", snapshot_path=None, ahora_utc=None):
    """Build sandbox -> snapshot (live fetch or replay) -> mirror both lanes -> prod-preview.
    Returns the run dict (also persisted to sandbox/last-run.json)."""
    ahora_utc = ahora_utc or datetime.now(timezone.utc)
    fecha_bo = ahora_utc.astimezone(BOLIVIA_TZ).strftime("%Y-%m-%d")
    args = SimpleNamespace(umbral=ing.UMBRAL_PUNTAJE, top=ing.TOP_N,
                           top_latam=ing.LATAM_TOP_N, dry_run=False)

    info = sandbox.build_sandbox()
    fp_before = sandbox.real_db_fingerprints(full_hash=False)

    # Snapshot
    if mode == "replay":
        snap_file = Path(snapshot_path) if snapshot_path else (cfg.SANDBOX_DIR / "snapshot.json")
        if not snap_file.exists():
            raise FileNotFoundError(f"No snapshot to replay at {snap_file} — run a live capture first.")
        snap = load_snapshot(snap_file)
        scoring = "replay"
    else:  # live
        snap = capture_live_snapshot(info["cache_path"])
        save_snapshot(snap, cfg.SANDBOX_DIR / "snapshot.json")
        try:
            scoring = "tfidf" if scraper.get_modelo().disponible else "keywords"
        except Exception:
            scoring = "desconocido"

    conn = sqlite3.connect(str(info["db_path"]))
    try:
        with harness(info["cache_path"], snapshot=snap):
            previos = ing.titulos_recientes(conn)
            bol = mirror_bolivia(snap, conn, args, ahora_utc, fecha_bo, previos)
            if mode == "live":
                try:
                    lat = mirror_latam(conn, args, ahora_utc, fecha_bo, previos, entries=None)
                except Exception as e:  # noqa: BLE001
                    lat = {"error": f"latam_skipped: {type(e).__name__}: {e}", "stages": {}, "finales": []}
            else:
                # Latam parity is live-only (its replay seam is latam.fetch_entries_latam,
                # not captured here). Bolivia is the parity target (acceptance #1).
                lat = {"error": "latam corre solo en modo live (sin snapshot de entries)",
                       "stages": {}, "finales": []}
    finally:
        conn.close()

    fp_after = sandbox.real_db_fingerprints(full_hash=False)
    hermetic_ok = fp_before == fp_after

    preview = prod_preview(bol.get("finales", []), lat.get("finales", []))

    run_dict = {
        "ts": ahora_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fecha_bo": fecha_bo,
        "mode": mode,
        "scoring": scoring,
        "deps": __import__("deps").check().as_dict(),
        "bolivia": {"stages": [_stage_row(s, bol) for s in pipeline_map.BOLIVIA_STAGES],
                    "final": [_final_row(n) for n in bol.get("finales", [])],
                    "budget": bol.get("budget"), "ya_hoy": bol.get("ya_hoy"),
                    "evaluated": bol.get("evaluated"), "error": bol.get("error"),
                    "portales_ok": bol.get("portales_ok"), "portales_fail": bol.get("portales_fail")},
        "latam": {"stages": [_stage_row(s, lat) for s in pipeline_map.LATAM_STAGES],
                  "final": [_final_row(n) for n in lat.get("finales", [])],
                  "error": lat.get("error")},
        "prod_preview": preview,
        "hermetic": {"ok": hermetic_ok, "before": fp_before, "after": fp_after},
        "sandbox": {"db": str(info["db_path"]), "cache": info["cache"], "seeded": info["seeded"],
                    "seed_source": info.get("seed_source"), "seed_max_date": info.get("seed_max_date")},
    }
    (cfg.SANDBOX_DIR / "last-run.json").write_text(
        json.dumps(run_dict, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return run_dict


def _stage_row(stage_meta, lane_result):
    rt = (lane_result.get("stages") or {}).get(stage_meta["i"], {})
    return {**stage_meta, "out": rt.get("out"), "killed": rt.get("killed", []),
            "killed_n": len(rt.get("killed", []))}


def _final_row(n):
    return {"id": n.get("id"), "title": n.get("title"), "source": n.get("source"),
            "category": n.get("category"), "tema": n.get("tema"), "puntaje": n.get("puntaje"),
            "impact": n.get("impact"), "tambien_en": n.get("tambien_en")}
