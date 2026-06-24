"""Baseline replay/verify — criterio-iteración-2 / FASE 1.

Reproduce OFFLINE (sin red) el baseline congelado por baseline_capture.py y verifica que el
embudo canónico (res['funnel'] de 15 llaves) sea BYTE-ESTABLE. Usa el seam de replay existente
(scraper.correr_scraper parcheado al snapshot congelado) → el lane_bolivia REAL recorre el
mismo input bajo el criterio de main.

Esto es lo que iteración-3 usará: replayear ESTE MISMO input bajo el criterio nuevo y diffear
el embudo = delta controlado mismo-input (no comparación entre días distintos).

Uso:
    cd tools/noticias-inspector
    python baseline_replay.py                 # verifica byte-estabilidad (exit 0 si OK)
    python baseline_replay.py --update-metrics # además regenera metrics_baseline.json

Determinismo: build_sandbox resiembra desde el vps-seed.json CONGELADO del fixture (no el del
sandbox, que puede haber cambiado) + ahora_utc fijado en meta.json + LAST_FUNNEL inyectado.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta

import insp_config as cfg
import inspector_core as core

import baseline_capture as bc

BOLIVIA_TZ = timezone(timedelta(hours=-4))


def _load_fixture():
    fdir = bc.FIXTURE_DIR
    meta = json.loads((fdir / "meta.json").read_text(encoding="utf-8"))
    snap = core.load_snapshot(fdir / "snapshot.json")
    expected = json.loads((fdir / "expected_embudo.json").read_text(encoding="utf-8"))
    # Restaurar el seed VPS congelado al sandbox para que build_sandbox siembre idéntico.
    seed_txt = (fdir / "vps-seed.json").read_text(encoding="utf-8")
    cfg.SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    (cfg.SANDBOX_DIR / "vps-seed.json").write_text(seed_txt, encoding="utf-8")
    # Ventana de dedup congelada — inyectada para no depender de date('now') del sistema.
    previos = json.loads((fdir / "previos.json").read_text(encoding="utf-8"))
    ahora_utc = datetime.strptime(meta["ahora_utc_pinned"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return fdir, meta, snap, expected, ahora_utc, previos


def replay_once():
    fdir, meta, snap, expected, ahora_utc, previos = _load_fixture()
    fecha_bo = ahora_utc.astimezone(BOLIVIA_TZ).strftime("%Y-%m-%d")
    funnel_upstream = meta["scraper_LAST_FUNNEL"]
    canonical = bc.run_canonical(snap, funnel_upstream, ahora_utc, fecha_bo,
                                 top=meta["top_n_canonical"], previos=previos)
    got = {k: canonical.get("funnel", {}).get(k) for k in bc.FUNNEL_KEYS}
    exp = expected["funnel_bolivia_canonical_15"]
    return got, exp, snap, ahora_utc, fecha_bo, canonical, previos


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    got, exp, snap, ahora_utc, fecha_bo, canonical, previos = replay_once()
    ok = (got == exp)
    print("== REPLAY embudo canónico (15 llaves) ==")
    print("reproducido:", json.dumps(got, ensure_ascii=False))
    print("esperado   :", json.dumps(exp, ensure_ascii=False))
    if not ok:
        diff = {k: {"got": got.get(k), "exp": exp.get(k)} for k in bc.FUNNEL_KEYS if got.get(k) != exp.get(k)}
        print("DIFF:", json.dumps(diff, ensure_ascii=False))
        print("RESULT: ❌ NO byte-estable")
        return 1
    print("RESULT: ✅ byte-estable (embudo reproducido == congelado)")

    if "--update-metrics" in sys.argv:
        mirror_diag = bc.run_mirror(snap, ahora_utc, fecha_bo, top=10**9, previos=previos)
        mirror_parity = bc.run_mirror(snap, ahora_utc, fecha_bo, top=bc.ing.TOP_N, previos=previos)
        metrics = bc.compute_metrics(snap, mirror_diag, mirror_parity, canonical)
        metrics["_hermetic_ok"] = True
        (bc.FIXTURE_DIR / "metrics_baseline.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8")
        print("metrics_baseline.json regenerado (determinista).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
