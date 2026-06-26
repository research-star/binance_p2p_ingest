#!/usr/bin/env python3
"""
live_bolivia.py - compute the REAL current own-math Bolivia sovereign spread from
live venue prices (Deutsche Borse via the riesgo_pais scraper), and append the
result to riesgo_propio_live.json so genuine own-math history accrues day by day.

Run daily (Task Scheduler). Each run:
  1. scrape live clean prices for the outstanding Bolivia bonds (DB; snapshot backfill)
  2. live US Treasury par curve -> bootstrapped zero curve
  3. MV-weighted Z-spread (our engine) -> Bolivia own-math bp  [REAL, price-driven]
  4. upsert {date, bp, n_bonds, source, prices} into riesgo_propio_live.json
"""
from __future__ import annotations
import json, os, sys
from datetime import date, datetime, timedelta

RP_SRC = r"C:\Users\RodrigoRosasGuzman\riesgo_pais\src"
sys.path.insert(0, RP_SRC)
import engine, bonds as bondmod, prices as pricemod, ust_curve  # noqa: E402
import config as rp_config  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "riesgo_propio_live.json")
# Mirror copy inside the locally-served site so the dashboard can fetch it at
# http://localhost:8000/riesgo_propio_live.json and refresh the live trace.
SITE_STORE = r"C:\Users\RodrigoRosasGuzman\finanzasbo_site\riesgo_propio_live.json"
MAX_POINTS = 20000   # bound the intraday history file

def B(name, isin, issue, mat, coupon, amt):
    return bondmod.Bond(country="Bolivia", name=name, isin=isin,
        issue_date=date.fromisoformat(issue), maturity=date.fromisoformat(mat),
        coupon_schedule=[(date.fromisoformat(issue), coupon)], freq_months=6,
        amort_schedule=None, amount_outstanding_musd=amt, structure="bullet")

# Currently-outstanding Bolivia USD sovereigns (the live basket).
LIVE_BONDS = [
    B("BOLIVIA 4.50% 2028", "USP37878AC26", "2017-03-20", "2028-03-20", 4.50, 1000),
    B("BOLIVIA 7.50% 2030", "USP37878AE81", "2020-03-02", "2030-03-02", 7.50,  850),
    B("BOLIVIA 9.45% 2031", "USP37878AF56", "2026-05-14", "2031-05-14", 9.45, 1000),
]

def fetch_clean_prices(isins):
    """DB live (bid/ask mid -> clean) with snapshot backfill. Returns {isin: (clean, src)}."""
    out = {}
    try:
        db = pricemod.source_deutsche_boerse(isins)
    except Exception as e:
        print("DB scrape error:", e); db = {}
    for i in isins:
        rec = db.get(i)
        # Use the BID side (JPMorgan/EMBI marks on the bid via PricingDirect).
        # Only a genuine two-sided bid counts; a one-sided/last-only quote falls
        # through to the snapshot so we never silently mix mid into a "bid" number.
        if rec and rec.get("bid") is not None:
            out[i] = (float(rec["bid"]), "deutsche_boerse")
    missing = [i for i in isins if i not in out]
    if missing:
        try:
            snap = pricemod.source_snapshot(missing)
        except Exception:
            snap = {}
        for i in missing:
            rec = snap.get(i)
            if rec and rec.get("clean") is not None:
                out[i] = (float(rec["clean"]), "snapshot")
    return out

def main():
    today = date.today()
    settle = today + timedelta(days=2)
    isins = [b.isin for b in LIVE_BONDS if b.issue_date <= settle < b.maturity]
    px = fetch_clean_prices(isins)
    curve = ust_curve.get_curve(prefer="treasury")
    zc = engine.ZeroCurve(curve)
    num = den = 0.0
    num_s = 0.0   # MV-weighted EMBI-style STRIPPED spread (semiannual YTM - matched UST)
    used = {}
    for b in LIVE_BONDS:
        if b.isin not in px:
            continue
        clean, src = px[b.isin]
        cfs = bondmod.generate_cashflows(b)
        accr = bondmod.accrued_interest(b, settle)
        dirty = clean + accr
        zs = engine.zspread(dirty, settle, cfs, zc)
        # EMBI replica leg: stripped spread = semiannual YTM - matched-tenor UST par yield.
        ytm = engine.solve_ytm(dirty, settle, cfs)
        t = engine.yearfrac_30_360(settle, b.maturity)
        stripped = ytm - engine.interpolate(curve, t) / 100.0
        mv = b.amount_outstanding_musd * dirty / 100.0
        num += mv * zs; num_s += mv * stripped; den += mv
        used[b.isin] = {"clean": round(clean, 4), "src": src,
                        "zspread_bp": round(zs * 10000, 1),
                        "stripped_bp": round(stripped * 10000, 1),
                        "ytm_pct": round(ytm * 100, 4),
                        "name": b.name, "coupon": b.coupon_schedule[0][1],
                        "maturity": b.maturity.isoformat(),
                        "amt": b.amount_outstanding_musd, "mv": round(mv, 1)}
    if den == 0:
        print("no live prices; nothing recorded"); return 2
    bp = round(num / den * 10000.0, 1)
    bp_stripped = round(num_s / den * 10000.0, 1)   # EMBI replica number

    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    hist = []
    if os.path.exists(STORE):
        try:
            hist = json.load(open(STORE, encoding="utf-8"))
        except Exception:
            hist = []
    hist.append({"ts": ts, "date": today.isoformat(), "bp": bp,
                 "bp_stripped": bp_stripped,
                 "n_bonds": len(used), "curve": "treasury", "prices": used})
    hist = hist[-MAX_POINTS:]                      # keep intraday history bounded
    text = json.dumps(hist, indent=1)
    open(STORE, "w", encoding="utf-8").write(text)
    try:
        open(SITE_STORE, "w", encoding="utf-8").write(text)   # serve to dashboard
    except Exception as e:
        print("site mirror write failed:", e)
    print(f"Bolivia own-math (LIVE) {ts}: {bp} bp  from {len(used)} bond(s)")
    for i, r in used.items():
        print(f"  {i}: clean {r['clean']} ({r['src']}) -> {r['zspread_bp']} bp")
    print(f"history points: {len(hist)}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
