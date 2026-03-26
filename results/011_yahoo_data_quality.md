---
title: "Experiment 011: Yahoo Finance Option Data Quality"
date: 2026-03-26
experiment: 011
status: inconclusive
finding: "Yahoo Finance only returns CURRENT option chains, not historical. Expired expirations return 0 calls/0 puts. YF is usable for live recommendations but NOT for backtesting. Databento remains the only source of real historical option prices."
---

# Experiment 011: Can We Trust Yahoo Finance Option Data?

**Date:** March 26, 2026
**Method:** Compare YF option chain prices against Databento OHLCV ground truth on AAPL

## The Question

We have Databento data for 5 tickers but GOOGL and AMZN are untested. Yahoo Finance is free. Can we use YF historical option data to extend our backtesting coverage?

## What We Found

**YF doesn't provide historical option chains.** When we fetched chains for expired expirations (e.g., AAPL 2025-04-11), YF returned 0 calls, 0 puts. All 20 sample dates returned empty chains.

This is a fundamental limitation of the Yahoo Finance API — it only returns the CURRENT live chain, not historical snapshots.

## BSM as Free Data Proxy

Since YF can't provide historical chains, we tested BSM (Black-Scholes with RV*1.2 as IV) as a free alternative to Databento:

| OTM% | Databento (real) P&L | BSM (free) P&L | Error |
|---|---|---|---|
| 3% | +$240 | +$2,336 | **9.7x overstated** |
| 5% | -$542 | +$1,806 | **Wrong direction** |
| 7% | -$1,106 | +$2,597 | **Wrong direction** |
| 10% | +$272 | +$677 | 2.5x overstated |
| 15% | +$351 | +$2,681 | **7.6x overstated** |

BSM picks the same BEST strategy (15% OTM) but massively overstates profits and shows losing strategies as profitable.

## Verdict: INCONCLUSIVE

- **YF for live recommendations:** Works (current chains are accurate)
- **YF for backtesting:** Impossible (no historical data)
- **BSM for directional screening:** Works (picks correct best/worst)
- **BSM for P&L estimates:** Dangerous (7.6x overstatement)
- **For accurate backtesting:** Databento is the only option

## Reproducibility

```bash
python experiments/011_yahoo_data_quality/run.py
```
