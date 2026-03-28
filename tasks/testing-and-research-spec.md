# Options Tool: Testing Infrastructure + Research Process Spec

**Date:** 2026-03-28
**Status:** Draft — awaiting approval before implementation
**Reference:** Adapted from sports-dashboard/tasks/testing-and-infra-spec.md

---

## Why we're doing this

We found that our analysis-to-deployment pipeline has no structural guardrails. Experiment 013 analyzed paper trade losses, proposed parameter changes, and deployed them directly to production — bypassing walk-forward validation. Experiment 014 (the validation) proved 2 of 3 recommendations were wrong. Meanwhile, the paper trade scoring had a bug (-118,671% total P&L from uncapped loss percentages). We have 51 tests for position_monitor.py but zero tests for the financial math that determines paper trade outcomes, scoring accuracy, and strategy recommendations.

One important caveat: all backfilled paper trades use BSM pricing (not real market prices). Every BSM-based number carries that uncertainty. Real paper trades (from the daily logger using live Yahoo Finance chains) are more reliable.

---

## How the two plans fit together

Plan A builds tests protecting all financial math. Plan B formalizes the research pipeline so analysis can never skip validation again. Plan A comes first because Plan B changes how experiments flow into production, and we need tests protecting the math before we restructure the process.

The sequence:

1. **Plan A phases 1-3** — Write unit tests for scoring, pricing, and strategy validation logic.
2. **Plan B work stream 1** — Formalize the experiment pipeline with approval gates.
3. **Plan A phase 4** — Add tests to CI so they run on every push.
4. **Plan B work streams 2-3** — Shadow mode for parameter proposals, automated walk-forward in the approval gate.

---

# Plan A: Testing Foundation

## Phase 1: Setup

We already have pytest and a CI workflow (`.github/workflows/test.yml`). Extend it.

Create fixture factories — helper functions that generate realistic test data (paper trade records, position alerts, option chain snapshots, stock price histories). No API calls in any test.

## Phase 2: Unit tests for critical financial logic

Seven test areas covering every piece of math that determines paper trade outcomes and strategy recommendations.

**Paper trade scoring** (highest priority). The scorer (`score_paper_trades.py`) determines P&L for every paper trade. Test: expired OTM = +100% P&L, expired ITM with cap = -100% P&L, partial ITM scenarios, zero premium edge case. The -118,671% bug happened because losses weren't capped. A test would have caught this immediately.

**BSM pricing** (used in backfill). The backfill uses `bsm_call()` to estimate premiums. Test: known option price for given S/K/T/r/sigma, zero time = intrinsic value, negative result impossible, ATM options approximately equal for calls/puts. Verify against py_vollib for reference values.

**ITM probability table** (position_monitor.py). Already tested (51 tests) but add: boundary conditions between buckets, ensure every bucket is reachable, verify table sums are monotonic (higher moneyness = higher probability).

**Walk-forward splitter.** Test: train/test split produces non-overlapping date ranges, train always precedes test, correct proportions (67/33), edge case with very short data.

**Strategy validation logic.** Test: loss rate calculation matches hand-computed example, win rate + loss rate = 100% for scored trades, pattern detection finds known patterns in test data.

**Copilot alert accuracy.** Given a known stock price path and a known covered call position, does `assess_position()` fire CLOSE_NOW at the correct time? Simulate 3-4 known scenarios (stock rallies through strike on day 15, stock stays flat, stock drops).

**Paper trade backfill.** Test: backfill produces one trade per ticker per interval, uses correct historical date (not today's date — the bug we found), BSM premium > 0 for reasonable inputs.

## Phase 3: Property-based tests

Use hypothesis (Python property-based testing) to generate random inputs and verify invariants.

**Scoring invariants.** For any premium > 0 and any outcome price >= 0: P&L is between -100% and +100%. Expired OTM always gives +100%. P&L = 0 only when outcome_price = premium exactly.

**Alert invariants.** For any stock price and strike: ITM (stock > strike) never returns SAFE or WATCH. OTM > 10% with DTE > 30 always returns SAFE (unless ex-div/earnings). EMERGENCY requires both ITM and ex-div within 3 days.

**Strategy invariants.** For any OTM% between 0 and 0.30: loss count + win count = total scored. Win rate is between 0% and 100%. Higher OTM% always produces fewer or equal losses on the same price path.

## Phase 4: CI pipeline

Extend `.github/workflows/test.yml` to run all new tests. Should take under 10 seconds. Fail the build if any test fails. Add to the daily monitoring workflow as well.

---

# Plan B: Research Pipeline Formalization

## Work Stream 1: Experiment approval gates

Formalize the pipeline that Experiment 014 followed (and Experiment 013 skipped):

**Gate 1: Pre-registration.** Every experiment that could change production parameters MUST have a `README.md` with:
- Hypothesis in plain English
- Pass/fail thresholds (immutable after registration)
- Method (walk-forward split, sample size, metrics)
- What changes if PASS vs FAIL

**Gate 2: Walk-forward validation.** Train on first 67% of data, test on last 33%. The proposed parameter must achieve the pre-registered threshold on the TEST period only. Train-period results are reported but not used for the pass/fail decision.

**Gate 3: One variable at a time.** Each ticker's parameter change is a separate commit with a separate walk-forward result. Never batch multiple tickers into one commit.

**Gate 4: Shadow period.** New parameters run in shadow mode first — paper trade logger uses BOTH old and new parameters for 2 weeks. Compare outcomes before switching production.

**Gate 5: Deployment.** Only after gates 1-4 pass. Commit message must reference the experiment number and the walk-forward test result.

Create `experiments/GATE_TEMPLATE.md` that enforces this structure.

## Work Stream 2: Shadow mode for parameter proposals

When Experiment 013 says "TMUS should be 15% OTM instead of 3%":
1. Don't change `ticker_strategies.py`
2. Instead, add a `shadow_strategies` dict with the proposed parameters
3. The paper trade logger logs BOTH: the production trade AND the shadow trade
4. After 2 weeks, compare: does the shadow outperform production on real data?
5. If yes: go through Gate 2-5 to deploy

This means every analysis finding gets a built-in shadow test before it touches production.

**Files:**
- `ticker_strategies.py` — add `SHADOW_STRATEGIES` dict
- `paper_trade_logger.py` — log shadow trades alongside production trades
- `web/src/app/paper-trades/` — show shadow vs production comparison

## Work Stream 3: Automated walk-forward in approval gate

Create `run_approval_gate.py` that:
1. Reads a proposed parameter change from a JSON file
2. Fetches stock data
3. Runs walk-forward validation automatically
4. Outputs PASS/FAIL with evidence
5. Blocks deployment if FAIL

This is the structural guardrail that makes it impossible to skip validation. The script runs as a GitHub Action before any commit that touches `ticker_strategies.py`.

**Files:**
- `run_approval_gate.py` — NEW
- `.github/workflows/approval-gate.yml` — triggers on changes to ticker_strategies.py

---

## What could invalidate this plan

**BSM-priced paper trades give misleading walk-forward results.** BSM overstates premiums by 7.6x (Experiment 011). Walk-forward on BSM data might pass strategies that fail on real prices. Mitigation: clearly label all BSM results, prioritize real-price paper trades as they accumulate.

**The shadow period is too short.** 2 weeks might not be enough to see losses. Mitigation: require minimum 10 shadow trades before comparison.

**The approval gate is too strict.** 15% loss rate threshold might reject strategies that are profitable net of premium. Mitigation: also track net P&L (premium - losses), not just loss rate.

**Tests find an existing bug in the scorer.** This would mean current paper trade stats are wrong. This is actually the highest-value outcome — finding a real bug before Dad trades real money.

---

## Synopsis

Tests first (protect the scoring math that produced the -118K% bug and every paper trade outcome), then formalize the research pipeline with 5 gates so analysis can never skip validation again. The highest-ROI single item is the paper trade scoring test suite — an uncapped loss there produced nonsensical stats that were live on the app for hours. Shadow mode for parameter proposals prevents future Exp 013-style mistakes structurally, not behaviorally.
