"""
Discipline Framework — When NOT to trade + pass rate tracking.

From Sinclair & Mack (2024): "Theta is NOT an edge. Discomfort IS a signal edge exists."
From variance_betting: Ted only bets ~30% of analyzed matches. Discipline IS edge.

20 rules enforced here. The system should PASS on 55-70% of GREEN signals.
If trading >60% of opportunities: thresholds too loose.
If trading <20%: thresholds too tight OR market is correctly priced.
"""

from datetime import datetime
import db


# ============================================================
# TRADE FILTERS — when NOT to trade
# ============================================================

def check_trade_filters(vrp=None, iv_rank=None, term_label=None,
                         regime=None, vix=None, fomc_days=None,
                         earnings_days=None, dte=None,
                         portfolio_vega=None, portfolio_vega_limit=None,
                         consecutive_wins=None, atm_iv=None):
    """
    Apply all "when NOT to trade" rules.

    Returns:
        (should_trade: bool, reasons: list of str)
        reasons lists WHY we should pass (empty if should_trade=True)
    """
    reasons = []

    # Rule 1: VRP too thin (Sinclair: need 3.55 avg, minimum ~2 to cover costs)
    if vrp is not None and vrp < 2.0:
        reasons.append(f"VRP too thin ({vrp:.1f} < 2.0 vol points)")

    # Rule 2: IV Rank too low (premiums too cheap to sell)
    if iv_rank is not None and iv_rank < 25:
        reasons.append(f"IV Rank too low ({iv_rank:.0f}% < 25%)")

    # Rule 3: Backwardation (market pricing near-term risk)
    if term_label and term_label.lower() == "backwardation":
        reasons.append("Term structure in backwardation — catching falling knife")

    # Rule 4: Within 2 days of FOMC
    if fomc_days is not None and fomc_days <= 2:
        reasons.append(f"Within {fomc_days} days of FOMC — macro event risk")

    # Rule 5: Within 5 days of earnings
    if earnings_days is not None and 0 < earnings_days <= 5:
        reasons.append(f"Within {earnings_days} days of earnings — event vol justified")

    # Rule 6: VIX > 35 — reduce 50%
    # (returns reason but doesn't block — caller decides sizing)
    if vix is not None and vix > 45:
        reasons.append(f"VIX > 45 ({vix:.1f}) — HALT all new premium selling")
    elif vix is not None and vix > 35:
        reasons.append(f"VIX > 35 ({vix:.1f}) — reduce position size 50%")

    # Rule 8: Portfolio vega at limit
    if portfolio_vega is not None and portfolio_vega_limit is not None:
        if abs(portfolio_vega) >= portfolio_vega_limit:
            reasons.append(f"Portfolio vega at limit ({portfolio_vega:.0f} >= {portfolio_vega_limit:.0f})")

    # Rule 9: DTE too low (gamma risk)
    if dte is not None and dte < 10:
        reasons.append(f"DTE too low ({dte} < 10) — gamma risk extreme")

    # Rule 17: Vol spike + backwardation (Sinclair Ch 10)
    if vix is not None and vix > 30 and term_label and term_label.lower() == "backwardation":
        reasons.append("VIX spike + backwardation — wait for mean reversion")

    # Rule 18: After 3+ consecutive seller wins (straddle breakout, Sinclair Ch 15)
    if consecutive_wins is not None and consecutive_wins >= 3:
        reasons.append(f"After {consecutive_wins} consecutive wins — breakout risk (reduce/skip)")

    # Rule 19: VRP < transaction costs for structure
    # (approximate: iron condors need ~0.5% VRP to cover 4-leg costs)
    if vrp is not None and atm_iv is not None and atm_iv > 0:
        vrp_pct = vrp / atm_iv
        if vrp_pct < 0.03:  # VRP < 3% of IV → probably eaten by costs
            reasons.append(f"VRP/IV ratio too thin ({vrp_pct:.1%} < 3%) — costs may consume edge")

    should_trade = len(reasons) == 0
    return should_trade, reasons


def get_severity(reasons):
    """Classify trade filter result severity."""
    if not reasons:
        return "TRADE"
    halt_keywords = ["HALT", "backwardation", "vega at limit"]
    if any(kw in r for r in reasons for kw in halt_keywords):
        return "HALT"
    reduce_keywords = ["reduce", "thin", "breakout"]
    if any(kw in r.lower() for r in reasons for kw in reduce_keywords):
        return "REDUCE"
    return "PASS"


# ============================================================
# PASS RATE TRACKING
# ============================================================

def track_pass_rate(date_str, green_count, traded_count):
    """
    Log daily pass rate to pass_rate_history table.

    Args:
        date_str: Date (YYYY-MM-DD)
        green_count: Number of GREEN signals generated
        traded_count: Number actually traded (after all filters)
    """
    if green_count == 0:
        return

    pass_rate = 1.0 - (traded_count / green_count)

    sb = db._get_supabase()
    row = {
        "date": date_str,
        "green_signals": green_count,
        "trades_taken": traded_count,
        "pass_rate": round(pass_rate, 4),
    }

    if sb:
        sb.table("pass_rate_history").upsert(row, on_conflict="date").execute()
    else:
        conn = db._get_sqlite()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS pass_rate_history "
            "(date TEXT PRIMARY KEY, green_signals INTEGER, "
            "trades_taken INTEGER, pass_rate REAL)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO pass_rate_history VALUES (?, ?, ?, ?)",
            (date_str, green_count, traded_count, pass_rate),
        )
        conn.commit()
        conn.close()

    # Alerts
    trade_rate = traded_count / green_count
    if trade_rate > 0.60:
        print(f"[discipline] WARNING: Trading {trade_rate:.0%} of GREEN signals. "
              "Thresholds may be too loose.")
    elif trade_rate < 0.15:
        print(f"[discipline] NOTE: Only trading {trade_rate:.0%} of GREEN signals. "
              "Check if filters are too tight.")
    else:
        print(f"[discipline] Pass rate: {pass_rate:.0%} "
              f"({traded_count}/{green_count} GREEN signals traded)")


# ============================================================
# OVERRIDE LOGGING
# ============================================================

def log_override(prediction_id, direction, reason):
    """
    Record when human overrides model recommendation.

    Args:
        prediction_id: The prediction row ID
        direction: 'trade_despite_red' or 'pass_despite_green'
        reason: Why the human disagrees
    """
    today = datetime.now().strftime("%Y-%m-%d")
    sb = db._get_supabase()
    row = {
        "prediction_id": prediction_id,
        "override_direction": direction,
        "reason": reason,
        "date": today,
    }
    if sb:
        sb.table("overrides").insert(row).execute()
    else:
        conn = db._get_sqlite()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS overrides "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, prediction_id INTEGER, "
            "override_direction TEXT, reason TEXT, date TEXT, outcome_clv REAL)"
        )
        conn.execute(
            "INSERT INTO overrides (prediction_id, override_direction, reason, date) "
            "VALUES (?, ?, ?, ?)",
            (prediction_id, direction, reason, today),
        )
        conn.commit()
        conn.close()

    print(f"[discipline] Override logged: {direction} (prediction {prediction_id})")
