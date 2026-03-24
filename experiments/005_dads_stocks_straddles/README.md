# Experiment 005: Straddles/Strangles on Dad's Stocks

## CONSTRAINT (checked before every strategy idea)

Dad owns: TXN, TMUS, GOOGL, AMZN, AAPL, KKR, DIS
- ONLY trade options on these 7 stocks
- NEVER sell shares (unrealized gains tax)
- Prefer not to buy shares (but acceptable as last resort)

## Pre-Registration

**Date:** 2026-03-24
**Status:** Pre-registered (before seeing results)

## What's Different from Experiments 001-004

| Previous | This Experiment |
|---|---|
| Put spreads (2 legs, long put costs $40-80) | Straddles/strangles (no long option, full premium) |
| Monthly DTE (20-30 days) | Weekly DTE (5-7 days) for more trades |
| Also test 30-day DTE | Head-to-head weekly vs monthly |
| BSM synthetic prices | Real Databento prices (AAPL, DIS, TXN, TMUS, KKR) |
| Individual trade P&L | Portfolio-level daily P&L (corrected engine) |
| Arbitrary trade skip | Every eligible day, position-limited |
| No sanity checks | Hand-verify 1 trade, check max loss < capital |

## Why Straddles Instead of Spreads

Sinclair (Ch 10): "Most liquid and cheapest to trade... Most vega for a given expiration."

Spreads buy overpriced protection — $40-80 per trade in long-put cost. That's where most of the edge went. Straddles collect the FULL premium from both sides (call + put). The trade-off is unlimited risk, but with:
- Small position size (1 contract = 100 shares notional)
- DTE floor exit at 2 days (don't hold through expiry gamma)
- Only trading when VRP > 2 (GREEN signal)

## What We Test

### Variant 1: Weekly ATM straddle on each stock (5 tickers with data)
- Sell ATM call + ATM put, ~7 DTE
- Close at DTE floor (2 days) or take-profit (25%, 50%)
- Real Databento prices for entry/exit
- Max 1 straddle per ticker at a time

### Variant 2: Monthly ATM straddle (20-30 DTE)
- Same as above but monthly expiry
- More theta, more gamma risk

### Variant 3: Strangle (sell 5% OTM call + 5% OTM put)
- Wider range = higher win rate but less premium
- Compare to straddle

### Variant 4: Liquid-only (AAPL + DIS only)
- Skip KKR/TMUS (illiquid, proven failures)
- Concentrate on tickers where repricing works

### Variant 5: VRP threshold sweep
- VRP > 2 vs > 4 vs > 6 vs > 8

## Pass/Fail (immutable)

| Metric | Pass | Fail |
|---|---|---|
| Portfolio daily Sharpe | > 0.3 | <= 0.3 |
| Max drawdown | > -15% of capital | <= -15% |
| Holdout Sharpe ratio | > 0.5x training | <= 0.5x |
| Bootstrap 95% CI lower | > 0 | <= 0 |
| Individual trade win rate | > 55% | <= 55% |

## Sanity Checks (per lessons.md)

Before trusting any results:
- [ ] Hand-calculate 1 AAPL straddle trade, verify engine matches
- [ ] Max portfolio loss < starting capital on any day
- [ ] sum(daily_pnl) ≈ sum(trade_realized_pnl) within 10%
- [ ] No Sharpe > 3.0 on > 50 trades (red flag if so)
- [ ] Rerun with different random seed — results stable

## If It Fails

If straddles on Dad's stocks also produce Sharpe < 0.3:
- Document honestly
- The conclusion: VRP harvesting via options on individual stocks is NOT viable after real-world friction, regardless of structure
- Recommend Dad explore: (a) covered calls on positions with LOW unrealized gains, (b) cash-secured puts only when he genuinely wants more shares at a discount, (c) accept that his edge is in stock-picking, not options income
