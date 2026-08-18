---
title: "Experiment 012: Walk-Forward Validation — Strategies Hold Out-of-Sample [SUPERSEDED]"
date: 2026-03-26
experiment: 012
status: superseded
superseded_by: 022
finding: "SUPERSEDED 2026-08-17 by Exp 022. Every number below was produced by the simulator that measured DTE against datetime.now(), so each observation was evaluated at DTE=0 with ex_div_date=None. Kept as the record of what was believed, not as a result. The re-derivation on the fixed engine is results/022_baseline_rederivation.md. Original finding, no longer supported: 'PASS — 4 of 5 tickers profitable out-of-sample.'"
---

> **⚠️ SUPERSEDED — do not cite these numbers.** Experiment 015 found that
> `assess_position()` computed DTE from the wall clock (fixed in commit `8040440`), which
> invalidated every backtest from Exp 007 to Exp 014, this one included. The baseline was
> re-derived on `experiments/cc_sim.py` in **Exp 022** — see
> `results/022_baseline_rederivation.md`. Nothing here is deleted, because the record of
> what was believed is itself worth keeping.

# Experiment 012: Walk-Forward Validation

**Date:** March 26, 2026
**Method:** Train on first 67% of data, test on last 33%. Find optimal OTM% in training, validate out-of-sample.

## The Question

Experiment 008 found profitable strategies by testing on the FULL dataset. That's in-sample evaluation — the results could be overfit. Do the strategies hold when we properly split train/test?

## Results

| Ticker | Train OTM | Train P&L | Test P&L | OOS Ratio | Pass? |
|---|---|---|---|---|---|
| AAPL | 10% | +$297 | **+$311** | **1.05x** | YES |
| DIS | 3% | +$402 | +$295 | 0.73x | YES |
| TMUS | 3% | +$1,485 | +$493 | 0.33x | YES |
| KKR | 15% | +$469 | +$262 | 0.56x | YES |
| TXN | 10% | +$326 | -$384 | -1.18x | NO |

**4 of 5 tickers profitable out-of-sample. PASS.**

## Key Findings

1. **AAPL is the most robust** — test period actually beats training (1.05x). The conservative 10% OTM strategy works in both periods.

2. **TMUS has the highest absolute P&L** but degrades more out-of-sample (0.33x). Still profitable, but the training-period results overstate real performance.

3. **TXN fails as expected** — Experiment 008 already flagged it as "skip." Walk-forward confirms: TXN is too volatile for covered calls regardless of OTM%.

4. **Walk-forward optimal OTM% differs slightly from full-sample:**
   - AAPL: walk-forward picks 10% (full-sample: 15%)
   - KKR: walk-forward picks 15% (full-sample: 3%)
   - The "best" OTM% shifts between periods, but all tested strategies remain profitable

## What This Means

The strategies from Experiment 008 are real — not overfit to the training data. The specific optimal OTM% may shift over time, but the general approach (sell covered calls with copilot monitoring, per-ticker OTM% between 3-15%) works across both time periods.

**For the product:** We can confidently recommend these strategies to Dad. The walk-forward validation is the strongest evidence yet that the copilot + strategy combination works.

## Verdict: PASS

Out-of-sample P&L is positive for 4/5 tickers (pre-registered threshold: 3+). Strategies validated.

## Reproducibility

```bash
python experiments/012_walk_forward/run.py
```
