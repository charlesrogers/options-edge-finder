# Experiment 003: AAPL Cash-Secured Puts with Real Prices

## Pre-Registration

**Date:** 2026-03-23
**Status:** Pre-registered (results not yet computed)
**Hypotheses:** H40, H41, H42, H43
**Motivated by:** Experiment 002 failure — put spreads lose money due to friction + asymmetric risk. But AAPL-only take-profit trades WERE profitable (Sharpe 6.83).

## Root Cause from Experiment 002

Three causes of failure:
1. **Win/loss ratio 0.16x** — avg winner $50 vs avg loser $321
2. **Expiry trades catastrophic** — 20 expiry trades lost $4,927; 67 take-profit trades made $2,841
3. **Illiquid names** — KKR alone lost $2,049 (82% of total losses)

**Key insight:** Take-profit exits on liquid names = profitable. Everything else = not.

## Why Cash-Secured Puts Instead of Spreads

The spread's protective long put costs money on every trade:
- Buying overpriced insurance (exactly what Sinclair warns against)
- Extra slippage on second leg
- Estimated savings from dropping long put: $50-80 per trade

AAPL specifically: 1-3% bid-ask (not 15%), so slippage haircut drops from 15% to 5%.

## Hypotheses

### H40: AAPL CSP Profitable
- Sell 5% OTM put, 20-30 DTE, GREEN signal, 25% TP exit, 5% slippage
- Pass: avg P&L > $0, Sharpe > 0.5
- Fail: avg P&L <= $0

### H41: CSP Beats Put Spread on AAPL
- Same conditions, compare single-leg vs two-leg
- Pass: CSP Sharpe > spread Sharpe by > 0.3

### H42: Higher VRP Threshold Helps
- Compare VRP > 2 vs VRP > 5 vs VRP > 8
- Pass: higher threshold improves Sharpe

### H43: Survives Holdout + Bootstrap
- 80/20 split, 1000x bootstrap
- Pass: holdout Sharpe > 50% of training, P(ruin) < 5%

## Data
- AAPL Databento OHLCV: 2,211,521 rows (Mar 2025 - Mar 2026)
- AAPL Yahoo stock: 2 years
- Cost: $0 (already downloaded)
