---
title: "Experiment 008: Strategy Grid Search — The Tri-Fold Optimization"
date: 2026-03-24
experiment: 008
hypotheses: ["Optimal OTM% exists for tri-fold goal", "3% OTM beats 5% OTM", "Optimal params are ticker-dependent"]
status: completed
finding: "75 parameter combos across 5 tickers with real Databento data. 3% OTM is the best overall strategy (+$500 avg P&L), not 5% (-$230). The premium from selling closer to the money absorbs buyback costs. 46 of 75 combos are profitable with zero assignments. The optimal OTM% is ticker-dependent: TMUS and KKR prefer 3%, DIS prefers 7%, AAPL prefers 10-15%. TXN should be avoided."
---

# Experiment 008: Which Covered Call Strategy Makes the Most Money?

**Date:** March 24, 2026
**Data:** Real option prices for AAPL, DIS, TXN, TMUS, KKR (Databento OHLCV, 1yr each)
**Grid:** 5 OTM% x 3 DTE ranges x 5 tickers = 75 parameter combos

## The Question

Experiment 007 proved the copilot prevents assignments. But at 5% OTM, net P&L was -$542. The strategy was losing money. Dad's goals are tri-fold:

1. **Never get called away** (0 assignments)
2. **Never lose money** (net P&L > 0)
3. **Maximize premium income**

Which covered call parameters satisfy all three?

## The Grid

| Parameter | Values Tested |
|---|---|
| OTM % | 3%, 5%, 7%, 10%, 15% |
| DTE range | 14-30 (short), 20-45 (standard), 30-60 (long) |
| Tickers | AAPL, DIS, TXN, TMUS, KKR |

## The Headline Result

| OTM% | Avg Net P&L | Win Rate | Profitable Combos | Avg Worst Trade |
|---|---|---|---|---|
| **3%** | **+$500** | 52% | **12/15 (80%)** | -$260 |
| 5% | -$230 | 50% | 7/15 (47%) | -$462 |
| 7% | -$192 | 61% | 8/15 (53%) | -$442 |
| 10% | +$165 | 75% | 10/15 (67%) | -$345 |
| 15% | +$105 | 84% | 9/15 (60%) | -$313 |

**Zero assignments across all 75 combos.** The copilot works at every OTM level.

## Why 3% OTM Wins

The intuition says "sell further OTM = safer = more profit." The data says the opposite.

At 3% OTM:
- **Higher premium collected** ($6-8/share vs $2-3 at 10% OTM)
- **More emergency buybacks** (stock approaches strike more often)
- **But the premium covers the buybacks** — net positive

At 5-7% OTM:
- **Moderate premium** ($3-5/share)
- **Still gets emergency buybacks** (stock only needs to drift 3-5%)
- **Premium can't cover the buybacks** — net negative

At 10-15% OTM:
- **Tiny premium** ($0.50-2/share)
- **Rarely needs buyback** (stock would need a 10%+ move)
- **Almost all premium retained** — but there isn't much to retain

**5% OTM is the worst of both worlds.** Enough risk to trigger buybacks, not enough premium to absorb them.

## Top 10 Strategies

| Rank | Ticker | OTM% | DTE | Net P&L | Win% | Worst Trade |
|---|---|---|---|---|---|---|
| 1 | TMUS | 3% | 20-45 | **+$2,276** | 57% | -$185 |
| 2 | TMUS | 3% | 14-30 | +$1,972 | 57% | -$124 |
| 3 | KKR | 3% | 20-45 | +$1,796 | 80% | -$155 |
| 4 | TMUS | 3% | 30-60 | +$1,980 | 50% | -$320 |
| 5 | TMUS | 5% | 14-30 | +$1,583 | 64% | -$408 |
| 6 | KKR | 3% | 30-60 | +$1,292 | 76% | -$501 |
| 7 | KKR | 5% | 20-45 | +$1,342 | 69% | -$245 |
| 8 | TMUS | 7% | 30-60 | +$1,154 | 71% | -$320 |
| 9 | TMUS | 15% | 30-60 | **+$1,026** | **100%** | +$24 |
| 10 | TMUS | 5% | 20-45 | +$1,118 | 57% | -$526 |

## Per-Ticker Breakdown

### TMUS (T-Mobile) — Best stock for covered calls

Every single parameter combo is profitable. TMUS has moderate vol and steady upward drift.

| OTM% | Best DTE | Net P&L | Win% |
|---|---|---|---|
| 3% | 20-45 | +$2,276 | 57% |
| 5% | 14-30 | +$1,583 | 64% |
| 7% | 30-60 | +$1,154 | 71% |
| 10% | 20-45 | +$981 | 79% |
| 15% | 30-60 | +$1,026 | **100%** |

**Recommendation:** 3% OTM, 20-45 DTE for maximum income. Or 15% OTM, 30-60 DTE for zero-stress (100% win rate).

### KKR — Strong performer (3yr data, 41 trades)

| OTM% | Best DTE | Net P&L | Win% |
|---|---|---|---|
| 3% | 20-45 | +$1,796 | 80% |
| 5% | 20-45 | +$1,342 | 69% |
| 7% | 20-45 | +$702 | 76% |
| 10% | — | negative | — |
| 15% | 14-30 | +$386 | 81% |

**Recommendation:** 3% OTM, 20-45 DTE. KKR has enough vol for good premium but trends predictably.

### DIS (Disney) — Sweet spot at 7%

| OTM% | Best DTE | Net P&L | Win% |
|---|---|---|---|
| 3% | 30-60 | +$445 | 60% |
| 5% | 14-30 | +$204 | 57% |
| **7%** | **30-60** | **+$822** | **71%** |
| 10% | 30-60 | +$452 | 79% |
| 15% | — | negative | — |

**Recommendation:** 7% OTM, 30-60 DTE. DIS has occasional big moves — needs more buffer than TMUS.

### AAPL — Conservative approach works best

| OTM% | Best DTE | Net P&L | Win% |
|---|---|---|---|
| 3% | 30-60 | +$280 | 43% |
| 5% | — | negative | — |
| 7% | — | negative | — |
| 10% | 30-60 | +$279 | 79% |
| **15%** | **20-45** | **+$351** | **100%** |

**Recommendation:** 15% OTM, 20-45 DTE. AAPL rallied hard in this period. Tiny premium but 100% win rate — every call expired worthless.

### TXN (Texas Instruments) — Avoid

| OTM% | Best DTE | Net P&L | Win% |
|---|---|---|---|
| 3% | — | -$939 to -$1,681 | 14-36% |
| 5% | — | -$1,838 to -$2,638 | 21-29% |
| 7% | — | -$1,423 to -$1,780 | 29-36% |
| 10% | 14-30 | +$225 | 71% |
| 15% | 30-60 | +$23 | 69% |

**Recommendation: Do not sell covered calls on TXN.** It's too volatile — blows through strikes at every OTM level. Only 10%+ OTM barely breaks even.

## What This Means for the Product

The copilot needs **per-ticker recommendations**, not one-size-fits-all:

| Ticker | Recommended OTM% | DTE | Expected P&L/yr | Win Rate |
|---|---|---|---|---|
| TMUS | 3% | 20-45 | +$2,276 | 57% |
| KKR | 3% | 20-45 | +$1,796 | 80% |
| DIS | 7% | 30-60 | +$822 | 71% |
| AAPL | 15% | 20-45 | +$351 | 100% |
| TXN | **Skip** | — | — | — |
| GOOGL | Insufficient data | — | — | — |
| AMZN | No data | — | — | — |

## Verdict

**PASS.** 46 of 75 combos achieve both zero assignments AND positive P&L. The optimal strategy is ticker-dependent — high-vol stocks need more OTM buffer, low-vol stocks can sell closer and collect more premium. The 5% OTM default was wrong for most stocks.

## Reproducibility

```bash
python experiments/008_strategy_grid/run.py
```

Results: `experiments/008_strategy_grid/results.json`
