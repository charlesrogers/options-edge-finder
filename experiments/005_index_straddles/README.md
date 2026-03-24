# Experiment 005: Index Straddles (Sinclair's Actual Recommendation)

## Pre-Registration

**Date:** 2026-03-24
**Status:** Pre-registered
**Hypotheses:** H44, H45, H46
**Motivated by:** Experiments 001-004 tested the WRONG strategy (put spreads on individual stocks). Sinclair recommends straddles on indices.

## Key Difference from Previous Experiments

| Previous (failed) | This experiment |
|---|---|
| Put spread (2 legs, buys protection) | Straddle (sell ATM call + ATM put, no protection) |
| Individual stocks | SPY, QQQ, IWM |
| 20-30 DTE monthly | 5-7 DTE weekly |
| 1 ticker at a time | 3 indices simultaneously |
| Defined risk but high friction | Unlimited risk but minimal friction |

## Method

BSM proxy pricing (ATM options where BSM is most accurate ~14-20% error).
Yahoo OHLCV for stock data (free, 2 years).
Portfolio-level daily P&L using corrected backtest engine.

**CAVEAT:** BSM proxy, not real prices. If Sharpe > 0.3, results are DIRECTIONAL only — must validate with real data before deploying.

## Pass/Fail

| Metric | Pass | Fail |
|---|---|---|
| SPY straddle daily Sharpe | > 0.3 | <= 0.3 |
| 3-index diversified Sharpe | > single-index × 1.5 | No diversification benefit |
| Backwardation filter Sharpe | > unfiltered | No improvement |
