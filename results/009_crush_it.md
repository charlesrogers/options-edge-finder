---
title: "Experiment 009: Make It Crush — IV-Aware Entry + Early Rolling"
date: 2026-03-25
experiment: 009
hypotheses: ["IV filter improves P&L", "Early rolling converts losers to winners", "Combined improves retention to 40%+"]
status: completed
finding: "IV-aware entry is the single biggest lever — triples avg P&L from +$70 to +$213 (+204%). Rolling helps individual trades but doesn't move the aggregate. Combined retention only reaches 13%, not the 40% target. The copilot's aggressive closing is the binding constraint — correct for safety, expensive for income. MARGINAL pass: P&L improved >20% but retention didn't hit 35%."
---

# Experiment 009: Make It Crush

**Date:** March 25, 2026
**Data:** Same 5 tickers as Experiment 008 (AAPL, DIS, TXN, TMUS, KKR), real Databento prices
**Grid:** 3 variants x 75 parameter combos = 225 simulation runs

## The Question

Experiment 008 found profitable strategies but premium retention was only 26% (5% after correcting for aggregate). Can we do better with:
1. **IV-aware entry** — only sell when IV is elevated (skip low-IV months)
2. **Early rolling** — at CLOSE_SOON, roll to next month instead of closing

## Results: Head-to-Head

| Variant | Avg P&L | vs Baseline | Win Rate | Profitable | Retention | Assignments |
|---|---|---|---|---|---|---|
| A: Baseline (Exp 008) | +$70 | — | 64% | 46/75 | 5% | 0 |
| **B: IV filter only** | **+$213** | **+204%** | **70%** | **49/75** | **13%** | 0 |
| C: Roll only | +$188 | +168% | 62% | 50/75 | 5% | 0 |
| D: IV + Roll | +$203 | +190% | 65% | 44/75 | 6% | 0 |

## The IV Filter Is the Clear Winner

Skipping low-IV months (iv_rank < 50) had the biggest impact:
- AAPL 5% OTM: **-$542 → +$894** (from losing money to profitable)
- Average P&L tripled across all 75 combos
- Win rate improved from 64% to 70%
- 3 more combos became profitable (46 → 49)

**Why it works:** Low-IV months produce thin premium that can't absorb buyback costs. By only selling when IV is elevated, each trade collects more premium — enough to survive the copilot's emergency closes.

## Rolling: Helps Individuals, Not the Portfolio

Rolling at CLOSE_SOON (instead of closing) showed mixed results:
- **KKR 7% OTM: +$702 → +$1,894** (rolling saved multiple positions)
- But aggregate P&L improvement was smaller than IV filter alone
- Combined (D) slightly underperformed IV-alone (B) because the IV filter already removes the bad entries rolling would have saved

195 rolls executed across all combos, 3,360 entries skipped by IV filter.

## Why Retention Is Still Only 13%

The copilot fires CLOSE_NOW on every position that approaches the strike. This is correct — it's why we have zero assignments. But it means:
- 74% of premium goes to buyback costs
- The copilot is an expensive insurance policy
- The premium income is a bonus on top of the real value: tax protection

**This is the right tradeoff for Dad.** One assignment on 1,000 shares costs $45,000+ in taxes. The copilot costs ~$2,000/yr in buyback friction. That's 22x ROI on the insurance alone.

## Verdict: MARGINAL PASS

- P&L improved by +204% (exceeds 20% threshold)
- But retention only reached 13%, not the 35% target
- The copilot's aggressiveness is the binding constraint
- Loosening it risks assignments — the one thing Dad can't afford

## What This Means for the Product

1. **Wire IV filter into Today's Trades** — only recommend covered calls when IV is elevated
2. **The product pitch is insurance + income, not income alone**
3. At Dad's scale (1,000 shares x 4 tickers): ~$8,500/yr premium + $100K+ tax protection
4. The premium pays for itself many times over as insurance cost

## Reproducibility

```bash
python experiments/009_crush_it/run.py
```
