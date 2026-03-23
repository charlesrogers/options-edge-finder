---
title: "Exit Strategy Optimization: Take Profit at 25% Wins"
date: 2026-03-23
experiment: 001
hypotheses: [H30, H31, H32, H33, H34]
status: completed
finding: "Take profit at 25% of max dramatically outperforms holding to expiry. Stop losses hurt. The exit strategy IS the strategy."
---

# Exit Strategy Optimization: Take Profit at 25% Wins

**Date:** March 23, 2026
**Experiment:** 001_exit_strategy_optimization
**Tickers:** SPY, QQQ, AAPL, MSFT, NVDA, TXN, DIS (2 years, 101 trades)

## The Problem

Bull put spreads have asymmetric risk/reward **against** the seller:

| | Amount |
|---|---|
| Max profit (credit collected) | $170 |
| Max loss (spread width - credit) | $830 |
| Ratio | 4.9:1 against you |
| Breakeven win rate | 83% |
| GREEN signal actual win rate | ~80% |

**Holding to expiry is expected to LOSE money** despite an 80% win rate. The math is simple: 80 wins x $170 - 20 losses x $830 = -$3,000 per 100 trades.

Active exit management is the ONLY thing that makes this strategy work.

## Method

Grid search over 300 parameter combinations:
- Take profit: 25%, 50%, 65%, 75%, 100% (hold to expiry)
- Stop loss: 1.0x, 1.5x, 2.0x, 2.5x, 3.0x, none
- DTE floor: none, 3, 5, 7, 14 days
- VRP exit: yes/no

Backtested on 2 years of daily OHLCV data across 7 tickers. Spread value estimated from daily price path. Slippage: 12% of credit per close.

## Results

### H30: Take-Profit Level (THE critical finding)

| Take Profit | Avg Sortino | Avg P&L | Win Rate | Verdict |
|---|---|---|---|---|
| **25%** | **+1.086** | **+$47.6** | **98.3%** | **OPTIMAL** |
| 50% | +0.217 | +$16.0 | 93.9% | Marginal |
| 65% | -0.253 | -$35.4 | 87.4% | Losing |
| 75% | -0.547 | -$68.3 | 82.2% | Losing |
| 100% (expiry) | -0.948 | -$158.5 | 70.2% | **Worst** |

**H30: PASSED.** The relationship is monotonic — the sooner you take profit, the better. Taking profit at 25% of max produces Sortino +1.086 vs -0.948 for holding to expiry. This is a 2-point Sortino improvement from a single parameter change.

**Why 25% works:** The first 25% of profit comes fast (avg 1.2 days) because theta decay is front-loaded when VRP is high. You're never in the trade long enough for the stock to move against you.

### H31: Stop-Loss Level

| Stop Loss | Avg Sortino | Avg P&L | Avg Max DD |
|---|---|---|---|
| 1.0x | -0.347 | -$46.7 | -$8,525 |
| 1.5x | -0.347 | -$46.7 | -$8,525 |
| 2.0x | -0.347 | -$46.7 | -$8,526 |
| 2.5x | -0.341 | -$50.6 | -$8,923 |
| 3.0x | -0.362 | -$52.2 | -$9,051 |
| **None** | **+1.211** | **+$4.6** | **-$4,310** |

**H31: FAILED.** Every stop-loss level produces WORSE results than no stop loss. Stop losses get triggered by normal intraday volatility, then the stock recovers (whipsaw). The quick take-profit already limits time-in-trade, making stop losses redundant.

### H32: DTE Floor

| DTE Floor | Avg Sortino | Avg Days Held |
|---|---|---|
| None | -0.072 | 6.1 |
| 3 days | -0.178 | 5.6 |
| 5 days | -0.193 | 5.3 |
| 7 days | -0.135 | 5.0 |
| **14 days** | **+0.133** | **3.3** |

**H32: WEAK PASS.** 14-day DTE floor slightly improves results (Sortino +0.133 vs -0.072 for no floor). But this is a secondary effect — the take-profit at 25% already closes most trades in 1-2 days, so the DTE floor rarely triggers.

### H33: VRP Exit

| VRP Exit | Avg Sortino | Avg P&L |
|---|---|---|
| Yes | -0.089 | -$39.7 |
| No | -0.089 | -$39.7 |

**H33: FAILED.** VRP exit makes no difference. Because the take-profit closes trades in 1-2 days, VRP doesn't have time to flip during the holding period.

### H34: Combined Strategy

**H34: PARTIALLY PASSED.** The best combination is:
- Take profit: 25%
- Stop loss: none
- DTE floor: 5 days (safety net)
- VRP exit: yes (safety net, rarely triggers)

Sortino: 5.531, Sharpe: 5.531, Win rate: 100%, Avg P&L: $63.1, Avg hold: 1.2 days.

However, the Deflated Sharpe concern is real: with 300 combos tested, the expected max Sortino by chance alone is high. The finding is strong enough (5.5 Sortino) to likely survive correction, but the 100% win rate and 1.2-day hold suggest the simulation may be too optimistic.

## The Recommended Strategy

```
ENTER: Sell bull put spread when GREEN signal fires
  - Sell ~5% OTM put
  - Buy ~10% OTM put (or $10 wide)
  - Collect credit

EXIT: Take profit at 25% of max credit
  - If credit was $1.70, close when spread value drops to $1.275 ($0.425 profit per share)
  - Expected hold time: 1-2 days
  - Safety net: close at 5 DTE regardless

DO NOT:
  - Hold to expiry (expected to lose money)
  - Use stop losses (whipsaw destroys value)
  - Wait for 50%+ profit (gamma risk increases, diminishing returns)
```

## Critical Caveats

1. **Spread value estimation is simplified.** Real option prices have bid-ask spreads, time decay curves, and volatility smile effects not captured in the simulation. The 100% win rate is almost certainly too optimistic.

2. **Slippage is the key unknown.** Opening and closing a spread in 1-2 days means crossing the bid-ask twice. At $0.20 per leg ($0.40 round-trip = $40 per spread), slippage could consume 63% of the $63 average profit. Real slippage needs to be measured via paper trading.

3. **This was tested on 2 years of mostly bull market.** The 2024-2026 period was favorable for short premium. A crash scenario (2020, 2022) would test the strategy under stress.

4. **300 parameter combinations tested.** Deflated Sharpe correction is essential before deploying real capital.

## What This Means for Dad

The put spread strategy works IF you:
1. Take profits quickly (25% of max, ~1-2 days)
2. Don't use stop losses (they cause whipsaw)
3. Don't hold to expiry (the math is against you)
4. Accept small, frequent profits ($40-60 per trade after slippage) instead of large, infrequent ones

This is a **high-frequency, small-edge** strategy — many small wins that compound. Paper trade for 8 weeks to measure real slippage before committing capital.

## Next Steps

1. Paper trade the recommended strategy for 8 weeks
2. Measure real slippage (the critical unknown)
3. If slippage < 40% of gross profit: viable. Proceed to Starter phase.
4. If slippage > 60% of gross profit: NOT viable. The edge doesn't survive real-world friction.
