# Week 2 Farm-Out Spec — Retention Engine, Trend Gate, EMERGENCY Refinement

**Executor:** Opus 5, fresh session, working dir `/Users/charlesrogers/Documents/options-tool`
**Prerequisite:** Week 1 reliability spec (`tasks/week1-reliability-spec.md`) complete — do not run research against a pipeline that can silently lie.
**Read first:** `CLAUDE.md`, `tasks/lessons.md`, `tasks/testing-and-research-spec.md`, `signal_registry.py`, `ticker_strategies.py`, `position_monitor.py`, `experiments/008_strategy_grid/run.py`, `experiments/009_crush_it/run.py`, `results/006_covered_call_copilot.md`, `results/009_crush_it.md`

## Context

Strategy: conservative covered calls on ~7 tickers the user's father owns (10k shares each), per-ticker OTM%/DTE in `ticker_strategies.py`, IV-rank ≥ 50 entry gate, 5-level exit copilot. Validated across 14 experiments on real Databento option prices. The edge is operational (exit discipline + ex-div assignment avoidance), not pricing.

**The problem this week attacks:** premium retention is 13% — the copilot triggers CLOSE_SOON/CLOSE_NOW on *distance to strike*, and 74% of gross premium goes to buyback costs (Exp 009). At the father's scale (~$85K/yr gross potential), lifting retention to ~20-25% without adding assignments is worth $30-60K/yr. We own the asset that makes this possible: an empirical assignment-probability table built from **145,099 real option observations** (moneyness × DTE, in `position_monitor.py` and `results/006_covered_call_copilot.md`).

## The research discipline (bettybot model — non-negotiable)

This repo implements the variance-betting hypothesis pipeline in `signal_registry.py`: **pre_register → mark_testing → mark_result → graveyard** (Supabase-backed; failed signals are stored forever for Deflated Sharpe correction). H01–H16 are taken; this spec registers **H17–H20**.

Rules, each of which has been violated once in this project's history and cost real time:

1. **Pre-register with immutable pass/fail thresholds BEFORE touching data.** Never adjust thresholds after seeing results. (The one time this was skipped — Exp 013 → direct deploy — walk-forward later proved 2 of 3 recommendations wrong and forced a revert.)
2. **Walk-forward holdout mandatory** (train first 67%, test last 33%). Nothing deploys on in-sample results.
3. **Analysis output goes to `results/NNN_*.md`, never straight to production config.** Deployment is a separate, gated step: one ticker/variable per commit, commit message references the experiment.
4. **Real prices only for conclusions.** Databento files at `/Users/charlesrogers/Documents/options-tool/data/databento/raw/` (gitignored, ~145MB, loaded by `experiments/backtest_engine.py`). BSM/Yahoo-proxy results are labeled "directional estimate only — not deployable."
5. **No silent Nones:** every repricing/lookup failure logged and counted; report "X of Y days missing data" in every backtest result.
6. **Compute expected trade count before running; flag < 100 trades as unreliable, target 200+** where the data allows.
7. **Every threshold in a recommendation is either derived (show the derivation) or labeled an arbitrary starting value to tune.**
8. Mark every finding in the graveyard — pass AND fail.

Data caveat: Databento OHLCV is trade-based; strikes that didn't trade have no bar. AAPL ~6% missing, KKR ~71%. Weight conclusions toward AAPL/TMUS/DIS; treat KKR results as low-confidence.

## Experiment 015 — Probability-Based Buyback Thresholds (register as H17, Tier 1)

**Hypothesis:** Replacing distance-based CLOSE_SOON/CLOSE_NOW triggers with assignment-probability triggers (empirical table lookup on moneyness × DTE) raises simulated premium retention from 13% to ≥ 20% while keeping assignments at zero and net P&L ≥ the current-rule baseline, on walk-forward test data.

**Why believable first (Sinclair's rule — believe, then test):** the current rule fires at a fixed distance regardless of DTE; the table says 5% OTM at 3 DTE is 1.7% assignment risk while 5% OTM at 30 DTE is 25.3%. A fixed-distance rule necessarily over-buys-back short-dated positions and under-protects long-dated ones. The information is already paid for.

**Method:**
- Reuse the Exp 008/009 simulator. Swap the copilot trigger for `P(assign) = table[moneyness_bucket][dte_bucket]`; grid over trigger thresholds — CLOSE_SOON at P > {10%, 15%, 20%}, CLOSE_NOW at P > {25%, 35%, 45%} (arbitrary starting values to tune, not derived).
- All 6 tradeable tickers × current production OTM%/DTE settings. Walk-forward 67/33.
- **EMERGENCY logic untouched.** The ex-div rule is out of scope here.
- Report per combo: retention %, net P&L, assignments (must be 0), worst trade, buyback count vs baseline, missing-data days.

**Pass (immutable):** on the test period, some threshold pair achieves retention ≥ 20% AND 0 assignments AND net P&L ≥ baseline for ≥ 3 tickers.
**Fail:** no threshold pair beats baseline retention without either an assignment or lower net P&L.
**Deployment gate:** per-ticker walk-forward pass → deploy that ticker only, one commit each, then 2 weeks of shadow mode (log old-rule vs new-rule decisions side by side in production before switching the live trigger).

## Experiment 016 — Trend Gate (register as H18, Tier 2)

**Hypothesis:** Suppressing new call sales when the stock is in a strong uptrend reduces per-ticker loss rate by ≥ 30% (relative) while skipping ≤ 25% of otherwise-valid entries, walk-forward.

**Source:** Sinclair & Mack (2024), Ch. 10 & 15 — momentum persistence is real; options on trending stocks are systematically *cheap* (BSM is "fooled by trends"), i.e., selling calls on a trending stock is selling underpriced insurance. This is the theoretical backbone of our worst empirical result (GOOGL: 48% loss rate before it was widened/near-skipped).

**Method:**
- Stock data only for the signal (2y daily via `yf_proxy`, free); option P&L from the existing simulator.
- Candidate gates (arbitrary starting values): 20-day return > {+5%, +8%}; 60-day return > {+12%, +18%}; 252-day rolling autocorrelation percentile > {70th, 85th}. Test independently — no combined gates (overfitting surface).
- **Control (bettybot pattern):** KKR and DIS already run ~0-2% loss rates. The gate should change their results ≤ ±1 loss. If the gate "improves" the already-clean tickers, suspect a framework bug, not a discovery.
- Primary target: does the gate rescue GOOGL-class losses on AAPL/TMUS/GOOGL/DIS?

**Pass (immutable):** ≥ 30% relative loss-rate reduction on ≥ 2 of the loss-bearing tickers, ≤ 25% of entries skipped, control tickers unchanged, net P&L not reduced by more than the premium of skipped winning trades' fair share.
**Fail:** loss reduction < 30% relative, or entry loss > 25%, or control tickers shift.
**Deployment:** gate becomes an additional entry condition in `ticker_strategies.py` / the Sell tab, per-ticker, one commit each, after walk-forward pass.

## Experiment 017 — EMERGENCY Rational-Exercise Refinement (register as H19, Tier 2 — SHADOW MODE ONLY)

**Hypothesis:** Conditioning EMERGENCY on Natenberg's rational early-exercise criteria — ITM **and** ex-div ≤ 3 days **and** dividend > call's remaining extrinsic value **and** delta ≥ 0.95 — reduces false-positive emergency buybacks by ≥ 50% with **zero** missed true-assignment scenarios in historical data.

**Source:** Natenberg (1994), Ch. 12: a call is only rationally exercised early when trading at parity (extrinsic ≈ 0) with delta near 100; for dividend capture, when remaining time value < the dividend. Our current ITM+3d rule is a blunt superset. Note his warning: early exercise is *more* common in low-vol regimes — the calm months are when this matters most.

**Safety framing — this loosens a $400K alert, so:**
- **No production change in Week 2. Shadow mode only.** Log both rules' verdicts on every monitor pass; the live alert remains the current rule.
- Backtest first on chain snapshots in Supabase + Databento prices. **Data caveat:** chain capture was dead 2026-03-30 → 2026-08-15; the historical snapshot record has a 4.5-month hole. Quantify the usable sample before promising anything; if historical ITM+ex-div events < 20, say so and let shadow mode carry the burden.
- Safety margin: the suppression condition uses extrinsic > dividend × 1.5 (arbitrary starting margin, to tune upward only).

**Pass (immutable):** in combined backtest + ≥ 2 weeks shadow logging: ≥ 50% of current-rule EMERGENCY firings suppressed, AND zero cases where the refined rule stayed silent and the option was (or empirically would have been, per the assignment table at ≥ 90% probability) assigned.
**Fail:** any missed true-assignment scenario. One miss kills the hypothesis regardless of the false-positive win.
**Deployment:** requires explicit sign-off from Charles after reviewing shadow logs. Not autonomous.

## Experiment 018 (stretch, only if 015–017 complete) — Roll-at-CLOSE_SOON Revisit (register as H20, Tier 3)

Exp 009 showed rolling instead of closing helped individual names (KKR +$702 → +$1,894) but not the aggregate, *under the old distance triggers*. Re-run the roll variant under Exp 015's winning probability triggers, walk-forward. Pre-register pass/fail before running (retention ≥ 25%, 0 assignments, aggregate P&L > close-only). If 015 failed, skip this entirely.

## Mechanics & deliverables

- Each experiment: `experiments/NNN_name/README.md` (pre-registration, committed BEFORE the run script), `run.py`, `results/NNN_*.md`, graveyard `mark_result`.
- New financial logic (probability triggers, gate logic, extrinsic-value calc) gets pytest coverage in `tests/` before any deployment commit. CI green.
- Every run prints progress (batch/50-iteration intervals — no silent scripts).
- **Two-reversal rule:** if successive analyses flip a conclusion twice, stop and report "contradictory results, needs deeper method work" — do not present the latest flip as the answer.
- Final response: `✅ DONE` proof-of-work (correctness review warranted — this touches financial calculation and model parameters) or `⏸ HANDOFF` with per-experiment status. Include a one-table summary: hypothesis → verdict → deployed? → expected $ impact at 10k shares/ticker.

## Explicitly out of scope this week

Spending the Databento credits (that's Phase 3 of the roadmap — the stress purchase should validate the NEW buyback rule, not the old one). Directional prediction of any kind. OTM% re-grid-searches on the already-mined year. SPX/index strategies. Anything levered or naked — structurally forbidden for this account.
