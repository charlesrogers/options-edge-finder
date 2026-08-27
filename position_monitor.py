"""
Covered Call Copilot — Position Monitor

Zero assignment, maximum premium. Researched thresholds from
Experiment 006 (145,099 real observations) + Monte Carlo (480,000 paths).

Alert levels:
  SAFE       — Do nothing. 75-95% chance of keeping full premium.
  WATCH      — Check daily. Stock approaching strike.
  CLOSE_SOON — Take profit this week. Risk/reward flipping.
  CLOSE_NOW  — Buy back immediately. Assignment risk is real.
  EMERGENCY  — ITM + near ex-dividend. The $400K alert.

Priority order:
  #1 Never get called away (assignment = tax catastrophe)
  #2 Don't lose money on the buyback
  #3 Make money (keep maximum premium)
"""

from datetime import datetime, timedelta
# Unpatchable aliases: tests patch `position_monitor.datetime` to freeze "now",
# which would break isinstance() checks against it. Type checks use these.
from datetime import datetime as _datetime, date as _date
from dataclasses import dataclass
from typing import Optional

# Stdlib-only module (dataclasses + typing). Importing it here cannot drag a
# research dependency onto the safety-critical monitor's path — the failure
# mode tasks/lessons.md records for 2026-08-16, when a scipy import at module
# scope took the monitor down.
import cc_core


# ============================================================
# ITM PROBABILITY TABLE (from Study A, 145,099 observations)
# ============================================================
# Key: (pct_from_strike_bucket, dte_bucket) → P(finish ITM)
# pct_from_strike: positive = OTM (safe), negative = ITM (danger)

ITM_PROBABILITY = {
    # (pct_otm_low, pct_otm_high, dte_low, dte_high) → probability
    # >10% OTM
    (10, 100, 0, 3): 0.00,
    (10, 100, 3, 7): 0.001,
    (10, 100, 7, 14): 0.013,
    (10, 100, 14, 30): 0.023,
    (10, 100, 30, 60): 0.059,
    # 5-10% OTM
    (5, 10, 0, 3): 0.017,
    (5, 10, 3, 7): 0.082,
    (5, 10, 7, 14): 0.148,
    (5, 10, 14, 30): 0.253,
    (5, 10, 30, 60): 0.380,
    # 3-5% OTM
    (3, 5, 0, 3): 0.040,
    (3, 5, 3, 7): 0.158,
    (3, 5, 7, 14): 0.327,
    (3, 5, 14, 30): 0.423,
    (3, 5, 30, 60): 0.569,
    # 1-3% OTM
    (1, 3, 0, 3): 0.129,
    (1, 3, 3, 7): 0.319,
    (1, 3, 7, 14): 0.465,
    (1, 3, 14, 30): 0.550,
    (1, 3, 30, 60): 0.725,
    # 0-1% OTM (barely OTM)
    (0, 1, 0, 3): 0.266,
    (0, 1, 3, 7): 0.491,
    (0, 1, 7, 14): 0.558,
    (0, 1, 14, 30): 0.669,
    (0, 1, 30, 60): 0.775,
    # 0-1% ITM
    (-1, 0, 0, 3): 0.762,
    (-1, 0, 3, 7): 0.705,
    (-1, 0, 7, 14): 0.640,
    (-1, 0, 14, 30): 0.723,
    (-1, 0, 30, 60): 0.807,
    # 1-3% ITM
    (-3, -1, 0, 3): 0.912,
    (-3, -1, 3, 7): 0.847,
    (-3, -1, 7, 14): 0.771,
    (-3, -1, 14, 30): 0.832,
    (-3, -1, 30, 60): 0.877,
    # 3-5% ITM
    (-5, -3, 0, 3): 0.970,
    (-5, -3, 3, 7): 0.947,
    (-5, -3, 7, 14): 0.897,
    (-5, -3, 14, 30): 0.898,
    (-5, -3, 30, 60): 0.909,
    # >5% ITM
    (-100, -5, 0, 3): 0.979,
    (-100, -5, 3, 7): 0.986,
    (-100, -5, 7, 14): 0.967,
    (-100, -5, 14, 30): 0.972,
    (-100, -5, 30, 60): 0.984,
}


def _to_naive_datetime(value):
    """Coerce str / date / datetime / pandas Timestamp to a tz-naive datetime.

    Backtests hand us pandas Timestamps (sometimes tz-aware); the live app hands
    us 'YYYY-MM-DD' strings. Mixing the two raises TypeError on subtraction, so
    everything is normalised here rather than at each call site.
    """
    if isinstance(value, str):
        return _datetime.strptime(value[:10], "%Y-%m-%d")
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, _date) and not isinstance(value, _datetime):
        return _datetime(value.year, value.month, value.day)
    if getattr(value, "tzinfo", None) is not None:
        value = value.replace(tzinfo=None)
    return value


def lookup_itm_probability(pct_from_strike, dte):
    """
    Look up probability of finishing ITM from empirical table.
    pct_from_strike: positive = OTM (stock below strike), negative = ITM
    """
    for (lo, hi, dte_lo, dte_hi), prob in ITM_PROBABILITY.items():
        if lo <= pct_from_strike < hi and dte_lo <= dte < dte_hi:
            return prob
    # Default: if very far OTM or very long DTE
    if pct_from_strike > 10:
        return 0.05
    if pct_from_strike < -5:
        return 0.98
    return 0.50


# ============================================================
# ALERT LEVELS
# ============================================================

@dataclass
class PositionAlert:
    """Alert for a single covered call position."""
    level: str  # SAFE, WATCH, CLOSE_SOON, CLOSE_NOW, EMERGENCY
    ticker: str
    strike: float
    expiry: str
    sold_price: float
    current_stock: float
    current_option: Optional[float]
    dte: int
    days_to_exdiv: Optional[int]
    days_to_earnings: Optional[int]
    pct_from_strike: float  # positive = OTM
    premium_captured_pct: float
    p_assignment: float
    buyback_cost: Optional[float]  # per contract (x100)
    net_pnl: Optional[float]  # if closed now
    reason: str
    action: str
    # Machine-readable id of the ladder rung that fired. `level` is too coarse
    # (five CLOSE_NOW clauses share one level) and `reason` is formatted prose,
    # so neither can support a reachability audit. A clause that never fires
    # across hundreds of observations is presumed unwired, not unlucky
    # (tasks/lessons.md 2026-08-16) — that audit needs a stable key, and this is
    # it. Defaulted so no existing caller has to change.
    clause: str = "unclassified"


def assess_position(ticker, strike, expiry, sold_price, contracts,
                     current_stock, current_option_ask=None,
                     ex_div_date=None, earnings_date=None, as_of=None):
    """
    Assess a covered call position and return an alert.

    Args:
        ticker: Stock symbol
        strike: Call strike price
        expiry: Expiration date (str YYYY-MM-DD or datetime)
        sold_price: Premium received per share
        contracts: Number of contracts
        current_stock: Current stock price
        current_option_ask: Current ask to buy back (per share)
        ex_div_date: Next ex-dividend date (str or datetime or None)
        earnings_date: Next earnings date (str or datetime or None)
        as_of: Evaluation date (str YYYY-MM-DD or datetime). Defaults to now.
               Backtests MUST pass this — otherwise every DTE is measured
               against the wall clock, which collapses to 0 on historical
               expiries and silently disables every DTE-conditional rule.
    """
    today = _to_naive_datetime(as_of) if as_of is not None else datetime.now()

    # Parse dates
    expiry_dt = _to_naive_datetime(expiry)
    dte = max(0, (expiry_dt - today).days)

    days_to_exdiv = None
    if ex_div_date:
        days_to_exdiv = max(0, (_to_naive_datetime(ex_div_date) - today).days)

    days_to_earnings = None
    if earnings_date:
        days_to_earnings = max(0, (_to_naive_datetime(earnings_date) - today).days)

    # Compute metrics
    pct_from_strike = (strike - current_stock) / current_stock * 100
    is_itm = current_stock > strike

    # Premium captured
    if current_option_ask is not None and sold_price > 0:
        premium_captured_pct = (1 - current_option_ask / sold_price) * 100
    else:
        premium_captured_pct = 0

    # P(assignment) from empirical table
    p_assignment = lookup_itm_probability(pct_from_strike, dte)

    # Buyback cost
    buyback_cost = current_option_ask * 100 * contracts if current_option_ask else None
    net_pnl = (sold_price - (current_option_ask or 0)) * 100 * contracts if current_option_ask else None

    # ============================================================
    # ALERT LOGIC (priority order: EMERGENCY → CLOSE_NOW → CLOSE_SOON → WATCH → SAFE)
    # ============================================================

    # EMERGENCY: ITM + ex-div within 3 days
    if is_itm and days_to_exdiv is not None and days_to_exdiv <= 3:
        return PositionAlert(
            clause="emergency_itm_exdiv_3d",
            level="EMERGENCY", ticker=ticker, strike=strike, expiry=str(expiry)[:10],
            sold_price=sold_price, current_stock=current_stock,
            current_option=current_option_ask, dte=dte,
            days_to_exdiv=days_to_exdiv, days_to_earnings=days_to_earnings,
            pct_from_strike=round(pct_from_strike, 2),
            premium_captured_pct=round(premium_captured_pct, 1),
            p_assignment=round(p_assignment * 100, 1),
            buyback_cost=round(buyback_cost, 2) if buyback_cost else None,
            net_pnl=round(net_pnl, 2) if net_pnl else None,
            reason=f"ITM ({abs(pct_from_strike):.1f}%) + ex-dividend in {days_to_exdiv} days. "
                   f"Early exercise is virtually certain.",
            action="BUY BACK IMMEDIATELY. This is the $400K scenario. Do not wait.",
        )

    # CLOSE_NOW: ITM by any amount
    if is_itm:
        return PositionAlert(
            clause="close_now_itm",
            level="CLOSE_NOW", ticker=ticker, strike=strike, expiry=str(expiry)[:10],
            sold_price=sold_price, current_stock=current_stock,
            current_option=current_option_ask, dte=dte,
            days_to_exdiv=days_to_exdiv, days_to_earnings=days_to_earnings,
            pct_from_strike=round(pct_from_strike, 2),
            premium_captured_pct=round(premium_captured_pct, 1),
            p_assignment=round(p_assignment * 100, 1),
            buyback_cost=round(buyback_cost, 2) if buyback_cost else None,
            net_pnl=round(net_pnl, 2) if net_pnl else None,
            reason=f"Stock is {abs(pct_from_strike):.1f}% ABOVE strike. "
                   f"{p_assignment*100:.0f}% probability of assignment.",
            action="Buy back at market open. Every day you wait, it costs more.",
        )

    # CLOSE_NOW: Within 1% + ex-div within 5 days
    if pct_from_strike < 1 and days_to_exdiv is not None and days_to_exdiv <= 5:
        return PositionAlert(
            clause="close_now_near_strike_exdiv_5d",
            level="CLOSE_NOW", ticker=ticker, strike=strike, expiry=str(expiry)[:10],
            sold_price=sold_price, current_stock=current_stock,
            current_option=current_option_ask, dte=dte,
            days_to_exdiv=days_to_exdiv, days_to_earnings=days_to_earnings,
            pct_from_strike=round(pct_from_strike, 2),
            premium_captured_pct=round(premium_captured_pct, 1),
            p_assignment=round(p_assignment * 100, 1),
            buyback_cost=round(buyback_cost, 2) if buyback_cost else None,
            net_pnl=round(net_pnl, 2) if net_pnl else None,
            reason=f"Stock is only {pct_from_strike:.1f}% from strike + ex-dividend in {days_to_exdiv} days.",
            action="Buy back today. Even slightly ITM near ex-div = exercise.",
        )

    # CLOSE_NOW: DTE < 3 AND within 3% of strike
    if dte < 3 and pct_from_strike < 3:
        return PositionAlert(
            clause="close_now_dte_lt3_within_3pct",
            level="CLOSE_NOW", ticker=ticker, strike=strike, expiry=str(expiry)[:10],
            sold_price=sold_price, current_stock=current_stock,
            current_option=current_option_ask, dte=dte,
            days_to_exdiv=days_to_exdiv, days_to_earnings=days_to_earnings,
            pct_from_strike=round(pct_from_strike, 2),
            premium_captured_pct=round(premium_captured_pct, 1),
            p_assignment=round(p_assignment * 100, 1),
            buyback_cost=round(buyback_cost, 2) if buyback_cost else None,
            net_pnl=round(net_pnl, 2) if net_pnl else None,
            reason=f"Only {dte} DTE and {pct_from_strike:.1f}% from strike. "
                   f"Gamma makes anything possible in the last 3 days.",
            action="Close now. The remaining premium isn't worth the gamma risk.",
        )

    # CLOSE_NOW: Within 2% + earnings within 2 days
    if pct_from_strike < 2 and days_to_earnings is not None and days_to_earnings <= 2:
        return PositionAlert(
            clause="close_now_within_2pct_earnings_2d",
            level="CLOSE_NOW", ticker=ticker, strike=strike, expiry=str(expiry)[:10],
            sold_price=sold_price, current_stock=current_stock,
            current_option=current_option_ask, dte=dte,
            days_to_exdiv=days_to_exdiv, days_to_earnings=days_to_earnings,
            pct_from_strike=round(pct_from_strike, 2),
            premium_captured_pct=round(premium_captured_pct, 1),
            p_assignment=round(p_assignment * 100, 1),
            buyback_cost=round(buyback_cost, 2) if buyback_cost else None,
            net_pnl=round(net_pnl, 2) if net_pnl else None,
            reason=f"Earnings in {days_to_earnings} days and stock is {pct_from_strike:.1f}% from strike. "
                   f"Earnings can cause sharp moves + IV crush.",
            action="Close before earnings. The post-earnings move could push you ITM instantly.",
        )

    # CLOSE_SOON: Within 2% of strike with 7+ DTE
    if pct_from_strike < 2 and dte >= 7:
        return PositionAlert(
            clause="close_soon_within_2pct_dte_ge7",
            level="CLOSE_SOON", ticker=ticker, strike=strike, expiry=str(expiry)[:10],
            sold_price=sold_price, current_stock=current_stock,
            current_option=current_option_ask, dte=dte,
            days_to_exdiv=days_to_exdiv, days_to_earnings=days_to_earnings,
            pct_from_strike=round(pct_from_strike, 2),
            premium_captured_pct=round(premium_captured_pct, 1),
            p_assignment=round(p_assignment * 100, 1),
            buyback_cost=round(buyback_cost, 2) if buyback_cost else None,
            net_pnl=round(net_pnl, 2) if net_pnl else None,
            reason=f"Stock is {pct_from_strike:.1f}% from strike with {dte} DTE. "
                   f"{p_assignment*100:.0f}% chance of assignment.",
            action=f"Close this week. You've captured {premium_captured_pct:.0f}% of premium — take the profit.",
        )

    # CLOSE_SOON: Within 3% + DTE < 7 (gamma zone)
    # Narrowed from 5% to 3% — at 3-5% OTM with <7 DTE, P(assignment) is only 4%
    # (Study A, 145K obs). 5% was causing 39% false alarm rate in simulator.
    if pct_from_strike < 3 and dte < 7:
        return PositionAlert(
            clause="close_soon_gamma_within_3pct_dte_lt7",
            level="CLOSE_SOON", ticker=ticker, strike=strike, expiry=str(expiry)[:10],
            sold_price=sold_price, current_stock=current_stock,
            current_option=current_option_ask, dte=dte,
            days_to_exdiv=days_to_exdiv, days_to_earnings=days_to_earnings,
            pct_from_strike=round(pct_from_strike, 2),
            premium_captured_pct=round(premium_captured_pct, 1),
            p_assignment=round(p_assignment * 100, 1),
            buyback_cost=round(buyback_cost, 2) if buyback_cost else None,
            net_pnl=round(net_pnl, 2) if net_pnl else None,
            reason=f"Gamma danger zone: {dte} DTE and {pct_from_strike:.1f}% from strike.",
            action="Close soon. Small stock moves have big option impact this close to expiry.",
        )

    # CLOSE_SOON: 75%+ premium captured
    if premium_captured_pct >= 75:
        return PositionAlert(
            clause="close_soon_tp75",
            level="CLOSE_SOON", ticker=ticker, strike=strike, expiry=str(expiry)[:10],
            sold_price=sold_price, current_stock=current_stock,
            current_option=current_option_ask, dte=dte,
            days_to_exdiv=days_to_exdiv, days_to_earnings=days_to_earnings,
            pct_from_strike=round(pct_from_strike, 2),
            premium_captured_pct=round(premium_captured_pct, 1),
            p_assignment=round(p_assignment * 100, 1),
            buyback_cost=round(buyback_cost, 2) if buyback_cost else None,
            net_pnl=round(net_pnl, 2) if net_pnl else None,
            reason=f"{premium_captured_pct:.0f}% of premium captured. Remaining {100-premium_captured_pct:.0f}% "
                   f"carries gamma risk.",
            action="Consider closing to lock in profit. The last 25% isn't worth the risk.",
        )

    # CLOSE_SOON: Ex-div 3-5 days + within 5%
    if days_to_exdiv is not None and days_to_exdiv <= 5 and pct_from_strike < 5:
        return PositionAlert(
            clause="close_soon_exdiv_3to5d_within_5pct",
            level="CLOSE_SOON", ticker=ticker, strike=strike, expiry=str(expiry)[:10],
            sold_price=sold_price, current_stock=current_stock,
            current_option=current_option_ask, dte=dte,
            days_to_exdiv=days_to_exdiv, days_to_earnings=days_to_earnings,
            pct_from_strike=round(pct_from_strike, 2),
            premium_captured_pct=round(premium_captured_pct, 1),
            p_assignment=round(p_assignment * 100, 1),
            buyback_cost=round(buyback_cost, 2) if buyback_cost else None,
            net_pnl=round(net_pnl, 2) if net_pnl else None,
            reason=f"Ex-dividend in {days_to_exdiv} days and stock is {pct_from_strike:.1f}% from strike.",
            action="Close before ex-div. Even a small move could push you ITM + trigger exercise.",
        )

    # WATCH: 2-5% from strike with 14+ DTE
    if pct_from_strike < 5 and dte >= 14:
        return PositionAlert(
            clause="watch_2to5pct_dte_ge14",
            level="WATCH", ticker=ticker, strike=strike, expiry=str(expiry)[:10],
            sold_price=sold_price, current_stock=current_stock,
            current_option=current_option_ask, dte=dte,
            days_to_exdiv=days_to_exdiv, days_to_earnings=days_to_earnings,
            pct_from_strike=round(pct_from_strike, 2),
            premium_captured_pct=round(premium_captured_pct, 1),
            p_assignment=round(p_assignment * 100, 1),
            buyback_cost=round(buyback_cost, 2) if buyback_cost else None,
            net_pnl=round(net_pnl, 2) if net_pnl else None,
            reason=f"Stock is {pct_from_strike:.1f}% from strike with {dte} DTE. "
                   f"{p_assignment*100:.0f}% chance of assignment.",
            action="Check daily. If stock approaches within 2% of strike, close.",
        )

    # WATCH: 2-5% from strike with 7-14 DTE
    if pct_from_strike < 5 and dte >= 7:
        return PositionAlert(
            clause="watch_2to5pct_dte_7to14",
            level="WATCH", ticker=ticker, strike=strike, expiry=str(expiry)[:10],
            sold_price=sold_price, current_stock=current_stock,
            current_option=current_option_ask, dte=dte,
            days_to_exdiv=days_to_exdiv, days_to_earnings=days_to_earnings,
            pct_from_strike=round(pct_from_strike, 2),
            premium_captured_pct=round(premium_captured_pct, 1),
            p_assignment=round(p_assignment * 100, 1),
            buyback_cost=round(buyback_cost, 2) if buyback_cost else None,
            net_pnl=round(net_pnl, 2) if net_pnl else None,
            reason=f"Stock is {pct_from_strike:.1f}% from strike with {dte} DTE.",
            action="Monitor closely. Getting into gamma territory.",
        )

    # WATCH: Ex-div 5-10 days + within 5%
    if days_to_exdiv is not None and days_to_exdiv <= 10 and pct_from_strike < 5:
        return PositionAlert(
            clause="watch_exdiv_5to10d_within_5pct",
            level="WATCH", ticker=ticker, strike=strike, expiry=str(expiry)[:10],
            sold_price=sold_price, current_stock=current_stock,
            current_option=current_option_ask, dte=dte,
            days_to_exdiv=days_to_exdiv, days_to_earnings=days_to_earnings,
            pct_from_strike=round(pct_from_strike, 2),
            premium_captured_pct=round(premium_captured_pct, 1),
            p_assignment=round(p_assignment * 100, 1),
            buyback_cost=round(buyback_cost, 2) if buyback_cost else None,
            net_pnl=round(net_pnl, 2) if net_pnl else None,
            reason=f"Ex-dividend in {days_to_exdiv} days. Stock {pct_from_strike:.1f}% from strike.",
            action="Watch for stock to approach strike as ex-div nears.",
        )

    # WATCH: 50%+ premium captured + within 5%
    if premium_captured_pct >= 50 and pct_from_strike < 5:
        return PositionAlert(
            clause="watch_tp50_within_5pct",
            level="WATCH", ticker=ticker, strike=strike, expiry=str(expiry)[:10],
            sold_price=sold_price, current_stock=current_stock,
            current_option=current_option_ask, dte=dte,
            days_to_exdiv=days_to_exdiv, days_to_earnings=days_to_earnings,
            pct_from_strike=round(pct_from_strike, 2),
            premium_captured_pct=round(premium_captured_pct, 1),
            p_assignment=round(p_assignment * 100, 1),
            buyback_cost=round(buyback_cost, 2) if buyback_cost else None,
            net_pnl=round(net_pnl, 2) if net_pnl else None,
            reason=f"{premium_captured_pct:.0f}% premium captured, stock {pct_from_strike:.1f}% from strike.",
            action="Good risk/reward to close and lock in profit. Consider it.",
        )

    # SAFE: Everything else
    return PositionAlert(
        clause="safe_default",
        level="SAFE", ticker=ticker, strike=strike, expiry=str(expiry)[:10],
        sold_price=sold_price, current_stock=current_stock,
        current_option=current_option_ask, dte=dte,
        days_to_exdiv=days_to_exdiv, days_to_earnings=days_to_earnings,
        pct_from_strike=round(pct_from_strike, 2),
        premium_captured_pct=round(premium_captured_pct, 1),
        p_assignment=round(p_assignment * 100, 1),
        buyback_cost=round(buyback_cost, 2) if buyback_cost else None,
        net_pnl=round(net_pnl, 2) if net_pnl else None,
        reason=f"Stock is {pct_from_strike:.1f}% below strike with {dte} DTE. "
               f"Only {p_assignment*100:.0f}% chance of assignment.",
        action=f"Keep holding. {100 - p_assignment*100:.0f}% chance you keep the full premium.",
    )


# ============================================================
# SHADOW MODE — H19 / Experiment 017
#
# The refined EMERGENCY rule is NOT wired into assess_position(). It runs
# alongside the live rule and is logged, nothing more. Switching it on requires
# Charles's explicit sign-off after reviewing shadow logs. Read
# experiments/017_natenberg_emergency/README.md before touching any of this.
# ============================================================

# Natenberg (1994) Ch. 12: an American call is rationally exercised early only
# when it is trading at parity with delta near 100, and for dividend capture
# only when the remaining time value is less than the dividend.
RATIONAL_EXERCISE_DELTA = 0.95
RATIONAL_EXERCISE_MARGIN = 1.5   # arbitrary safety margin — TUNE UPWARD ONLY


# Promoted to cc_core so the monitor, the simulator and the paper engine all
# validate externally-sourced numbers the same way (paper-engine spec §5.5).
# Kept as a module-level name here because the fail-safe guards below and the
# existing tests both reference it.
_is_usable_number = cc_core.is_usable_number


def rational_exercise_emergency(strike, current_stock, current_option_ask,
                                days_to_exdiv, dividend_amount, delta=None,
                                safety_margin=RATIONAL_EXERCISE_MARGIN):
    """Would a rational holder exercise this call early to capture the dividend?

    Returns (fires, reason). `fires` True means EMERGENCY under the refined rule.

    FAIL-SAFE: any missing input (no option price, no dividend amount, no
    delta) makes this fire. The refined rule may only ever be *quieter* than
    the current rule when it has the data to justify silence. Missing data must
    never buy silence on a $400K alert.
    """
    is_itm = current_stock > strike
    if not is_itm:
        return False, "not ITM"
    if days_to_exdiv is None or days_to_exdiv > 3:
        return False, "no ex-dividend within 3 days"

    # `is None` is not enough. A NaN reaches here whenever an upstream feed
    # returns a NaN yield or price (float('nan') is not None, and bool(nan) is
    # True, so it survives every truthiness guard). Left unchecked it silently
    # wins every comparison below — `extrinsic >= nan` is False, so the rule
    # falls through to silence. Zero and negative prices are equally
    # meaningless here. All of them are missing data and must FIRE.
    if not _is_usable_number(current_option_ask, allow_zero=True):
        return True, "FAIL-SAFE: no usable option price, cannot rule out early exercise"
    if not _is_usable_number(dividend_amount):
        return True, "FAIL-SAFE: no usable dividend amount, cannot rule out early exercise"
    if not _is_usable_number(delta, allow_zero=True):
        return True, "FAIL-SAFE: no usable delta, cannot rule out early exercise"

    intrinsic = max(0.0, current_stock - strike)
    extrinsic = max(0.0, current_option_ask - intrinsic)
    threshold = dividend_amount * safety_margin

    if extrinsic >= threshold:
        return False, (f"extrinsic ${extrinsic:.2f} >= dividend ${dividend_amount:.2f} "
                       f"x {safety_margin} = ${threshold:.2f}; holder gains more by waiting")
    if delta < RATIONAL_EXERCISE_DELTA:
        return False, (f"delta {delta:.2f} < {RATIONAL_EXERCISE_DELTA}; "
                       f"not deep enough for rational exercise")

    return True, (f"ITM, ex-div in {days_to_exdiv}d, extrinsic ${extrinsic:.2f} < "
                  f"${threshold:.2f}, delta {delta:.2f}. Rational early exercise.")


def assess_position_shadow(dividend_amount=None, delta=None,
                           safety_margin=RATIONAL_EXERCISE_MARGIN, **kwargs):
    """Run the live rule and the H19 refined rule side by side.

    Returns (live_alert, shadow) where `shadow` describes what the refined rule
    would have done. The live alert is produced by the untouched
    assess_position() and is what production acts on.
    """
    alert = assess_position(**kwargs)
    current_fires = alert.level == "EMERGENCY"

    refined_fires, reason = rational_exercise_emergency(
        strike=kwargs["strike"],
        current_stock=kwargs["current_stock"],
        current_option_ask=kwargs.get("current_option_ask"),
        days_to_exdiv=alert.days_to_exdiv,
        dividend_amount=dividend_amount,
        delta=delta,
        safety_margin=safety_margin,
    )

    if current_fires and not refined_fires:
        disposition = "SUPPRESSED"
    elif current_fires and refined_fires:
        disposition = "AGREE_FIRE"
    elif refined_fires:
        disposition = "REFINED_ONLY"       # should be impossible: refined ⊂ current
    else:
        disposition = "AGREE_SILENT"

    return alert, {
        "current_rule_fires": current_fires,
        "refined_rule_fires": refined_fires,
        "disposition": disposition,
        "reason": reason,
        "dividend_amount": dividend_amount,
        "delta": delta,
        "safety_margin": safety_margin,
        "p_assignment": alert.p_assignment,
    }
