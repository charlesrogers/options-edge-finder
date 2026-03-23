# Experiment 002: Put Spread Backtest with Real Option Prices

## Pre-Registration

**Date:** 2026-03-23
**Status:** Pre-registered (results not yet computed)
**Hypotheses:** H35, H36, H37, H38, H39

## Primary Question

Does the bull put spread strategy with 25% take-profit exit produce positive risk-adjusted returns when priced with REAL option market data (Databento OHLCV)?

## Data

3.6 million rows of real option OHLCV from Databento:
- AAPL: 2,211,521 rows (Mar 2025 - Mar 2026)
- DIS: 593,053 rows (Mar 2025 - Mar 2026)
- TXN: 299,027 rows (Mar 2025 - Mar 2026)
- TMUS: 201,261 rows (Mar 2025 - Mar 2026)
- KKR: 280,909 rows (Mar 2023 - Mar 2026, 3 years)
- GOOGL: 37,990 rows (1 week, validation only)

Stock OHLCV: 2 years per ticker from Yahoo Finance (free).

## Hypotheses

### H35: Strategy is profitable with real prices
Sell 5% OTM put, buy 10% OTM put, enter on GREEN signal, exit at 25% take-profit or 5 DTE. 15% bid-ask haircut on entry and exit.
- **Pass:** avg P&L > $0, Sharpe > 0.3
- **Fail:** avg P&L <= $0

### H36: BSM estimates match real prices within 25%
Compare BSM-computed option prices to Databento closes.
- **Pass:** median absolute % error < 25%
- **Fail:** error >= 25% (Experiment 001 was unreliable)

### H37: 25% take-profit is still optimal with real prices
Grid search TP at 25%, 50%, 65%, 75%, 100%.
- **Pass:** 25% TP has highest Sortino
- **Fail:** different TP% is optimal

### H38: Survives holdout validation
Train first 80%, test last 20%.
- **Pass:** holdout Sharpe > 50% of training, holdout P&L > 0
- **Fail:** holdout degrades > 50%

### H39: Survives bootstrap stress test
Resample P&L 1000x.
- **Pass:** 95% CI lower bound for avg P&L > 0, P(ruin) < 5%
- **Fail:** P(ruin) >= 5%

## Method

For each ticker, for each trading day:
1. Compute realized vol, GARCH forecast, VRP, GREEN/YELLOW/RED signal
2. If GREEN: find nearest put strikes in Databento data
3. Net credit = sell_put_close - buy_put_close, with 15% haircut
4. Each day: reprice from real Databento OHLCV
5. Exit at 25% TP, 5 DTE floor, or expiry
6. P&L = haircut_credit - haircut_close_cost

## Pass/Fail Thresholds (pre-registered, immutable)

| Metric | Pass | Fail |
|---|---|---|
| Avg P&L per trade | > $0 | <= $0 |
| Sharpe (annualized) | > 0.3 | <= 0.3 |
| Holdout/Training Sharpe | > 0.50 | <= 0.50 |
| Bootstrap 95% CI lower | > $0 | <= $0 |
| P(ruin) | < 5% | >= 5% |
| BSM vs real error | < 25% | >= 25% |

## If It Fails

- Document honestly
- The put spread strategy is NOT viable with real friction
- Consider: index ETF straddles (Sinclair's preferred), or alternative structure
- We will NOT move goalposts
