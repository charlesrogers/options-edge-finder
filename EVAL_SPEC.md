# VRP Model Evaluation Pipeline — Implementation Spec

## Overview

This spec defines 8 modules that transform our options tool from "signal generator with no
validation" into a rigorous evaluation pipeline. Each module is self-contained and testable.
Build order matters — later modules depend on earlier ones.

---

## Module 1: GARCH Forecast Evaluation

**Why first:** The GARCH engine is the analytical core. If it forecasts poorly, everything
downstream (VRP, signals, predictions) is garbage. We need to know before building anything else.

**File:** `eval_forecast.py`

### 1A: Mincer-Zarnowitz Regression

Tests whether the GARCH forecast is unbiased.

```
Regression: RV²_realized = α + β × σ²_forecast + ε
Null hypothesis: α = 0, β = 1 (forecast tracks reality)
```

**Implementation:**
- For each ticker with 250+ days of history:
  - Generate rolling 20-day GARCH forecasts (train on prior 252 days, forecast next 20)
  - Measure realized variance over the same 20-day forward window (Yang-Zhang estimator)
  - Run OLS: realized_var ~ forecast_var
  - Record: α, β, R², p-values for joint test α=0,β=1
- Common failure: α > 0, β < 1 = model underestimates low-vol, overestimates high-vol

**Output:** DataFrame with columns:
`ticker, alpha, beta, r_squared, p_value_joint, n_observations, diagnosis`

Diagnosis categories:
- "well_calibrated": α not sig different from 0, β not sig different from 1
- "biased_high": α > 0 significantly (overestimates)
- "biased_low": α < 0 significantly (underestimates)
- "poor_tracking": R² < 0.10

### 1B: HAR-RV Alternative Model

Heterogeneous Autoregressive model (Corsi 2009) — consistently beats GARCH for equity vol.

```
RV_t = c + β_d × RV_daily + β_w × RV_weekly + β_m × RV_monthly + ε
Where:
  RV_daily  = yesterday's RV (1-day)
  RV_weekly = avg RV over last 5 days
  RV_monthly = avg RV over last 22 days
```

**Implementation:**
- Simple OLS — no iterative fitting like GARCH
- Use Yang-Zhang RV at each horizon for efficiency
- Forecast 20 days ahead by iterating the model
- Same rolling evaluation window as GARCH

**Output:** Same DataFrame format as 1A for direct comparison.

### 1C: Diebold-Mariano Test

Formally tests whether GARCH and HAR-RV forecasts are statistically different.

```
d_t = L(e_GARCH) - L(e_HARV)   where L = QLIKE loss function
QLIKE(σ², RV²) = log(σ²) + RV²/σ²
```

**Why QLIKE:** Patton (2011) proved only MSE and QLIKE are robust to noisy vol proxies.
QLIKE penalizes underestimation more than overestimation — critical for option sellers
because underestimating future vol is the costlier error.

**Implementation:**
- Compute loss differential series d_t for each ticker
- DM statistic = mean(d) / (HAC_stderr(d))  [Newey-West with ~sqrt(T) lags]
- Two-sided test: reject null of equal accuracy if |DM| > 1.96

**Output:** DataFrame:
`ticker, dm_statistic, p_value, winner, qlike_garch, qlike_harv`

### 1D: Forecast Combination

If both models have significant coefficients in an encompassing regression, combine them.

```
RV²_realized = α + β₁ × σ²_GARCH + β₂ × σ²_HARV + ε
If both β₁ and β₂ significant → use weighted combination
```

**Implementation:**
- Run encompassing OLS
- If both significant: combined_forecast = β₁*GARCH + β₂*HARV (normalized)
- If only one significant: use that model alone
- Re-run Mincer-Zarnowitz on combined forecast to verify improvement

**Output:** Recommended forecast method per ticker + combination weights.

### 1E: Skewed Student's t Upgrade

Replace symmetric Student's t in `calc_prob_of_loss()` with skewed Student's t
(Lambert & Laurent 2001). The `arch` package supports this via `SkewStudent`.

**Implementation:**
- In `calc_garch_forecast()`: fit with `dist='skewt'` instead of `'t'`
- Extract skewness parameter alongside df
- In `calc_prob_of_loss()`: use scipy's skewed-t or manually adjust quantiles
- Expose skewness parameter in model_info dict

**Output:** Updated `calc_garch_forecast()` and `calc_prob_of_loss()`.

---

## Module 2: P&L-Based Prediction Scoring

**Why second:** Our current scoring is binary (seller_won: yes/no). The research doc's
$1-win/$10-loss example shows why this is dangerous. We need actual dollar P&L.

**File:** Updates to `db.py` + `eval_pnl.py`

### 2A: Expand Prediction Outcomes

Add to predictions table:
```sql
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS expected_move_pct REAL;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS actual_move_pct REAL;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS premium_estimate REAL;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS pnl_estimate REAL;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS pnl_pct REAL;
```

**P&L calculation:**
```
premium_estimate = atm_iv / 100 * sqrt(holding_days/252) * spot_price
  (approximate ATM straddle premium as % of spot)

If |actual_move| < expected_move:
    pnl = premium_estimate  (keep full premium)
Else:
    pnl = premium_estimate - (|actual_move| - expected_move) * spot_price
    (premium minus intrinsic loss)

pnl_pct = pnl / spot_price * 100
```

This is approximate (ignores gamma, theta path, actual strikes) but captures the
return distribution shape that binary win/loss hides.

### 2B: Update Scoring Function

Modify `score_pending_predictions()` to compute and store all new fields.

### 2C: Update Scorecard

Replace/supplement win-rate displays with:
- Average P&L per signal (GREEN vs YELLOW vs RED)
- P&L distribution histogram per signal
- Cumulative P&L curve over time
- Worst single-prediction P&L per signal
- Skewness and kurtosis of P&L distribution

**Key test:** GREEN signals should have higher average P&L AND less negative skew
than RED signals. If GREEN has higher win rate but worse P&L, the signals are broken.

---

## Module 3: Tail Risk Metrics

**Why third:** With P&L data from Module 2, we can compute proper risk metrics.

**File:** `eval_risk.py`

### 3A: CVaR (Conditional Value at Risk) at 95%

```
CVaR_95 = E[Loss | Loss > VaR_95]
       = average of the worst 5% of outcomes
```

**Implementation:**
- From scored predictions P&L series
- Sort P&L ascending, take bottom 5%
- CVaR = mean of that bottom 5%
- Compare to cumulative premium collected over same period
- **Critical test:** If CVaR > cumulative_premium, strategy is net-negative in the tail

Calculate per-signal (GREEN/YELLOW/RED) and overall.

### 3B: Maximum Drawdown

```
For cumulative P&L series:
  peak = running maximum
  drawdown = (cumulative - peak) / peak
  max_drawdown = min(drawdown)
```

**Implementation:**
- Build cumulative P&L curve from chronologically ordered scored predictions
- Track running peak and drawdown at each point
- Record max drawdown magnitude, start date, end date, recovery date
- Compare to CBOE PUT index floor of -32.7%

### 3C: Omega Ratio

```
Omega(θ) = ∫[θ,∞] (1-F(x))dx / ∫[-∞,θ] F(x)dx
         = sum of gains above threshold / sum of losses below threshold
```

**Implementation:**
- Calculate at θ=0 (breakeven) and θ=risk_free_rate/252*holding_days
- Omega > 1 at risk-free threshold = strategy has positive expected value
  after accounting for full distributional shape
- No parametric assumptions — works directly on empirical P&L

### 3D: Sortino and Calmar Ratios

```
Sortino = (mean_return - risk_free) / downside_deviation
Calmar = CAGR / |max_drawdown|
```

- Sortino avoids penalizing capped upside (correct for short premium)
- Calmar measures return per unit of worst-case pain

### 3E: Conditional Beta (Up/Down)

```
Up-beta:   regress strategy returns on SPY returns, using only days SPY > 0
Down-beta: regress strategy returns on SPY returns, using only days SPY < 0
```

**Key insight:** Short premium strategies have high down-beta (~0.75) and low up-beta
(~0.34). This concavity is invisible to symmetric metrics. Display prominently.

---

## Module 4: Walk-Forward Backtest

**Why fourth:** Our current backtest is one-pass with no out-of-sample validation.
It can't distinguish signal from overfit.

**File:** Updates to `analytics.py` backtest functions

### 4A: Rolling Walk-Forward

```
Training window: 756 trading days (3 years)
Test window: 126 trading days (6 months)
Step: 63 trading days (3 months)

For each step:
  1. Train GARCH + HAR-RV on training window
  2. Generate signals on test window using trained model
  3. Record out-of-sample P&L
  4. Slide forward
```

**Implementation:**
- Rewrite `backtest_vrp_strategy()` to accept train/test split parameters
- Collect out-of-sample results from all windows
- Report: OOS Sharpe, OOS win rate, OOS avg P&L vs in-sample equivalents
- **Overfitting indicator:** IS performance >> OOS performance

### 4B: IV Multiplier Sensitivity Analysis

```
For multiplier in [1.0, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30]:
  Run full walk-forward backtest
  Record: win_rate, avg_pnl, max_drawdown, signal_distribution
```

**Key output:** Table showing how sensitive results are to the IV assumption.
If profitability flips between 1.1 and 1.2, the strategy is fragile.

### 4C: Survivorship Bias Estimate

```
Adjustment = -150 bps/year (conservative estimate from literature)
Apply to annualized returns as a haircut
```

We can't fully correct for this without delisted ticker data, but we can
report adjusted returns alongside raw returns with this standard haircut.

### 4D: Transaction Cost Sensitivity

```
For spread_assumption in [0.01, 0.03, 0.05, 0.10]:  (dollars per contract)
  Rerun backtest
  Report break-even spread (where strategy P&L = 0)
```

---

## Module 5: Signal Validation

**Why fifth:** With proper P&L and backtesting in place, we can rigorously test
whether each signal component adds value.

**File:** `eval_signals.py`

### 5A: Marginal Signal Contribution (Fama-MacBeth Style)

For each prediction with P&L outcome, run panel regression:

```
pnl_i,t = α + β₁×VRP + β₂×IV_Rank + β₃×Term_Structure + β₄×Regime + β₅×Skew + ε

Step 1: Cross-sectional regression for each date t
Step 2: Time-series average of coefficients
Step 3: t-stats on averaged coefficients
```

**Output:** Which signals have statistically significant coefficients?
- If β₁ (VRP) is not significant → core thesis is broken
- If β₄ (regime) is not significant → regime filter is noise
- If β₅ (skew) is not significant → skew scoring is noise

### 5B: Multicollinearity Check

```
For each pair of signals, compute correlation
Compute VIF for each signal in the regression
If VIF > 5: signals are redundant
```

VRP, IV rank, term structure, and skew all move with market stress.
Likely outcome: high collinearity, need PCA or signal reduction.

### 5C: Regime Filter Value Test

```
Strategy A: Full model with regime filter
Strategy B: Same model, regime filter disabled (trade all signals)
Strategy C: Same model, randomly skip same % of trades regime would skip

Compare: A vs B (does filter add absolute value?)
Compare: A vs C (does filter beat random skipping?)

Use Ledoit-Wolf test for Sharpe ratio difference
```

If A doesn't significantly beat C, the regime filter is reducing sample size
without adding information.

### 5D: Exit Rule Overfitting Test

We have 9 exit triggers. Each has implicit parameters.

```
Count total parameter combinations across all exit rules
Apply Bailey-López de Prado Deflated Sharpe Ratio:
  DSR = SR * sqrt(T) * correction_factor(n_trials)

If DSR < 2.0 after correction, exit rules may be overfit
```

Also: remove each exit rule one at a time and measure impact on OOS P&L.
If removing a rule doesn't hurt (or helps), it's noise.

---

## Module 6: Portfolio Risk

**Why sixth:** Individual position analysis is done. Now we need portfolio-level risk
for the 350-name universe.

**File:** `eval_portfolio.py`

### 6A: Crisis Correlation Modeling

```
Normal correlation matrix: from last 252 days of returns
Crisis correlation matrix: from returns on days where SPY < -1%

Effective independent bets (normal):  N_eff = N / (1 + (N-1) * avg_corr)
Effective independent bets (crisis):  same formula with crisis correlations
```

For 350 names:
- Normal avg_corr ≈ 0.30 → N_eff ≈ 3.3 (!)
- Crisis avg_corr ≈ 0.80 → N_eff ≈ 1.2

This reveals how fake the diversification is.

### 6B: Portfolio Vega Stress Test

```
For each open position, estimate vega (from existing Greeks calc)
Portfolio_vega = sum of all position vegas

Stress: 10-point VIX spike
Portfolio_loss_estimate = portfolio_vega * 10

Test: portfolio_loss < 5% of portfolio value
```

### 6C: Theta/Risk Ratios

```
Portfolio theta = sum of daily theta across all positions
Portfolio vega = sum of vega
Portfolio gamma = sum of gamma

Monitor:
  theta_vega_ratio = portfolio_theta / portfolio_vega
    (days of theta income to offset 1-point IV expansion)
  theta_gamma_ratio = portfolio_theta / portfolio_gamma
    (breakeven daily move = sqrt(2 * theta / gamma))
```

### 6D: Historical Stress Test

Reprice all current positions under:
1. **COVID March 2020:** SPY -34%, VIX = 82, correlations = 0.95
2. **Volmageddon Feb 2018:** VIX doubles overnight (17→37)
3. **Aug 2024 Yen unwind:** VIX spike to 65 intraday

For each: estimated portfolio P&L, margin requirement change, forced liquidation risk.

---

## Module 7: Position Sizing Fix

**Why seventh:** Kelly criterion needs negative-skew adjustment.

**File:** Updates to `analytics.py`

### 7A: Quarter-Kelly with Skew Adjustment

Current `calc_kelly_size()` uses `fraction=0.25` but doesn't account for
the non-normal return distribution of short premium.

```
Adjusted Kelly:
  1. Compute standard Kelly fraction
  2. Adjust for empirical skewness: kelly_adj = kelly * (1 / (1 + |skew|))
  3. Cap at quarter-Kelly: min(kelly_adj, 0.25 * full_kelly)
  4. Absolute cap: 5% of portfolio per position
```

### 7B: Capital Deployment Tracking

Add to positions tab:
```
total_capital = user input or estimated from positions
deployed_capital = sum of (margin requirement per position)
deployment_pct = deployed / total
cash_reserve_pct = 1 - deployment_pct

Targets:
  Normal regime: 50-65% deployed, 35-50% cash
  High vol regime: 25-40% deployed
  Crash regime: 0% deployed (all cash)

Warning if cash_reserve < 25%
```

---

## Module 8: Monitoring & Edge Erosion

**Why last:** Requires everything above to be running and producing data.

**File:** `eval_monitor.py`

### 8A: CUSUM Edge Erosion Detection

```
Reference value K = 0.25  (midpoint between IR=0.5 "good" and IR=0 "bad")
Decision threshold H = 4  (one false alarm per ~200 months)

S_t = max(0, S_{t-1} + (K - r_t))
Where r_t = standardized daily information ratio

If S_t > H: ALERT — edge may have eroded
```

**Implementation:**
- Run on rolling scored prediction P&L
- Display on Scorecard tab as a chart
- Alert when threshold crossed

### 8B: GARCH Parameter Drift

```
Every 30 days (or on each batch sampler run):
  Refit GARCH on latest 1000 days
  Compare (omega, alpha, beta, gamma) to previous calibration
  If any parameter changes > 15%: flag for investigation
  If Ljung-Box test on residuals fails (p < 0.05): model misspecified
```

### 8C: Circuit Breakers (Portfolio Level)

Add to positions monitoring:
```
VIX-based:
  VIX > 35: reduce sizing 50%, halt single-name selling
  VIX > 45: halt ALL new premium selling
  VIX > 65: close all positions

Drawdown-based:
  Portfolio drawdown > 10%: reduce sizes 50%
  Portfolio drawdown > 15%: halt new selling
  Portfolio drawdown > 20%: close all positions

Calendar-based:
  Within 2 days of FOMC: no new trades (already have this)
  Within 5 days of earnings: no new trades on that ticker
  Quad witching week: reduce sizes 25%
```

---

## Build Order and Dependencies

```
Module 1: GARCH Evaluation        ← standalone, no dependencies
Module 2: P&L Scoring             ← needs Module 1 (better forecasts)
Module 3: Tail Risk Metrics       ← needs Module 2 (P&L data)
Module 4: Walk-Forward Backtest   ← needs Module 1 (HAR-RV) + Module 2 (P&L)
Module 5: Signal Validation       ← needs Module 2 + 4 (P&L + proper backtest)
Module 6: Portfolio Risk          ← standalone for stress tests, needs Module 2 for others
Module 7: Position Sizing Fix     ← needs Module 3 (skewness data)
Module 8: Monitoring              ← needs everything above running
```

## Minimum Viable Pipeline (if we can only build 3 things)

1. **Module 1A+1B+1C** — Is our GARCH forecast any good? Does HAR-RV beat it?
2. **Module 2A+2B+2C** — P&L scoring instead of binary win/loss
3. **Module 3A+3B** — CVaR and max drawdown so we know the tail risk

Everything else is important but these three answer the existential questions:
"Does the engine work?", "Does winning make money?", "How bad is the worst case?"

---

## Data Requirements

- **Already have:** 350 tickers x 90 days bootstrap IV data in Supabase,
  daily real IV snapshots accumulating, prediction logging with full context
- **Need for Module 1:** 250+ days of price history per ticker (have via proxy)
- **Need for Module 4:** 1000+ days of price history (have via 2y proxy fetch)
- **Need for Module 6:** Current open positions with Greeks (have)
- **Need for Module 8:** 30+ days of scored predictions (need to wait)

## Success Criteria

The pipeline succeeds if it can answer these questions with statistical confidence:

1. Is our vol forecast better than a 22-day rolling average? (Module 1)
2. Do GREEN signals make more money than RED signals? (Module 2)
3. What's the worst realistic month for this strategy? (Module 3)
4. Do our signals work out-of-sample? (Module 4)
5. Which signals actually matter? (Module 5)
6. Would a 2020-style crash wipe us out? (Module 6)
7. Are we sizing positions safely? (Module 7)
8. Is the edge still there? (Module 8)
