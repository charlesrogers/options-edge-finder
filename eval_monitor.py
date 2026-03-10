"""
Module 8: Monitoring & Edge Erosion
====================================
Ongoing monitoring for strategy health and automated circuit breakers.

Sub-modules:
  8A: CUSUM Edge Erosion Detection
  8B: GARCH Parameter Drift
  8C: Circuit Breakers (VIX, drawdown, calendar)
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta


# ──────────────────────────────────────────────────────────────
# 8A: CUSUM Edge Erosion Detection
# ──────────────────────────────────────────────────────────────

def cusum_edge_detection(pnl_series: pd.Series, dates: pd.Series = None,
                         k: float = 0.25, h: float = 4.0) -> dict:
    """
    Page's CUSUM test for detecting edge erosion.

    Monitors whether the strategy's information ratio has degraded
    below an acceptable threshold.

    Reference value K = 0.25 (midpoint between IR=0.5 "good" and IR=0 "bad")
    Decision threshold H = 4 (one false alarm per ~200 months)

    S_t = max(0, S_{t-1} + (K - r_t))
    If S_t > H: ALERT — edge may have eroded.

    Args:
        pnl_series: Series of per-trade P&L values
        dates: Optional corresponding dates
        k: Reference value (edge threshold)
        h: Decision threshold (alarm sensitivity)

    Returns:
        dict with CUSUM values, alert status, chart data
    """
    pnl = pnl_series.dropna()
    if len(pnl) < 20:
        return {"error": f"Only {len(pnl)} observations, need 20+"}

    # Standardize P&L to information ratio scale
    mean_pnl = float(pnl.mean())
    std_pnl = float(pnl.std())
    if std_pnl == 0:
        return {"error": "Zero variance in P&L"}

    standardized = (pnl - mean_pnl) / std_pnl

    # CUSUM: accumulate deviations below threshold
    cusum_values = []
    s = 0.0
    alert_idx = None
    for i, r in enumerate(standardized):
        s = max(0, s + (k - r))
        cusum_values.append(s)
        if s > h and alert_idx is None:
            alert_idx = i

    cusum_series = pd.Series(cusum_values, index=pnl.index)
    current_cusum = float(cusum_values[-1])

    # Build chart data
    chart_data = []
    for i in range(len(cusum_values)):
        entry = {"idx": i, "cusum": round(cusum_values[i], 4)}
        if dates is not None and i < len(dates):
            entry["date"] = str(dates.iloc[i])
        chart_data.append(entry)

    # Recent trend: last 20 trades vs first half
    if len(pnl) >= 40:
        recent_ir = float(pnl.tail(20).mean() / pnl.tail(20).std()) if pnl.tail(20).std() > 0 else 0
        early_ir = float(pnl.head(20).mean() / pnl.head(20).std()) if pnl.head(20).std() > 0 else 0
        ir_trend = recent_ir - early_ir
    else:
        recent_ir = None
        early_ir = None
        ir_trend = None

    return {
        "current_cusum": round(current_cusum, 4),
        "threshold": h,
        "alert": current_cusum > h,
        "alert_trade_idx": alert_idx,
        "n_trades": len(pnl),
        "mean_pnl": round(mean_pnl, 4),
        "current_ir": round(float(pnl.mean() / pnl.std()), 4) if std_pnl > 0 else 0,
        "recent_ir": round(recent_ir, 4) if recent_ir is not None else None,
        "early_ir": round(early_ir, 4) if early_ir is not None else None,
        "ir_trend": round(ir_trend, 4) if ir_trend is not None else None,
        "chart_data": chart_data,
    }


# ──────────────────────────────────────────────────────────────
# 8B: GARCH Parameter Drift
# ──────────────────────────────────────────────────────────────

def garch_parameter_drift(hist: pd.DataFrame, ticker: str = "",
                          lookback_1: int = 1000, lookback_2: int = 500) -> dict:
    """
    Compare GARCH parameters from two different fitting windows
    to detect model drift.

    Fits GJR-GARCH(1,1,1) on:
      - Recent window (last lookback_2 days)
      - Full window (last lookback_1 days)

    If parameters differ >15%, the model may need recalibration.
    Also runs Ljung-Box test on residuals for misspecification.

    Args:
        hist: OHLCV DataFrame with enough history
        ticker: For display

    Returns:
        dict with parameter comparison, drift flags, Ljung-Box result
    """
    try:
        from arch import arch_model
    except ImportError:
        return {"error": "arch package not installed (pip install arch)"}

    log_ret = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()

    if len(log_ret) < lookback_1:
        return {"error": f"Need {lookback_1} days, have {len(log_ret)}"}

    results = {}

    for label, window in [("full", lookback_1), ("recent", lookback_2)]:
        data = log_ret.tail(window) * 100  # scale for arch

        try:
            model = arch_model(data, vol="GARCH", p=1, o=1, q=1, dist="normal")
            fit = model.fit(disp="off", show_warning=False)

            params = {
                "omega": float(fit.params.get("omega", 0)),
                "alpha": float(fit.params.get("alpha[1]", 0)),
                "beta": float(fit.params.get("beta[1]", 0)),
                "gamma": float(fit.params.get("gamma[1]", 0)),
            }

            # Ljung-Box on standardized residuals
            std_resid = fit.resid / fit.conditional_volatility
            std_resid = std_resid.dropna()

            # Manual Ljung-Box at lag 10
            n = len(std_resid)
            sq_resid = std_resid ** 2
            lb_stat = 0
            for lag in range(1, min(11, n)):
                r = float(sq_resid.autocorr(lag))
                if not np.isnan(r):
                    lb_stat += r ** 2 / (n - lag)
            lb_stat *= n * (n + 2)

            # Chi-squared p-value approximation (df=10)
            from math import exp, gamma as math_gamma
            df_lb = 10
            # Simple chi-squared CDF approximation
            lb_p = _chi2_survival(lb_stat, df_lb)

            results[label] = {
                "params": params,
                "aic": float(fit.aic),
                "bic": float(fit.bic),
                "ljung_box_stat": round(lb_stat, 2),
                "ljung_box_p": round(lb_p, 4),
                "ljung_box_pass": lb_p > 0.05,
                "n_obs": len(data),
            }
        except Exception as e:
            results[label] = {"error": str(e)}

    if results.get("full", {}).get("error") or results.get("recent", {}).get("error"):
        return {"error": "GARCH fitting failed", "details": results}

    # Compare parameters
    full_p = results["full"]["params"]
    recent_p = results["recent"]["params"]
    drift = {}
    any_drift = False

    for param in ["omega", "alpha", "beta", "gamma"]:
        if full_p[param] != 0:
            pct_change = abs(recent_p[param] - full_p[param]) / abs(full_p[param]) * 100
        else:
            pct_change = 0 if recent_p[param] == 0 else 100

        drifted = pct_change > 15
        if drifted:
            any_drift = True

        drift[param] = {
            "full": round(full_p[param], 6),
            "recent": round(recent_p[param], 6),
            "pct_change": round(pct_change, 1),
            "drifted": drifted,
        }

    return {
        "ticker": ticker,
        "full_window": results["full"],
        "recent_window": results["recent"],
        "drift": drift,
        "any_drift": any_drift,
        "model_misspecified": not results["recent"]["ljung_box_pass"],
    }


def _chi2_survival(x, df):
    """Approximate chi-squared survival function P(X > x)."""
    # Wilson-Hilferty approximation
    if x <= 0:
        return 1.0
    z = ((x / df) ** (1/3) - (1 - 2 / (9 * df))) / np.sqrt(2 / (9 * df))
    # Normal CDF approximation
    from math import erf, sqrt
    p = 0.5 * (1 + erf(z / sqrt(2)))
    return max(0, 1 - p)


# ──────────────────────────────────────────────────────────────
# 8C: Circuit Breakers
# ──────────────────────────────────────────────────────────────

# VIX thresholds
VIX_CIRCUIT_BREAKERS = {
    "reduce_sizing": {"vix": 35, "action": "Reduce position sizes 50%, halt single-name selling"},
    "halt_selling": {"vix": 45, "action": "HALT all new premium selling"},
    "close_all": {"vix": 65, "action": "CLOSE all positions immediately"},
}

# Drawdown thresholds
DD_CIRCUIT_BREAKERS = {
    "reduce_sizing": {"dd_pct": 10, "action": "Reduce new position sizes by 50%"},
    "halt_selling": {"dd_pct": 15, "action": "HALT all new premium selling"},
    "close_all": {"dd_pct": 20, "action": "CLOSE all positions immediately"},
}

# Quad witching: third Friday of March, June, September, December
def _next_quad_witching(as_of=None):
    """Find the next quad witching date (3rd Friday of Mar/Jun/Sep/Dec)."""
    if as_of is None:
        as_of = datetime.now()

    quad_months = [3, 6, 9, 12]

    for offset in range(0, 13):
        month = as_of.month + offset
        year = as_of.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1

        if month not in quad_months:
            continue

        # 3rd Friday: find first day of month, advance to Friday, add 2 weeks
        first = datetime(year, month, 1)
        # days until Friday (4 = Friday)
        days_to_friday = (4 - first.weekday()) % 7
        third_friday = first + timedelta(days=days_to_friday + 14)

        if third_friday.date() >= as_of.date():
            return third_friday, (third_friday - as_of).days

    return None, None


def check_circuit_breakers(vix_level: float = None,
                           portfolio_drawdown_pct: float = None,
                           fomc_days: int = None,
                           earnings_days: dict = None,
                           open_tickers: list = None) -> dict:
    """
    Check all circuit breakers and return active alerts.

    Args:
        vix_level: Current VIX level
        portfolio_drawdown_pct: Current portfolio drawdown as positive %
        fomc_days: Days until next FOMC
        earnings_days: Dict of {ticker: days_until_earnings}
        open_tickers: List of tickers with open positions

    Returns:
        dict with active breakers, sizing adjustments, blocked tickers
    """
    alerts = []
    sizing_multiplier = 1.0
    blocked_tickers = []
    halt_new = False
    close_all = False

    # VIX-based
    if vix_level is not None:
        if vix_level >= 65:
            alerts.append({
                "type": "VIX", "severity": "CRITICAL",
                "message": f"VIX at {vix_level:.1f} — CLOSE ALL POSITIONS",
                "action": VIX_CIRCUIT_BREAKERS["close_all"]["action"],
            })
            close_all = True
        elif vix_level >= 45:
            alerts.append({
                "type": "VIX", "severity": "HIGH",
                "message": f"VIX at {vix_level:.1f} — HALT all new selling",
                "action": VIX_CIRCUIT_BREAKERS["halt_selling"]["action"],
            })
            halt_new = True
        elif vix_level >= 35:
            alerts.append({
                "type": "VIX", "severity": "MODERATE",
                "message": f"VIX at {vix_level:.1f} — reduce sizing 50%",
                "action": VIX_CIRCUIT_BREAKERS["reduce_sizing"]["action"],
            })
            sizing_multiplier = min(sizing_multiplier, 0.5)

    # Drawdown-based
    if portfolio_drawdown_pct is not None and portfolio_drawdown_pct > 0:
        if portfolio_drawdown_pct >= 20:
            alerts.append({
                "type": "DRAWDOWN", "severity": "CRITICAL",
                "message": f"Portfolio drawdown {portfolio_drawdown_pct:.1f}% — CLOSE ALL",
                "action": DD_CIRCUIT_BREAKERS["close_all"]["action"],
            })
            close_all = True
        elif portfolio_drawdown_pct >= 15:
            alerts.append({
                "type": "DRAWDOWN", "severity": "HIGH",
                "message": f"Portfolio drawdown {portfolio_drawdown_pct:.1f}% — HALT new selling",
                "action": DD_CIRCUIT_BREAKERS["halt_selling"]["action"],
            })
            halt_new = True
        elif portfolio_drawdown_pct >= 10:
            alerts.append({
                "type": "DRAWDOWN", "severity": "MODERATE",
                "message": f"Portfolio drawdown {portfolio_drawdown_pct:.1f}% — reduce sizing 50%",
                "action": DD_CIRCUIT_BREAKERS["reduce_sizing"]["action"],
            })
            sizing_multiplier = min(sizing_multiplier, 0.5)

    # Calendar: FOMC
    if fomc_days is not None and fomc_days <= 2 and fomc_days >= 0:
        alerts.append({
            "type": "CALENDAR", "severity": "MODERATE",
            "message": f"FOMC decision in {fomc_days} day(s) — no new trades",
            "action": "Wait until after FOMC announcement to open positions",
        })
        halt_new = True

    # Calendar: Earnings
    if earnings_days and open_tickers:
        for ticker in open_tickers:
            days = earnings_days.get(ticker)
            if days is not None and 0 <= days <= 5:
                alerts.append({
                    "type": "EARNINGS", "severity": "MODERATE",
                    "message": f"{ticker} earnings in {days} day(s)",
                    "action": f"No new trades on {ticker} until after earnings",
                })
                blocked_tickers.append(ticker)

    # Calendar: Quad witching
    qw_date, qw_days = _next_quad_witching()
    if qw_days is not None and 0 <= qw_days <= 5:
        alerts.append({
            "type": "CALENDAR", "severity": "LOW",
            "message": f"Quad witching in {qw_days} day(s) ({qw_date.strftime('%Y-%m-%d')})",
            "action": "Reduce position sizes 25% — elevated pin risk and erratic moves",
        })
        sizing_multiplier = min(sizing_multiplier, 0.75)

    return {
        "alerts": alerts,
        "sizing_multiplier": sizing_multiplier,
        "halt_new_trades": halt_new,
        "close_all_positions": close_all,
        "blocked_tickers": blocked_tickers,
        "n_alerts": len(alerts),
        "max_severity": (
            "CRITICAL" if any(a["severity"] == "CRITICAL" for a in alerts) else
            "HIGH" if any(a["severity"] == "HIGH" for a in alerts) else
            "MODERATE" if any(a["severity"] == "MODERATE" for a in alerts) else
            "LOW" if alerts else "NONE"
        ),
    }


# ──────────────────────────────────────────────────────────────
# Combined: Run all Module 8 checks
# ──────────────────────────────────────────────────────────────

def run_all_monitoring(pred_df: pd.DataFrame = None,
                       hist: pd.DataFrame = None,
                       ticker: str = "",
                       vix_level: float = None,
                       portfolio_drawdown_pct: float = None,
                       fomc_days: int = None) -> dict:
    """
    Run all monitoring checks.

    Args:
        pred_df: Scored predictions DataFrame (for CUSUM)
        hist: Price history DataFrame (for GARCH drift)
        ticker: Ticker for GARCH drift test
        vix_level: Current VIX
        portfolio_drawdown_pct: Current drawdown %
        fomc_days: Days until next FOMC
    """
    results = {}

    # 8A: CUSUM
    if pred_df is not None and "pnl_pct" in pred_df.columns:
        print("[8A] CUSUM edge erosion detection...")
        pnl = pred_df["pnl_pct"].dropna()
        dates = pred_df.loc[pnl.index, "date"] if "date" in pred_df.columns else None
        results["cusum"] = cusum_edge_detection(pnl, dates)
    else:
        results["cusum"] = {"error": "No P&L data for CUSUM"}

    # 8B: GARCH drift
    if hist is not None and len(hist) >= 1000:
        print("[8B] GARCH parameter drift...")
        results["garch_drift"] = garch_parameter_drift(hist, ticker)
    else:
        results["garch_drift"] = {"error": "Need 1000+ days of history for GARCH drift"}

    # 8C: Circuit breakers
    print("[8C] Circuit breakers...")
    results["circuit_breakers"] = check_circuit_breakers(
        vix_level=vix_level,
        portfolio_drawdown_pct=portfolio_drawdown_pct,
        fomc_days=fomc_days,
    )

    return results


# ──────────────────────────────────────────────────────────────
# CLI runner
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from db import _get_supabase, _get_sqlite
    import sys

    print("=" * 70)
    print("MODULE 8: Monitoring & Edge Erosion")
    print("=" * 70)

    # Load scored predictions
    sb = _get_supabase()
    if sb:
        print("[monitor] Loading from Supabase...")
        resp = sb.table("predictions").select("*").eq("scored", 1).order("date").execute()
        data = resp.data or []
        pred_df = pd.DataFrame(data) if data else pd.DataFrame()
    else:
        print("[monitor] Loading from SQLite...")
        conn = _get_sqlite()
        pred_df = pd.read_sql_query(
            "SELECT * FROM predictions WHERE scored = 1 ORDER BY date", conn
        )
        conn.close()

    # Fetch SPY for GARCH drift test
    hist = None
    try:
        import yfinance as yf
        print("[monitor] Fetching SPY history for GARCH drift...")
        hist = yf.download("SPY", period="5y", progress=False)
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
    except Exception as e:
        print(f"[monitor] Could not fetch SPY: {e}")

    # Get current VIX
    vix_level = None
    try:
        import yfinance as yf
        vix = yf.download("^VIX", period="5d", progress=False)
        if isinstance(vix.columns, pd.MultiIndex):
            vix.columns = vix.columns.get_level_values(0)
        if not vix.empty:
            vix_level = float(vix["Close"].iloc[-1])
    except Exception:
        pass

    # FOMC
    try:
        from analytics import get_next_fomc_date
        _, fomc_days = get_next_fomc_date()
    except Exception:
        fomc_days = None

    results = run_all_monitoring(
        pred_df=pred_df, hist=hist, ticker="SPY",
        vix_level=vix_level, fomc_days=fomc_days,
    )

    # ── Print results ──
    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)

    # 8A: CUSUM
    print("\n--- 8A: CUSUM Edge Erosion ---")
    cusum = results.get("cusum", {})
    if cusum.get("error"):
        print(f"  Error: {cusum['error']}")
    else:
        print(f"  Current CUSUM: {cusum['current_cusum']:.4f} (threshold: {cusum['threshold']:.1f})")
        print(f"  Overall IR: {cusum['current_ir']:.4f}")
        if cusum.get("recent_ir") is not None:
            print(f"  Early IR: {cusum['early_ir']:.4f} → Recent IR: {cusum['recent_ir']:.4f} "
                  f"(trend: {cusum['ir_trend']:+.4f})")
        if cusum["alert"]:
            print(f"  ⚠ ALERT: CUSUM crossed threshold at trade #{cusum['alert_trade_idx']}!")
            print(f"    Edge may have eroded. Investigate before opening new positions.")
        else:
            print(f"  ✓ No edge erosion detected")

    # 8B: GARCH Drift
    print("\n--- 8B: GARCH Parameter Drift ---")
    gd = results.get("garch_drift", {})
    if gd.get("error"):
        print(f"  Error: {gd['error']}")
    else:
        print(f"  {'Param':<8} {'Full (1000d)':>12} {'Recent (500d)':>14} {'Change':>8} {'Drift':>6}")
        print("  " + "-" * 52)
        for param, d in gd["drift"].items():
            flag = " ⚠" if d["drifted"] else ""
            print(f"  {param:<8} {d['full']:>12.6f} {d['recent']:>14.6f} "
                  f"{d['pct_change']:>7.1f}%{flag}")

        if gd["any_drift"]:
            print(f"\n  ⚠ Parameter drift detected — model may need recalibration")
        else:
            print(f"\n  ✓ Parameters stable")

        lb = gd["recent_window"]
        if lb.get("ljung_box_pass") is False:
            print(f"  ⚠ Ljung-Box FAILS (p={lb['ljung_box_p']:.4f}) — model misspecified")
        elif lb.get("ljung_box_pass") is True:
            print(f"  ✓ Ljung-Box passes (p={lb['ljung_box_p']:.4f})")

    # 8C: Circuit Breakers
    print("\n--- 8C: Circuit Breakers ---")
    cb = results.get("circuit_breakers", {})
    if vix_level:
        print(f"  VIX: {vix_level:.1f}")
    if fomc_days is not None:
        print(f"  FOMC: {fomc_days} days away")

    qw_date, qw_days = _next_quad_witching()
    if qw_days is not None:
        print(f"  Quad witching: {qw_days} days ({qw_date.strftime('%Y-%m-%d')})")

    if cb.get("alerts"):
        print(f"\n  ACTIVE ALERTS ({cb['n_alerts']}):")
        for a in cb["alerts"]:
            sev_icon = {"CRITICAL": "🚨", "HIGH": "⚠", "MODERATE": "⚡", "LOW": "ℹ"}.get(a["severity"], "")
            print(f"    {sev_icon} [{a['severity']}] {a['message']}")
            print(f"       Action: {a['action']}")

        print(f"\n  Sizing multiplier: {cb['sizing_multiplier']:.0%}")
        if cb["halt_new_trades"]:
            print(f"  ⛔ NEW TRADES HALTED")
        if cb["close_all_positions"]:
            print(f"  🚨 CLOSE ALL POSITIONS")
    else:
        print(f"\n  ✓ No circuit breakers active. All clear.")

    # Verdict
    print(f"\n{'='*70}")
    print("VERDICT")
    print("=" * 70)

    issues = []
    if not cusum.get("error") and cusum.get("alert"):
        issues.append("CUSUM edge erosion alert — strategy may no longer work")
    if not gd.get("error") and gd.get("any_drift"):
        issues.append("GARCH parameters have drifted — recalibrate model")
    if not gd.get("error") and gd.get("model_misspecified"):
        issues.append("GARCH residuals fail Ljung-Box — model misspecified")
    if cb.get("close_all_positions"):
        issues.append("CRITICAL circuit breaker — close all positions NOW")
    elif cb.get("halt_new_trades"):
        issues.append("Circuit breaker — halt new trades")

    if issues:
        print("ALERTS:")
        for i in issues:
            print(f"  ! {i}")
    else:
        print("All monitoring checks pass. Strategy is operating normally.")
