---
title: "Experiment 022: Baseline Re-derivation — H25 FAILS, and TMUS/KKR's profit turns out to be a repricing artefact"
date: 2026-08-17
experiment: 022
hypothesis: H25
status: completed
finding: "FAIL, 3 of 4 tickers. The deployed expected_pnl values overstate the corrected ones by 66-68% for DIS and TMUS and 18% for KKR; only AAPL survives its tolerance. The larger finding is not in the hypothesis: when the sample is restricted to trades whose exit price was a REAL Databento print, TMUS goes from +$151/yr to -$81/yr per contract and KKR from +$316/yr to -$88/yr. Their overlay profit is made of carried-forward prices. AAPL (99% real fills) does not move at all. The pre-registered coverage rule demoted exactly those two tickers to probation before any of this was visible."
---

# Experiment 022 — Baseline Re-derivation (H25)

**Pre-registered:** `experiments/022_baseline_rederivation/README.md`, commit `01c40bf`,
pushed 2026-08-17T21:56:29Z — before this experiment's `run.py` existed.
**Engine:** `experiments/cc_sim.py` (real `as_of`, real ex-dividend dates, simulated
assignment, one cohort per trading day). Real Databento OPRA prices. No money spent.

## The question

Every per-ticker number the product publishes — `expected_pnl`, `expected_win_rate`,
`expected_trades`, and `results/012_walk_forward.md` — came from the simulator that
measured DTE against `datetime.now()`. Every historical observation in Exps 007–013 was
evaluated at DTE = 0 with `ex_div_date=None`. Those numbers are live on the Sell tab as
"Expected P&L/yr per contract" and "Win Rate, from Experiment 008 backtest on real data".

H21 — the reason to spend $125 on stress-year option data — compares stress years to those
numbers. So this had to run first.

## H25 verdict: **FAIL** (3 of 4 tickers outside tolerance)

Median of 25 staggered sequential chains, production settings, production IV-rank ≥ 50 gate,
production copilot, slippage 0.

| Ticker | Deployed `expected_pnl` | Corrected (median, $/contract/yr) | Rel. error | Deployed win rate | Corrected | Δ | Within tolerance? |
|---|---:|---:|---:|---:|---:|---:|---|
| AAPL | $351 | **$299** [−739 … 389] | −15% | 100% | **91.7%** | −8.3pp | ✅ both |
| DIS | $822 | **$267** [51 … 590] | **−68%** | 71% | **80.0%** | +9.0pp | ❌ P&L |
| TMUS | $447 | **$151** [−99 … 976] | **−66%** | 89% | **92.3%** | +3.3pp | ❌ P&L |
| KKR | $386 | **$316** [279 … 351] | −18% | 100% | **63.3%** | **−36.7pp** | ❌ win rate |
| *TXN (control, tier=skip)* | *$0* | *−$2,003* [−2,617 … −1,138] | — | *0%* | *50.0%* | — | *not gating* |

Tolerances were ±25% relative and ±10pp, fixed before the run. AAPL passes both. Nothing
was moved afterwards.

The bracketed range is the min–max across the 25 start-date offsets and is the number that
deserves the most attention: AAPL's median year is +$299 and its worst start date is
−$739, because a single −$970 trade lands inside some chains and not others. With ~13
trades a year, **which Tuesday you start on matters more than most parameter choices.**

## The finding that was not in the hypothesis: real fills vs carried-forward prices

`cc_sim` carries the last known option price forward when Databento has no print for that
symbol that day, and counts every occurrence. Restricting to trades whose **exit** was
either a settlement (expiry / early exercise, priced off the stock) or a genuine print on
the exit date:

| Ticker | Repricing coverage | Real-fill exits | Annualised $/contract, all trades | Annualised $/contract, real fills only |
|---|---:|---:|---:|---:|
| AAPL | 97.5% | 98/99 (99.0%) | $299 | **$299** (unchanged) |
| DIS | 85.7% | 97/126 (77.0%) | $267 | **$204** |
| TMUS | 56.0% | 90/122 (73.8%) | $151 | **−$81** |
| KKR | 36.3% | 248/388 (63.9%) | $316 | **−$88** |
| *TXN* | *84.2%* | *97/120 (80.8%)* | *−$2,003* | *−$2,282* |

**TMUS and KKR change sign.** Their positive overlay P&L is not a market result; it is what
happens when a buyback is paid at a price that was last printed days earlier. This is the
third independent time TMUS and KKR have flipped sign (twice between simulators in the
Phase 3 session, now once between fill definitions). AAPL, which has essentially complete
data, does not move by a single dollar.

The pre-registered deployment rule demoted exactly these two tickers to `probation` on a
coverage threshold fixed **before** the run and before this table existed.

## Regime luck, measured

Per calendar half-year of entry (retention = net ÷ gross premium):

| Ticker | Worst half | Best half | Swing |
|---|---|---|---|
| AAPL | 2025H1 −8.5% | 2025H2 +67.1% | 76pp |
| DIS | 2025H1 −77.9% | 2026H1 +92.8% | **171pp** |
| TMUS | 2026H1 −127.1% | 2025H2 +78.0% | **205pp** |
| KKR | 2024H2 −25.7% | 2026H1 +78.4% | 104pp |

Exp 015 measured 40–180pp retention swings between halves and warned that a point estimate
measures regime luck. Confirmed, with one window worse than that range. Any single-number
claim about this strategy's income is a claim about which six months you looked at.

## Assignments

**Zero**, across every ticker, every chain, every half-year — 855 simulated positions,
including 61 KKR positions that never saw a single real quote after entry. The tri-fold
goal's first clause (never get called away) is the one thing in this system that has
survived every correction. Note the engine simulates both expiry assignment and rational
early exercise into a dividend; it is not inferring assignment the way Exp 008/009 did.

## What this means at Dad's size (10,000 shares/ticker)

| | AAPL | DIS | TMUS | KKR* | **Total/yr** |
|---|---:|---:|---:|---:|---:|
| What the app claims today | $35,100 | $82,200 | $44,700 | $2,702 | **$164,702** |
| Corrected, all trades | $29,900 | $26,700 | $15,100 | $2,213 | **$73,913** |
| Corrected, real fills only | $29,900 | $20,400 | −$8,100 | −$618 | **$41,582** |

*KKR at its Exp 021 liquidity cap of 7 contracts, not 100.

Read the bottom row as an order of magnitude, not a forecast: one year, one favourable
regime, chain medians whose spreads are wider than the differences between rows. The point
is the direction of the correction — **the product has been claiming roughly 4× what the
fixed engine measures on real fills** — not the precision of the number.

## Spec directive 3 — DTE-bug blast radius (verified, not assumed)

| Artefact | Verdict |
|---|---|
| Exp 006 assignment-probability table (`ITM_PROBABILITY`, 145,099 obs) | **Clean.** A hardcoded literal; `lookup_itm_probability(pct_from_strike, dte)` takes DTE as an argument, never calls `assess_position()`, never reads the wall clock. **Caveat:** the table is fine, but every backtest that consumed it *through* `assess_position()` asked it for `dte=0`. |
| Exp 014 stock-close walk-forward (the evidence for every deployed OTM% and for GOOGL's probation) | **Clean.** `experiments/014_validated_param_update/run.py` does not import `position_monitor`, never calls `assess_position()`, and never reads the wall clock. |

Both were *believed* independent. They now are *known* independent. The deployed strike
distances therefore stand on evidence the bug never touched.

## Deployed (pre-registered rules only)

1. `expected_pnl` / `expected_win_rate` / `expected_trades` replaced with the corrected
   medians for **DIS, TMUS, KKR** — the three tickers that failed their tolerance. One
   commit each. AAPL's fields are left untouched because it passed, exactly as
   pre-registered; only the English claim in its note ("never loses") is corrected, since
   the corrected loss rate is 8.3% and the worst single trade is −$971.
2. **TMUS and KKR demoted to `probation`** — repricing coverage 56.0% and 36.3%, both under
   the 70% floor fixed in advance. `probation` is Exp 021's badge: we looked, but with a
   weaker instrument. No parameters change. No ticker was promoted.
3. `results/012_walk_forward.md` marked superseded, not deleted — it is the record of what
   was believed.

## What this does NOT license

The $125 purchase is now unblocked *for AAPL and DIS*. It is not clear that TMUS stress
data can answer anything: at 44% missing repricing in 2025–26, a 2020/2022 TMUS pull would
produce a verdict with the same defect as the numbers above. The revised purchase order
(AAPL 2020 first) is confirmed by this experiment, and TMUS's position at the back of that
queue should probably become "not at all."

## Reproduce

```bash
python3 experiments/022_baseline_rederivation/run.py   # ~6 min, all data local
```

Raw output: `experiments/022_baseline_rederivation/results.json`.
