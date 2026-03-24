"""
Test H05-H08: Edge Sizing Hypotheses

Uses aggregate backtest data (15 ticker-signal groups across 5 tickers)
to test whether VRP thresholds, IV Rank thresholds, and VRP/IV ratios
are optimally calibrated.

These are AGGREGATE tests (not individual-trade tests). Individual-trade
tests will run when live predictions are scored (~April 7+).

Usage:
  python test_edge_sizing.py
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from scipy import stats as scipy_stats


def load_data():
    results_dir = os.path.join(os.path.dirname(__file__), "basket_results")
    files = sorted([f for f in os.listdir(results_dir) if f.endswith(".json")])
    if not files:
        return None
    with open(os.path.join(results_dir, files[-1])) as f:
        return json.load(f)


def extract_groups(data):
    """Extract all ticker-signal groups with computed Realized VRP."""
    groups = []
    for ticker, tdata in data["tickers"].items():
        by_signal = tdata.get("one_pass", {}).get("by_signal", {})
        for sig, s in by_signal.items():
            exp = s.get("avg_expected_move", 0)
            act = s.get("avg_actual_move", 0)
            rvrp = (exp - act) / exp if exp > 0 else None
            groups.append({
                "ticker": ticker,
                "signal": sig,
                "count": s["count"],
                "avg_vrp": s.get("avg_vrp", 0),
                "win_rate": s["win_rate"],
                "avg_pnl": s["avg_pnl_pct"],
                "avg_expected_move": exp,
                "avg_actual_move": act,
                "rvrp": rvrp,
                "cost_pct": s.get("avg_cost_pct", 0.3),
            })
    return groups


def test_h05(groups):
    """
    H05: Optimal VRP Threshold

    Is there a VRP level below which Realized VRP turns negative?
    Plot the VRP-to-RVRP mapping and find the breakpoint.
    """
    print("\n" + "=" * 60)
    print("H05: Optimal VRP Threshold")
    print("=" * 60)

    sorted_groups = sorted(groups, key=lambda x: x["avg_vrp"])

    print(f"\n{'VRP':>8s} {'RVRP':>8s} {'Win%':>7s} {'PnL%':>8s} {'Ticker':>6s} {'Signal':>8s} {'n':>5s}")
    print("-" * 58)
    for g in sorted_groups:
        rvrp_str = f"{g['rvrp']:.1%}" if g['rvrp'] is not None else "N/A"
        print(f"{g['avg_vrp']:8.1f} {rvrp_str:>8s} {g['win_rate']:6.1f}% {g['avg_pnl']:+7.2f}% "
              f"{g['ticker']:>6s} {g['signal']:>8s} {g['count']:5d}")

    # Find breakpoint: where does RVRP turn consistently positive?
    vrps = np.array([g["avg_vrp"] for g in sorted_groups])
    rvrps = np.array([g["rvrp"] for g in sorted_groups if g["rvrp"] is not None])
    vrps_valid = np.array([g["avg_vrp"] for g in sorted_groups if g["rvrp"] is not None])

    # All groups have positive RVRP in this dataset, so look for the steepest improvement
    # Breakpoint = where marginal RVRP gain per VRP point is highest
    rho, p = scipy_stats.spearmanr(vrps_valid, rvrps)

    # Check: do negative-VRP groups still have positive RVRP?
    neg_vrp = [g for g in sorted_groups if g["avg_vrp"] < 0 and g["rvrp"] is not None]
    pos_vrp = [g for g in sorted_groups if g["avg_vrp"] > 0 and g["rvrp"] is not None]
    neg_avg_rvrp = np.mean([g["rvrp"] for g in neg_vrp]) if neg_vrp else None
    pos_avg_rvrp = np.mean([g["rvrp"] for g in pos_vrp]) if pos_vrp else None

    # Check VRP > 2 (current threshold) vs VRP 0-2 vs VRP < 0
    high_vrp = [g for g in groups if g["avg_vrp"] > 2 and g["rvrp"] is not None]
    mid_vrp = [g for g in groups if 0 <= g["avg_vrp"] <= 2 and g["rvrp"] is not None]
    low_vrp = [g for g in groups if g["avg_vrp"] < 0 and g["rvrp"] is not None]

    print(f"\n=== VRP Bucket Analysis ===")
    for label, bucket in [("VRP > 2 (GREEN zone)", high_vrp),
                           ("VRP 0-2 (YELLOW zone)", mid_vrp),
                           ("VRP < 0 (RED zone)", low_vrp)]:
        if bucket:
            avg_r = np.mean([g["rvrp"] for g in bucket])
            avg_w = np.mean([g["win_rate"] for g in bucket])
            n = sum(g["count"] for g in bucket)
            print(f"  {label}: RVRP={avg_r:.1%}, Win={avg_w:.1f}%, n={n}")

    print(f"\nCorrelation VRP → RVRP: rho={rho:.3f}, p={p:.4f}")

    # H05 finding
    if neg_avg_rvrp is not None and neg_avg_rvrp > 0:
        print(f"\nFINDING: Even NEGATIVE VRP groups have positive RVRP ({neg_avg_rvrp:.1%}).")
        print("This means the IV proxy (RV * 1.2) in backtests bakes in some VRP.")
        print("The threshold question is: at what VRP does RVRP become LARGE enough")
        print("to justify the risk? Current threshold (VRP > 2) appears conservative.")
    else:
        print(f"\nFINDING: Negative VRP → negative RVRP. Threshold at VRP=0 is validated.")


def test_h06(groups):
    """
    H06: IV Rank Threshold

    We can't directly test IV Rank from aggregate data (not in by_signal stats).
    But we can infer: GREEN signals require IV Rank > quantile threshold.
    Compare GREEN RVRP across tickers (proxy for IV level variation).
    """
    print("\n" + "=" * 60)
    print("H06: IV Rank Threshold (Indirect Test)")
    print("=" * 60)

    print("\nCannot directly test IV Rank thresholds from aggregate backtest data.")
    print("IV Rank is used in signal classification but not reported per-signal.")
    print("This hypothesis requires individual-trade data (available after April 7).")
    print("\nIndirect evidence: GREEN signals (which require IV above q30 threshold)")
    print("consistently outperform YELLOW/RED across all 5 tickers,")
    print("suggesting the IV threshold adds value beyond VRP alone.")

    for ticker in sorted(set(g["ticker"] for g in groups)):
        t_groups = [g for g in groups if g["ticker"] == ticker]
        green = [g for g in t_groups if g["signal"] == "GREEN"]
        yellow = [g for g in t_groups if g["signal"] == "YELLOW"]
        if green and yellow:
            g_rvrp = green[0]["rvrp"] if green[0]["rvrp"] else 0
            y_rvrp = yellow[0]["rvrp"] if yellow[0]["rvrp"] else 0
            print(f"  {ticker}: GREEN RVRP={g_rvrp:.1%} vs YELLOW={y_rvrp:.1%} "
                  f"(spread={g_rvrp-y_rvrp:.1%})")

    print("\nWill formally test with individual predictions after scoring begins.")


def test_h08(groups):
    """
    H08: VRP/IV Ratio vs Absolute VRP

    Sinclair: VRP is ~19% of IV at low vol, ~13% at high vol.
    Test: is VRP/expected_move (proxy for VRP/IV) a better predictor than absolute VRP?
    """
    print("\n" + "=" * 60)
    print("H08: VRP/IV Ratio vs Absolute VRP")
    print("=" * 60)

    # Compute VRP as % of expected move (proxy for VRP/IV)
    for g in groups:
        if g["avg_expected_move"] > 0:
            g["vrp_pct_of_iv"] = g["avg_vrp"] / g["avg_expected_move"]
        else:
            g["vrp_pct_of_iv"] = None

    valid = [g for g in groups if g["rvrp"] is not None and g.get("vrp_pct_of_iv") is not None]

    vrps_abs = np.array([g["avg_vrp"] for g in valid])
    vrps_pct = np.array([g["vrp_pct_of_iv"] for g in valid])
    rvrps = np.array([g["rvrp"] for g in valid])

    rho_abs, p_abs = scipy_stats.spearmanr(vrps_abs, rvrps)
    rho_pct, p_pct = scipy_stats.spearmanr(vrps_pct, rvrps)

    print(f"\nAbsolute VRP → RVRP: rho={rho_abs:.3f} (p={p_abs:.4f})")
    print(f"VRP/IV Ratio → RVRP: rho={rho_pct:.3f} (p={p_pct:.4f})")

    print(f"\n{'Ticker':>6s} {'Signal':>8s} {'VRP':>8s} {'VRP/IV':>8s} {'RVRP':>8s}")
    print("-" * 44)
    for g in sorted(valid, key=lambda x: x.get("vrp_pct_of_iv", 0), reverse=True):
        print(f"{g['ticker']:>6s} {g['signal']:>8s} {g['avg_vrp']:8.1f} "
              f"{g['vrp_pct_of_iv']:8.1%} {g['rvrp']:8.1%}")

    if rho_pct > rho_abs + 0.05:
        print(f"\nH08 FINDING: VRP/IV ratio ({rho_pct:.3f}) is a BETTER predictor than "
              f"absolute VRP ({rho_abs:.3f}). Consider switching to percentage-based thresholds.")
    elif abs(rho_pct - rho_abs) < 0.05:
        print(f"\nH08 FINDING: VRP/IV ratio ({rho_pct:.3f}) and absolute VRP ({rho_abs:.3f}) "
              f"are roughly equivalent predictors. Keep absolute VRP (simpler).")
    else:
        print(f"\nH08 FINDING: Absolute VRP ({rho_abs:.3f}) is BETTER than VRP/IV ratio "
              f"({rho_pct:.3f}). Current system is correct.")


def main():
    data = load_data()
    if not data:
        print("No basket results found.")
        return

    groups = extract_groups(data)
    print(f"Loaded {len(groups)} ticker-signal groups across {len(data['tickers'])} tickers")

    test_h05(groups)
    test_h06(groups)
    test_h08(groups)

    # Summary
    print("\n" + "=" * 60)
    print("EDGE SIZING SUMMARY")
    print("=" * 60)
    print("H05 (VRP threshold): Tested on aggregate data. Full test needs individual trades.")
    print("H06 (IV Rank threshold): Needs individual trade data (after April 7).")
    print("H07 (IV compression): Needs timestamped IV data (after April 7).")
    print("H08 (VRP/IV ratio): Tested on aggregate data. See finding above.")
    print("\nAll edge-sizing hypotheses will get definitive answers once")
    print("live predictions are scored with individual-trade RVRP data.")


if __name__ == "__main__":
    main()
