"""Opt-in seed refresh desde el VPS (cierra la salvedad de budget/dedup).

Las etapas 14 (presupuesto) y 15 (dedup inter-día) dependen del ESTADO de la tabla
`noticias`; el mirror local puede estar stale. Este módulo baja la tabla `noticias` ACTUAL
del VPS por SSH **read-only** (SELECT) a `sandbox/vps-seed.json`. La próxima corrida siembra
desde ese JSON (ver sandbox.build_sandbox), así budget/dedup quedan contra el estado de HOY.

Hermeticidad intacta: nunca se escribe en el VPS (solo SELECT) ni en los DB reales locales;
el dump vive en `sandbox/` (gitignored). Si el SSH falla, degrada al mirror local con aviso.

Método: `sqlite3 -json` vía SSH (VPS 3.45.1 lo soporta) — pulls SOLO la tabla noticias como
JSON column-keyed (pocas filas), robusto a schema skew. No scp del DB de 1.37 GB.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

import insp_config as cfg

SEED_FILE = cfg.SANDBOX_DIR / "vps-seed.json"
_REMOTE_QUERY = "SELECT * FROM noticias"


def refresh_from_vps(timeout: int = 45) -> dict:
    """SSH SELECT read-only de la tabla noticias del VPS -> sandbox/vps-seed.json.
    Devuelve {ok, source, n, min_date, max_date, fetched_at} o {ok:False, error}."""
    cfg.SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    remote = f"sqlite3 -json {cfg.VPS_DB} '{_REMOTE_QUERY}'"
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}", cfg.VPS_HOST, remote]
    try:
        # encoding utf-8 OBLIGATORIO: el JSON trae acentos; text=True usaría cp1252 en Windows
        # y el reader thread de subprocess crashea (UnicodeDecodeError) -> stdout vacío.
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout + 20)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"ssh timeout (>{timeout + 20}s)"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"ssh fallo: {type(e).__name__}: {e}"}
    if proc.returncode != 0:
        return {"ok": False, "error": f"ssh rc={proc.returncode}: {(proc.stderr or '').strip()[:200]}"}
    out = (proc.stdout or "").strip()
    if not out:
        return {"ok": False, "error": "VPS devolvió 0 filas (tabla vacía o query sin salida)"}
    try:
        rows = json.loads(out)
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"JSON inválido del VPS: {e}"}
    if not isinstance(rows, list) or not rows:
        return {"ok": False, "error": "payload del VPS no es una lista de filas"}

    dates = sorted(r.get("date") for r in rows if r.get("date"))
    meta = {
        "source": "vps",
        "host": cfg.VPS_HOST,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n": len(rows),
        "min_date": dates[0] if dates else None,
        "max_date": dates[-1] if dates else None,
    }
    SEED_FILE.write_text(json.dumps({**meta, "rows": rows}, ensure_ascii=False, default=str),
                         encoding="utf-8")
    return {"ok": True, **meta}


def load_seed_rows() -> list | None:
    """Filas del seed VPS si existe un refresh previo; None si no hay (→ usar mirror local)."""
    if not SEED_FILE.exists():
        return None
    try:
        return json.loads(SEED_FILE.read_text(encoding="utf-8")).get("rows")
    except Exception:  # noqa: BLE001
        return None


def seed_info() -> dict:
    """Metadata del seed actual para la UI (fuente + frescura)."""
    if not SEED_FILE.exists():
        return {"source": "mirror-local", "note": "seed nunca refrescado desde el VPS"}
    try:
        d = json.loads(SEED_FILE.read_text(encoding="utf-8"))
        return {k: d.get(k) for k in ("source", "fetched_at", "n", "min_date", "max_date", "host")}
    except Exception as e:  # noqa: BLE001
        return {"source": "mirror-local", "note": f"vps-seed.json ilegible: {e}"}


def clear_seed() -> bool:
    """Borra el seed VPS (vuelve al mirror local). Devuelve True si había algo que borrar."""
    if SEED_FILE.exists():
        SEED_FILE.unlink()
        return True
    return False
