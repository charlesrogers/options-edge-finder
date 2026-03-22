# Options Edge Finder: 10-Year Vision Spec

## Document Purpose
Detailed implementation specifications for 5 transformative upgrades to the Options Edge Finder. Each proposal includes: what it is, why it matters, how to do it right, what wrong looks like, how it wires into the existing system, and what the acceptance criteria are.

---

# Proposal 1: Full Stochastic Volatility Surface Engine

## What It Is
Replace the single-point ATM IV measurement with a calibrated volatility surface model that prices every strike and expiration simultaneously. The surface reveals where the market is mispricing volatility — not just "is IV high?" but "which specific contracts are richest?"

## Why It Matters (The Edge Argument)

The current system computes one VRP number: `ATM IV - GARCH forecast`. But VRP varies dramatically across the surface:

- 30-delta puts typically carry 2-3x more risk premium than ATM options (Israelov & Kelly, 2017)
- Short-dated options have higher annualized VRP than long-dated (due to gamma risk premium)
- Skew steepness itself is a signal — steep skew after a crash often means puts are overpriced relative to realized tail frequency

With one number, you're averaging over all of this. The surface lets you find the **richest point** on the grid and sell there specifically. This is the difference between "the market is expensive" and "this specific contract is 40% overpriced."

## How to Do It Right

### Phase 1A: SABR Calibration Per Expiration (Start Here)

SABR (Stochastic Alpha Beta Rho) is the industry standard for single-expiration smile fitting. It's simpler than Heston, more robust, and has closed-form approximations.

**SABR Parameters (4 per expiration):**
- alpha: ATM vol level
- beta: backbone (typically fixed at 0.5 for equities, 1.0 for rates)
- rho: correlation between spot and vol (negative = skew)
- nu: vol-of-vol (controls smile curvature/wings)

**Calibration procedure:**
```
For each expiration in the chain:
    1. Extract all strike/IV pairs with bid-ask midpoint IV
    2. Filter: discard strikes with zero volume AND zero OI (no real market)
    3. Filter: discard strikes where bid-ask spread > 50% of mid (unreliable IV)
    4. Weight: volume-weight the calibration (liquid strikes matter more)
    5. Fix beta = 0.5 (standard for equities; reduces to 3-param fit)
    6. Initial guess: alpha = ATM_IV, rho = -0.3, nu = 0.4
    7. Minimize: sum of weighted squared IV errors using scipy.optimize.minimize (L-BFGS-B)
       - Bounds: alpha > 0, -0.999 < rho < 0.999, nu > 0
    8. Store: (expiration, alpha, beta, rho, nu, calibration_error, n_strikes_used)
```

**Why SABR first, not Heston:**
- SABR fits one expiration at a time — isolates term structure from smile
- Closed-form Hagan approximation means no PDE/FFT needed
- Heston requires simultaneous fit across ALL expirations (harder to debug)
- SABR parameters are directly interpretable (rho = skew, nu = kurtosis)
- Can always upgrade to Heston later for cross-expiration consistency

**Key function to add (in analytics.py):**
```python
def calibrate_sabr_surface(chains_by_expiry: dict, spot: float, r: float = 0.045) -> dict:
    """
    Calibrate SABR model to each expiration independently.

    Args:
        chains_by_expiry: {expiry_date: DataFrame with columns [strike, mid_iv, volume, oi]}
        spot: current underlying price
        r: risk-free rate

    Returns:
        {expiry_date: {alpha, beta, rho, nu, atm_iv, calibration_rmse, n_strikes}}
    """
```

### Phase 1B: Model-Free Implied Moments (Parallel with 1A)

Extract variance, skewness, and kurtosis directly from option prices using Bakshi-Kapadia-Madan (2003). No model assumptions needed.

**The math:**
```
Implied Variance:   V = integral[0, inf] of (2(1 - ln(K/S)) / K^2) * C(K) dK  (for OTM calls)
                      + integral[0, inf] of (2(1 + ln(S/K)) / K^2) * P(K) dK  (for OTM puts)

Implied Skewness:   W = (mu3 - 3*mu*V - mu^3) / V^(3/2)

Implied Kurtosis:   X = (mu4 - 4*mu*mu3 + 6*mu^2*V + 3*mu^4) / V^2
```

Where mu, mu3, mu4 are the first, third, and fourth moments computed by integrating OTM option prices across strikes.

**Implementation:**
```
1. Sort OTM calls by strike ascending, OTM puts by strike descending
2. Use trapezoidal integration (strikes are discrete, not continuous)
3. Extrapolate wings: flat IV beyond last traded strike (conservative)
4. Compute V, W, X per expiration
5. Compare to GARCH-implied moments: if market skew >> GARCH skew, puts are overpriced
```

**Why model-free matters:**
- SABR skew is parameterized (smooth) — model-free skew captures kinks and jumps
- Model-free kurtosis directly measures how fat the market thinks tails are
- The ratio `model-free kurtosis / empirical kurtosis` is a tradeable signal: if market thinks tails are 2x fatter than history, puts are expensive

### Phase 1C: Heston Calibration (After 1A and 1B are validated)

Heston gives a globally consistent surface across all expirations simultaneously.

**Heston Parameters (5 total, shared across all expirations):**
- v0: current instantaneous variance
- kappa: mean-reversion speed of variance
- theta: long-run variance level
- sigma: vol-of-vol
- rho: spot-vol correlation

**Calibration procedure:**
```
1. Collect ALL strike/IV pairs across ALL expirations
2. Price each option using Carr-Madan FFT (characteristic function approach)
   - FFT with N=4096 grid points, eta=0.25, alpha=1.5
   - This gives prices for all strikes in one FFT call per expiration
3. Convert model prices to model IVs (Newton-Raphson inversion)
4. Minimize: sum of squared (market_IV - model_IV) weighted by vega * volume
   - Use differential evolution (global optimizer) for initial guess
   - Then L-BFGS-B for local refinement
5. Constraints:
   - Feller condition: 2*kappa*theta > sigma^2 (ensures variance stays positive)
   - kappa > 0, theta > 0, sigma > 0
   - -1 < rho < 0 (equities have negative spot-vol correlation)
   - v0 > 0
```

**Why vega-weighting:**
- ATM options have high vega — their IV is precisely known from the market
- Deep OTM options have low vega — small price errors translate to huge IV errors
- Without vega-weighting, the calibration chases noisy wing IVs and distorts ATM fit

### Phase 1D: VRP Surface Construction

Once you have a calibrated model surface (SABR or Heston), compare it to the realized distribution:

```
For each (strike, expiration) on the surface:
    model_iv = SABR_or_Heston_IV(strike, expiration)
    realized_vol_at_delta = empirical_vol_at_equivalent_return_threshold
    vrp_surface[strike, expiration] = model_iv - realized_vol_at_delta
```

The "realized vol at equivalent return threshold" is key:
- For ATM: this is just RV20 (or GARCH forecast)
- For 30-delta put (roughly 5% OTM): this is the realized frequency of moves exceeding -5% over the holding period
- For 15-delta put (roughly 10% OTM): frequency of -10% moves

This gives you VRP *per strike* — the thing that actually matters for trade selection.

### Phase 1E: Storage and Integration

**New Supabase table: `vol_surface_snapshots`**
```sql
CREATE TABLE vol_surface_snapshots (
    ticker TEXT,
    date TEXT,
    expiration TEXT,
    model TEXT,           -- 'sabr' or 'heston'
    -- SABR params
    sabr_alpha REAL,
    sabr_rho REAL,
    sabr_nu REAL,
    -- Heston params (NULL if SABR-only)
    heston_v0 REAL,
    heston_kappa REAL,
    heston_theta REAL,
    heston_sigma REAL,
    heston_rho REAL,
    -- Diagnostics
    calibration_rmse REAL,
    n_strikes_used INTEGER,
    -- Model-free moments
    implied_variance REAL,
    implied_skewness REAL,
    implied_kurtosis REAL,
    PRIMARY KEY (ticker, date, expiration, model)
);
```

**Wire into batch_sampler.py:**
- After fetching options chain (existing step), add SABR calibration
- Store surface params alongside existing iv_snapshots
- ~500ms per expiration, ~4 seconds per ticker (8 expirations), ~23 min for 350 tickers

**Wire into streamlit_app.py:**
- New visualization in Dashboard: 3D surface plot (strike x expiration x IV) with VRP heatmap overlay
- Trade Analyzer: show VRP at the selected strike, not just ATM VRP
- Replace `build_vol_surface()` in analytics.py (currently just data dump) with SABR-interpolated surface

## What Wrong Looks Like

### Wrong: Fitting to illiquid strikes
**Symptom:** SABR rho swings wildly day-to-day (e.g., -0.9 one day, -0.1 the next)
**Cause:** Including zero-volume deep OTM strikes where bid-ask spread is 50%+ of mid
**Fix:** Filter to strikes with volume > 0 OR open interest > 100. Weight by sqrt(volume).

### Wrong: Ignoring the Feller condition in Heston
**Symptom:** Calibration "succeeds" but simulated variance paths go negative, model prices become NaN
**Cause:** sigma^2 > 2*kappa*theta, so variance process hits zero and reflects incorrectly
**Fix:** Hard constraint in optimizer: `2*kappa*theta - sigma^2 > 0.001`. If constraint is binding, the data doesn't support Heston — fall back to SABR.

### Wrong: Using model IV for VRP instead of market IV
**Symptom:** VRP surface is suspiciously smooth, no edge visible anywhere
**Cause:** Computing VRP as `SABR_IV(K) - GARCH_forecast` when SABR was already calibrated to match market IV. The model smooths away the mispricing you're trying to find.
**Fix:** VRP = `market_mid_IV(K) - model_fair_IV(K)` where model_fair_IV comes from the *realized* distribution, not from fitting to market. SABR is for interpolation and extrapolation, not for defining "fair."

### Wrong: Overfitting wings with too many parameters
**Symptom:** Surface looks perfect in-sample but prices are way off for new strikes the next day
**Cause:** Adding extra SABR/Heston parameters to fit every kink in the smile
**Fix:** SABR with fixed beta (3 free params) is almost always sufficient. If RMSE > 2 vol points, the issue is data quality, not model complexity.

### Wrong: Not handling early exercise
**Symptom:** Put surface shows phantom skew for deep ITM puts near expiration
**Cause:** American puts have early exercise premium that BSM doesn't capture — their IV is inflated
**Fix:** Either use only OTM options for calibration (standard practice) or add a Barone-Adesi-Whaley early exercise adjustment.

### Wrong: Calibrating in price space instead of IV space
**Symptom:** ATM fit is terrible despite low overall RMSE
**Cause:** Deep OTM options have tiny prices ($0.01-$0.10) — squared price errors are tiny even when IV is off by 10 vol points. ATM options have large prices — optimizer focuses there.
**Fix:** Always calibrate in implied volatility space, not price space. Convert model prices to IV via Newton-Raphson, then minimize IV errors.

## Acceptance Criteria

- [ ] SABR calibration produces stable parameters (day-over-day rho change < 0.1 for liquid names)
- [ ] Calibration RMSE < 1.5 vol points for front 3 expirations on SPY/QQQ
- [ ] Model-free implied skewness correlates > 0.7 with SABR rho (consistency check)
- [ ] VRP surface shows identifiable rich zones (30-delta puts should be richer than ATM, confirming literature)
- [ ] Surface stored daily in Supabase, retrievable for historical analysis
- [ ] 3D surface visualization renders in Streamlit with <2 second load time
- [ ] Full universe (350 tickers) calibrates in <30 minutes on GitHub Actions runner

---

# Proposal 2: Multi-Leg Strategy Optimizer

## What It Is
Given the current market state (vol surface, VRP signal, portfolio Greeks), find the optimal multi-leg option structure — not just "sell a put" but "sell this specific iron condor with these strikes at this expiration for this credit."

## Why It Matters (The Edge Argument)

Single-leg selling has two fatal flaws:
1. **Unlimited risk** — A naked put on NVDA during a 30% crash loses ~$9,000 per contract. The backtest showed -285% max drawdown.
2. **Capital inefficiency** — A cash-secured put on a $200 stock ties up $20,000 in margin for ~$400 in premium (2% return on capital at risk).

Multi-leg structures fix both:
- **Iron condor** on the same stock: max loss = wing width ($500), credit = $150 (30% return on risk). Same VRP capture, 40x better capital efficiency.
- **Vertical spread**: defined risk, much lower margin, similar P&L in the high-probability zone
- **Calendar spread**: exploits term structure directly (sell rich front month, buy cheap back month)

The current system identifies WHEN to sell (GREEN signal) but not WHAT structure to sell. That's like a real estate tool that says "buy in this neighborhood" but doesn't tell you which house.

## How to Do It Right

### Phase 2A: Structure Definition Library

Define each structure as a set of legs with constraints:

```python
STRUCTURES = {
    "short_put": {
        "legs": [{"type": "put", "side": "sell", "delta_target": -0.20}],
        "margin_type": "cash_secured",
        "max_loss": "unlimited",  # well, strike * 100
    },
    "bull_put_spread": {
        "legs": [
            {"type": "put", "side": "sell", "delta_target": -0.25},
            {"type": "put", "side": "buy",  "delta_target": -0.10},
        ],
        "margin_type": "defined_risk",
        "max_loss": "width - credit",
    },
    "iron_condor": {
        "legs": [
            {"type": "put",  "side": "sell", "delta_target": -0.20},
            {"type": "put",  "side": "buy",  "delta_target": -0.08},
            {"type": "call", "side": "sell", "delta_target":  0.20},
            {"type": "call", "side": "buy",  "delta_target":  0.08},
        ],
        "margin_type": "defined_risk",
        "max_loss": "max(put_width, call_width) - credit",
    },
    "calendar_spread": {
        "legs": [
            {"type": "put", "side": "sell", "strike": "atm", "expiry": "front"},
            {"type": "put", "side": "buy",  "strike": "atm", "expiry": "second"},
        ],
        "margin_type": "debit",
        "max_loss": "debit_paid",
        "requires": "contango",  # only makes sense when front IV > back IV... wait, no
        # Calendar profits from front decaying faster; contango means back > front (normal)
        # Actually profitable when front IV drops faster OR time decay of front > back
    },
    "jade_lizard": {
        "legs": [
            {"type": "put",  "side": "sell", "delta_target": -0.25},
            {"type": "call", "side": "sell", "delta_target":  0.30},
            {"type": "call", "side": "buy",  "delta_target":  0.15},  # further OTM call
        ],
        "margin_type": "semi_defined",
        "max_loss": "put_side_unlimited, call_side_defined",
        "requires": "bullish_or_neutral",
    },
}
```

### Phase 2B: Candidate Generation (The Hard Part)

For each structure type, generate all valid combinations from the available chain:

```
For each structure in STRUCTURES:
    For each expiration (front 4):
        For each valid strike combination satisfying delta_target constraints:
            1. Snap delta_target to nearest available strike
            2. Compute: credit/debit, max_loss, max_profit, breakevens
            3. Compute: probability of max profit (from vol surface or empirical dist)
            4. Compute: expected P&L = prob_profit * credit - prob_loss * avg_loss
            5. Compute: return_on_risk = expected_pnl / max_loss
            6. Check constraints:
               - Credit > minimum_credit_threshold (e.g., $0.50 per spread)
               - Max_loss < position_size_limit (from Kelly, Module 7)
               - All legs have volume > 10 OR open_interest > 50
               - Bid-ask spread on each leg < 20% of mid
            7. If passes, add to candidates list
```

**Pruning to avoid combinatorial explosion:**
- Don't enumerate all strike^4 combinations for iron condors
- Instead: pick sell strikes by delta target, then test 3 wing widths ($2.50, $5, $10) for each
- This reduces candidates from O(strikes^4) to O(expirations * delta_snaps * wing_widths) ~ 4 * 3 * 3 = 36 per structure type
- Total candidates across all structure types: ~200-300 per ticker (very manageable)

### Phase 2C: Ranking and Selection

Score each candidate on multiple dimensions:

```python
def score_candidate(candidate, portfolio_state, market_state):
    """
    Score a multi-leg structure candidate.

    Returns composite score 0-100.
    """
    # 1. Edge score (0-30): How much VRP are we capturing?
    #    Use VRP at the sold strikes from the vol surface (Proposal 1)
    #    vrp_at_sold_strike / max_vrp_available * 30
    edge = vrp_weighted_credit / max_available_vrp * 30

    # 2. Risk-adjusted return (0-25): Expected P&L per dollar at risk
    #    Use empirical distribution (or vol surface) to compute expected P&L
    rar = expected_pnl / max_loss
    rar_score = min(rar / 0.15, 1.0) * 25  # 15% return on risk = perfect score

    # 3. Portfolio fit (0-20): Does this improve portfolio Greeks?
    #    Adding this position should:
    #    - Not increase portfolio vega beyond limit
    #    - Not increase sector concentration
    #    - Improve theta/gamma ratio
    new_vega = portfolio_state.vega + candidate.vega
    new_theta = portfolio_state.theta + candidate.theta
    vega_ok = abs(new_vega) < portfolio_state.vega_limit
    theta_improvement = (new_theta / abs(new_vega)) > (portfolio_state.theta / abs(portfolio_state.vega))
    portfolio_fit = (10 if vega_ok else 0) + (10 if theta_improvement else 5)

    # 4. Liquidity (0-15): Can we actually execute this?
    #    Min volume across all legs, weighted by contracts needed
    min_volume = min(leg.volume for leg in candidate.legs)
    liquidity = min(min_volume / 100, 1.0) * 15

    # 5. Simplicity (0-10): Fewer legs = easier to manage
    simplicity = {1: 10, 2: 8, 3: 5, 4: 3}[len(candidate.legs)]

    return edge + rar_score + portfolio_fit + liquidity + simplicity
```

### Phase 2D: Roll Optimization

When an exit signal fires (from existing `generate_exit_signals()`), don't just close — search for optimal roll:

```
1. Current position hits exit trigger (e.g., 50% profit captured)
2. Generate candidates for SAME structure type at:
   - Next expiration (same strikes)
   - Next expiration (re-centered on current spot)
   - Same expiration but wider/narrower wings
3. Compute: net credit/debit to roll (close current + open new)
4. Compute: expected P&L of rolled position vs just closing
5. Recommend: "Close for $1.50 profit" or "Roll to April 195/190/210/215 IC for additional $0.85 credit"
```

### Phase 2E: Integration with Existing System

**Wire into streamlit_app.py Trade Analyzer tab:**
- After displaying current single-leg analysis, add "Multi-Leg Strategies" section
- Show top 5 candidates ranked by composite score
- For each: payoff diagram, Greeks, probability of profit, max loss
- "Select" button populates the position entry form

**Wire into batch_sampler.py (optional, for daily tracking):**
- After computing VRP signal, also compute top structure recommendation
- Store in new column in predictions table: `recommended_structure`, `structure_credit`, `structure_max_loss`
- Enables backtesting of structure recommendations over time

**New file: `strategy_optimizer.py`** (~400-600 lines)
- Structure definitions
- Candidate generator
- Scorer
- Roll optimizer
- Payoff diagram generator (replaces simple P&L in stress_test_trade)

## What Wrong Looks Like

### Wrong: Optimizing for max credit without risk adjustment
**Symptom:** Optimizer always recommends the widest possible iron condor or naked straddle because it collects the most premium
**Cause:** Scoring function weights credit too heavily, doesn't penalize max loss
**Why it's dangerous:** Max credit = max risk. A $5-wide iron condor collecting $4.80 has 96% return on risk but >80% probability of max loss. This is picking up pennies in front of a steamroller.
**Fix:** Score on **expected P&L / max loss**, not raw credit. Use empirical probability of loss (from Module 3's distribution), not BSM probability.

### Wrong: Ignoring bid-ask spread in multi-leg pricing
**Symptom:** Recommended structures show $2.00 credit but actual fill is $1.20 or worse
**Cause:** Using mid prices for all legs; in reality, you cross the spread on each leg (4 legs = 4 spreads)
**Why it's dangerous:** A 4-leg iron condor on an illiquid name can lose $0.60-$1.00 to spread alone, wiping out the entire edge
**Fix:** Use (bid+ask)/2 for initial estimate, then deduct `sum(ask-bid)/2` across all legs as slippage estimate. Only recommend structures where `credit - slippage_estimate > minimum_threshold`.

### Wrong: Recommending calendars in backwardation
**Symptom:** Calendar spread loses money even when stock doesn't move
**Cause:** Calendar spreads profit from time decay differential — but in backwardation, front month IV is HIGHER than back month. The bought back-month option decays slower but costs more.
**Why it's dangerous:** Calendars in backwardation have negative theta and negative vega exposure — worst of both worlds
**Fix:** Hard filter: `if term_structure == 'backwardation': exclude calendar_spread`. The existing `get_term_structure()` already detects this.

### Wrong: Not accounting for early assignment risk on short legs
**Symptom:** Short ITM put gets assigned, investor forced to buy stock with cash they don't have
**Cause:** American options can be exercised early, especially puts near ex-dividend dates
**Why it's dangerous:** Assignment on one leg of a spread while the other leg is OTM creates unhedged stock exposure
**Fix:** Flag when short leg has |delta| > 0.80 AND ex-dividend within DTE. Add "early assignment risk: HIGH" warning to candidate output. Never recommend short calls on dividend stocks within 5 days of ex-date.

### Wrong: Combinatorial explosion on full chain enumeration
**Symptom:** Candidate generation takes 30+ seconds per ticker, or crashes on memory
**Cause:** Generating all possible 4-leg combinations from 50 strikes = 50^4 = 6.25M candidates
**Fix:** Use delta-targeting (Phase 2B pruning): pick sold strikes by delta, enumerate only 3 wing widths. Total candidates < 300 per ticker.

### Wrong: Portfolio fit score ignoring correlation
**Symptom:** Optimizer recommends iron condors on AAPL, MSFT, GOOGL, META, AMZN (all mega-cap tech) because each one individually looks good
**Cause:** Portfolio fit only checks total vega, not sector concentration
**Why it's dangerous:** Module 6 showed these names have crisis correlation >0.85 — five "independent" iron condors become one giant bet on tech
**Fix:** Portfolio fit must include: (a) sector exposure check, (b) correlation with existing positions (from `calc_portfolio_correlation()`), (c) effective independent bets after adding this position.

## Acceptance Criteria

- [ ] Generates valid candidates for at least 5 structure types (put spread, call spread, iron condor, calendar, strangle)
- [ ] All candidates satisfy: positive credit, defined max loss, all legs have volume > 0
- [ ] Recommended structures have better risk-adjusted return than equivalent single-leg in >60% of cases
- [ ] Slippage-adjusted credit is within 15% of actual fill (validate on paper trades)
- [ ] Roll recommendations beat "close and re-enter" in >50% of cases (track over time)
- [ ] Candidate generation completes in <3 seconds per ticker
- [ ] Payoff diagram renders correctly for all structure types (verify visually)

---

# Proposal 3: Bayesian Adaptive Signal Engine

## What It Is
Replace the static, hand-tuned GREEN/YELLOW/RED scoring system with a Bayesian model that continuously learns which signal components drive P&L, adapts to regime changes automatically, and provides calibrated probability estimates instead of traffic lights.

## Why It Matters (The Edge Argument)

The current signal logic (`calc_vrp_signal()` lines 253-321 in analytics.py) is a manually scored rubric:
- VRP > 4 = 3 points, VRP > 2 = 2 points, etc.
- IV Rank > 50% = 2 points, > 30% = 1 point
- Contango = 2 points, flat = 1, backwardation = 0
- Total >= 5 = GREEN

These thresholds were set once based on intuition from Sinclair's book. They don't adapt. Module 5 (signal validation) exists specifically to check if they're still valid — but it's a one-time diagnostic, not a continuous feedback loop.

Problems:
1. **Thresholds are arbitrary**: Why is the GREEN cutoff 5, not 4.5 or 5.5? Why is VRP > 4 worth 3 points and not 2.5?
2. **Weights don't change**: In 2020 (high vol), regime mattered most. In 2024 (low vol), IV rank mattered most. Static weights can't capture this.
3. **Multicollinearity**: Module 5 will likely show VRP, IV Rank, and term structure are correlated — the scoring double-counts them.
4. **No calibration**: GREEN doesn't mean "80% chance of profit" — it means "score >= 5." The actual probability depends on the inputs in ways the point system can't express.

A Bayesian model fixes all of these by learning the mapping from inputs to outcomes directly from data, with uncertainty quantification.

## How to Do It Right

### Phase 3A: Bayesian Logistic Regression (Start Simple)

Don't jump to deep learning. Start with the simplest Bayesian model that addresses the core problems:

```python
# Model: probability of seller winning as a function of signal components
# Using PyMC (or NumPyro for speed)

import pymc as pm

with pm.Model() as vrp_model:
    # Priors (weakly informative)
    intercept = pm.Normal("intercept", mu=0, sigma=2)
    beta_vrp = pm.Normal("beta_vrp", mu=0.5, sigma=1)      # expect positive
    beta_iv_rank = pm.Normal("beta_iv_rank", mu=0.3, sigma=1)
    beta_term = pm.Normal("beta_term", mu=0.3, sigma=1)
    beta_regime = pm.Normal("beta_regime", mu=-0.3, sigma=1)  # expect negative for high vol
    beta_skew = pm.Normal("beta_skew", mu=-0.2, sigma=1)

    # Linear predictor (logit scale)
    logit_p = (intercept
               + beta_vrp * vrp_standardized
               + beta_iv_rank * iv_rank_standardized
               + beta_term * term_structure_numeric
               + beta_regime * regime_numeric
               + beta_skew * skew_standardized)

    # Likelihood
    p = pm.math.sigmoid(logit_p)
    outcome = pm.Bernoulli("seller_won", p=p, observed=seller_won_data)

    # Fit
    trace = pm.sample(2000, chains=4, target_accept=0.9)
```

**Why logistic first:**
- You have binary outcome data (seller_won) already in the predictions table
- Logistic regression is well-understood, fast to fit, interpretable
- Posterior on each beta tells you: "VRP coefficient is 0.42 +/- 0.08 (95% CI: 0.26-0.58)"
- This directly answers: "Does VRP matter? How much? How certain are we?"

**What you get immediately:**
- Calibrated probabilities: "This trade has 78% probability of seller winning" (not just GREEN)
- Uncertainty bands: "...but we're only 60% confident it's above 70%"
- Feature importance: posterior means rank the signal components
- Automatic regularization: Bayesian priors prevent overfitting (unlike Module 5's OLS)

### Phase 3B: Time-Varying Coefficients

The static model (3A) gives average relationships. But VRP's importance changes over time:

```python
with pm.Model() as dynamic_model:
    # Innovation variance for each coefficient
    tau_vrp = pm.HalfNormal("tau_vrp", sigma=0.1)
    tau_iv = pm.HalfNormal("tau_iv", sigma=0.1)

    # Time-varying coefficients (Gaussian random walk)
    # One value per month (not per day — too noisy)
    beta_vrp_t = pm.GaussianRandomWalk("beta_vrp_t", sigma=tau_vrp,
                                        shape=n_months, init_dist=pm.Normal.dist(0.5, 1))
    beta_iv_t = pm.GaussianRandomWalk("beta_iv_t", sigma=tau_iv,
                                       shape=n_months, init_dist=pm.Normal.dist(0.3, 1))

    # Map each observation to its month
    logit_p = (intercept
               + beta_vrp_t[month_index] * vrp
               + beta_iv_t[month_index] * iv_rank
               + ...)
```

**Why monthly granularity:**
- Daily coefficients would overfit (each day has ~350 observations but coefficients are shared)
- Monthly gives ~7,000 observations per window (350 tickers * 20 trading days)
- The random walk prior `sigma=0.1` means coefficients change slowly — they can't jump 2 standard deviations in one month
- If tau_vrp posterior is near zero, the coefficient is actually stable (model learns it doesn't need to vary)

### Phase 3C: Hierarchical Ticker Grouping

Not all tickers respond to VRP the same way. NVDA (high vol, fat tails) is different from SPY (low vol, mean-reverting).

```python
with pm.Model() as hierarchical_model:
    # Population-level (shared across all tickers)
    mu_beta_vrp = pm.Normal("mu_beta_vrp", mu=0.5, sigma=1)
    sigma_beta_vrp = pm.HalfNormal("sigma_beta_vrp", sigma=0.5)

    # Ticker-level (partial pooling)
    beta_vrp_ticker = pm.Normal("beta_vrp_ticker", mu=mu_beta_vrp,
                                 sigma=sigma_beta_vrp, shape=n_tickers)

    # Each observation uses its ticker's coefficient
    logit_p = intercept + beta_vrp_ticker[ticker_index] * vrp + ...
```

**Why hierarchical:**
- **Full pooling** (one coefficient for all tickers): assumes NVDA and SPY are identical. Wrong.
- **No pooling** (separate model per ticker): each ticker uses only its own ~300 data points. Noisy.
- **Partial pooling** (hierarchical): tickers with little data shrink toward the population mean; tickers with lots of distinctive data get their own coefficient. This is the optimal bias-variance tradeoff.

**Practical implication:**
- A new ticker added to the universe immediately gets the population average — no cold-start problem
- After 60+ days of data, it develops its own coefficient
- You can identify "VRP-responsive" vs "VRP-unresponsive" tickers by examining the posterior

### Phase 3D: Replacing the Traffic Light

The new signal output replaces `calc_vrp_signal()`:

```python
def calc_bayesian_signal(vrp, iv_rank, term_structure, regime, skew, ticker,
                          model_trace, month_index, ticker_index):
    """
    Bayesian signal: calibrated probability + uncertainty.

    Returns:
        {
            "prob_seller_wins": 0.78,          # posterior mean
            "prob_ci_lower": 0.71,              # 5th percentile of posterior predictive
            "prob_ci_upper": 0.84,              # 95th percentile
            "expected_pnl_pct": 2.3,            # E[P&L | inputs] (if Phase 3E added)
            "signal": "GREEN",                  # backward-compatible label
            "confidence": "high",               # based on CI width
            "top_driver": "VRP (beta=0.52)",    # largest coefficient * input
            "regime_effect": "-0.15",           # regime coefficient contribution
        }
    """
    # Compute posterior predictive for this specific input
    logit_samples = (trace["intercept"]
                     + trace[f"beta_vrp_ticker"][:, ticker_index] * standardize(vrp)
                     + ...)
    prob_samples = 1 / (1 + np.exp(-logit_samples))

    # Posterior statistics
    prob_mean = np.mean(prob_samples)
    prob_ci = np.percentile(prob_samples, [5, 95])

    # Backward-compatible label (for existing UI)
    if prob_mean > 0.70:
        signal = "GREEN"
    elif prob_mean > 0.55:
        signal = "YELLOW"
    else:
        signal = "RED"

    # Confidence based on CI width
    ci_width = prob_ci[1] - prob_ci[0]
    confidence = "high" if ci_width < 0.15 else "medium" if ci_width < 0.25 else "low"

    return {...}
```

**Key design decision: backward compatibility**
- Keep GREEN/YELLOW/RED for the UI (users understand traffic lights)
- But now the thresholds are calibrated: GREEN = "model says >70% win probability" (not "score >= 5")
- Add probability and confidence as additional context
- The UI shows "GREEN (78% +/- 7%)" instead of just "GREEN"

### Phase 3E: Online Updating (The Continuous Learning Loop)

Every night when `score-predictions.yml` scores new predictions:

```python
def update_model(new_outcomes, prior_trace):
    """
    Bayesian online update: use yesterday's posterior as today's prior.

    This is approximate online learning — full refit monthly,
    warm-start daily.
    """
    # Option 1: Full refit with all data (monthly, ~30 min)
    # Option 2: Importance-weighted update (daily, ~30 sec)
    #   - Weight old samples by likelihood of new data
    #   - Resample to get updated posterior
    # Option 3: Variational inference update (daily, ~2 min)
    #   - Use yesterday's variational parameters as initialization
    #   - Run 100 VI steps on new data

    # Recommended: Option 3 (fast enough for daily, accurate enough for trading)
```

**Schedule:**
- Daily (after score-predictions): warm-start VI update with new outcomes
- Weekly (Sunday basket-test time): full MCMC refit with all historical data
- Monthly: model comparison (WAIC/LOO) to test if new features improve fit

## What Wrong Looks Like

### Wrong: Using flat (non-informative) priors
**Symptom:** Model with 300 data points gives coefficients of +15 or -20 (absurd magnitudes)
**Cause:** Flat priors let the likelihood dominate; small samples + correlated features = extreme estimates
**Why it's dangerous:** The model might say "VRP doesn't matter but skew has coefficient +12" — which just means skew is overfitting to noise in a small sample
**Fix:** Use weakly informative priors: Normal(0, 1) for standardized coefficients. This encodes "we expect effects in the range of -2 to +2 standard deviations" — generous but prevents absurdity.

### Wrong: Updating too frequently
**Symptom:** Signal flips GREEN to RED and back daily on the same ticker with similar inputs
**Cause:** Daily refitting on the latest 20 outcomes causes recency bias — one bad week swings all coefficients
**Why it's dangerous:** Users lose trust; system seems erratic
**Fix:** Monthly granularity on time-varying coefficients (Phase 3B). The random walk prior tau controls how fast coefficients can change — set it so 95% of monthly changes are < 0.2 standard deviations.

### Wrong: Not validating calibration
**Symptom:** Model says "80% probability" but actual win rate for those predictions is 65%
**Cause:** Model is overconfident (common in logistic regression with correlated features)
**Why it's dangerous:** Users trust the probability and size positions accordingly — miscalibrated probabilities lead to wrong position sizes
**Fix:** Calibration plot: bin predictions by model probability (0-10%, 10-20%, ..., 90-100%), plot actual win rate in each bin. If not on the diagonal, apply Platt scaling or check for missing features.

### Wrong: Treating the posterior mean as ground truth
**Symptom:** "VRP coefficient is 0.42, therefore VRP definitely matters"
**Cause:** Ignoring the posterior uncertainty — the 95% CI might be [0.01, 0.83]
**Why it's dangerous:** Building downstream decisions on point estimates loses the whole advantage of going Bayesian
**Fix:** Always propagate uncertainty. Signal output must include CI. Position sizing should use the conservative end of the CI (lower bound of expected P&L), not the mean.

### Wrong: Hierarchical model with too few tickers per group
**Symptom:** Ticker-level coefficients are all identical to the population mean
**Cause:** With 350 tickers but only 60 days of data each, the hierarchical model aggressively shrinks to the mean — no ticker-level differentiation
**Fix:** This is actually correct behavior early on! The model is saying "I don't have enough data to distinguish tickers." Run the model quarterly; after 1 year (~250 observations per ticker), differentiation will emerge naturally.

### Wrong: Adding too many features without model comparison
**Symptom:** Model has 15 features, fits perfectly in-sample, prediction quality is worse than the simple 5-feature version
**Cause:** Overfitting despite Bayesian regularization — when features outnumber effective degrees of freedom
**Fix:** Use WAIC (Widely Applicable Information Criterion) or LOO-CV (Leave-One-Out Cross-Validation via PSIS) to compare models. Only add features that improve out-of-sample predictive density. PyMC computes these automatically with `pm.compare()`.

## Acceptance Criteria

- [ ] Bayesian logistic regression fits on full prediction history (all scored predictions in Supabase)
- [ ] Calibration plot shows <5% absolute deviation from diagonal in each probability bin
- [ ] Time-varying coefficients show interpretable regime shifts (e.g., VRP coefficient drops during 2022 rate shock)
- [ ] Hierarchical model identifies at least 3 ticker clusters with meaningfully different coefficient profiles
- [ ] Signal output includes probability + CI, backward-compatible GREEN/YELLOW/RED labels
- [ ] Daily VI update completes in <5 minutes on GitHub Actions runner
- [ ] Out-of-sample log-likelihood improves over static logistic regression by >5% (measured via LOO-CV)
- [ ] Existing scorecard metrics (win rate, P&L) improve or stay flat when switching from static to Bayesian signals

---

# Proposal 4: Copula-Based Tail Dependency & Dynamic Portfolio Construction

## What It Is
Replace the simple correlation analysis in Module 6 with a vine copula framework that captures how dependencies change in the tails — then use it to build portfolios that are genuinely diversified against crisis scenarios, not just diversified in normal times.

## Why It Matters (The Edge Argument)

Module 6A already revealed the problem: 350 names reduce to ~3 independent bets in normal markets and ~1 in a crisis. But the "crisis correlation" analysis (SPY < -1% days) is crude:

1. **Threshold is arbitrary**: Why -1%? At -0.5%, you get different correlations. At -3%, different again.
2. **Correlation is symmetric**: It doesn't distinguish between "crash together" and "rally together." For short premium sellers, only the former matters.
3. **Correlation is linear**: Two stocks can have 0.3 correlation overall but 0.9 correlation in the left tail. Linear correlation is blind to this.
4. **Correlation is not a copula**: Correlation summarizes one number; the full dependency structure requires a function over the entire joint distribution.

The practical consequence: you might hold 20 "diversified" short puts that all blow up simultaneously in a crash, because their **tail dependence** is 0.8 even though their **correlation** is 0.4.

## How to Do It Right

### Phase 4A: Marginal Distribution Fitting

Before modeling dependencies, fit each ticker's return distribution individually:

```python
from scipy.stats import t as student_t, nct, skewnorm

def fit_marginal(returns: np.ndarray) -> dict:
    """
    Fit best marginal distribution to a ticker's returns.

    Try:
    1. Skewed Student's t (skewnorm * t hybrid or Hansen's skewed t)
    2. Standard Student's t
    3. Normal (fallback)

    Select by BIC (penalizes complexity).
    """
    # Standardize
    mu, sigma = returns.mean(), returns.std()
    z = (returns - mu) / sigma

    # Fit Student's t
    df_t, loc_t, scale_t = student_t.fit(z)
    ll_t = student_t.logpdf(z, df_t, loc_t, scale_t).sum()
    bic_t = -2 * ll_t + 3 * np.log(len(z))

    # Fit skewed t (Hansen parameterization)
    # ... (more complex, 4 parameters)

    # Transform to uniform margins via probability integral transform
    u = student_t.cdf(z, df_t, loc_t, scale_t)  # u ~ Uniform(0,1) if model is correct

    return {"distribution": "student_t", "params": (df_t, loc_t, scale_t),
            "uniform_margins": u, "bic": bic_t}
```

**Why this matters:**
- Copulas model the **dependency structure** separately from marginals
- If marginals are wrong (e.g., using normal when tails are fat), the copula will compensate by showing spurious tail dependence
- Getting marginals right is prerequisite for meaningful copula analysis

**Validation:**
- Plot u (uniform margins) histogram — should be flat (uniform). If it's U-shaped or J-shaped, the marginal is wrong.
- Run Kolmogorov-Smirnov test: `kstest(u, 'uniform')` — p > 0.05 required.

### Phase 4B: Pairwise Copula Selection

For each pair of tickers, fit multiple copula families and select the best:

```python
COPULA_FAMILIES = {
    "gaussian": {
        "params": ["rho"],  # one correlation parameter
        "tail_dependence": {"lower": 0, "upper": 0},  # NO tail dependence
        "when_to_use": "symmetric, light-tailed dependency",
    },
    "student_t": {
        "params": ["rho", "df"],  # correlation + degrees of freedom
        "tail_dependence": "symmetric, increases as df decreases",
        "when_to_use": "symmetric tail dependency (both tails)",
    },
    "clayton": {
        "params": ["theta"],  # theta > 0
        "tail_dependence": {"lower": "2^(-1/theta)", "upper": 0},
        "when_to_use": "LEFT tail dependency (crash together), independent in right tail",
    },
    "gumbel": {
        "params": ["theta"],  # theta >= 1
        "tail_dependence": {"lower": 0, "upper": "2 - 2^(1/theta)"},
        "when_to_use": "RIGHT tail dependency (rally together), independent in left tail",
    },
    "frank": {
        "params": ["theta"],
        "tail_dependence": {"lower": 0, "upper": 0},
        "when_to_use": "symmetric, no tail dependency (like gaussian but flexible)",
    },
    "survival_clayton": {  # 180-degree rotated Clayton
        "params": ["theta"],
        "tail_dependence": {"lower": 0, "upper": "2^(-1/theta)"},
        "when_to_use": "RIGHT tail dependency, opposite of Clayton",
    },
}
```

**For each pair (i, j):**
```
1. Extract uniform margins: u_i, u_j (from Phase 4A)
2. For each copula family:
   a. Fit parameters via maximum likelihood
   b. Compute AIC = -2*loglik + 2*n_params
3. Select family with lowest AIC
4. Extract tail dependence coefficients:
   - lambda_lower = P(U_j < q | U_i < q) as q -> 0
   - lambda_upper = P(U_j > 1-q | U_i > 1-q) as q -> 0
5. Store: (pair, family, params, lambda_lower, lambda_upper, aic)
```

**Expected findings for options selling portfolio:**
- Most equity pairs: **Clayton** copula (crash together, independent rally) — this is the fundamental risk of short premium
- VIX-related pairs: **Student's t** copula (symmetric tail dependence — vol spikes affect everything)
- Cross-sector pairs (e.g., XLE vs XLK): **Gaussian** copula (no tail dependence — genuinely independent in extremes)

### Phase 4C: Vine Copula Construction

With ~50 tickers, fitting all C(50,2) = 1,225 pair copulas independently ignores higher-order dependencies. A vine copula provides a structured way to model the full joint distribution:

```
D-vine structure (simplified):

    Tree 1: Pair copulas for (1,2), (2,3), (3,4), ..., (n-1,n)
            These are unconditional bivariate copulas

    Tree 2: Conditional pair copulas for (1,3|2), (2,4|3), ..., (n-2,n|n-1)
            These capture dependency AFTER accounting for the shared neighbor

    Tree 3: (1,4|2,3), (2,5|3,4), ..., etc.
            Higher-order conditional dependencies

    ... up to Tree n-1
```

**Implementation approach:**
- Use the `pyvinecopulib` library (C++ backend, very fast)
- Or implement a simplified version: only Trees 1-3 (captures >90% of dependency structure)
- Truncation: after Tree 3, assume conditional independence (standard practice for n > 20)

```python
import pyvinecopulib as pv

def fit_vine_copula(uniform_margins: np.ndarray, n_tickers: int):
    """
    Fit D-vine copula to portfolio returns.

    Args:
        uniform_margins: (T, n_tickers) array of uniform-transformed returns

    Returns:
        Fitted vine copula object
    """
    # Controls
    controls = pv.FitControlsVinecop(
        family_set=[pv.BicopFamily.gaussian,
                    pv.BicopFamily.student,
                    pv.BicopFamily.clayton,
                    pv.BicopFamily.gumbel,
                    pv.BicopFamily.frank],
        trunc_lvl=3,           # truncate after tree 3
        selection_criterion="aic",
        num_threads=4,
    )

    # Fit
    cop = pv.Vinecop(uniform_margins, controls=controls)

    return cop
```

### Phase 4D: Portfolio Tail Risk Quantification

Use the fitted vine copula to simulate 100,000 joint return scenarios:

```python
def simulate_portfolio_scenarios(vine_copula, marginal_params, n_sims=100000):
    """
    Generate joint return scenarios from vine copula.

    Steps:
    1. Sample from vine copula -> uniform margins (T, n_tickers)
    2. Transform each margin back to returns via inverse CDF of fitted marginal
    3. Compute portfolio P&L under each scenario
    """
    # Sample uniform margins
    u_sims = vine_copula.simulate(n_sims)  # (100000, n_tickers)

    # Transform to returns
    returns_sims = np.zeros_like(u_sims)
    for j in range(n_tickers):
        dist = marginal_params[j]["distribution"]
        params = marginal_params[j]["params"]
        returns_sims[:, j] = dist.ppf(u_sims[:, j], *params)

    # Compute portfolio-level P&L (assuming short straddle on each ticker)
    portfolio_pnl = np.zeros(n_sims)
    for j in range(n_tickers):
        premium = positions[j]["premium_collected"]
        expected_move = positions[j]["expected_move"]
        actual_move = np.abs(returns_sims[:, j]) * positions[j]["spot"]
        pnl_j = np.where(actual_move < expected_move, premium, premium - (actual_move - expected_move))
        portfolio_pnl += pnl_j * positions[j]["contracts"]

    return {
        "mean_pnl": portfolio_pnl.mean(),
        "var_95": np.percentile(portfolio_pnl, 5),
        "cvar_95": portfolio_pnl[portfolio_pnl < np.percentile(portfolio_pnl, 5)].mean(),
        "var_99": np.percentile(portfolio_pnl, 1),
        "cvar_99": portfolio_pnl[portfolio_pnl < np.percentile(portfolio_pnl, 1)].mean(),
        "worst_case": portfolio_pnl.min(),
        "prob_total_loss_gt_10pct": (portfolio_pnl < -0.10 * portfolio_value).mean(),
    }
```

**Why copula simulation >> historical stress tests:**
- Historical stress tests replay 3 past events (COVID, Volmageddon, Aug 2024)
- Copula simulation generates scenarios **worse** than any historical event
- The 99.9th percentile copula scenario might be "COVID-level correlation + Volmageddon-level VIX + 2x larger moves" — something that hasn't happened yet but *could*
- This is how banks compute regulatory capital requirements (Basel III uses copula-based models)

### Phase 4E: Tail-Risk-Constrained Portfolio Optimization

Given the copula model, find the portfolio that maximizes expected VRP capture subject to tail risk constraints:

```python
from scipy.optimize import minimize

def optimize_portfolio(expected_pnl, cvar_func, positions, constraints):
    """
    Find position sizes that maximize expected P&L subject to CVaR constraint.

    Decision variables: w = [w_1, w_2, ..., w_n] (contracts per ticker)

    Objective: maximize sum(w_i * expected_pnl_i)

    Subject to:
        CVaR_95(w) > -max_loss_budget          # tail risk budget
        sum(w_i * margin_i) < total_capital     # capital constraint
        w_i <= max_position_size                 # per-position limit
        w_i >= 0                                 # long-only (selling premium)
        sector_exposure(w) < sector_limit        # concentration limit
        N_eff(w) > min_independent_bets          # diversification floor
    """
    def objective(w):
        return -np.dot(w, expected_pnl)  # negative because we minimize

    def cvar_constraint(w):
        # Compute CVaR via copula simulation with these weights
        portfolio_pnl = sum(w[j] * pnl_scenarios[:, j] for j in range(n))
        cvar = portfolio_pnl[portfolio_pnl < np.percentile(portfolio_pnl, 5)].mean()
        return cvar - (-max_loss_budget)  # must be >= 0

    def capital_constraint(w):
        return total_capital - sum(w[j] * margin[j] for j in range(n))

    result = minimize(objective, x0=equal_weights, method='SLSQP',
                      constraints=[
                          {'type': 'ineq', 'fun': cvar_constraint},
                          {'type': 'ineq', 'fun': capital_constraint},
                      ],
                      bounds=[(0, max_contracts[j]) for j in range(n)])

    return result.x
```

**The N_eff constraint is critical:**
```python
def effective_independent_bets(weights, correlation_matrix):
    """
    Compute effective number of independent bets.

    N_eff = (sum w_i)^2 / (w' * Sigma * w)
    where Sigma is the correlation (not covariance) matrix

    For equal weights on identical assets: N_eff = 1
    For equal weights on independent assets: N_eff = N
    """
    w = weights / weights.sum()
    return 1.0 / (w @ correlation_matrix @ w)
```

This constraint forces the optimizer to spread across uncorrelated names, preventing the "5 tech stocks" failure mode.

### Phase 4F: Integration

**New file: `portfolio_optimizer.py`** (~800-1000 lines)
- Marginal fitting
- Pair copula selection
- Vine copula construction
- Scenario simulation
- Portfolio optimization

**Wire into streamlit_app.py:**
- Replace Module 6A's simple correlation with copula-based tail dependence matrix
- New "Portfolio Optimizer" section in Dashboard: recommended position sizes per ticker
- Heatmap: tail dependence coefficients (red = high, green = low)
- Scenario distribution: histogram of 100K portfolio P&L outcomes

**Wire into batch_sampler.py (weekly):**
- Refit vine copula every Sunday (alongside basket test)
- Store copula parameters and tail dependence matrix in Supabase
- Track tail dependence evolution over time (does it increase before crises?)

## What Wrong Looks Like

### Wrong: Using Gaussian copula for everything
**Symptom:** Tail risk estimates are too optimistic; copula VaR << historical worst loss
**Cause:** Gaussian copula has zero tail dependence by construction — it literally cannot model crash co-dependence
**Why it's dangerous:** This is exactly the error that caused the 2008 financial crisis. CDO pricing used Gaussian copulas (Li, 2000), which underestimated joint default probability. The model said "these mortgages are diversified" when they weren't.
**Fix:** Always include Clayton and Student's t in the family set. If AIC selects Gaussian for equity pairs, be suspicious — plot the lower tail scatter and visually verify.

### Wrong: Fitting copulas to raw returns instead of uniform margins
**Symptom:** Copula parameters are unstable; Clayton theta oscillates wildly
**Cause:** Copulas assume uniform marginals. If you feed in raw returns (which are fat-tailed), the copula tries to model both the marginal AND the dependency — it can't separate them.
**Fix:** Phase 4A (marginal fitting + PIT transform) MUST come first. Validate with KS test that margins are uniform.

### Wrong: Not truncating the vine for large portfolios
**Symptom:** Fitting a 50-ticker vine takes 4 hours and produces garbage estimates
**Cause:** Full vine with 49 trees has C(50,2)=1,225 pair copulas at tree 1, plus hundreds more at higher trees. Not enough data to estimate them all reliably.
**Fix:** Truncate at tree 3 (standard in literature for n>20). This captures ~95% of the dependency structure. Higher trees model "dependency conditional on 3+ other variables" which requires enormous samples.

### Wrong: Optimizing portfolio on in-sample copula
**Symptom:** Optimal portfolio looks great in backtest but crashes out-of-sample
**Cause:** Copula was fit to the same data used for optimization — the optimizer exploits estimation noise
**Fix:** Walk-forward approach: fit copula on years 1-3, optimize portfolio for year 4, evaluate on year 4. Slide forward. This mirrors Module 4's walk-forward design.

### Wrong: Using copula simulation as a substitute for circuit breakers
**Symptom:** "The copula says our 99th percentile loss is only 8%, so we don't need VIX-based circuit breakers"
**Cause:** Copula is estimated from historical data — it can't model unprecedented events (9/11, pandemic)
**Why it's dangerous:** Copula gives you the distribution of **known risks**. Circuit breakers protect against **unknown risks** (Knightian uncertainty).
**Fix:** Copula simulation sets position sizes; circuit breakers are a separate, independent safety layer. Both must coexist. Module 8C circuit breakers are non-negotiable regardless of copula estimates.

### Wrong: Interpreting tail dependence as correlation
**Symptom:** "AAPL-MSFT tail dependence is 0.4, so they're 40% correlated"
**Cause:** Tail dependence lambda=0.4 means "if AAPL is in its worst 1% of days, there's a 40% chance MSFT is also in its worst 1%." This is NOT the same as 40% correlation.
**Fix:** Always label outputs clearly. Tail dependence is a conditional probability, not a correlation. Provide plain-English interpretation in the UI: "When AAPL crashes hard (worst 1% of days), MSFT crashes with it 40% of the time."

## Acceptance Criteria

- [ ] Marginal distributions pass KS test (p > 0.05) for >90% of tickers
- [ ] Copula family selection correctly identifies Clayton for known crash-correlated pairs (e.g., AAPL-MSFT)
- [ ] Vine copula fits 50-ticker universe in <4 hours (truncated at tree 3)
- [ ] 100K scenario simulation completes in <5 minutes
- [ ] Copula-based CVaR is more conservative than historical CVaR (it should be — copula extrapolates beyond observed data)
- [ ] Optimized portfolio has higher Sortino ratio than equal-weighted portfolio in walk-forward test
- [ ] N_eff constraint produces portfolios with >8 effective independent bets (vs ~3 for equal-weighted)
- [ ] Tail dependence matrix is stored and visualizable as heatmap in Streamlit

---

# Proposal 5: Autonomous Decision Agent with Reinforcement Learning

## What It Is
Train a reinforcement learning agent that learns the optimal trading policy — when to enter, how much to trade, when to exit, when to roll — from historical data and the full evaluation pipeline. The agent operates as a recommendation engine with human oversight, not as an autonomous trader.

## Why It Matters (The Edge Argument)

The current system has:
- 7 signal components combined into a point score
- 9 exit triggers with fixed thresholds
- Kelly-based sizing with fixed quarter-Kelly cap
- Circuit breakers with fixed VIX thresholds

Each of these was designed independently. But the **optimal decision at any moment depends on the full state**: your current portfolio Greeks, how many positions are open, how much capital is deployed, what regime you're in, what happened yesterday. The dimensionality is too high for hand-coded rules.

Example: Should you sell a put on NVDA when VRP = 5 (GREEN signal)?
- If portfolio vega is already -$5,000 and NVDA would add -$800 more → probably not
- If it's 3 days before FOMC and VIX is 22 → maybe wait
- If you already have 3 tech names and NVDA correlates 0.8 with them → definitely not
- If your last 5 trades all lost money (drawdown) → reduce size, not skip

A rules-based system handles each of these with separate if/else blocks. An RL agent learns the *joint* optimal response from data.

## How to Do It Right

### Phase 5A: Environment Design (The Most Important Phase)

The RL environment defines what the agent can see, what it can do, and what it gets rewarded for. Getting this right is 80% of the work.

```python
class OptionSellingEnv:
    """
    Gym-compatible environment for option selling portfolio management.

    Time step: 1 trading day
    Episode: 1 year (252 trading days)
    """

    # OBSERVATION SPACE (what the agent sees)
    # Per-ticker signals (for top N candidates, e.g., N=20):
    #   vrp, iv_rank, term_structure, regime, skew,
    #   bayesian_prob (from Proposal 3), vrp_surface_richness (from Proposal 1)
    # Per-open-position (max M=10 positions):
    #   unrealized_pnl, days_held, current_delta, current_theta, current_vega,
    #   pct_of_max_profit_captured, pct_of_max_loss_hit
    # Portfolio-level:
    #   total_vega, total_theta, theta_gamma_ratio, deployed_capital_pct,
    #   current_drawdown_pct, n_eff (effective independent bets),
    #   portfolio_cvar (from Proposal 4)
    # Market-level:
    #   vix, vix_term_structure, spy_20d_return, days_to_fomc, days_to_quad_witching

    observation_dim = 20 * 7 + 10 * 7 + 8 + 5  # = 283 features

    # ACTION SPACE (what the agent can do)
    # For each open position: {hold, close, roll_out, roll_out_and_up/down}
    # For each candidate: {skip, open_small, open_medium, open_large}
    # Portfolio-level: {sizing_normal, sizing_reduced, sizing_halted}

    # Simplified to discrete:
    # action = (position_actions[M], candidate_actions[N], portfolio_action)
    # Total: 4^10 * 4^20 * 3 ... way too large for discrete

    # Better: Parameterized action space
    # For each of top 5 candidates: continuous [0, 1] = fraction of max Kelly to deploy
    # For each open position: continuous [-1, 0, 1] = close / hold / roll
    # This is a continuous action space, suitable for SAC or PPO with continuous actions

    action_dim = 5 + 10  # 5 candidates + 10 positions = 15 continuous values
```

**Key environment design decisions:**

**1. Observation normalization:**
All features must be normalized to roughly [-1, 1] or [0, 1] range. Neural networks can't learn from features that range from 0.001 (skew) to 50,000 (notional).

```python
def normalize_observation(raw_obs):
    # VRP: typical range [-5, 15] -> divide by 10
    # IV Rank: already [0, 100] -> divide by 100
    # Theta: typical range [-500, 0] -> divide by -500
    # Drawdown: [0, -0.30] -> divide by 0.30
    # VIX: typical [10, 80] -> (vix - 20) / 30
    ...
```

**2. Action masking:**
Not all actions are valid at all times. Mask invalid actions:
- Can't close a position that doesn't exist
- Can't open new positions if circuit breaker is active
- Can't exceed capital limits

```python
def get_action_mask(state):
    mask = np.ones(action_dim)
    for i in range(10):
        if not positions[i].is_open:
            mask[5 + i] = 0  # can't act on non-existent position
    if state.circuit_breaker_active:
        mask[:5] = 0  # can't open new positions
    return mask
```

**3. Reward design (CRITICAL):**

```python
def compute_reward(state, action, next_state):
    """
    Reward must encode:
    1. P&L (obvious)
    2. Risk management (less obvious but essential)
    3. Transaction cost penalty (prevents churning)

    BAD reward: just daily P&L
    - Agent will maximize leverage, ignore tail risk, and blow up

    GOOD reward: risk-adjusted P&L with penalties
    """
    # Daily P&L of portfolio
    daily_pnl = next_state.portfolio_value - state.portfolio_value
    daily_return = daily_pnl / state.portfolio_value

    # Risk-adjusted component (Sortino-like)
    # Track rolling 20-day downside deviation
    if daily_return < 0:
        downside_penalty = daily_return ** 2 * 10  # quadratic penalty for losses
    else:
        downside_penalty = 0

    # Tail risk penalty (from copula CVaR)
    cvar_exceedance = max(0, -next_state.portfolio_cvar - cvar_budget)
    tail_penalty = cvar_exceedance * 50  # heavy penalty for exceeding tail risk budget

    # Concentration penalty
    if next_state.n_eff < min_independent_bets:
        concentration_penalty = (min_independent_bets - next_state.n_eff) * 0.01
    else:
        concentration_penalty = 0

    # Transaction cost (prevents churning)
    n_trades = count_new_trades(action)
    tc_penalty = n_trades * avg_spread_cost

    # Circuit breaker compliance (hard penalty)
    if violated_circuit_breaker(state, action):
        return -10.0  # massive negative reward, episode doesn't end but agent learns fast

    reward = daily_return - downside_penalty - tail_penalty - concentration_penalty - tc_penalty

    return reward
```

### Phase 5B: Historical Environment Construction

The agent needs a realistic training environment built from actual data:

```python
class HistoricalEnvironment(OptionSellingEnv):
    """
    Replay historical data as the environment.

    Data sources:
    - iv_snapshots table: daily IV, RV, VRP, signals for 350 tickers (since sampling began)
    - Yahoo Finance OHLCV: for realized moves and Greek calculations
    - VIX data: for circuit breaker logic
    - FOMC dates: for calendar features

    For longer history (pre-sampling):
    - Reconstruct synthetic snapshots from OHLCV data
    - Use RV * 1.2 as IV proxy (same as backtest in analytics.py)
    - This gives 6+ years of training data
    """

    def __init__(self, start_date, end_date, tickers):
        # Load all historical data into memory
        self.ohlcv = load_ohlcv(tickers, start_date, end_date)
        self.iv_snapshots = load_snapshots(tickers, start_date, end_date)
        self.vix = load_vix(start_date, end_date)

        # Pre-compute daily features for all tickers
        self.daily_features = precompute_features(self.ohlcv, self.iv_snapshots)

        # Pre-compute option prices for realistic P&L
        # Use BSM with historical IV for each day's ATM straddle
        self.option_prices = precompute_option_prices(self.ohlcv, self.iv_snapshots)

    def step(self, action):
        """
        Advance one trading day.

        1. Execute action (open/close/hold positions)
        2. Advance to next day
        3. Mark-to-market all positions using next day's prices
        4. Check for expiring positions (settle)
        5. Compute reward
        6. Return (next_obs, reward, done, info)
        """
```

**Critical: no look-ahead bias**
- When the agent decides on day T, it can only see data through day T
- Option P&L uses day T+1 prices (or later, for multi-day holds)
- VRP computation uses RV from past (backward-looking), not future (forward-looking)
- Same anti-bias approach as Module 4's walk-forward backtest

### Phase 5C: Training Pipeline

```python
# Using Stable-Baselines3 (most mature RL library for continuous actions)
from stable_baselines3 import SAC  # Soft Actor-Critic (best for continuous actions)

# Or CleanRL for more transparency (single-file implementations)

def train_agent():
    # 1. Create environment
    env = HistoricalEnvironment(
        start_date="2019-01-01",
        end_date="2025-12-31",
        tickers=CORE_20_TICKERS,
    )

    # 2. Configure SAC
    model = SAC(
        "MlpPolicy",
        env,
        learning_rate=3e-4,
        buffer_size=1_000_000,
        learning_starts=10_000,      # explore randomly for first 10K steps
        batch_size=256,
        tau=0.005,                    # soft target update
        gamma=0.99,                   # discount factor (0.99 = care about ~100 days ahead)
        train_freq=1,                 # update every step
        gradient_steps=1,
        policy_kwargs={
            "net_arch": [256, 256],   # 2 hidden layers, 256 units each
        },
        verbose=1,
    )

    # 3. Train
    # 6 years * 252 days * 20 tickers = ~30K steps per episode
    # Train for 100 episodes = 3M steps
    model.learn(total_timesteps=3_000_000)

    # 4. Evaluate on held-out data
    eval_env = HistoricalEnvironment(
        start_date="2026-01-01",
        end_date="2026-03-22",
        tickers=CORE_20_TICKERS,
    )
    mean_reward, std_reward = evaluate_policy(model, eval_env, n_eval_episodes=10)

    return model
```

**Hyperparameter sensitivity (what to tune carefully):**
- `gamma` (discount factor): 0.99 means the agent values rewards 100 days ahead at 37% of today's reward. Too low (0.9) = myopic, takes excessive risk for short-term gain. Too high (0.999) = sluggish, won't close losing positions.
- `learning_rate`: Too high (1e-3) = unstable training, policy oscillates. Too low (1e-5) = takes forever. Start at 3e-4, decay to 1e-4 over training.
- `net_arch`: [256, 256] is standard. Bigger networks (512, 512) can model more complex policies but need more data. With 3M steps, [256, 256] is appropriate.

### Phase 5D: Interpretability Layer (Non-Negotiable for Trading)

A black-box RL agent that says "sell 3 contracts of SPY April 520 puts" with no explanation is unusable. The interpretability layer explains WHY:

```python
def explain_decision(agent, observation, action):
    """
    Generate human-readable explanation of agent's decision.

    Three complementary approaches:
    """

    # 1. SHAP values (feature attribution)
    # Which features drove this decision?
    import shap
    explainer = shap.DeepExplainer(agent.policy.actor, background_obs)
    shap_values = explainer.shap_values(observation)
    top_features = sorted(zip(feature_names, shap_values[0]), key=lambda x: abs(x[1]), reverse=True)[:5]
    # Output: "Top drivers: VRP (SPY)=0.32, portfolio_vega=-0.28, drawdown=0.15, ..."

    # 2. Counterfactual analysis
    # What would the agent do if X were different?
    counterfactuals = {}
    for feature in ["vix", "portfolio_vega", "drawdown"]:
        modified_obs = observation.copy()
        modified_obs[feature_index[feature]] += 0.1  # small perturbation
        counterfactual_action = agent.predict(modified_obs)
        counterfactuals[feature] = counterfactual_action - action
    # Output: "If VIX were 2 points higher, agent would reduce SPY position by 1 contract"

    # 3. Policy distillation (offline, periodic)
    # Compress the neural network into a decision tree
    from sklearn.tree import DecisionTreeRegressor

    # Collect (observation, action) pairs from trained agent
    obs_buffer, action_buffer = [], []
    for obs in historical_observations:
        action = agent.predict(obs)
        obs_buffer.append(obs)
        action_buffer.append(action)

    # Fit decision tree
    tree = DecisionTreeRegressor(max_depth=6)  # human-readable depth
    tree.fit(obs_buffer, action_buffer)

    # The tree IS the explanation:
    # "If VRP > 3.2 AND portfolio_vega > -2000 AND drawdown < 5%: open medium position"
    # "If VRP > 3.2 AND portfolio_vega < -2000: skip (vega budget exhausted)"

    return {
        "shap_top_5": top_features,
        "counterfactuals": counterfactuals,
        "distilled_rule": tree.decision_path(observation),
    }
```

**The distilled decision tree is the real deliverable.** The neural network is the learning engine; the tree is the product. After training, the tree replaces the current hand-coded thresholds with empirically optimal ones.

### Phase 5E: Paper Trading and Validation

**NEVER deploy an RL agent to live trading without extensive paper trading.**

```
Month 1-3: Shadow mode
    - Agent generates daily recommendations
    - Existing rule-based system also generates recommendations
    - Both are logged; neither executes
    - Track: where do they agree? Where do they disagree?
    - Human reviews every disagreement

Month 4-6: Split-test mode
    - Paper-trade agent's recommendations on half the universe
    - Paper-trade rule-based on the other half
    - Weekly comparison: Sharpe, drawdown, win rate, P&L

Month 7-12: Gradual deployment
    - If agent outperforms on paper:
      - Start with 25% of capital following agent
      - 75% still rule-based
      - Increase agent allocation by 25% per quarter if performance holds

Kill switch: If agent's rolling 30-day Sharpe drops below -0.5,
             immediately revert to rule-based system
```

### Phase 5F: Integration

**New file: `rl_agent.py`** (~600-800 lines)
- Environment class
- Training script (offline, run on GPU)
- Inference function (daily, lightweight)
- Explanation generator

**New file: `rl_environment.py`** (~400-500 lines)
- Historical data loader
- Feature engineering pipeline
- Reward computation
- Action validation and masking

**Wire into streamlit_app.py:**
- New "AI Recommendations" section in Dashboard
- Shows: agent's top 5 recommendations with explanations
- Side-by-side comparison with rule-based signal
- Disagreement highlighting: "Agent says SKIP but rules say GREEN — here's why"

**Wire into GitHub Actions:**
- New workflow: `rl-daily-inference.yml`
- Runs after score-predictions (needs latest data)
- Loads trained model, generates recommendations for next day
- Stores in Supabase `rl_recommendations` table

**Wire into scorecard:**
- Track RL recommendations alongside rule-based predictions
- Compare: RL win rate, RL P&L, RL Sharpe vs. baseline
- Show disagreement analysis: does the agent add value precisely when it disagrees?

## What Wrong Looks Like

### Wrong: Training on too little data
**Symptom:** Agent learns one specific market regime and fails when regime changes
**Cause:** 6 years of daily data = ~1,500 time steps. For an RL agent with 283 features, this is tiny.
**Why it's dangerous:** Agent might learn "always sell because 2020-2024 was mostly a bull market" — then blow up in the next crash
**Fix:**
1. Data augmentation: perturb historical scenarios (add noise to returns, shift VIX levels)
2. Curriculum learning: train on synthetic environments first (GBM with varying parameters), then fine-tune on historical
3. Domain randomization: randomly vary transaction costs, slippage, regime boundaries during training
4. Ensemble: train 5 agents with different random seeds, use majority vote

### Wrong: Reward hacking
**Symptom:** Agent finds a "cheat" — e.g., always closes positions at +$0.01 profit to maximize win count without maximizing P&L
**Cause:** Reward function inadvertently incentivizes a degenerate strategy
**Why it's dangerous:** Agent looks great on one metric (win rate) while destroying another (total return)
**Examples of reward hacking to watch for:**
- Closing winners immediately, holding losers forever (creates positive win rate but negative P&L)
- Never trading (0 risk = 0 downside penalty = moderate reward from time decay)
- Opening and closing the same position repeatedly (if transaction cost penalty is too low)
**Fix:**
1. Multi-metric reward: P&L + Sortino + drawdown penalty (harder to hack all three)
2. Minimum holding period: can't close within 5 days of opening
3. Minimum trade frequency: must open at least N trades per month (prevents "do nothing" strategy)
4. Regular human review of agent behavior logs

### Wrong: Overfitting to the training environment
**Symptom:** Agent achieves 300% annualized return in training, 5% in paper trading
**Cause:** Agent memorized the historical sequence — learned "buy SPY on March 23, 2020 because that's the exact COVID bottom"
**Why it's dangerous:** This is the same problem as backtesting overfitting (Module 4), but 10x worse because RL has millions of parameters
**Fix:**
1. Walk-forward training: train on 2019-2023, evaluate on 2024-2025. NEVER let training data include eval period.
2. Multiple episodes: randomize the starting date within the training period
3. Observation noise: add small random noise to features during training (regularization)
4. Compare to simple baseline: agent must beat "always follow GREEN signal with quarter-Kelly" by a statistically significant margin

### Wrong: Deploying without the interpretability layer
**Symptom:** Agent says "sell 5 contracts" and you can't explain why to the human user
**Cause:** Skipped Phase 5D because "the returns are good enough"
**Why it's dangerous:**
1. When the agent makes an unusual recommendation, you can't tell if it's brilliant or broken
2. Regulatory risk (if ever managing others' money): unexplainable AI decisions are a compliance nightmare
3. User trust: the whole product philosophy is "help users understand what they're doing" — a black box contradicts this
**Fix:** Interpretability layer is mandatory. SHAP values on every recommendation. Distilled decision tree updated monthly. Counterfactual explanations for non-obvious decisions.

### Wrong: Not having a kill switch
**Symptom:** Agent starts losing money consistently but keeps generating recommendations
**Cause:** No automated monitoring of agent performance vs. baseline
**Why it's dangerous:** Unlike the rule-based system (which has Module 8 CUSUM), the RL agent has no built-in self-monitoring
**Fix:**
1. Rolling 30-day comparison: RL Sharpe vs. rules-based Sharpe
2. If RL underperforms by >0.5 Sharpe for 30 days: automatic alert
3. If RL underperforms for 60 days: automatic revert to rules-based
4. The kill switch is in the code, not in a human's head — it executes automatically

### Wrong: Letting the agent modify its own reward function
**Symptom:** Agent discovers it can influence its own observations (e.g., by opening positions that change portfolio metrics)
**Cause:** Reward depends on portfolio state, which the agent's actions change
**Why it's dangerous:** This is a form of "reward tampering" — the agent optimizes the metric instead of the underlying goal
**Example:** Agent opens a small hedging position that reduces portfolio CVaR on paper (reducing tail penalty) but the hedge is too small to actually protect in a crash
**Fix:** Compute tail risk from the COPULA MODEL (Proposal 4), not from the agent's own portfolio metrics. The copula is fit externally and is not influenced by the agent's actions.

## Acceptance Criteria

- [ ] Environment loads 6 years of historical data and runs at >1000 steps/second
- [ ] Agent trains to convergence (rolling reward stabilizes) within 3M timesteps
- [ ] Agent outperforms rule-based system by >10% in risk-adjusted return (Sortino) on held-out 2026 data
- [ ] SHAP explanations are generated for every recommendation in <1 second
- [ ] Distilled decision tree has max depth 6 and accuracy >85% vs. neural network decisions
- [ ] Paper trading phase runs for minimum 6 months before any live capital allocation
- [ ] Kill switch tested: agent reverts to rules-based within 1 day of threshold breach
- [ ] Agent respects ALL circuit breakers from Module 8C (never violates VIX halt, drawdown halt)
- [ ] Agent does not degenerate into "never trade" or "always trade" strategies

---

# Cross-Proposal Dependencies and Build Order

```
                    QUARTER 1              QUARTER 2              QUARTER 3            QUARTER 4+

Proposal 1:    [1A: SABR calibration] → [1B: Model-free]  → [1C: Heston]       → [1D: VRP surface]
               [per-expiry smile]        [BKM moments]       [cross-expiry]        [rich/cheap map]

Proposal 3:    [3A: Bayesian logistic] → [3B: Time-varying] → [3C: Hierarchical] → [3D: Replace traffic light]
               [simple, immediate]       [monthly coeffs]     [per-ticker]          [full integration]

Proposal 2:                              [2A: Structure lib] → [2B: Candidate gen] → [2C: Scorer + UI]
                                         [needs 1A surface]    [needs 1A for VRP]    [needs 1A+3A]

Proposal 4:    [4A: Marginals]         → [4B: Pair copulas]  → [4C: Vine copula]  → [4E: Portfolio opt]
               [can start immediately]   [needs 4A]            [needs 4B]            [needs 4C + 1D]

Proposal 5:                                                                        → [5A: Environment] → [5B-F: Train + deploy]
                                                                                     [needs 1+2+3+4]     [6-12 months after 5A]
```

**Quarter 1 (start now):**
- 1A (SABR) and 3A (Bayesian logistic) and 4A (marginals) in parallel
- These are independent and immediately valuable

**Quarter 2:**
- 1B, 3B, 4B continue their tracks
- 2A starts (needs 1A's vol surface for strike-level VRP)

**Quarter 3:**
- 1C, 3C, 4C continue
- 2B-2C completes the multi-leg optimizer

**Quarter 4+:**
- 1D and 4E tie the surface and copula into portfolio optimization
- 5A begins — the RL environment needs all of the above as inputs
- 5B-5F (training and deployment): 6-12 months of work after environment is built

**Total timeline to full vision: 18-24 months of focused development.**

---

# Computational Infrastructure Requirements

| Phase | Current (GitHub Actions) | Required | Estimated Cost |
|-------|------------------------|----------|---------------|
| 1A (SABR) | Sufficient (CPU) | Same | $0 |
| 1C (Heston FFT) | Marginal (7-min limit) | Larger runner or self-hosted | $20/mo |
| 3A-3C (Bayesian) | Insufficient (MCMC is slow) | GPU runner or Colab Pro | $10-50/mo |
| 4C (Vine copula) | Insufficient (4+ hours) | 8-core self-hosted runner | $30/mo |
| 5B-5C (RL training) | Impossible | GPU instance (A10 or better) | $100-300/mo during training |
| 5F (RL inference) | Sufficient (forward pass is fast) | Same | $0 |

**Recommendation:** Start with Colab Pro ($10/mo) for Proposals 3 and 4 prototyping. Upgrade to a dedicated GPU VM ($100-300/mo) only when training the RL agent (Proposal 5, Quarter 4+).

---

# Success Metrics (How We Know This Worked)

| Metric | Current Baseline | Target (Year 1) | Target (Year 3) |
|--------|-----------------|-----------------|-----------------|
| Win rate (GREEN signals) | 80.3% | 82%+ (Bayesian calibration) | 85%+ (RL optimization) |
| Risk-adjusted return (Sortino) | 5.68-17.3 (varies by ticker) | >15 across all tickers | >20 |
| Max drawdown (worst ticker) | -285% (NVDA, uncapped) | -50% (multi-leg capping) | -25% (copula-optimized) |
| Effective independent bets | ~3 (normal), ~1 (crisis) | >8 (copula-constrained) | >12 |
| Signal calibration error | Unknown (not measured) | <5% (Bayesian) | <3% |
| Time to analyze a ticker | ~5 seconds | ~8 seconds (surface + Bayesian) | ~10 seconds (full stack) |
| Decision quality | Binary (GREEN/RED) | Probabilistic (78% +/- 7%) | Optimal (RL with explanation) |
