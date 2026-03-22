"""
Run core hypotheses H01-H04 through the testing gate.

This is the moment of truth: do we have real edge by Realized VRP standards?

H01: VRP Predicts Seller Wins (core thesis)
H02: GARCH Beats Naive RV20 (forecast quality — tested separately via eval_forecast)
H03: Signal Discrimination (GREEN > YELLOW > RED)
H04: VRP Magnitude Proportional to Edge (higher VRP = higher RVRP)

Usage:
  python run_gate_h01_h04.py
  # Or via GitHub Actions with Supabase credentials
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import db
import signal_registry
import vrp_tracker
import testing_gate


def load_scored_predictions():
    """Load all scored predictions from Supabase/SQLite."""
    sb = db._get_supabase()
    if sb:
        resp = sb.table("predictions").select("*").eq("scored", 1).order("date").execute()
        data = resp.data or []
        return pd.DataFrame(data) if data else pd.DataFrame()
    else:
        conn = db._get_sqlite()
        df = pd.read_sql_query(
            "SELECT * FROM predictions WHERE scored = 1 ORDER BY date", conn
        )
        conn.close()
        return df


def run_h01(df):
    """H01: VRP Predicts Seller Wins — core thesis validation."""
    print("\n" + "=" * 60)
    print("H01: VRP Predicts Seller Wins")
    print("=" * 60)

    signal_registry.validate_pre_registration("H01")
    signal_registry.mark_testing("H01")

    # Run core VRP test
    result = vrp_tracker.core_vrp_test(df)
    print(f"\n{result.get('interpretation', 'No interpretation')}")

    if "error" in result:
        signal_registry.mark_result("H01", False, 4,
                                     failure_reason=result["error"])
        return result

    # Run through Layer 4 (standalone alpha)
    print("\nLayer 4 — Standalone Alpha Test:")
    r4 = testing_gate.run_layer_4(df)
    testing_gate.print_gate_results([r4])

    passed = result.get("passed_h01", False) and r4.get("passed", False)

    metrics = r4.get("metrics", {})
    signal_registry.mark_result(
        "H01", passed, 4 if passed else 4,
        metrics={"sharpe": metrics.get("sharpe"), "rvrp": metrics.get("avg_rvrp"),
                 "n_trades": metrics.get("n_trades")},
        failure_reason=None if passed else "Core VRP test or Layer 4 failed",
    )
    return result


def run_h03(df):
    """H03: Signal Discrimination — GREEN > YELLOW > RED."""
    print("\n" + "=" * 60)
    print("H03: Signal Discrimination (GREEN > YELLOW > RED)")
    print("=" * 60)

    signal_registry.validate_pre_registration("H03")
    signal_registry.mark_testing("H03")

    result = vrp_tracker.signal_discrimination_test(df)
    print(f"\n{result.get('interpretation', 'No interpretation')}")

    passed = result.get("passed_h03", False)

    # Also run Layer 4 per signal type
    for sig in ["GREEN", "YELLOW", "RED"]:
        sig_count = len(df[df["signal"] == sig])
        if sig_count >= 10:
            r4 = testing_gate.run_layer_4(df, signal_filter=sig, min_trades=10)
            print(f"\n  {sig} Layer 4:")
            testing_gate.print_gate_results([r4])

    by_sig = result.get("by_signal", {})
    green_rvrp = by_sig.get("GREEN", {}).get("avg")
    signal_registry.mark_result(
        "H03", passed, 4 if passed else 4,
        metrics={"rvrp": green_rvrp,
                 "n_trades": sum(v.get("count", 0) for v in by_sig.values())},
        failure_reason=None if passed else "Signal ordering not monotonic or insufficient spread",
    )
    return result


def run_h04(df):
    """H04: VRP Magnitude Proportional to Edge."""
    print("\n" + "=" * 60)
    print("H04: VRP Magnitude Proportional to Edge")
    print("=" * 60)

    signal_registry.validate_pre_registration("H04")
    signal_registry.mark_testing("H04")

    result = vrp_tracker.vrp_rvrp_correlation(df)
    print(f"\n{result.get('interpretation', 'No interpretation')}")

    if "error" in result:
        signal_registry.mark_result("H04", False, 4,
                                     failure_reason=result["error"])
        return result

    passed = result.get("passed_h04", False)

    # Also show the VRP-vs-RVRP curve
    curve = vrp_tracker.rvrp_vs_feature(df, "vrp")
    if not curve.empty:
        print("\nVRP Decile → Realized VRP:")
        for _, row in curve.iterrows():
            print(f"  VRP ~{row['bin_center']:.1f}: "
                  f"Avg RVRP={row['avg_rvrp']:.1%} "
                  f"(n={int(row['count'])}, {row['pct_positive']:.0f}% positive)")

    signal_registry.mark_result(
        "H04", passed, 4,
        metrics={"sharpe": result.get("spearman_rho"),
                 "n_trades": result.get("n")},
        failure_reason=None if passed else "VRP-RVRP correlation too weak",
    )
    return result


def main():
    print("Loading scored predictions...")
    df = load_scored_predictions()

    if df.empty:
        print("No scored predictions found. Run score_pending_predictions() first.")
        return

    print(f"Loaded {len(df)} scored predictions.")

    # Check for Realized VRP data
    has_rvrp = "clv_realized" in df.columns and df["clv_realized"].notna().any()
    rvrp_count = df["clv_realized"].notna().sum() if has_rvrp else 0
    print(f"Predictions with Realized VRP: {rvrp_count}")

    if rvrp_count < 10:
        print("\nWARNING: Very few predictions have Realized VRP data.")
        print("Run backfill_clv.py first, or wait for more predictions to be scored.")
        print("Testing with available data anyway (results will be preliminary)...\n")

    # Run H01
    h01 = run_h01(df)

    # H02 is tested via eval_forecast.py (GARCH vs RV20 QLIKE comparison)
    print("\n" + "=" * 60)
    print("H02: GARCH Beats Naive RV20")
    print("=" * 60)
    print("H02 is tested via eval_forecast.py (Module 1).")
    print("Run: python eval_forecast.py for Diebold-Mariano test results.")
    signal_registry.mark_testing("H02")

    # Run H03
    h03 = run_h03(df)

    # Run H04
    h04 = run_h04(df)

    # Final summary
    print("\n" + "=" * 60)
    print("GATE RESULTS SUMMARY")
    print("=" * 60)
    signal_registry.summary()


if __name__ == "__main__":
    main()
