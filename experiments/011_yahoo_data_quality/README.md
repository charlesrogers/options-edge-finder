---
experiment: 011
title: "Yahoo Finance Option Data Quality vs Databento Ground Truth"
date: 2026-03-26
status: pre-registered
hypotheses:
  - "Yahoo Finance ATM call close prices correlate > 0.90 with Databento OHLCV close prices"
  - "Mean absolute error < 10% for ATM options"
---

# Experiment 011: Can We Trust Yahoo Finance Option Data?

## Problem

We have real Databento data for 5 tickers but GOOGL and AMZN are untested.
Yahoo Finance is free but unverified. Before using YF to expand coverage,
we need to know: how accurate is it?

## Method

For AAPL (where we have Databento ground truth):
1. Load Databento OHLCV close prices for ATM calls
2. Fetch Yahoo Finance option chain for the same strikes/dates
3. Compare: correlation, mean absolute error, max error

## Pass/Fail (Pre-Registered)

- **PASS**: Correlation > 0.90 AND mean error < 10%
- **MARGINAL**: Correlation 0.80-0.90 OR mean error 10-20%
- **FAIL**: Correlation < 0.80 OR mean error > 20%

If PASS: use YF data for GOOGL, AMZN, MSFT strategy validation
If FAIL: keep "untested" tier, note data limitation
