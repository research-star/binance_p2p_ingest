"""
Bond definitions and cashflow generation.

Supports the three structures found across the tracked sovereigns:
  * plain bullet (Brazil, Chile, Colombia, Mexico, Peru, Bolivia)
  * step-up coupon (coupon rate changes on scheduled dates)
  * amortizing principal / sinkable (Argentina GD, Ecuador 2030/35/40)

A bond is described by:
  * coupon schedule: list of (effective_from_date, annual_rate)
  * amortization schedule: list of (date, principal_fraction) summing to 1.0
    (for a bullet, a single entry [(maturity, 1.0)])
  * payment frequency (months between coupons; 6 = semiannual)

generate_cashflows() walks the coupon dates from maturity back to issue,
applies the step-up rate in force for each period to the OUTSTANDING notional,
and attaches principal repayments on amortization dates.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from dateutil.relativedelta import relativedelta
from engine import CashFlow, days_30_360


@dataclass
class Bond:
    country: str
    name: str
    isin: str
    issue_date: date
    maturity: date
    coupon_schedule: list           # [(date_from, annual_rate_pct)], sorted
    freq_months: int = 6
    amort_schedule: list = None     # [(date, fraction)]; None => bullet
    amount_outstanding_musd: float = 0.0   # for MV weighting
    structure: str = "bullet"       # 'bullet' | 'stepup' | 'amortizing'
    daycount: str = "30/360"
    sources: dict = field(default_factory=dict)  # {'price': url, 'terms': url}
    notes: str = ""

    def coupon_dates(self) -> list:
        """Coupon payment dates from issue (exclusive) to maturity (inclusive)."""
        dts = []
        d = self.maturity
        while d > self.issue_date:
            dts.append(d)
            d = d - relativedelta(months=self.freq_months)
        return sorted(dts)

    def rate_on(self, d: date) -> float:
        """Annual coupon rate (%) in force on date d, from the step-up schedule."""
        rate = self.coupon_schedule[0][1]
        for eff_from, r in self.coupon_schedule:
            if d > eff_from:
                rate = r
        return rate

    def _amort(self) -> list:
        if not self.amort_schedule:
            return [(self.maturity, 1.0)]
        return sorted(self.amort_schedule)


def generate_cashflows(bond: Bond) -> list:
    """Full dated cashflow vector, per 100 original face."""
    cdates = bond.coupon_dates()
    amort = dict(bond._amort())
    period_frac = bond.freq_months / 12.0  # 0.5 for semiannual (30/360 regular period)

    outstanding = 1.0  # fraction of original face still outstanding
    cfs = []
    prev = bond.issue_date
    for cd in cdates:
        rate = bond.rate_on(cd) / 100.0
        coupon = outstanding * rate * period_frac * 100.0
        principal = 0.0
        if cd in amort:
            principal = amort[cd] * 100.0
            outstanding -= amort[cd]
        cfs.append(CashFlow(cd, coupon, principal))
        prev = cd
    # guard: ensure principal sums to ~100
    tot_p = sum(cf.principal for cf in cfs)
    assert abs(tot_p - 100.0) < 1e-6, f"{bond.isin}: principal sums to {tot_p}, not 100"
    return cfs


def accrued_interest(bond: Bond, settle: date) -> float:
    """Accrued interest per 100 original face, 30/360, on outstanding notional."""
    cdates = bond.coupon_dates()
    last = bond.issue_date
    nxt = cdates[-1]
    for cd in cdates:
        if cd <= settle:
            last = cd
        else:
            nxt = cd
            break
    # outstanding notional as of settle
    outstanding = 1.0
    for cd, frac in bond._amort():
        if cd <= settle:
            outstanding -= frac
    rate = bond.rate_on(nxt) / 100.0
    return outstanding * rate * (days_30_360(last, settle) / 360.0) * 100.0
