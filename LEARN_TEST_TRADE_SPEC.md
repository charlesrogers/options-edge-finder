# Learn / Test / Trade Pipeline Specification

## Origin

This spec merges two systems:
- **Options Edge Finder** — VRP-based options selling tool (8 eval modules, 350 tickers daily, GARCH/HAR-RV forecasting, walk-forward backtesting)
- **Variance Betting** — Ted Knutson's football betting framework (10-layer pod-shop testing, CLV tracking, dual independent signals, 28 pre-registered hypotheses, disciplined process)

The variance_betting system's power isn't any single model — it's the **process architecture**. Two independent signals must agree. Every hypothesis is pre-registered before testing. Every signal passes a 10-layer gate before real capital. CLV (not win rate) is the primary metric. 70% of opportunities are passed on. That discipline is what the options tool needs.

---

# Part I: Architecture Overview

## The Three Loops

```
                    ┌──────────────────────────────────────┐
                    │           LEARN LOOP                  │
                    │                                       │
                    │  Market-Implied Signal (Vol Surface)  │
                    │  Fundamental Signal (GARCH/HAR-RV)    │
                    │  Bayesian Model (updates from scored  │
                    │    predictions — adapts weights)       │
                    │  Copula Model (tail dependencies —     │
                    │    updates weekly from return data)    │
                    │                                       │
                    └──────────────┬────────────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────────────┐
                    │           TEST LOOP                   │
                    │                                       │
                    │  Pre-Registration Gate                │
                    │  10-Layer Validation Pipeline         │
                    │  Signal Graveyard + Deflated Sharpe   │
                    │  Stability Matrix (tickers x regimes  │
                    │    x time periods)                    │
                    │  CLV as primary metric                │
                    │                                       │
                    └──────────────┬────────────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────────────┐
                    │           TRADE LOOP                  │
                    │                                       │
                    │  Discipline Framework (when NOT to)   │
                    │  Structure Optimizer (multi-leg)      │
                    │  Staged Deployment (Shadow → 100%)    │
                    │  Portfolio Construction               │
                    │  4-Layer Production Monitoring        │
                    │  Circuit Breakers (Module 8C)         │
                    │                                       │
                    └──────────────┬────────────────────────┘
                                   │
                                   ▼
                              OUTCOMES
                           (scored predictions)
                                   │
                                   └──────► feeds back to LEARN LOOP
```

Each loop runs on a different cadence:
- **Learn**: Daily (Bayesian warm-start), weekly (copula refit), monthly (full MCMC refit)
- **Test**: Per-hypothesis (weeks to months), quarterly (stability review)
- **Trade**: Daily (signal generation + trade recommendations), continuous (monitoring)

---

# Part II: The Two Independent Signals

## Why Two Signals

The variance_betting system's core architecture is two independent models that must agree before betting:

1. **Market-Implied (MI) Model** — Reverse-engineers team ratings from betting odds via bivariate Poisson. Knows what the market thinks.
2. **xG Analysis** — Uses fundamental data (expected goals) to measure true quality. Knows what the data says.

When both agree, confidence is highest. When they disagree, either pass or flag the trade as an "override" with lower confidence.

The options equivalent:

| Role | Variance Betting | Options Edge Finder |
|------|-----------------|-------------------|
| Market-Implied Signal | MI model (Poisson from odds) | **Vol Surface** (SABR/Heston from option chain) |
| Fundamental Signal | xG analysis (historical performance) | **GARCH/HAR-RV Forecast** (historical volatility) |
| What market-implied reveals | "Market thinks Team A is 1.8 PPG" | "Market prices 30-delta put IV at 32%" |
| What fundamental reveals | "xG says Team A is actually 2.1 PPG" | "GARCH forecasts realized vol at 24%" |
| Edge when both agree | Market underrates team that xG says is good | Market overprices vol that GARCH says will be lower |
| Edge location | Asian Handicap mispricing | Specific strike/expiry where VRP is richest |

## Signal 1: Market-Implied (Vol Surface)

**Current state**: Single ATM IV number from front month.
**Target state**: Full SABR-calibrated surface revealing IV at every strike/expiry.

What it tells you:
- Where on the surface is IV richest relative to its own history?
- Is skew steeper than usual? (puts overpriced)
- Is term structure inverted? (near-term fear)
- Where do the model-free implied moments (variance, skew, kurtosis) disagree with historical moments?

The surface is the options equivalent of the MI model — it tells you **what the market thinks** about future volatility at every point.

## Signal 2: Fundamental (GARCH/HAR-RV Forecast)

**Current state**: GJR-GARCH(1,1,1) 20-day forecast + Yang-Zhang RV + HAR-RV comparison.
**Target state**: Best-of-breed forecast (GARCH, HAR-RV, or blend per Module 1D) with Bayesian uncertainty.

What it tells you:
- What will realized vol actually be over the next 20 days?
- Is the market's implied vol justified by fundamentals?
- How certain are we? (GARCH CI vs HAR-RV CI)

The forecast is the options equivalent of xG — it tells you **what the data says** about true quality, independent of what the market prices.

## Agreement Matrix

| Vol Surface Says | Forecast Says | Decision | Confidence | Variance Betting Equivalent |
|---|---|---|---|---|
| IV rich (high VRP at this strike) | RV will be lower than IV | **TRADE** | High | "Model bet" (MI + xG agree) |
| IV rich | RV uncertain / model disagreement | **REDUCE or PASS** | Medium | "Model bet, but reduce" |
| IV fair | RV will be lower | **PASS** (no market mispricing) | Low | "Line is fair" — no bet |
| IV cheap | RV will be lower | **PASS** (can't sell cheap vol) | None | "Line already moved past value" |
| IV rich | RV will be HIGHER than IV | **PASS** (VRP negative) | None | "xG says team is bad" — don't bet |
| Human override disagrees with model | — | **FLAG as override** | Varies | "Me bet, not Model bet" |

---

# Part III: Options CLV — The Critical New Metric

## What CLV Is

In betting:
```
CLV = (closing_implied_prob - your_implied_prob) / your_implied_prob
```
"Did you bet at better odds than where the line closed?" If yes, you consistently capture edge, even if individual bets lose.

In options:
```
CLV_market = (IV_at_entry - IV_at_close_or_expiry) / IV_at_entry
CLV_realized = (IV_at_entry - RV_over_holding_period) / IV_at_entry
```

**CLV_market**: "Did you sell at higher IV than where IV settled?" This measures whether you sold into elevated vol that subsequently compressed. Equivalent to beating the closing line.

**CLV_realized**: "Did implied vol exceed realized vol?" This measures whether the VRP actually materialized. This is the fundamental edge.

## Why CLV > Win Rate > P&L

| Metric | Variance | Signal | When Useful |
|--------|----------|--------|-------------|
| **P&L** | Very high | Noisy | Need 1,000+ trades for significance |
| **Win rate** | High | Moderate | 200+ trades for 95% CI |
| **CLV** | Lower | Strong | 100+ trades shows real signal |

From variance_betting research: a 2% edge requires ~1,700 bets to prove statistically via ROI at 95% confidence. CLV proves it faster because it has lower variance — you measure the spread between your entry and the efficient close, not the binary outcome.

**For options**: If you consistently sell at IV 32% and IV settles to 28% (CLV = 12.5%), you have edge even if some individual trades lose to realized vol spikes. CLV measures process quality; P&L measures outcome (which includes luck).

## Implementation

### New columns in `predictions` table:
```sql
ALTER TABLE predictions ADD COLUMN iv_at_entry REAL;        -- already stored as atm_iv
ALTER TABLE predictions ADD COLUMN iv_at_scoring REAL;      -- IV on outcome_date
ALTER TABLE predictions ADD COLUMN rv_over_holding REAL;    -- already stored as outcome_rv
ALTER TABLE predictions ADD COLUMN clv_market REAL;         -- (entry_iv - scoring_iv) / entry_iv
ALTER TABLE predictions ADD COLUMN clv_realized REAL;       -- (entry_iv - rv_holding) / entry_iv
```

### CLV computation in `score_pending_predictions()`:
```python
# After fetching outcome data (existing code):
iv_at_scoring = get_current_iv(ticker, outcome_date)  # fetch from iv_snapshots
rv_over_holding = outcome_rv  # already computed

clv_market = (atm_iv - iv_at_scoring) / atm_iv if iv_at_scoring else None
clv_realized = (atm_iv - rv_over_holding) / atm_iv if rv_over_holding else None
```

### CLV dashboard in Streamlit scorecard tab:
- Average CLV by signal type (GREEN/YELLOW/RED)
- Rolling 30-day CLV (is edge holding or decaying?)
- CLV distribution histogram (should be right-shifted)
- CLV vs P&L scatter (should correlate but CLV is smoother)

---

# Part IV: Testable Hypotheses

## Pre-Registration Format

Every hypothesis MUST be documented before testing. This prevents post-hoc rationalization ("we found a pattern!" after looking at data).

```
ID: H##
Name: [descriptive name]
Tier: [1-4]
Pre-registered: [date]
Status: [untested / testing / passed / failed / killed]

HYPOTHESIS: [one sentence, falsifiable]

FILTER: [which tickers/conditions qualify for this test]

TRADE DIRECTION: [what action the signal recommends]

PRIMARY METRIC: CLV (always)
SECONDARY METRICS: [P&L, Sharpe, Sortino, win rate]

PASS THRESHOLDS:
  - CLV > [X]%
  - Sharpe > [Y]
  - Sample size >= [Z]
  - [Additional criteria]

FAIL CRITERIA: [when to kill it]

DATA NEEDED: [source and date range]

EVIDENCE: [why we think this might work — prior to testing]

RESULTS: [filled in AFTER testing, never before]
```

## The 23 Hypotheses

### Tier 1: Core Signal (if these fail, stop everything)

**H01: VRP Predicts Seller Wins**
```
Tier: 1
HYPOTHESIS: When IV exceeds GARCH-forecasted RV by >2 vol points,
  selling premium produces positive CLV over 20-day holding periods.

FILTER: All tickers where GARCH model converges and IV data available

TRADE DIRECTION: Sell ATM straddle when VRP > 2

PRIMARY METRIC: CLV_realized
PASS THRESHOLDS:
  - CLV_realized > 1.5%
  - Win rate > 55%
  - Sharpe > 0.8 (annualized)
  - Sample >= 500 trades across 3+ years and 20+ tickers

FAIL CRITERIA: CLV_realized < 0 over full sample → core thesis is broken

DATA: iv_snapshots + predictions tables (existing)
EVIDENCE: Sinclair & Mack (2024): IV > RV ~82% of time for indices
```

**H02: GARCH Beats Naive RV20**
```
Tier: 1
HYPOTHESIS: GJR-GARCH(1,1,1) produces lower QLIKE loss than 20-day
  close-to-close RV for 20-day-ahead volatility forecasting.

FILTER: All tickers with 252+ days of history

TRADE DIRECTION: Use GARCH instead of RV20 as forecast model

PRIMARY METRIC: QLIKE loss ratio (GARCH / RV20)
PASS THRESHOLDS:
  - QLIKE ratio < 0.95 (GARCH at least 5% better)
  - Diebold-Mariano p < 0.05
  - Positive in 60%+ of tickers

FAIL CRITERIA: QLIKE ratio > 1.0 (GARCH is WORSE) → use RV20 or HAR-RV

DATA: OHLCV history (yfinance proxy)
EVIDENCE: Module 1 already tests this — formalize with CLV integration
```

**H03: Signal Discrimination**
```
Tier: 1
HYPOTHESIS: GREEN signals produce higher CLV than YELLOW, which produce
  higher CLV than RED. The traffic light ordering is monotonic.

FILTER: All scored predictions

TRADE DIRECTION: Only trade GREEN (and maybe YELLOW), never RED

PRIMARY METRIC: CLV by signal tier
PASS THRESHOLDS:
  - CLV(GREEN) > CLV(YELLOW) > CLV(RED)
  - CLV(GREEN) > 2%
  - CLV(GREEN) - CLV(RED) > 1.5% (meaningful separation)
  - Each signal type has 100+ observations

FAIL CRITERIA: CLV ordering is NOT monotonic → signal logic is broken

DATA: predictions table (existing)
EVIDENCE: Backtest shows GREEN 80.3% win rate vs RED 59.9%
```

**H04: VRP Magnitude Proportional to Edge**
```
Tier: 1
HYPOTHESIS: Higher VRP produces proportionally higher CLV.
  The CLV-vs-VRP curve is monotonically increasing (not flat/noisy).

FILTER: All scored predictions with VRP data

TRADE DIRECTION: Size positions proportional to VRP magnitude

PRIMARY METRIC: Rank correlation (Spearman) of VRP vs CLV
PASS THRESHOLDS:
  - Spearman rho > 0.15
  - p < 0.01
  - CLV at VRP=6+ is at least 2x CLV at VRP=2-3

FAIL CRITERIA: Flat or negative correlation → VRP magnitude doesn't matter,
  only its sign matters (binary signal, not continuous)

DATA: predictions table
EVIDENCE: Variance betting H09 (large xG gaps → larger CLV)
```

### Tier 2: Edge Sizing

**H05: Optimal VRP Threshold**
```
Tier: 2
HYPOTHESIS: There exists an optimal minimum VRP threshold below which
  CLV turns negative or insignificant. The current threshold (VRP > 0
  for any signal, VRP-driven points for GREEN) may not be optimal.

FILTER: All scored predictions

TRADE DIRECTION: Only trade when VRP exceeds optimal threshold

PRIMARY METRIC: CLV as function of VRP threshold (plot curve)
PASS THRESHOLDS:
  - Clear breakpoint visible in CLV curve
  - Breakpoint is stable across time (first half vs second half of data)
  - Optimal threshold produces CLV > 2%

FAIL CRITERIA: CLV curve is monotonically increasing with no breakpoint
  → always trade higher VRP, no useful threshold exists (still informative)

DATA: predictions table
EVIDENCE: Variance betting H07 (optimal bet threshold exists)
```

**H06: IV Rank Threshold**
```
Tier: 2
HYPOTHESIS: IV Rank has an optimal minimum below which selling premium
  has negative or zero CLV, regardless of VRP level.

FILTER: All scored predictions with IV rank data

TRADE DIRECTION: Only sell when IV Rank > optimal threshold

PRIMARY METRIC: CLV as function of IV Rank threshold
PASS THRESHOLDS:
  - Breakpoint in CLV curve between IV Rank 15-40%
  - CLV below threshold is statistically zero or negative
  - CLV above threshold > 1.5%

FAIL CRITERIA: IV Rank has no relationship to CLV after controlling for VRP
  → drop IV Rank from signal (simplify)

DATA: predictions table
EVIDENCE: Current threshold is 30% (from Sinclair). May be wrong.
```

**H07: IV Compression as Entry Signal**
```
Tier: 2
HYPOTHESIS: When IV has already dropped >5% from its 10-day high by the
  time we generate a signal, the remaining VRP is smaller. "The line has
  already moved" — options equivalent of closing line movement.

FILTER: Tickers where IV dropped >5% in prior 10 days vs those where IV
  was stable or rising

TRADE DIRECTION: Avoid selling when IV already compressing (value extracted)

PRIMARY METRIC: CLV for "fresh high IV" vs "already compressing IV"
PASS THRESHOLDS:
  - CLV(fresh) > CLV(compressing) by > 1%
  - Difference is statistically significant (t-test p < 0.05)

FAIL CRITERIA: No difference → IV compression speed doesn't matter for CLV

DATA: iv_snapshots (compute 10-day IV trajectory per ticker)
EVIDENCE: Variance betting H08/H09 (line movement kills value)
```

### Tier 3: Model Adjustments

**H08: Vol Surface VRP > ATM VRP**
```
Tier: 3
HYPOTHESIS: Selecting strikes based on the VRP SURFACE (where IV minus
  fair value is richest) produces higher CLV than always selling ATM.

FILTER: Tickers with calibrated SABR surface (Proposal 1A)

TRADE DIRECTION: Sell at strike with highest surface VRP (often 25-30 delta puts)

PRIMARY METRIC: CLV of surface-selected trades vs ATM trades
PASS THRESHOLDS:
  - CLV uplift > 0.5% (Layer 5 incremental threshold)
  - Information Ratio vs ATM baseline > 0.3
  - Works across 50%+ of tickers

FAIL CRITERIA: Surface VRP doesn't improve CLV → ATM is fine, save complexity

DATA: vol_surface_snapshots (new) + predictions
EVIDENCE: Israelov & Kelly (2017): 30-delta puts carry 2-3x VRP of ATM
```

**H09: Bayesian Probability > Static Thresholds**
```
Tier: 3
HYPOTHESIS: Bayesian logistic regression (Proposal 3A) produces better-
  calibrated probabilities than the static point-scoring system, resulting
  in higher CLV for trades above the Bayesian threshold.

FILTER: All tickers with scored predictions (for Bayesian training)

TRADE DIRECTION: Trade when Bayesian P(seller_wins) > 70% instead of
  when static score >= 5

PRIMARY METRIC: CLV of Bayesian-selected trades vs static-selected
PASS THRESHOLDS:
  - Calibration error < 5% (predicted prob matches actual win rate)
  - CLV uplift > 0.5%
  - Out-of-sample log-likelihood improves > 5%

FAIL CRITERIA: Bayesian model is not better calibrated → static thresholds
  are fine (simpler is better)

DATA: predictions table (existing — train Bayesian on scored predictions)
EVIDENCE: Module 5 suggests signal weights are suboptimal
```

**H10: Multi-Leg > Single-Leg (Risk-Adjusted)**
```
Tier: 3
HYPOTHESIS: Iron condors and vertical spreads produce higher risk-adjusted
  CLV than naked puts/calls, because defined risk allows larger position
  sizes for the same tail risk budget.

FILTER: Tickers with liquid options chains (bid-ask < 20% of mid)

TRADE DIRECTION: Sell iron condors / vertical spreads instead of single-leg

PRIMARY METRIC: Sortino ratio of multi-leg vs single-leg
PASS THRESHOLDS:
  - Sortino(multi-leg) > Sortino(single-leg) by > 0.3
  - Max drawdown < 50% of single-leg max drawdown
  - Gross CLV may be lower (narrower spreads) but net CLV after sizing is higher

FAIL CRITERIA: Bid-ask spread on multi-leg structures destroys the edge
  → single-leg with defined-risk via portfolio sizing is better

DATA: Options chains (for structure pricing) + historical backtest
EVIDENCE: NVDA -285% max drawdown on single-leg; iron condor caps at wing width
```

**H11: HAR-RV + GARCH Blend**
```
Tier: 3
HYPOTHESIS: The optimal forecast is a weighted blend of GARCH and HAR-RV
  (per Module 1D encompassing regression), not either model alone.

FILTER: Tickers where both models converge

TRADE DIRECTION: Use blended forecast for VRP computation

PRIMARY METRIC: QLIKE loss of blend vs individual models
PASS THRESHOLDS:
  - Blend QLIKE < min(GARCH QLIKE, HAR-RV QLIKE)
  - Improvement > 3% over best individual model
  - Stable weights (blend ratio doesn't swing wildly quarter-to-quarter)

FAIL CRITERIA: One model dominates → use that model alone (simpler)

DATA: OHLCV history
EVIDENCE: Module 1D already tests this — formalize as hypothesis
```

**H12: Regime Filter Adds Value**
```
Tier: 3
HYPOTHESIS: Excluding trades during unfavorable regimes (High Vol, Crisis)
  improves CLV compared to trading all GREEN signals regardless of regime.

FILTER: All GREEN signals, split by regime

TRADE DIRECTION: Trade GREEN only in Low Vol and Normal regimes

PRIMARY METRIC: CLV(filtered) vs CLV(unfiltered)
PASS THRESHOLDS:
  - CLV uplift > 0.5%
  - Not just reducing sample size (must beat random exclusion — Module 5C test)
  - z-test p < 0.05 vs random exclusion

FAIL CRITERIA: Regime filter doesn't beat random exclusion → regime adds
  no information beyond what VRP already captures

DATA: predictions table (regime column exists)
EVIDENCE: Module 5C designed to test exactly this
```

**H13: Earnings Exclusion**
```
Tier: 3
HYPOTHESIS: Excluding trades within 5 days of earnings announcements
  improves CLV because event vol is often justified (not overpriced).

FILTER: Predictions where earnings_days <= 5 vs earnings_days > 5

TRADE DIRECTION: Skip all trades within 5 days of earnings

PRIMARY METRIC: CLV(no-earnings) vs CLV(near-earnings)
PASS THRESHOLDS:
  - CLV(near-earnings) < CLV(no-earnings) by > 1%
  - Or: CLV(near-earnings) < 0 (selling into earnings is net-negative)
  - Statistically significant (t-test p < 0.05)

FAIL CRITERIA: No difference → earnings vol is also overpriced (interesting finding!)

DATA: predictions table (earnings_days column exists from batch_sampler)
EVIDENCE: Post-earnings vol crush is a known pattern but pre-earnings
  selling may be priced correctly by market makers
```

**H14: FOMC Exclusion**
```
Tier: 3
HYPOTHESIS: Excluding trades within 2 days of FOMC announcements improves
  CLV because macro event risk is often justified.

FILTER: Predictions where fomc_days <= 2 vs fomc_days > 2

TRADE DIRECTION: Skip all trades within 2 days of FOMC

PRIMARY METRIC: CLV split
PASS THRESHOLDS:
  - CLV(near-FOMC) significantly lower than CLV(away-from-FOMC)
  - Note: sample size will be small (~8 FOMC per year * 350 tickers = ~2800,
    but only those with GREEN signal, so maybe ~500-800)

FAIL CRITERIA: No difference → FOMC risk is already overpriced in IV
  (which would mean FOMC days are actually GOOD times to sell)

DATA: predictions table (fomc_days column exists)
EVIDENCE: Module 8C already uses FOMC as circuit breaker input
```

**H15: Term Structure as Independent Signal**
```
Tier: 3
HYPOTHESIS: Term structure (contango vs backwardation) provides independent
  predictive power for CLV beyond what VRP and IV Rank capture.

FILTER: All scored predictions

TRADE DIRECTION: Sell only in contango; never sell in backwardation

PRIMARY METRIC: Fama-MacBeth regression coefficient on term_structure
  after controlling for VRP and IV Rank
PASS THRESHOLDS:
  - Term structure coefficient significant (t > 2.0)
  - VIF < 5 (not just proxying for VRP)
  - CLV(contango) - CLV(backwardation) > 2%

FAIL CRITERIA: Term structure coefficient insignificant after controlling
  for VRP → it's redundant (drop from signal for simplicity)

DATA: predictions table (term_label exists)
EVIDENCE: Current signal already uses term structure, but Module 5 VIF
  may show it's redundant with VRP
```

**H16: Skew-Adjusted Kelly > Fixed Quarter-Kelly**
```
Tier: 3
HYPOTHESIS: Position sizing that accounts for empirical skewness (reducing
  size for negatively-skewed P&L distributions) produces better risk-
  adjusted returns than fixed 25% Kelly.

FILTER: Tickers with 50+ scored predictions (enough for skew estimate)

TRADE DIRECTION: Size = min(kelly * (1 / (1 + |skew|)), 0.25 * kelly, 5%)

PRIMARY METRIC: Sortino ratio of skew-adjusted vs fixed sizing
PASS THRESHOLDS:
  - Sortino improvement > 0.2
  - Max drawdown reduction > 10%
  - Total P&L not significantly lower (sizing reduction isn't too aggressive)

FAIL CRITERIA: Skew adjustment reduces P&L more than it reduces drawdown
  → fixed quarter-Kelly is fine

DATA: predictions table (pnl_pct for computing skew per ticker)
EVIDENCE: Module 7 spec; standard quant finance result
```

### Tier 4: Situational Modifiers (Monitor, Don't Formally Test Yet)

These have insufficient sample size for formal testing but should be tagged on every prediction for future analysis:

**H17: Day-of-Week Effect**
- Tag: day_of_week on each prediction
- Hypothesis: Monday entries have higher CLV than Friday (weekend theta)
- Minimum for formal test: 2 years of daily data

**H18: Sector Rotation Effect**
- Tag: sector on each prediction
- Hypothesis: When sector is in "rotation out" phase, IV is temporarily overpriced
- Minimum: 2 years + sector classification

**H19: VIX Term Structure Slope as Timing Signal**
- Tag: vix_slope (VIX - VIX3M) on each prediction
- Hypothesis: Steep contango (VIX << VIX3M) = complacency → sell less; inversion = fear → sell more (contrarian)
- Minimum: 2 years with VIX data

**H20: Post-FOMC Vol Crush as Predictable Pattern**
- Tag: days_after_fomc on each prediction
- Hypothesis: The 2-3 days after FOMC consistently show IV compression → sell INTO FOMC meeting, not after
- Minimum: 3 years (24+ FOMC meetings)

**H21: Earnings Vol Crush Timing**
- Tag: days_after_earnings on each prediction
- Hypothesis: Selling 1-2 days before earnings and closing day-of captures vol crush
- Minimum: 2 years, many tickers

**H22: Put-Call Ratio Extremes as Contrarian Signal**
- Tag: put_call_ratio (if obtainable)
- Hypothesis: Extreme put buying = fear overpriced → sell puts
- Minimum: 2 years with ratio data

**H23: Skew Steepness as Independent Signal**
- Tag: skew_25d (already captured)
- Hypothesis: When 25-delta put skew is >2 standard deviations above normal, puts are overpriced
- Minimum: 1 year of skew data per ticker

---

# Part V: The 10-Layer Testing Gate

Adapted from variance_betting's pod-shop framework. Every new signal must pass all 10 layers before receiving real capital.

## Layer 1: Data Store

**Purpose**: Ensure all data is point-in-time with no future leakage.

**Requirements:**
- Every feature must exist BEFORE the trade decision date
- iv_snapshots table timestamps all readings
- predictions table records entry conditions at trade time
- No computed features can use data from after entry date

**Checks:**
```python
def validate_no_lookahead(predictions_df):
    """Verify no feature uses future data."""
    for idx, row in predictions_df.iterrows():
        entry_date = row['date']
        # rv_forecast must use only data before entry_date
        # iv_rank must use only historical IV before entry_date
        # outcome fields must be NULL until scored
        assert row['outcome_date'] is None or row['outcome_date'] > entry_date
        assert row['scored'] == 0 or row['outcome_date'] is not None
```

**Tables:**
| Table | Exists? | Purpose |
|-------|---------|---------|
| iv_snapshots | Yes | Daily IV/RV/VRP readings |
| predictions | Yes | Signal log with outcomes |
| vol_surface_snapshots | New | SABR params per expiry |
| signal_graveyard | New | All tested signals (pass + fail) |
| clv_tracking | Embedded in predictions | CLV columns added |
| deployment_stage | New | Current stage per signal |

## Layer 2: Frozen Flagship

**Purpose**: Immutable baseline during research. All new signals tested against this.

**The Flagship:**
```
calc_vrp_signal() as of commit [hash] on [date]
- VRP score: 0-3 points based on magnitude
- IV Rank score: 0-2 points based on percentile
- Term Structure score: 0-2 points based on contango/flat/backwardation
- Total >= 5 = GREEN, 3-4 = YELLOW, <3 = RED
- Regime overrides: Crash → RED, High Vol caps at YELLOW
```

**Rules:**
- Flagship is NEVER modified while testing a new signal
- Fork analytics.py for experimental signal logic
- Flagship retrained on fixed schedule (quarterly, not ad-hoc)
- All incremental tests (Layer 5) compare to flagship

**Retrain triggers (from INFRASTRUCTURE_IMPROVEMENTS.md):**
- Quarterly schedule (Jan, Apr, Jul, Oct)
- After major regime change (sustained VIX > 35 for 10+ days)
- Feature drift (PSI > 0.2 for 2+ consecutive weeks)

## Layer 3: Walk-Forward Engine

**Purpose**: Out-of-sample validation that prevents overfitting.

**Upgrade from current Module 4:**

Current (fixed window):
```
Train: 756 days, Test: 126 days, Step: 63 days
```

Upgraded (expanding window, like variance_betting):
```
Step 1: Train [Day 1..Day 252] → Test [Day 258..Day 378]  (5-day embargo)
Step 2: Train [Day 1..Day 315] → Test [Day 321..Day 441]
Step 3: Train [Day 1..Day 378] → Test [Day 384..Day 504]
...
Continue until data exhausted
```

**Why expanding > fixed:**
- Expanding window uses ALL available history (more data = better estimates)
- Fixed window throws away old data (wasteful)
- Expanding mimics actual deployment: you train on everything you have

**5-day embargo**: Options settle over days, not instantly. Skip 5 trading days between train end and test start to prevent information leakage from overlapping holding periods.

**Multi-ticker pooling**: Like variance_betting's multi-league approach:
```
IR = IC x sqrt(BR)

Single ticker (SPY): IC=0.05, BR=60 trades/year, IR=0.39
20 tickers: IC=0.05, BR=1200 trades/year, IR=1.73
```
Pool predictions across tickers for more robust statistics.

**Warm-start GARCH**: Use previous window's parameters as initialization (2-3 iterations vs 200 — massive speedup, from variance_betting practical spec).

## Layer 4: Standalone Alpha Test

**Purpose**: Does this signal produce positive CLV on its own?

**Pass/Fail Thresholds:**
| Metric | Threshold | Rationale |
|--------|-----------|-----------|
| Average CLV | > 1.5% | Must beat transaction costs |
| Win rate | > 55% | Better than coin flip |
| Sharpe (annualized) | > 0.8 | Meaningful risk-adjusted return |
| Sortino (annualized) | > 1.0 | Accounts for downside skew |
| Brier score | Better than closing IV | Model beats market |
| Deflated Sharpe | > 0 | Survives multiple testing correction |
| Sample size | >= 200 trades, 2+ years | Statistical validity |

**Implementation:**
```python
def standalone_alpha_test(signal_predictions: pd.DataFrame) -> dict:
    """
    Layer 4: Does this signal work alone?

    signal_predictions: DataFrame with columns
      [date, ticker, signal, clv_market, clv_realized, pnl_pct, seller_won]
    """
    # Only test on out-of-sample predictions
    trades = signal_predictions[signal_predictions['signal'] == 'GREEN']

    avg_clv = trades['clv_realized'].mean()
    win_rate = trades['seller_won'].mean()
    sharpe = trades['pnl_pct'].mean() / trades['pnl_pct'].std() * np.sqrt(252/20)
    sortino = compute_sortino(trades['pnl_pct'])

    # Deflated Sharpe (adjusts for number of signals tested)
    n_trials = get_signal_graveyard_count()  # total signals ever tested
    dsr = deflated_sharpe_ratio(sharpe, n_trials, len(trades),
                                 trades['pnl_pct'].skew(),
                                 trades['pnl_pct'].kurtosis())

    passed = (avg_clv > 0.015
              and win_rate > 0.55
              and sharpe > 0.8
              and sortino > 1.0
              and dsr > 0
              and len(trades) >= 200)

    return {
        'passed': passed,
        'avg_clv': avg_clv,
        'win_rate': win_rate,
        'sharpe': sharpe,
        'sortino': sortino,
        'deflated_sharpe': dsr,
        'n_trades': len(trades),
        'details': '...'
    }
```

## Layer 5: Incremental Alpha Test

**Purpose**: Does adding this signal improve the flagship?

Not enough to work alone — it must add something the flagship doesn't already capture.

**Methods (from variance_betting):**

**Method A: Jensen's Alpha Regression**
```
R_new = alpha + beta * R_flagship + epsilon

PASS if:
  alpha > 0 AND t-stat > 2.0 (signal adds independent value)
  beta < 0.5 (not just a leveraged version of flagship)
  R-squared < 0.3 (genuinely independent)
```

**Method B: CLV Uplift**
```
CLV_combined = CLV when using flagship + new signal for trade selection
CLV_flagship = CLV when using flagship alone

Uplift = CLV_combined - CLV_flagship

PASS if:
  Uplift > 0.5%
  Max drawdown doesn't worsen by > 20%
  Information Ratio > 0.3
```

**Method C: GRS Spanning Test (from INFRASTRUCTURE_IMPROVEMENTS.md)**
```
Does the new signal expand the efficient frontier?
Gibbons-Ross-Shanken F-test on the tangency portfolio.

PASS if: F-statistic significant at p < 0.05
```

## Layer 6: Orthogonality Test

**Purpose**: Is this signal independent, or just repackaged VRP?

**This is critical because** VRP, IV Rank, term structure, regime, and skew are all correlated (Module 5B). A "new" signal that's just VRP * 1.1 adds nothing.

**Regression-Based Test (upgraded from simple correlation):**
```python
def orthogonality_test(new_signal, existing_signals):
    """
    Regress new signal on all existing signals.
    If residual still predicts CLV, the signal adds independent info.
    """
    # Step 1: Regress new signal on existing
    X = existing_signals  # [vrp, iv_rank, term, regime, skew]
    y = new_signal
    model = OLS(y, add_constant(X)).fit()
    residual = model.resid

    # Step 2: Does residual predict CLV?
    clv_model = OLS(clv, add_constant(residual)).fit()

    passed = (clv_model.pvalues[1] < 0.05  # residual is significant
              and abs(model.rsquared) < 0.7  # not fully explained by existing
              )

    return {
        'passed': passed,
        'correlation_with_existing': correlation_matrix,
        'residual_predicts_clv': clv_model.pvalues[1] < 0.05,
        'r_squared_with_existing': model.rsquared,
    }
```

**Kill thresholds:**
| Correlation with existing | Decision |
|---|---|
| > 0.7 | Kill — redundant |
| 0.3 - 0.7 | Proceed with caution; must pass residual test |
| < 0.3 | Promote — genuinely independent |

## Layer 7: Stability Test

**Purpose**: Does the signal work across different conditions?

**The Stability Matrix (equivalent of variance_betting's league matrix):**

```
                  SPY   QQQ   AAPL  MSFT  NVDA  JPM   XOM  ... OVERALL
CLV (all)        +2.1  +1.8  +2.5  +1.9  +3.2  +1.1  +0.8    +1.9
CLV (GREEN)      +3.5  +3.1  +4.2  +3.0  +5.1  +2.3  +1.5    +3.2
Win Rate         72%   71%   74%   73%   68%   66%   64%      70%
Sharpe           1.4   1.3   1.6   1.4   0.9   0.8   0.6      1.1
```

**Cross-cuts (must be profitable in EACH):**
| Dimension | Requirement |
|---|---|
| Time: by year | Profitable in 3+ of 5 years |
| Tickers: by name | Profitable in 60%+ of tickers |
| Regime: low/normal/high vol | Profitable in at least 2 of 3 regimes |
| IV level: high/medium/low IV names | Works in at least 2 of 3 categories |
| Sector: tech/finance/energy/etc | Not concentrated in one sector |

**Split-half validation**: Split out-of-sample data into two random halves. Both must be profitable. If only one half works, the signal is overfitting to a specific time period.

## Layer 8: Production Simulation

**Purpose**: Is the signal profitable after real-world execution friction?

**Realistic cost model:**
```python
def simulate_production(trades, cost_params):
    """
    Apply real-world friction to backtest results.
    """
    for trade in trades:
        # Bid-ask spread (per leg)
        spread_cost = trade.n_legs * trade.avg_spread * 0.5  # cross half the spread
        # Commission
        commission = trade.n_legs * trade.contracts * 0.65  # $0.65/contract
        # Slippage (market orders, partial fills)
        slippage = trade.credit * 0.02  # 2% of credit
        # Timing slippage (signal generated at 3:55 PM, executed next morning)
        timing_slip = trade.vega * 0.5  # half a vol point of adverse IV movement

        total_friction = spread_cost + commission + slippage + timing_slip
        trade.net_pnl = trade.gross_pnl - total_friction

    # Metrics after friction
    net_clv = trades.net_pnl.mean() / trades.notional.mean()
    net_sharpe = ...
    max_dd = ...

    return {
        'passed': net_clv > 0.01 and net_sharpe > 0.5 and max_dd > -0.20,
        'gross_clv': gross_clv,
        'net_clv': net_clv,
        'friction_pct': (gross_clv - net_clv) / gross_clv,
    }
```

**Pass thresholds:**
| Metric | Threshold |
|--------|-----------|
| Net CLV (after all friction) | > 1.0% |
| Net Sharpe | > 0.5 |
| Max drawdown | > -20% |
| Recovery factor (total P&L / |max DD|) | > 1.5 |
| Trades per month | >= 5 (enough to compound) |

## Layer 9: Portfolio Construction

**Purpose**: How to allocate capital across surviving signals.

**Phase 1 (Years 1-2): Equal Weight**

From DeMiguel, Garlappi & Uppal (2009): naive equal-weight beats mean-variance optimization unless you have 3,000+ months of data. We won't have that for years.

```python
def equal_weight_allocation(surviving_signals, total_capital, max_per_position=0.05):
    """
    Equal weight across all qualifying trades.
    Each trade gets the same notional allocation.
    Cap at 5% of portfolio per position.
    """
    n_trades = len(qualifying_trades)
    per_trade = min(total_capital / n_trades, total_capital * max_per_position)
    return {trade: per_trade for trade in qualifying_trades}
```

**Phase 2 (Years 2-3): Inverse-Variance Weighting**
```python
def inverse_variance_allocation(trades, historical_vol):
    """
    Weight inversely proportional to historical P&L volatility.
    High-vol names (NVDA) get smaller positions; low-vol (SPY) get larger.
    """
    inv_var = 1.0 / historical_vol
    weights = inv_var / inv_var.sum()
    return weights * total_capital
```

**Phase 3 (Years 3+): Copula-Optimized (Proposal 4)**
```python
# Full CVaR-constrained optimization using vine copula
# Only after 2+ years of copula data
```

**Signal-Level Allocation:**
- Kill signals with rolling 6-month IR < 0.3
- Kill signals correlated > 0.5 with another surviving signal
- Cap any single signal at 40% of capital
- Rebalance quarterly

## Layer 10: Live Paper Trading & Decay Monitoring

**Purpose**: Validate in real-time before risking real capital.

### 5-Stage Deployment Protocol

```
Stage 0: SHADOW (3 months minimum)
  - Model generates recommendations daily
  - No capital deployed
  - Track: would-have-been CLV, P&L, Sharpe
  - Gate to Stage 1: CLV > 1%, Sharpe > 0.5, no month with CLV < -3%

Stage 1: 10% CAPITAL (3 months minimum)
  - 10% of portfolio follows this signal
  - 90% follows existing strategy (or cash)
  - Gate to Stage 2: same as Stage 0 gates, on LIVE data

Stage 2: 25% CAPITAL (3 months minimum)
  - Gate to Stage 3: same gates, plus max DD < 10%

Stage 3: 50% CAPITAL (6 months minimum)
  - Gate to Stage 4: same gates, plus net Sharpe > 0.8

Stage 4: 100% CAPITAL (ongoing)
  - Full deployment
  - Continuous monitoring (see below)
```

**Kill Switch:**
```python
def check_kill_switch(rolling_metrics):
    """
    Automatic reversion if performance degrades.
    """
    rolling_clv_30d = rolling_metrics['clv'].rolling(30).mean().iloc[-1]
    rolling_sharpe_30d = rolling_metrics['sharpe_30d'].iloc[-1]
    current_dd = rolling_metrics['drawdown'].iloc[-1]

    if rolling_clv_30d < 0 and days_below_zero >= 60:
        return "KILL — revert to previous stage"
    if current_dd < -0.20:
        return "KILL — max drawdown breached"
    if rolling_sharpe_30d < -0.5:
        return "KILL — negative Sharpe for 30 days"

    if rolling_clv_30d < 0.005:
        return "ALERT — CLV declining, monitor closely"

    return "OK"
```

### 4-Layer Production Monitoring Stack

```
Layer A: DATA QUALITY
  - Are IV snapshots arriving daily? (batch_sampler health)
  - Any tickers missing for >3 days?
  - Options chain data fresh? (proxy working?)
  - ALERT: >5% of tickers missing

Layer B: FEATURE DRIFT (Population Stability Index)
  - Compare VRP distribution this month vs baseline
  - Compare IV Rank distribution
  - PSI > 0.1 = drift worth investigating
  - PSI > 0.2 for 2+ weeks = trigger model retrain

Layer C: PREDICTION DRIFT
  - Is the model systematically overconfident/underconfident?
  - Track: average predicted probability vs actual win rate (calibration)
  - ECE (Expected Calibration Error) > 5% = recalibrate
  - Proportion of GREEN signals shifting? (market regime change?)

Layer D: PERFORMANCE DECAY
  - CUSUM from Module 8A (already exists)
  - Rolling 30-day CLV (new — primary metric)
  - Rolling Sharpe
  - Comparison: current period vs historical average
  - ALERT if CLV_current < 0.5 * CLV_historical for 4+ weeks
```

---

# Part VI: Signal Graveyard & Deflated Sharpe

## The Graveyard

**Every signal idea gets logged, whether it passes or fails.** This is critical for Deflated Sharpe Ratio — without knowing how many signals you tested, you can't correct for multiple testing.

From INFRASTRUCTURE_IMPROVEMENTS.md: "The single most dangerous omission is not tracking failed signals."

**Table: signal_graveyard**
```sql
CREATE TABLE signal_graveyard (
    signal_id TEXT PRIMARY KEY,
    name TEXT,
    hypothesis TEXT,
    pre_registered_date TEXT,
    tested_date TEXT,
    status TEXT,  -- 'passed', 'failed_layer_4', 'failed_layer_5', etc.
    layer_reached INTEGER,  -- highest layer passed (1-10)
    best_sharpe REAL,
    best_clv REAL,
    n_trades INTEGER,
    failure_reason TEXT,
    notes TEXT
);
```

**Deflated Sharpe Ratio:**
```python
def deflated_sharpe_ratio(sharpe_observed, n_trials, n_obs, skew=0, kurtosis=3):
    """
    From Bailey & Lopez de Prado (2014).
    Adjusts observed Sharpe for number of strategies tested.

    n_trials = total entries in signal_graveyard (ALL tested, pass + fail)
    """
    euler_gamma = 0.5772156649
    e = 2.718281828

    # Expected maximum Sharpe under null (no real edge, just noise)
    e_max_sharpe = ((1 - euler_gamma) * norm.ppf(1 - 1/n_trials)
                    + euler_gamma * norm.ppf(1 - 1/(n_trials * e)))

    # Standard error of Sharpe estimate
    se_sharpe = np.sqrt((1 + 0.5 * sharpe_observed**2
                         - skew * sharpe_observed
                         + (kurtosis - 3) / 4 * sharpe_observed**2)
                        / n_obs)

    # Probability that observed Sharpe is real (not noise)
    dsr = norm.cdf((sharpe_observed - e_max_sharpe) / se_sharpe)
    return dsr  # > 0.95 = likely real; < 0.50 = likely noise
```

**Example**: If you've tested 20 signals (15 failed, 5 passed) and the best has Sharpe 1.5 over 500 trades:
- Without correction: "Sharpe 1.5! Amazing!"
- With DSR: "Expected max Sharpe from 20 random tests is ~1.3. Your 1.5 has DSR = 0.72 — probably real but not certain."

If you tested 50 signals and the best has Sharpe 1.5:
- Expected max from 50 random: ~1.6
- DSR = 0.38 — **probably noise**

This is why the graveyard matters. Without it, you think you found alpha. With it, you know you're just data mining.

---

# Part VII: The Discipline Framework

## When NOT to Trade

Mapped from Ted Knutson's playbook (Section 10: "Discipline is Edge"):

| # | Condition | Action | Options Equivalent | Playbook Source |
|---|-----------|--------|-------------------|----------------|
| 1 | VRP < 2 vol points | PASS | Edge too thin; transaction costs eat it | "10 cents of play" |
| 2 | IV Rank < 25% | PASS | Premiums too cheap to sell | "Line is fair" |
| 3 | Backwardation | PASS | Market pricing near-term risk | "Both teams chaotic" |
| 4 | Within 2 days of FOMC | PASS | Macro event risk | "International break" |
| 5 | Within 5 days of earnings | PASS | Event vol often justified | "Insufficient information" |
| 6 | VIX > 35 | REDUCE 50% | Extreme regime | "Championship chaos — reduce stake" |
| 7 | VIX > 45 | HALT all new | Survival mode | "Financial concerns — OFF LIMITS" |
| 8 | Portfolio vega at limit | PASS | Risk budget exhausted | "Bankroll guidelines" |
| 9 | < 10 DTE | PASS | Gamma risk too high | "Overperformance on your side" |
| 10 | IV already compressing | CAUTION | "Line has moved" | "Line already moved past value" |
| 11 | Both signals disagree | PASS or FLAG | Model says sell, forecast says don't | "Me bet" flag |
| 12 | Edge comes from one factor only | CAUTION | VRP high but IV Rank low, term flat | "Marginal bet" |

## Pass Rate Tracking

**Ted's pass rate: ~70% (only bets ~30% of analyzed matches)**

For options:
- Track: `signals_generated` vs `trades_recommended` per day
- Target pass rate: 55-70% (trade 30-45% of GREEN signals after all filters)
- Alert if pass rate < 40% (too aggressive — not enough edge per trade)
- Alert if pass rate > 85% (too conservative — leaving money on table, or market correctly priced)

```python
def track_pass_rate(daily_signals):
    """
    Monitor trading discipline.
    """
    green_signals = daily_signals[daily_signals['signal'] == 'GREEN']
    traded = green_signals[green_signals['traded'] == True]

    pass_rate = 1 - len(traded) / len(green_signals)

    if pass_rate < 0.40:
        alert("DISCIPLINE WARNING: Trading too many signals ({:.0%}). "
              "Tighten filters or raise minimum edge threshold.".format(1-pass_rate))
    elif pass_rate > 0.85:
        alert("DISCIPLINE NOTE: Passing on {:.0%} of GREEN signals. "
              "Check if filters are too tight or market is correctly priced.".format(pass_rate))

    return {
        'date': today,
        'green_signals': len(green_signals),
        'trades_taken': len(traded),
        'pass_rate': pass_rate,
    }
```

## The Override Flag

From variance_betting: "Me bet, not Model bet"

When the human disagrees with the model:
```python
def log_override(prediction_id, override_direction, reason):
    """
    Record when human overrides model recommendation.

    override_direction: 'trade_despite_red' or 'pass_despite_green'
    reason: free text explanation

    Track over time:
    - Does overriding the model produce better or worse CLV?
    - If human overrides consistently lose → stop overriding
    - If human overrides consistently win → model is missing something
    """
    db.insert('overrides', {
        'prediction_id': prediction_id,
        'override_direction': override_direction,
        'reason': reason,
        'date': today,
    })
```

Track override performance separately. If overrides underperform the model over 50+ instances, the human should stop overriding. If overrides outperform, the model is missing a feature the human sees.

---

# Part VIII: Integration Map

## New Files to Create

| File | Lines (est.) | Purpose |
|------|-------------|---------|
| `signal_registry.py` | ~200 | Pre-registration template, hypothesis tracking |
| `clv_tracker.py` | ~150 | CLV computation, CLV-based metrics |
| `testing_gate.py` | ~600 | 10-layer validation pipeline |
| `discipline.py` | ~200 | Pass rate tracking, "when NOT to trade", override logging |
| `deployment.py` | ~300 | 5-stage deployment state machine, kill switch |
| `monitoring.py` | ~400 | 4-layer production monitoring (data/feature/prediction/performance) |

## Modifications to Existing Files

| File | Change | Scope |
|------|--------|-------|
| `db.py` | Add CLV columns to predictions, add signal_graveyard table, add deployment_stage table, add overrides table | ~50 lines added |
| `batch_sampler.py` | Record pass/trade decisions, tag Tier 4 hypothesis features (day_of_week, etc.) | ~30 lines added |
| `analytics.py` | Extract signal computation into registerable/testable components | ~100 lines refactored |
| `streamlit_app.py` | Add CLV dashboard tab, pass rate display, signal graveyard viewer, deployment stage indicator | ~200 lines added |
| `eval_backtest.py` | Upgrade to expanding window, add CLV as primary metric | ~80 lines modified |

## New Supabase Tables

```sql
-- Signal Graveyard: every hypothesis ever tested
CREATE TABLE signal_graveyard (
    signal_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    tier INTEGER,
    hypothesis TEXT,
    pre_registered_date TEXT NOT NULL,
    tested_date TEXT,
    status TEXT DEFAULT 'untested',
    layer_reached INTEGER DEFAULT 0,
    best_sharpe REAL,
    best_clv REAL,
    n_trades INTEGER,
    failure_reason TEXT,
    notes TEXT
);

-- Deployment Stages: current stage per signal
CREATE TABLE deployment_stages (
    signal_id TEXT PRIMARY KEY,
    current_stage INTEGER DEFAULT 0,  -- 0=shadow, 1=10%, 2=25%, 3=50%, 4=100%
    stage_entered_date TEXT,
    capital_pct REAL DEFAULT 0,
    rolling_clv_30d REAL,
    rolling_sharpe_30d REAL,
    max_drawdown REAL,
    kill_switch_active BOOLEAN DEFAULT FALSE
);

-- Override Log: when human disagrees with model
CREATE TABLE overrides (
    id SERIAL PRIMARY KEY,
    prediction_id INTEGER REFERENCES predictions(id),
    override_direction TEXT,  -- 'trade_despite_red', 'pass_despite_green'
    reason TEXT,
    date TEXT,
    outcome_clv REAL  -- filled in after scoring
);

-- Pass Rate History: daily discipline tracking
CREATE TABLE pass_rate_history (
    date TEXT PRIMARY KEY,
    green_signals INTEGER,
    trades_taken INTEGER,
    pass_rate REAL,
    avg_edge_traded REAL,
    avg_edge_passed REAL
);
```

## New GitHub Actions Workflow

```yaml
# .github/workflows/monitoring.yml
name: Daily Monitoring
on:
  schedule:
    - cron: '0 2 * * 1-5'  # 10 PM ET weekdays (after scoring completes)
  workflow_dispatch:

jobs:
  monitor:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r requirements.txt
      - name: Run monitoring stack
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}
        run: |
          python -c "
          from monitoring import run_full_monitoring_stack
          alerts = run_full_monitoring_stack()
          for alert in alerts:
              print(f'ALERT [{alert.level}]: {alert.message}')
          if any(a.level == 'CRITICAL' for a in alerts):
              exit(1)
          "
```

---

# Part IX: Implementation Roadmap

## Phase 0: Foundation (Weeks 1-2)

**Goal**: CLV tracking operational. This is the single biggest unlock.

- [ ] Add CLV columns to predictions table (`iv_at_scoring`, `clv_market`, `clv_realized`)
- [ ] Modify `score_pending_predictions()` in db.py to compute CLV at scoring time
- [ ] Fetch IV at scoring date from iv_snapshots table
- [ ] Add CLV display to Streamlit scorecard tab (avg CLV by signal, rolling 30-day CLV)
- [ ] Create `signal_graveyard` table in Supabase
- [ ] Pre-register H01-H04 in signal_graveyard (before any analysis!)

**Deliverable**: Can answer "what is our average CLV?" for the first time.

## Phase 1: The Gate (Month 1)

**Goal**: Testing infrastructure operational.

- [ ] Create `signal_registry.py` with pre-registration template
- [ ] Create `testing_gate.py` with Layers 1-7
- [ ] Create `discipline.py` with pass rate tracking
- [ ] Create `clv_tracker.py` with CLV computation functions
- [ ] Modify `batch_sampler.py` to record pass/trade decisions
- [ ] Run H01-H04 through Layers 1-7 using existing scored predictions
- [ ] Document results in signal_graveyard

**Deliverable**: Know whether core VRP thesis passes formal validation with CLV as primary metric.

## Phase 2: First Signals Through the Gate (Months 2-3)

**Goal**: Test edge-sizing and model adjustment hypotheses.

- [ ] Pre-register and test H05-H08 (edge sizing)
- [ ] Pre-register and test H09-H16 (model adjustments)
- [ ] Build stability matrix across tickers and regimes
- [ ] Implement Deflated Sharpe with graveyard count
- [ ] Upgrade eval_backtest.py to expanding window with CLV

**Deliverable**: Know which signal components actually drive CLV, which are redundant. Signal graveyard has 10+ entries.

## Phase 3: New Signals (Months 3-6)

**Goal**: Develop and test Proposal 1A (SABR) and Proposal 3A (Bayesian).

- [ ] Implement SABR calibration (Proposal 1A from VISION_SPEC.md)
- [ ] Pre-register H08 (vol surface VRP) and test through gate
- [ ] Implement Bayesian logistic regression (Proposal 3A)
- [ ] Pre-register H09 (Bayesian probability) and test through gate
- [ ] Winning signals enter Stage 0 (shadow trading)

**Deliverable**: New signals validated or killed through formal process.

## Phase 4: Staged Deployment (Months 6-12)

**Goal**: Move validated signals through deployment stages.

- [ ] Implement `deployment.py` with 5-stage state machine
- [ ] Implement `monitoring.py` with 4-layer stack
- [ ] Add monitoring GitHub Action
- [ ] Implement production simulation (Layer 8)
- [ ] Begin Stage 1 (10% capital) for first passing signal
- [ ] Begin portfolio construction (equal weight)

**Deliverable**: Real capital following validated, monitored signals.

## Phase 5: Advanced (Year 2+)

**Goal**: Full vision from VISION_SPEC.md through the testing gate.

- [ ] Multi-leg optimizer (Proposal 2) through gate as H10
- [ ] Copula model (Proposal 4) for portfolio optimization
- [ ] Upgrade portfolio construction from equal-weight to copula-optimized
- [ ] RL agent (Proposal 5) development begins
- [ ] System has 2+ years of CLV history and 20+ graveyard entries

**Deliverable**: Multiple independent signals surviving the gate, portfolio-optimized allocation, continuous learning loop operational.

---

# Part X: What Wrong Looks Like (Process Anti-Patterns)

| # | Anti-Pattern | Symptom | Root Cause | Fix |
|---|---|---|---|---|
| 1 | **Data Mining Masquerading as Research** | "We found 12 signals that work!" but DSR shows most are noise | No pre-registration, no graveyard | Mandatory pre-reg before data touch; DSR with full graveyard count |
| 2 | **CLV-Blind Optimization** | "Win rate is 80%!" but selling at worse IV than where it settles | Optimizing win rate instead of CLV | CLV is primary metric everywhere; win rate is secondary |
| 3 | **Overfitting to Backtest** | Signal has Sharpe 3.0 in backtest, 0.2 in shadow | Fixed window, no expanding; or too many parameters | Walk-forward expanding window; Layers 4-7 stability checks |
| 4 | **Overtrading** | Trading 80% of signals because "they're all GREEN" | No pass rate tracking; no minimum edge enforcement | Track pass rate; alert if >60%; enforce VRP > 2 minimum |
| 5 | **Premature Complexity** | Mean-variance optimization on 6 months of data | Skipping DeMiguel finding about sample size requirements | Equal weight for 2+ years; inverse-variance at year 2; copula at year 3+ |
| 6 | **Skipping Shadow** | "Backtest looks great, let's go 100%" | Impatience; confidence in backtest results | Mandatory 3 months shadow minimum; gates between every stage |
| 7 | **Moving the Goalposts** | "Signal failed Layer 4 but I'll adjust the threshold and retest" | Post-hoc rationalization; adjusting until it passes | Pre-registered thresholds are final. If it fails, it fails. Log in graveyard. |
| 8 | **Modifying Flagship During Testing** | "I'll just tweak VRP weights while testing the new signal" | Contaminating baseline | Flagship is FROZEN in a specific commit. Fork for testing. |
| 9 | **Ignoring the Graveyard** | "We've only tested 3 signals" (actually tested 30, didn't log failures) | No tracking infrastructure | Every idea logged on creation, not on completion |
| 10 | **Ignoring Regime Stability** | "Works great 2023-2025!" (all low vol) | Testing on one regime; assuming it generalizes | Layer 7 requires profitability in 2+ regimes |
| 11 | **Using P&L as Primary Metric** | "We made $50K!" (on 2,000 trades with negative CLV — pure luck) | P&L has huge variance; misleading in small samples | CLV first, always. P&L is confirmation, not evidence. |
| 12 | **No Kill Switch** | Signal decays for 6 months, still running at 100% | No automated monitoring; no reversion trigger | Rolling 30-day CLV < 0 for 60 days → automatic stage reversion |

---

# Appendix: Mapping to Existing Eval Modules

| Eval Module | Testing Gate Layer | Status | Integration |
|---|---|---|---|
| Module 1 (GARCH Forecast) | Layer 3 (walk-forward) | Complete | Upgrade to expanding window |
| Module 2 (P&L Scoring) | Layer 1 (data) | Incomplete | Add CLV columns |
| Module 3 (Tail Risk) | Layer 4 (standalone, Sortino threshold) | Complete | Wire into standalone test |
| Module 4 (Walk-Forward) | Layer 3 (walk-forward engine) | Complete | Upgrade to expanding window |
| Module 5 (Signal Validation) | Layers 5-6 (incremental + orthogonality) | Complete | Wire into incremental + orthogonality tests |
| Module 6 (Portfolio Risk) | Layer 9 (portfolio construction) | Complete | Wire into portfolio allocation |
| Module 7 (Position Sizing) | Hypothesis H16 | Spec only | Test through gate as H16 |
| Module 8 (Monitoring) | Layer 10 (production monitoring) | Complete | Wire CUSUM into monitoring stack |

The eval modules are already 70% of the testing gate. This spec organizes them into a pipeline with gates, adds CLV as the throughline metric, and wraps the whole thing in discipline infrastructure.

---

# Appendix: Key Formulas Reference

**CLV (Market):**
```
CLV_market = (IV_entry - IV_close) / IV_entry
```

**CLV (Realized):**
```
CLV_realized = (IV_entry - RV_holding) / IV_entry
```

**Deflated Sharpe Ratio:**
```
E[max(SR)] = (1 - gamma) * Phi^-1(1 - 1/N) + gamma * Phi^-1(1 - 1/(N*e))
DSR = Phi((SR_observed - E[max(SR)]) / SE(SR))
```

**Information Ratio:**
```
IR = (R_signal - R_flagship) / std(R_signal - R_flagship) * sqrt(252/holding_period)
```

**Fundamental Law (Grinold-Kahn):**
```
IR = IC * sqrt(BR)
where IC = information coefficient (correlation of forecast with outcome)
      BR = breadth (number of independent bets per year)
```

**Population Stability Index (feature drift):**
```
PSI = sum((p_new - p_baseline) * ln(p_new / p_baseline))
where p = proportion of observations in each bin
PSI > 0.1 = investigate; > 0.2 = significant drift
```

---

# Part XI: Source Material Integration (Sinclair & Mack, 2024)

The following findings from "Retail Options Trading" (Sinclair & Mack, 2024) update, correct, or extend the spec above. Where conflicts exist, the book's empirical data takes precedence over our earlier assumptions.

## Critical Corrections

### Correction 1: "Theta is NOT an Edge"

The book is explicit: **"The most important takeaway is that greeks are not edges. They are just ways to measure various risks. In particular, theta (time decay) is not an edge."**

Options don't decay — they decay if the stock moves LESS than expected. Theta is perfectly accounted for in fair pricing. The edge is VRP (IV > RV), not time decay. The BSM equation proves this: if the stock moves as expected, theta decay is exactly cancelled by gamma gains.

**Impact on spec:**
- Remove any scoring logic that treats theta as a positive feature
- Never describe the strategy as "collecting theta" — describe it as "harvesting VRP"
- The `score_trade()` function in analytics.py should not reward high theta per se
- Scorecard should never display theta as evidence of edge

### Correction 2: Structure Preference is Backwards

The book ranks VRP harvesting structures by edge quality:

| Structure | Vega Efficiency | Transaction Cost | Edge Quality | Why |
|---|---|---|---|---|
| **Straddle** | Best (highest vega per contract) | 1x baseline | **Highest** | Most liquid strikes, fewest contracts, cleanest edge measurement |
| **Strangle** | Good (1.5x contracts needed) | 1.5x | **Good** | Benefits from overpriced OTM puts (skew premium), but higher costs |
| **Iron Condor** | Poor (2x+ contracts) | 4x | **Lowest** | Bought wings are the most overpriced options; buying overpriced things destroys edge |

The current tool focuses on covered calls and cash-secured puts. The book doesn't even list these as VRP harvesting structures — they're directional trades with a vol overlay.

**Impact on spec:**
- Proposal 2 (Multi-Leg Optimizer) should rank straddles first, not iron condors
- The "defined risk" advantage of iron condors is real but comes at severe edge cost
- Add straddle/strangle backtesting to the evaluation pipeline
- H10 (multi-leg hypothesis) should compare straddles vs strangles vs iron condors on CLV, not just risk-adjusted return

### Correction 3: VRP is Larger at Low Vol (Counterintuitive)

From the book's SPY data:
- At **low volatility**: VRP is ~**19% of IV level**
- At **high volatility**: VRP is ~**13% of IV level**

This means options are MORE overpriced (in percentage terms) when vol is low. The current system's regime logic caps signals at YELLOW during high vol — this is directionally correct but for the wrong reason. The real reason to be cautious in high vol isn't that VRP disappears (it doesn't — it's still 13%), it's that tail risk is catastrophic.

**Impact on spec:**
- H04 (VRP magnitude proportional to edge) needs to test in PERCENTAGE terms, not absolute vol points
- The VRP scoring in `calc_vrp_signal()` uses absolute thresholds (VRP > 4, > 2, etc.) — should also consider VRP/IV ratio
- Add new hypothesis: **H24: VRP as percentage of IV is a better predictor of CLV than absolute VRP**

### Correction 4: Adverse Selection Degrades Live Performance

The book presents a clear model: backtests show all trades, but live execution gets disproportionately the BAD trades (competitive for good ones, you're the only bidder on bad ones). This systematically degrades realized edge vs backtest edge.

**Impact on spec:**
- Layer 8 (Production Simulation) should include an **adverse selection haircut** of 15-25% on gross CLV
- All backtest Sharpe/CLV numbers should be marked "pre-adverse-selection"
- The walk-forward engine should track fill quality: was the actual credit received close to the mid-price?

### Correction 5: Timing the VRP Requires 82.8% Accuracy

SPY data (1993-2023): average annual return 11.1%, up 77.4% of years. To match buy-and-hold by timing in/out, you need **82.8% predictive accuracy**.

**Impact on spec:**
- The regime filter (H12) and FOMC/earnings exclusions (H13, H14) are timing the VRP — they need to clear a very high bar
- If regime filtering doesn't improve CLV by at least the amount lost from missed trades, it's destroying value
- Default stance should be: **always harvest VRP unless there's overwhelming evidence to stop**
- Circuit breakers (VIX > 45) are different — they're survival, not timing

## New Empirical Benchmarks

### VRP Baseline Data (SPY, One-Month)

| Metric | Value | Source |
|---|---|---|
| Average VRP | 3.55 vol points | Sinclair & Mack Fig 10.1 |
| Median VRP | 4.34 vol points | Sinclair & Mack Fig 10.1 |
| Std Dev of VRP | 7.44 vol points | Sinclair & Mack Fig 10.1 |
| Maximum VRP | 34.70 vol points | Sinclair & Mack Fig 10.1 |
| Minimum VRP | -66.51 vol points | Sinclair & Mack Fig 10.1 |
| % of Days VRP > 0 | 82.39% | Sinclair & Mack Fig 10.1 |
| VRP at Low Vol | ~19% of IV level | Sinclair & Mack Ch 10 |
| VRP at High Vol | ~13% of IV level | Sinclair & Mack Ch 10 |
| SPY daily range autocorrelation | 0.69 | Sinclair & Mack Ch 3 |

These should be the baseline for H01-H04 testing. If our system produces numbers materially different from these, something is wrong with our data or methodology.

### Realistic Performance Expectations

| Metric | Realistic | Unrealistic |
|---|---|---|
| Annual return | 20-40% | 100%+ |
| Sharpe ratio | 1.5-2.0 | 3.0+ |
| Win rate (straddle) | 50-60% | 80%+ |
| Win rate (strangle) | 55-70% | 85%+ |
| Drawdown expected | 2-3x expected profit | Never losing |

Source: Sinclair & Mack Ch 21. "Michael Jordan's career shooting: 50%. Even the greatest miss a lot."

### Straddle P&L Estimation

```
Expected P&L per trade = Vega x VRP (in vol points)
Expected drawdown per trade = up to 3x expected P&L
Catastrophic loss (10% move) = can exceed 10x expected P&L
```

Example from the book (SPY short straddle, 7-day):
- Premium: $776 (per contract)
- Expected P&L: ~$104 (vega $62 x VRP ~2 vol points)
- Actual drawdown: -$270 (2.6x expected profit)
- 10% move scenario: -$1,400 loss (13.5x expected profit)
- Worst historical: -$10,000+ (96x expected profit)

## New Hypotheses from Sinclair & Mack

### Tier 2 Addition

**H24: VRP/IV Ratio > Absolute VRP as Predictor**
```
Tier: 2
HYPOTHESIS: VRP expressed as a percentage of IV level (VRP/IV) is a
  better predictor of CLV than absolute VRP in vol points. Options
  are relatively MORE overpriced at low IV (19% premium) than high
  IV (13% premium).

FILTER: All scored predictions with VRP and IV data

TRADE DIRECTION: Use VRP/IV ratio instead of absolute VRP for signal scoring

PRIMARY METRIC: Rank correlation of VRP/IV vs CLV compared to VRP vs CLV
PASS THRESHOLDS:
  - Spearman rho(VRP/IV, CLV) > Spearman rho(VRP, CLV)
  - Difference statistically significant (permutation test p < 0.05)

FAIL CRITERIA: Absolute VRP is equally or more predictive — keep current system

DATA: predictions table (VRP and IV already stored)
EVIDENCE: Sinclair & Mack Ch 10: low-vol VRP = 19% of IV, high-vol = 13%
```

### Tier 3 Additions

**H25: Straddle > Strangle > Iron Condor for CLV**
```
Tier: 3
HYPOTHESIS: Straddle selling produces higher gross CLV per unit of vega
  than strangle selling, which produces higher CLV than iron condor
  selling, due to transaction cost differential and buying overpriced
  wings.

FILTER: Tickers with liquid ATM options (bid-ask < 10% of mid)

TRADE DIRECTION: Compare straddle vs strangle vs iron condor CLV

PRIMARY METRIC: CLV per unit of vega exposure
PASS THRESHOLDS:
  - CLV(straddle) > CLV(strangle) > CLV(iron condor)
  - Ordering holds after transaction costs

FAIL CRITERIA: Iron condors produce higher risk-adjusted CLV (possible
  if tail risk reduction allows larger sizing)

DATA: Options chains + historical backtest
EVIDENCE: Sinclair & Mack Ch 10: straddle = most liquid, highest vega/contract,
  iron condor = 4x costs, buys overpriced wings
```

**H26: Autocorrelation as Vol Pricing Signal**
```
Tier: 3
HYPOTHESIS: Stocks with high 252-day return autocorrelation (H > 0.55
  Hurst exponent) have systematically underpriced options because
  trending behavior produces higher realized vol than BSM assumes.
  Conversely, mean-reverting stocks (H < 0.45) have overpriced options.

FILTER: Tickers with 252+ days of daily returns

TRADE DIRECTION:
  - H > 0.55: BUY straddles (vol underpriced)
  - H < 0.45: SELL straddles (vol overpriced)

PRIMARY METRIC: CLV by Hurst exponent bucket
PASS THRESHOLDS:
  - CLV(high H) < 0 for sellers (confirming vol is underpriced for trending)
  - CLV(low H) > 2% for sellers (confirming vol is overpriced for mean-reverting)
  - Monotonic relationship across Hurst buckets

FAIL CRITERIA: No relationship between Hurst and CLV → autocorrelation
  already priced into options market

DATA: OHLCV history (compute rolling 252-day Hurst exponent)
EVIDENCE: Sinclair & Mack Ch 15: "High autocorrelation stocks have
  cheaper options (trending = underpriced vol)"
  Jeon, Kan, Li (2019): stock return autocorrelation determines expected
  option returns
```

**H27: Straddle Breakout Pattern (Entropy Signal)**
```
Tier: 3
HYPOTHESIS: After 3+ consecutive straddle-seller wins (stock moved less
  than expected on 3+ consecutive trades), the next trade has elevated
  probability of a breakout (stock moves MORE than expected). Shannon
  entropy of win/loss sequences predicts this.

FILTER: Tickers with 4+ recent sequential VRP trades

TRADE DIRECTION:
  - After 3+ seller wins: REDUCE position size or SKIP (crowding signal)
  - After 2+ seller losses: INCREASE position size (reversion)

PRIMARY METRIC: CLV conditional on prior win/loss sequence
PASS THRESHOLDS:
  - CLV after 3+ wins < CLV unconditional (confirming breakout risk)
  - Negative entropy > 0.05 for win-streak patterns

FAIL CRITERIA: No sequential dependence → win/loss sequences are independent

DATA: predictions table (seller_won column, chronological per ticker)
EVIDENCE: Sinclair & Mack Ch 15: "Straddle sellers MORE vulnerable
  AFTER multiple sequential wins. Vol expands after multiple sequential
  compression days."
```

**H28: Vanna Crush Effect Around Events**
```
Tier: 3
HYPOTHESIS: Realized volatility remains elevated for 1-2 days AFTER
  major IV crush events (earnings, FOMC) because market maker delta
  rehedging (vanna dynamics) creates price impact even as IV collapses.
  Selling premium immediately post-event captures less VRP than waiting
  2 days for rehedging to complete.

FILTER: Predictions within 2 days after earnings or FOMC

TRADE DIRECTION: Wait 2 days after event before selling premium

PRIMARY METRIC: CLV(wait 2 days) vs CLV(sell immediately post-event)
PASS THRESHOLDS:
  - CLV difference > 0.5%
  - Statistically significant (paired t-test p < 0.05)

FAIL CRITERIA: No difference → sell immediately post-crush is fine

DATA: predictions table + earnings/FOMC calendar
EVIDENCE: Sinclair & Mack Ch 15: "Post-catalyst realized vol stays high
  despite IV crush — market maker rehedging causes sharp underlying moves"
```

### Tier 4 Additions (Monitor, Don't Formally Test Yet)

**H29: Day-of-Week Volatility Effect**
- Tag: day_of_week on each prediction
- Tuesday: lower realized vol than VIX suggests (best day to sell)
- Thursday: higher realized vol (worst day to sell)
- Source: Sinclair & Mack Ch 14

**H30: Intraday Timing (First Hours vs Last 30 Min)**
- Tag: entry_time on each prediction
- First hours: lower vol (short vol)
- Last 30 minutes: vol spike (long vol or avoid entry)
- Source: Sinclair & Mack Ch 14

**H31: Monthly Expiration Effect**
- Tag: days_to_monthly_opex on each prediction
- Day after monthly expiration: lower vol (potential short vol entry)
- Source: Sinclair & Mack Ch 14

**H32: Month-End Vol Ramp**
- Tag: trading_day_of_month on each prediction
- End-of-month: higher vol (institutional rebalancing)
- Days 2-5: low-to-high vol pattern
- Source: Sinclair & Mack Ch 14

## Updated "When NOT to Trade" (Sinclair & Mack Additions)

The discipline table from Part VII gets these additions from the book:

| # | Condition | Action | Source |
|---|-----------|--------|--------|
| 13 | Can't estimate Kelly ratio | DON'T TRADE AT ALL | Ch 17: "If you can't make a sensible estimate of return/variance, you shouldn't make the trade" |
| 14 | Position size too small to matter | PASS | Ch 17: "Final size needs to be big enough to matter but not so big it will kill you. If that size doesn't exist, it probably isn't a good trade." |
| 15 | < 100-200 observations for this signal | REDUCE SIZE | Ch 17: reduce size when testing on limited data |
| 16 | Excess kurtosis in P&L distribution | REDUCE SIZE | Ch 17: fat tails mean Kelly overestimates safe sizing |
| 17 | Vol spike + term structure backwardation | WAIT for reversion | Ch 10: "catching falling knife" — don't sell into vol spike |
| 18 | After 3+ consecutive seller wins on a ticker | REDUCE or SKIP | Ch 15: straddle breakout effect — crowding/breakout imminent |
| 19 | VRP exists but < transaction costs for structure | PASS | Ch 10: iron condors at 4x costs can consume entire VRP |
| 20 | Uncomfortable with the trade | GOOD — trade it | Ch 20: "If a position makes you nervous, you will get paid to put the position on." Comfort = no edge. |

Rule 20 is counterintuitive but important: **discomfort is a signal that edge exists**. If a trade feels safe, the market has probably already priced it. If it makes you nervous, there's likely a risk premium.

## Updated Position Sizing (Sinclair & Mack)

The book's practical sizing process replaces the simple "quarter-Kelly" from the earlier spec:

```
1. Estimate Kelly ratio: f* = mean_return / variance
2. Halve it: f = f* / 2
3. Halve it again: f = f* / 4 (quarter-Kelly — conservative baseline)
4. Adjust UP slightly if positive skew (long vol strategies)
5. Adjust DOWN if negative skew (short vol — this is our case)
6. Adjust DOWN if excess kurtosis (fat tails in P&L)
7. Adjust DOWN if < 100-200 observations (uncertain estimates)
8. Adjust DOWN if correlated with other open positions (treat as one strategy)
9. Final: must be big enough to matter, small enough not to kill you
```

**Catastrophe insurance rule:** Cap max loss at ~30 weeks of expected profit (not 5x). Use longer-dated hedges (lower VRP cost, lower roll costs). Don't try to make the hedge cheaper — that makes it worse.

## The ARCTIC Framework for Finding New Edges

Sinclair & Mack's framework for evaluating new edge hypotheses (complements the 10-layer gate):

| Letter | Question | What It Tests |
|---|---|---|
| **A** - Anomaly | "What did I observe that doesn't fit normal?" | Pattern recognition — most will be noise |
| **R** - Rationale | "Why might this work? What mechanism?" | Economic logic — needs a story, not just statistics |
| **C** - Counterparty | "Who's on the other side? Why are they wrong?" | Ideal: unsophisticated retail. Bad: Susquehanna. |
| **T** - Threats | "How fast will competitors learn? Barriers to entry?" | Moat assessment — easy-to-find = easy-to-arbitrage |
| **I** - Incentives | "Why is counterparty compelled to take losing side?" | Behavioral/structural forces that sustain the edge |
| **C** - Considerations | "Anything else? Modeling challenges?" | Catch-all for practical issues |

**Key insight:** "Test 98-99 ideas before finding one promising. Not every twitching blade of grass is a mouse."

This maps to our signal graveyard: expect a 1-2% success rate. If we're finding 20%+ of hypotheses passing, our thresholds are too loose.

## The 5-Step Trading Process (Sinclair & Mack)

Replaces the ad-hoc flow in the current tool with a formal process:

```
Step 1: IDENTIFY THE EFFECT
  - What drives the edge? Risk premium (durable) or anomaly (transient)?
  - Risk premia: VRP, skewness premium, term structure carry
  - Anomalies: autocorrelation, day-of-week, straddle breakout

Step 2: TEST FOR EDGE
  - Use Monte Carlo to FALSIFY (not prove) — Popper's principle
  - "No backtest survives contact with the live order book"
  - Purpose: quickly discard bad ideas, not validate good ones
  - Run through 10-layer gate

Step 3: SCAN FOR SETUPS
  - Monitor universe daily for pre-defined conditions
  - This is what batch_sampler.py already does
  - Don't hunt for trades — let the system surface them

Step 4: SIZE YOUR RISK
  - Kelly framework (quarter-Kelly with adjustments above)
  - Think in target allocations, not share counts
  - "How much vega/theta/delta do I WANT?" then size to match

Step 5: POSITION ADJUSTMENT
  - Compare actual allocation to desired allocation
  - Rebalance when they diverge beyond cost tolerance band
  - Exit when edge disappears (spread returns to average)
  - Don't obsess over "taking profits" or "letting it run"
```

**Exit rule (from Ch 18):** "When the spread is average, we have no view and hence no edge. It doesn't matter how it got there or what our PL is. Get out."

This maps directly to the CLV framework: when IV compresses to where RV forecast says it should be, VRP is gone. Close the trade.

## 11 Categories Where New Edges Hide

For future hypothesis generation beyond H01-H32:

| # | Category | Options Application | Barrier to Entry |
|---|---|---|---|
| 1 | **Hard to backtest** | Cross-sectional vol effects, multi-asset dispersion | High (requires custom infrastructure) |
| 2 | **Information costs** | Proprietary IV data (ORATS, LiveVol), order flow | Medium (paid data sources) |
| 3 | **Novel transformations** | VRP normalized by Hurst exponent, entropy-adjusted IV rank | Medium (requires research) |
| 4 | **Transposition** | Apply mean-reversion framework from bonds to vol | Medium (domain transfer) |
| 5 | **Cross-pollination** | Entropy from information theory, copulas from hydrology | High (requires cross-domain knowledge) |
| 6 | **Low liquidity** | Weekly options on single stocks, micro-cap options | Low barrier, high noise |
| 7 | **Excess liquidity** | 0DTE options on SPX (massive volume, subtle inefficiencies) | Low barrier, competitive |
| 8 | **Behavioral fallacies** | "Theta gang" selling without VRP assessment, meme stock IV | Low barrier (just be more disciplined) |
| 9 | **Derivative logic** | ES options → SPX options price gaps | Medium (cross-market analysis) |
| 10 | **Granularity** | High-frequency vol estimation (HEAVY model), tick-by-tick Greeks | High (requires infrastructure) |
| 11 | **Sophistication differential** | Discord groups blindly following trade alerts; retail anchoring | Low barrier (just be better informed) |

Category 8 (behavioral fallacies) is our current primary edge: "theta gang" indiscriminately selling vol without assessing VRP creates predictable patterns we can exploit by being selective (the discipline framework).

## Performance Expectations Table

| Metric | Conservative | Moderate | Aggressive | Unrealistic |
|---|---|---|---|---|
| Annual return | 15-20% | 20-30% | 30-40% | 100%+ |
| Sharpe ratio | 1.0-1.5 | 1.5-2.0 | 2.0+ | 3.0+ |
| Max drawdown | -15% | -20% | -30% | "never losing" |
| Win rate (straddle) | 50-55% | 55-60% | - | 80%+ |
| Win rate (strangle) | 55-65% | 65-70% | - | 85%+ |
| Trades per year | 100-200 | 200-400 | 400+ | - |
| Edge per trade (CLV) | 1-2% | 2-4% | 4%+ | 10%+ |

These replace any prior performance targets in the spec. Source: Sinclair & Mack Ch 21 + historical VRP data from Ch 10.
