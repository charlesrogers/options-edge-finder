# Experiment 019b — Backwardation Guard (H22 + H22a, Tier 2)

**Pre-registered:** 2026-08-16, before any data was touched.
**Spec:** `tasks/phase3-strategy-spec.md` Part C.

## Source

Sinclair & Mack, *Positional Option Trading* / Ch. 10 of the retail volume: the one
situation their risk tolerance forbids is selling into a vol spike with the term structure
in **backwardation** — "the volatility equivalent of catching a falling knife." Our IV-rank
≥ 50 entry gate was validated only in calm regimes and actively *encourages* exactly that:
a crash pins IV rank at 100 and the gate screams SELL.

## The guard (arbitrary starting values — to be tuned, not derived)

Suppress **new** call sales when either:

- `VIX > VIX3M` (term structure in backwardation), **or**
- spot < 0.85 × (60-trading-day high) — i.e. the stock is more than **15%** below its
  60-day high.

Both thresholds (the 15%, the 60-day lookback) are **arbitrary starting values**, labelled
as such per research-discipline rule 7. Nothing here is derived from data.
Existing positions are untouched — this is an entry gate only, never an exit rule.

## H22 (spec text, immutable) — TESTABILITY: BLOCKED

> Adding the guard improves **2020** stress-year P&L by ≥ 20% relative with ≤ 10% of
> entries skipped across the full 2019–2023 window, and changes 2022 / 2024–26 results by
> ≤ ±5% (the guard should be dormant outside crash regimes — its control condition).

The 2020 and 2022 P&L clauses need real 2020/2022 option prices, which we do not own
(see `experiments/019_stress_replay/README.md`). No credits were spent this session, so
**H22 is recorded PENDING**, not passed and not failed.

## H22a (new, immutable) — the arm that free data CAN decide

The option data we already own (2025-03-21 → 2026-03-20) contains a genuine vol-spike
regime: 24 backwardation days, clustered in the April-2025 tariff selloff plus
Nov-2025 and Mar-2026. That is a real-price test of the guard's core claim, one regime
short of H22 but on the right kind of tape.

**Hypothesis H22a:** on real option prices over the owned window, adding the guard to the
production entry gate

1. skips ≤ **15%** of otherwise-valid entries (arbitrary starting value), **and**
2. improves aggregate net call P&L across the tradeable tickers (AAPL, DIS, TMUS, KKR) by
   ≥ **10%** relative (arbitrary starting value), **and**
3. does not increase assignments (production baseline is zero — it must stay zero), **and**
4. is dormant in the calm control: on backwardation-free calendar years (2021 and 2023 —
   0 and 2 backwardation days respectively), the guard changes the stock-data entry count
   by ≤ **±5%**.

- **PASS:** all four clauses.
- **MARGINAL:** clauses 1, 3, 4 hold but the P&L change is within ±10% (guard is harmless
  but not yet shown to help — needs the 2020 arm to decide).
- **FAIL:** skips > 15% of entries, **or** reduces aggregate net call P&L, **or** adds an
  assignment, **or** fires materially in the calm control (a guard that fires when there is
  nothing to guard against is a framework bug, not a discovery).

## Method

- Simulator: `experiments/lib_cc_sim.py` (shared, new). Production settings frozen as of
  this commit: per-ticker OTM%/DTE from `ticker_strategies.py`, IV-rank ≥ 50 gate
  (Exp 009 ATM-price proxy), copilot exits via `position_monitor.assess_position`,
  ≥ 25 calendar days between entries. TXN excluded (production tier = skip).
- Guard arm vs. no-guard arm, identical seeds and identical entry calendar otherwise.
- **Staggered entry cohorts:** 25 start-date offsets per ticker, so each arm is measured
  over hundreds of trades instead of ~12. Cohorts overlap and are NOT independent — they
  are reported as a robustness spread (median + min/max across offsets), never as an
  n-large significance test.
- Every repricing failure is counted and reported ("X of Y days missing data"). No silent
  `None` handling.
- Free VIX term structure: `^VIX`, `^VIX3M` daily closes 2019-01-01 → 2026-08-16 (Yahoo).
- Calm control (clause 4) uses stock data only — it counts entries, not P&L, so it needs
  no option prices.

## Deployment

Entry-gate addition in **one commit**, only after H22a passes AND H22's 2020 arm is
resolved, with the guard's live status surfaced on the Sell tab. A pass on H22a alone is
not sufficient for deployment — the whole point of the guard is the regime we cannot yet
test. This is stated before seeing any result so it cannot be relaxed afterwards.

## Reproducibility

```bash
python experiments/019b_backwardation_guard/run.py
```
