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


# ============================================================
# PHASE-AWARE POSITION SIZING
# ============================================================

PHASES = {
    "paper": {"label": "Paper Trading", "max_contracts": 0, "max_positions": 0, "max_pct": 0, "min_weeks": 8},
    "starter": {"label": "Starter (1 Contract)", "max_contracts": 1, "max_positions": 3, "max_pct": 0, "min_weeks": 8},
    "quarter_kelly": {"label": "Quarter-Kelly", "max_contracts": None, "max_positions": 6, "max_pct": 0.03, "min_weeks": 16},
    "full": {"label": "Full Deployment", "max_contracts": None, "max_positions": 10, "max_pct": 0.05, "min_weeks": 0},
}


def get_position_size(portfolio_value, strike_price, current_phase="paper"):
    """
    Enforce phase-appropriate position sizing for cash-secured puts.

    Returns:
        (contracts: int, reason: str)
    """
    phase = PHASES.get(current_phase, PHASES["paper"])

    if current_phase == "paper":
        return 0, "Paper trading only — no real contracts"

    if current_phase == "starter":
        return 1, "Starter phase — max 1 contract per trade"

    if phase["max_pct"] > 0 and strike_price > 0:
        max_capital = portfolio_value * phase["max_pct"]
        contracts = max(1, int(max_capital / (strike_price * 100)))
        if phase.get("max_contracts"):
            contracts = min(contracts, phase["max_contracts"])
        return contracts, f"{phase['label']} — {phase['max_pct']:.0%} of portfolio per position"

    return 1, "Default 1 contract"


def size_covered_call(shares_owned, existing_calls=0, cover_pct=0.25):
    """
    How many covered calls to sell on shares you already own.

    Args:
        shares_owned: total shares of this ticker
        existing_calls: calls already sold on this ticker
        cover_pct: fraction of shares to cover (0.25 = conservative)

    Returns:
        (contracts: int, reason: str)
    """
    if shares_owned < 100:
        return 0, f"Need at least 100 shares to sell covered calls (have {shares_owned})"

    max_calls = shares_owned // 100
    available = max_calls - existing_calls
    if available <= 0:
        return 0, f"All {max_calls * 100} shares already covered"

    target = max(1, int(max_calls * cover_pct))
    new_calls = min(target - existing_calls, available)
    new_calls = max(0, new_calls)

    covered_shares = (existing_calls + new_calls) * 100
    return new_calls, f"Cover {covered_shares} of {shares_owned} shares ({covered_shares/shares_owned:.0%})"


def size_cash_secured_put(portfolio_value, available_cash, strike_price,
                           current_phase="paper", max_pct=0.03):
    """
    How many cash-secured puts to sell.

    Args:
        portfolio_value: total portfolio value
        available_cash: cash not committed to other positions
        strike_price: put strike price
        current_phase: deployment phase
        max_pct: max % of portfolio per position

    Returns:
        (contracts: int, reason: str)
    """
    if current_phase == "paper":
        return 0, "Paper only"
    if current_phase == "starter":
        return 1, "Starter: max 1 contract"

    capital_per = strike_price * 100

    # Limit 1: max % of portfolio
    max_from_portfolio = int(portfolio_value * max_pct / capital_per) if capital_per > 0 else 0

    # Limit 2: available cash (keep 25% reserve)
    usable_cash = available_cash * 0.75
    max_from_cash = int(usable_cash / capital_per) if capital_per > 0 else 0

    contracts = max(0, min(max_from_portfolio, max_from_cash))
    committed = contracts * capital_per

    if contracts == 0 and max_from_portfolio > 0:
        return 0, f"Insufficient cash (need ${capital_per:,} per contract, have ${available_cash:,.0f} usable)"
    elif contracts == 0:
        return 0, f"Position would exceed {max_pct:.0%} of portfolio"

    return contracts, f"{contracts} contract{'s' if contracts > 1 else ''} (${committed:,} committed, keeping 25% cash reserve)"


def check_concentration(ticker, current_exposure, portfolio_value, max_pct=0.15):
    """Don't let any single name exceed max_pct of portfolio."""
    if portfolio_value <= 0:
        return True, "Unknown portfolio value"
    current_pct = current_exposure / portfolio_value
    if current_pct > max_pct:
        return False, f"{ticker} is {current_pct:.0%} of portfolio (max {max_pct:.0%}). Don't add more exposure."
    return True, f"{ticker} is {current_pct:.0%} of portfolio. Room to add."


def check_position_limits(open_positions, current_phase="paper"):
    """
    Check if adding a new position would violate phase limits.

    Returns:
        (can_add: bool, reason: str)
    """
    phase = PHASES.get(current_phase, PHASES["paper"])
    max_pos = phase["max_positions"]

    if current_phase == "paper":
        return True, "Paper trading — track unlimited"

    n_open = len(open_positions) if open_positions else 0
    if n_open >= max_pos:
        return False, f"At position limit ({n_open}/{max_pos} for {phase['label']})"

    return True, f"{n_open}/{max_pos} positions open"
