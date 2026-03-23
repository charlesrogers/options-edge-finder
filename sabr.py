"""
SABR Volatility Surface Calibration (Proposal 1A)

Calibrates the SABR stochastic volatility model to option chain data,
producing a smooth implied volatility smile per expiration.

SABR parameters:
  alpha: ATM vol level
  beta:  backbone (fixed at 0.5 for equities)
  rho:   spot-vol correlation (negative = skew)
  nu:    vol-of-vol (controls smile curvature)

The SABR model gives IV at ANY strike, enabling:
  - VRP at every strike (not just ATM)
  - Accurate skew measurement (not the 5% OTM proxy)
  - Foundation for multi-leg strategy pricing

References:
  Hagan et al. (2002), "Managing Smile Risk"
  Sinclair & Mack (2024), Ch. 7: "The Volatility Surface"
"""

import numpy as np
from scipy.optimize import minimize


# ============================================================
# SABR IMPLIED VOLATILITY (Hagan approximation)
# ============================================================

def sabr_iv(strike, forward, T, alpha, beta, rho, nu):
    """
    Compute SABR implied volatility using Hagan's approximation.

    Args:
        strike: Option strike price
        forward: Forward price (spot * exp(r*T))
        T: Time to expiration in years
        alpha: ATM vol level
        beta: Backbone parameter (0.5 for equities)
        rho: Spot-vol correlation
        nu: Vol-of-vol

    Returns:
        Implied volatility (annualized, as decimal e.g. 0.25 = 25%)
    """
    if T <= 0 or alpha <= 0 or strike <= 0 or forward <= 0:
        return np.nan

    # ATM case (avoid division by zero)
    if abs(strike - forward) < 1e-10:
        fmid = forward
        term1 = alpha / (fmid ** (1 - beta))
        term2 = 1 + T * (
            ((1 - beta) ** 2 / 24) * alpha ** 2 / (fmid ** (2 * (1 - beta)))
            + (rho * beta * nu * alpha) / (4 * fmid ** (1 - beta))
            + (2 - 3 * rho ** 2) * nu ** 2 / 24
        )
        return term1 * term2

    # General case
    fk = forward * strike
    fk_beta = fk ** ((1 - beta) / 2)
    logfk = np.log(forward / strike)

    # z and x(z)
    z = (nu / alpha) * fk_beta * logfk
    if abs(z) < 1e-10:
        xz = 1.0
    else:
        sqrt_term = np.sqrt(1 - 2 * rho * z + z ** 2)
        xz = z / np.log((sqrt_term + z - rho) / (1 - rho))

    # Prefactor
    prefactor = alpha / (
        fk_beta * (
            1 + (1 - beta) ** 2 / 24 * logfk ** 2
            + (1 - beta) ** 4 / 1920 * logfk ** 4
        )
    )

    # Correction term
    correction = 1 + T * (
        ((1 - beta) ** 2 / 24) * alpha ** 2 / (fk ** (1 - beta))
        + (rho * beta * nu * alpha) / (4 * fk_beta)
        + (2 - 3 * rho ** 2) * nu ** 2 / 24
    )

    return prefactor * xz * correction


# ============================================================
# SABR CALIBRATION
# ============================================================

def calibrate_sabr(strikes, market_ivs, spot, T, r=0.045,
                   beta=0.5, weights=None):
    """
    Calibrate SABR model to market implied volatilities for one expiration.

    Args:
        strikes: Array of strike prices
        market_ivs: Array of market implied vols (as decimals, e.g. 0.25)
        spot: Current underlying price
        T: Time to expiration in years
        r: Risk-free rate (default 4.5%)
        beta: Fixed backbone parameter (default 0.5 for equities)
        weights: Optional array of calibration weights (e.g. sqrt(volume))

    Returns:
        dict with {alpha, beta, rho, nu, rmse, n_strikes} or None if failed
    """
    strikes = np.asarray(strikes, dtype=float)
    market_ivs = np.asarray(market_ivs, dtype=float)

    # Filter invalid data
    valid = np.isfinite(strikes) & np.isfinite(market_ivs) & (strikes > 0) & (market_ivs > 0)
    strikes = strikes[valid]
    market_ivs = market_ivs[valid]

    if len(strikes) < 3:
        return None

    if weights is not None:
        weights = np.asarray(weights, dtype=float)[valid]
        weights = weights / weights.sum()  # normalize
    else:
        weights = np.ones(len(strikes)) / len(strikes)

    forward = spot * np.exp(r * T)

    # Find ATM IV for initial guess
    atm_idx = np.argmin(np.abs(strikes - spot))
    atm_iv = market_ivs[atm_idx]

    # Initial guess: alpha ≈ ATM IV * F^(1-beta), rho = -0.3, nu = 0.4
    alpha_init = atm_iv * (forward ** (1 - beta))
    x0 = [alpha_init, -0.3, 0.4]

    def objective(params):
        alpha, rho, nu = params
        total_error = 0.0
        for i in range(len(strikes)):
            model_iv = sabr_iv(strikes[i], forward, T, alpha, beta, rho, nu)
            if np.isnan(model_iv):
                return 1e10
            total_error += weights[i] * (model_iv - market_ivs[i]) ** 2
        return total_error

    # Bounds: alpha > 0, -0.999 < rho < 0.999, nu > 0.001
    bounds = [(1e-6, None), (-0.999, 0.999), (0.001, 5.0)]

    try:
        result = minimize(objective, x0, method='L-BFGS-B', bounds=bounds,
                         options={'maxiter': 500, 'ftol': 1e-12})

        alpha_fit, rho_fit, nu_fit = result.x

        # Compute RMSE
        model_ivs = np.array([
            sabr_iv(k, forward, T, alpha_fit, beta, rho_fit, nu_fit)
            for k in strikes
        ])
        residuals = model_ivs - market_ivs
        rmse = float(np.sqrt(np.mean(residuals ** 2)))

        return {
            "alpha": float(alpha_fit),
            "beta": float(beta),
            "rho": float(rho_fit),
            "nu": float(nu_fit),
            "atm_iv": float(atm_iv),
            "rmse": rmse,
            "n_strikes": len(strikes),
            "forward": float(forward),
            "converged": result.success,
        }

    except Exception:
        return None


def calibrate_surface(chains_by_expiry, spot, r=0.045, beta=0.5,
                      min_volume=0, min_oi=0, max_spread_pct=0.5):
    """
    Calibrate SABR model across multiple expirations.

    Args:
        chains_by_expiry: Dict of {expiry_str: SimpleNamespace(calls=df, puts=df)}
        spot: Current underlying price
        r: Risk-free rate
        beta: SABR beta (fixed)
        min_volume: Minimum volume to include strike (0 = include all with OI)
        min_oi: Minimum open interest
        max_spread_pct: Maximum bid-ask spread as fraction of mid (0.5 = 50%)

    Returns:
        Dict of {expiry_str: sabr_params_dict}
    """
    from datetime import datetime

    results = {}
    today = datetime.now()

    for expiry_str, chain in chains_by_expiry.items():
        try:
            # Parse expiry for DTE
            expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d")
            dte = max((expiry_date - today).days, 1)
            T = dte / 365.0

            # Combine calls and puts (use OTM options only — standard practice)
            strikes_list = []
            ivs_list = []
            weights_list = []

            # OTM calls: strike > spot
            if hasattr(chain, 'calls') and not chain.calls.empty:
                calls = chain.calls.copy()
                otm_calls = calls[calls["strike"] > spot].copy()
                _extract_strikes(otm_calls, strikes_list, ivs_list, weights_list,
                                min_volume, min_oi, max_spread_pct)

            # OTM puts: strike < spot
            if hasattr(chain, 'puts') and not chain.puts.empty:
                puts = chain.puts.copy()
                otm_puts = puts[puts["strike"] < spot].copy()
                _extract_strikes(otm_puts, strikes_list, ivs_list, weights_list,
                                min_volume, min_oi, max_spread_pct)

            # ATM from calls (closest strike)
            if hasattr(chain, 'calls') and not chain.calls.empty:
                calls = chain.calls.copy()
                calls["dist"] = abs(calls["strike"] - spot)
                atm = calls.loc[calls["dist"].idxmin()]
                iv_val = atm.get("impliedVolatility", 0)
                if iv_val and iv_val > 0:
                    strikes_list.append(float(atm["strike"]))
                    ivs_list.append(float(iv_val))
                    vol = atm.get("volume", 0) or 0
                    weights_list.append(max(np.sqrt(float(vol)), 1.0) * 2)  # double-weight ATM

            if len(strikes_list) < 3:
                continue

            strikes = np.array(strikes_list)
            ivs = np.array(ivs_list)
            weights = np.array(weights_list)

            # Sort by strike
            order = np.argsort(strikes)
            strikes = strikes[order]
            ivs = ivs[order]
            weights = weights[order]

            # Calibrate
            params = calibrate_sabr(strikes, ivs, spot, T, r, beta, weights)
            if params:
                params["expiry"] = expiry_str
                params["dte"] = dte
                results[expiry_str] = params

        except Exception:
            continue

    return results


def _extract_strikes(options_df, strikes_list, ivs_list, weights_list,
                     min_volume, min_oi, max_spread_pct):
    """Extract valid strikes from an options DataFrame into lists."""
    for _, row in options_df.iterrows():
        iv = row.get("impliedVolatility", 0)
        volume = row.get("volume", 0) or 0
        oi = row.get("openInterest", 0) or 0
        bid = row.get("bid", 0) or 0
        ask = row.get("ask", 0) or 0

        # Filter: must have some market activity
        if volume < min_volume and oi < min_oi:
            if volume == 0 and oi == 0:
                continue

        # Filter: IV must be valid
        if not iv or iv <= 0 or iv > 10:
            continue

        # Filter: bid-ask spread not too wide
        mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else 0
        if mid > 0 and ask > bid:
            spread_pct = (ask - bid) / mid
            if spread_pct > max_spread_pct:
                continue

        strikes_list.append(float(row["strike"]))
        ivs_list.append(float(iv))
        weights_list.append(max(np.sqrt(float(volume)), 1.0))


# ============================================================
# VRP SURFACE — where is vol richest?
# ============================================================

def compute_vrp_surface(sabr_params, spot, rv_forecast, T):
    """
    Compute VRP at multiple strikes using SABR model.

    Args:
        sabr_params: Dict from calibrate_sabr() with alpha, beta, rho, nu
        spot: Current price
        rv_forecast: Realized vol forecast (annualized, as decimal)
        T: Time to expiry in years

    Returns:
        List of dicts: [{strike, moneyness, sabr_iv, rv_forecast, vrp, vrp_pct}]
    """
    if not sabr_params:
        return []

    alpha = sabr_params["alpha"]
    beta = sabr_params["beta"]
    rho = sabr_params["rho"]
    nu = sabr_params["nu"]
    forward = sabr_params.get("forward", spot)

    # Generate strike grid: 80% to 120% of spot in 2.5% steps
    moneyness_range = np.arange(0.80, 1.21, 0.025)
    surface = []

    for m in moneyness_range:
        K = spot * m
        iv = sabr_iv(K, forward, T, alpha, beta, rho, nu)
        if np.isnan(iv) or iv <= 0:
            continue

        vrp = iv - rv_forecast
        vrp_pct = vrp / iv if iv > 0 else 0

        surface.append({
            "strike": round(float(K), 2),
            "moneyness": round(float(m), 4),
            "sabr_iv": round(float(iv), 6),
            "rv_forecast": round(float(rv_forecast), 6),
            "vrp": round(float(vrp), 6),
            "vrp_pct": round(float(vrp_pct), 6),
        })

    return surface


def find_richest_strike(vrp_surface):
    """
    Find the strike with the highest VRP (richest premium to sell).

    Returns dict with the richest strike info, or None.
    """
    if not vrp_surface:
        return None

    return max(vrp_surface, key=lambda x: x["vrp"])
