"""
Module 3: Tail Risk Metrics
===========================
Computes risk metrics from scored prediction P&L data.
Designed to work with data from db.get_prediction_scorecard() or direct DB queries.

Sub-modules:
  3A: CVaR (Conditional Value at Risk) at 95%
  3B: Maximum Drawdown (with dates)
  3C: Omega Ratio
  3D: Sortino and Calmar Ratios
  3E: Conditional Beta (Up/Down vs SPY)
"""

import numpy as np
import pandas as pd


# ──────────────────────────────────────────────────────────────
# 3A: CVaR (Conditional Value at Risk)
# ──────────────────────────────────────────────────────────────

def calc_cvar(pnl_series: pd.Series, confidence: float = 0.95) -> dict:
    """
    CVaR (Expected Shortfall) at a given confidence level.

    CVaR_95 = mean of the worst 5% of outcomes.

    Args:
        pnl_series: Series of P&L values (% of stock price)
        confidence: Confidence level (default 0.95 = worst 5%)

    Returns:
        dict with var, cvar, n_tail, cumulative_premium
    """
    pnl = pnl_series.dropna()
    if len(pnl) < 20:
        return None

    sorted_pnl = pnl.sort_values()
    cutoff_idx = max(1, int(len(sorted_pnl) * (1 - confidence)))
    tail = sorted_pnl.iloc[:cutoff_idx]

    var_level = float(sorted_pnl.iloc[cutoff_idx])
    cvar = float(tail.mean())
    cumulative_premium = float(pnl[pnl > 0].sum())

    return {
        "var_95": round(var_level, 4),
        "cvar_95": round(cvar, 4),
        "n_tail": len(tail),
        "n_total": len(pnl),
        "cumulative_premium_pct": round(cumulative_premium, 4),
        "tail_risk_ratio": round(abs(cvar) / (cumulative_premium / len(pnl)) if cumulative_premium > 0 else float("inf"), 2),
    }


def calc_cvar_by_signal(df: pd.DataFrame, confidence: float = 0.95) -> dict:
    """CVaR computed per signal (GREEN/YELLOW/RED) and overall."""
    results = {}

    # Overall
    if "pnl_pct" in df.columns:
        results["overall"] = calc_cvar(df["pnl_pct"], confidence)

    # Per signal
    if "signal" in df.columns and "pnl_pct" in df.columns:
        for sig in ["GREEN", "YELLOW", "RED"]:
            subset = df[df["signal"] == sig]
            if len(subset) >= 10:
                results[sig] = calc_cvar(subset["pnl_pct"], confidence)

    return results


# ──────────────────────────────────────────────────────────────
# 3B: Maximum Drawdown
# ──────────────────────────────────────────────────────────────

def calc_max_drawdown(pnl_series: pd.Series, dates: pd.Series = None) -> dict:
    """
    Maximum drawdown from cumulative P&L series.

    Args:
        pnl_series: Series of per-trade P&L values (% of stock price)
        dates: Optional date series aligned with pnl_series

    Returns:
        dict with max_drawdown, peak, trough, start/end dates, recovery date
    """
    pnl = pnl_series.dropna()
    if len(pnl) < 5:
        return None

    cum_pnl = pnl.cumsum()
    running_max = cum_pnl.cummax()
    drawdown = cum_pnl - running_max

    max_dd = float(drawdown.min())
    if max_dd == 0:
        return {
            "max_drawdown_pct": 0.0,
            "peak_pnl": round(float(cum_pnl.max()), 4),
            "trough_pnl": round(float(cum_pnl.max()), 4),
            "start_date": None,
            "end_date": None,
            "recovery_date": None,
            "n_trades_in_drawdown": 0,
            "current_drawdown_pct": 0.0,
        }

    # Find the trough (worst point)
    trough_idx = drawdown.idxmin()
    trough_pos = pnl.index.get_loc(trough_idx)

    # Find the peak before the trough
    peak_val = running_max.iloc[trough_pos]
    # Walk backward to find where cumulative was at peak
    peak_pos = None
    for i in range(trough_pos, -1, -1):
        if cum_pnl.iloc[i] == peak_val:
            peak_pos = i
            break
    if peak_pos is None:
        peak_pos = 0

    # Find recovery (if any) — where cumulative returns to peak level after trough
    recovery_pos = None
    for i in range(trough_pos + 1, len(cum_pnl)):
        if cum_pnl.iloc[i] >= peak_val:
            recovery_pos = i
            break

    # Current drawdown
    current_dd = float(cum_pnl.iloc[-1] - cum_pnl.max())

    result = {
        "max_drawdown_pct": round(max_dd, 4),
        "peak_pnl": round(float(peak_val), 4),
        "trough_pnl": round(float(cum_pnl.iloc[trough_pos]), 4),
        "n_trades_in_drawdown": trough_pos - peak_pos,
        "current_drawdown_pct": round(current_dd, 4),
        "recovered": recovery_pos is not None,
    }

    if dates is not None and len(dates) == len(pnl):
        result["start_date"] = str(dates.iloc[peak_pos])
        result["end_date"] = str(dates.iloc[trough_pos])
        result["recovery_date"] = str(dates.iloc[recovery_pos]) if recovery_pos else None
    else:
        result["start_date"] = None
        result["end_date"] = None
        result["recovery_date"] = None

    return result


# ──────────────────────────────────────────────────────────────
# 3C: Omega Ratio
# ──────────────────────────────────────────────────────────────

def calc_omega_ratio(pnl_series: pd.Series, threshold: float = 0.0) -> dict:
    """
    Omega ratio: sum of gains above threshold / sum of losses below threshold.

    No parametric assumptions — works on empirical P&L distribution.

    Args:
        pnl_series: Series of P&L values (%)
        threshold: Breakeven threshold (default 0)

    Returns:
        dict with omega at breakeven and at risk-free threshold
    """
    pnl = pnl_series.dropna()
    if len(pnl) < 20:
        return None

    gains = pnl[pnl > threshold] - threshold
    losses = threshold - pnl[pnl <= threshold]

    sum_gains = float(gains.sum())
    sum_losses = float(losses.sum())

    omega_breakeven = round(sum_gains / sum_losses, 4) if sum_losses > 0 else float("inf")

    # Also compute at risk-free threshold (~5% annual / 252 days * 20 holding days)
    rf_threshold = 5.0 / 252 * 20 / 100 * 100  # ~0.40% over 20 trading days
    gains_rf = pnl[pnl > rf_threshold] - rf_threshold
    losses_rf = rf_threshold - pnl[pnl <= rf_threshold]
    sum_gains_rf = float(gains_rf.sum())
    sum_losses_rf = float(losses_rf.sum())
    omega_rf = round(sum_gains_rf / sum_losses_rf, 4) if sum_losses_rf > 0 else float("inf")

    return {
        "omega_breakeven": omega_breakeven,
        "omega_risk_free": omega_rf,
        "rf_threshold_pct": round(rf_threshold, 4),
        "n_gains": int((pnl > threshold).sum()),
        "n_losses": int((pnl <= threshold).sum()),
    }


# ──────────────────────────────────────────────────────────────
# 3D: Sortino and Calmar Ratios
# ──────────────────────────────────────────────────────────────

def calc_sortino_ratio(pnl_series: pd.Series, risk_free_annual: float = 5.0,
                       holding_days: int = 20) -> dict:
    """
    Sortino ratio: (mean_return - risk_free) / downside_deviation

    Better than Sharpe for short premium because it doesn't penalize
    capped upside (options premium is bounded).

    Args:
        pnl_series: Series of P&L values (%)
        risk_free_annual: Annual risk-free rate in %
        holding_days: Typical holding period in trading days
    """
    pnl = pnl_series.dropna()
    if len(pnl) < 20:
        return None

    rf_per_trade = risk_free_annual / 252 * holding_days  # % per trade

    excess = pnl - rf_per_trade
    downside = pnl[pnl < 0]
    downside_dev = float(downside.std()) if len(downside) >= 3 else None

    mean_excess = float(excess.mean())

    sortino = round(mean_excess / downside_dev, 4) if downside_dev and downside_dev > 0 else None

    # Annualize: ~252/holding_days trades per year
    trades_per_year = 252 / holding_days
    sortino_annual = round(sortino * np.sqrt(trades_per_year), 4) if sortino is not None else None

    return {
        "sortino_per_trade": sortino,
        "sortino_annualized": sortino_annual,
        "mean_excess_pct": round(mean_excess, 4),
        "downside_dev_pct": round(downside_dev, 4) if downside_dev else None,
        "n_downside": len(downside),
    }


def calc_calmar_ratio(pnl_series: pd.Series, dates: pd.Series = None,
                      holding_days: int = 20) -> dict:
    """
    Calmar ratio: CAGR / |max_drawdown|

    Measures return per unit of worst-case pain.
    """
    pnl = pnl_series.dropna()
    if len(pnl) < 20:
        return None

    dd = calc_max_drawdown(pnl, dates)
    if dd is None or dd["max_drawdown_pct"] == 0:
        return None

    # Approximate CAGR from cumulative P&L
    total_pnl = float(pnl.sum())
    n_trades = len(pnl)
    trades_per_year = 252 / holding_days
    years = n_trades / trades_per_year

    if years <= 0:
        return None

    # Simple annualized return (not compound, since these are % per trade)
    annual_return = total_pnl / years

    calmar = round(annual_return / abs(dd["max_drawdown_pct"]), 4) if dd["max_drawdown_pct"] != 0 else None

    return {
        "calmar_ratio": calmar,
        "annual_return_pct": round(annual_return, 4),
        "max_drawdown_pct": dd["max_drawdown_pct"],
        "years": round(years, 2),
    }


# ──────────────────────────────────────────────────────────────
# 3E: Conditional Beta (Up/Down vs SPY)
# ──────────────────────────────────────────────────────────────

def calc_conditional_beta(pred_df: pd.DataFrame) -> dict:
    """
    Conditional beta: regress strategy P&L on SPY returns,
    split by SPY up-days vs SPY down-days.

    Short premium strategies typically show:
    - High down-beta (~0.75) — lose when market drops
    - Low up-beta (~0.34) — don't fully participate in rallies
    This concavity is the core risk of short premium.

    Args:
        pred_df: DataFrame with columns: date, pnl_pct, ticker
                 SPY returns fetched internally.

    Returns:
        dict with up_beta, down_beta, asymmetry ratio
    """
    try:
        import yfinance as yf
    except ImportError:
        return {"error": "yfinance not installed"}

    if "pnl_pct" not in pred_df.columns or "date" not in pred_df.columns:
        return None

    df = pred_df[["date", "pnl_pct"]].dropna().copy()
    df["date"] = pd.to_datetime(df["date"])

    if len(df) < 20:
        return None

    # Get SPY returns for matching dates
    min_date = df["date"].min() - pd.Timedelta(days=5)
    max_date = df["date"].max() + pd.Timedelta(days=5)

    try:
        spy = yf.download("SPY", start=min_date, end=max_date, progress=False)
        if spy.empty:
            return {"error": "Could not fetch SPY data"}

        # Handle multi-level columns from yfinance
        if isinstance(spy.columns, pd.MultiIndex):
            spy.columns = spy.columns.get_level_values(0)

        spy["spy_return"] = spy["Close"].pct_change() * 100
        spy = spy[["spy_return"]].dropna()
        spy.index = spy.index.tz_localize(None) if spy.index.tz else spy.index
    except Exception as e:
        return {"error": f"SPY fetch failed: {e}"}

    # Aggregate strategy P&L by date (average across tickers for same date)
    daily_pnl = df.groupby("date")["pnl_pct"].mean().reset_index()
    daily_pnl["date"] = pd.to_datetime(daily_pnl["date"])
    daily_pnl = daily_pnl.set_index("date")

    # Join with SPY
    spy_daily = spy[["spy_return"]].copy()
    spy_daily.index = pd.to_datetime(spy_daily.index)

    merged = daily_pnl.join(spy_daily, how="inner")
    if len(merged) < 20:
        return {"error": f"Only {len(merged)} overlapping dates with SPY"}

    # Split by SPY direction
    up_days = merged[merged["spy_return"] > 0]
    down_days = merged[merged["spy_return"] <= 0]

    result = {
        "n_total": len(merged),
        "n_up_days": len(up_days),
        "n_down_days": len(down_days),
    }

    # Up-beta: regress strategy on SPY for up days
    if len(up_days) >= 10:
        x = up_days["spy_return"].values
        y = up_days["pnl_pct"].values
        x_mat = np.column_stack([np.ones(len(x)), x])
        try:
            beta = np.linalg.lstsq(x_mat, y, rcond=None)[0]
            result["up_alpha"] = round(float(beta[0]), 4)
            result["up_beta"] = round(float(beta[1]), 4)
        except Exception:
            result["up_beta"] = None

    # Down-beta: regress strategy on SPY for down days
    if len(down_days) >= 10:
        x = down_days["spy_return"].values
        y = down_days["pnl_pct"].values
        x_mat = np.column_stack([np.ones(len(x)), x])
        try:
            beta = np.linalg.lstsq(x_mat, y, rcond=None)[0]
            result["down_alpha"] = round(float(beta[0]), 4)
            result["down_beta"] = round(float(beta[1]), 4)
        except Exception:
            result["down_beta"] = None

    # Asymmetry ratio
    if result.get("up_beta") is not None and result.get("down_beta") is not None:
        if result["up_beta"] != 0:
            result["asymmetry_ratio"] = round(result["down_beta"] / result["up_beta"], 2)
        else:
            result["asymmetry_ratio"] = None
    else:
        result["asymmetry_ratio"] = None

    return result


# ──────────────────────────────────────────────────────────────
# Combined: Run all Module 3 metrics
# ──────────────────────────────────────────────────────────────

def run_all_risk_metrics(pred_df: pd.DataFrame, holding_days: int = 20) -> dict:
    """
    Run all tail risk metrics on a scored predictions DataFrame.

    Args:
        pred_df: DataFrame from DB with at minimum: date, pnl_pct, signal, seller_won

    Returns:
        dict with all risk metric results
    """
    if pred_df.empty or "pnl_pct" not in pred_df.columns:
        return {"error": "No P&L data available. Run prediction scoring first."}

    pnl = pred_df["pnl_pct"].dropna()
    dates = pred_df.loc[pnl.index, "date"] if "date" in pred_df.columns else None

    results = {}

    # 3A: CVaR
    print("[risk] Computing CVaR...")
    results["cvar"] = calc_cvar_by_signal(pred_df)

    # 3B: Max Drawdown
    print("[risk] Computing max drawdown...")
    results["max_drawdown"] = calc_max_drawdown(pnl, dates)

    # 3C: Omega Ratio
    print("[risk] Computing Omega ratio...")
    results["omega"] = calc_omega_ratio(pnl)

    # 3D: Sortino & Calmar
    print("[risk] Computing Sortino ratio...")
    results["sortino"] = calc_sortino_ratio(pnl, holding_days=holding_days)
    print("[risk] Computing Calmar ratio...")
    results["calmar"] = calc_calmar_ratio(pnl, dates, holding_days=holding_days)

    # 3E: Conditional Beta
    print("[risk] Computing conditional beta vs SPY...")
    results["conditional_beta"] = calc_conditional_beta(pred_df)

    return results


# ──────────────────────────────────────────────────────────────
# CLI runner
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from db import _get_supabase, _get_sqlite
    import sys

    print("=" * 70)
    print("MODULE 3: Tail Risk Metrics")
    print("=" * 70)

    # Load scored predictions
    sb = _get_supabase()
    if sb:
        print("[risk] Loading scored predictions from Supabase...")
        resp = sb.table("predictions").select("*").eq("scored", 1).order("date").execute()
        data = resp.data or []
        df = pd.DataFrame(data) if data else pd.DataFrame()
    else:
        print("[risk] Loading scored predictions from SQLite...")
        conn = _get_sqlite()
        df = pd.read_sql_query(
            "SELECT * FROM predictions WHERE scored = 1 ORDER BY date",
            conn
        )
        conn.close()

    if df.empty:
        print("ERROR: No scored predictions found. Run scoring first.")
        sys.exit(1)

    has_pnl = "pnl_pct" in df.columns and df["pnl_pct"].notna().any()
    if not has_pnl:
        print("ERROR: No P&L data in predictions. Run Module 2 scoring first.")
        sys.exit(1)

    n_scored = len(df)
    n_pnl = df["pnl_pct"].notna().sum()
    print(f"[risk] {n_scored} scored predictions, {n_pnl} with P&L data")
    print()

    results = run_all_risk_metrics(df)

    # ── Print results ──
    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)

    # 3A: CVaR
    print("\n--- 3A: CVaR (Conditional Value at Risk) ---")
    cvar = results.get("cvar", {})
    for label, data in cvar.items():
        if data is None:
            continue
        print(f"  {label}:")
        print(f"    VaR (95%):  {data['var_95']:+.2f}%")
        print(f"    CVaR (95%): {data['cvar_95']:+.2f}%  (avg of worst {data['n_tail']} trades)")
        print(f"    Tail Risk Ratio: {data['tail_risk_ratio']:.1f}x  "
              f"(CVaR / avg premium, >1 = tail wipes out premium)")

    # 3B: Max Drawdown
    print("\n--- 3B: Maximum Drawdown ---")
    dd = results.get("max_drawdown")
    if dd:
        print(f"  Max Drawdown: {dd['max_drawdown_pct']:+.2f}%")
        print(f"  Peak cum P&L: {dd['peak_pnl']:+.2f}%  →  Trough: {dd['trough_pnl']:+.2f}%")
        print(f"  Duration: {dd['n_trades_in_drawdown']} trades")
        if dd.get("start_date"):
            print(f"  Period: {dd['start_date']} to {dd['end_date']}")
        if dd.get("recovery_date"):
            print(f"  Recovered: {dd['recovery_date']}")
        elif dd.get("recovered") is False:
            print(f"  NOT YET RECOVERED. Current drawdown: {dd['current_drawdown_pct']:+.2f}%")
    else:
        print("  Not enough data")

    # 3C: Omega Ratio
    print("\n--- 3C: Omega Ratio ---")
    omega = results.get("omega")
    if omega:
        print(f"  Omega (breakeven):   {omega['omega_breakeven']:.2f}  {'> 1 ✓' if omega['omega_breakeven'] > 1 else '< 1 ✗'}")
        print(f"  Omega (risk-free):   {omega['omega_risk_free']:.2f}  (threshold: {omega['rf_threshold_pct']:.2f}%)")
        print(f"  Gains/Losses ratio:  {omega['n_gains']} / {omega['n_losses']}")
    else:
        print("  Not enough data")

    # 3D: Sortino & Calmar
    print("\n--- 3D: Sortino & Calmar Ratios ---")
    sortino = results.get("sortino")
    if sortino and sortino.get("sortino_per_trade") is not None:
        print(f"  Sortino (per trade):  {sortino['sortino_per_trade']:.3f}")
        print(f"  Sortino (annualized): {sortino['sortino_annualized']:.3f}")
        print(f"  Mean excess return:   {sortino['mean_excess_pct']:+.4f}%")
        print(f"  Downside deviation:   {sortino['downside_dev_pct']:.4f}%  ({sortino['n_downside']} losing trades)")
    else:
        print("  Sortino: Not enough data")

    calmar = results.get("calmar")
    if calmar and calmar.get("calmar_ratio") is not None:
        print(f"  Calmar ratio:         {calmar['calmar_ratio']:.3f}")
        print(f"  Annual return:        {calmar['annual_return_pct']:+.2f}%")
        print(f"  Max drawdown:         {calmar['max_drawdown_pct']:+.2f}%")
        print(f"  Period:               {calmar['years']:.1f} years")
    else:
        print("  Calmar: Not enough data")

    # 3E: Conditional Beta
    print("\n--- 3E: Conditional Beta (vs SPY) ---")
    cb = results.get("conditional_beta")
    if cb and cb.get("error"):
        print(f"  Error: {cb['error']}")
    elif cb and cb.get("up_beta") is not None and cb.get("down_beta") is not None:
        print(f"  Up-beta (SPY > 0):   {cb['up_beta']:.3f}  ({cb['n_up_days']} days)")
        print(f"  Down-beta (SPY ≤ 0): {cb['down_beta']:.3f}  ({cb['n_down_days']} days)")
        if cb.get("asymmetry_ratio") is not None:
            print(f"  Asymmetry ratio:     {cb['asymmetry_ratio']:.2f}x  "
                  f"(>1 = lose more in down markets than you gain in up markets)")
            if cb["asymmetry_ratio"] > 2:
                print("  ⚠ HIGH ASYMMETRY — typical for short premium but monitor closely")
            elif cb["asymmetry_ratio"] > 1:
                print("  Moderate asymmetry — expected for short premium strategies")
            else:
                print("  Low asymmetry — unusual for short premium, double-check data")
    else:
        print("  Not enough data")

    print()
    print("=" * 70)
    print("VERDICT")
    print("=" * 70)

    # Summary verdict
    issues = []
    positives = []

    omega = results.get("omega")
    if omega and omega["omega_breakeven"] > 1:
        positives.append(f"Omega > 1 ({omega['omega_breakeven']:.2f})")
    elif omega:
        issues.append(f"Omega < 1 ({omega['omega_breakeven']:.2f}) — strategy has negative EV")

    cvar_overall = cvar.get("overall")
    if cvar_overall and cvar_overall["tail_risk_ratio"] > 3:
        issues.append(f"CVaR tail risk ratio {cvar_overall['tail_risk_ratio']:.1f}x — tail losses are severe")
    elif cvar_overall and cvar_overall["tail_risk_ratio"] > 1.5:
        issues.append(f"CVaR tail risk ratio {cvar_overall['tail_risk_ratio']:.1f}x — moderate tail risk")
    elif cvar_overall:
        positives.append(f"Tail risk ratio {cvar_overall['tail_risk_ratio']:.1f}x — manageable")

    dd = results.get("max_drawdown")
    if dd and dd["max_drawdown_pct"] < -5:
        issues.append(f"Large max drawdown ({dd['max_drawdown_pct']:+.1f}%)")
    elif dd:
        positives.append(f"Max drawdown {dd['max_drawdown_pct']:+.1f}% — acceptable")

    sortino = results.get("sortino")
    if sortino and sortino.get("sortino_annualized") is not None:
        if sortino["sortino_annualized"] > 1:
            positives.append(f"Annualized Sortino {sortino['sortino_annualized']:.2f} — good risk-adjusted return")
        elif sortino["sortino_annualized"] > 0:
            positives.append(f"Annualized Sortino {sortino['sortino_annualized']:.2f} — positive but modest")
        else:
            issues.append(f"Negative Sortino ({sortino['sortino_annualized']:.2f}) — poor risk-adjusted return")

    if positives:
        print("POSITIVES:")
        for p in positives:
            print(f"  + {p}")
    if issues:
        print("CONCERNS:")
        for i in issues:
            print(f"  - {i}")

    if not issues:
        print("\nAll risk metrics look healthy. Strategy appears viable.")
    elif len(issues) <= 1:
        print("\nMinor concerns. Strategy is workable but monitor the flagged metric.")
    else:
        print("\nMultiple risk flags. Review strategy parameters before live trading.")
