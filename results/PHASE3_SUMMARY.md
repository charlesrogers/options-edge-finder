---
title: "Phase 3 Summary — H21–H24: nothing passed, two things shipped, and the $125 purchase now has a better shopping list"
date: 2026-08-16
status: completed
finding: "Four hypotheses, zero passes. H21 and H22 were blocked on option data that costs money Charles ruled out spending; H22a and H23 failed on their own pre-registered thresholds; H24(b) failed with its control tickers failing alongside it. Two production changes shipped anyway, both of which only restrict: KKR is capped at 7 contracts because its 15%-OTM strike trades 3 a day, and GOOGL is demoted from 'good' to a new 'probation' badge because its parameter was never tested on real option prices."
---

# Phase 3 Summary — Strategy Improvement (H21–H24)

**Constraint:** Charles instructed on 2026-08-16 that this session execute everything in
`tasks/phase3-strategy-spec.md` that does **not** consume API credits. The $125 Databento
purchase (Part A) therefore did not run, and neither did anything that strictly requires
option prices for 2020, 2022, or GOOGL.

## The table

| Hypothesis | Verdict | Deployed? | Expected $ impact at 10k shares/ticker | Regime caveat |
|---|---|---|---|---|
| **H21** — bear/rebound stress replay | **BLOCKED** — no 2020/2022 option prices | No | Unknown. This is the hypothesis that would price the tail risk in Dad's account; it is still unpriced. | The entire question is regime. Exp 010's Monte Carlo is all we have and H21 exists because that was not convincing. |
| **H22** — backwardation guard | **PENDING** — 2020/2022 arms unbought | No | — | The regime it exists for is the one we cannot see. |
| **H22a** — guard, real-price vol-spike arm | **FAIL** (3 of 4 clauses) | No | Would have been +21.6% (AAPL) / +62.2% (DIS) on net call P&L had it passed — but it skips 27.5% of entries and fires in calm years. | Tested on a vol spike that *recovered fast* (Apr-2025). 2020 did not. |
| **H23** — partial overwriting (50–70%) | **FAIL** | No | ~$0. The ratio moves max drawdown by 0.00–1.45pp; it is an income dial, and income is exactly linear in it. | Structural, not regime-dependent — stress years cannot overturn it. |
| **H24(a)** — GOOGL on real prices | **PENDING** — 5 days of data owned | Tier only | — | — |
| **H24(b)** — MSFT/AMZN probation | **FAIL** — 20.0% / 22.9% test loss rate vs a 10% gate | No | $0 — neither ticker enters the recommendation set. | Controls fail the same window (AAPL 11.4%, DIS 20.0%); both candidates pass on 2019–2026. |
| **KKR capacity** (derived, no pass/fail) | 7 contracts / 700 shares | **Yes** | Caps KKR's contribution at ~7% of what the un-capped sizing implied. Prevents an unfillable 100-contract order. | None — liquidity is measured, not forecast. |

Full write-ups: `results/019_stress_replay.md`, `results/019b_backwardation_guard.md`,
`results/020_partial_overwriting.md`, `results/021_capacity_expansion.md`, and the empty
`results/019_data_purchase_ledger.md`.

## What shipped

Two commits, both narrowing what the app claims or recommends:

1. **KKR liquidity cap** — `max_contracts: 7` in `ticker_strategies.py`, enforced by
   `get_max_contracts()` and surfaced on the Sell tab with its reason. Derived from 753
   days of Databento volume in the exact strike the rule sells: median **3 contracts/day**
   (mean 36.7, p25 1, p75 10). At 10,000 shares the un-capped position is 100 contracts —
   33× the median daily volume of that strike. The spec's suspicion is confirmed: the
   position IS the market.
2. **GOOGL `probation` tier** — new badge in `TIER_CONFIG`, deliberately distinct from
   `untested` (which means nobody looked; probation means we looked with a weaker
   instrument). GOOGL's 10% OTM parameter was validated on stock closes only; it was
   displayed with the same `good` badge as tickers validated on real option prices.
   Parameters unchanged.

Nothing else was deployed. Every hypothesis that would have changed the strategy failed.

## Four things Charles should know that were not on the spec

1. **The clock bug invalidates the H21 baseline.** Phase 1 (which landed in parallel today)
   found that `assess_position()` measured DTE against `datetime.now()`, pinning it to 0 in
   every backtest from Exp 007 to Exp 014. H21's clause 2 compares stress-year loss rates
   to "their 2025–26 walk-forward values" — i.e. to `results/012_walk_forward.md`, produced
   on the broken clock. **Re-derive that baseline on `cc_sim.py` before buying stress data**,
   or the purchase buys a comparison against a number that was never measured.

2. **Repricing coverage is worse than assumed, and it is not uniform.** Measured on the
   production entry path: AAPL **2.5%** missing, DIS **14.3%**, TMUS **44.0%**, KKR
   **63.7%**. Only AAPL and DIS carry conclusions. TMUS and KKR each flipped the *sign* of
   their overlay P&L between two simulators built the same week. The purchase order should
   probably lead with **AAPL 2020** rather than TMUS 2022 — cheapest-first is a cost
   heuristic, information-per-dollar is the objective. Recommendation only; the spec's
   order stands until Charles says otherwise.

3. **The IV-rank ≥ 50 entry gate deserves its own experiment.** It is live on every ticker,
   its evidence is one un-staggered path from Exp 009, and the descriptive control in
   Exp 020 shows it rescuing DIS and KKR while costing AAPL and TMUS. Not a conclusion —
   no threshold was pre-registered and nothing was deployed off it — but it is the
   highest-value untested thing in the system.

4. **AMZN is currently recommendable at 5% OTM with zero validation.** It sits in
   `TICKER_STRATEGIES` as tier `untested`, is not marked `skip`, and so is returned by
   `get_recommended_tickers()`. This session just failed to validate AMZN at the far more
   conservative 15% OTM. The pre-registration says a clause-(b) failure means no production
   change, so it was left alone — but the 5% entry is more aggressive than the setting that
   failed. It should be marked `skip` or `probation` in a separate, deliberate commit.

## Discipline record

- All five hypotheses (H21, H22, H22a, H23, H24) were pre-registered with immutable
  thresholds in commit `3a09eba`, **before** any data was touched, and verdicts — all
  failures — are recorded in the signal graveyard.
- The `signal_graveyard` table did not exist in Supabase at all; both this session and
  Phase 1 discovered it independently. `migrations/001_signal_graveyard.sql` creates it and
  it is now live.
- No threshold was moved after seeing a result. H24(b)'s candidates pass on a longer window
  than the pre-registered one; the verdict is still FAIL.
- Two reversals were hit and reported as reversals rather than as answers: the leg ordering
  in H22a and the per-ticker overlay P&L signs for TMUS and KKR both flipped between
  simulators. Neither is presented as settled.
- pytest: 171 passing, including 37 new tests for the liquidity cap, the probation tier,
  the equity curve and the guard.

## What Phase 3 costs to finish

The Databento purchase, unchanged: ~$125, one shot, resolving H21, H22 and H24(a). Given
finding 1, budget a re-derivation of the walk-forward baseline on `cc_sim.py` first —
otherwise the stress-year comparison has nothing valid to compare against.
