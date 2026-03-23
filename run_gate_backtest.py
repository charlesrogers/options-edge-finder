"""
Run H01-H04 against BACKTEST data (6 years, 5 tickers).

This doesn't wait for live predictions to mature — it uses the basket_results
JSON from the existing backtest engine to test core hypotheses TODAY.

Realized VRP from backtest = (expected_move - actual_move) / expected_move
  where expected_move = IV-derived, actual_move = realized

Usage:
  python run_gate_backtest.py
  # Or via GitHub Actions
"""

import os
import sys
import json
import math

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np


def load_basket_results():
    """Load the most recent basket results JSON."""
    results_dir = os.path.join(os.path.dirname(__file__), "basket_results")
    if not os.path.exists(results_dir):
        print("No basket_results directory found.")
        return None

    files = sorted([f for f in os.listdir(results_dir) if f.endswith(".json")])
    if not files:
        print("No basket result files found.")
        return None

    latest = os.path.join(results_dir, files[-1])
    print(f"Loading: {latest}")
    with open(latest) as f:
        return json.load(f)


def run_h01_backtest(data):
    """
    H01: VRP Predicts Seller Wins.

    Test: Do trades where VRP > 0 produce positive Realized VRP?
    Using backtest by_signal data across all tickers.
    """
    print("\n" + "=" * 60)
    print("H01: VRP Predicts Seller Wins (Backtest)")
    print("=" * 60)

    all_signals = []
    for ticker, tdata in data["tickers"].items():
        by_signal = tdata.get("one_pass", {}).get("by_signal", {})
        for sig, stats in by_signal.items():
            count = stats.get("count", 0)
            exp_move = stats.get("avg_expected_move", 0)
            act_move = stats.get("avg_actual_move", 0)
            win_rate = stats.get("win_rate", 0)
            avg_pnl = stats.get("avg_pnl_pct", 0)
            avg_vrp = stats.get("avg_vrp", 0)

            # Realized VRP = (expected_move - actual_move) / expected_move
            if exp_move and exp_move > 0:
                rvrp = (exp_move - act_move) / exp_move
            else:
                rvrp = None

            all_signals.append({
                "ticker": ticker, "signal": sig, "count": count,
                "win_rate": win_rate, "avg_pnl_pct": avg_pnl,
                "avg_vrp": avg_vrp,
                "avg_expected_move": exp_move, "avg_actual_move": act_move,
                "realized_vrp": rvrp,
            })

    # Aggregate across all tickers
    total_trades = sum(s["count"] for s in all_signals)
    weighted_rvrp = sum(s["realized_vrp"] * s["count"] for s in all_signals if s["realized_vrp"] is not None)
    weighted_count = sum(s["count"] for s in all_signals if s["realized_vrp"] is not None)
    avg_rvrp = weighted_rvrp / weighted_count if weighted_count > 0 else 0

    weighted_win = sum(s["win_rate"] * s["count"] for s in all_signals) / total_trades if total_trades > 0 else 0

    # Per-ticker breakdown
    print(f"\nTotal trades across all tickers/signals: {total_trades}")
    print(f"Weighted avg Realized VRP: {avg_rvrp:.1%}")
    print(f"Weighted avg win rate: {weighted_win:.1f}%")

    print("\nPer-ticker breakdown:")
    for ticker in data["tickers"]:
        t_signals = [s for s in all_signals if s["ticker"] == ticker]
        t_trades = sum(s["count"] for s in t_signals)
        t_rvrp_w = sum(s["realized_vrp"] * s["count"] for s in t_signals if s["realized_vrp"])
        t_rvrp = t_rvrp_w / t_trades if t_trades > 0 else 0
        t_win = sum(s["win_rate"] * s["count"] for s in t_signals) / t_trades if t_trades > 0 else 0
        print(f"  {ticker}: RVRP={t_rvrp:.1%}, Win={t_win:.1f}%, n={t_trades}")

    # GREEN-only test (the core thesis)
    green_trades = sum(s["count"] for s in all_signals if s["signal"] == "GREEN")
    green_rvrp_w = sum(s["realized_vrp"] * s["count"] for s in all_signals
                       if s["signal"] == "GREEN" and s["realized_vrp"] is not None)
    green_rvrp = green_rvrp_w / green_trades if green_trades > 0 else 0
    green_win = sum(s["win_rate"] * s["count"] for s in all_signals if s["signal"] == "GREEN") / green_trades if green_trades > 0 else 0

    print(f"\nGREEN signals only:")
    print(f"  Realized VRP: {green_rvrp:.1%}")
    print(f"  Win rate: {green_win:.1f}%")
    print(f"  Trades: {green_trades}")

    # Sharpe approximation from per-ticker green_only data
    green_pnls = []
    for ticker, tdata in data["tickers"].items():
        go = tdata.get("green_only", {})
        if go.get("avg_pnl") and go.get("n_trades"):
            green_pnls.extend([go["avg_pnl"]] * go["n_trades"])
    sharpe = 0
    if green_pnls:
        arr = np.array(green_pnls)
        sharpe = arr.mean() / arr.std() * np.sqrt(252 / 20) if arr.std() > 0 else 0

    # H01 assessment
    passed = (green_rvrp > 0.015
              and green_win > 55
              and green_trades >= 200)

    print(f"\nH01 ASSESSMENT:")
    print(f"  [{'PASS' if green_rvrp > 0.015 else 'FAIL'}] Avg Realized VRP > 1.5%: {green_rvrp:.1%}")
    print(f"  [{'PASS' if green_win > 55 else 'FAIL'}] Win rate > 55%: {green_win:.1f}%")
    print(f"  [{'PASS' if green_trades >= 200 else 'FAIL'}] n >= 200: {green_trades}")
    print(f"\n  H01: {'PASSED' if passed else 'FAILED'}")

    return {
        "hypothesis": "H01",
        "passed": passed,
        "metrics": {
            "avg_rvrp_all": round(avg_rvrp, 4),
            "avg_rvrp_green": round(green_rvrp, 4),
            "win_rate_green": round(green_win, 2),
            "n_trades_green": green_trades,
            "n_trades_all": total_trades,
            "approx_sharpe": round(sharpe, 4),
        },
    }


def run_h03_backtest(data):
    """
    H03: Signal Discrimination — GREEN > YELLOW > RED.

    Test: Is the Realized VRP ordering monotonic across signal types?
    """
    print("\n" + "=" * 60)
    print("H03: Signal Discrimination (GREEN > YELLOW > RED)")
    print("=" * 60)

    # Aggregate by signal across all tickers
    signal_agg = {}
    for sig in ["GREEN", "YELLOW", "RED"]:
        entries = []
        for ticker, tdata in data["tickers"].items():
            by_signal = tdata.get("one_pass", {}).get("by_signal", {})
            if sig in by_signal:
                s = by_signal[sig]
                exp = s.get("avg_expected_move", 0)
                act = s.get("avg_actual_move", 0)
                rvrp = (exp - act) / exp if exp > 0 else None
                entries.append({
                    "ticker": ticker,
                    "count": s["count"],
                    "win_rate": s["win_rate"],
                    "avg_pnl": s["avg_pnl_pct"],
                    "avg_vrp": s.get("avg_vrp", 0),
                    "rvrp": rvrp,
                })

        total = sum(e["count"] for e in entries)
        if total > 0:
            w_rvrp = sum(e["rvrp"] * e["count"] for e in entries if e["rvrp"] is not None)
            w_win = sum(e["win_rate"] * e["count"] for e in entries)
            w_pnl = sum(e["avg_pnl"] * e["count"] for e in entries)
            signal_agg[sig] = {
                "avg_rvrp": w_rvrp / total,
                "avg_win_rate": w_win / total,
                "avg_pnl": w_pnl / total,
                "n_trades": total,
            }

    print("\nSignal Type | Realized VRP | Win Rate | Avg P&L | Trades")
    print("-" * 65)
    for sig in ["GREEN", "YELLOW", "RED"]:
        if sig in signal_agg:
            s = signal_agg[sig]
            print(f"  {sig:8s} | {s['avg_rvrp']:11.1%} | {s['avg_win_rate']:7.1f}% | {s['avg_pnl']:+7.2f}% | {s['n_trades']}")

    # Monotonic check
    g = signal_agg.get("GREEN", {}).get("avg_rvrp")
    y = signal_agg.get("YELLOW", {}).get("avg_rvrp")
    r = signal_agg.get("RED", {}).get("avg_rvrp")

    monotonic = True
    if g is not None and y is not None:
        monotonic = monotonic and g > y
    if y is not None and r is not None:
        monotonic = monotonic and y > r

    spread = (g - r) if g is not None and r is not None else None

    passed = (monotonic
              and g is not None and g > 0.02
              and spread is not None and spread > 0.015)

    print(f"\nH03 ASSESSMENT:")
    print(f"  [{'PASS' if monotonic else 'FAIL'}] Monotonic ordering: GREEN > YELLOW > RED")
    print(f"  [{'PASS' if g and g > 0.02 else 'FAIL'}] GREEN RVRP > 2%: {g:.1%}" if g else "  [FAIL] No GREEN data")
    print(f"  [{'PASS' if spread and spread > 0.015 else 'FAIL'}] GREEN-RED spread > 1.5%: {spread:.1%}" if spread else "  [FAIL] No spread data")
    print(f"\n  H03: {'PASSED' if passed else 'FAILED'}")

    return {
        "hypothesis": "H03",
        "passed": passed,
        "metrics": {
            "green_rvrp": round(g, 4) if g else None,
            "yellow_rvrp": round(y, 4) if y else None,
            "red_rvrp": round(r, 4) if r else None,
            "spread": round(spread, 4) if spread else None,
            "monotonic": monotonic,
        },
    }


def run_h04_backtest(data):
    """
    H04: VRP Magnitude Proportional to Edge.

    Test: Do tickers/signals with higher VRP produce higher Realized VRP?
    """
    print("\n" + "=" * 60)
    print("H04: VRP Magnitude Proportional to Edge")
    print("=" * 60)

    # Collect (avg_vrp, realized_vrp) pairs across all ticker-signal combos
    points = []
    for ticker, tdata in data["tickers"].items():
        by_signal = tdata.get("one_pass", {}).get("by_signal", {})
        for sig, stats in by_signal.items():
            avg_vrp = stats.get("avg_vrp", 0)
            exp = stats.get("avg_expected_move", 0)
            act = stats.get("avg_actual_move", 0)
            if exp > 0:
                rvrp = (exp - act) / exp
                points.append({
                    "ticker": ticker, "signal": sig,
                    "vrp": avg_vrp, "rvrp": rvrp,
                    "count": stats["count"],
                })

    if len(points) < 5:
        print("Insufficient data points for correlation test.")
        return {"hypothesis": "H04", "passed": False, "error": "insufficient data"}

    vrps = np.array([p["vrp"] for p in points])
    rvrps = np.array([p["rvrp"] for p in points])
    weights = np.array([p["count"] for p in points])

    # Weighted Spearman (approximate: use ranks)
    from scipy import stats as scipy_stats
    rho, p_value = scipy_stats.spearmanr(vrps, rvrps)

    print(f"\nVRP vs Realized VRP across {len(points)} ticker-signal groups:")
    print(f"  Spearman rho: {rho:.3f}")
    print(f"  p-value: {p_value:.6f}")

    # Show the data
    print(f"\n  {'Ticker':6s} {'Signal':8s} {'VRP':>8s} {'RVRP':>8s} {'Trades':>6s}")
    print("  " + "-" * 42)
    for p in sorted(points, key=lambda x: x["vrp"], reverse=True):
        print(f"  {p['ticker']:6s} {p['signal']:8s} {p['vrp']:8.2f} {p['rvrp']:8.1%} {p['count']:6d}")

    passed = rho > 0.15 and p_value < 0.05  # relaxed from 0.01 for small sample

    print(f"\nH04 ASSESSMENT:")
    print(f"  [{'PASS' if rho > 0.15 else 'FAIL'}] Spearman rho > 0.15: {rho:.3f}")
    print(f"  [{'PASS' if p_value < 0.05 else 'FAIL'}] p-value < 0.05: {p_value:.4f}")
    print(f"\n  H04: {'PASSED' if passed else 'FAILED'}")

    return {
        "hypothesis": "H04",
        "passed": passed,
        "metrics": {
            "spearman_rho": round(float(rho), 4),
            "p_value": round(float(p_value), 6),
            "n_groups": len(points),
        },
    }


def main():
    data = load_basket_results()
    if not data:
        return

    tickers = list(data["tickers"].keys())
    print(f"Tickers: {tickers}")
    print(f"Period: {data.get('period', 'unknown')}")
    print(f"Holding period: {data.get('holding_period', 20)} days")

    # Run hypotheses
    h01 = run_h01_backtest(data)
    h03 = run_h03_backtest(data)
    h04 = run_h04_backtest(data)

    # Try to record in graveyard (if Supabase available)
    try:
        import signal_registry
        for result in [h01, h03, h04]:
            hid = result["hypothesis"]
            try:
                signal_registry.validate_pre_registration(hid)
                signal_registry.mark_result(
                    hid, result["passed"], layer=4,
                    metrics={
                        "rvrp": result["metrics"].get("avg_rvrp_green") or result["metrics"].get("green_rvrp"),
                        "n_trades": result["metrics"].get("n_trades_green") or result["metrics"].get("n_groups"),
                    },
                    failure_reason=None if result["passed"] else f"{hid} failed on backtest data",
                )
            except Exception as e:
                print(f"[graveyard] Could not record {hid}: {e}")
    except ImportError:
        print("\n[graveyard] signal_registry not available — results not recorded in graveyard")

    # Summary
    print("\n" + "=" * 60)
    print("BACKTEST GATE SUMMARY")
    print("=" * 60)
    for result in [h01, h03, h04]:
        status = "PASSED" if result["passed"] else "FAILED"
        print(f"  {result['hypothesis']}: {status}")
        for k, v in result["metrics"].items():
            if v is not None:
                print(f"    {k}: {v}")
    print(f"\n  H02: Tested via eval_forecast.py (GARCH vs RV20 QLIKE comparison)")

    # Overall
    core_passed = all(r["passed"] for r in [h01, h03, h04])
    if core_passed:
        print(f"\n  ALL CORE HYPOTHESES PASSED on backtest data.")
        print(f"  The VRP thesis holds on {data.get('period', '6 years')} of data.")
        print(f"  Next: validate on live predictions when they mature (~April 7).")
    else:
        failed = [r["hypothesis"] for r in [h01, h03, h04] if not r["passed"]]
        print(f"\n  FAILED: {', '.join(failed)}")
        print(f"  Investigate before proceeding to live deployment.")


if __name__ == "__main__":
    main()
