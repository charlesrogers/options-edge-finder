"""
Experiment 010: Bear Market Stress Test

Monte Carlo simulation of covered call portfolios through crash scenarios.
Answers: "What happens to Dad's money if the market drops 30%?"

Uses GBM stock paths with regime-shifted volatility to simulate crashes.
Option pricing via simplified BSM (adequate for stress testing).
"""

import os
import sys
import json
import math
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
import pandas as pd
from scipy.stats import norm

from position_monitor import assess_position


# ============================================================
# BSM PRICING (simplified, for stress test only)
# ============================================================

def bsm_call_price(S, K, T, r, sigma):
    """Black-Scholes call price. T in years."""
    if T <= 0 or sigma <= 0:
        return max(S - K, 0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)


# ============================================================
# STOCK PATH GENERATORS
# ============================================================

def generate_gbm_paths(S0, days, n_paths, mu, sigma, seed=42):
    """Generate geometric Brownian motion stock paths."""
    rng = np.random.RandomState(seed)
    dt = 1 / 252
    paths = np.zeros((n_paths, days))
    paths[:, 0] = S0
    for t in range(1, days):
        z = rng.standard_normal(n_paths)
        paths[:, t] = paths[:, t-1] * np.exp((mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z)
    return paths


def generate_crash_paths(S0, days, n_paths, crash_day, crash_pct, pre_vol, post_vol, seed=42):
    """Generate paths with a crash event at crash_day."""
    rng = np.random.RandomState(seed)
    dt = 1 / 252
    paths = np.zeros((n_paths, days))
    paths[:, 0] = S0

    for t in range(1, days):
        z = rng.standard_normal(n_paths)
        if t == crash_day:
            # Crash: deterministic drop + high vol noise
            paths[:, t] = paths[:, t-1] * (1 + crash_pct + post_vol * np.sqrt(dt) * z)
        elif t > crash_day:
            # Post-crash: elevated vol, slight recovery drift
            paths[:, t] = paths[:, t-1] * np.exp((0.05 - 0.5 * post_vol**2) * dt + post_vol * np.sqrt(dt) * z)
        else:
            # Pre-crash: normal
            paths[:, t] = paths[:, t-1] * np.exp((0.10 - 0.5 * pre_vol**2) * dt + pre_vol * np.sqrt(dt) * z)

    return paths


def generate_gradual_decline(S0, days, n_paths, total_decline, vol, seed=42):
    """Generate paths with gradual decline (2022 style)."""
    rng = np.random.RandomState(seed)
    dt = 1 / 252
    # Daily drift to achieve total_decline over the period
    daily_drift = total_decline / days
    paths = np.zeros((n_paths, days))
    paths[:, 0] = S0
    for t in range(1, days):
        z = rng.standard_normal(n_paths)
        paths[:, t] = paths[:, t-1] * np.exp((daily_drift - 0.5 * vol**2) * dt + vol * np.sqrt(dt) * z)
    return paths


# ============================================================
# COVERED CALL SIMULATOR (on synthetic paths)
# ============================================================

def simulate_covered_call_on_path(path, otm_pct=0.05, entry_interval=21,
                                    min_dte=20, max_dte=45, vol=0.25, r=0.05):
    """
    Simulate covered call selling on a single stock price path.

    Returns portfolio value series (stock + call P&L).
    """
    days = len(path)
    call_pnl_total = 0.0
    positions = []
    daily_pnl = []
    current_pos = None
    assignments = 0
    trades = []
    last_entry_day = -entry_interval  # allow entry on day 0

    for day in range(days):
        spot = path[day]
        remaining_days = days - day

        # Entry: sell a new call if no position and enough time
        if current_pos is None and (day - last_entry_day) >= entry_interval and remaining_days > min_dte:
            strike = spot * (1 + otm_pct)
            dte = min(max_dte, remaining_days - 5)  # leave buffer
            if dte >= min_dte:
                T = dte / 252
                premium = bsm_call_price(spot, strike, T, r, vol * 1.2)  # sell at elevated IV
                current_pos = {
                    'strike': strike, 'premium': premium,
                    'entry_day': day, 'entry_spot': spot,
                    'dte_at_entry': dte, 'expiry_day': day + dte,
                }
                last_entry_day = day

        # Monitor existing position
        if current_pos:
            dte_now = max(0, current_pos['expiry_day'] - day)
            T_now = max(dte_now / 252, 1/252)

            # Current call value
            call_value = bsm_call_price(spot, current_pos['strike'], T_now, r, vol * 1.2)

            # Run copilot
            pct_from_strike = (current_pos['strike'] - spot) / spot * 100
            is_itm = spot > current_pos['strike']

            # Simplified copilot logic (matches position_monitor thresholds)
            close = False
            close_reason = ""

            if is_itm:
                close = True
                close_reason = "CLOSE_NOW: ITM"
            elif dte_now < 3 and pct_from_strike < 3:
                close = True
                close_reason = "CLOSE_NOW: gamma zone"
            elif pct_from_strike < 2 and dte_now >= 7:
                close = True
                close_reason = "CLOSE_SOON: near strike"
            elif pct_from_strike < 3 and dte_now < 7:
                close = True
                close_reason = "CLOSE_SOON: gamma zone"
            elif dte_now <= 0:
                close = True
                close_reason = "Expired"

            if close:
                buyback = call_value
                pnl = (current_pos['premium'] - buyback) * 100
                would_assign = spot > current_pos['strike'] if close_reason == "Expired" else False

                trades.append({
                    'entry_day': current_pos['entry_day'],
                    'exit_day': day,
                    'strike': current_pos['strike'],
                    'premium': current_pos['premium'],
                    'buyback': buyback,
                    'pnl': pnl,
                    'close_reason': close_reason,
                    'entry_spot': current_pos['entry_spot'],
                    'exit_spot': spot,
                })

                call_pnl_total += pnl
                current_pos = None

        # Daily value: stock value + cumulative call P&L
        stock_value = spot * 100  # 100 shares
        daily_pnl.append(stock_value + call_pnl_total)

    return {
        'daily_values': daily_pnl,
        'total_call_pnl': call_pnl_total,
        'trades': trades,
        'final_stock': path[-1] * 100,
        'final_total': daily_pnl[-1] if daily_pnl else path[-1] * 100,
    }


# ============================================================
# SCENARIOS
# ============================================================

SCENARIOS = {
    'bull_market': {
        'label': 'Bull Market (+20% over 6mo)',
        'generator': 'gbm',
        'params': {'mu': 0.20, 'sigma': 0.20, 'days': 126},
    },
    'sideways': {
        'label': 'Sideways Grind (0% over 6mo, high vol)',
        'generator': 'gbm',
        'params': {'mu': 0.0, 'sigma': 0.30, 'days': 126},
    },
    'gradual_decline': {
        'label': 'Gradual Decline (-20% over 6mo, 2022 style)',
        'generator': 'gradual',
        'params': {'total_decline': -0.20, 'vol': 0.35, 'days': 126},
    },
    'sharp_crash': {
        'label': 'Sharp Crash (-30% in 1 month)',
        'generator': 'crash',
        'params': {'crash_day': 15, 'crash_pct': -0.30, 'pre_vol': 0.20, 'post_vol': 0.50, 'days': 126},
    },
    'flash_crash': {
        'label': 'Flash Crash (-10% day 1, recovery)',
        'generator': 'crash',
        'params': {'crash_day': 1, 'crash_pct': -0.10, 'pre_vol': 0.20, 'post_vol': 0.35, 'days': 126},
    },
}


def run_scenario(name, config, S0=250, n_paths=10000, otm_pct=0.05):
    """Run Monte Carlo for one scenario."""
    gen = config['generator']
    params = config['params']
    days = params['days']

    if gen == 'gbm':
        paths = generate_gbm_paths(S0, days, n_paths, params['mu'], params['sigma'])
    elif gen == 'gradual':
        paths = generate_gradual_decline(S0, days, n_paths, params['total_decline'], params['vol'])
    elif gen == 'crash':
        paths = generate_crash_paths(S0, days, n_paths,
                                      params['crash_day'], params['crash_pct'],
                                      params['pre_vol'], params['post_vol'])

    # Simulate covered calls on each path
    stock_only_finals = []
    cc_finals = []
    cc_call_pnls = []
    cushion_pcts = []

    vol_for_pricing = params.get('sigma', params.get('vol', params.get('post_vol', 0.30)))

    print(f"  Simulating {n_paths} paths...", end=" ", flush=True)
    for i in range(n_paths):
        path = paths[i]
        result = simulate_covered_call_on_path(path, otm_pct=otm_pct, vol=vol_for_pricing)

        stock_final = path[-1] * 100
        cc_final = result['final_total']

        stock_only_finals.append(stock_final)
        cc_finals.append(cc_final)
        cc_call_pnls.append(result['total_call_pnl'])

        stock_return = (path[-1] - S0) / S0 * 100
        cc_return = (cc_final - S0 * 100) / (S0 * 100) * 100
        cushion_pcts.append(cc_return - stock_return)

    stock_only = np.array(stock_only_finals)
    cc_total = np.array(cc_finals)
    call_pnls = np.array(cc_call_pnls)
    cushions = np.array(cushion_pcts)

    initial = S0 * 100
    stock_returns = (stock_only - initial) / initial * 100
    cc_returns = (cc_total - initial) / initial * 100

    print("done")

    return {
        'scenario': name,
        'label': config['label'],
        'n_paths': n_paths,
        'initial_value': initial,
        # Stock only
        'stock_mean_return': round(float(np.mean(stock_returns)), 2),
        'stock_median_return': round(float(np.median(stock_returns)), 2),
        'stock_5th_pctl': round(float(np.percentile(stock_returns, 5)), 2),
        'stock_1st_pctl': round(float(np.percentile(stock_returns, 1)), 2),
        'stock_worst': round(float(np.min(stock_returns)), 2),
        # Covered calls + copilot
        'cc_mean_return': round(float(np.mean(cc_returns)), 2),
        'cc_median_return': round(float(np.median(cc_returns)), 2),
        'cc_5th_pctl': round(float(np.percentile(cc_returns, 5)), 2),
        'cc_1st_pctl': round(float(np.percentile(cc_returns, 1)), 2),
        'cc_worst': round(float(np.min(cc_returns)), 2),
        # Premium cushion
        'avg_call_pnl': round(float(np.mean(call_pnls)), 2),
        'median_call_pnl': round(float(np.median(call_pnls)), 2),
        'avg_cushion_pct': round(float(np.mean(cushions)), 2),
        # Comparison
        'cc_beats_stock_pct': round(float((cc_total > stock_only).mean() * 100), 1),
    }


def main():
    print("=" * 80)
    print("EXPERIMENT 010: Bear Market Stress Test")
    print("What happens to Dad's covered call portfolio in a crash?")
    print(f"10,000 Monte Carlo paths per scenario, starting at $250/share (100 shares)")
    print("=" * 80)

    results = []

    for name, config in SCENARIOS.items():
        print(f"\n{'=' * 80}")
        print(f"SCENARIO: {config['label']}")
        print(f"{'=' * 80}")

        # Run at the recommended OTM% for AAPL (15%) and the "aggressive" 3%
        for otm_label, otm_pct in [("3% OTM (aggressive)", 0.03), ("15% OTM (conservative)", 0.15)]:
            print(f"\n  Strategy: {otm_label}")
            result = run_scenario(name, config, S0=250, n_paths=10000, otm_pct=otm_pct)
            result['otm_label'] = otm_label
            result['otm_pct'] = otm_pct
            results.append(result)

            print(f"    Stock only:     {result['stock_mean_return']:+.1f}% mean, "
                  f"{result['stock_5th_pctl']:+.1f}% (5th pctl), {result['stock_worst']:+.1f}% (worst)")
            print(f"    CC + copilot:   {result['cc_mean_return']:+.1f}% mean, "
                  f"{result['cc_5th_pctl']:+.1f}% (5th pctl), {result['cc_worst']:+.1f}% (worst)")
            print(f"    Premium cushion: ${result['avg_call_pnl']:+,.0f} avg")
            print(f"    CC beats stock: {result['cc_beats_stock_pct']:.0f}% of paths")

    # ============================================================
    # SUMMARY TABLE
    # ============================================================
    print(f"\n{'=' * 80}")
    print("SUMMARY: Does the covered call strategy help or hurt in each scenario?")
    print(f"{'=' * 80}")

    print(f"\n{'Scenario':<35s} {'OTM%':<15s} | {'Stock':>8s} {'CC+Cop':>8s} {'Cushion':>8s} {'CC wins':>8s}")
    print("-" * 90)
    for r in results:
        print(f"{r['label'][:35]:<35s} {r['otm_label'][:15]:<15s} | "
              f"{r['stock_mean_return']:>+7.1f}% {r['cc_mean_return']:>+7.1f}% "
              f"{r['avg_cushion_pct']:>+7.1f}% {r['cc_beats_stock_pct']:>7.0f}%")

    # ============================================================
    # DAD'S PORTFOLIO AT SCALE
    # ============================================================
    print(f"\n{'=' * 80}")
    print("WHAT THIS MEANS FOR DAD (1,000 shares = 10 contracts)")
    print(f"{'=' * 80}")

    # Focus on the crash scenarios
    for r in results:
        if 'crash' in r['scenario'] or 'decline' in r['scenario']:
            scale = 10  # 10 contracts = 1000 shares
            stock_loss_5th = r['stock_5th_pctl'] / 100 * 250 * 1000
            cc_loss_5th = r['cc_5th_pctl'] / 100 * 250 * 1000
            cushion = (cc_loss_5th - stock_loss_5th)
            print(f"\n  {r['label']} ({r['otm_label']}):")
            print(f"    Stock loss (5th pctl): ${stock_loss_5th:+,.0f}")
            print(f"    CC + copilot loss:     ${cc_loss_5th:+,.0f}")
            print(f"    Premium cushion:       ${cushion:+,.0f}")

    # Save
    out = os.path.join(os.path.dirname(__file__), 'results.json')
    with open(out, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    main()
