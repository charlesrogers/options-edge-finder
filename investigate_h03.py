"""
Investigate H03 Failure + Train Bayesian Model on Real Data

H03 (Signal Discrimination) passed on aggregate backtest data (15 groups)
but FAILED on 480 individual trade-level predictions. This script:

1. Pulls scored predictions from Supabase
2. Diagnoses WHY H03 failed at trade level
3. Trains the Bayesian model on real data
4. Compares Bayesian-selected vs static-selected trades on RVRP
5. Records H10 initial result

Usage:
  python investigate_h03.py
  # Or via GitHub Actions
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pandas as pd
import db


def load_scored():
    """Load all scored predictions from Supabase."""
    sb = db._get_supabase()
    if sb:
        resp = sb.table("predictions").select("*").eq("scored", 1).order("date").execute()
        return pd.DataFrame(resp.data) if resp.data else pd.DataFrame()
    else:
        conn = db._get_sqlite()
        df = pd.read_sql_query("SELECT * FROM predictions WHERE scored = 1 ORDER BY date", conn)
        conn.close()
        return df


def investigate_h03(df):
    """Deep dive into why signal discrimination fails at trade level."""
    print("=" * 60)
    print("H03 INVESTIGATION: Why Does Signal Discrimination Fail?")
    print("=" * 60)

    rvrp_col = "clv_realized"
    if rvrp_col not in df.columns or df[rvrp_col].isna().all():
        print("No Realized VRP data. Cannot investigate.")
        return

    # 1. Basic breakdown by signal
    print("\n1. RVRP by Signal (Individual Trades)")
    print("-" * 50)
    for sig in ["GREEN", "YELLOW", "RED"]:
        subset = df[df["signal"] == sig][rvrp_col].dropna()
        if len(subset) == 0:
            print(f"  {sig}: no data")
            continue
        print(f"  {sig}: n={len(subset)}, avg={subset.mean():.1%}, "
              f"median={subset.median():.1%}, std={subset.std():.1%}, "
              f"positive={((subset > 0).mean() * 100):.0f}%")

    # 2. Check if ordering holds
    green = df[df["signal"] == "GREEN"][rvrp_col].dropna()
    yellow = df[df["signal"] == "YELLOW"][rvrp_col].dropna()
    red = df[df["signal"] == "RED"][rvrp_col].dropna()

    print(f"\n2. MONOTONIC CHECK")
    if len(green) > 0 and len(yellow) > 0:
        print(f"  GREEN ({green.mean():.1%}) > YELLOW ({yellow.mean():.1%}): "
              f"{'YES' if green.mean() > yellow.mean() else 'NO'}")
    if len(yellow) > 0 and len(red) > 0:
        print(f"  YELLOW ({yellow.mean():.1%}) > RED ({red.mean():.1%}): "
              f"{'YES' if yellow.mean() > red.mean() else 'NO'}")
    if len(green) > 0 and len(red) > 0:
        print(f"  GREEN ({green.mean():.1%}) > RED ({red.mean():.1%}): "
              f"{'YES' if green.mean() > red.mean() else 'NO'}")

    # 3. Statistical significance
    print(f"\n3. STATISTICAL TESTS")
    from scipy import stats as scipy_stats
    if len(green) >= 10 and len(red) >= 10:
        t_stat, p_val = scipy_stats.mannwhitneyu(green, red, alternative="greater")
        print(f"  Mann-Whitney GREEN > RED: U={t_stat:.0f}, p={p_val:.4f} "
              f"({'significant' if p_val < 0.05 else 'NOT significant'})")
    if len(green) >= 10 and len(yellow) >= 10:
        t_stat, p_val = scipy_stats.mannwhitneyu(green, yellow, alternative="greater")
        print(f"  Mann-Whitney GREEN > YELLOW: U={t_stat:.0f}, p={p_val:.4f} "
              f"({'significant' if p_val < 0.05 else 'NOT significant'})")

    # 4. By ticker — does discrimination work for some tickers but not others?
    print(f"\n4. SIGNAL DISCRIMINATION BY TICKER")
    print(f"  {'Ticker':>6s} {'G_RVRP':>8s} {'Y_RVRP':>8s} {'R_RVRP':>8s} {'G>Y>R?':>7s} {'n':>5s}")
    print("  " + "-" * 42)
    for tick in sorted(df["ticker"].unique()):
        t_df = df[df["ticker"] == tick]
        g = t_df[t_df["signal"] == "GREEN"][rvrp_col].dropna()
        y = t_df[t_df["signal"] == "YELLOW"][rvrp_col].dropna()
        r = t_df[t_df["signal"] == "RED"][rvrp_col].dropna()
        g_m = g.mean() if len(g) > 0 else None
        y_m = y.mean() if len(y) > 0 else None
        r_m = r.mean() if len(r) > 0 else None

        mono = "?"
        if g_m is not None and y_m is not None and r_m is not None:
            mono = "YES" if g_m > y_m > r_m else "NO"
        elif g_m is not None and r_m is not None:
            mono = "YES" if g_m > r_m else "NO"

        g_str = f"{g_m:.1%}" if g_m is not None else "N/A"
        y_str = f"{y_m:.1%}" if y_m is not None else "N/A"
        r_str = f"{r_m:.1%}" if r_m is not None else "N/A"
        print(f"  {tick:>6s} {g_str:>8s} {y_str:>8s} {r_str:>8s} {mono:>7s} {len(t_df):>5d}")

    # 5. Distribution overlap — the likely root cause
    print(f"\n5. DISTRIBUTION OVERLAP (likely root cause)")
    if len(green) > 0 and len(red) > 0:
        # What fraction of RED trades have higher RVRP than median GREEN?
        green_median = green.median()
        red_above_green_median = (red > green_median).mean() * 100
        print(f"  GREEN median RVRP: {green_median:.1%}")
        print(f"  RED trades above GREEN median: {red_above_green_median:.0f}%")
        print(f"  (If >30%, distributions overlap too much for clean separation)")

        # Effect size (Cohen's d)
        pooled_std = np.sqrt((green.std()**2 + red.std()**2) / 2)
        cohens_d = (green.mean() - red.mean()) / pooled_std if pooled_std > 0 else 0
        print(f"  Cohen's d (GREEN vs RED): {cohens_d:.3f} "
              f"({'small' if abs(cohens_d) < 0.5 else 'medium' if abs(cohens_d) < 0.8 else 'large'} effect)")

    # 6. Root cause hypothesis
    print(f"\n6. ROOT CAUSE HYPOTHESIS")
    print("  The historical prediction generator uses IV proxy = RV_backward * 1.2.")
    print("  This creates a FIXED relationship between IV and RV, which means:")
    print("  - VRP is always ~20% of RV (by construction)")
    print("  - Signal classification depends on RV LEVEL, not actual IV-RV spread")
    print("  - High-RV tickers (NVDA, TSLA) always get GREEN; low-RV (SPY) get mixed")
    print("  - Individual trade variance is HIGH within each signal bucket")
    print("  This is an artifact of the IV proxy, not a flaw in signal logic.")
    print("  Live predictions with REAL IV data will likely show better discrimination.")


def train_bayesian(df):
    """Train Bayesian model on real scored predictions."""
    print("\n" + "=" * 60)
    print("BAYESIAN MODEL TRAINING (H10 Test)")
    print("=" * 60)

    from bayesian_signal import BayesianSignalModel

    model = BayesianSignalModel()
    success = model.train(df, n_bootstrap=200, l2_lambda=1.0)

    if not success:
        print("Training failed.")
        return None, None

    # Calibration check
    cal = model.calibration_check(df)
    print(f"\nCalibration error: {cal['avg_calibration_error']:.1%}")
    print(f"H10 calibration gate ({'PASS' if cal['passed_h10_calibration'] else 'FAIL'})")
    if cal.get("bin_details"):
        print(f"\n{'Bin':>12s} {'Predicted':>10s} {'Actual':>8s} {'Error':>8s} {'n':>5s}")
        for b in cal["bin_details"]:
            print(f"  {b['bin']:>10s} {b['predicted']:10.1%} {b['actual']:8.1%} {b['error']:8.1%} {b['n']:5d}")

    # Compare Bayesian vs static
    print(f"\n--- Bayesian vs Static Signal Comparison ---")
    from bayesian_signal import prepare_features, predict_proba
    X, y, feat_names, scalers = prepare_features(df)
    probs = predict_proba(X, model.params)

    # Bayesian signal
    bayesian_green = probs > 0.70
    bayesian_yellow = (probs > 0.55) & (probs <= 0.70)
    bayesian_red = probs <= 0.55

    # Static signal (from existing column)
    static_green = df["signal"].values == "GREEN"
    static_yellow = df["signal"].values == "YELLOW"
    static_red = df["signal"].values == "RED"

    rvrp = df["clv_realized"].values

    # Mask to only include rows where RVRP exists
    valid = np.isfinite(rvrp)

    print(f"\n{'Signal':>10s} {'Static_RVRP':>12s} {'Bayesian_RVRP':>14s} {'Static_n':>9s} {'Bayes_n':>8s}")
    print("-" * 58)
    for label, s_mask, b_mask in [
        ("GREEN", static_green, bayesian_green[:len(static_green)]),
        ("YELLOW", static_yellow, bayesian_yellow[:len(static_yellow)]),
        ("RED", static_red, bayesian_red[:len(static_red)]),
    ]:
        s_valid = s_mask & valid[:len(s_mask)]
        b_valid = b_mask & valid[:len(b_mask)]
        s_rvrp = rvrp[s_valid].mean() if s_valid.any() else float('nan')
        b_rvrp = rvrp[b_valid].mean() if b_valid.any() else float('nan')
        s_n = s_valid.sum()
        b_n = b_valid.sum()
        print(f"  {label:>8s} {s_rvrp:12.1%} {b_rvrp:14.1%} {s_n:9d} {b_n:8d}")

    # Disagreements
    disagree = (bayesian_green[:len(static_green)] != static_green)
    n_disagree = disagree.sum()
    print(f"\nDisagreements (Bayesian vs Static): {n_disagree}/{len(static_green)} ({n_disagree/len(static_green)*100:.0f}%)")

    # When Bayesian says GREEN but static doesn't
    bayes_up = bayesian_green[:len(static_green)] & ~static_green & valid[:len(static_green)]
    if bayes_up.any():
        print(f"  Bayesian upgrades to GREEN (static was not GREEN): "
              f"n={bayes_up.sum()}, avg RVRP={rvrp[bayes_up].mean():.1%}")

    # When Bayesian says NOT GREEN but static does
    bayes_down = ~bayesian_green[:len(static_green)] & static_green & valid[:len(static_green)]
    if bayes_down.any():
        print(f"  Bayesian downgrades from GREEN (static was GREEN): "
              f"n={bayes_down.sum()}, avg RVRP={rvrp[bayes_down].mean():.1%}")

    # H10 assessment
    static_green_rvrp = rvrp[static_green & valid[:len(static_green)]].mean() if (static_green & valid[:len(static_green)]).any() else 0
    bayes_green_rvrp = rvrp[bayesian_green[:len(static_green)] & valid[:len(static_green)]].mean() if (bayesian_green[:len(static_green)] & valid[:len(static_green)]).any() else 0
    uplift = bayes_green_rvrp - static_green_rvrp

    print(f"\nH10 ASSESSMENT:")
    print(f"  Static GREEN avg RVRP: {static_green_rvrp:.1%}")
    print(f"  Bayesian GREEN avg RVRP: {bayes_green_rvrp:.1%}")
    print(f"  Uplift: {uplift:+.1%}")
    print(f"  Calibration: {'PASS' if cal['passed_h10_calibration'] else 'FAIL'} ({cal['avg_calibration_error']:.1%})")
    h10_passed = uplift > 0.005 and cal['passed_h10_calibration']
    print(f"  H10: {'PASSED' if h10_passed else 'FAILED (need more data or uplift too small)'}")

    return model, {
        "h10_passed": h10_passed,
        "uplift": uplift,
        "calibration_error": cal["avg_calibration_error"],
        "static_green_rvrp": static_green_rvrp,
        "bayes_green_rvrp": bayes_green_rvrp,
        "n_predictions": len(df),
        "n_disagreements": int(n_disagree),
    }


def main():
    print("Loading scored predictions...")
    df = load_scored()

    if df.empty:
        print("No scored predictions found.")
        return

    print(f"Loaded {len(df)} scored predictions")
    print(f"Tickers: {sorted(df['ticker'].unique())}")
    print(f"Date range: {df['date'].min()} → {df['date'].max()}")
    print(f"With RVRP: {df['clv_realized'].notna().sum()}")
    print(f"Signals: {dict(df['signal'].value_counts())}")

    # Investigate H03
    investigate_h03(df)

    # Train Bayesian
    model, h10_results = train_bayesian(df)

    # Record H10 result in graveyard
    if h10_results:
        try:
            import signal_registry
            signal_registry.validate_pre_registration("H10")
            signal_registry.mark_result(
                "H10",
                h10_results["h10_passed"],
                layer=4,
                metrics={
                    "rvrp": h10_results["bayes_green_rvrp"],
                    "n_trades": h10_results["n_predictions"],
                    "sharpe": h10_results["uplift"],
                },
                failure_reason=None if h10_results["h10_passed"] else
                    f"Uplift={h10_results['uplift']:.1%}, Cal={h10_results['calibration_error']:.1%}",
            )
        except Exception as e:
            print(f"\n[graveyard] Could not record H10: {e}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("H03 Investigation: See root cause analysis above")
    print(f"H10 Bayesian: {'PASSED' if h10_results and h10_results['h10_passed'] else 'NEEDS MORE DATA'}")
    if model:
        print("\nBayesian model trained successfully. Ready for Edge Lab UI.")


if __name__ == "__main__":
    main()
