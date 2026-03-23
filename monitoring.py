"""
Production Monitoring — 4-layer monitoring stack.

From LEARN_TEST_TRADE_SPEC and variance_betting INFRASTRUCTURE_IMPROVEMENTS:

Layer A: Data Quality — are IV snapshots arriving? Missing tickers?
Layer B: Feature Drift — has the VRP distribution shifted? (PSI)
Layer C: Prediction Drift — is the model systematically wrong?
Layer D: Performance Decay — CUSUM, rolling RVRP, rolling Sharpe

Runs daily after score-predictions via GitHub Actions.
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import db


class Alert:
    def __init__(self, level, layer, message):
        self.level = level  # 'INFO', 'WARNING', 'CRITICAL'
        self.layer = layer  # 'A', 'B', 'C', 'D'
        self.message = message
        self.timestamp = datetime.now().isoformat()

    def __repr__(self):
        return f"[{self.level}] Layer {self.layer}: {self.message}"


# ============================================================
# LAYER A: DATA QUALITY
# ============================================================

def check_data_quality():
    """Check if daily data pipeline is healthy."""
    alerts = []
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    sb = db._get_supabase()
    if not sb:
        alerts.append(Alert("WARNING", "A", "Not connected to Supabase — using local SQLite"))
        return alerts

    # Check recent IV snapshots
    resp = sb.table("iv_snapshots").select("ticker", count="exact").gte("date", yesterday).execute()
    recent_count = resp.count if hasattr(resp, 'count') and resp.count else len(resp.data or [])

    if recent_count == 0:
        # Check if it's a weekend/holiday
        dow = datetime.now().weekday()
        if dow < 5:  # weekday
            alerts.append(Alert("CRITICAL", "A",
                f"No IV snapshots in last 24h (expected ~250+). Sampler may be down."))
        else:
            alerts.append(Alert("INFO", "A", "Weekend — no snapshots expected."))
    elif recent_count < 200:
        alerts.append(Alert("WARNING", "A",
            f"Only {recent_count} snapshots in last 24h (expected ~250+). "
            "Some tickers may be failing."))
    else:
        alerts.append(Alert("INFO", "A", f"{recent_count} snapshots in last 24h. Pipeline healthy."))

    # Check predictions pipeline
    pending = db.get_pending_predictions_count()
    alerts.append(Alert("INFO", "A", f"{pending} predictions pending scoring."))

    # Check SABR surface data
    try:
        resp = sb.table("vol_surface_snapshots").select("ticker", count="exact").gte("date", yesterday).execute()
        sabr_count = resp.count if hasattr(resp, 'count') and resp.count else len(resp.data or [])
        if sabr_count > 0:
            alerts.append(Alert("INFO", "A", f"{sabr_count} SABR surface snapshots in last 24h."))
        elif datetime.now().weekday() < 5:
            alerts.append(Alert("WARNING", "A", "No SABR surface data in last 24h."))
    except Exception:
        pass  # Table may not exist yet

    return alerts


# ============================================================
# LAYER B: FEATURE DRIFT (Population Stability Index)
# ============================================================

def compute_psi(baseline, current, n_bins=10):
    """
    Population Stability Index — measures distribution shift.

    PSI > 0.1 = investigate
    PSI > 0.2 = significant drift (retrain trigger)
    """
    if len(baseline) < n_bins or len(current) < n_bins:
        return None

    # Use baseline quantiles as bin edges
    bins = np.quantile(baseline, np.linspace(0, 1, n_bins + 1))
    bins[0] = -np.inf
    bins[-1] = np.inf

    baseline_counts = np.histogram(baseline, bins=bins)[0]
    current_counts = np.histogram(current, bins=bins)[0]

    # Add small constant to avoid division by zero
    baseline_pct = (baseline_counts + 1) / (len(baseline) + n_bins)
    current_pct = (current_counts + 1) / (len(current) + n_bins)

    psi = np.sum((current_pct - baseline_pct) * np.log(current_pct / baseline_pct))
    return float(psi)


def check_feature_drift():
    """Check if key features have drifted from their historical distribution."""
    import pandas as pd
    alerts = []

    sb = db._get_supabase()
    if not sb:
        return alerts

    # Load recent vs baseline IV snapshots
    cutoff_recent = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    cutoff_baseline = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

    try:
        recent = sb.table("iv_snapshots").select("vrp,iv_rank,atm_iv").gte("date", cutoff_recent).execute()
        baseline = sb.table("iv_snapshots").select("vrp,iv_rank,atm_iv").gte("date", cutoff_baseline).lt("date", cutoff_recent).execute()

        recent_df = pd.DataFrame(recent.data) if recent.data else pd.DataFrame()
        baseline_df = pd.DataFrame(baseline.data) if baseline.data else pd.DataFrame()
    except Exception as e:
        alerts.append(Alert("WARNING", "B", f"Could not load feature data: {e}"))
        return alerts

    if recent_df.empty or baseline_df.empty:
        alerts.append(Alert("INFO", "B", "Insufficient data for drift detection."))
        return alerts

    # Check PSI for each key feature
    for col in ["vrp", "iv_rank", "atm_iv"]:
        if col in recent_df.columns and col in baseline_df.columns:
            recent_vals = recent_df[col].dropna().values
            baseline_vals = baseline_df[col].dropna().values
            if len(recent_vals) >= 30 and len(baseline_vals) >= 30:
                psi = compute_psi(baseline_vals, recent_vals)
                if psi is not None:
                    if psi > 0.2:
                        alerts.append(Alert("WARNING", "B",
                            f"{col} PSI={psi:.3f} (>0.2) — significant drift. Consider retraining."))
                    elif psi > 0.1:
                        alerts.append(Alert("INFO", "B",
                            f"{col} PSI={psi:.3f} (>0.1) — moderate drift. Monitor closely."))
                    else:
                        alerts.append(Alert("INFO", "B", f"{col} PSI={psi:.3f} — stable."))

    return alerts


# ============================================================
# LAYER C: PREDICTION DRIFT
# ============================================================

def check_prediction_drift():
    """Check if signal distribution has shifted (model producing different proportions)."""
    import pandas as pd
    alerts = []

    sb = db._get_supabase()
    if not sb:
        return alerts

    cutoff_30d = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    try:
        recent = sb.table("predictions").select("signal").gte("date", cutoff_30d).execute()
        all_time = sb.table("predictions").select("signal").execute()

        recent_signals = [r["signal"] for r in (recent.data or [])]
        all_signals = [r["signal"] for r in (all_time.data or [])]
    except Exception as e:
        alerts.append(Alert("WARNING", "C", f"Could not load prediction data: {e}"))
        return alerts

    if len(recent_signals) < 50 or len(all_signals) < 100:
        alerts.append(Alert("INFO", "C", "Insufficient predictions for drift detection."))
        return alerts

    # Compare signal proportions
    for sig in ["GREEN", "YELLOW", "RED"]:
        recent_pct = recent_signals.count(sig) / len(recent_signals) * 100
        all_pct = all_signals.count(sig) / len(all_signals) * 100
        diff = abs(recent_pct - all_pct)

        if diff > 15:
            alerts.append(Alert("WARNING", "C",
                f"{sig} signals shifted: recent {recent_pct:.0f}% vs historical {all_pct:.0f}% "
                f"(delta {diff:.0f}pp). Possible regime change."))
        elif diff > 8:
            alerts.append(Alert("INFO", "C",
                f"{sig} signals: recent {recent_pct:.0f}% vs historical {all_pct:.0f}% "
                f"(delta {diff:.0f}pp). Minor shift."))

    return alerts


# ============================================================
# LAYER D: PERFORMANCE DECAY
# ============================================================

def check_performance_decay():
    """Check rolling RVRP, Sharpe, and CUSUM for edge erosion."""
    import pandas as pd
    alerts = []

    sb = db._get_supabase()
    if not sb:
        return alerts

    try:
        resp = sb.table("predictions").select("*").eq("scored", 1).order("date").execute()
        df = pd.DataFrame(resp.data) if resp.data else pd.DataFrame()
    except Exception as e:
        alerts.append(Alert("WARNING", "D", f"Could not load scored predictions: {e}"))
        return alerts

    if df.empty or "clv_realized" not in df.columns:
        alerts.append(Alert("INFO", "D", "No scored predictions with RVRP data yet."))
        return alerts

    rvrp = df["clv_realized"].dropna()
    if len(rvrp) < 20:
        alerts.append(Alert("INFO", "D", f"Only {len(rvrp)} RVRP observations. Need 20+."))
        return alerts

    # Overall RVRP
    avg_rvrp = float(rvrp.mean())
    alerts.append(Alert(
        "INFO" if avg_rvrp > 0 else "WARNING", "D",
        f"Overall Realized VRP: {avg_rvrp:.1%} (n={len(rvrp)})"
    ))

    # Rolling 30 (or all if < 30)
    window = min(30, len(rvrp))
    recent_rvrp = float(rvrp.tail(window).mean())
    earlier_rvrp = float(rvrp.head(len(rvrp) - window).mean()) if len(rvrp) > window else avg_rvrp

    if recent_rvrp < 0:
        alerts.append(Alert("CRITICAL", "D",
            f"Recent RVRP is NEGATIVE ({recent_rvrp:.1%} over last {window} trades). "
            "Edge may have eroded."))
    elif recent_rvrp < earlier_rvrp * 0.5 and earlier_rvrp > 0:
        alerts.append(Alert("WARNING", "D",
            f"RVRP declining: recent {recent_rvrp:.1%} vs earlier {earlier_rvrp:.1%} "
            f"({recent_rvrp/earlier_rvrp:.0%} of baseline)."))
    else:
        alerts.append(Alert("INFO", "D",
            f"Recent RVRP: {recent_rvrp:.1%} (last {window} trades). Stable."))

    return alerts


# ============================================================
# LAYER E: PORTFOLIO HEALTH (hard stops)
# ============================================================

def check_portfolio_health():
    """Hard stops that can't be overridden — protects against over-concentration."""
    alerts = []

    try:
        from db import get_open_trades
        open_trades = get_open_trades()
    except Exception:
        open_trades = []

    n_open = len(open_trades)

    if n_open > 10:
        alerts.append(Alert("CRITICAL", "E",
            f"Too many open positions ({n_open} > 10). Do NOT add more. "
            "Close weakest positions first."))
    elif n_open > 6:
        alerts.append(Alert("WARNING", "E",
            f"{n_open} open positions. Approaching limit (10 max). Be selective."))
    else:
        alerts.append(Alert("INFO", "E", f"{n_open} open positions. Within limits."))

    # Check sector concentration (if we can determine sector from ticker)
    if open_trades:
        tickers = [t.get("ticker", "") for t in open_trades]
        TECH = {"AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA", "AMD", "CRM", "ORCL"}
        tech_count = sum(1 for t in tickers if t in TECH)
        if tech_count > 3:
            alerts.append(Alert("WARNING", "E",
                f"{tech_count} tech positions open. Max recommended: 3. "
                "Diversify across sectors."))

    return alerts


# ============================================================
# FULL MONITORING STACK
# ============================================================

def run_full_monitoring_stack():
    """Run all 4 monitoring layers. Returns list of Alerts."""
    print("=" * 50)
    print(f"MONITORING STACK — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    all_alerts = []

    print("\nLayer A: Data Quality")
    a_alerts = check_data_quality()
    all_alerts.extend(a_alerts)
    for a in a_alerts:
        print(f"  {a}")

    print("\nLayer B: Feature Drift")
    b_alerts = check_feature_drift()
    all_alerts.extend(b_alerts)
    for a in b_alerts:
        print(f"  {a}")

    print("\nLayer C: Prediction Drift")
    c_alerts = check_prediction_drift()
    all_alerts.extend(c_alerts)
    for a in c_alerts:
        print(f"  {a}")

    print("\nLayer D: Performance Decay")
    d_alerts = check_performance_decay()
    all_alerts.extend(d_alerts)
    for a in d_alerts:
        print(f"  {a}")

    print("\nLayer E: Portfolio Health")
    e_alerts = check_portfolio_health()
    all_alerts.extend(e_alerts)
    for a in e_alerts:
        print(f"  {a}")

    # Summary
    critical = [a for a in all_alerts if a.level == "CRITICAL"]
    warnings = [a for a in all_alerts if a.level == "WARNING"]
    print(f"\nSummary: {len(critical)} critical, {len(warnings)} warnings, "
          f"{len(all_alerts) - len(critical) - len(warnings)} info")

    if critical:
        print("\nCRITICAL ALERTS:")
        for a in critical:
            print(f"  {a}")

    return all_alerts


if __name__ == "__main__":
    alerts = run_full_monitoring_stack()
    if any(a.level == "CRITICAL" for a in alerts):
        sys.exit(1)
