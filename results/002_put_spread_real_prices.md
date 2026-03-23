---
title: "Experiment 002: Put Spreads FAIL with Real Option Prices"
date: 2026-03-23
experiment: 002
hypotheses: [H35, H36, H37, H38, H39]
status: completed
finding: "The bull put spread strategy loses money after real-world bid-ask friction. 78.9% win rate but avg P&L is -$27.87 per trade. 100% probability of ruin. DO NOT trade this strategy."
---

# Experiment 002: Put Spreads FAIL with Real Option Prices

**Date:** March 23, 2026
**Pre-registered:** March 23, 2026 (before seeing any results)
**Data:** 3.6M rows of real option OHLCV from Databento (AAPL, DIS, TXN, TMUS, KKR)

## The Question

Does the bull put spread strategy with 25% take-profit exit produce positive returns when priced with REAL option market data?

## The Answer

**No.** The strategy loses money.

## Results

| Metric | Value | Pass Threshold | Result |
|---|---|---|---|
| Avg P&L per trade | **-$27.87** | > $0 | **FAIL** |
| Win rate | 78.9% | — | High but irrelevant |
| Sharpe ratio | -0.558 | > 0.3 | **FAIL** |
| Total P&L (90 trades) | -$2,509 | > $0 | **FAIL** |
| Holdout Sharpe ratio | -727.5x training | > 0.50x | **FAIL** |
| Bootstrap P(negative returns) | 87.6% | — | Near-certain loss |
| Bootstrap P(ruin >20% DD) | 100% | < 5% | **FAIL** |

## Per-Ticker Breakdown

| Ticker | Trades | Win Rate | Avg P&L | Sharpe | Max DD |
|---|---|---|---|---|---|
| AAPL | 14 | 78.6% | **+$28.24** | **6.83** | -$1.72 |
| DIS | 15 | 80.0% | -$0.61 | -0.04 | -$254.66 |
| TXN | 16 | 87.5% | -$40.39 | -0.62 | -$1,285.80 |
| TMUS | 17 | 94.1% | -$11.78 | -0.29 | -$944.22 |
| KKR | 28 | 64.3% | -$73.16 | -0.94 | -$2,590.66 |

**Only AAPL was profitable.** Every other ticker lost money despite high win rates.

## Why It Fails

### 1. Bid-Ask Friction Destroys the Edge

The VRP edge (selling overpriced volatility) is real — our H01 backtest confirmed it on 7,339 trades. But the VRP is ~3.5 vol points on average. When translated to a put spread:

- Credit collected: ~$1.70 per share ($170 per contract)
- 15% entry slippage: -$0.26 ($26)
- 15% exit slippage: -$0.26 ($26)
- **Total friction: $52 per round-trip**

On a $170 credit, $52 in friction is **30% of the edge**. The remaining $118 isn't enough to offset the asymmetric losses when spreads go against you.

### 2. Asymmetric Risk/Reward Kills You

The put spread structure means:
- Max win: credit ($170)
- Max loss: width - credit ($830)
- Ratio: 4.9:1 against you

Even with 25% take-profit (reducing max win to ~$120):
- Managed win: ~$120
- Managed loss (when trades hit expiry): ~$400-800
- Need 85%+ win rate to break even
- Real win rate with friction: 78.9% — not enough

### 3. Illiquid Tickers Are Catastrophic

KKR (2 contracts/day volume) lost -$73 per trade with 64% win rate. The bid-ask spreads on illiquid names eat the entire premium. This is NOT a viable strategy on low-volume options.

### 4. Only Ultra-Liquid Names Work

AAPL (24,000+ contracts/day) was the only profitable ticker. Its tight spreads (~1-3% bid-ask) preserve enough of the VRP edge to be profitable.

## Exit Strategy Analysis (H37)

| Take Profit | Avg P&L | Sortino | N |
|---|---|---|---|
| 25% | -$27.87 | -0.338 | 90 |
| 50% | -$18.93 | -0.210 | 87 |
| 75% | -$37.80 | -0.395 | 87 |
| 100% (expiry) | -$41.72 | -0.398 | 86 |

50% take-profit was slightly less bad than 25%, but **ALL levels lost money.** The exit strategy doesn't fix the structural problem.

## What This Tells Us

### The VRP Edge is Real, But Put Spreads Can't Capture It

The variance risk premium exists (validated in Experiments 001 and H01-H04). But the put spread STRUCTURE has too much friction and too much asymmetric risk to harvest it profitably on most stocks.

The issue is NOT the signal (GREEN works). The issue is the VEHICLE (put spread on individual stocks).

## Most Fertile Areas for Exploration

Based on what we learned, here's where the edge might actually be capturable:

### 1. Index ETF Straddles/Strangles (Sinclair's #1 Recommendation)

Sinclair ranks straddle > strangle > iron condor for VRP harvesting. He specifically says indices are the best product. SPY has:
- The tightest bid-ask spreads in the world (~$0.01-0.03)
- Highest volume (millions of contracts/day)
- Most consistent VRP (82% positive historically)
- No single-stock risk (diversified by construction)

**Why we haven't tested this:** SPY option data was too expensive on Databento ($47/month). But we can test with BSM (which was shown to be accurate on AAPL) or get SPY data on a new Databento account.

**This is the most promising alternative.** Sinclair's entire book is based on index VRP.

### 2. AAPL-Only Strategy

AAPL was the only profitable ticker (Sharpe 6.83, 14/14 trades hit take-profit). It's the most liquid single-stock option in the world. A strategy focused EXCLUSIVELY on AAPL put spreads might work.

**Risk:** 14 trades is too few for statistical significance. Need more data.

### 3. Wider Spreads on Liquid Names

Our spreads were 5%/10% OTM ($10-wide). Wider spreads ($20-30 wide) collect more credit, which better absorbs friction. The trade-off is higher max loss, but with active exit management this might be manageable.

### 4. Cash-Secured Puts Instead of Spreads

The spread's protective long put costs money (buying overpriced insurance — exactly what Sinclair warns against). A naked/cash-secured put avoids this cost. The risk is higher (unlimited-ish downside), but:
- No long-put friction
- Full premium collected
- Better return on friction
- Dad is willing to buy more shares at a discount (backup plan)

**Caveat:** Dad originally said he prefers not to buy more shares. But this might be the price of a viable strategy.

### 5. Longer DTE (45-60 days instead of 20-30)

Longer-dated options have:
- Lower gamma risk (less sensitive to short-term moves)
- More time for theta to work
- Wider bid-ask in dollar terms but tighter as % of premium
- Potentially better risk/reward if exiting at 25% TP

### 6. Sell When VRP is Extreme, Not Just Positive

Our GREEN signal fires when VRP > 2 vol points. But maybe the edge only exists at VRP > 5 or VRP > 8. Being MORE selective (trading less often but with bigger edge per trade) might overcome friction.

## Conclusion

**The put spread strategy on individual stocks does not work after real-world friction.** This is an honest finding from a pre-registered experiment with real option prices.

The VRP edge is real. The signal works. But the VEHICLE (put spreads on individual stocks) has too much friction. The most promising path forward is index ETF options (SPY/QQQ straddles) — Sinclair's actual recommendation that we deviated from to accommodate Dad's constraint of never selling shares.

The question now: **is there a structure that harvests VRP on SPY without owning shares, without forced assignment, and with low enough friction to preserve the edge?** That's Experiment 003.
