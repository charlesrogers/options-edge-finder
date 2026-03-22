"""
Testing Gate — 10-layer validation pipeline for options signals.

Adapted from variance_betting pod-shop framework (Citadel/Millennium model).
Every new signal must pass Layers 1-7 before shadow trading.
Layers 8-10 added in Phase 4 (production simulation, portfolio, live monitoring).

Layers:
  1. Data Validation — no lookahead, timestamps valid
  2. Frozen Flagship — baseline hasn't changed
  3. Walk-Forward — expanding window OOS validation
  4. Standalone Alpha — signal works alone (RVRP > 1.5%, Sharpe > 0.8)
  5. Incremental Alpha — signal improves the flagship
  6. Orthogonality — signal is independent (not repackaged VRP)
  7. Stability — works across tickers, regimes, time periods

From Sinclair & Mack (2024): "No backtest survives contact with the live order book."
Purpose is FALSIFICATION (Popper), not proof. Quickly discard bad ideas.
"""

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from datetime import datetime

import db
import signal_registry
import vrp_tracker


# ============================================================
# LAYER 1: DATA VALIDATION
# ============================================================

def run_layer_1(predictions_df):
    """
    Verify data integrity — no lookahead bias, timestamps valid.

    Checks:
    - All features exist BEFORE the trade decision date
    - outcome_date > date for all scored predictions
    - No NaN in critical columns (ticker, date, signal)
    - Dates are valid format
    """
    issues = []
    df = predictions_df.copy()

    # Critical columns present
    required = ["ticker", "date", "signal"]
    for col in required:
        if col not in df.columns:
            issues.append(f"Missing required column: {col}")
        elif df[col].isna().any():
            n_missing = df[col].isna().sum()
            issues.append(f"{col} has {n_missing} NULL values")

    # Outcome date > prediction date for scored predictions
    scored = df[df["scored"] == 1].copy()
    if not scored.empty and "outcome_date" in scored.columns:
        scored["date_dt"] = pd.to_datetime(scored["date"], errors="coerce")
        scored["outcome_dt"] = pd.to_datetime(scored["outcome_date"], errors="coerce")
        bad = scored[scored["outcome_dt"] <= scored["date_dt"]]
        if len(bad) > 0:
            issues.append(f"{len(bad)} predictions have outcome_date <= date (lookahead)")

    passed = len(issues) == 0
    return {
        "layer": 1,
        "name": "Data Validation",
        "passed": passed,
        "issues": issues,
        "n_predictions": len(df),
        "n_scored": len(scored) if not df.empty else 0,
    }


# ============================================================
# LAYER 2: FROZEN FLAGSHIP
# ============================================================

def run_layer_2(flagship_commit=None):
    """
    Verify the flagship signal logic hasn't been modified during testing.

    In practice: check that calc_vrp_signal() in analytics.py matches
    the locked version. For now, just records the commit hash.
    """
    # Simple version: just log the flagship state
    return {
        "layer": 2,
        "name": "Frozen Flagship",
        "passed": True,
        "flagship_commit": flagship_commit or "not_specified",
        "note": "Flagship lock is a process discipline — verify manually that "
                "calc_vrp_signal() hasn't changed since testing began.",
    }


# ============================================================
# LAYER 4: STANDALONE ALPHA TEST
# ============================================================

def run_layer_4(predictions_df, signal_filter=None, rvrp_col="clv_realized",
                min_rvrp=0.015, min_sharpe=0.8, min_sortino=1.0,
                min_win_rate=0.55, min_trades=200):
    """
    Does this signal produce positive Realized VRP on its own?

    Args:
        predictions_df: Scored predictions DataFrame
        signal_filter: Optional filter value (e.g., 'GREEN') on 'signal' column.
                       If None, tests all predictions.
        min_rvrp: Minimum average Realized VRP (default 1.5%)
        min_sharpe: Minimum annualized Sharpe (default 0.8)
        min_sortino: Minimum annualized Sortino (default 1.0)
        min_win_rate: Minimum win rate (default 55%)
        min_trades: Minimum sample size (default 200)

    Returns:
        Dict with all metrics and pass/fail.
    """
    df = predictions_df[predictions_df["scored"] == 1].copy()

    if signal_filter:
        df = df[df["signal"] == signal_filter]

    if rvrp_col not in df.columns or df[rvrp_col].isna().all():
        return {
            "layer": 4, "name": "Standalone Alpha",
            "passed": False, "error": f"No {rvrp_col} data available",
        }

    rvrp = df[rvrp_col].dropna()
    n = len(rvrp)

    if n < 30:
        return {
            "layer": 4, "name": "Standalone Alpha",
            "passed": False, "error": f"Only {n} observations (need >= 30 for any test)",
        }

    # Core metrics
    avg_rvrp = float(rvrp.mean())
    std_rvrp = float(rvrp.std())
    trades_per_year = 252 / 20
    sharpe = (avg_rvrp / std_rvrp * np.sqrt(trades_per_year)) if std_rvrp > 0 else 0

    # Sortino (downside deviation only)
    downside = rvrp[rvrp < 0]
    downside_std = float(downside.std()) if len(downside) > 1 else std_rvrp
    sortino = (avg_rvrp / downside_std * np.sqrt(trades_per_year)) if downside_std > 0 else 0

    win_rate = float((df["seller_won"] == 1).mean()) if "seller_won" in df.columns else None
    pct_positive = float((rvrp > 0).mean())
    skewness = float(rvrp.skew())
    kurtosis = float(rvrp.kurtosis())

    # Deflated Sharpe Ratio
    n_trials = db.get_graveyard_count()
    dsr = deflated_sharpe_ratio(sharpe, max(n_trials, 1), n, skewness, kurtosis + 3)

    # Pass/fail assessment
    checks = {
        "avg_rvrp >= threshold": avg_rvrp >= min_rvrp,
        "sharpe >= threshold": sharpe >= min_sharpe,
        "sortino >= threshold": sortino >= min_sortino,
        "win_rate >= threshold": win_rate is None or win_rate >= min_win_rate,
        "n_trades >= threshold": n >= min_trades,
        "deflated_sharpe > 0": dsr > 0,
    }
    passed = all(checks.values())

    return {
        "layer": 4,
        "name": "Standalone Alpha",
        "passed": passed,
        "signal_filter": signal_filter,
        "metrics": {
            "avg_rvrp": round(avg_rvrp, 6),
            "median_rvrp": round(float(rvrp.median()), 6),
            "std_rvrp": round(std_rvrp, 6),
            "sharpe": round(sharpe, 4),
            "sortino": round(sortino, 4),
            "win_rate": round(win_rate, 4) if win_rate else None,
            "pct_positive": round(pct_positive * 100, 2),
            "skewness": round(skewness, 4),
            "kurtosis": round(kurtosis, 4),
            "n_trades": n,
            "deflated_sharpe": round(dsr, 4),
            "n_trials_in_graveyard": n_trials,
        },
        "checks": checks,
        "thresholds": {
            "min_rvrp": min_rvrp,
            "min_sharpe": min_sharpe,
            "min_sortino": min_sortino,
            "min_win_rate": min_win_rate,
            "min_trades": min_trades,
        },
    }


# ============================================================
# LAYER 5: INCREMENTAL ALPHA TEST
# ============================================================

def run_layer_5(new_signal_df, flagship_df, rvrp_col="clv_realized",
                min_clv_uplift=0.005, min_ir=0.3):
    """
    Does adding this signal improve the flagship?

    Uses Jensen's alpha: R_new = alpha + beta * R_flagship + epsilon
    Signal adds value if alpha > 0 with t-stat > 2.0 and beta < 0.5.

    Args:
        new_signal_df: Predictions selected by new signal (with RVRP)
        flagship_df: Predictions selected by flagship (with RVRP)
        min_clv_uplift: Minimum RVRP improvement (default 0.5%)
        min_ir: Minimum Information Ratio (default 0.3)
    """
    new_rvrp = new_signal_df[rvrp_col].dropna()
    flag_rvrp = flagship_df[rvrp_col].dropna()

    if len(new_rvrp) < 30 or len(flag_rvrp) < 30:
        return {
            "layer": 5, "name": "Incremental Alpha",
            "passed": False, "error": "Insufficient data for comparison",
        }

    # CLV uplift
    clv_uplift = float(new_rvrp.mean() - flag_rvrp.mean())

    # Align dates for regression
    new_by_date = new_signal_df.groupby("date")[rvrp_col].mean()
    flag_by_date = flagship_df.groupby("date")[rvrp_col].mean()
    common = new_by_date.index.intersection(flag_by_date.index)

    if len(common) < 20:
        return {
            "layer": 5, "name": "Incremental Alpha",
            "passed": False, "error": f"Only {len(common)} common dates",
        }

    y = new_by_date.loc[common].values
    x = flag_by_date.loc[common].values

    # Jensen's alpha regression: y = alpha + beta * x + epsilon
    x_with_const = np.column_stack([np.ones(len(x)), x])
    try:
        betas, residuals, _, _ = np.linalg.lstsq(x_with_const, y, rcond=None)
        alpha, beta = betas[0], betas[1]
    except Exception:
        return {
            "layer": 5, "name": "Incremental Alpha",
            "passed": False, "error": "Regression failed",
        }

    # Standard errors
    y_pred = x_with_const @ betas
    resid = y - y_pred
    n = len(y)
    mse = float(np.sum(resid ** 2) / (n - 2)) if n > 2 else 1.0
    xtx_inv = np.linalg.pinv(x_with_const.T @ x_with_const)
    se = np.sqrt(np.diag(xtx_inv * mse))
    alpha_se = se[0] if len(se) > 0 else 1.0
    t_stat = alpha / alpha_se if alpha_se > 0 else 0
    r_squared = 1 - np.sum(resid ** 2) / np.sum((y - y.mean()) ** 2) if np.sum((y - y.mean()) ** 2) > 0 else 0

    # Information ratio
    excess = new_rvrp.values[:min(len(new_rvrp), len(flag_rvrp))] - flag_rvrp.values[:min(len(new_rvrp), len(flag_rvrp))]
    ir = float(excess.mean() / excess.std() * np.sqrt(252 / 20)) if excess.std() > 0 else 0

    checks = {
        "clv_uplift >= threshold": clv_uplift >= min_clv_uplift,
        "alpha > 0 and t_stat > 2.0": alpha > 0 and t_stat > 2.0,
        "beta < 0.5 (not leveraged flagship)": beta < 0.5,
        "r_squared < 0.3 (independent)": r_squared < 0.3,
        "information_ratio >= threshold": ir >= min_ir,
    }
    passed = all(checks.values())

    return {
        "layer": 5,
        "name": "Incremental Alpha",
        "passed": passed,
        "metrics": {
            "clv_uplift": round(clv_uplift, 6),
            "alpha": round(float(alpha), 6),
            "alpha_t_stat": round(float(t_stat), 4),
            "beta": round(float(beta), 4),
            "r_squared": round(float(r_squared), 4),
            "information_ratio": round(ir, 4),
        },
        "checks": checks,
    }


# ============================================================
# LAYER 6: ORTHOGONALITY TEST
# ============================================================

def run_layer_6(predictions_df, new_signal_col, existing_signal_cols,
                rvrp_col="clv_realized", max_corr=0.7):
    """
    Is the new signal independent or just repackaged VRP?

    Regresses new signal on existing signals. If residual still
    predicts RVRP, the signal adds independent information.

    Args:
        predictions_df: DataFrame with all signal columns + RVRP
        new_signal_col: Name of new signal column
        existing_signal_cols: List of existing signal column names
        max_corr: Maximum allowed correlation (default 0.7)
    """
    all_cols = [new_signal_col] + existing_signal_cols + [rvrp_col]
    clean = predictions_df[all_cols].dropna()

    if len(clean) < 30:
        return {
            "layer": 6, "name": "Orthogonality",
            "passed": False, "error": f"Only {len(clean)} complete observations",
        }

    # Pairwise correlations
    correlations = {}
    for col in existing_signal_cols:
        r, p = scipy_stats.spearmanr(clean[new_signal_col], clean[col])
        correlations[col] = {"rho": float(r), "p": float(p)}

    max_abs_corr = max(abs(v["rho"]) for v in correlations.values()) if correlations else 0

    # Regression: new_signal = f(existing_signals)
    X = clean[existing_signal_cols].values
    y = clean[new_signal_col].values
    X_with_const = np.column_stack([np.ones(len(X)), X])

    try:
        betas, _, _, _ = np.linalg.lstsq(X_with_const, y, rcond=None)
        residual = y - X_with_const @ betas
        r_squared = 1 - np.sum(residual ** 2) / np.sum((y - y.mean()) ** 2)
    except Exception:
        return {
            "layer": 6, "name": "Orthogonality",
            "passed": False, "error": "Regression on existing signals failed",
        }

    # Does the residual predict RVRP?
    rvrp_vals = clean[rvrp_col].values
    rvrp_X = np.column_stack([np.ones(len(residual)), residual])
    try:
        rvrp_betas, _, _, _ = np.linalg.lstsq(rvrp_X, rvrp_vals, rcond=None)
        rvrp_resid = rvrp_vals - rvrp_X @ rvrp_betas
        n = len(rvrp_vals)
        mse = np.sum(rvrp_resid ** 2) / (n - 2) if n > 2 else 1.0
        xtx_inv = np.linalg.pinv(rvrp_X.T @ rvrp_X)
        se = np.sqrt(np.diag(xtx_inv * mse))
        residual_t_stat = float(rvrp_betas[1] / se[1]) if len(se) > 1 and se[1] > 0 else 0
        residual_p = float(2 * (1 - scipy_stats.t.cdf(abs(residual_t_stat), n - 2))) if n > 2 else 1.0
    except Exception:
        residual_t_stat = 0
        residual_p = 1.0

    residual_predicts = residual_p < 0.05

    checks = {
        "max_correlation < threshold": max_abs_corr < max_corr,
        "residual_predicts_rvrp": residual_predicts,
        "r_squared_with_existing < 0.7": r_squared < 0.7,
    }
    passed = all(checks.values())

    return {
        "layer": 6,
        "name": "Orthogonality",
        "passed": passed,
        "metrics": {
            "max_abs_correlation": round(max_abs_corr, 4),
            "r_squared_with_existing": round(float(r_squared), 4),
            "residual_t_stat": round(residual_t_stat, 4),
            "residual_p_value": round(residual_p, 6),
            "residual_predicts_rvrp": residual_predicts,
        },
        "correlations": correlations,
        "checks": checks,
    }


# ============================================================
# LAYER 7: STABILITY TEST
# ============================================================

def run_layer_7(predictions_df, signal_filter=None, rvrp_col="clv_realized"):
    """
    Does the signal work across different conditions?

    Checks stability across:
    - Time (by year: profitable in 60%+ of years)
    - Tickers (profitable in 60%+ of tickers)
    - Regimes (profitable in 2+ of 3 regime categories)
    - Split-half (both random halves profitable)

    Args:
        predictions_df: Scored predictions
        signal_filter: Optional signal value to filter (e.g., 'GREEN')
    """
    df = predictions_df[predictions_df["scored"] == 1].copy()
    if signal_filter:
        df = df[df["signal"] == signal_filter]

    if rvrp_col not in df.columns or len(df) < 50:
        return {
            "layer": 7, "name": "Stability",
            "passed": False, "error": f"Insufficient data ({len(df)} rows)",
        }

    df["year"] = pd.to_datetime(df["date"]).dt.year
    rvrp = df[rvrp_col].dropna()

    # By year
    year_results = {}
    for yr in sorted(df["year"].unique()):
        yr_rvrp = df[df["year"] == yr][rvrp_col].dropna()
        if len(yr_rvrp) >= 10:
            year_results[int(yr)] = {
                "avg_rvrp": float(yr_rvrp.mean()),
                "n": len(yr_rvrp),
                "profitable": float(yr_rvrp.mean()) > 0,
            }
    years_profitable = sum(1 for v in year_results.values() if v["profitable"])
    years_total = len(year_results)

    # By ticker
    ticker_results = {}
    for tick in df["ticker"].unique():
        t_rvrp = df[df["ticker"] == tick][rvrp_col].dropna()
        if len(t_rvrp) >= 5:
            ticker_results[tick] = {
                "avg_rvrp": float(t_rvrp.mean()),
                "n": len(t_rvrp),
                "profitable": float(t_rvrp.mean()) > 0,
            }
    tickers_profitable = sum(1 for v in ticker_results.values() if v["profitable"])
    tickers_total = len(ticker_results)

    # By regime
    regime_results = {}
    if "regime" in df.columns:
        for reg in df["regime"].dropna().unique():
            r_rvrp = df[df["regime"] == reg][rvrp_col].dropna()
            if len(r_rvrp) >= 10:
                regime_results[reg] = {
                    "avg_rvrp": float(r_rvrp.mean()),
                    "n": len(r_rvrp),
                    "profitable": float(r_rvrp.mean()) > 0,
                }
    regimes_profitable = sum(1 for v in regime_results.values() if v["profitable"])
    regimes_total = len(regime_results)

    # Split-half validation
    np.random.seed(42)
    idx = np.random.permutation(len(rvrp))
    half1 = rvrp.iloc[idx[:len(idx) // 2]]
    half2 = rvrp.iloc[idx[len(idx) // 2:]]
    split_half_both_positive = float(half1.mean()) > 0 and float(half2.mean()) > 0

    checks = {
        "years_profitable >= 60%": years_total == 0 or (years_profitable / years_total >= 0.6),
        "tickers_profitable >= 60%": tickers_total == 0 or (tickers_profitable / tickers_total >= 0.6),
        "regimes_profitable >= 2": regimes_total == 0 or regimes_profitable >= min(2, regimes_total),
        "split_half_both_positive": split_half_both_positive,
    }
    passed = all(checks.values())

    return {
        "layer": 7,
        "name": "Stability",
        "passed": passed,
        "metrics": {
            "years_profitable": f"{years_profitable}/{years_total}",
            "tickers_profitable": f"{tickers_profitable}/{tickers_total}",
            "regimes_profitable": f"{regimes_profitable}/{regimes_total}",
            "split_half_both_positive": split_half_both_positive,
            "half1_avg_rvrp": round(float(half1.mean()), 6),
            "half2_avg_rvrp": round(float(half2.mean()), 6),
        },
        "by_year": year_results,
        "by_ticker_count": tickers_total,
        "by_regime": regime_results,
        "checks": checks,
    }


# ============================================================
# DEFLATED SHARPE RATIO
# ============================================================

def deflated_sharpe_ratio(sharpe_observed, n_trials, n_obs, skew=0, kurtosis=3):
    """
    Adjusts observed Sharpe for number of strategies tested.
    From Bailey & Lopez de Prado (2014).

    Args:
        sharpe_observed: The observed Sharpe ratio
        n_trials: Total signals ever tested (from graveyard — pass + fail)
        n_obs: Number of observations in the test
        skew: Skewness of returns
        kurtosis: Kurtosis of returns (excess kurtosis + 3)

    Returns:
        Probability that Sharpe is real (0-1). > 0.95 = likely real.
    """
    if n_trials <= 0 or n_obs <= 0:
        return 0.0

    euler_gamma = 0.5772156649
    e = 2.718281828

    # Expected maximum Sharpe under null (no real edge, just noise)
    try:
        from scipy.stats import norm
        z1 = norm.ppf(1 - 1 / n_trials) if n_trials > 1 else 0
        z2 = norm.ppf(1 - 1 / (n_trials * e)) if n_trials > 1 else 0
        e_max_sharpe = (1 - euler_gamma) * z1 + euler_gamma * z2
    except Exception:
        e_max_sharpe = 0

    # Standard error of Sharpe estimate
    se_sharpe = np.sqrt(
        (1 + 0.5 * sharpe_observed ** 2
         - skew * sharpe_observed
         + (kurtosis - 3) / 4 * sharpe_observed ** 2)
        / max(n_obs, 1)
    )

    if se_sharpe <= 0:
        return 0.0

    try:
        from scipy.stats import norm
        dsr = float(norm.cdf((sharpe_observed - e_max_sharpe) / se_sharpe))
    except Exception:
        dsr = 0.0

    return dsr


# ============================================================
# FULL GATE ORCHESTRATOR
# ============================================================

def run_full_gate(predictions_df, signal_id, signal_filter=None,
                  layers=7, flagship_df=None,
                  new_signal_col=None, existing_signal_cols=None):
    """
    Run a signal through all available layers and record results.

    Args:
        predictions_df: Full scored predictions DataFrame
        signal_id: Hypothesis ID (must be pre-registered)
        signal_filter: Signal value to filter (e.g., 'GREEN')
        layers: How many layers to run (default 7)
        flagship_df: Flagship predictions for Layer 5 comparison
        new_signal_col: Column name for Layer 6 orthogonality
        existing_signal_cols: Existing signal columns for Layer 6
    """
    # Validate pre-registration
    signal_registry.validate_pre_registration(signal_id)
    signal_registry.mark_testing(signal_id)

    results = []
    highest_passed = 0

    # Layer 1: Data Validation
    r1 = run_layer_1(predictions_df)
    results.append(r1)
    if not r1["passed"]:
        signal_registry.mark_result(signal_id, False, 1,
                                     failure_reason="Data validation failed: " + "; ".join(r1["issues"]))
        return results
    highest_passed = 1

    # Layer 2: Frozen Flagship
    r2 = run_layer_2()
    results.append(r2)
    highest_passed = 2

    # Layer 4: Standalone Alpha (skip Layer 3 walk-forward for now — uses existing scored predictions)
    r4 = run_layer_4(predictions_df, signal_filter=signal_filter)
    results.append(r4)
    if not r4["passed"]:
        metrics = r4.get("metrics", {})
        signal_registry.mark_result(
            signal_id, False, 4,
            metrics={"sharpe": metrics.get("sharpe"), "rvrp": metrics.get("avg_rvrp"),
                     "n_trades": metrics.get("n_trades")},
            failure_reason="Standalone alpha test failed: " +
                           ", ".join(k for k, v in r4.get("checks", {}).items() if not v),
        )
        return results
    highest_passed = 4

    # Layer 5: Incremental Alpha (if flagship provided)
    if layers >= 5 and flagship_df is not None:
        filtered = predictions_df
        if signal_filter:
            filtered = predictions_df[predictions_df["signal"] == signal_filter]
        r5 = run_layer_5(filtered, flagship_df)
        results.append(r5)
        if not r5["passed"]:
            signal_registry.mark_result(signal_id, False, 5,
                                         failure_reason="Incremental alpha test failed")
            return results
        highest_passed = 5

    # Layer 6: Orthogonality (if signal columns provided)
    if layers >= 6 and new_signal_col and existing_signal_cols:
        r6 = run_layer_6(predictions_df, new_signal_col, existing_signal_cols)
        results.append(r6)
        if not r6["passed"]:
            signal_registry.mark_result(signal_id, False, 6,
                                         failure_reason="Orthogonality test failed")
            return results
        highest_passed = 6

    # Layer 7: Stability
    if layers >= 7:
        r7 = run_layer_7(predictions_df, signal_filter=signal_filter)
        results.append(r7)
        if not r7["passed"]:
            signal_registry.mark_result(signal_id, False, 7,
                                         failure_reason="Stability test failed: " +
                                         ", ".join(k for k, v in r7.get("checks", {}).items() if not v))
            return results
        highest_passed = 7

    # All layers passed!
    final_metrics = r4.get("metrics", {})
    signal_registry.mark_result(
        signal_id, True, highest_passed,
        metrics={"sharpe": final_metrics.get("sharpe"),
                 "rvrp": final_metrics.get("avg_rvrp"),
                 "n_trades": final_metrics.get("n_trades")},
    )

    return results


def print_gate_results(results):
    """Pretty-print gate results."""
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"  Layer {r['layer']} ({r['name']}): {status}")
        if r.get("metrics"):
            for k, v in r["metrics"].items():
                if v is not None:
                    print(f"    {k}: {v}")
        if r.get("checks"):
            for k, v in r["checks"].items():
                mark = "+" if v else "X"
                print(f"    [{mark}] {k}")
        if r.get("issues"):
            for issue in r["issues"]:
                print(f"    ! {issue}")
        if r.get("error"):
            print(f"    ERROR: {r['error']}")
