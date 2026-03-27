---
experiment: 013
title: "Loss Analysis: Why GOOGL Loses 48% and What To Fix"
date: 2026-03-26
status: pre-registered
hypotheses:
  - "GOOGL losses are from sustained rally — higher OTM% (10-15%) would fix it"
  - "TMUS 3% OTM is too aggressive in bull markets — 5-7% would reduce losses"
  - "Copilot-adjusted P&L is significantly better than raw -100% per loss"
  - "Losses concentrate in trending/low-VIX regimes"
---

# Experiment 013: Loss Analysis

## Problem
73 losses / 386 scored (19% loss rate). Concentrated in GOOGL (48%), TMUS (34%), AAPL (25%).
KKR (0%) and DIS (2%) are nearly perfect. The OTM% is wrong for trending stocks.

## Questions
1. Would 10-15% OTM fix GOOGL?
2. Would 5-7% OTM reduce TMUS losses?
3. What would copilot-adjusted P&L look like?
4. Are losses regime-dependent?

## Pass/Fail
- PASS: Find an OTM% that reduces GOOGL losses to <15% and TMUS to <15%
- FAIL: No OTM% achieves <15% loss rate for both tickers
