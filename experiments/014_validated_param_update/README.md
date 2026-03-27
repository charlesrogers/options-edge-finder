---
experiment: 014
title: "Validated Parameter Update: TMUS 10%, KKR 15%, GOOGL skip"
date: 2026-03-27
status: pre-registered
hypotheses:
  - "TMUS at 10% OTM achieves <15% loss rate in walk-forward holdout"
  - "KKR at 15% OTM achieves <15% loss rate in walk-forward holdout"
  - "GOOGL at any OTM% (5-20%) fails to achieve <25% loss rate in walk-forward"
prior_experiment: 013
---

# Experiment 014: Validated Parameter Update

## Motivation

Experiment 013 found that TMUS (3% OTM, 28% loss rate), KKR (3%, 30%),
and GOOGL (5%, 48%) need parameter changes. But those findings were
in-sample — they used the full dataset to pick new OTM% and didn't
validate out-of-sample.

This experiment pre-registers the proposed changes and validates them
with proper walk-forward splits before deploying to production.

## Proposed Changes (from Exp 013 analysis)

| Ticker | Current | Proposed | Exp 013 Reason |
|---|---|---|---|
| TMUS | 3% OTM (best) | 10% OTM | 28% loss at 3%, 11% at 10% |
| KKR | 3% OTM (strong) | 15% OTM | 30% loss at 3%, 13% at 15% |
| GOOGL | 5% OTM (untested) | SKIP | 48% loss, no OTM% works |

## Method

For each ticker, split Yahoo Finance 1yr stock data:
- **Train**: first 67% of trading days
- **Test**: last 33% of trading days

On the TEST period only:
1. Simulate weekly covered calls at the PROPOSED OTM%
2. Count wins (expired OTM) vs losses (expired ITM)
3. Calculate loss rate

## Pass/Fail Thresholds (Pre-Registered, Immutable)

### TMUS 10% OTM
- **PASS**: Loss rate < 15% on test period
- **FAIL**: Loss rate >= 15%
- If FAIL: try 15% OTM as fallback

### KKR 15% OTM
- **PASS**: Loss rate < 15% on test period
- **FAIL**: Loss rate >= 15%
- If FAIL: try 20% OTM as fallback

### GOOGL (any OTM%)
- **PASS (confirming skip)**: Loss rate > 25% at 10% OTM on test period
- **FAIL (keep trading)**: Loss rate < 25% at 10% OTM — reconsider skip

## Deployment Gate

Only deploy parameter changes for tickers that PASS walk-forward.
One ticker per commit. Each commit message must reference this experiment.
