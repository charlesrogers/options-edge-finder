"""
VRP Tracker — Realized VRP computation and analytics.

Realized VRP = (IV_entry - RV_holding) / IV_entry

This is the primary edge metric from Sinclair & Mack (2024):
- Average VRP: 3.55 vol points (SPY, one-month)
- Positive 82.39% of the time
- At low vol: ~19% of IV level
- At high vol: ~13% of IV level

Functions here support hypothesis testing (H01-H04+) and ongoing monitoring.
"""

import numpy as np
import pandas as pd
from scipy import stats


def compute_rvrp(iv_entry, rv_holding):
    """Compute Realized VRP = (IV_entry - RV) / IV_entry."""
    if iv_entry and rv_holding and iv_entry > 0:
        return (iv_entry - rv_holding) / iv_entry
    return None


def compute_rvrp_market(iv_entry, iv_at_scoring):
    """Compute market-based RVRP = (IV_entry - IV_scoring) / IV_entry."""
    if iv_entry and iv_at_scoring and iv_entry > 0:
        return (iv_entry - iv_at_scoring) / iv_entry
    return None


def rvrp_by_group(df, group_col, rvrp_col="clv_realized"):
    """
    Compute Realized VRP stats grouped by any column.

    Args:
        df: Predictions DataFrame (scored)
        group_col: Column to group by (e.g., 'signal', 'regime', 'ticker')
        rvrp_col: Column containing realized VRP values

    Returns:
        Dict of {group_value: {avg, median, count, pct_positive}}
    """
    result = {}
    if rvrp_col not in df.columns:
        return result
    for val in df[group_col].dropna().unique():
        subset = df[df[group_col] == val][rvrp_col].dropna()
        if len(subset) < 3:
            continue
        result[val] = {
            "avg": float(subset.mean()),
            "median": float(subset.median()),
            "std": float(subset.std()),
            "count": len(subset),
            "pct_positive": float((subset > 0).mean() * 100),
        }
    return result


def rolling_rvrp(df, window=30, rvrp_col="clv_realized"):
    """
    Compute rolling Realized VRP over a prediction-count window.

    Returns DataFrame with columns: [date, rolling_rvrp, count].
    """
    if rvrp_col not in df.columns:
        return pd.DataFrame()

    scored = df[df[rvrp_col].notna()].sort_values("date").copy()
    if len(scored) < window:
        return pd.DataFrame()

    scored["rolling_rvrp"] = scored[rvrp_col].rolling(window).mean()
    result = scored[scored["rolling_rvrp"].notna()][["date", "rolling_rvrp"]].copy()
    result["count"] = window
    return result


def rvrp_vs_feature(df, feature_col, rvrp_col="clv_realized", bins=10):
    """
    Compute Realized VRP as a function of any feature (for H04-H07).

    Bins the feature into deciles and computes average RVRP per bin.
    Use to find breakpoints and monotonic relationships.

    Args:
        df: Predictions DataFrame
        feature_col: Column to bin (e.g., 'vrp', 'iv_rank')
        rvrp_col: Column with realized VRP
        bins: Number of bins (default 10 = deciles)

    Returns:
        DataFrame with columns: [bin_center, avg_rvrp, count, pct_positive]
    """
    clean = df[[feature_col, rvrp_col]].dropna()
    if len(clean) < bins * 3:
        return pd.DataFrame()

    clean["bin"] = pd.qcut(clean[feature_col], q=bins, duplicates="drop")
    grouped = clean.groupby("bin", observed=True)[rvrp_col].agg(
        avg_rvrp="mean",
        median_rvrp="median",
        count="count",
        pct_positive=lambda x: (x > 0).mean() * 100,
    ).reset_index()

    # Extract bin centers for plotting
    grouped["bin_center"] = grouped["bin"].apply(lambda x: x.mid)
    return grouped.sort_values("bin_center")


def vrp_rvrp_correlation(df, vrp_col="vrp", rvrp_col="clv_realized"):
    """
    Test H04: Is VRP magnitude proportional to Realized VRP?

    Returns:
        Dict with spearman_rho, p_value, n, and pass/fail assessment.
    """
    clean = df[[vrp_col, rvrp_col]].dropna()
    if len(clean) < 30:
        return {"error": f"Insufficient data ({len(clean)} < 30)"}

    rho, p_value = stats.spearmanr(clean[vrp_col], clean[rvrp_col])

    # H04 pass thresholds
    passed = rho > 0.15 and p_value < 0.01

    return {
        "spearman_rho": float(rho),
        "p_value": float(p_value),
        "n": len(clean),
        "passed_h04": passed,
        "interpretation": (
            f"Spearman rho={rho:.3f} (p={p_value:.4f}, n={len(clean)}). "
            + ("VRP magnitude IS proportional to edge." if passed
               else "VRP magnitude is NOT clearly proportional to edge.")
        ),
    }


def signal_discrimination_test(df, rvrp_col="clv_realized"):
    """
    Test H03: Does GREEN RVRP > YELLOW RVRP > RED RVRP?

    Returns:
        Dict with per-signal stats, monotonic check, and pass/fail.
    """
    by_signal = rvrp_by_group(df, "signal", rvrp_col)

    green_avg = by_signal.get("GREEN", {}).get("avg")
    yellow_avg = by_signal.get("YELLOW", {}).get("avg")
    red_avg = by_signal.get("RED", {}).get("avg")

    # Check monotonic ordering
    monotonic = True
    if green_avg is not None and yellow_avg is not None:
        monotonic = monotonic and green_avg > yellow_avg
    if yellow_avg is not None and red_avg is not None:
        monotonic = monotonic and yellow_avg > red_avg
    if green_avg is not None and red_avg is not None:
        monotonic = monotonic and green_avg > red_avg

    # H03 pass thresholds
    spread = None
    if green_avg is not None and red_avg is not None:
        spread = green_avg - red_avg

    passed = (monotonic
              and green_avg is not None and green_avg > 0.02
              and spread is not None and spread > 0.015)

    # Count check
    counts_ok = all(
        by_signal.get(s, {}).get("count", 0) >= 100
        for s in ["GREEN", "YELLOW", "RED"]
        if s in by_signal
    )

    return {
        "by_signal": by_signal,
        "monotonic": monotonic,
        "green_red_spread": spread,
        "counts_sufficient": counts_ok,
        "passed_h03": passed and counts_ok,
        "interpretation": (
            f"GREEN={green_avg:.1%}, YELLOW={yellow_avg:.1%}, RED={red_avg:.1%}. "
            if all(x is not None for x in [green_avg, yellow_avg, red_avg])
            else "Insufficient signal types for full test. "
        ) + ("Monotonic ordering holds." if monotonic else "Ordering BROKEN."),
    }


def core_vrp_test(df, rvrp_col="clv_realized"):
    """
    Test H01: Does VRP predict seller wins? (Core thesis validation)

    Computes overall Realized VRP stats and checks against Sinclair benchmarks.

    Returns:
        Dict with stats and pass/fail assessment.
    """
    rvrp = df[rvrp_col].dropna()
    if len(rvrp) < 50:
        return {"error": f"Insufficient data ({len(rvrp)} < 50)"}

    # Annualized Sharpe approximation (assuming ~18 trades/year at 20-day holding)
    trades_per_year = 252 / 20  # ~12.6
    mean_rvrp = float(rvrp.mean())
    std_rvrp = float(rvrp.std())
    sharpe = (mean_rvrp / std_rvrp * np.sqrt(trades_per_year)) if std_rvrp > 0 else 0

    win_rate = float((df["seller_won"] == 1).mean()) if "seller_won" in df.columns else None
    pct_positive = float((rvrp > 0).mean() * 100)

    # H01 pass thresholds
    passed = (mean_rvrp > 0.015
              and (win_rate is None or win_rate > 0.55)
              and sharpe > 0.8
              and len(rvrp) >= 200)

    return {
        "avg_rvrp": mean_rvrp,
        "median_rvrp": float(rvrp.median()),
        "std_rvrp": std_rvrp,
        "pct_positive": pct_positive,
        "sharpe": sharpe,
        "win_rate": win_rate,
        "n_trades": len(rvrp),
        "skewness": float(rvrp.skew()),
        "kurtosis": float(rvrp.kurtosis()),
        "passed_h01": passed,
        "interpretation": (
            f"Avg Realized VRP={mean_rvrp:.1%}, positive {pct_positive:.0f}% of trades, "
            f"Sharpe={sharpe:.2f}, n={len(rvrp)}. "
            + (f"Sinclair benchmark: 82% positive for SPY. "
               f"{'ABOVE' if pct_positive > 82 else 'BELOW'} benchmark. "
               if pct_positive else "")
            + ("PASSED H01." if passed else "FAILED H01.")
        ),
    }
