---
title: "Experiment 019b: Backwardation Guard — FAIL on three of four clauses. It helps the two tickers we can measure and hurts the two we cannot."
date: 2026-08-16
experiment: 019b
hypothesis: H22 (pending) / H22a (fail)
status: completed
finding: "H22a FAILS clauses 1, 2 and 4: the guard skips 27.5% of entries (threshold 15%), moves aggregate net P&L by -1.0% (threshold +10%), and fires on up to 13.3% of entry opportunities in backwardation-free years (threshold 5%). Underneath the fail is a real signal: it improves AAPL by +21.6% and DIS by +62.2% — the only two tickers with usable price coverage — and blocks entries whose mean P&L is negative on both. It is not deployable as specified: too coarse, thresholds never tuned, and the regime it exists for (2020) is the data we did not buy."
---

# Experiment 019b — Backwardation Guard (H22 / H22a)

**Verdict H22a: FAIL** (clauses 1, 2, 4). **Verdict H22: PENDING.** **Deployed: nothing.**

Pre-registration: `experiments/019b_backwardation_guard/README.md`, committed before the
data was touched. Engine: `experiments/cc_sim.py`, with the guard expressed as a cc_sim
entry gate ANDed with the production IV-rank gate, so the arms differ in exactly one thing.

## The guard

Suppress **new** call sales when `VIX > VIX3M` (term structure in backwardation) **or**
spot < 0.85 × 60-trading-day high. Both numbers are **arbitrary starting values** from the
spec — nothing here is derived. Existing positions are untouched.

Source: Sinclair & Mack Ch. 10 — the one situation their risk tolerance forbids is selling
into a vol spike with the term structure inverted. Our IV-rank ≥ 50 gate, validated only in
calm regimes, actively encourages exactly that.

## Setup

Real Databento prices over the window we already own. That window is not calm: **24 of its
251 days are in backwardation**, clustered in the April-2025 tariff selloff plus Nov-2025
and Mar-2026. Free `^VIX` / `^VIX3M` daily closes supply the term structure.

## Scoring against the pre-registered clauses

| Clause | Threshold | Measured | Result |
|---|---|---|---|
| 1. Entries skipped | ≤ 15% | **27.5%** | **FAIL** |
| 2. Aggregate net call P&L | ≥ +10% relative | **−1.0%** | **FAIL** |
| 3. Assignments added | 0 | **0** (both arms, all four tickers) | PASS |
| 4. Calm control, backwardation-free years | ≤ ±5% of entries | **13.3%** | **FAIL** |

**H22a FAILS.** The thresholds are the ones fixed in the README before the run and are not
being relaxed now.

## Per ticker — and the split that matters

| Ticker | Missing prices | Baseline net | Guard net | Entries skipped | Δ P&L | Blocked entries: mean P&L |
|---|---|---|---|---|---|---|
| AAPL | **2.5%** | +$127,653 | +$155,251 | 23.2% | **+21.6%** | −$1,200 (20W/3L) |
| DIS | **14.3%** | +$702,791 | +$1,139,760 | 19.1% | **+62.2%** | −$18,207 (5W/19L) |
| TMUS | 44.0% | +$451,984 | +$351,049 | 36.9% | −22.3% | +$2,243 (38W/7L) |
| KKR | 63.7% | +$311,642 | −$68,155 | 28.4% | −121.9% | +$3,453 (79W/20L) |

Dollar totals span every daily cohort × 100 contracts — overlapping positions, not a
tradeable P&L. Read the relative deltas and the blocked-entry column.

The blocked-entry column is the diagnostic that actually answers the question. A gate never
changes a trade it allows, so a paired per-entry comparison between arms is identically
zero and says nothing; what matters is whether the entries it *removed* were good ones. On
AAPL and DIS the guard threw away losers (mean −$1,200 and −$18,207; DIS blocked 19 losers
against 5 winners). On TMUS and KKR it threw away winners.

**The sign of the effect lines up exactly with data quality.** The guard helps both tickers
with usable coverage and hurts both tickers where 44–64% of daily repricing lookups have no
bar at all. That is suggestive, not conclusive — and it is why clause 2 fails on the
all-ticker aggregate (−1.0%) while the aggregate excluding KKR is +28.4%.

## Which leg is doing the work

The guard is `backwardation OR drawdown`. Each leg alone (diagnostic arms, not
pre-registered clauses):

| Ticker | Backwardation leg: skipped / Δ P&L | Drawdown leg: skipped / Δ P&L |
|---|---|---|
| AAPL | 17.2% / **+39.6%** | 18.2% / +33.2% |
| DIS | 15.1% / **+35.7%** | 15.1% / +65.5% |
| TMUS | 13.9% / −53.6% | 23.8% / +30.5% |
| KKR | 8.8% / +67.9% | 26.3% / −129.9% |
| Aggregate ex-KKR | +4.6% | +50.0% |

On the two well-measured tickers **both legs help**, and the backwardation leg — the one
with the theory behind it — is the stronger of the two on AAPL (+39.6%). On the two
badly-measured tickers the legs disagree with each other and with everything else.

An earlier run of this experiment on a different simulator produced the opposite leg
ordering (backwardation hurting everywhere). Per CLAUDE.md's two-reversal rule: **the leg
comparison is not settled and must not be used to pick a leg to ship.** What is stable
across both runs is that the composite guard is far too coarse.

## Why clause 4 failed

`spot < 85% of the 60-day high` is not a crash detector. It is a "this stock is down"
detector, and it stays on for months after a drawdown. In **2023 — a year with zero
backwardation days** — it blocked 2 of 15 entry opportunities for DIS and 2 of 15 for KKR.

| Ticker | 2021 blocked | 2023 blocked |
|---|---|---|
| AAPL | 0.0% | 6.7% |
| DIS | 6.7% | 13.3% |
| TMUS | 13.3% | 0.0% |
| KKR | 0.0% | 13.3% |

The backwardation leg contributed **zero** blocks in every calm ticker-year; the drawdown
leg contributed all of them. A gate that fires when there is nothing to guard against is
the definition of one that will misbehave in production, and this control condition exists
precisely to catch that.

## H22 proper — still open

The 2020 and 2022 clauses of H22 need real option prices for those years. They were not
purchased (no API credits this session), so **H22 is recorded PENDING** — not passed, not
failed. The owned window contains a vol spike that *recovered fast*, which is the regime in
which selling into backwardation works. 2020 is the regime in which it is supposed not to.
This experiment cannot tell those apart.

## What should happen next

Do **not** deploy the guard as specified. The follow-up worth pre-registering, with its own
immutable thresholds and its own control condition:

- the backwardation leg alone (it needs no per-ticker tuning and it never fired in the calm
  control), evaluated on AAPL and DIS only,
- with the 2020 arm bought, because that is the claim,
- and an entry-skip budget that matches the 15% the spec asked for rather than the 27% this
  version spends.

## Data quality

Missing daily repricing lookups, baseline arm: AAPL 2.5%, DIS 14.3%, TMUS 44.0%, KKR 63.7%.
Trades that never saw a single real quote after entry: AAPL 0, DIS 0, TMUS 2, KKR 61. Every
miss carries the previous price forward and is counted.

## Verdicts

- **H22a: FAIL** — clauses 1, 2 and 4.
- **H22: PENDING** — needs 2020/2022 option prices.

## Reproducibility

```bash
python experiments/019b_backwardation_guard/run.py
```
Raw output: `experiments/019b_backwardation_guard/results.json`.
