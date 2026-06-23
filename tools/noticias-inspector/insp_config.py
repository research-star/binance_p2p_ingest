"""Paths + tunables for the Noticias Inspector.

Anything that mirrors a prod fact lives here and is a SYNC-MANUAL surface
(see SYNC.md): PROD_IMG_UNAVAILABLE. Everything else is imported live from the
real modules so it auto-syncs.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Repo root = three levels up from this file (tools/noticias-inspector/insp_config.py).
# Code + model + gallery webp are committed, so they live in whatever checkout runs
# the tool (the main checkout when deployed).
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # so `import scraper`/`ingest_noticias`/`dashboard` resolve

TOOL_DIR = Path(__file__).resolve().parent
SANDBOX_DIR = TOOL_DIR / "sandbox"          # gitignored; all runtime writes land here

# The productive DBs (p2p_normalized.db, cache_urls.db) are GITIGNORED — they exist
# only in the checkout that runs the pipeline, NOT in a fresh git worktree. FB_DATA_ROOT
# overrides where to find them (used when developing the tool inside a worktree); in the
# deployed/main checkout it's unset so DATA_ROOT == ROOT. Opened READ-ONLY, never written.
DATA_ROOT = Path(os.environ.get("FB_DATA_ROOT", str(ROOT))).resolve()

REAL_DB = DATA_ROOT / "p2p_normalized.db"
REAL_CACHE = DATA_ROOT / "noticias_ingest" / "data" / "cache_urls.db"

# Gallery webp live in static/ as gal-<slug>.webp (committed; use this checkout's copy).
GALLERY_DIR = ROOT / "static"

# VPS (prod) target for the OPT-IN seed refresh — SELECT-only, read-only, never written.
# Refrescar el seed hace prod-fieles las etapas 14 (budget) y 15 (dedup inter-día) cuando
# el mirror local está stale. Override por env si cambia el host/path.
VPS_HOST = os.environ.get("FB_VPS_HOST", "binance@46.62.158.88")
VPS_DB = os.environ.get("FB_VPS_DB", "/opt/binance_p2p/p2p_normalized.db")

# How many days of `noticias` rows to seed into the sandbox so the inter-day
# dedupe window (DEDUPE_DIAS) and the rolling budget COUNT(*) behave like prod.
SEED_DIAS = 8  # one more than DEDUPE_DIAS=7 for safety

# ── SYNC-MANUAL surface (Sync Contract item 3) ───────────────────────────────
# Source slugs whose og:image prod CANNOT serve, so the prod-preview must null
# the og:image and fall through to the gallery slug — matching what prod renders.
#   eldeber   — VPS IP blocked, article HTML never downloads -> image_url NULL
#   bloomberg — og:image is an Arc resizer URL with an expiring signed token;
#               not persisted. The latam carril uses bandera/'internacional' anyway.
# If FASE 2b enables Bloomberg images or El Deber unblocks, update this set.
PROD_IMG_UNAVAILABLE = frozenset({"eldeber", "bloomberg"})

SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
