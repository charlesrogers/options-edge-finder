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
from dataclasses import dataclass
from typing import Optional


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


def assess_position(ticker, strike, expiry, sold_price, contracts,
                     current_stock, current_option_ask=None,
                     ex_div_date=None, earnings_date=None):
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
    """
    today = datetime.now()

    # Parse dates
    if isinstance(expiry, str):
        expiry_dt = datetime.strptime(expiry, "%Y-%m-%d")
    else:
        expiry_dt = expiry

    dte = max(0, (expiry_dt - today).days)

    days_to_exdiv = None
    if ex_div_date:
        if isinstance(ex_div_date, str):
            ex_div_dt = datetime.strptime(ex_div_date, "%Y-%m-%d")
        else:
            ex_div_dt = ex_div_date
        days_to_exdiv = max(0, (ex_div_dt - today).days)

    days_to_earnings = None
    if earnings_date:
        if isinstance(earnings_date, str):
            earn_dt = datetime.strptime(earnings_date, "%Y-%m-%d")
        else:
            earn_dt = earnings_date
        days_to_earnings = max(0, (earn_dt - today).days)

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

    # CLOSE_SOON: Within 5% + DTE < 7 (gamma zone)
    if pct_from_strike < 5 and dte < 7:
        return PositionAlert(
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
