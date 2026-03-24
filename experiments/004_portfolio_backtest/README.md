# Experiment 004: Portfolio-Level Backtest with Correct Methodology

## Pre-Registration

**Date:** 2026-03-23
**Status:** Pre-registered
**Motivated by:** Every previous experiment had a methodological flaw. This experiment fixes the engine before testing strategies.

## Methodology Fixes

| Flaw in Exp 001-003 | Fix in Exp 004 |
|---|---|
| Individual trade P&L | Portfolio daily P&L (sum of all open positions) |
| Arbitrary trade skip (5-20 days) | Every GREEN day, subject to position limits |
| No concurrent positions | Max N positions per ticker, tracked daily |
| Holdout on 8 trades | Holdout on 50+ calendar days |
| Bootstrap on trade P&L | Bootstrap on daily portfolio returns |
| Sharpe on trade list | Sharpe on daily portfolio returns |

## Pass/Fail Thresholds (immutable)

| Metric | Pass | Fail |
|---|---|---|
| Portfolio daily Sharpe (annualized) | > 0.3 | <= 0.3 |
| Portfolio max drawdown | > -20% of capital | <= -20% |
| Holdout daily Sharpe | > 50% of training | <= 50% |
| Bootstrap 95% CI for daily return | > 0 | <= 0 |
| Win rate (individual trades) | > 60% | <= 60% |

## Data
- AAPL, DIS, TXN, TMUS: 1yr Databento real option OHLCV
- KKR: 3yr Databento
- Stock OHLCV: 2yr Yahoo Finance (free)

## If It Fails
- Document honestly
- Consider: is VRP harvesting via options viable AT ALL for retail?
- Or: is the edge real but too small to overcome friction?
