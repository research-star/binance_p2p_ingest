"""Noticias Inspector — Flask server + APScheduler hourly cron (FASE B).

Runs on the laptop (NOT the VPS). Serves the 3-tab UI and the API the frontend polls.
A "run" executes core.run() in a background thread (live = real fetch, ~60-90s) so the UI
stays responsive; the frontend polls /api/last-run for the new timestamp.

    python server.py            # http://127.0.0.1:5057
    python server.py --port 8080
"""
from __future__ import annotations

import argparse
import threading
import traceback
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory

import insp_config as cfg
import deps
import pipeline_map
import gallery_view
import inspector_core as core
import seed_refresh

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    _HAS_APS = True
except Exception:  # pragma: no cover  (deps banner will flag it)
    _HAS_APS = False

app = Flask(__name__, static_folder=str(cfg.TOOL_DIR / "static"), template_folder=str(cfg.TOOL_DIR / "templates"))

_state = {"running": False, "last_error": None, "last_started": None, "last_mode": None}
_lock = threading.Lock()
_scheduler = BackgroundScheduler(timezone="UTC") if _HAS_APS else None
_JOB_ID = "noticias-hourly"


def _do_run(mode: str):
    # `running` was already claimed atomically by _spawn() under _lock; just execute + release.
    try:
        core.run(mode=mode)
    except Exception:  # noqa: BLE001
        _state["last_error"] = traceback.format_exc()[-1200:]
    finally:
        _state["running"] = False


def _spawn(mode: str) -> bool:
    # Single guard point: atomic test-and-set of `running` UNDER the lock, so two
    # near-simultaneous /api/run-now (or a cron tick racing a manual run) can't both start a
    # run. The loser is rejected cleanly — no thread spawned.
    with _lock:
        if _state["running"]:
            return False
        _state.update(running=True, last_error=None,
                      last_started=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      last_mode=mode)
    threading.Thread(target=_do_run, args=(mode,), daemon=True).start()
    return True


# ── UI ───────────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    return send_from_directory(app.template_folder, "index.html")


@app.get("/static/<path:f>")
def static_files(f):
    return send_from_directory(app.static_folder, f)


@app.get("/gal/<path:fname>")
def gallery_webp(fname):
    """Serve the real gallery webp so the prod-preview shows real images."""
    if not fname.startswith("gal-") or ".." in fname:
        return ("forbidden", 403)
    return send_from_directory(str(cfg.GALLERY_DIR), fname)


# ── API ──────────────────────────────────────────────────────────────────────
@app.post("/api/run-now")
def api_run_now():
    mode = request.args.get("mode", "live")
    started = _spawn(mode)
    return jsonify({"started": started, "running": _state["running"], "mode": mode})


@app.post("/api/cron/start")
def api_cron_start():
    if not _HAS_APS:
        return jsonify({"ok": False, "error": "apscheduler no instalado"}), 503
    if not _scheduler.running:
        _scheduler.start()
    if _scheduler.get_job(_JOB_ID) is None:
        _scheduler.add_job(lambda: _spawn("live"), "interval", hours=1, id=_JOB_ID,
                           next_run_time=datetime.now(timezone.utc))  # fire one immediately
    else:
        _scheduler.resume_job(_JOB_ID)
    return jsonify(_cron_status())


@app.post("/api/cron/stop")
def api_cron_stop():
    if _HAS_APS and _scheduler.get_job(_JOB_ID):
        _scheduler.remove_job(_JOB_ID)
    return jsonify(_cron_status())


def _cron_status() -> dict:
    job = _scheduler.get_job(_JOB_ID) if (_HAS_APS and _scheduler.running) else None
    nxt = job.next_run_time.strftime("%Y-%m-%dT%H:%M:%SZ") if (job and job.next_run_time) else None
    return {"ok": True, "cron_on": job is not None, "next_run": nxt, "every": "1h"}


@app.get("/api/last-run")
def api_last_run():
    f = cfg.SANDBOX_DIR / "last-run.json"
    last = None
    if f.exists():
        import json
        last = json.loads(f.read_text(encoding="utf-8"))
    return jsonify({
        "run": last,
        "state": _state,
        "cron": _cron_status(),
        "deps": deps.check().as_dict(),
        "seed": seed_refresh.seed_info(),
    })


@app.post("/api/seed/refresh")
def api_seed_refresh():
    """Opt-in: baja la tabla noticias actual del VPS (read-only) a sandbox/. Alimenta la
    PRÓXIMA corrida → budget/dedup prod-fieles. Falla de SSH → 502 con error (la UI cae al
    mirror local con aviso; no crashea)."""
    res = seed_refresh.refresh_from_vps()
    return jsonify(res), (200 if res.get("ok") else 502)


@app.post("/api/seed/clear")
def api_seed_clear():
    """Vuelve al mirror local (descarta el seed VPS)."""
    cleared = seed_refresh.clear_seed()
    return jsonify({"cleared": cleared, "seed": seed_refresh.seed_info()})


@app.get("/api/constants")
def api_constants():
    return jsonify(pipeline_map.live_constants())


@app.get("/api/gallery")
def api_gallery():
    return jsonify(gallery_view.inverse())


@app.get("/api/pipeline-map")
def api_pipeline_map():
    return jsonify({"bolivia": pipeline_map.BOLIVIA_STAGES, "latam": pipeline_map.LATAM_STAGES})


def main():
    import sys
    # Windows consolas usan cp1252 y crashean al imprimir glyphs no-ASCII (→, ⚠, —).
    # Forzar UTF-8 con fallback evita que un print de arranque tumbe el server.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Noticias Inspector server")
    ap.add_argument("--port", type=int, default=5057)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    rep = deps.check()
    print(deps.banner(rep))
    print(f"\nNoticias Inspector -> http://{args.host}:{args.port}  (Ctrl-C para salir)")
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
