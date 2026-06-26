# Bolivia Sovereign Country Risk — Own-Math Calculator

**Methodology & metrics**
FinanzasBo · Macroeconomía → Riesgo país
*Document generated 2026-06-26. Figures quoted as examples are the live values at that date.*

---

## 1. Purpose & philosophy

This calculator measures **Bolivia's sovereign country risk** — the extra yield investors
demand to hold Bolivian USD government debt over the risk-free US Treasury — and computes it
**independently from raw market inputs** rather than copying a published index.

- We compute the spread **ourselves** from three raw inputs: each bond's **clean price**, its
  **contractual cashflows**, and the **US Treasury curve**.
- The published **J.P. Morgan EMBI Global Diversified** (redistributed daily by the BCRD) is
  used as a **cross-check only — never as the source of truth.**
- The visible value of the calculator is the **gap** between our own-math number and EMBI: it
  tells us, in real time, when the market (as we price it) diverges from the lagged index.

Risk bands (FinanzasBo, reference thresholds — not an official market standard):
**BAJO < 350 bp · MEDIO 350–700 bp · ALTO > 700 bp.**

---

## 2. The number, in one line

> **Country spread = market-value-weighted Z-spread of all outstanding Bolivia USD bonds,
> over the bootstrapped US Treasury zero curve, priced on the bid side.**

As of 2026-06-26: **own-math 438 bp** vs **EMBI 448 bp** → **gap −10 bp**.

---

## 3. Bond universe

**Currently outstanding (the live basket):**

| Bond | ISIN (Reg S) | Coupon | Issued | Maturity | Amount (USD MM) | Structure |
|---|---|---|---|---|---|---|
| BOLIVIA 4.50% 2028 | USP37878AC26 | 4.50% | 2017-03-20 | 2028-03-20 | 1,000 | bullet |
| BOLIVIA 7.50% 2030 | USP37878AE81 | 7.50% | 2020-03-02 | 2030-03-02 | 850 | bullet |
| BOLIVIA 9.45% 2031 | USP37878AF56 | 9.45% | 2026-05-14 | 2031-05-14 | 1,000 | bullet |

All semiannual, 30/360, US$-denominated 144A/Reg-S sovereign Eurobonds.

**Historical universe (for the backwards trend only):** the basket also includes the matured
**4.875% 2022** and **5.95% 2023** Eurobonds, which enter/exit on their real issue/maturity
dates so the historical series reflects the bonds outstanding on each date. *(Matured-bond
terms are provisional pending verification; they affect only the pre-2023 reconstruction,
which is EMBI-anchored regardless — see §10.)*

---

## 4. Data sources & timing

| Input | Source | Side | Timing | Status |
|---|---|---|---|---|
| Bond clean prices (2028, 2031) | Deutsche Börse (Frankfurt), live via headless DOM read | **bid** | venue close ~11:30 ET | live |
| Bond clean price (2030) | Validated snapshot (no live venue) | n/a | static | snapshot, curve-validated |
| US Treasury par curve | home.treasury.gov daily par yields | — | daily close ~15:30 ET | live |
| EMBI Bolivia (cross-check) | BCRD redistribution of J.P. Morgan EMBI GD | bid | NY close 15:00 ET | daily, ~1 business-day lag |

**Why these sources.** The DDR EODHD account returns *Forbidden* for all bond endpoints
(bond add-on disabled), so individual bond prices come from the European venue scrape; EODHD
is usable only for the Treasury curve / FX. No free venue carries the 2030 (Deutsche Börse
doesn't list it; Börse Stuttgart's API host is retired and the site is Cloudflare-gated;
Tradegate/LS-TC don't carry it; Business Insider's quote is stale), so the 2030 uses a
validated snapshot that sits on the live 2028–2031 curve.

---

## 5. Core formulas

**Settlement.** `T = observation date + 2 calendar days` (T+2, US/EMBI convention).

**Day count — 30/360 (US bond basis).** For dates d1, d2:

```
D(d1,d2) = 360·(Y2−Y1) + 30·(M2−M1) + (D2* − D1*)
  where D1* = min(day1, 30),  D2* = 30 if D1*=30 and day2=31, else day2
Time in years:  τ(d) = D(T, d) / 360
```

**Cashflows (per 100 face).** Semiannual bullet: coupon `c_k = coupon/2` on each date `d_k`,
plus principal `100` at maturity.

**Accrued interest & dirty price.**

```
AI       = coupon · D(last_coupon_date, T) / 360
P_dirty  = P_clean + AI
```

**US Treasury par → zero (spot) curve bootstrap.** From the par curve `p(τ)` interpolated onto
a semiannual grid `τ_j = 0.5·j`:

```
DF(τ_j) = ( 1 − (p_j/2)·Σ_{i<j} DF(τ_i) ) / ( 1 + p_j/2 )
z(τ_j)  = 2·( DF(τ_j)^(−1/(2τ_j)) − 1 )
```

**Z-spread (per bond) — the core number.** The constant spread `s_i` added to the *entire*
zero curve that reprices the bond to its dirty price (solved by bisection):

```
P_dirty,i = Σ_k  CF_k / ( 1 + (z(τ_k) + s_i)/2 )^(2·τ_k)
per-bond spread (bp) = s_i × 10,000
```

**Country (own-math) spread — market-value-weighted.**

```
S_own = [ Σ_i w_i · s_i / Σ_i w_i ] × 10,000
  weight  w_i = A_i · P_dirty,i / 100      (A_i = amount outstanding, USD MM)
```

**Cross-check — semiannual YTM.** Solves `P_dirty = Σ CF_k/(1+y/2)^(2τ_k)`; annualised
`y_ann = (1+y/2)² − 1`. Used only to validate against venue yields.

**EMBI-style stripped spread (for the replica, §9).** Per bond: `semiannual YTM − matched-tenor
UST par yield`, then market-value-weighted. (For this curve it comes out ≈ the Z-spread.)

---

## 6. Pricing conventions

- **Bid side.** J.P. Morgan marks the EMBI on the **bid** (via PricingDirect). To be
  comparable, our clean price is the venue **bid**, not the bid/ask mid. On these illiquid
  bonds the bid-ask is wide (~1 point on the 2028), so the mid materially understated the
  spread; bid is the conservative, EMBI-consistent side.
- **EOD strike at 15:00 ET (DST-aware).** EMBI is struck at the **New York bond-market close,
  15:00 ET** (PricingDirect "NY Bond 3PM" snapshot). The daily **EOD own-math** is taken from
  the capture nearest **15:00 wall-clock America/New_York** — computed via `Intl` so it tracks
  EDT (19:00 UTC) and EST (20:00 UTC) automatically across DST boundaries.
- **Residual timing basis.** Even struck at 15:00 ET, the underlying bond price is the
  **Frankfurt close (~11:30 ET)** — ~3.5 h before J.P. Morgan's mark. This residual cannot be
  removed without US-close institutional prices (TRACE/Bloomberg/ICE), which are gated.

---

## 7. Metrics shown on the dashboard

| Metric | Definition |
|---|---|
| **Bolivia en vivo** (ticker) | Live own-math country spread (bid, MV-weighted Z-spread), bp |
| **EOD propio** | Own-math struck at 15:00 ET — directly comparable to EMBI's EOD mark |
| **EMBI (EOD)** | Published J.P. Morgan EMBI GD Bolivia spread (cross-check), bp |
| **Brecha (gap)** | `own-math − EMBI`, bp. Negative = we read tighter than the index |
| **Per-bond Z-spread** | Each bond's `s_i × 10⁴` (the decomposition panel) |
| **Per-bond stripped spread** | Each bond's `YTM − matched UST` (the replica/trial panel) |
| **MV weight** | `A_i · P_dirty,i / 100` — the bond's market value in the basket |
| **Band** | BAJO / MEDIO / ALTO per the 350 / 700 bp thresholds |

Example (2026-06-26, bid): 2028 → **342 bp**, 2030 → **469 bp** (snapshot), 2031 → **502 bp**;
MV-weighted **438 bp**.

---

## 8. The gap vs J.P. Morgan EMBI

The gap is coherent because nearly every difference pushes us the *same* direction (tighter):

| Difference | Logic or input | Effect | Closeable |
|---|---|---|---|
| Mid vs **bid** price | input | mid overstates price → tighter | **Yes — done (was ~30 bp)** |
| Z-spread vs stripped spread | logic | ≈ 0 on this (flat) curve | n/a — not a driver |
| Basket weighting | logic | EMBIGD caps are country-level; within Bolivia = MV (same as ours) | n/a — no within-basket effect |
| **2030 on snapshot** (no live bid) | input | one leg not on live bid | only with paid feed |
| **Timing** (Frankfurt 11:30 ET vs NY 15:00 ET) | input | ~3.5 h stale | only with US-close prices |

**Key findings.** Switching mid → **bid closed ~30 bp of a ~40 bp gap.** Replicating EMBI's
**weighting changed nothing** (its diversification caps act at the country level; within a
single country it is market-value weighting — already what we do). Replicating EMBI's **spread
definition also changed nothing** — the stripped spread came out ≈ identical to the Z-spread
because the UST curve is flat across the 2–5y zone where these bonds sit. The **residual −10 bp
is purely data-limited** (the 2030 snapshot + the ~3.5 h timing basis), not a modeling choice.

---

## 9. EMBI replica (trial)

A separate "trial" panel applies **all** the closers at once — **bid + stripped spread +
MV (EMBIGD) weighting + 15:00 ET** — to see how close pure replication gets:

```
Réplica (all fixes)        ≈ 438 bp
EMBI                          448 bp
Residual                      −10 bp     ← 2030 snapshot + timing
+ Path-C base offset (+10) →  448 bp = EMBI   (anchored, NOT independent)
```

The trial demonstrates that every *legitimate* fix lands at 438; hitting EMBI **exactly**
requires a constant "venue-basis" offset that simply re-anchors to the index and discards the
independent signal. We do **not** apply that offset to the headline number.

---

## 10. Historical reconstruction (backwards trend)

Independent historical per-bond prices do not exist for free, so the back-history line is an
**EMBI-anchored reconstruction**: for each past date `t`, each outstanding bond's price is
*implied* from the EMBI level, then re-run through *our* Z-spread math over the bonds
outstanding that day, and the whole series is level-anchored to the live real-price number:

```
y_i(t) = UST(τ_i; t) + S_EMBI(t)  ⇒  P_dirty,i(t)  ⇒  s_i(t)  ⇒  S_recon(t)   (MV-weighted)
S_propio(t) = S_recon(t) + ( S_live_anchor − S_recon(t0) )
```

This is **transparent and labeled**: the back-history tracks EMBI by construction (it is the
only historical market data available); the **independent signal lives only at the live edge**
(real bid prices) and accrues forward each day. The historical UST curves are the real
treasury.gov daily closes, and the bond basket genuinely changes membership over time.

---

## 11. Live system architecture

- **Capture loop** (`live_bolivia.py` via `live_loop.py`): every ~60 s, scrape the venue bid,
  fetch the live Treasury curve, compute the MV-weighted Z-spread (and the stripped spread),
  append a **timestamped** point to `riesgo_propio_live.json`.
- **Serving**: the store is mirrored into the served site; the dashboard fetches
  `/riesgo_propio_live.json` and refreshes the ticker, decomposition, and trial panels.
- **Backwards trend** (`build_historical.py`): regenerates the EMBI-anchored reconstruction,
  re-anchored to the latest live point, plus the EMBI comparison series.
- **Panels** (Macro → Riesgo país): the live ticker card, the decomposition panel (per-bond
  Z-spreads + EOD gap), the EMBI-replica trial box, and the historical chart with three Bolivia
  traces — EMBI, own-math reconstruction, and live own-math markers.

---

## 12. Limitations & caveats

- **2030 leg is a static snapshot** (no live venue / no live bid). Flagged as such on the panel.
- **~3.5 h timing basis** between the Frankfurt close and J.P. Morgan's 15:00 ET mark.
- **Back-history is EMBI-anchored**, not independently priced (no free historical bond prices).
- **EODHD cannot price bonds** on this account; venue scrape is the only bond source.
- **Illiquid bid-ask**: these bonds trade wide; the bid is conservative but moves with thin
  liquidity. Off-venue-hours the price holds at the last close quote.
- Risk-band thresholds (350 / 700) are FinanzasBo reference levels, not a market standard.

---

## 13. Validation & reproducibility

The pricing engine is the validated **riesgo_pais** engine: `python src/run.py --obs 2026-06-24
--source snapshot --curve seed` reproduces the reference country spreads to the basis point
(Colombia 188, Bolivia 434, Peru 97, Brazil 190) and the Bolivia 2028 annual YTM = 7.5136%; its
21-test suite is green. The FinanzasBo layer (`riesgo_propio/`) reuses that engine unchanged and
adds the bid convention, the EOD/JP-Morgan timing alignment, the stripped-spread replica, and
the dashboard panels.

**Scripts** (`binance_p2p_ingest/riesgo_propio/`): `live_bolivia.py` (one capture),
`live_loop.py` (minute loop), `build_historical.py` (reconstruction), `inject_into_site.py`
(dashboard panels), `daily_update.py` (daily orchestration).

---

*Own-math is the truth from raw inputs; EMBI is the cross-check. This is informational, not
financial advice.*
