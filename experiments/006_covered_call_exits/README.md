# Experiment 006: Covered Call Exit Timing Research

## CONSTRAINT
Dad ALREADY sells covered calls on his stocks. He NEVER wants to be called away.
He lost $400K on MSFT by not buying back calls before ex-dividend.
This research determines WHEN to buy back, not WHETHER to trade.

## Pre-Registration

**Date:** 2026-03-24
**Status:** Pre-registered (before seeing any results)

## Data Split (locked before analysis)

| Set | Data | Purpose |
|---|---|---|
| **Train (60%)** | AAPL Apr-Nov 2025 + KKR 2023-2024 | Discover thresholds |
| **Validate (20%)** | DIS Apr-Nov 2025 + KKR Jan-Jun 2025 | Check generalization |
| **Holdout (20%)** | AAPL+DIS Dec 2025-Mar 2026 + KKR Jul-Dec 2025 | Final sealed test |

Rules: Train first. Validate second. Holdout opened ONCE after thresholds locked.

## Studies

### Study A: ITM Probability by Moneyness + DTE
When stock is X% from strike with Y days to expiry, what's the probability it finishes ITM?

### Study B: Optimal Take-Profit (things go right)
At what % of premium captured should Dad close? Expected value of holding further.

### Study C: Optimal Buy-Back (things go wrong)
When stock approaches strike, what's the optimal moment to buy back?
Too early = overpay. Too late = assignment risk.

### Study D: Ex-Dividend Danger Zone
How many days before ex-div AND at what moneyness is early exercise virtually certain?

### Study E: Gamma Danger Zone
At what DTE does a small stock move flip a safe position to dangerous?

### Study F: MSFT Retrospective
How often does the Dad-MSFT scenario (ITM + near ex-div + asleep) occur?
What alert threshold catches it with acceptable false alarm rate?
