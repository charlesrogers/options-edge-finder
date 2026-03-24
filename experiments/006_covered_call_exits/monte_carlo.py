"""
Monte Carlo Optimal Buyback Simulation

For each scenario (stock vs strike, DTE, volatility):
Simulate 10,000 stock paths, price the call daily via BSM,
compare 8 buyback strategies, find the cheapest one.

Answers: "Given where the stock is NOW, when is the cheapest moment to buy back?"
"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
from py_vollib.black_scholes import black_scholes as bsm_price


def simulate_paths(spot, vol, r, n_days, n_paths=10000):
    """
    Simulate stock price paths using Geometric Brownian Motion.
    Returns array of shape (n_paths, n_days+1) with daily closes.
    """
    dt = 1 / 252
    drift = (r - 0.5 * vol ** 2) * dt
    diffusion = vol * np.sqrt(dt)

    np.random.seed(42)
    Z = np.random.normal(0, 1, (n_paths, n_days))
    log_returns = drift + diffusion * Z

    # Build price paths
    paths = np.zeros((n_paths, n_days + 1))
    paths[:, 0] = spot
    for t in range(n_days):
        paths[:, t + 1] = paths[:, t] * np.exp(log_returns[:, t])

    return paths


def price_call_bsm(spot, strike, T, r, vol):
    """Price a call option via BSM. Returns 0 if T <= 0."""
    if T <= 0.001:
        return max(0, spot - strike)  # intrinsic at expiry
    try:
        return bsm_price('c', spot, strike, T, r, vol)
    except Exception:
        return max(0, spot - strike)


def run_scenario(spot, strike, dte, vol, r=0.045, n_paths=10000):
    """
    Run Monte Carlo for one scenario.

    Returns dict with expected cost of each buyback strategy.
    """
    n_days = dte
    paths = simulate_paths(spot, vol, r, n_days, n_paths)

    # Price the call at entry (day 0)
    T0 = dte / 252
    entry_call_price = price_call_bsm(spot, strike, T0, r, vol)

    # For each path, compute call price each day
    # Shape: (n_paths, n_days+1)
    call_prices = np.zeros((n_paths, n_days + 1))
    for t in range(n_days + 1):
        T_remaining = max(0, (dte - t) / 252)
        for p in range(n_paths):
            call_prices[p, t] = price_call_bsm(paths[p, t], strike, T_remaining, r, vol)

    # Strategy costs (per share, per path)
    results = {
        "immediate": np.full(n_paths, entry_call_price),  # buy back day 0
        "50pct_captured": np.full(n_paths, np.nan),  # first day call drops to 50%
        "75pct_captured": np.full(n_paths, np.nan),
        "strike_cross": np.full(n_paths, np.nan),  # first day stock crosses strike
        "dte_floor_3": np.full(n_paths, np.nan),  # at 3 DTE
        "dte_or_strike": np.full(n_paths, np.nan),  # whichever first
        "expiry": np.zeros(n_paths),  # intrinsic at expiry
        "oracle": np.full(n_paths, np.inf),  # cheapest point on each path
    }

    dte_floor_day = max(0, dte - 3)  # day index where 3 DTE occurs

    for p in range(n_paths):
        # Oracle: minimum call price across all days
        results["oracle"][p] = call_prices[p, :].min()

        # Expiry: intrinsic value at last day
        results["expiry"][p] = max(0, paths[p, -1] - strike)

        # DTE floor: price at 3 DTE
        if dte_floor_day < n_days + 1:
            results["dte_floor_3"][p] = call_prices[p, dte_floor_day]

        # Track triggers across days
        for t in range(1, n_days + 1):
            cp = call_prices[p, t]

            # 50% captured: call price drops to 50% of entry
            if np.isnan(results["50pct_captured"][p]) and cp <= entry_call_price * 0.50:
                results["50pct_captured"][p] = cp

            # 75% captured
            if np.isnan(results["75pct_captured"][p]) and cp <= entry_call_price * 0.25:
                results["75pct_captured"][p] = cp

            # Strike cross: stock goes above strike
            if np.isnan(results["strike_cross"][p]) and paths[p, t] > strike:
                results["strike_cross"][p] = cp

            # DTE or strike: whichever first
            if np.isnan(results["dte_or_strike"][p]):
                if paths[p, t] > strike:
                    results["dte_or_strike"][p] = cp
                elif t >= dte_floor_day:
                    results["dte_or_strike"][p] = cp

        # Fill NaN with expiry cost (trigger never fired → held to expiry)
        for key in ["50pct_captured", "75pct_captured", "strike_cross", "dte_or_strike"]:
            if np.isnan(results[key][p]):
                results[key][p] = results["expiry"][p]

        # DTE floor NaN → expiry
        if np.isnan(results["dte_floor_3"][p]):
            results["dte_floor_3"][p] = results["expiry"][p]

    # Compute statistics for each strategy
    summary = {}
    for strategy, costs in results.items():
        costs_clean = costs[np.isfinite(costs)]
        if len(costs_clean) == 0:
            continue
        summary[strategy] = {
            "mean": round(float(np.mean(costs_clean)), 4),
            "median": round(float(np.median(costs_clean)), 4),
            "p10": round(float(np.percentile(costs_clean, 10)), 4),
            "p90": round(float(np.percentile(costs_clean, 90)), 4),
            "p99": round(float(np.percentile(costs_clean, 99)), 4),
            "pct_zero": round(float((costs_clean == 0).mean() * 100), 1),
            "pct_itm": round(float((costs_clean > 0).mean() * 100), 1),
        }

    # P(assignment) = P(stock > strike at expiry)
    p_assignment = float((paths[:, -1] > strike).mean() * 100)

    return {
        "spot": spot,
        "strike": strike,
        "dte": dte,
        "vol": round(vol, 4),
        "entry_call_price": round(entry_call_price, 4),
        "moneyness_pct": round((spot / strike - 1) * 100, 2),
        "p_assignment": round(p_assignment, 1),
        "strategies": summary,
    }


def main():
    print("=" * 70)
    print("MONTE CARLO: Optimal Buyback Timing for Covered Calls")
    print("10,000 paths per scenario, BSM pricing")
    print("=" * 70)

    # Use AAPL-like parameters
    base_spot = 250  # ~AAPL price
    strike = 260  # sold $260 call
    r = 0.045

    # Volatility levels from real data
    vol_levels = {
        "low": 0.18,   # quiet market
        "mid": 0.28,   # normal AAPL
        "high": 0.45,  # elevated (earnings, macro)
    }

    # Moneyness grid (spot relative to strike)
    moneyness_grid = [
        ("10% OTM", 0.90),
        ("5% OTM", 0.95),
        ("3% OTM", 0.97),
        ("1% OTM", 0.99),
        ("ATM", 1.00),
        ("1% ITM", 1.01),
        ("3% ITM", 1.03),
        ("5% ITM", 1.05),
    ]

    # DTE grid
    dte_grid = [30, 21, 14, 7, 5, 3]

    all_results = []

    # Run with mid volatility first (most common)
    vol = vol_levels["mid"]
    print(f"\nVolatility: {vol:.0%} (normal AAPL)")

    for m_label, m_ratio in moneyness_grid:
        for dte in dte_grid:
            spot = strike * m_ratio
            result = run_scenario(spot, strike, dte, vol)
            result["moneyness_label"] = m_label
            all_results.append(result)

    # Print the decision matrix
    print(f"\n{'=' * 90}")
    print(f"DECISION MATRIX: Expected Buyback Cost by Strategy ($/share, vol={vol:.0%})")
    print(f"{'=' * 90}")
    print(f"{'Position':<12s} {'DTE':>4s} {'P(assign)':>9s} {'Now':>8s} {'50%cap':>8s} {'75%cap':>8s} "
          f"{'StrikeX':>8s} {'3DTE':>8s} {'Expiry':>8s} {'Oracle':>8s} {'BEST':>10s}")
    print("-" * 95)

    for r in all_results:
        s = r["strategies"]
        costs = {k: v["mean"] for k, v in s.items()}
        # Find best non-oracle strategy
        non_oracle = {k: v for k, v in costs.items() if k != "oracle"}
        best_key = min(non_oracle, key=non_oracle.get)
        best_label = {
            "immediate": "NOW",
            "50pct_captured": "50%cap",
            "75pct_captured": "75%cap",
            "strike_cross": "StrikeX",
            "dte_floor_3": "3DTE",
            "dte_or_strike": "DTE/Str",
            "expiry": "Expire",
        }.get(best_key, best_key)

        print(f"{r['moneyness_label']:<12s} {r['dte']:>4d} {r['p_assignment']:>8.1f}% "
              f"${costs.get('immediate', 0):>7.2f} ${costs.get('50pct_captured', 0):>7.2f} "
              f"${costs.get('75pct_captured', 0):>7.2f} ${costs.get('strike_cross', 0):>7.2f} "
              f"${costs.get('dte_floor_3', 0):>7.2f} ${costs.get('expiry', 0):>7.2f} "
              f"${costs.get('oracle', 0):>7.2f} {best_label:>10s}")

    # Print tail risk (99th percentile) for the dangerous scenarios
    print(f"\n{'=' * 70}")
    print(f"TAIL RISK: 99th Percentile Buyback Cost (worst 1%)")
    print(f"{'=' * 70}")
    print(f"{'Position':<12s} {'DTE':>4s} {'Now_p99':>8s} {'50%_p99':>8s} {'Expire_p99':>10s}")
    print("-" * 50)

    for r in all_results:
        s = r["strategies"]
        if r["moneyness_pct"] >= -5:  # only show near-ATM and ITM
            print(f"{r['moneyness_label']:<12s} {r['dte']:>4d} "
                  f"${s.get('immediate', {}).get('p99', 0):>7.2f} "
                  f"${s.get('50pct_captured', {}).get('p99', 0):>7.2f} "
                  f"${s.get('expiry', {}).get('p99', 0):>10.2f}")

    # THE KEY FINDING: at what point does "close now" beat "wait"?
    print(f"\n{'=' * 70}")
    print(f"KEY FINDING: When Does 'Close Now' Beat 'Wait'?")
    print(f"{'=' * 70}")

    for r in all_results:
        s = r["strategies"]
        now = s.get("immediate", {}).get("mean", 0)
        wait_dte = s.get("dte_floor_3", {}).get("mean", 0)
        wait_expire = s.get("expiry", {}).get("mean", 0)

        # Close now is better when its cost < expected cost of waiting
        now_beats_wait = now < wait_dte

        if r["dte"] == 14:  # show the 14 DTE slice
            marker = "← CLOSE NOW" if now_beats_wait else "  wait OK"
            print(f"  {r['moneyness_label']:<12s} 14 DTE: "
                  f"Now=${now:.2f}, Wait=${wait_dte:.2f}, Expire=${wait_expire:.2f} "
                  f"{marker}")

    # Save
    out = os.path.join(os.path.dirname(__file__), "monte_carlo_results.json")
    with open(out, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nFull results saved to {out}")


if __name__ == "__main__":
    main()
