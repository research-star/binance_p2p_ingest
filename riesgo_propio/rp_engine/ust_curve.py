"""
US Treasury par-yield curve: fetch + bootstrap source.

Primary live source : US Treasury daily par yield curve (free, no key, all tenors)
Cross-check / alt   : EODHD government bonds  US{n}.GBOND  (EOD; use previousClose)
Offline / tests     : SEED_CURVE (the validated 2026-06-24 reference curve)

Spreads are quoted in bp vs the matched-tenor UST. UST is a bond-equivalent
(semiannual) yield, so it lines up directly with our semiannual bond YTM. The
curve refreshes daily; intraday UST drift is small relative to EM-bond price
moves, so a once-daily curve is adequate for the 12-min cron.

The engine bootstraps a zero curve from whatever par curve `get_curve` returns
(engine.ZeroCurve) and interpolates with engine.interpolate.
"""
from __future__ import annotations
import json
import urllib.request

from engine import interpolate  # re-exported for callers; single source of truth

# Validated reference curve (build-prompt Section 7, par yields %, 2026-06-24).
# 10Y anchored to EODHD US10Y.GBOND previousClose 4.502. Short end (<=0.5y) added
# for a smooth bootstrap. Reproduces the Section-8 country spreads to the bp.
SEED_CURVE = {
    0.083: 4.40, 0.25: 4.35, 0.5: 4.20, 1: 3.994, 2: 4.207, 3: 4.223,
    5: 4.275, 7: 4.379, 10: 4.502, 20: 4.964, 30: 4.948,
}

_TREASURY_LABELS = {
    "1 Mo": 1 / 12, "1.5 Month": 1.5 / 12, "2 Mo": 2 / 12, "3 Mo": 0.25,
    "4 Mo": 4 / 12, "6 Mo": 0.5, "1 Yr": 1, "2 Yr": 2, "3 Yr": 3,
    "5 Yr": 5, "7 Yr": 7, "10 Yr": 10, "20 Yr": 20, "30 Yr": 30,
}


def fetch_treasury_par_curve(timeout: int = 15) -> dict:
    """Live US Treasury par yield curve (most recent business day)."""
    import csv, io, datetime
    yr = datetime.date.today().year
    url = ("https://home.treasury.gov/resource-center/data-chart-center/"
           "interest-rates/daily-treasury-rates.csv/{0}/all"
           "?field_tdr_date_value={0}&type=daily_treasury_yield_curve&page&_format=csv").format(yr)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        rows = list(csv.DictReader(io.StringIO(r.read().decode())))
    latest = rows[0]  # most recent date first
    curve = {}
    for lbl, yrs in _TREASURY_LABELS.items():
        v = latest.get(lbl)
        if v not in (None, "", "N/A"):
            curve[yrs] = float(v)
    return curve or dict(SEED_CURVE)


def fetch_eodhd_curve(api_key: str, timeout: int = 15) -> dict:
    """Cross-check curve from EODHD govt bonds (EOD, previousClose)."""
    tenors = {1: "US1Y", 2: "US2Y", 3: "US3Y", 5: "US5Y",
              7: "US7Y", 10: "US10Y", 20: "US20Y", 30: "US30Y"}
    curve = {}
    for yrs, code in tenors.items():
        url = f"https://eodhd.com/api/real-time/{code}.GBOND?api_token={api_key}&fmt=json"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                d = json.loads(r.read().decode())
            val = d.get("close")
            if val in (None, "NA"):
                val = d.get("previousClose")
            if val not in (None, "NA"):
                curve[yrs] = float(val)
        except Exception:
            pass
    return curve


def get_curve(api_key: str | None = None, prefer: str = "seed") -> dict:
    """
    Return a usable par-yield curve (percent).

      prefer="seed"     -> the validated reference curve (deterministic; default)
      prefer="treasury" -> live US Treasury par curve, fall back to seed
      prefer="eodhd"    -> EODHD govt bonds (needs api_key), fall back to seed

    Defaulting to the seed keeps the cron and tests deterministic; the cron can
    request live data explicitly via run.py --curve.
    """
    try:
        if prefer == "treasury":
            return fetch_treasury_par_curve()
        if prefer == "eodhd" and api_key:
            c = fetch_eodhd_curve(api_key)
            if c:
                return c
    except Exception:
        pass
    return dict(SEED_CURVE)
