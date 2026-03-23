# Experiment 001: Exit Strategy Optimization for Put Spreads

## Pre-Registration

**Date:** 2026-03-23
**Status:** Pre-registered (results not yet analyzed)
**Author:** Options Edge Finder research pipeline
**Hypotheses:** H30, H31, H32, H33, H34

## Problem Statement

Bull put spreads have asymmetric risk/reward against the seller:
- $10-wide spread, $1.70 credit: max profit $170, max loss $830
- Breakeven win rate: 83%
- GREEN signal win rate: ~80%

**Holding to expiry is expected to LOSE money.** Active exit management is required.

## Hypotheses

### H30: Optimal Take-Profit Level
There exists a take-profit percentage (25-75% of max) that maximizes risk-adjusted returns.
**Pass:** At least one TP level has Sortino > 0.5 AND avg P&L > 0.

### H31: Optimal Stop-Loss Level
A stop-loss at 1.5-2.5x premium collected improves risk-adjusted returns.
**Pass:** At least one SL level improves Sortino vs no stop loss.
**Fail:** All stop-loss levels produce worse results than no stop loss.

### H32: Time-Based Exit (DTE Floor)
Closing at 7 DTE avoids gamma acceleration and improves returns.
**Pass:** DTE floor of 5-14 has higher Sortino than no floor.

### H33: VRP-Based Exit
Closing when VRP flips negative captures the "edge disappearance" signal.
**Pass:** VRP exit improves Sortino by > 0.1 vs no VRP exit.

### H34: Combined Exit Strategy
The optimal combination of all four exit types outperforms any single exit type.
**Pass:** Best combo has Sortino > best single-type exit by > 0.2.

## Method

**Grid search** over:
- Take profit: [25%, 50%, 65%, 75%, 100% (hold to expiry)]
- Stop loss: [1.0x, 1.5x, 2.0x, 2.5x, 3.0x, none]
- DTE floor: [0 (none), 3, 5, 7, 14 days]
- VRP exit: [yes, no]

Total: 300 parameter combinations.

**Data:** 2 years OHLCV for SPY, QQQ, AAPL, MSFT, NVDA, TXN, DIS (7 tickers).

**Simulation:** Daily spread value estimated from stock price path. Credit estimated from IV proxy (RV * 1.2). Slippage of 12% of credit per close.

**Primary metric:** Sortino ratio (penalizes downside, not upside).
**Secondary:** Sharpe, avg P&L, win rate, max drawdown, avg holding period.

**Multiple testing correction:** 300 combos = massive overfitting risk. Apply Deflated Sharpe Ratio with n_trials=300.

## Failure Criteria

If NO parameter combination produces Sortino > 0.5 after DSR correction, the put spread strategy is not viable with this exit framework. Consider alternative structures.

## Caveats (pre-registered)

1. Spread value estimation is simplified (not real option prices)
2. IV proxy (RV * 1.2) may not reflect actual option chain pricing
3. Slippage model is constant 12% — real slippage varies by name and conditions
4. Grid search on 300 combos risks finding noise — DSR correction essential
5. 2 years of data may not include enough market regimes (no 2020-style crash)
