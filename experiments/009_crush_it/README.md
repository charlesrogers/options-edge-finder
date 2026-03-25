---
experiment: 009
title: "Make It Crush: IV-Aware Entry + Early Rolling"
date: 2026-03-25
status: pre-registered
hypotheses:
  - "IV-aware entry (skip low-IV months) reduces losing trades and improves net P&L"
  - "Early rolling at CLOSE_SOON (instead of closing) converts some losers to winners"
  - "Combined IV filter + rolling improves premium retention from 26% to 40%+"
---

# Experiment 009: Make It Crush

## Problem

Experiment 008 found 46/75 profitable combos with zero assignments, but premium retention
is only 26% — 74% of collected premium goes to buyback costs. The 8 losing trades per
ticker all happened at 0 DTE with 2-3x buyback multipliers.

Research finding: **rolling at 0 DTE makes it WORSE** (adds friction). The losers should
have been avoided at entry (low-IV months) or rolled EARLY (at CLOSE_SOON, not CLOSE_NOW).

## Levers

### Lever 1: IV-Aware Entry Filter
Only sell covered calls when `iv_rank >= 50` (IV is in the upper half of its 52-week range).
Skip low-IV months entirely. Fewer trades, but each trade has better premium and edge.

### Lever 2: Early Rolling
When copilot says CLOSE_SOON (not CLOSE_NOW):
- Check if next-month call at same OTM% has decent premium (>= 50% of original)
- If yes: buy back current call + sell next month (roll)
- If no: close as usual
- Only roll when 7-14 DTE remaining (enough time value in both legs)

## Grid

| Variant | IV Filter | Early Roll |
|---|---|---|
| A: Baseline | No | No |
| B: IV filter only | Yes (rank >= 50) | No |
| C: Roll only | No | Yes |
| D: Both | Yes | Yes |

Each variant runs the same 5 OTM% x 3 DTE x 5 tickers = 75 combos from Experiment 008.
Baseline results already exist — only need to run B, C, D.

## Pass/Fail Thresholds (Pre-Registered)

- **PASS**: Combined variant (D) improves premium retention from 26% to >= 35%
  AND maintains zero assignments AND net P&L improves by >= 20%
- **MARGINAL**: Retention improves to 30-35% or P&L improves by 10-20%
- **FAIL**: No variant meaningfully improves on baseline Experiment 008

## Metrics

Same tri-fold scorecard as Experiment 008, plus:
- Premium retention % (target: 40%+)
- Roll success rate (% of rolls that resulted in net profit)
- Trades skipped by IV filter (and what they would have done)
- Roll count per ticker
