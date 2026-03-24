---
title: "Experiment 005: Straddles on Dad's Stocks Also Fail"
date: 2026-03-24
experiment: 005
hypotheses: [H44]
status: completed
finding: "Every variant of straddles and strangles on Dad's individual stocks loses money (263-387 trades, statistically significant). VRP harvesting via options on individual stocks is not viable after real-world friction, regardless of structure."
---

# Experiment 005: Straddles on Dad's Stocks Also Fail

**Date:** March 24, 2026
**Data:** Real Databento OHLCV for AAPL, DIS, TXN, TMUS, KKR

## Context

Experiments 001-004 tested put spreads. All failed or were marginal. Sinclair ranks straddles above spreads for VRP harvesting. This experiment tested whether removing the expensive long-put leg (switching from spreads to straddles) fixes the economics.

## Results

| Variant | Trades | Win% | Total P&L | Sharpe | Max DD |
|---|---|---|---|---|---|
| Weekly straddle, TP=50% | 263 | 56.7% | **-$14,396** | -1.35 | -16.6% |
| Weekly straddle, TP=25% | 373 | 54.2% | -$13,922 | -1.39 | -16.5% |
| Weekly straddle, hold | 255 | 58.0% | -$13,925 | -1.30 | -16.2% |
| Monthly straddle, TP=50% | 83 | 48.2% | -$11,501 | -1.04 | -14.6% |
| Weekly strangle 5% OTM | 387 | 56.8% | **-$6,236** | **-0.75** | -9.4% |
| AAPL+DIS liquid only | 85 | 57.6% | -$7,958 | -1.48 | -8.9% |

**All variants lose money.** All Sharpes deeply negative. All holdouts fail. All bootstraps show >86% probability of negative returns.

## Why Straddles Fail Too

Same root cause as spreads: bid-ask friction on individual stock options consumes the VRP edge.

- Straddles collect more premium (both sides) but also face more friction (buying back both legs)
- AAPL lost $4K-7K on straddles despite being the most liquid stock option
- KKR was the only profitable ticker (+$232 to +$2,033) — on straddles but not spreads — likely due to higher IV

## The Definitive Conclusion

**VRP harvesting via options on individual stocks is NOT viable after real-world friction, regardless of structure (spreads, straddles, strangles, weekly, monthly).**

This has been tested on 1,500+ real trades across 5 experiments with real Databento option prices. The result is consistent and statistically significant.

## What IS Viable

Experiment 006 pivoted to the RIGHT problem: Dad already sells covered calls profitably. He doesn't need a VRP harvesting strategy. He needs a monitoring system to tell him when to buy back the calls he's already sold, so he never gets called away again (the MSFT $400K lesson).
