---
title: "Experiment 004: Correct Portfolio Backtest — Individual Stock Spreads Are Marginal"
date: 2026-03-24
experiment: 004
hypotheses: [H35, H38, H39]
status: completed
finding: "With correct portfolio-level accounting, put spreads on individual stocks produce Sharpe 0.14-0.18. Positive but below 0.3 threshold. The edge is ~$1-3 per trade after friction — too small to deploy. Sinclair's actual recommendation (index straddles) was never tested."
---

# Experiment 004: The Definitive Individual Stock Backtest

**Date:** March 24, 2026
**Engine:** Portfolio-level daily P&L with correct accounting (fixed cumulative-vs-change bug)

## Critical Bug Fixed

Previous experiments had a P&L accounting error that showed $191K loss on $100K capital — impossible for defined-risk spreads. The bug: daily P&L was computed as cumulative unrealized level, not daily change. After fixing, the real numbers emerged.

## Correct Results

| Variant | Trades | Win% | Total P&L | Sharpe | Max DD |
|---|---|---|---|---|---|
| All 5 tickers, max 3/ticker | 530 | 83.2% | +$1,469 | 0.138 | -6.6% |
| AAPL only, spread, max 3 | 100 | 88.0% | -$294 | -0.058 | -3.1% |
| AAPL only, CSP, max 3 | 101 | 90.1% | -$92 | -0.008 | -9.5% |
| AAPL spread, max 1 | 42 | 90.5% | +$99 | 0.046 | -1.1% |
| AAPL spread, TP=50% | 70 | 81.4% | +$526 | 0.110 | -3.1% |
| AAPL spread, TP=75% | 54 | 77.8% | **+$809** | **0.181** | -2.9% |
| AAPL spread, hold-to-DTE | 41 | 75.6% | +$606 | 0.165 | -2.9% |

**Best variant:** AAPL spread with 75% take-profit, Sharpe 0.181.

## Why Everything Fails the Threshold

Pre-registered pass criteria required Sharpe > 0.3. The best variant is 0.181 — positive but 40% below threshold. The edge is real but tiny:
- Average trade P&L: +$1-3
- Average credit collected: ~$130
- Average slippage (entry + exit): ~$13 (5% × 2)
- Net edge after friction: $3-8 per trade
- But DTE floor losses average -$400+, wiping out 50-100 small wins

## The Fundamental Problem

**Put spreads on individual stocks have the wrong economics for VRP harvesting:**
1. The long put (protection) costs $40-80 per trade — eating most of the VRP edge
2. Individual stock bid-ask spreads (even AAPL) consume 10-30% of credit
3. Single-stock risk means occasional large losses that overwhelm small wins
4. Monthly DTE means only 12 entry points per year per ticker

## What Sinclair Actually Recommends (We Finally Read It Properly)

From "Retail Options Trading" (2024):

> "Stock indices are the products with the most consistent volatility premium. A portfolio of short volatility bets on a group of indices should be the core of a variance premium harvesting strategy."

And on structure:

> Straddles are "most liquid and cheapest to trade... most vega for a given expiration."

**We tested the wrong thing.** Sinclair says: sell STRADDLES on INDICES (SPY/QQQ/IWM), not put SPREADS on individual STOCKS.

| What We Tested | What Sinclair Recommends |
|---|---|
| Put spreads (2 legs) | Straddles (no protection) |
| Individual stocks | Index ETFs (SPY, QQQ, IWM) |
| Monthly (20-30 DTE) | Weekly (5-7 DTE) |
| 1 ticker | 3-5 indices simultaneously |

## Why Index Straddles Might Work

1. **No long-put cost.** Spreads buy overpriced protection. Straddles don't.
2. **SPY bid-ask: $0.01-0.03** vs AAPL $0.10-0.30 vs KKR $0.50+
3. **SPY VRP positive 82% of days** (vs 70% for stocks)
4. **Weekly = 52 trades/year** per index (vs 12 for monthly)
5. **No single-stock risk.** No earnings, no CEO scandals.
6. **Independent of Dad's holdings.** SPY straddles don't touch his stocks.

## Next Steps

Experiment 005: BSM proxy backtest of SPY weekly straddles. Free, immediate, uses the correct engine. If Sharpe > 0.3 on BSM → promising, validate with real data. If < 0.1 → VRP harvesting may not work for Dad's situation at all.
