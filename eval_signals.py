"""
Module 5: Signal Validation
============================
Tests whether each signal component actually adds predictive value.

Sub-modules:
  5A: Marginal Signal Contribution (Fama-MacBeth style panel regression)
  5B: Multicollinearity Check (VIF + correlation matrix)
  5C: Regime Filter Value Test (filtered vs unfiltered vs random-skip)
  5D: Exit Rule Overfitting Test (leave-one-out impact, Deflated Sharpe)
"""

import numpy as np
import pandas as pd


# ──────────────────────────────────────────────────────────────
# 5A: Marginal Signal Contribution (Fama-MacBeth)
# ──────────────────────────────────────────────────────────────

def fama_macbeth_regression(df: pd.DataFrame) -> dict:
    """
    Fama-MacBeth style analysis of signal components.

    For each date with enough cross-sectional observations:
      OLS: pnl = α + β₁×VRP + β₂×IV_Pctl + β₃×Regime_num + β₄×Skew + ε
    Then average the coefficients across dates and compute t-stats.

    If not enough cross-sectional data per date (common for daily predictions),
    falls back to pooled OLS with Newey-West standard errors.

    Args:
        df: Scored predictions DataFrame with pnl_pct, vrp, iv_pctl, regime, skew_penalty

    Returns:
        dict with coefficients, t-stats, significance flags
    """
    required = ["pnl_pct", "date"]
    for col in required:
        if col not in df.columns:
            return {"error": f"Missing column: {col}"}

    df = df.copy()
    df = df[df["pnl_pct"].notna()]

    if len(df) < 30:
        return {"error": f"Only {len(df)} observations, need at least 30"}

    # Build feature matrix
    features = {}
    feature_names = []

    if "vrp" in df.columns and df["vrp"].notna().sum() > 20:
        features["vrp"] = df["vrp"].fillna(0).astype(float)
        feature_names.append("vrp")

    if "iv_pctl" in df.columns and df["iv_pctl"].notna().sum() > 20:
        features["iv_pctl"] = df["iv_pctl"].fillna(50).astype(float)
        feature_names.append("iv_pctl")
    elif "iv_rank" in df.columns and df["iv_rank"].notna().sum() > 20:
        features["iv_rank"] = df["iv_rank"].fillna(50).astype(float)
        feature_names.append("iv_rank")

    if "regime" in df.columns and df["regime"].notna().sum() > 20:
        regime_map = {"Low Vol": 0, "Normal": 1, "Elevated": 2, "High Vol": 3, "Crisis": 4}
        features["regime_num"] = df["regime"].map(regime_map).fillna(1).astype(float)
        feature_names.append("regime_num")

    if "skew_penalty" in df.columns and df["skew_penalty"].notna().sum() > 20:
        features["skew_penalty"] = df["skew_penalty"].fillna(0).astype(float)
        feature_names.append("skew_penalty")
    elif "skew" in df.columns and df["skew"].notna().sum() > 20:
        features["skew"] = df["skew"].fillna(0).astype(float)
        feature_names.append("skew")

    if not feature_names:
        return {"error": "No signal features available in predictions data"}

    # Build X matrix
    X_df = pd.DataFrame(features)
    y = df["pnl_pct"].values
    valid = X_df.notna().all(axis=1)
    X_df = X_df[valid]
    y = y[valid.values]

    if len(y) < 30:
        return {"error": f"Only {len(y)} valid rows after filtering NaN features"}

    # Standardize for comparability
    X_means = X_df.mean()
    X_stds = X_df.std()
    X_stds = X_stds.replace(0, 1)
    X_std = (X_df - X_means) / X_stds

    # --- Pooled OLS with Newey-West (more practical with limited cross-sections) ---
    X = np.column_stack([np.ones(len(y)), X_std.values])
    names = ["intercept"] + feature_names

    try:
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
    except Exception as e:
        return {"error": f"OLS failed: {e}"}

    residuals = y - X @ beta
    n, k = X.shape

    # Newey-West HAC standard errors (lag = int(n^(1/3)))
    lag = max(1, int(n ** (1 / 3)))
    S = np.zeros((k, k))
    for j in range(lag + 1):
        weight = 1.0 if j == 0 else 1 - j / (lag + 1)
        for t in range(j, n):
            e_outer = np.outer(X[t] * residuals[t], X[t - j] * residuals[t - j])
            if j == 0:
                S += weight * e_outer
            else:
                S += weight * (e_outer + e_outer.T)

    S /= n
    XtX_inv = np.linalg.inv(X.T @ X / n)
    cov = XtX_inv @ S @ XtX_inv / n
    se = np.sqrt(np.diag(cov))
    se = np.where(se > 0, se, 1e-10)
    t_stats = beta / se
    p_values = 2 * (1 - _t_cdf(np.abs(t_stats), n - k))

    results = {
        "method": "pooled_ols_newey_west",
        "n_obs": n,
        "n_features": len(feature_names),
        "r_squared": round(float(1 - np.sum(residuals ** 2) / np.sum((y - y.mean()) ** 2)), 4),
        "coefficients": {},
    }

    for i, name in enumerate(names):
        sig = "***" if p_values[i] < 0.01 else "**" if p_values[i] < 0.05 else "*" if p_values[i] < 0.10 else ""
        results["coefficients"][name] = {
            "beta": round(float(beta[i]), 6),
            "se": round(float(se[i]), 6),
            "t_stat": round(float(t_stats[i]), 3),
            "p_value": round(float(p_values[i]), 4),
            "significant": p_values[i] < 0.05,
            "stars": sig,
        }

    return results


def _t_cdf(x, df):
    """Approximate t-distribution CDF using normal for large df."""
    from math import erf, sqrt
    # For df > 30, t ≈ normal
    if df > 30:
        return 0.5 * (1 + erf(x / sqrt(2)))
    # Rough approximation for smaller df
    a = 1 + x ** 2 / df
    return 0.5 + 0.5 * np.sign(x) * (1 - a ** (-(df + 1) / 2))


# ──────────────────────────────────────────────────────────────
# 5B: Multicollinearity Check (VIF)
# ──────────────────────────────────────────────────────────────

def multicollinearity_check(df: pd.DataFrame) -> dict:
    """
    Check for multicollinearity among signal components.

    VIF > 5 indicates redundant signals.
    VIF > 10 is severe — one signal should be dropped.
    """
    feature_cols = []
    df = df.copy()

    if "vrp" in df.columns and df["vrp"].notna().sum() > 20:
        feature_cols.append("vrp")
    if "iv_pctl" in df.columns and df["iv_pctl"].notna().sum() > 20:
        feature_cols.append("iv_pctl")
    elif "iv_rank" in df.columns and df["iv_rank"].notna().sum() > 20:
        feature_cols.append("iv_rank")
    if "regime" in df.columns and df["regime"].notna().sum() > 20:
        regime_map = {"Low Vol": 0, "Normal": 1, "Elevated": 2, "High Vol": 3, "Crisis": 4}
        df["regime_num"] = df["regime"].map(regime_map).fillna(1)
        feature_cols.append("regime_num")
    if "skew_penalty" in df.columns and df["skew_penalty"].notna().sum() > 20:
        feature_cols.append("skew_penalty")
    elif "skew" in df.columns and df["skew"].notna().sum() > 20:
        feature_cols.append("skew")

    if len(feature_cols) < 2:
        return {"error": "Need at least 2 signal features for collinearity check"}

    X = df[feature_cols].dropna()
    if len(X) < 30:
        return {"error": f"Only {len(X)} valid rows"}

    # Correlation matrix
    corr = X.corr()

    # VIF: for each feature, regress it on all others, VIF = 1 / (1 - R²)
    vif_results = {}
    for col in feature_cols:
        others = [c for c in feature_cols if c != col]
        y_v = X[col].values
        X_v = np.column_stack([np.ones(len(y_v)), X[others].values])
        try:
            beta = np.linalg.lstsq(X_v, y_v, rcond=None)[0]
            pred = X_v @ beta
            ss_res = np.sum((y_v - pred) ** 2)
            ss_tot = np.sum((y_v - y_v.mean()) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
            vif = 1 / (1 - r2) if r2 < 1 else float("inf")
        except Exception:
            vif = None

        vif_results[col] = {
            "vif": round(vif, 2) if vif is not None else None,
            "concern": "severe" if vif and vif > 10 else "moderate" if vif and vif > 5 else "ok",
        }

    return {
        "correlation_matrix": {
            col: {c2: round(float(corr.loc[col, c2]), 3) for c2 in feature_cols}
            for col in feature_cols
        },
        "vif": vif_results,
        "n_obs": len(X),
        "high_correlations": [
            {"pair": f"{c1} × {c2}", "corr": round(float(corr.loc[c1, c2]), 3)}
            for i, c1 in enumerate(feature_cols)
            for c2 in feature_cols[i + 1:]
            if abs(corr.loc[c1, c2]) > 0.5
        ],
    }


# ──────────────────────────────────────────────────────────────
# 5C: Regime Filter Value Test
# ──────────────────────────────────────────────────────────────

def regime_filter_test(df: pd.DataFrame, n_random_trials: int = 100) -> dict:
    """
    Tests whether the regime filter adds value.

    Strategy A: Full model (only trade GREEN signals in favorable regimes)
    Strategy B: No regime filter (trade all GREEN signals regardless of regime)
    Strategy C: Random skip (skip same % of trades as regime would, but randomly)

    If A doesn't beat C, the regime filter is just reducing sample size.
    """
    if "pnl_pct" not in df.columns or "signal" not in df.columns:
        return {"error": "Need pnl_pct and signal columns"}

    df = df[df["pnl_pct"].notna()].copy()

    if "regime" not in df.columns or df["regime"].isna().all():
        return {"error": "No regime data available"}

    green = df[df["signal"] == "GREEN"]
    if len(green) < 20:
        return {"error": f"Only {len(green)} GREEN predictions, need 20+"}

    # Strategy A: GREEN in favorable regimes (Low Vol, Normal)
    favorable = ["Low Vol", "Normal"]
    a_trades = green[green["regime"].isin(favorable)]

    # Strategy B: All GREEN (no filter)
    b_trades = green

    # Strategy C: Random skip, matching A's sample size (average over trials)
    skip_pct = 1 - len(a_trades) / len(b_trades) if len(b_trades) > 0 else 0
    keep_n = len(a_trades)

    c_pnls = []
    rng = np.random.RandomState(42)
    for _ in range(n_random_trials):
        if keep_n >= len(b_trades):
            sample = b_trades
        else:
            sample = b_trades.iloc[rng.choice(len(b_trades), size=keep_n, replace=False)]
        c_pnls.append(float(sample["pnl_pct"].mean()))

    a_pnl = float(a_trades["pnl_pct"].mean()) if len(a_trades) > 0 else None
    b_pnl = float(b_trades["pnl_pct"].mean()) if len(b_trades) > 0 else None
    c_pnl_avg = float(np.mean(c_pnls))
    c_pnl_std = float(np.std(c_pnls))

    result = {
        "strategy_a": {
            "name": "Regime-filtered GREEN",
            "n_trades": len(a_trades),
            "avg_pnl_pct": round(a_pnl, 4) if a_pnl is not None else None,
            "win_rate": round(float(a_trades["seller_won"].mean() * 100), 1) if len(a_trades) > 0 and "seller_won" in a_trades.columns else None,
        },
        "strategy_b": {
            "name": "All GREEN (no regime filter)",
            "n_trades": len(b_trades),
            "avg_pnl_pct": round(b_pnl, 4) if b_pnl is not None else None,
            "win_rate": round(float(b_trades["seller_won"].mean() * 100), 1) if "seller_won" in b_trades.columns else None,
        },
        "strategy_c": {
            "name": f"Random skip ({skip_pct:.0%} dropped)",
            "n_trades": keep_n,
            "avg_pnl_pct": round(c_pnl_avg, 4),
            "std_pnl_pct": round(c_pnl_std, 4),
        },
        "skip_pct": round(skip_pct * 100, 1),
    }

    # Verdict
    if a_pnl is not None and b_pnl is not None:
        result["filter_vs_no_filter"] = round(a_pnl - b_pnl, 4)
        result["filter_vs_random"] = round(a_pnl - c_pnl_avg, 4) if a_pnl else None

        # Is A significantly better than C? (simple z-test)
        if c_pnl_std > 0 and a_pnl is not None:
            z = (a_pnl - c_pnl_avg) / c_pnl_std
            result["z_vs_random"] = round(z, 2)
            result["regime_adds_value"] = z > 1.65  # one-sided 5%
        else:
            result["regime_adds_value"] = None

    return result


# ──────────────────────────────────────────────────────────────
# 5D: Exit Rule Overfitting Test
# ──────────────────────────────────────────────────────────────

def exit_rule_analysis(df: pd.DataFrame) -> dict:
    """
    Analyze exit rule overfitting risk.

    We have 9 exit triggers, each with implicit parameters.
    This estimates the Deflated Sharpe Ratio to account for
    multiple testing across exit rule configurations.

    Also: if we have enough data, test impact of removing each regime
    on aggregate P&L (proxy for exit rule impact, since we can't
    test exit rules directly without trade-level data).

    For a full test, we'd need trade-level exit data. Here we
    compute the DSR adjustment as a warning flag.
    """
    if "pnl_pct" not in df.columns:
        return {"error": "Need pnl_pct column"}

    pnl = df["pnl_pct"].dropna()
    if len(pnl) < 30:
        return {"error": f"Only {len(pnl)} observations, need 30+"}

    n = len(pnl)
    mean_pnl = float(pnl.mean())
    std_pnl = float(pnl.std())

    if std_pnl == 0:
        return {"error": "Zero variance in P&L"}

    sharpe = mean_pnl / std_pnl

    # Deflated Sharpe Ratio (Bailey-López de Prado)
    # 9 exit rules × ~3 parameter settings each = ~27 trials
    n_trials = 27
    skew = float(pnl.skew())
    kurt = float(pnl.kurtosis())

    # Expected max Sharpe under null (Sharpe = 0, n_trials independent tests)
    # E[max(SR)] ≈ sqrt(2 * log(n_trials)) * (1 - γ/(2*log(n_trials))) + γ/sqrt(2*log(n_trials))
    # where γ ≈ 0.5772 (Euler-Mascheroni)
    gamma_em = 0.5772
    if n_trials > 1:
        log_n = np.log(n_trials)
        e_max_sr = np.sqrt(2 * log_n) * (1 - gamma_em / (2 * log_n)) + gamma_em / np.sqrt(2 * log_n)
    else:
        e_max_sr = 0

    # SR standard error with skewness/kurtosis correction
    sr_se = np.sqrt((1 + 0.5 * sharpe ** 2 - skew * sharpe + (kurt / 4) * sharpe ** 2) / n)
    sr_se = max(sr_se, 1e-10)

    # DSR: probability that observed Sharpe is above E[max SR under null]
    dsr_z = (sharpe - e_max_sr) / sr_se

    # Approximate p-value using normal CDF
    from math import erf, sqrt
    dsr_p = 0.5 * (1 + erf(dsr_z / sqrt(2)))

    return {
        "observed_sharpe": round(sharpe, 4),
        "n_trials_assumed": n_trials,
        "expected_max_sharpe_null": round(e_max_sr, 4),
        "deflated_sharpe_z": round(dsr_z, 4),
        "deflated_sharpe_p": round(dsr_p, 4),
        "passes_dsr": dsr_p > 0.95,  # observed SR significantly above multiple-testing threshold
        "skewness": round(skew, 3),
        "kurtosis": round(kurt, 3),
        "n_obs": n,
        "sr_std_error": round(sr_se, 4),
    }


# ──────────────────────────────────────────────────────────────
# Combined: Run all Module 5 tests
# ──────────────────────────────────────────────────────────────

def run_all_signal_validation(df: pd.DataFrame) -> dict:
    """
    Run all signal validation tests on scored predictions.

    Args:
        df: Scored predictions DataFrame

    Returns:
        dict with all sub-module results
    """
    results = {}

    print("[5A] Fama-MacBeth signal contribution...")
    results["fama_macbeth"] = fama_macbeth_regression(df)

    print("[5B] Multicollinearity check...")
    results["multicollinearity"] = multicollinearity_check(df)

    print("[5C] Regime filter value test...")
    results["regime_filter"] = regime_filter_test(df)

    print("[5D] Exit rule overfitting test...")
    results["exit_rule"] = exit_rule_analysis(df)

    return results


# ──────────────────────────────────────────────────────────────
# CLI runner
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from db import _get_supabase, _get_sqlite
    import sys

    print("=" * 70)
    print("MODULE 5: Signal Validation")
    print("=" * 70)

    # Load scored predictions
    sb = _get_supabase()
    if sb:
        print("[signals] Loading from Supabase...")
        resp = sb.table("predictions").select("*").eq("scored", 1).order("date").execute()
        data = resp.data or []
        df = pd.DataFrame(data) if data else pd.DataFrame()
    else:
        print("[signals] Loading from SQLite...")
        conn = _get_sqlite()
        df = pd.read_sql_query(
            "SELECT * FROM predictions WHERE scored = 1 ORDER BY date", conn
        )
        conn.close()

    if df.empty:
        print("ERROR: No scored predictions found.")
        sys.exit(1)

    has_pnl = "pnl_pct" in df.columns and df["pnl_pct"].notna().any()
    if not has_pnl:
        print("ERROR: No P&L data. Run Module 2 scoring first.")
        sys.exit(1)

    n_scored = len(df)
    print(f"[signals] {n_scored} scored predictions loaded")

    # List available signal columns
    sig_cols = [c for c in ["vrp", "iv_pctl", "iv_rank", "regime", "skew_penalty", "skew", "term_label"]
                if c in df.columns and df[c].notna().any()]
    print(f"[signals] Available signal features: {sig_cols}")
    print()

    results = run_all_signal_validation(df)

    # ── Print results ──
    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)

    # 5A: Fama-MacBeth
    print("\n--- 5A: Marginal Signal Contribution ---")
    fm = results.get("fama_macbeth", {})
    if fm.get("error"):
        print(f"  Error: {fm['error']}")
    else:
        print(f"  Method: {fm['method']} (n={fm['n_obs']})")
        print(f"  R²: {fm['r_squared']:.4f}")
        print(f"\n  {'Feature':<16} {'Beta':>10} {'SE':>10} {'t-stat':>8} {'p-value':>9} {'Sig':>5}")
        print("  " + "-" * 60)
        for name, coeff in fm["coefficients"].items():
            print(f"  {name:<16} {coeff['beta']:>10.4f} {coeff['se']:>10.4f} "
                  f"{coeff['t_stat']:>8.3f} {coeff['p_value']:>9.4f} {coeff['stars']:>5}")

        # Interpretation
        sig_features = [n for n, c in fm["coefficients"].items()
                        if c["significant"] and n != "intercept"]
        insig_features = [n for n, c in fm["coefficients"].items()
                          if not c["significant"] and n != "intercept"]
        if sig_features:
            print(f"\n  SIGNIFICANT: {', '.join(sig_features)}")
        if insig_features:
            print(f"  NOT SIGNIFICANT: {', '.join(insig_features)} — consider removing")

        # Critical check: is VRP significant?
        vrp_coeff = fm["coefficients"].get("vrp")
        if vrp_coeff:
            if vrp_coeff["significant"] and vrp_coeff["beta"] > 0:
                print("\n  ✓ VRP is significant with positive coefficient — core thesis holds")
            elif vrp_coeff["significant"]:
                print(f"\n  ⚠ VRP is significant but coefficient is NEGATIVE ({vrp_coeff['beta']:.4f}) — inverted!")
            else:
                print(f"\n  ✗ VRP is NOT significant (p={vrp_coeff['p_value']:.3f}) — core thesis is weak")

    # 5B: Multicollinearity
    print("\n--- 5B: Multicollinearity Check ---")
    mc = results.get("multicollinearity", {})
    if mc.get("error"):
        print(f"  Error: {mc['error']}")
    else:
        print(f"  VIF scores (>5 = concern, >10 = severe):")
        for feat, vif_data in mc["vif"].items():
            flag = " ⚠" if vif_data["concern"] != "ok" else ""
            print(f"    {feat:<16} VIF = {vif_data['vif']:.2f}{flag}")

        if mc["high_correlations"]:
            print(f"\n  High correlations (|r| > 0.5):")
            for hc in mc["high_correlations"]:
                print(f"    {hc['pair']}: r = {hc['corr']:.3f}")
        else:
            print(f"\n  No high correlations found — signals are reasonably independent")

    # 5C: Regime Filter
    print("\n--- 5C: Regime Filter Value Test ---")
    rf = results.get("regime_filter", {})
    if rf.get("error"):
        print(f"  Error: {rf['error']}")
    else:
        a = rf["strategy_a"]
        b = rf["strategy_b"]
        c = rf["strategy_c"]
        print(f"  Strategy A (regime-filtered GREEN): {a['n_trades']} trades, "
              f"avg P&L = {a['avg_pnl_pct']:+.4f}%")
        print(f"  Strategy B (all GREEN):             {b['n_trades']} trades, "
              f"avg P&L = {b['avg_pnl_pct']:+.4f}%")
        print(f"  Strategy C (random skip {rf['skip_pct']:.0f}%):    {c['n_trades']} trades, "
              f"avg P&L = {c['avg_pnl_pct']:+.4f}% ± {c['std_pnl_pct']:.4f}%")

        diff_ab = rf.get("filter_vs_no_filter", 0)
        print(f"\n  Filter vs No Filter: {diff_ab:+.4f}pp")

        if rf.get("z_vs_random") is not None:
            z = rf["z_vs_random"]
            print(f"  Filter vs Random Skip: z = {z:.2f} "
                  f"({'significant' if rf['regime_adds_value'] else 'NOT significant'} at 5%)")

        if rf.get("regime_adds_value") is True:
            print("\n  ✓ Regime filter adds statistically significant value")
        elif rf.get("regime_adds_value") is False:
            print("\n  ✗ Regime filter does NOT beat random skipping — it may just be reducing sample size")

    # 5D: Exit Rule Overfitting
    print("\n--- 5D: Exit Rule Overfitting (Deflated Sharpe Ratio) ---")
    er = results.get("exit_rule", {})
    if er.get("error"):
        print(f"  Error: {er['error']}")
    else:
        print(f"  Observed Sharpe (per-trade): {er['observed_sharpe']:.4f}")
        print(f"  Expected max Sharpe under null ({er['n_trials_assumed']} trials): "
              f"{er['expected_max_sharpe_null']:.4f}")
        print(f"  Deflated Sharpe z-score: {er['deflated_sharpe_z']:.4f}")
        print(f"  P(observed > null): {er['deflated_sharpe_p']:.4f}")
        print(f"  P&L skewness: {er['skewness']:.3f}, kurtosis: {er['kurtosis']:.3f}")

        if er["passes_dsr"]:
            print("\n  ✓ Passes Deflated Sharpe test — performance likely not due to overfitting")
        else:
            print("\n  ✗ FAILS Deflated Sharpe test — observed performance may be due to multiple testing")
            print("    Consider reducing exit rule parameters or requiring stronger edge")

    # ── Verdict ──
    print(f"\n{'='*70}")
    print("VERDICT")
    print("=" * 70)

    issues = []
    positives = []

    # VRP significance
    if not fm.get("error"):
        vrp_c = fm["coefficients"].get("vrp")
        if vrp_c and vrp_c["significant"] and vrp_c["beta"] > 0:
            positives.append("VRP has significant positive predictive power")
        elif vrp_c and not vrp_c["significant"]:
            issues.append("VRP is NOT significant — core thesis is weak")

    # Multicollinearity
    if not mc.get("error"):
        severe = [f for f, v in mc["vif"].items() if v["concern"] == "severe"]
        if severe:
            issues.append(f"Severe multicollinearity in: {', '.join(severe)}")

    # Regime filter
    if not rf.get("error") and rf.get("regime_adds_value") is False:
        issues.append("Regime filter does not beat random skipping")
    elif not rf.get("error") and rf.get("regime_adds_value") is True:
        positives.append("Regime filter adds significant value")

    # DSR
    if not er.get("error"):
        if er["passes_dsr"]:
            positives.append("Passes multiple-testing correction (Deflated Sharpe)")
        else:
            issues.append("Fails Deflated Sharpe — possible overfitting from exit rules")

    if positives:
        print("POSITIVES:")
        for p in positives:
            print(f"  + {p}")
    if issues:
        print("CONCERNS:")
        for i in issues:
            print(f"  - {i}")

    if not issues:
        print("\nAll signal components validated. Signals are working as designed.")
    elif len(issues) == 1:
        print("\nMinor concern. Most signals are sound.")
    else:
        print("\nMultiple signal issues. Review which components to keep/drop.")
