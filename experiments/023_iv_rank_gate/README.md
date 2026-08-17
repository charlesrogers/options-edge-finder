# Experiment 023 — The IV-Rank Entry Gate on Trial (H26, Tier 1)

**Pre-registered:** 2026-08-17, before any data was touched or any run executed.
**Spec:** `tasks/phase3-strategy-spec.md` REVISED directive 9.
**Needs no new data.** Owned Databento option OHLCV only.

## Why this exists

`DEFAULT_IV_THRESHOLD = 50` is live on **every** ticker: `paper_trade_logger.py` refuses to
open a position when IV rank < 50, and the Sell tab tells the user low-IV months mean
selling nothing. Its entire evidence base is Experiment 009 — one un-staggered path, on the
simulator with the broken DTE clock, whose headline claim was "+204% average P&L".

Exp 019b's descriptive control then observed the gate **rescuing DIS and KKR while costing
AAPL and TMUS**. That was not a pre-registered test and nothing was deployed off it, but a
single global constant justified by an invalid experiment, live on Dad's account, is the
highest-value untested thing in the system.

The gate is a *restriction*: it removes entries. Removing a restriction increases exposure,
so the deployment rules below are deliberately asymmetric — a gate that fails to prove
itself is not thereby proven harmful, and this experiment cannot license loosening.

## Hypothesis (H26) — immutable, resolved per ticker

> **Clause 1 (the gate earns its place):** for each ticker, entries taken under the
> production gate (IV rank ≥ 50) return a higher **mean net P&L per entry** on the
> walk-forward **holdout** window than entries taken with no gate at all, by at least
> **10% relative**.
>
> **Clause 2 (global 50 is the right number):** for each ticker, the per-ticker threshold
> chosen on the **training window only** from {25, 50, 75} beats the global 50 on the
> holdout by at least **10% relative**.

**Sign convention, fixed in advance** (the H23 lesson — a ratio metric must state what it
does when its inputs go negative): where the comparison baseline's mean per-entry P&L is
**≤ 0**, "10% relative" means an improvement of at least 10% of that baseline's *magnitude*
**and** a resulting mean that is **> 0**. Numerator and denominator are always reported
separately, alongside a no-gate reference row, so no verdict rests on a ratio alone.

**Hard constraint on any deployment (immutable):** the deployed arm must not produce more
assignments on the holdout than the production arm. Zero assignments is the tri-fold goal's
first clause; no P&L improvement buys an assignment.

## Operational definitions (method, fixed before running — not thresholds)

- **Universe:** AAPL, DIS, TMUS, KKR (live, real option data). TXN descriptive control only.
- **Arms:** `no_gate` (A) · `iv_rank_gate(50)` = production (B) · `iv_rank_gate(25)` ·
  `iv_rank_gate(75)`. Arm C = whichever of {25, 50, 75} has the highest **train-window**
  mean net P&L per entry for that ticker. C is selected on train and scored on holdout;
  nothing is selected on the holdout.
- **Settings:** production per-ticker `otm_pct`/`min_dte`/`max_dte`,
  `policy=cc_sim.baseline_policy`, slippage 0.0. Only the gate varies between arms.
- **Walk-forward split:** a single **calendar** cut at `option_days[int(0.67 × n)]`,
  identical for every arm, so arms with different entry counts are still split at the same
  date. Train = entries before the cut; holdout = entries on or after it.
- **Primary metric:** mean net P&L per entry, `pnl_per_share × 100`, dollars per contract.
  A gate cannot change a trade it allows, so a paired per-entry comparison between arms is
  identically zero on shared entries — the question is whether the entries the gate
  *removes* are worse than the ones it keeps. Reported alongside: entries taken, total P&L,
  loss rate, retention, assignments, and `lib_phase3.blocked_entry_stats` (what the gate
  threw away).
- **Decision-relevant view (reported, non-gating):** annualised net P&L per contract from
  25 staggered sequential chains per arm, the same construction as Exp 022 — because an
  account that can hold one call at a time cares about P&L per *year*, not per *entry*, and
  a gate that improves per-entry quality while halving entry opportunities may still lose
  on that basis. Non-gating because the verdict thresholds above were fixed on per-entry
  P&L before any of it was run.
- **Missing data:** repricing coverage per ticker per arm, counted and reported.

## Deployment rules (immutable, fixed before running)

1. **Clause 1 PASS** for a ticker → the gate keeps its place. No production change (it is
   already live); the evidence line in the ticker's `note` is updated to cite this
   experiment instead of the invalid Exp 009.
2. **Clause 1 FAIL** → recorded as "the ≥ 50 gate is **unevidenced** for this ticker".
   **No production change.** The gate is not removed: removal is a loosening change that
   increases exposure in Dad's account, and a failed test of a restriction is not evidence
   for its opposite. The finding goes in the results file and in the ticker note.
3. **Clause 2 PASS** for a ticker **and** the winning threshold is **≥ 50** (equal or more
   restrictive) **and** its holdout assignments ≤ production's → deploy a per-ticker
   `iv_threshold` field, one commit per ticker, with `get_iv_threshold(ticker)` falling
   back to `DEFAULT_IV_THRESHOLD` for everything else, and pytest covering the fallback.
4. **Clause 2 PASS with a winning threshold below 50** → **not deployed.** Recorded as a
   pre-registered candidate for a dedicated loosening experiment with its own thresholds
   and its own walk-forward, because one year of one regime cannot license more selling.
5. TXN deploys nothing under any outcome.

## Known statistical weakness (stated before running)

The IV rank here is production's own proxy — ATM call price as a percent of spot, ranked
against its trailing 60 observations (`cc_sim.compute_iv_rank`, reproducing Exp 009's
definition rather than reinventing it). It is not an implied volatility. One year, one
regime, overlapping cohorts; the holdout is roughly four months for the one-year tickers,
which is thin, and thinner still for the arms that gate hardest. Entry counts per arm are
reported so the reader can see exactly how thin. Nothing here is a significance test.

## Reproducibility

```bash
python3 experiments/023_iv_rank_gate/run.py
```
