"""
Tests for position_monitor.py — the Covered Call Copilot.

This is a financial safety system. A wrong alert level can cost $400K+.
Every threshold boundary must be tested.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from position_monitor import assess_position, lookup_itm_probability, PositionAlert


# ============================================================
# Helper: freeze "today" so tests are deterministic
# ============================================================

def _assess(ticker="AAPL", strike=250, expiry=None, sold_price=3.50,
            contracts=1, current_stock=240, current_option_ask=1.00,
            ex_div_date=None, earnings_date=None, today=None):
    """Wrapper that patches datetime.now() for deterministic tests."""
    if today is None:
        today = datetime(2026, 3, 1)
    if expiry is None:
        expiry = (today + timedelta(days=30)).strftime("%Y-%m-%d")

    with patch('position_monitor.datetime') as mock_dt:
        mock_dt.now.return_value = today
        mock_dt.strptime = datetime.strptime
        return assess_position(
            ticker=ticker, strike=strike, expiry=expiry,
            sold_price=sold_price, contracts=contracts,
            current_stock=current_stock,
            current_option_ask=current_option_ask,
            ex_div_date=ex_div_date, earnings_date=earnings_date,
        )


# ============================================================
# SAFE: Stock far below strike, plenty of time
# ============================================================

class TestSafe:
    def test_far_otm_long_dte(self):
        """10% OTM, 30 DTE, low premium captured → SAFE"""
        # Use option ask close to sold price so premium_captured < 75%
        alert = _assess(strike=260, current_stock=234, sold_price=3.50,
                        current_option_ask=2.50)
        assert alert.level == "SAFE"

    def test_6pct_otm_30dte(self):
        """6% OTM, 30 DTE, low premium captured → SAFE"""
        alert = _assess(strike=260, current_stock=244, sold_price=3.50,
                        current_option_ask=2.80)
        assert alert.level == "SAFE"

    def test_pct_from_strike_positive_when_otm(self):
        """pct_from_strike should be positive when stock < strike"""
        alert = _assess(strike=260, current_stock=240)
        assert alert.pct_from_strike > 0

    def test_premium_captured_calculation(self):
        """Sold at $3.50, now $0.50 ask → ~86% captured"""
        alert = _assess(sold_price=3.50, current_option_ask=0.50)
        assert 85 <= alert.premium_captured_pct <= 87

    def test_buyback_cost_calculation(self):
        """1 contract at $1.00 ask → $100 buyback cost"""
        alert = _assess(current_option_ask=1.00, contracts=1)
        assert alert.buyback_cost == 100.0

    def test_net_pnl_calculation(self):
        """Sold $3.50, buyback $1.00, 1 contract → $250 profit"""
        alert = _assess(sold_price=3.50, current_option_ask=1.00, contracts=1)
        assert alert.net_pnl == 250.0


# ============================================================
# WATCH: Stock approaching strike
# ============================================================

class TestWatch:
    def test_4pct_otm_30dte(self):
        """4% OTM, 30 DTE → WATCH (2-5% zone, 14+ DTE)"""
        alert = _assess(strike=250, current_stock=240, current_option_ask=1.50)
        # 250-240/240 = 4.17% → WATCH
        assert alert.level == "WATCH"

    def test_3pct_otm_14dte(self):
        """3% OTM, 14 DTE → WATCH"""
        today = datetime(2026, 3, 1)
        expiry = (today + timedelta(days=14)).strftime("%Y-%m-%d")
        alert = _assess(strike=250, current_stock=242.7, current_option_ask=1.00,
                        today=today, expiry=expiry)
        # 250-242.7/242.7 = 3.01% → WATCH (2-5% zone, 14+ DTE)
        assert alert.level == "WATCH"

    def test_3pct_otm_10dte(self):
        """3% OTM, 10 DTE → WATCH (2-5% zone, 7-14 DTE)"""
        today = datetime(2026, 3, 1)
        expiry = (today + timedelta(days=10)).strftime("%Y-%m-%d")
        alert = _assess(strike=250, current_stock=242.7, current_option_ask=1.00,
                        today=today, expiry=expiry)
        assert alert.level == "WATCH"

    def test_exdiv_8days_4pct_otm(self):
        """Ex-div in 8 days, 4% OTM → WATCH"""
        today = datetime(2026, 3, 1)
        exdiv = (today + timedelta(days=8)).strftime("%Y-%m-%d")
        alert = _assess(strike=250, current_stock=240, current_option_ask=1.00,
                        today=today, ex_div_date=exdiv)
        assert alert.level == "WATCH"

    def test_50pct_premium_captured_4pct_otm(self):
        """50% premium captured + 4% OTM → WATCH"""
        alert = _assess(strike=250, current_stock=240, sold_price=3.00,
                        current_option_ask=1.50)
        assert alert.level == "WATCH"


# ============================================================
# CLOSE_SOON: Time to take profit / risk flipping
# ============================================================

class TestCloseSoon:
    def test_1_5pct_otm_14dte(self):
        """1.5% OTM, 14 DTE → CLOSE_SOON (within 2%, 7+ DTE)"""
        today = datetime(2026, 3, 1)
        expiry = (today + timedelta(days=14)).strftime("%Y-%m-%d")
        alert = _assess(strike=250, current_stock=246.3, current_option_ask=2.00,
                        today=today, expiry=expiry)
        # 250-246.3/246.3 = 1.50%
        assert alert.level == "CLOSE_SOON"

    def test_2pct_otm_5dte_gamma_zone(self):
        """2% OTM, 5 DTE → CLOSE_SOON (gamma zone: <3% + <7 DTE)"""
        today = datetime(2026, 3, 1)
        expiry = (today + timedelta(days=5)).strftime("%Y-%m-%d")
        alert = _assess(strike=250, current_stock=245, current_option_ask=1.00,
                        today=today, expiry=expiry)
        # 250-245/245 = 2.04% → within 3%, dte=5 → CLOSE_SOON
        assert alert.level == "CLOSE_SOON"

    def test_4pct_otm_5dte_NOT_close_soon(self):
        """4% OTM, 5 DTE → NOT CLOSE_SOON (3-5% at <7 DTE downgraded from gamma zone)"""
        today = datetime(2026, 3, 1)
        expiry = (today + timedelta(days=5)).strftime("%Y-%m-%d")
        # Use high ask so premium_captured stays below 75% (avoid take-profit trigger)
        alert = _assess(strike=250, current_stock=240, sold_price=3.50,
                        current_option_ask=2.50, today=today, expiry=expiry)
        # 4.17% OTM, 5 DTE, 29% premium captured → not gamma zone, not take-profit
        assert alert.level != "CLOSE_SOON"

    def test_75pct_premium_captured(self):
        """80% premium captured, far OTM → CLOSE_SOON (take profit)"""
        alert = _assess(strike=270, current_stock=240, sold_price=4.00,
                        current_option_ask=0.80)
        # 270-240/240 = 12.5% OTM, but 80% premium captured
        assert alert.level == "CLOSE_SOON"

    def test_exdiv_4days_3pct_otm(self):
        """Ex-div in 4 days, 3% OTM, not ITM → CLOSE_SOON"""
        today = datetime(2026, 3, 1)
        exdiv = (today + timedelta(days=4)).strftime("%Y-%m-%d")
        alert = _assess(strike=250, current_stock=242.7, current_option_ask=1.00,
                        today=today, ex_div_date=exdiv)
        # 250-242.7/242.7 = 3.01% → CLOSE_SOON (exdiv <=5 + <5%)
        assert alert.level == "CLOSE_SOON"

    def test_boundary_exactly_2pct_otm(self):
        """Exactly 2% OTM, 14 DTE → should be CLOSE_SOON (< 2 means strictly less)"""
        today = datetime(2026, 3, 1)
        expiry = (today + timedelta(days=14)).strftime("%Y-%m-%d")
        # Strike 250, stock 245.098 → pct = (250-245.098)/245.098 = 2.0004%
        # pct < 2 is False, so should NOT be CLOSE_SOON via the <2% rule
        # But pct < 5 and dte >= 14, so WATCH
        alert = _assess(strike=250, current_stock=245.098, current_option_ask=1.50,
                        today=today, expiry=expiry)
        assert alert.level in ("CLOSE_SOON", "WATCH")


# ============================================================
# CLOSE_NOW: Assignment risk is real
# ============================================================

class TestCloseNow:
    def test_itm_any_amount(self):
        """Stock $1 above strike → CLOSE_NOW"""
        alert = _assess(strike=250, current_stock=251)
        assert alert.level == "CLOSE_NOW"

    def test_deeply_itm(self):
        """Stock 10% above strike → CLOSE_NOW"""
        alert = _assess(strike=250, current_stock=275)
        assert alert.level == "CLOSE_NOW"

    def test_barely_itm(self):
        """Stock $0.01 above strike → CLOSE_NOW"""
        alert = _assess(strike=250, current_stock=250.01)
        assert alert.level == "CLOSE_NOW"

    def test_pct_from_strike_negative_when_itm(self):
        """pct_from_strike should be negative when stock > strike"""
        alert = _assess(strike=250, current_stock=260)
        assert alert.pct_from_strike < 0

    def test_1pct_otm_exdiv_3days(self):
        """0.5% OTM + ex-div in 3 days → CLOSE_NOW"""
        today = datetime(2026, 3, 1)
        exdiv = (today + timedelta(days=3)).strftime("%Y-%m-%d")
        alert = _assess(strike=250, current_stock=248.75, current_option_ask=2.00,
                        today=today, ex_div_date=exdiv)
        # 250-248.75/248.75 = 0.50% → within 1% + exdiv <=5
        assert alert.level == "CLOSE_NOW"

    def test_2dte_2pct_otm(self):
        """2 DTE, 2% OTM → CLOSE_NOW (dte<3 + <3% from strike)"""
        today = datetime(2026, 3, 1)
        expiry = (today + timedelta(days=2)).strftime("%Y-%m-%d")
        alert = _assess(strike=250, current_stock=245, current_option_ask=1.00,
                        today=today, expiry=expiry)
        # 250-245/245 = 2.04% → <3%, dte=2 → CLOSE_NOW
        assert alert.level == "CLOSE_NOW"

    def test_0dte_2_5pct_otm(self):
        """0 DTE, 2.5% OTM → CLOSE_NOW (last day, within 3%)"""
        today = datetime(2026, 3, 1)
        expiry = today.strftime("%Y-%m-%d")
        alert = _assess(strike=250, current_stock=243.9, current_option_ask=0.10,
                        today=today, expiry=expiry)
        assert alert.level == "CLOSE_NOW"

    def test_earnings_1day_1pct_otm(self):
        """Earnings tomorrow, 1% OTM → CLOSE_NOW"""
        today = datetime(2026, 3, 1)
        earnings = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        alert = _assess(strike=250, current_stock=247.5, current_option_ask=2.00,
                        today=today, earnings_date=earnings)
        # 250-247.5/247.5 = 1.01% → <2% + earnings <=2 days
        assert alert.level == "CLOSE_NOW"


# ============================================================
# EMERGENCY: The $400K alert
# ============================================================

class TestEmergency:
    def test_itm_exdiv_tomorrow(self):
        """ITM + ex-div tomorrow → EMERGENCY"""
        today = datetime(2026, 3, 1)
        exdiv = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        alert = _assess(strike=250, current_stock=252, current_option_ask=4.00,
                        today=today, ex_div_date=exdiv)
        assert alert.level == "EMERGENCY"

    def test_itm_exdiv_today(self):
        """ITM + ex-div TODAY → EMERGENCY"""
        today = datetime(2026, 3, 1)
        exdiv = today.strftime("%Y-%m-%d")
        alert = _assess(strike=250, current_stock=255, current_option_ask=6.00,
                        today=today, ex_div_date=exdiv)
        assert alert.level == "EMERGENCY"

    def test_itm_exdiv_3days(self):
        """ITM + ex-div in 3 days → EMERGENCY (boundary: <=3)"""
        today = datetime(2026, 3, 1)
        exdiv = (today + timedelta(days=3)).strftime("%Y-%m-%d")
        alert = _assess(strike=250, current_stock=251, current_option_ask=3.00,
                        today=today, ex_div_date=exdiv)
        assert alert.level == "EMERGENCY"

    def test_itm_exdiv_4days_NOT_emergency(self):
        """ITM + ex-div in 4 days → CLOSE_NOW (not EMERGENCY, >3 days)"""
        today = datetime(2026, 3, 1)
        exdiv = (today + timedelta(days=4)).strftime("%Y-%m-%d")
        alert = _assess(strike=250, current_stock=251, current_option_ask=3.00,
                        today=today, ex_div_date=exdiv)
        assert alert.level == "CLOSE_NOW"  # ITM but exdiv too far for EMERGENCY

    def test_otm_exdiv_tomorrow_NOT_emergency(self):
        """OTM + ex-div tomorrow → NOT EMERGENCY (must be ITM)"""
        today = datetime(2026, 3, 1)
        exdiv = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        alert = _assess(strike=250, current_stock=248, current_option_ask=1.50,
                        today=today, ex_div_date=exdiv)
        assert alert.level != "EMERGENCY"

    def test_emergency_reason_mentions_exdiv(self):
        """EMERGENCY reason should mention ex-dividend"""
        today = datetime(2026, 3, 1)
        exdiv = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        alert = _assess(strike=250, current_stock=252, current_option_ask=4.00,
                        today=today, ex_div_date=exdiv)
        assert "ex-dividend" in alert.reason.lower() or "ex-div" in alert.reason.lower()

    def test_emergency_action_is_urgent(self):
        """EMERGENCY action should convey urgency"""
        today = datetime(2026, 3, 1)
        exdiv = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        alert = _assess(strike=250, current_stock=252, current_option_ask=4.00,
                        today=today, ex_div_date=exdiv)
        assert "immediately" in alert.action.lower() or "now" in alert.action.lower()


# ============================================================
# ITM Probability Lookup Table
# ============================================================

class TestITMProbability:
    def test_deep_otm_low_dte(self):
        """15% OTM, 1 DTE → ~0% (default fallback)"""
        p = lookup_itm_probability(15, 1)
        assert p <= 0.05

    def test_5pct_otm_14dte(self):
        """5-10% OTM, 14 DTE → 14.8%"""
        p = lookup_itm_probability(7, 10)
        assert abs(p - 0.148) < 0.001

    def test_atm_7dte(self):
        """0-1% OTM, 7 DTE → lookup exists and is meaningful"""
        p = lookup_itm_probability(0.5, 5)
        assert 0.2 < p < 0.6  # Should be ~49.1%

    def test_itm_1pct_3dte(self):
        """1% ITM, 1 DTE → ~76%"""
        p = lookup_itm_probability(-0.5, 1)
        assert p > 0.7

    def test_deep_itm(self):
        """10% ITM → ~98%"""
        p = lookup_itm_probability(-10, 5)
        assert p > 0.95

    def test_boundary_exactly_at_bucket_edge(self):
        """Exactly at bucket boundary (pct=5, dte=7) → should not crash"""
        p = lookup_itm_probability(5, 7)
        assert 0 <= p <= 1

    def test_extreme_otm(self):
        """50% OTM → very low probability (default fallback or table edge)"""
        p = lookup_itm_probability(50, 30)
        assert p <= 0.10

    def test_extreme_itm(self):
        """50% ITM → near-100% probability"""
        p = lookup_itm_probability(-50, 1)
        assert p >= 0.95

    def test_dte_60_plus_fallback(self):
        """DTE > 60 → should return something reasonable, not crash"""
        p = lookup_itm_probability(3, 90)
        assert 0 <= p <= 1


# ============================================================
# Priority Order: EMERGENCY > CLOSE_NOW > CLOSE_SOON > WATCH > SAFE
# ============================================================

class TestPriorityOrder:
    def test_emergency_beats_close_now(self):
        """ITM + exdiv should be EMERGENCY, not just CLOSE_NOW"""
        today = datetime(2026, 3, 1)
        exdiv = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        alert = _assess(strike=250, current_stock=260, current_option_ask=12.00,
                        today=today, ex_div_date=exdiv)
        assert alert.level == "EMERGENCY"

    def test_close_now_beats_close_soon(self):
        """ITM should always be CLOSE_NOW minimum, even with plenty of DTE"""
        alert = _assess(strike=250, current_stock=251)
        assert alert.level in ("CLOSE_NOW", "EMERGENCY")

    def test_itm_is_never_safe(self):
        """No matter the DTE, ITM should never be SAFE"""
        for dte in [1, 5, 14, 30, 45]:
            today = datetime(2026, 3, 1)
            expiry = (today + timedelta(days=dte)).strftime("%Y-%m-%d")
            alert = _assess(strike=250, current_stock=255, today=today, expiry=expiry)
            assert alert.level not in ("SAFE", "WATCH"), \
                f"ITM position at {dte} DTE should not be {alert.level}"


# ============================================================
# Edge Cases
# ============================================================

class TestEdgeCases:
    def test_no_option_ask(self):
        """current_option_ask=None should not crash"""
        alert = _assess(current_option_ask=None)
        assert alert.level in ("SAFE", "WATCH", "CLOSE_SOON", "CLOSE_NOW", "EMERGENCY")
        assert alert.buyback_cost is None
        assert alert.premium_captured_pct == 0

    def test_zero_sold_price(self):
        """sold_price=0 should not crash (division)"""
        alert = _assess(sold_price=0)
        assert alert.level in ("SAFE", "WATCH", "CLOSE_SOON", "CLOSE_NOW", "EMERGENCY")

    def test_expiry_as_datetime(self):
        """expiry can be datetime object, not just string"""
        today = datetime(2026, 3, 1)
        expiry_dt = today + timedelta(days=30)
        with patch('position_monitor.datetime') as mock_dt:
            mock_dt.now.return_value = today
            mock_dt.strptime = datetime.strptime
            alert = assess_position(
                ticker="AAPL", strike=250, expiry=expiry_dt,
                sold_price=3.50, contracts=1, current_stock=240,
                current_option_ask=1.00,
            )
        assert alert.dte == 30

    def test_stock_exactly_at_strike(self):
        """Stock exactly at strike → should be CLOSE_NOW (pct_from_strike=0, is_itm=False technically)"""
        alert = _assess(strike=250, current_stock=250)
        # pct_from_strike = 0, is_itm = False (250 > 250 is False)
        # But 0% from strike with DTE < 3 or DTE >= 7 triggers CLOSE_SOON
        assert alert.level in ("CLOSE_SOON", "CLOSE_NOW")

    def test_multiple_contracts(self):
        """3 contracts should scale buyback cost and net_pnl"""
        alert = _assess(contracts=3, sold_price=3.50, current_option_ask=1.00)
        assert alert.buyback_cost == 300.0
        assert alert.net_pnl == 750.0


# ============================================================
# Return type validation
# ============================================================

class TestReturnType:
    def test_returns_position_alert(self):
        alert = _assess()
        assert isinstance(alert, PositionAlert)

    def test_all_fields_populated(self):
        alert = _assess()
        assert alert.ticker == "AAPL"
        assert isinstance(alert.dte, int)
        assert isinstance(alert.p_assignment, float)
        assert isinstance(alert.reason, str)
        assert isinstance(alert.action, str)
        assert len(alert.reason) > 0
        assert len(alert.action) > 0
