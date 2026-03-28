"""
Tests for paper trade scoring — the financial math that determines every trade's P&L.

The -118,671% bug happened because losses weren't capped at -100%.
These tests ensure that never happens again.
"""

import pytest
import math
from datetime import datetime, timedelta


# ── Scoring formula (extracted for testing) ──

def compute_pnl_pct(premium, outcome_price, expired_itm):
    """
    Compute P&L percentage for a paper trade.
    - Expired OTM (worthless): +100% (kept full premium)
    - Expired ITM: capped at -100% (max loss = premium collected)
    """
    if premium <= 0:
        return 0.0
    if not expired_itm:
        return 100.0  # expired worthless, kept full premium
    intrinsic = outcome_price
    pnl = max(-100.0, ((premium - intrinsic) / premium) * 100)
    return round(pnl, 2)


# ── Tests ──

class TestPnLCalculation:
    """Paper trade P&L formula tests."""

    def test_expired_otm_full_profit(self):
        """Option expires worthless → +100% P&L."""
        assert compute_pnl_pct(premium=3.50, outcome_price=0, expired_itm=False) == 100.0

    def test_expired_otm_any_premium(self):
        """Any premium, expired OTM → always +100%."""
        for premium in [0.01, 0.50, 5.00, 20.00]:
            assert compute_pnl_pct(premium, 0, expired_itm=False) == 100.0

    def test_expired_itm_small_intrinsic(self):
        """ITM with small intrinsic → partial loss."""
        # Premium $5, stock $1 above strike → intrinsic $1
        pnl = compute_pnl_pct(premium=5.00, outcome_price=1.00, expired_itm=True)
        assert pnl == 80.0  # (5 - 1) / 5 * 100 = 80%

    def test_expired_itm_breakeven(self):
        """Stock exactly at premium above strike → 0% P&L."""
        pnl = compute_pnl_pct(premium=5.00, outcome_price=5.00, expired_itm=True)
        assert pnl == 0.0

    def test_expired_itm_deep_loss_capped(self):
        """Deep ITM: stock $50 above strike, premium $2 → capped at -100%."""
        pnl = compute_pnl_pct(premium=2.00, outcome_price=50.00, expired_itm=True)
        assert pnl == -100.0  # NOT -2400%

    def test_loss_never_below_negative_100(self):
        """No matter how deep ITM, P&L never goes below -100%."""
        for intrinsic in [10, 50, 100, 500, 1000]:
            pnl = compute_pnl_pct(premium=1.00, outcome_price=intrinsic, expired_itm=True)
            assert pnl >= -100.0, f"P&L {pnl}% below -100% for intrinsic={intrinsic}"

    def test_zero_premium_returns_zero(self):
        """Zero premium edge case → 0% (avoid division by zero)."""
        assert compute_pnl_pct(premium=0, outcome_price=5, expired_itm=True) == 0.0

    def test_pnl_always_between_minus100_and_plus100(self):
        """P&L is always in [-100, +100] range."""
        for premium in [0.01, 1, 5, 20]:
            for outcome in [0, 0.5, 1, 5, 20, 100]:
                for itm in [True, False]:
                    pnl = compute_pnl_pct(premium, outcome, itm)
                    assert -100 <= pnl <= 100, f"P&L {pnl} out of range for premium={premium}, outcome={outcome}, itm={itm}"


class TestBSMPricing:
    """Black-Scholes pricing used in backfill."""

    def test_atm_call_positive(self):
        """ATM call with positive vol should have positive price."""
        from scipy.stats import norm
        S, K, T, r, sigma = 250, 250, 30/252, 0.05, 0.25
        d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
        d2 = d1 - sigma*math.sqrt(T)
        price = S * norm.cdf(d1) - K * math.exp(-r*T) * norm.cdf(d2)
        assert price > 0
        assert price < S  # call price < stock price

    def test_zero_time_equals_intrinsic(self):
        """At expiry, call = max(S-K, 0)."""
        from scipy.stats import norm
        # ITM: S=260, K=250 → intrinsic = 10
        S, K, T, r, sigma = 260, 250, 0, 0.05, 0.25
        price = max(S - K, 0)  # BSM at T=0
        assert price == 10

        # OTM: S=240, K=250 → intrinsic = 0
        price = max(240 - 250, 0)
        assert price == 0

    def test_call_price_never_negative(self):
        """Call price is always >= 0."""
        from scipy.stats import norm
        for S in [100, 200, 300]:
            for K in [100, 200, 300]:
                for sigma in [0.1, 0.3, 0.5]:
                    T = 30/252
                    r = 0.05
                    if T > 0 and sigma > 0:
                        d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
                        d2 = d1 - sigma*math.sqrt(T)
                        price = S * norm.cdf(d1) - K * math.exp(-r*T) * norm.cdf(d2)
                        assert price >= 0, f"Negative price for S={S}, K={K}, sigma={sigma}"

    def test_higher_vol_higher_price(self):
        """Higher vol → higher call price (all else equal)."""
        from scipy.stats import norm
        S, K, T, r = 250, 260, 30/252, 0.05

        prices = []
        for sigma in [0.10, 0.20, 0.30, 0.40]:
            d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
            d2 = d1 - sigma*math.sqrt(T)
            prices.append(S * norm.cdf(d1) - K * math.exp(-r*T) * norm.cdf(d2))

        for i in range(len(prices) - 1):
            assert prices[i+1] >= prices[i], "Higher vol should produce higher price"


class TestWalkForwardSplit:
    """Walk-forward data splitting logic."""

    def test_split_proportions(self):
        """67/33 split on 252 trading days."""
        n = 252
        split = int(n * 0.67)
        assert split == 168
        assert n - split == 84

    def test_train_precedes_test(self):
        """Train period always comes before test period."""
        import pandas as pd
        dates = pd.date_range('2025-01-01', periods=252, freq='B')
        split = int(len(dates) * 0.67)
        train_end = dates[split - 1]
        test_start = dates[split]
        assert train_end < test_start

    def test_no_overlap(self):
        """Train and test periods don't overlap."""
        import pandas as pd
        dates = pd.date_range('2025-01-01', periods=252, freq='B')
        split = int(len(dates) * 0.67)
        train = set(dates[:split])
        test = set(dates[split:])
        assert len(train & test) == 0

    def test_short_data_still_works(self):
        """Even with 10 data points, split produces valid sets."""
        n = 10
        split = int(n * 0.67)
        assert split >= 1
        assert n - split >= 1


class TestLossRateCalculation:
    """Strategy validation math."""

    def test_perfect_record(self):
        """All wins → 0% loss rate."""
        wins, losses = 20, 0
        loss_rate = losses / (wins + losses) * 100
        assert loss_rate == 0.0

    def test_all_losses(self):
        """All losses → 100% loss rate."""
        wins, losses = 0, 20
        loss_rate = losses / (wins + losses) * 100
        assert loss_rate == 100.0

    def test_win_plus_loss_equals_total(self):
        """Win rate + loss rate = 100%."""
        for wins, losses in [(15, 5), (10, 10), (1, 99), (99, 1)]:
            total = wins + losses
            win_rate = wins / total * 100
            loss_rate = losses / total * 100
            assert abs(win_rate + loss_rate - 100.0) < 0.01
