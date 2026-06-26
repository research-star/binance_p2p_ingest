"""
Central configuration for the riesgo-pais engine.

Everything the spec asks to be configurable lives here and can be overridden
by environment variables so the cron / deployment can tune behaviour without
touching code:

    RIESGO_PRICE_SOURCE     snapshot | deutsche_boerse | stuttgart | auto
    RIESGO_FRESHNESS_MIN    max quote age in minutes before a quote is dropped
    RIESGO_CRON_MINUTES     cron interval (informational; the scheduler enforces it)
    RIESGO_OBS_DATE         YYYY-MM-DD price-observation date (default: today)
    RIESGO_OUT              output path for riesgo_pais.json
    EODHD_API_KEY           EODHD api token (Treasury curve / FX / reference)
"""
from __future__ import annotations
import os

# --- EODHD (Treasury curve, FX, reference data; NOT live bond prices) --------
EODHD_API_KEY = os.environ.get("EODHD_API_KEY", "")

# --- Price source ------------------------------------------------------------
# snapshot        : validated reference snapshot (offline, deterministic; tests)
# deutsche_boerse : live Playwright scrape of live.deutsche-boerse.com
# stuttgart       : live Playwright scrape of boerse-stuttgart.de (Bolivia USP*)
# trace           : FINRA TRACE (US institutional; needs FINRA_API_* creds)
# eodhd_bond      : EODHD bond add-on (EOD only; needs the add-on enabled)
# live / auto     : run SOURCE_PRIORITY as a cascade, snapshot-backfilled
# "a,b,c"         : explicit CSV cascade of the above
PRICE_SOURCE = os.environ.get("RIESGO_PRICE_SOURCE", "snapshot")

# Cascade order for source="live"/"auto": each source fills only the bonds still
# missing a fresh quote; the snapshot always backfills the remainder.
SOURCE_PRIORITY = os.environ.get(
    "RIESGO_SOURCE_PRIORITY",
    "deutsche_boerse,stuttgart,trace,eodhd_bond,snapshot",
).split(",")

# Concurrent headless pages when scraping a live venue. Keep modest (~5): too many
# simultaneous pages starve the thinner bonds' WebSocket quote and cause misses
# (a retry pass backfills any that still slip through).
LIVE_CONCURRENCY = int(os.environ.get("RIESGO_LIVE_CONCURRENCY", "5"))

# Drop any quote older than this (minutes) or without a two-sided (bid/ask) quote.
FRESHNESS_MAX_MINUTES = int(os.environ.get("RIESGO_FRESHNESS_MIN", "30"))

# Flag a country if fewer than this many fresh bonds remain.
MIN_FRESH_BONDS_PER_COUNTRY = 1

# --- Cron --------------------------------------------------------------------
# Same cadence as the dolar paralelo. The scheduler (Task Scheduler / cron /
# the schedule MCP) enforces it; this is the documented default.
CRON_INTERVAL_MINUTES = int(os.environ.get("RIESGO_CRON_MINUTES", "12"))

# --- Settlement --------------------------------------------------------------
# T+2 calendar days from the price-observation date (US/EMBI convention).
SETTLEMENT_LAG_DAYS = 2

# --- Risk bands (FinanzasBo), basis points -----------------------------------
BAND_BAJO_MAX = 350      # < 350  -> BAJO
BAND_MEDIO_MAX = 700     # 350..700 -> MEDIO ; > 700 -> ALTO


def risk_band(spread_bp: float) -> str:
    if spread_bp < BAND_BAJO_MAX:
        return "BAJO"
    if spread_bp <= BAND_MEDIO_MAX:
        return "MEDIO"
    return "ALTO"


# --- Path C: per-country basis offset (bp) -----------------------------------
# Frankfurt/Stuttgart retail prices investment-grade names richer (tighter) than
# the US institutional market that JPMorgan's EMBI tracks. We keep the live
# venue mids for INTRADAY MOVEMENT and add a small, frozen per-country offset to
# anchor the LEVEL to the official EMBI (hybrid "Path C").
#
# Calibrated 2026-06-24 as (official EMBI - our raw MV-weighted Z-spread) for the
# two IG names that show a structural venue basis. The four already-matching
# names (Colombia/Peru/Brazil/Bolivia, within ~15 bp) and the two incomplete
# baskets (Argentina/Ecuador, fixed by pricing the full curve, NOT by an offset)
# carry no offset. Set any of these to 0 to surface the pure raw number.
BASIS_OFFSET_BP = {
    "Mexico": 43,   # raw 158 + 43 -> 201 (EMBI)
    "Chile": 23,    # raw  59 + 23 ->  82 (EMBI)
    # Argentina / Ecuador: incomplete basket -> use the `complete` flag, not an offset.
    # Colombia / Peru / Brazil / Bolivia: raw already tracks EMBI within ~15 bp.
}

# --- Cross-check thresholds (bp) ---------------------------------------------
CROSSCHECK_EXPECT_BP = 2.0   # per-bond our-YTM vs venue-yield: expect <= 2 bp
CROSSCHECK_FLAG_BP = 5.0     # flag (warn) if > 5 bp

# --- Output ------------------------------------------------------------------
# Layout: src/ = implementation; the calculated data is written to the repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_JSON = os.environ.get("RIESGO_OUT", os.path.join(_REPO_ROOT, "riesgo_pais.json"))

# --- Built-in service (serve.py) ---------------------------------------------
# Long-running daemon that recomputes on the cron and serves the JSON feed (no UI).
SERVE_HOST = os.environ.get("RIESGO_SERVE_HOST", "0.0.0.0")
SERVE_PORT = int(os.environ.get("RIESGO_SERVE_PORT", "8765"))
# Curve / EMBI source for the live service (see ust_curve.get_curve / embi).
SERVE_CURVE = os.environ.get("RIESGO_SERVE_CURVE", "treasury")   # seed|treasury|eodhd
SERVE_EMBI_LIVE = os.environ.get("RIESGO_SERVE_EMBI", "live") == "live"

# Price-observation date override (YYYY-MM-DD). None -> today.
OBSERVATION_DATE = os.environ.get("RIESGO_OBS_DATE") or None
