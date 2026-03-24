---
experiment: 008
title: "Strategy Grid Search: Optimal Covered Call Parameters"
date: 2026-03-24
status: completed
hypotheses:
  - "Selling further OTM (7-10%) reduces costly buybacks enough to offset lower premium — REJECTED: 3% OTM is best"
  - "There exists an OTM% sweet spot where net P&L is maximized with 0 assignments — ACCEPTED: 46/75 combos profitable"
  - "Optimal parameters are consistent across Dad's tickers — REJECTED: ticker-dependent (TMUS 3%, DIS 7%, AAPL 15%)"
result: "PASS — 46/75 combos profitable with 0 assignments. 3% OTM avg +$500, 5% OTM avg -$230. Per-ticker recs needed."
---

# Experiment 008: Strategy Grid Search

## Problem

Experiment 007 showed the copilot prevents assignments (goal #1) but net P&L is -$542.
We optimized for "never get called away" but ignored goals #2 (don't lose money) and
#3 (maximize profit). The 5% OTM strikes are too close — stock drifts 3-5% and triggers
expensive emergency buybacks.

## Grid

| Parameter | Values |
|---|---|
| OTM % | 3%, 5%, 7%, 10%, 15% |
| DTE range | 14-30, 20-45, 30-60 |
| Tickers | AAPL, DIS, TXN, TMUS, KKR |

75 parameter combos total.

## Pass/Fail Thresholds (Pre-Registered)

- **PASS**: At least one combo achieves net P&L > $0 AND 0 assignments across 2+ tickers
- **FAIL**: No combo achieves profitable trading with zero assignments
- If FAIL: the copilot is valuable for tax avoidance but the covered call strategy itself needs rethinking

## Metrics (Tri-Fold Scorecard)

1. Assignments (must be 0)
2. Net P&L per contract (must be > $0)
3. Premium retained % (maximize)
4. Win rate
5. Worst single trade loss
6. Buyback cost as % of premium collected
