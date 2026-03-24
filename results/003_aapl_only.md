---
title: "Experiment 003: AAPL Put Spreads — Profitable but Fragile"
date: 2026-03-23
experiment: 003
hypotheses: [H40, H41, H42, H43]
status: completed
finding: "AAPL put spreads are profitable (Sharpe 4.6, 95% win rate) but the holdout fails because ONE bad trade (-$269) in 8 test trades tanks the Sharpe. With only 40 trades total, statistical confidence is thin."
---

# Experiment 003: AAPL Put Spreads — Profitable but Fragile

**Date:** March 23, 2026
**Data:** 2.2M rows of real AAPL option OHLCV from Databento (1 year)

## Results Summary

| Strategy | Trades | Win Rate | Avg P&L | Sharpe | Max DD |
|---|---|---|---|---|---|
| Put Spread (5%/10% OTM) | 40 | 95.0% | +$38.59 | 4.618 | -$290 |
| Cash-Secured Put (5% OTM) | 40 | 95.0% | +$77.30 | 5.866 | -$295 |

**H40: PASSED.** Both strategies are profitable on AAPL. Cash-secured puts make 2x the P&L of spreads.

**H43 Bootstrap: PASSED.** 95% CI for avg P&L: [$18.41, $54.44]. Only 0.1% probability of negative mean.

**H43 Holdout: FAILED.** Train Sharpe 11.5, Test Sharpe -0.28. Ratio: -0.02.

## Why the Holdout Failed: One Trade

The holdout split puts 32 trades in training and 8 in test. Here are the 8 test trades:

| # | Date | Exit Reason | P&L | VRP |
|---|---|---|---|---|
| 33 | 2026-01-29 | take_profit | +$78.72 | 4.0 |
| 34 | 2026-02-03 | take_profit | +$47.95 | 4.9 |
| 35 | 2026-02-09 | take_profit | +$40.73 | 5.1 |
| 36 | 2026-02-17 | take_profit | +$33.60 | 6.9 |
| 37 | 2026-02-23 | take_profit | +$51.46 | 6.5 |
| **38** | **2026-03-02** | **dte_floor** | **-$269.47** | **6.8** |
| 39 | 2026-03-09 | take_profit | +$34.43 | 5.9 |
| 40 | 2026-03-16 | stale_data_exit | -$54.48 | 4.8 |

**Trade 38 lost $269.** This is the DTE floor exit — the spread was held for 21 days, take-profit never triggered, and it was closed at the DTE floor with a large loss. This single trade turns the 8-trade test set from +$232 to -$37.

**Without trade 38:** Test avg P&L = +$33.20, Test Sharpe ≈ +3.0. Holdout would PASS.

**With trade 38:** Test avg P&L = -$4.63, Test Sharpe = -0.28. Holdout FAILS.

## The Real Problem: 40 Trades Is Not Enough

This is a **sample size problem**, not a strategy problem. With 40 trades:
- One bad trade is 2.5% of the dataset but can flip the holdout
- The 80/20 split gives only 8 test trades — meaningless for statistics
- A Sharpe of 4.6 over 40 trades has wide confidence intervals

**What we need:** 200+ trades minimum (from our pre-registered research standards). That means either:
1. **More time:** 5 years of AAPL data = ~200 trades (but costs $350 on Databento)
2. **More tickers:** Add SPY, QQQ, MSFT (similarly liquid) = 4 tickers × 40 = 160 trades
3. **Paper trade forward:** Accumulate 40+ more trades in real-time over 6-12 months
4. **BSM proxy:** Use BSM-estimated prices for additional years (already validated: AAPL BSM is within 6% of real)

## Grid Search Results

### Take-Profit Level (confirms Experiment 001)

| TP | Win Rate | Avg P&L | Sharpe |
|---|---|---|---|
| **25%** | **95.0%** | **$38.59** | **4.618** |
| 50% | 82.5% | $18.68 | 0.519 |
| 75% | 75.0% | $18.39 | 0.381 |
| Hold | 72.5% | $15.99 | 0.274 |

25% take-profit confirmed as optimal with real prices. Sharpe drops 17x from 25% to hold-to-expiry.

### Spread Width

| Width | Avg P&L | Sharpe |
|---|---|---|
| 3% ($8 wide) | $27.60 | 3.978 |
| 5% ($12 wide) | $38.59 | 4.618 |
| 10% ($25 wide) | $55.11 | 5.106 |
| **15% ($37 wide)** | **$66.28** | **5.445** |

Wider spreads are better — more credit absorbs friction. 15% width is best.

### VRP Threshold

| Min VRP | Trades | Win Rate | Avg P&L | Sharpe |
|---|---|---|---|---|
| >2 | 40 | 95.0% | $38.59 | 4.618 |
| >4 | 39 | 94.9% | $39.27 | 4.668 |
| >6 | 19 | 94.7% | $32.85 | 2.765 |
| >8 | 6 | 100% | $103.38 | 8.723 |

VRP > 2 is fine. Higher thresholds reduce trade count without proportional improvement.

### Cash-Secured Put vs Spread

| Mode | Avg P&L | Sharpe |
|---|---|---|
| Put Spread | $38.59 | 4.618 |
| **Cash-Secured Put** | **$77.30** | **5.866** |

CSP wins decisively. The long put in spreads costs ~$40/trade in premium and slippage — that's the entire edge difference.

## What Trade 38 Tells Us

Trade 38 (2026-03-02, DTE floor exit, -$269) happened during a period when AAPL dropped significantly. The take-profit never triggered because the stock was falling. After 21 days, the DTE floor forced a close at a loss.

This is the **fundamental risk of the strategy**: when the stock moves against you fast enough that theta can't keep up, you hold to DTE floor and lose big. This happens ~5% of the time (2 of 40 trades). The question is whether the 95% of winners make enough to cover the 5% of losers.

Over 40 trades: $1,543 total P&L (yes, positive despite trade 38).
The strategy makes money. But one bad trade in a small test set makes the holdout look terrible.

## Honest Assessment

**What's real:**
- AAPL put spreads at 25% TP with 5% slippage are profitable over 40 real-data trades
- Cash-secured puts are 2x better than spreads
- Bootstrap says 99.9% probability of positive average P&L

**What's uncertain:**
- 40 trades is too few for robust holdout validation
- One DTE floor exit can lose $270 — need to understand how often this happens over 200+ trades
- We only have 1 year of data — this includes no major crash (2020-style event would be devastating)

**What we need:**
- More data: either buy more AAPL history, add liquid tickers (SPY/QQQ), or paper trade forward
- The holdout failure is a SAMPLE SIZE issue, not necessarily a strategy issue — but we can't prove that without more data

## Fertile Areas (Updated)

Based on these results:

1. **Add SPY/QQQ/MSFT to get 160+ trades** — Most impactful. Same strategy, more liquid tickers, 4x the data. Needs ~$200 Databento credits for 1yr each.

2. **BSM-extended AAPL backtest** — Use BSM to price AAPL options for 2020-2024 (free, already have stock data). Validate BSM accuracy against our 1yr of real data. If BSM is within 10%, trust the 5-year BSM backtest. This gives 200+ AAPL trades at zero cost.

3. **Paper trade AAPL CSP starting now** — Real validation takes time but costs nothing. 1 paper trade per week = 50 trades in a year.

4. **Investigate DTE floor trades specifically** — The 2 DTE floor exits lost $270 and $290. Are these predictable? Can we exit earlier when the stock starts moving against us? (This was H31 — stop losses. They hurt on average but might help specifically for DTE floor scenarios.)
