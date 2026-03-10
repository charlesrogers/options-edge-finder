"""
Analytics engine for Options Edge Finder.
Implements volatility estimation, VRP calculation, and trade scoring
based on concepts from "Retail Options Trading" (Sinclair & Mack, 2024).
"""

import numpy as np
import pandas as pd
from datetime import datetime
from scipy.stats import norm, lognorm, t as t_dist
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

try:
    from py_vollib.black_scholes import black_scholes as bs_price
    from py_vollib.black_scholes.greeks.analytical import delta as bs_delta
    from py_vollib.black_scholes.greeks.analytical import gamma as bs_gamma
    from py_vollib.black_scholes.greeks.analytical import theta as bs_theta
    from py_vollib.black_scholes.greeks.analytical import vega as bs_vega
    HAS_VOLLIB = True
except ImportError:
    HAS_VOLLIB = False


def calc_realized_vol(hist: pd.DataFrame, window: int = 20) -> float:
    """
    Close-to-close realized volatility, annualized.
    Chapter 3: simplest method, standard deviation of log returns.
    """
    log_returns = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
    if len(log_returns) < window:
        return 0.0
    rv = log_returns.tail(window).std() * np.sqrt(252) * 100
    return rv


def calc_parkinson_vol(hist: pd.DataFrame, window: int = 20) -> float:
    """
    Parkinson volatility estimator using high-low range.
    Chapter 3: more accurate than C2C, captures intraday.
    """
    if len(hist) < window:
        return 0.0
    recent = hist.tail(window)
    hl_ratio = np.log(recent["High"] / recent["Low"])
    parkinson = np.sqrt((1 / (4 * window * np.log(2))) * (hl_ratio ** 2).sum()) * np.sqrt(252) * 100
    return parkinson


def get_iv_rank_percentile(hist: pd.DataFrame, current_iv=None):
    """
    IV Rank: where current IV sits in 52-week high-low range.
    IV Percentile: % of days IV was below current level.
    We approximate historical IV using 20-day realized vol as a proxy
    since yfinance doesn't provide historical IV.
    """
    if current_iv is None:
        return None, None

    # Use rolling 20-day realized vol as IV proxy for historical context
    log_returns = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
    rolling_vol = log_returns.rolling(20).std() * np.sqrt(252) * 100
    rolling_vol = rolling_vol.dropna()

    if rolling_vol.empty:
        return None, None

    vol_min = rolling_vol.min()
    vol_max = rolling_vol.max()

    if vol_max == vol_min:
        return 50.0, 50.0

    # IV Rank
    iv_rank = ((current_iv - vol_min) / (vol_max - vol_min)) * 100
    iv_rank = max(0, min(100, iv_rank))

    # IV Percentile
    iv_pctl = (rolling_vol < current_iv).sum() / len(rolling_vol) * 100

    return iv_rank, iv_pctl


def get_term_structure(chains: dict, expirations: list, current_price: float):
    """
    Determine if term structure is contango, flat, or backwardation.
    Chapter 8: backwardation = short-term IV > long-term IV = danger zone for selling.
    """
    if not chains or len(expirations) < 2:
        return {}, "N/A"

    ivs = {}
    for exp in expirations:
        if exp not in chains:
            continue
        calls = chains[exp].calls
        if calls.empty or "impliedVolatility" not in calls.columns:
            continue
        calls_copy = calls.copy()
        calls_copy["dist"] = abs(calls_copy["strike"] - current_price)
        atm = calls_copy.loc[calls_copy["dist"].idxmin()]
        ivs[exp] = atm["impliedVolatility"] * 100

    if len(ivs) < 2:
        return ivs, "N/A"

    sorted_exps = sorted(ivs.keys())
    front_iv = ivs[sorted_exps[0]]
    back_iv = ivs[sorted_exps[-1]]

    if front_iv > back_iv * 1.05:
        label = "Backwardation"
    elif back_iv > front_iv * 1.02:
        label = "Contango"
    else:
        label = "Flat"

    return ivs, label


def expected_move(price: float, iv: float):
    """
    Rule of 16: daily move = price * (IV/100) / 16
    Weekly move = daily * sqrt(5)
    Chapter 3.
    """
    daily = price * (iv / 100) / 16
    weekly = daily * np.sqrt(5)
    return daily, weekly


def calc_greeks_for_chain(
    chain_df: pd.DataFrame,
    spot: float,
    dte: int,
    option_type: str,  # "call" or "put"
) -> pd.DataFrame:
    """
    Calculate Greeks for each row in an options chain using py_vollib.
    Falls back to simple delta approximation if py_vollib unavailable.
    """
    t = max(dte / 365.0, 1 / 365.0)  # time in years, min 1 day
    r = 0.045  # approximate risk-free rate
    flag = "c" if option_type == "call" else "p"

    deltas, gammas, thetas, vegas = [], [], [], []

    for _, row in chain_df.iterrows():
        strike = row["strike"]
        iv = row.get("impliedVolatility", 0.3)

        if iv <= 0 or iv > 10 or strike <= 0:
            deltas.append(np.nan)
            gammas.append(np.nan)
            thetas.append(np.nan)
            vegas.append(np.nan)
            continue

        if HAS_VOLLIB:
            try:
                d = bs_delta(flag, spot, strike, t, r, iv)
                g = bs_gamma(flag, spot, strike, t, r, iv)
                th = bs_theta(flag, spot, strike, t, r, iv)
                v = bs_vega(flag, spot, strike, t, r, iv)
                deltas.append(round(d, 4))
                gammas.append(round(g, 6))
                thetas.append(round(th, 4))
                vegas.append(round(v, 4))
            except Exception:
                deltas.append(np.nan)
                gammas.append(np.nan)
                thetas.append(np.nan)
                vegas.append(np.nan)
        else:
            # Simple delta approximation
            moneyness = spot / strike
            if option_type == "call":
                d = max(0, min(1, 0.5 + (moneyness - 1) * 2))
            else:
                d = max(-1, min(0, -0.5 + (moneyness - 1) * 2))
            deltas.append(round(d, 4))
            gammas.append(np.nan)
            thetas.append(np.nan)
            vegas.append(np.nan)

    chain_df = chain_df.copy()
    chain_df.loc[:, "calc_delta"] = deltas
    chain_df.loc[:, "calc_gamma"] = gammas
    chain_df.loc[:, "calc_theta"] = thetas
    chain_df.loc[:, "calc_vega"] = vegas

    return chain_df


def classify_vol_regime(vix_level=None, vix_vix3m_ratio=None, rv20=None, rv60=None):
    """
    Simple volatility regime classifier.
    Returns (regime, details_dict).
    Regimes: 'crash', 'high_vol', 'normal', 'low_vol'.
    """
    details = {
        "vix": vix_level, "vix_ratio": vix_vix3m_ratio,
        "rv20": rv20, "rv60": rv60,
    }

    rv_ratio = rv20 / rv60 if rv20 and rv60 and rv60 > 0 else None

    # Crash: VIX > 30 AND backwardation (VIX > VIX3M)
    if vix_level is not None and vix_level > 30:
        if vix_vix3m_ratio is not None and vix_vix3m_ratio > 1.0:
            return "crash", {**details, "rv_ratio": rv_ratio, "reason": "VIX > 30 with backwardation — panic regime"}
        return "high_vol", {**details, "rv_ratio": rv_ratio, "reason": f"VIX at {vix_level:.0f} — elevated fear"}

    # High vol: VIX > 25 OR short-term vol spiking relative to long-term
    if vix_level is not None and vix_level > 25:
        return "high_vol", {**details, "rv_ratio": rv_ratio, "reason": f"VIX at {vix_level:.0f} — elevated vol"}
    if rv_ratio is not None and rv_ratio > 1.5:
        return "high_vol", {**details, "rv_ratio": rv_ratio, "reason": f"RV20/RV60 = {rv_ratio:.2f} — vol accelerating"}

    # Low vol: VIX < 15 AND short-term vol compressed
    if vix_level is not None and vix_level < 15:
        if rv_ratio is None or rv_ratio < 0.9:
            return "low_vol", {**details, "rv_ratio": rv_ratio, "reason": f"VIX at {vix_level:.0f} — premiums thin"}

    return "normal", {**details, "rv_ratio": rv_ratio, "reason": "Normal vol environment"}


# FOMC meeting dates (announcement days) — hardcoded for 2025-2026
FOMC_DATES = [
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-11-05", "2025-12-17",
    # 2026
    "2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
]


def get_next_fomc_date(as_of=None):
    """
    Returns (next_fomc_date, days_until) or (None, None) if beyond known dates.
    """
    if as_of is None:
        as_of = datetime.now()
    for d in FOMC_DATES:
        fomc = datetime.strptime(d, "%Y-%m-%d")
        days = (fomc - as_of).days
        if days >= -1:  # include today and yesterday (in case of late-day check)
            return fomc, days
    return None, None


def calc_vrp_signal(vrp, iv_rank, term_label, regime=None):
    """
    VRP-based signal for whether to sell options.
    Based on Chapter 10 logic:
    - VRP > 2 = edge exists
    - IV Rank > 30% = elevated premium
    - Term structure NOT in backwardation = safe to sell
    """
    if vrp is None:
        return "YELLOW", "yellow", "Cannot calculate VRP"

    reasons = []

    if vrp > 4:
        reasons.append(f"Strong VRP ({vrp:+.1f} pts)")
        vrp_score = 3
    elif vrp > 2:
        reasons.append(f"Moderate VRP ({vrp:+.1f} pts)")
        vrp_score = 2
    elif vrp > 0:
        reasons.append(f"Thin VRP ({vrp:+.1f} pts)")
        vrp_score = 1
    else:
        reasons.append(f"Negative VRP ({vrp:+.1f} pts) — options underpriced")
        vrp_score = 0

    if iv_rank is not None:
        if iv_rank > 50:
            reasons.append(f"High IV Rank ({iv_rank:.0f}%)")
            rank_score = 2
        elif iv_rank > 30:
            reasons.append(f"Moderate IV Rank ({iv_rank:.0f}%)")
            rank_score = 1
        else:
            reasons.append(f"Low IV Rank ({iv_rank:.0f}%)")
            rank_score = 0
    else:
        rank_score = 1

    if term_label == "Backwardation":
        reasons.append("CAUTION: Backwardation — don't catch falling knives")
        term_score = 0
    elif term_label == "Contango":
        reasons.append("Term structure normal (contango)")
        term_score = 2
    else:
        term_score = 1

    total = vrp_score + rank_score + term_score

    # Regime override: crash regime forces RED, high_vol caps at YELLOW
    if regime == "crash":
        reasons.append("REGIME: Crash — halt all new option selling")
        return "RED", "red", " | ".join(reasons)
    if regime == "high_vol" and total >= 5:
        reasons.append("REGIME: High vol — proceed with caution, use wider strikes")
        # Cap at YELLOW unless VRP is very strong
        if vrp is not None and vrp > 6:
            return "GREEN", "green", " | ".join(reasons)
        return "YELLOW", "yellow", " | ".join(reasons)
    if regime == "low_vol":
        reasons.append("REGIME: Low vol — premiums are thin, small edge")

    if total >= 5 and term_label != "Backwardation":
        return "GREEN", "green", " | ".join(reasons)
    elif total >= 3 and term_label != "Backwardation":
        return "YELLOW", "yellow", " | ".join(reasons)
    else:
        return "RED", "red", " | ".join(reasons)


def calc_skew_score(chain_calls, chain_puts, spot, dte):
    """
    Calculate 25-delta put/call IV skew and return a scoring penalty.
    Steep skew = market pricing tail risk into puts = penalize put selling.

    Returns (skew_value, skew_penalty, details_dict).
    skew_penalty: 0 = normal, -1 = elevated, -2 = extreme.
    """
    try:
        if chain_puts is None or chain_puts.empty or chain_calls is None or chain_calls.empty:
            return None, 0, {"error": "no chain data"}
        if "impliedVolatility" not in chain_puts.columns:
            return None, 0, {"error": "no IV data"}

        # Approximate 25-delta strikes: ~5% OTM for 30-day options
        # Scale by sqrt(dte/30) for different tenors
        otm_pct = 0.05 * np.sqrt(max(dte, 1) / 30)
        put_25d_strike = spot * (1 - otm_pct)
        call_25d_strike = spot * (1 + otm_pct)

        # Find nearest strikes
        puts = chain_puts[chain_puts["impliedVolatility"] > 0].copy()
        calls = chain_calls[chain_calls["impliedVolatility"] > 0].copy()
        if puts.empty or calls.empty:
            return None, 0, {"error": "no valid IV data"}

        puts["dist"] = abs(puts["strike"] - put_25d_strike)
        calls["dist"] = abs(calls["strike"] - call_25d_strike)

        put_25d_iv = puts.loc[puts["dist"].idxmin(), "impliedVolatility"] * 100
        call_25d_iv = calls.loc[calls["dist"].idxmin(), "impliedVolatility"] * 100

        # ATM IV
        calls_atm = calls.copy()
        calls_atm["dist_atm"] = abs(calls_atm["strike"] - spot)
        atm_iv = calls_atm.loc[calls_atm["dist_atm"].idxmin(), "impliedVolatility"] * 100

        skew = put_25d_iv - call_25d_iv  # positive = puts more expensive (normal)

        # Penalty for extreme skew
        if skew > 10:
            penalty = -2
        elif skew > 5:
            penalty = -1
        else:
            penalty = 0

        details = {
            "put_25d_iv": put_25d_iv,
            "call_25d_iv": call_25d_iv,
            "atm_iv": atm_iv,
            "skew": skew,
            "put_strike": puts.loc[puts["dist"].idxmin(), "strike"],
            "call_strike": calls.loc[calls["dist"].idxmin(), "strike"],
        }
        return skew, penalty, details
    except Exception:
        return None, 0, {"error": "skew calculation failed"}


def score_trade(row, current_iv, rv_forecast, iv_rank, term_label, skew_penalty=0):
    """
    Score a specific option trade 1-10.
    Higher = more edge.
    skew_penalty: from calc_skew_score(), penalizes put selling when skew is steep.
    """
    score = 5  # baseline

    # IV vs realized vol at this strike
    strike_iv = row.get("impliedVolatility", 0) * 100
    if strike_iv > 0 and rv_forecast > 0:
        strike_vrp = strike_iv - rv_forecast
        if strike_vrp > 6:
            score += 3
        elif strike_vrp > 3:
            score += 2
        elif strike_vrp > 1:
            score += 1
        elif strike_vrp < 0:
            score -= 2

    # IV rank bonus
    if iv_rank is not None:
        if iv_rank > 60:
            score += 1
        elif iv_rank < 20:
            score -= 1

    # Term structure
    if term_label == "Backwardation":
        score -= 2
    elif term_label == "Contango":
        score += 1

    # Liquidity (volume + OI)
    vol = row.get("volume", 0)
    oi = row.get("openInterest", 0)
    if pd.notna(vol) and vol > 100:
        score += 0.5
    if pd.notna(oi) and oi > 500:
        score += 0.5

    # Skew penalty (steep skew = market pricing tail risk)
    score += skew_penalty

    return max(1, min(10, round(score)))


# ========================================
# RISK PROTECTION LAYER
# ========================================

def calc_prob_of_loss(spot, strike, iv, dte, option_type, premium, hist=None):
    """
    Probability that a short option trade loses money at expiration.

    If `hist` is provided with 100+ days of data, uses Student's t-distribution
    fitted to actual historical returns (captures fat tails).
    Otherwise falls back to log-normal (GBM assumption).

    For short calls: loss if stock > strike + premium
    For short puts: loss if stock < strike - premium
    """
    if iv <= 0 or dte <= 0 or spot <= 0:
        return None, None, None

    t = dte / 365.0
    sigma = iv / 100.0
    r = 0.045

    # Try fitting Student's t to historical returns for fat-tail-aware probabilities
    use_t = False
    if hist is not None and len(hist) >= 100:
        try:
            log_returns = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
            # Fit t-distribution to daily log returns
            df_t, loc_t, scale_t = t_dist.fit(log_returns)
            if df_t > 2 and df_t < 100:  # sensible fit (2 < df < 100)
                # Scale to the holding period
                loc_period = loc_t * dte
                scale_period = scale_t * np.sqrt(dte)
                use_t = True
        except Exception:
            pass

    if use_t:
        # Student's t probabilities (fat tails)
        if option_type == "call":
            breakeven = strike + premium
            z = (np.log(breakeven / spot) - loc_period) / scale_period
            prob_loss = 1 - t_dist.cdf(z, df_t)
            prob_max_loss = 0.0
            z_assign = (np.log(strike / spot) - loc_period) / scale_period
            prob_assignment = 1 - t_dist.cdf(z_assign, df_t)
        else:
            breakeven = strike - premium
            z = (np.log(breakeven / spot) - loc_period) / scale_period
            prob_loss = t_dist.cdf(z, df_t)
            z_cat = (np.log(strike * 0.5 / spot) - loc_period) / scale_period
            prob_max_loss = t_dist.cdf(z_cat, df_t)
            z_assign = (np.log(strike / spot) - loc_period) / scale_period
            prob_assignment = t_dist.cdf(z_assign, df_t)
    else:
        # Fallback: log-normal (GBM)
        mu = (r - 0.5 * sigma**2) * t
        vol_t = sigma * np.sqrt(t)

        if option_type == "call":
            breakeven = strike + premium
            d = (np.log(breakeven / spot) - mu) / vol_t
            prob_loss = 1 - norm.cdf(d)
            prob_max_loss = 0.0
            d_assign = (np.log(strike / spot) - mu) / vol_t
            prob_assignment = 1 - norm.cdf(d_assign)
        else:
            breakeven = strike - premium
            d = (np.log(breakeven / spot) - mu) / vol_t
            prob_loss = norm.cdf(d)
            d_cat = (np.log(strike * 0.5 / spot) - mu) / vol_t
            prob_max_loss = norm.cdf(d_cat)
            d_assign = (np.log(strike / spot) - mu) / vol_t
            prob_assignment = norm.cdf(d_assign)

    return prob_loss, prob_assignment, prob_max_loss


def calc_kelly_size(prob_win, avg_win, avg_loss, fraction=0.25,
                    skewness=None, max_position_pct=0.05):
    """
    Fractional Kelly criterion with skew adjustment for position sizing.
    Chapter 17: f* = (bp - q) / b
    where b = avg_win/avg_loss, p = prob_win, q = 1-p

    Skew adjustment (Module 7A):
      Short premium has negative skewness (rare big losses).
      Standard Kelly ignores this and oversizes.
      Adjusted: kelly_adj = kelly * (1 / (1 + |skew|))
      Then capped at quarter-Kelly and 5% absolute.

    Args:
        prob_win: Probability of winning (0-1)
        avg_win: Average win amount
        avg_loss: Average loss amount
        fraction: Kelly fraction (default 0.25 = quarter-Kelly)
        skewness: Empirical P&L skewness (None = no adjustment)
        max_position_pct: Absolute cap per position (default 5%)

    Returns:
        float: fraction of capital to risk
        dict: sizing details (if skewness provided)
    """
    if avg_loss == 0 or prob_win <= 0 or prob_win >= 1:
        return 0.0

    b = abs(avg_win / avg_loss)
    p = prob_win
    q = 1 - p

    full_kelly = (b * p - q) / b
    if full_kelly <= 0:
        return 0.0  # no edge, don't bet

    quarter_kelly = full_kelly * fraction

    # Skew adjustment: penalize for negative skewness (fat left tail)
    if skewness is not None and skewness != 0:
        skew_factor = 1.0 / (1.0 + abs(skewness))
        skew_adjusted = full_kelly * skew_factor
        # Cap at quarter-Kelly
        adjusted = min(skew_adjusted, quarter_kelly)
    else:
        skew_factor = 1.0
        adjusted = quarter_kelly

    # Absolute cap: max_position_pct of portfolio per position
    final = min(adjusted, max_position_pct)

    return final


def calc_edge_confidence(vrp, iv_rank, term_label, prob_loss, volume, open_interest, dte):
    """
    Structural edge confidence score (0-100%).
    ARCTIC-inspired checklist: does the trade have a real, identifiable edge?

    Checks:
    1. Anomaly: Is VRP meaningfully positive? (the core edge)
    2. Rationale: IV rank confirms elevated premium?
    3. Counterparty: Good liquidity = rational counterparties?
    4. Threats: Term structure not in backwardation?
    5. Incentives: Time decay working for us (reasonable DTE)?
    6. Capacity: Probability of loss acceptable?
    """
    checks = {}

    # 1. VRP edge exists
    if vrp is not None and vrp > 4:
        checks["VRP Edge"] = (30, "Strong VRP — core edge present")
    elif vrp is not None and vrp > 2:
        checks["VRP Edge"] = (20, "Moderate VRP — edge exists")
    elif vrp is not None and vrp > 0:
        checks["VRP Edge"] = (10, "Thin VRP — marginal edge")
    else:
        checks["VRP Edge"] = (0, "No VRP edge — options fairly priced or cheap")

    # 2. IV rank confirms premium
    if iv_rank is not None and iv_rank > 50:
        checks["IV Rank"] = (20, f"High IV rank ({iv_rank:.0f}%) — selling at good levels")
    elif iv_rank is not None and iv_rank > 30:
        checks["IV Rank"] = (12, f"Moderate IV rank ({iv_rank:.0f}%)")
    else:
        checks["IV Rank"] = (5, f"Low IV rank — premium not elevated")

    # 3. Liquidity
    vol = volume if pd.notna(volume) else 0
    oi = open_interest if pd.notna(open_interest) else 0
    if vol > 100 and oi > 500:
        checks["Liquidity"] = (15, f"Good liquidity (vol={vol}, OI={oi})")
    elif vol > 20 or oi > 100:
        checks["Liquidity"] = (8, f"Thin liquidity — wider spreads likely")
    else:
        checks["Liquidity"] = (2, f"Poor liquidity — execution risk")

    # 4. Term structure
    if term_label == "Contango":
        checks["Term Structure"] = (15, "Normal contango — safe to sell")
    elif term_label == "Flat":
        checks["Term Structure"] = (8, "Flat term structure — neutral")
    else:
        checks["Term Structure"] = (0, "BACKWARDATION — danger, don't sell")

    # 5. DTE sweet spot (30-60 days is optimal for theta decay)
    if 21 <= dte <= 60:
        checks["DTE"] = (10, f"{dte} DTE — optimal theta window")
    elif 7 <= dte <= 90:
        checks["DTE"] = (6, f"{dte} DTE — acceptable")
    else:
        checks["DTE"] = (2, f"{dte} DTE — suboptimal")

    # 6. Probability
    if prob_loss is not None:
        if prob_loss < 0.15:
            checks["Prob of Loss"] = (10, f"{prob_loss*100:.1f}% loss probability — low risk")
        elif prob_loss < 0.30:
            checks["Prob of Loss"] = (6, f"{prob_loss*100:.1f}% loss probability — moderate")
        else:
            checks["Prob of Loss"] = (2, f"{prob_loss*100:.1f}% loss probability — elevated")
    else:
        checks["Prob of Loss"] = (5, "Cannot estimate probability")

    total = sum(v[0] for v in checks.values())
    return total, checks


def run_monte_carlo(spot, iv, dte, strike, premium, option_type, n_sims=10000):
    """
    Monte Carlo simulation of trade outcomes for a short option position.
    Returns distribution of P&L outcomes at expiration.
    """
    if iv <= 0 or dte <= 0:
        return None

    t = dte / 365.0
    sigma = iv / 100.0
    r = 0.045
    dt = t  # single step to expiration

    # Simulate terminal prices using GBM
    z = np.random.standard_normal(n_sims)
    s_t = spot * np.exp((r - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z)

    # Calculate P&L for short option
    if option_type == "call":
        intrinsic = np.maximum(s_t - strike, 0)
    else:
        intrinsic = np.maximum(strike - s_t, 0)

    pnl = (premium - intrinsic) * 100  # per contract

    results = {
        "pnl": pnl,
        "mean_pnl": float(np.mean(pnl)),
        "median_pnl": float(np.median(pnl)),
        "std_pnl": float(np.std(pnl)),
        "prob_profit": float(np.mean(pnl > 0)),
        "pct_5": float(np.percentile(pnl, 5)),
        "pct_25": float(np.percentile(pnl, 25)),
        "pct_75": float(np.percentile(pnl, 75)),
        "pct_95": float(np.percentile(pnl, 95)),
        "max_loss": float(np.min(pnl)),
        "max_gain": float(np.max(pnl)),
        "expected_value": float(np.mean(pnl)),
        "skew": float(pd.Series(pnl).skew()),
        "kurtosis": float(pd.Series(pnl).kurtosis()),
    }
    return results


def stress_test_trade(spot, strike, premium, iv, dte, option_type):
    """
    Stress test: P&L matrix across stock moves and IV changes.
    Returns a DataFrame showing P&L under different scenarios.
    """
    stock_moves = [-0.20, -0.15, -0.10, -0.05, -0.02, 0, 0.02, 0.05, 0.10, 0.15]
    iv_changes = [-10, -5, 0, 5, 10, 20]  # vol point changes

    t = max(dte / 365.0, 1/365)
    r = 0.045

    rows = []
    for move in stock_moves:
        new_spot = spot * (1 + move)
        row = {"Stock Move": f"{move*100:+.0f}%"}
        for iv_chg in iv_changes:
            new_iv = max(0.01, (iv + iv_chg) / 100.0)
            # Use BSM to price the option at new conditions with half the time elapsed
            t_remain = max(t * 0.5, 1/365)
            flag = "c" if option_type == "call" else "p"

            if HAS_VOLLIB:
                try:
                    new_price = bs_price(flag, new_spot, strike, t_remain, r, new_iv)
                except Exception:
                    # Fallback to intrinsic
                    if option_type == "call":
                        new_price = max(0, new_spot - strike)
                    else:
                        new_price = max(0, strike - new_spot)
            else:
                if option_type == "call":
                    new_price = max(0, new_spot - strike)
                else:
                    new_price = max(0, strike - new_spot)

            pnl = (premium - new_price) * 100
            row[f"IV {iv_chg:+d}"] = round(pnl)
        rows.append(row)

    return pd.DataFrame(rows)


# ========================================
# EXIT SIGNAL ENGINE
# ========================================

def generate_exit_signals(trade, spot, current_option_price, current_iv, rv_20, term_label, current_delta=None):
    """
    Generate exit signals for an open position.
    Returns list of (severity, signal_name, message, action).
    severity: "MUST_SELL", "WARNING", "INFO"

    Based on Chapter 18 position adjustment rules:
    - Take profit at 50%+ of max
    - Roll at <7 DTE with extrinsic value
    - Close if VRP flips negative
    - Close if term structure goes backwardation
    - Close if delta blows past thresholds
    - Close if loss exceeds 10x expected weekly profit
    """
    signals = []
    premium = trade["premium_received"]
    strike = trade["strike"]
    option_type = trade["option_type"]
    contracts = trade["contracts"]

    try:
        exp_date = datetime.strptime(trade["expiration"], "%Y-%m-%d")
        dte = max((exp_date - datetime.now()).days, 0)
    except Exception:
        dte = 0

    # Current P&L
    if current_option_price is not None:
        pnl_per_share = premium - current_option_price
        pnl_total = pnl_per_share * 100 * contracts
        pct_of_max = (pnl_per_share / premium) * 100 if premium > 0 else 0
    else:
        pnl_per_share = None
        pnl_total = None
        pct_of_max = None

    # --- 1. TAKE PROFIT (>50% of max) ---
    if pct_of_max is not None and pct_of_max >= 75:
        signals.append((
            "MUST_SELL", "Take Profit",
            f"Captured {pct_of_max:.0f}% of max profit (${pnl_total:+,.0f}). Close now — remaining edge is thin vs gamma risk.",
            "BUY TO CLOSE"
        ))
    elif pct_of_max is not None and pct_of_max >= 50:
        signals.append((
            "WARNING", "Take Profit",
            f"Captured {pct_of_max:.0f}% of max profit. Consider closing — diminishing returns from here.",
            "BUY TO CLOSE"
        ))

    # --- 2. DTE WARNING ---
    if dte <= 3:
        signals.append((
            "MUST_SELL", "Expiration Imminent",
            f"Only {dte} days to expiration. Gamma risk is extreme. Close unless you want assignment.",
            "BUY TO CLOSE or let expire"
        ))
    elif dte <= 7:
        if pct_of_max is not None and pct_of_max < 80:
            signals.append((
                "WARNING", "Roll Signal",
                f"{dte} DTE with only {pct_of_max:.0f}% profit captured. Roll to next month to collect more theta.",
                "ROLL to next expiration"
            ))
        else:
            signals.append((
                "INFO", "Near Expiry",
                f"{dte} DTE — monitor closely. Let expire if max profit nearly captured.",
                "HOLD or let expire"
            ))

    # --- 3. DELTA BLOWOUT ---
    if current_delta is not None:
        if option_type == "call" and abs(current_delta) > 0.70:
            signals.append((
                "MUST_SELL", "Delta Blowout",
                f"Call delta at {current_delta:.2f} — deep ITM, high assignment risk. Stock has rallied past your strike.",
                "BUY TO CLOSE — you're capping gains on a winner"
            ))
        elif option_type == "call" and abs(current_delta) > 0.50:
            signals.append((
                "WARNING", "Delta Warning",
                f"Call delta at {current_delta:.2f} — approaching ITM. Assignment probability rising.",
                "Consider rolling up and out"
            ))
        elif option_type == "put" and abs(current_delta) > 0.70:
            signals.append((
                "MUST_SELL", "Delta Blowout",
                f"Put delta at {current_delta:.2f} — deep ITM. Stock has dropped significantly. You will be assigned.",
                "BUY TO CLOSE — cut losses"
            ))
        elif option_type == "put" and abs(current_delta) > 0.50:
            signals.append((
                "WARNING", "Delta Warning",
                f"Put delta at {current_delta:.2f} — approaching ITM. Assignment risk increasing.",
                "Consider rolling down and out"
            ))

    # --- 4. VRP FLIP ---
    if current_iv is not None and rv_20 is not None:
        live_vrp = current_iv - rv_20
        if live_vrp < -2:
            signals.append((
                "MUST_SELL", "VRP Flipped Negative",
                f"VRP is now {live_vrp:+.1f} pts — implied vol is BELOW realized. You're selling cheap insurance. Close immediately.",
                "BUY TO CLOSE"
            ))
        elif live_vrp < 0:
            signals.append((
                "WARNING", "VRP Eroding",
                f"VRP is now {live_vrp:+.1f} pts — your edge has evaporated.",
                "Consider closing"
            ))

    # --- 5. TERM STRUCTURE BACKWARDATION ---
    if term_label == "Backwardation":
        signals.append((
            "MUST_SELL", "Backwardation",
            "Term structure has flipped to backwardation — short-term fear is elevated. Close short options now.",
            "BUY TO CLOSE"
        ))

    # --- 6. LOSS THRESHOLD (> 2x premium received) ---
    if pnl_per_share is not None and pnl_per_share < -premium * 2:
        signals.append((
            "MUST_SELL", "Loss Threshold",
            f"Loss is ${abs(pnl_total):,.0f} — exceeds 2x premium collected. Cut the loss.",
            "BUY TO CLOSE"
        ))
    elif pnl_per_share is not None and pnl_per_share < -premium:
        signals.append((
            "WARNING", "Loss Growing",
            f"Loss is ${abs(pnl_total):,.0f} — exceeds premium collected. Watch closely.",
            "Monitor or close"
        ))

    # --- 7. GAMMA RISK (near strike + near expiry) ---
    if dte <= 5 and current_delta is not None:
        if 0.40 <= abs(current_delta) <= 0.60:
            signals.append((
                "MUST_SELL", "Gamma/Pin Risk",
                f"Stock is near your strike with {dte} DTE. Gamma is extreme — small moves create huge delta swings. Close.",
                "BUY TO CLOSE"
            ))

    # No signals = position is fine
    if not signals:
        signals.append((
            "INFO", "Position OK",
            f"No exit triggers. {dte} DTE, {pct_of_max:.0f}% profit captured." if pct_of_max is not None else f"No exit triggers. {dte} DTE.",
            "HOLD"
        ))

    return signals, {
        "dte": dte,
        "pnl_per_share": pnl_per_share,
        "pnl_total": pnl_total,
        "pct_of_max": pct_of_max,
        "current_delta": current_delta,
    }


def get_action_playbook(trade, spot, strike, dte, option_type, pct_of_max):
    """
    Decision matrix: what to do in every scenario.
    Returns a list of (scenario, action, reasoning).
    """
    playbook = []

    # Scenario matrix
    if option_type == "call":
        playbook.append((
            "Stock rallies 5%+",
            "Buy to close or roll up",
            f"Your call goes ITM. If you want to keep shares, buy back the call. "
            f"If ok with selling, let it ride. Roll up to higher strike if you want more upside."
        ))
        playbook.append((
            "Stock drops 5%+",
            "Hold — this is ideal",
            f"Your call loses value = profit. Let theta work. Consider selling another call if stock stabilizes."
        ))
        playbook.append((
            "Stock flat, near expiry",
            "Let expire worthless",
            f"Best case. Premium is yours. Prepare to sell another call next month."
        ))
        playbook.append((
            "IV spikes (VIX jumps)",
            "Hold unless term structure inverts",
            f"Higher IV makes your call worth more (bad for you), but if VRP stays positive the edge is still there. "
            f"Only close if backwardation develops."
        ))
        playbook.append((
            "Earnings approaching",
            "Close before earnings",
            f"Earnings moves are often justified by IV — you don't have edge here. Close 2-3 days before."
        ))
    else:
        playbook.append((
            "Stock drops 5%+",
            "Roll down or close if > 2x premium loss",
            f"Your put goes ITM. If you want the shares at this level, hold. Otherwise cut loss and roll."
        ))
        playbook.append((
            "Stock rallies 5%+",
            "Hold — this is ideal",
            f"Put loses value = profit. If >50% captured, consider closing early."
        ))
        playbook.append((
            "Stock crashes 15%+",
            "Close immediately",
            f"Tail event. The math doesn't matter here — preserve capital. Close and reassess."
        ))
        playbook.append((
            "IV spikes + stock drops",
            "CLOSE — double whammy",
            f"Worst case for short puts. IV up = option more expensive + stock down = ITM. Exit."
        ))
        playbook.append((
            "Earnings approaching",
            "Close before earnings",
            f"Same rule as calls — earnings IV is usually fairly priced, no edge."
        ))

    # Universal scenarios
    playbook.append((
        f"Captured >50% profit with >{dte//2}+ days left",
        "Close early",
        f"You've captured most of the edge. Remaining theta doesn't justify the gamma risk. Redeploy capital."
    ))
    playbook.append((
        "VRP turns negative",
        "Close immediately",
        f"You're selling underpriced insurance — the structural edge is gone."
    ))

    return playbook


# ========================================
# HISTORICAL BACKTEST ENGINE
# ========================================

def backtest_vrp_strategy(hist: pd.DataFrame, window: int = 20, holding_period: int = 20,
                          iv_rv_ratio: float = 1.2,
                          commission_per_contract: float = 0.65,
                          slippage_per_contract: float = 0.025):
    """
    Backtest: what would have happened historically if you sold options
    whenever VRP conditions were met?

    De-biased approach: IV is estimated as RV * iv_rv_ratio (default 1.2)
    because historically IV ≈ RV * 1.15-1.25 for equities.
    This removes the circular bias of using RV as both IV and RV.

    Includes transaction costs: commission + slippage per contract.

    Returns a DataFrame of historical 'trades' with outcomes.
    """
    log_ret = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()

    # Rolling realized vol (backward-looking)
    rv_backward = log_ret.rolling(window).std() * np.sqrt(252) * 100

    # De-biased IV estimate: IV typically runs ~20% above backward RV
    iv_estimate = rv_backward * iv_rv_ratio

    # Forward-looking realized vol (what actually happened)
    rv_forward = log_ret.rolling(window).std().shift(-holding_period) * np.sqrt(252) * 100

    # Combine
    df = pd.DataFrame({
        "date": hist.index[1:],
        "close": hist["Close"].iloc[1:].values,
        "iv_proxy": iv_estimate.values,
        "rv_backward": rv_backward.values,
        "rv_actual": rv_forward.values,
    }).dropna()

    if df.empty:
        return None

    df["vrp_proxy"] = df["iv_proxy"] - df["rv_actual"]

    # Forward stock return over holding period
    df["fwd_return"] = hist["Close"].pct_change(holding_period).shift(-holding_period).iloc[1:len(df)+1].values

    df = df.dropna()

    # Classify each day by signal
    def classify(row):
        if row["vrp_proxy"] > 2 and row["iv_proxy"] > df["iv_proxy"].quantile(0.30):
            return "GREEN"
        elif row["vrp_proxy"] > 0:
            return "YELLOW"
        else:
            return "RED"

    df["signal"] = df.apply(classify, axis=1)

    # Premium simulation using de-biased IV estimate
    df["expected_move_pct"] = df["iv_proxy"] / 100 * np.sqrt(holding_period / 252)
    df["actual_move_pct"] = df["fwd_return"].abs()
    df["seller_wins"] = df["actual_move_pct"] < df["expected_move_pct"]

    # Approximate premium captured (% of stock price)
    df["premium_pct"] = df["iv_proxy"] / 100 * np.sqrt(holding_period / 252) * 100
    df["pnl_pct"] = np.where(
        df["seller_wins"],
        df["premium_pct"],
        df["premium_pct"] - (df["actual_move_pct"] * 100 - df["premium_pct"])
    )

    # Transaction costs as % of stock price (open + close = 2 legs)
    total_cost = (commission_per_contract + slippage_per_contract) * 2
    df["cost_pct"] = total_cost / df["close"] * 100  # as percentage of stock price
    df["pnl_pct"] = df["pnl_pct"] - df["cost_pct"]

    return df


def summarize_backtest(bt_df):
    """Summarize backtest results by signal type."""
    if bt_df is None or bt_df.empty:
        return None

    results = {}
    for signal in ["GREEN", "YELLOW", "RED"]:
        subset = bt_df[bt_df["signal"] == signal]
        if subset.empty:
            continue
        results[signal] = {
            "count": len(subset),
            "win_rate": subset["seller_wins"].mean() * 100,
            "avg_vrp": subset["vrp_proxy"].mean(),
            "avg_pnl_pct": subset["pnl_pct"].mean(),
            "worst_loss_pct": subset["pnl_pct"].min(),
            "best_win_pct": subset["pnl_pct"].max(),
            "avg_actual_move": subset["actual_move_pct"].mean() * 100,
            "avg_expected_move": subset["expected_move_pct"].mean() * 100,
            "avg_cost_pct": subset["cost_pct"].mean() if "cost_pct" in subset.columns else 0,
        }
    return results


def explain_signal_plain_english(signal, vrp, iv_rank, term_label, current_iv, rv_20, current_price):
    """
    Generate a plain-English explanation of why the signal is what it is.
    Written for someone who doesn't know options jargon.
    """
    parts = []

    if signal == "RED":
        parts.append("**Bottom line: Don't sell options right now.** Here's why:\n")
    elif signal == "YELLOW":
        parts.append("**Bottom line: Selling options is marginal right now.** Here's why:\n")
    else:
        parts.append("**Bottom line: Good conditions to sell options.** Here's why:\n")

    # VRP explanation
    if vrp is not None:
        if vrp < 0:
            parts.append(
                f"**The market is pricing options too cheap.** "
                f"Implied volatility ({current_iv:.1f}%) is *below* what the stock has actually been doing ({rv_20:.1f}%). "
                f"That means the 'insurance premium' you'd collect for selling options ({abs(vrp):.1f} points less than fair value) "
                f"isn't enough to cover the actual risk. "
                f"It's like selling car insurance for less than the expected claims — you'll lose money over time."
            )
        elif vrp < 2:
            parts.append(
                f"**The edge is razor thin.** "
                f"Options are priced only {vrp:.1f} points above what the stock actually moves. "
                f"After transaction costs and the risk of a bad outcome, there's barely any profit margin."
            )
        else:
            parts.append(
                f"**Options are meaningfully overpriced.** "
                f"The market expects {current_iv:.1f}% volatility but the stock has only been moving at {rv_20:.1f}% — "
                f"a {vrp:.1f} point gap. That gap is your edge. You're selling insurance for more than the expected claims."
            )

    # IV Rank explanation
    if iv_rank is not None:
        if iv_rank < 20:
            parts.append(
                f"\n**Premiums are near their lowest levels of the year** (IV Rank: {iv_rank:.0f}%). "
                f"Even if there's a small edge, the dollar amount you'd collect is low. "
                f"It's like selling umbrellas on a sunny day — cheap and not worth the effort."
            )
        elif iv_rank > 50:
            parts.append(
                f"\n**Premiums are elevated** (IV Rank: {iv_rank:.0f}%). "
                f"Options are priced higher than usual, which means you'd collect more premium. "
                f"Higher premiums = bigger cushion against losses."
            )
        else:
            parts.append(
                f"\n**Premiums are in the middle of their range** (IV Rank: {iv_rank:.0f}%). "
                f"Not cheap, not rich. The dollar amounts are moderate."
            )

    # Term structure
    if term_label == "Backwardation":
        parts.append(
            f"\n**WARNING: The market is in panic mode.** "
            f"Short-term options cost MORE than long-term options (backwardation). "
            f"This happens when traders are scrambling to buy protection *right now*. "
            f"Selling into this is called 'catching a falling knife' — "
            f"the stock could drop much further before things calm down."
        )
    elif term_label == "Contango":
        parts.append(
            f"\n**The market is calm and orderly** (term structure: contango). "
            f"Long-term options cost more than short-term, which is normal. "
            f"This is the safest environment for selling options."
        )

    # Expected move context
    if current_iv and current_price:
        daily_move = current_price * (current_iv / 100) / 16
        parts.append(
            f"\n**In dollar terms:** The market expects {current_price:.0f} to move about "
            f"${daily_move:.2f}/day (${daily_move * np.sqrt(5):.2f}/week). "
            f"If you sell a call, you're betting the stock won't rally beyond your strike. "
            f"If you sell a put, you're betting it won't crash below your strike."
        )

    return "\n".join(parts)


# ========================================
# ADVANCED ANALYTICS (closing the gap)
# ========================================

def calc_garch_forecast(hist: pd.DataFrame, horizon: int = 20):
    """
    GJR-GARCH(1,1,1) volatility forecast.
    Models vol clustering, mean reversion, AND the leverage effect
    (negative returns cause higher vol than positive returns of same magnitude).
    Much better than symmetric GARCH(1,1) for equity options.

    Returns (forecast_vol_annualized, model_info_dict) or (None, None) on failure.
    """
    try:
        from arch import arch_model
    except ImportError:
        return None, {"error": "arch library not installed"}

    log_ret = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
    if len(log_ret) < 100:
        return None, {"error": "Need 100+ days of data for GARCH"}

    # Scale to percentage for numerical stability
    returns_pct = log_ret * 100

    try:
        # GJR-GARCH: o=1 adds asymmetric (leverage) term
        # gamma[1] captures how much MORE vol increases after negative returns
        model = arch_model(returns_pct, vol="Garch", p=1, o=1, q=1, mean="Constant", rescale=False)
        result = model.fit(disp="off", show_warning=False)

        # Multi-step forecast
        forecast = result.forecast(horizon=horizon)
        avg_var = forecast.variance.iloc[-1].mean()
        annual_vol = np.sqrt(avg_var * 252)

        # Extract model parameters for transparency
        params = result.params
        alpha = float(params.get("alpha[1]", 0))
        beta = float(params.get("beta[1]", 0))
        gamma = float(params.get("gamma[1]", 0))
        omega = float(params.get("omega", 0))
        # GJR persistence = alpha + gamma/2 + beta
        persistence = alpha + gamma / 2 + beta
        denom = 1 - persistence
        info = {
            "omega": omega,
            "alpha": alpha,
            "beta": beta,
            "gamma": gamma,  # leverage coefficient: >0 means bad news increases vol more
            "persistence": persistence,
            "leverage_ratio": (alpha + gamma) / alpha if alpha > 0 else None,  # how much worse downside vol is
            "long_run_vol": float(np.sqrt(omega / denom * 252)) if denom > 0 else None,
            "current_cond_vol": float(np.sqrt(result.conditional_volatility.iloc[-1]**2 * 252 / 100**2) * 100)
            if len(result.conditional_volatility) > 0 else None,
        }
        return float(annual_vol), info
    except Exception as e:
        return None, {"error": str(e)}


def calc_empirical_probabilities(hist: pd.DataFrame, move_pct: float, holding_days: int = 20):
    """
    Use the stock's ACTUAL historical return distribution instead of log-normal.
    Captures fat tails that log-normal misses.

    Returns dict with empirical probabilities of various moves.
    """
    log_ret = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
    if len(log_ret) < 60:
        return None

    # Calculate rolling N-day returns
    period_ret = hist["Close"].pct_change(holding_days).dropna()
    if len(period_ret) < 30:
        return None

    results = {
        "n_observations": len(period_ret),
        "mean_return": float(period_ret.mean() * 100),
        "std_return": float(period_ret.std() * 100),
        "skew": float(period_ret.skew()),
        "kurtosis": float(period_ret.kurtosis()),  # excess kurtosis; 0 = normal
        # Empirical tail probabilities
        "prob_down_5pct": float((period_ret < -0.05).mean()),
        "prob_down_10pct": float((period_ret < -0.10).mean()),
        "prob_down_15pct": float((period_ret < -0.15).mean()),
        "prob_down_20pct": float((period_ret < -0.20).mean()),
        "prob_up_5pct": float((period_ret > 0.05).mean()),
        "prob_up_10pct": float((period_ret > 0.10).mean()),
        # Custom threshold
        "prob_move_exceeds": float((period_ret.abs() > abs(move_pct)).mean()),
        # Percentiles
        "pct_1": float(period_ret.quantile(0.01) * 100),
        "pct_5": float(period_ret.quantile(0.05) * 100),
        "pct_10": float(period_ret.quantile(0.10) * 100),
        "pct_90": float(period_ret.quantile(0.90) * 100),
        "pct_95": float(period_ret.quantile(0.95) * 100),
        "pct_99": float(period_ret.quantile(0.99) * 100),
    }

    # Compare to normal distribution at same vol
    normal_5pct = float(norm.cdf(-0.05 / period_ret.std()))
    results["normal_prob_down_5pct"] = normal_5pct
    results["tail_ratio_5pct"] = (
        results["prob_down_5pct"] / normal_5pct if normal_5pct > 0 else 1.0
    )

    return results


def build_vol_surface(chain_calls, chain_puts, spot, dte):
    """
    Build an IV smile/skew curve from the current option chain.
    Shows how IV varies across strikes — reveals skew premium in OTM puts.
    """
    rows = []
    for _, row in chain_calls.iterrows():
        if row.get("impliedVolatility", 0) > 0:
            moneyness = row["strike"] / spot
            rows.append({
                "strike": row["strike"],
                "moneyness": moneyness,
                "iv": row["impliedVolatility"] * 100,
                "type": "call",
                "volume": row.get("volume", 0),
                "oi": row.get("openInterest", 0),
            })

    for _, row in chain_puts.iterrows():
        if row.get("impliedVolatility", 0) > 0:
            moneyness = row["strike"] / spot
            rows.append({
                "strike": row["strike"],
                "moneyness": moneyness,
                "iv": row["impliedVolatility"] * 100,
                "type": "put",
                "volume": row.get("volume", 0),
                "oi": row.get("openInterest", 0),
            })

    if not rows:
        return None

    df = pd.DataFrame(rows)

    # Find ATM IV (moneyness closest to 1.0)
    atm_iv = df.loc[(df["moneyness"] - 1.0).abs().idxmin(), "iv"]

    # Skew metrics
    otm_puts = df[(df["type"] == "put") & (df["moneyness"] < 0.95)]
    otm_calls = df[(df["type"] == "call") & (df["moneyness"] > 1.05)]

    put_skew = otm_puts["iv"].mean() - atm_iv if not otm_puts.empty else 0
    call_skew = otm_calls["iv"].mean() - atm_iv if not otm_calls.empty else 0

    return {
        "data": df,
        "atm_iv": atm_iv,
        "put_skew": put_skew,  # positive = puts cost more than ATM (normal)
        "call_skew": call_skew,  # usually negative or near zero
        "skew_ratio": (atm_iv + put_skew) / atm_iv if atm_iv > 0 else 1.0,
    }


def calc_portfolio_correlation(tickers: list, period: str = "1y"):
    """
    Calculate return correlations between holdings.
    Shows how exposed you are to a simultaneous drawdown.
    """
    import yf_proxy

    if len(tickers) < 2:
        return None

    prices = pd.DataFrame()
    for t in tickers:
        try:
            hist = yf_proxy.get_stock_history(t, period=period)
            if not hist.empty:
                prices[t] = hist["Close"]
        except Exception:
            continue

    if prices.shape[1] < 2:
        return None

    # Also fetch SPY for beta calculation
    try:
        spy_hist = yf_proxy.get_stock_history("SPY", period=period)
        if not spy_hist.empty:
            prices["SPY_beta_ref"] = spy_hist["Close"]
    except Exception:
        pass

    returns = prices.pct_change().dropna()
    corr_matrix = returns[[t for t in tickers if t in returns.columns]].corr()

    # Average pairwise correlation
    actual_tickers = [t for t in tickers if t in corr_matrix.columns]
    n = len(actual_tickers)
    mask = np.triu(np.ones((n, n), dtype=bool), k=1)
    avg_corr = corr_matrix.values[mask].mean() if mask.sum() > 0 else 0

    vols = returns[[t for t in tickers if t in returns.columns]].std() * np.sqrt(252)

    # Beta calculation: cov(ticker, SPY) / var(SPY)
    betas = {}
    portfolio_beta = None
    if "SPY_beta_ref" in returns.columns:
        spy_ret = returns["SPY_beta_ref"]
        spy_var = spy_ret.var()
        if spy_var > 0:
            for t in actual_tickers:
                if t in returns.columns and t != "SPY_beta_ref":
                    cov = returns[t].cov(spy_ret)
                    betas[t] = float(cov / spy_var)
            if betas:
                portfolio_beta = float(np.mean(list(betas.values())))  # equal-weighted

    return {
        "correlation_matrix": corr_matrix,
        "avg_pairwise_corr": float(avg_corr),
        "individual_vols": {t: float(v * 100) for t, v in vols.items()},
        "diversification_ratio": float(
            vols.mean() / (returns[[t for t in tickers if t in returns.columns]].mean(axis=1).std() * np.sqrt(252))
        ) if returns[[t for t in tickers if t in returns.columns]].mean(axis=1).std() > 0 else 1.0,
        "betas": betas,
        "portfolio_beta": portfolio_beta,
    }


def calc_yang_zhang_vol(hist: pd.DataFrame, window: int = 20) -> float:
    """
    Yang-Zhang volatility estimator.
    Most efficient estimator — combines overnight (open-close) and intraday (high-low) components.
    Chapter 3 of Sinclair: the 'best' simple estimator.
    """
    if len(hist) < window + 1:
        return 0.0

    recent = hist.tail(window + 1)

    # Overnight returns: log(Open_t / Close_{t-1})
    overnight = np.log(recent["Open"].iloc[1:].values / recent["Close"].iloc[:-1].values)

    # Close-to-open: log(Close_t / Open_t)
    close_open = np.log(recent["Close"].iloc[1:].values / recent["Open"].iloc[1:].values)

    # Rogers-Satchell component
    hi = np.log(recent["High"].iloc[1:].values / recent["Open"].iloc[1:].values)
    lo = np.log(recent["Low"].iloc[1:].values / recent["Open"].iloc[1:].values)
    cl = np.log(recent["Close"].iloc[1:].values / recent["Open"].iloc[1:].values)

    rs = (hi * (hi - cl) + lo * (lo - cl)).mean()

    n = window
    k = 0.34 / (1.34 + (n + 1) / (n - 1))

    overnight_var = overnight.var(ddof=1)
    close_open_var = close_open.var(ddof=1)

    yz_var = overnight_var + k * close_open_var + (1 - k) * rs
    yz_vol = np.sqrt(max(yz_var, 0) * 252) * 100

    return float(yz_vol)
