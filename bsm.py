"""
Black-Scholes call pricing, implied volatility and delta.

Used by the H19 (Experiment 017) rational-early-exercise work, which needs a
call delta and the Databento/Yahoo feeds do not carry one.

**Delta from here is a model estimate, not an observation.** It is inverted
from an option's own market price, so it inherits every error in that price —
including the fact that Databento OHLCV is a trade print, not a mid quote.
Anything that uses it must say so.
"""

import math

from scipy.stats import norm

DEFAULT_RISK_FREE = 0.04


def call_price(S, K, T, r, sigma):
    """Black-Scholes European call. T in years."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(0.0, S - K)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)


def call_delta(S, K, T, r, sigma):
    """dPrice/dSpot for a European call."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return float(norm.cdf(d1))


def implied_vol_call(price, S, K, T, r=DEFAULT_RISK_FREE,
                     lo=1e-4, hi=5.0, tol=1e-6, max_iter=100):
    """Invert Black-Scholes for sigma by bisection. None if not invertible.

    Returns None rather than a guess when the price is below intrinsic or above
    the spot — a silently-substituted default vol would turn a data problem into
    a confident delta, which is exactly the failure mode this project keeps
    hitting (tasks/lessons.md 2026-03-23, silent None handling).
    """
    if price is None or T <= 0 or S <= 0 or K <= 0:
        return None
    intrinsic = max(0.0, S - K * math.exp(-r * T))
    if price < intrinsic - 1e-9 or price >= S:
        return None

    lo_price = call_price(S, K, T, r, lo)
    hi_price = call_price(S, K, T, r, hi)
    if not (lo_price <= price <= hi_price):
        return None

    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        val = call_price(S, K, T, r, mid)
        if abs(val - price) < tol:
            return mid
        if val < price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def delta_from_price(price, S, K, dte_days, r=DEFAULT_RISK_FREE):
    """Call delta implied by an observed option price. None if not invertible.

    A deep-ITM call at parity has no extrinsic value left to invert, so implied
    vol is undefined; delta is 1.0 there by definition and is returned as such.
    """
    T = max(dte_days, 0) / 365.0
    if T <= 0:
        return 1.0 if S > K else 0.0
    intrinsic = max(0.0, S - K)
    if price is not None and price <= intrinsic + 1e-6 and S > K:
        return 1.0
    sigma = implied_vol_call(price, S, K, T, r)
    if sigma is None:
        return None
    return call_delta(S, K, T, r, sigma)
