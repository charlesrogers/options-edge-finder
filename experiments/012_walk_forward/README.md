---
experiment: 012
title: "Walk-Forward Validation of Strategy Grid"
date: 2026-03-26
status: pre-registered
hypotheses:
  - "Optimal OTM% from first 8 months performs within 50% of in-sample on last 4 months"
  - "Per-ticker strategy recommendations hold out-of-sample for 3+ tickers"
---

# Experiment 012: Walk-Forward Validation

## Problem

Experiment 008 tested 75 parameter combos on the FULL dataset.
This is in-sample evaluation — the strategies could be overfit.
We need to validate out-of-sample.

## Method

For each ticker with 1yr data (AAPL, DIS, TXN, TMUS):
1. **Train period**: First 8 months — run strategy grid, find optimal OTM%
2. **Test period**: Last 4 months — run the optimal strategy, measure performance
3. Compare: does the train-period winner also win out-of-sample?

KKR has 3yr data — use 2yr train / 1yr test.

## Pass/Fail (Pre-Registered)

- **PASS**: Out-of-sample net P&L is positive for 3+ tickers using train-period optimal params
- **MARGINAL**: 2 tickers positive out-of-sample
- **FAIL**: 1 or fewer tickers positive — strategies are overfit

## Metrics

- In-sample optimal OTM% per ticker
- Out-of-sample P&L using that OTM%
- In-sample vs out-of-sample P&L ratio
- Win rate stability (train vs test)
