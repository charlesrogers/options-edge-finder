---
experiment: 010
title: "Bear Market Stress Test: What Happens When AAPL Drops 30%?"
date: 2026-03-25
status: pre-registered
hypotheses:
  - "Covered call premium provides meaningful downside cushion in a crash"
  - "The copilot correctly handles crash scenarios (no false EMERGENCY on stock drop)"
  - "Portfolio-level damage in a 2022-style drawdown is quantifiable"
---

# Experiment 010: Bear Market Stress Test

## Problem

All experiments (007-009) ran in a bull market (AAPL +60% in 1yr). We have zero
data on what happens in a crash. Dad needs to know: if 2022 happens again, what
does the covered call strategy + copilot do to his portfolio?

## Scenarios (Monte Carlo + Historical)

1. **Gradual decline (-20% over 6 months)** — 2022 style
2. **Sharp crash (-30% in 1 month)** — COVID March 2020 style
3. **Flash crash (-10% in 1 day, recovery)** — Aug 2024 style
4. **Sideways grind (-5% with high vol)** — best case for premium sellers

## What We're Measuring

- Does the copilot fire false alarms in a crash? (stock drops but calls go to $0)
- How much premium cushion offsets the stock decline?
- What's the worst-case portfolio drawdown?
- Is "covered calls + copilot" better or worse than "just hold stock"?

## Pass/Fail

- **PASS**: Covered calls + copilot lose LESS than naked stock in all crash scenarios
- **FAIL**: Strategy amplifies losses or creates false assignment risk in crashes
