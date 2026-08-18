# Experiment 022 — Baseline Re-derivation (H25, Tier 1)

**Pre-registered:** 2026-08-17, before any data was touched or any run executed.
**Spec:** `tasks/phase3-strategy-spec.md` REVISED directive 1 (Part 0, blocking).
**Needs no new data.** Owned Databento option OHLCV only.

## Why this exists

Every number the app currently shows a user — `expected_pnl`, `expected_win_rate`,
`expected_trades` in `ticker_strategies.py`, and the walk-forward table in
`results/012_walk_forward.md` — was produced by the simulator that measured DTE against
`datetime.now()`. Every historical observation in Experiments 007–013 was therefore
evaluated at **DTE = 0** with **`ex_div_date=None`**, which made every DTE-conditional
alert rule and both ex-dividend rules unreachable (fixed in commit `8040440`; see
`experiments/cc_sim.py` docstring). Assignment was also *inferred* rather than simulated.

Those fields are live on the Sell tab as "Expected P&L/yr per contract" and "Win Rate,
from Experiment 008 backtest on real data". They are the strongest quantitative claims the
product makes to Dad, and they rest on a broken clock.

H21 (the $125 stress purchase) compares stress-year loss rates to those same numbers. This
experiment therefore **blocks the purchase**: buying data to compare against an unmeasured
number is the failure mode the spec was written to avoid.

## Hypothesis (H25) — immutable

> The `expected_pnl` and `expected_win_rate` fields deployed in `ticker_strategies.py`
> (derived from Exp 008/009 on the DTE-broken simulator) are reproduced by the fixed
> engine `experiments/cc_sim.py`, on the same production per-ticker settings and the same
> production IV-rank ≥ 50 entry gate, within **±25% relative** (annualised net P&L per
> contract) and **±10 percentage points** (win rate), for each of AAPL, DIS, TMUS and KKR.

**PASS (immutable):** all four tickers inside **both** tolerances. The deployed fields
stand unchanged and `results/012_walk_forward.md` is re-affirmed.

**FAIL (immutable):** any ticker outside either tolerance. That ticker's `expected_*`
fields are replaced by the corrected values from this experiment — one commit per ticker —
and `results/012_walk_forward.md` is marked superseded.

This is a hypothesis about *our own published numbers*, not about the market. It is
expected to fail; pre-registering it anyway is what stops the correction from being
retrofitted to whatever the new engine happens to print.

## Operational definitions (method, fixed before running — not thresholds)

- **Universe:** AAPL, DIS, TMUS, KKR — the tickers with real Databento option OHLCV that
  are live in the recommendation set. TXN is run as a **descriptive control only**
  (production tier = `skip`); nothing about TXN is gating and no TXN change may deploy off
  this experiment. GOOGL (5 days) and AMZN (none) cannot be run at all.
- **Settings:** each ticker's production `otm_pct` / `min_dte` / `max_dte` from
  `ticker_strategies.py`, `policy=cc_sim.baseline_policy` (the live copilot, evaluated with
  a real `as_of` and real ex-dividend dates), `gate=cc_sim.iv_rank_gate(50)` (the live entry
  gate), slippage 0.0 (the Exp 007–009 convention, kept so the comparison is like-for-like).
- **Sequential chains:** cc_sim opens one cohort per eligible trading day; a real account
  holds one call at a time. Each chain takes the trade at start-offset *s*, then the next
  trade entering on or after the previous exit. **25 offsets per ticker** (s = 0…24).
- **Annualised net P&L per contract** (the quantity `expected_pnl` claims to be):
  `Σ pnl_per_share × 100 × 365 / (last_exit − first_entry).days` within a chain. Reported
  as the **median across the 25 chains**, with the min–max spread. The spread is the
  headline honesty number: with ~12 trades a year, the spread between start dates is
  expected to exceed the difference between most configurations.
- **Win rate:** fraction of trades in a chain with `pnl_per_share > 0`; median across chains.
- **Retention:** `net / gross premium` per chain; median across chains. Undefined when
  gross ≤ 0 — such chains are excluded from the median and **counted in the report**.
- **Half-year windows:** cohort entries partitioned by calendar half-year; `cc_sim.score()`
  per window; ranges reported for retention, loss rate and net P&L per trade. Exp 015
  measured 40–180pp retention swings between halves — a point estimate measures regime luck.
- **Real-fill vs carried-forward:** a trade's exit is a **real fill** when it settles on the
  stock price (`expiry_*`, `early_exercise`) or when a genuine Databento quote exists for
  its symbol on its exit date; otherwise the buyback price is a price carried forward from
  an earlier day. Every scorecard is reported twice: all trades, and real-fill trades only.
  `never_repriced` trades (whose entire life is the carried-forward entry price) and
  `missing_price_pct` are reported per ticker. No silent `None` anywhere.
- **Repricing coverage** = `priced_days / (priced_days + missing_price_days)` over the
  position-days of the entries this configuration actually takes.

## Deployment rules (immutable, fixed before running)

1. **`expected_pnl` / `expected_win_rate` / `expected_trades`** are replaced by this
   experiment's corrected medians for any ticker that fails its tolerance, with the
   chain min–max range recorded in the ticker's `note`. One commit per ticker.
2. **Tier changes are restricting-only.** A ticker is demoted to `probation` if either
   - its repricing coverage is **< 70%** — an arbitrary threshold, chosen in advance and
     labelled as such; the previously observed per-ticker values (AAPL 97.5%, DIS 85.7%,
     TMUS 56.0%, KKR 36.3%) leave a wide gap, and **any** threshold in 57–85% produces the
     same partition, which is why the exact number does not carry weight; or
   - its corrected **median** annualised net P&L per contract is **≤ $0**.

   `probation` is the badge created in Exp 021: we looked, but with a weaker instrument.
   **No ticker may be promoted** by this experiment, in any direction, for any reason.
   TXN stays `skip`.
3. **`results/012_walk_forward.md`** gains a superseded header pointing at this experiment
   if H25 fails. Its numbers are not silently deleted — they are the record of what was
   believed.
4. Nothing about strike distance, DTE band, exit rules or the entry gate changes here.
   Those are H26 (the gate) and the unbought stress purchase (everything else).

## Spec directive 3 — DTE-bug blast radius (verification, not a hypothesis)

Two artefacts are *believed* independent of the broken clock and are relied on downstream.
Believed is not verified, so this experiment verifies both and reports the answer:

- the Exp 006 assignment-probability table in `position_monitor.py` (145K observations),
  consumed by `lookup_itm_probability()` and by every probability-based rule;
- Exp 014's stock-close walk-forward, which is the entire evidence base for the deployed
  15%/10%/7% OTM parameters and for the GOOGL probation decision.

Method: static trace of whether either derivation ever calls `assess_position()` or reads a
DTE computed from the wall clock. Reported as a finding either way.

## Known statistical weakness (stated before running)

One year of real option prices for AAPL/DIS/TMUS/TXN, three for KKR, in one favourable
regime. Overlapping cohorts are **not** independent observations: everything is reported as
a distribution over start dates, never as a significance test. TMUS and KKR already flipped
the *sign* of their overlay P&L between two simulators built in the same week, and both sit
far below AAPL's repricing coverage — deployment rule 2 exists precisely because of that.

## Reproducibility

```bash
python3 experiments/022_baseline_rederivation/run.py
```
