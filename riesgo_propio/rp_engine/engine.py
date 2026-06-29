"""
Core fixed-income math for the riesgo-pais (EMBI-style sovereign spread) engine.

Design principle: we compute EVERYTHING ourselves from raw inputs
(clean price + dated cashflow vector + Treasury curve). Third-party yields
(Deutsche Borse, Borse Stuttgart) and the published JPMorgan EMBI are cross-checks
only, never the source of truth.

Conventions
-----------
* Cashflows are per 100 of ORIGINAL face value (amortizers are rebased to
  current face by the caller before solving).
* YTM uses SEMIANNUAL compounding (US / JPMorgan-EMBI convention) so it is
  directly comparable to US Treasuries (bond-equivalent yield). European venues
  quote ANNUAL compounding -> use semi_to_annual() before cross-checking them.
* Day count is 30/360 (US bond basis) for both accrual and discount time.

Validated vs Bolivia 4.5% 2028 (USP37878AC26): clean 95.38, accrued 1.1875
-> our annual YTM 7.5136% vs Deutsche Borse 7.5119% (0.2 bp); accrued exact.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date


# --------------------------------------------------------------------------- #
# Day count
# --------------------------------------------------------------------------- #
def days_30_360(d1: date, d2: date) -> int:
    """30/360 (US bond basis) day count from d1 to d2."""
    dd1 = min(d1.day, 30)
    dd2 = d2.day
    if dd1 == 30 and dd2 == 31:
        dd2 = 30
    return (d2.year - d1.year) * 360 + (d2.month - d1.month) * 30 + (dd2 - dd1)


def yearfrac_30_360(d1: date, d2: date) -> float:
    return days_30_360(d1, d2) / 360.0


# --------------------------------------------------------------------------- #
# Cashflow
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CashFlow:
    pay_date: date
    coupon: float      # coupon component, per 100 original face
    principal: float   # principal repaid, per 100 original face

    @property
    def total(self) -> float:
        return self.coupon + self.principal


# --------------------------------------------------------------------------- #
# Pricing / YTM (semiannual compounding)
# --------------------------------------------------------------------------- #
def dirty_price_from_ytm(ytm_semi, settle, cfs, daycount=days_30_360):
    """PV of remaining cashflows at a flat semiannual yield."""
    p = 0.0
    for cf in cfs:
        if cf.pay_date <= settle:
            continue
        t = daycount(settle, cf.pay_date) / 180.0   # number of semiannual periods
        p += cf.total / (1.0 + ytm_semi / 2.0) ** t
    return p


def solve_ytm(dirty, settle, cfs, daycount=days_30_360, lo=-0.5, hi=5.0):
    """Bisection solve for the semiannual YTM matching `dirty`."""
    for _ in range(300):
        mid = (lo + hi) / 2.0
        if dirty_price_from_ytm(mid, settle, cfs, daycount) > dirty:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def macaulay_duration(ytm_semi, settle, cfs, daycount=days_30_360):
    pv_total = weighted = 0.0
    for cf in cfs:
        if cf.pay_date <= settle:
            continue
        t_years = daycount(settle, cf.pay_date) / 360.0
        t_per = daycount(settle, cf.pay_date) / 180.0
        pv = cf.total / (1.0 + ytm_semi / 2.0) ** t_per
        pv_total += pv
        weighted += pv * t_years
    return weighted / pv_total if pv_total else 0.0


def weighted_average_life(settle, cfs, daycount=days_30_360):
    num = den = 0.0
    for cf in cfs:
        if cf.pay_date <= settle or cf.principal <= 0:
            continue
        t_years = daycount(settle, cf.pay_date) / 360.0
        num += cf.principal * t_years
        den += cf.principal
    return num / den if den else 0.0


# --------------------------------------------------------------------------- #
# Convention conversion (semiannual <-> annual)
# --------------------------------------------------------------------------- #
def semi_to_annual(ytm_semi: float) -> float:
    """y_annual = (1 + y_semi/2)^2 - 1."""
    return (1.0 + ytm_semi / 2.0) ** 2 - 1.0


def annual_to_semi(ytm_annual: float) -> float:
    """y_semi = 2((1 + y_annual)^0.5 - 1)."""
    return 2.0 * ((1.0 + ytm_annual) ** 0.5 - 1.0)


# --------------------------------------------------------------------------- #
# Treasury curve: linear interpolation, zero-curve bootstrap, Z-spread
# --------------------------------------------------------------------------- #
def interpolate(par_curve: dict, t_years: float) -> float:
    """Linear interpolation (flat beyond the ends) of a par yield (%) at t_years."""
    pts = sorted(par_curve.items())
    if t_years <= pts[0][0]:
        return pts[0][1]
    if t_years >= pts[-1][0]:
        return pts[-1][1]
    for (t0, y0), (t1, y1) in zip(pts, pts[1:]):
        if t0 <= t_years <= t1:
            w = (t_years - t0) / (t1 - t0)
            return y0 + w * (y1 - y0)
    return pts[-1][1]


class ZeroCurve:
    """
    Bootstrapped semiannual zero (spot) curve from a par-yield curve.

    The par curve (percent, e.g. {1: 3.994, 2: 4.207, ...}) is interpolated onto
    a dense semiannual grid (0.5y .. `max_years`), then bootstrapped node by node:
        DF(t) = (1 - (p/2) * sum(prev DFs)) / (1 + p/2)
        z(t)  = 2 * (DF(t)^(-1/(2t)) - 1)
    `at(t)` linearly interpolates the zero rate (decimal) at t years, flat at the
    ends. Used for the Z-spread.
    """

    def __init__(self, par_curve: dict, max_years: float = 110.0):
        self.par_curve = dict(par_curve)
        self.nodes = [i * 0.5 for i in range(1, int(max_years / 0.5) + 1)]
        par = {t: interpolate(par_curve, t) / 100.0 for t in self.nodes}
        df = {}
        for k, t in enumerate(self.nodes):
            p = par[t]
            s = sum(df[self.nodes[j]] for j in range(k))
            df[t] = (1 - (p / 2) * s) / (1 + p / 2)
        self.df = df
        self.zero = {t: 2 * ((1 / df[t]) ** (1 / (2 * t)) - 1) for t in self.nodes}

    def at(self, t: float) -> float:
        """Zero rate (decimal, semiannual) at t years."""
        ts = self.nodes
        if t <= ts[0]:
            return self.zero[ts[0]]
        if t >= ts[-1]:
            return self.zero[ts[-1]]
        for a, b in zip(ts, ts[1:]):
            if a <= t <= b:
                za, zb = self.zero[a], self.zero[b]
                return za + (t - a) / (b - a) * (zb - za)
        return self.zero[ts[-1]]


def zspread(dirty, settle, cfs, zero_curve: ZeroCurve,
            daycount=days_30_360, lo=-0.05, hi=0.6) -> float:
    """
    Constant spread s (decimal) added to the zero curve such that
        sum( CF / (1 + (z(t) + s)/2)^(2t) ) = dirty
    with t = 30/360 year fraction settle->pay_date. Solved by bisection.
    """
    def pv(s):
        v = 0.0
        for cf in cfs:
            if cf.pay_date <= settle:
                continue
            t = daycount(settle, cf.pay_date) / 360.0
            v += cf.total / (1 + (zero_curve.at(t) + s) / 2) ** (2 * t)
        return v

    for _ in range(200):
        m = (lo + hi) / 2
        if pv(m) > dirty:
            lo = m
        else:
            hi = m
    return (lo + hi) / 2
