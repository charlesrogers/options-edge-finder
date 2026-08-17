"""
Tests for the H19 refined EMERGENCY rule (shadow mode) and its BSM inputs.

This rule can only ever make the $400K alert QUIETER. Every test here exists to
pin down when it is allowed to be quiet. The single most important property is
the fail-safe: missing data must produce a firing alert, never silence.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import bsm
from position_monitor import (rational_exercise_emergency, assess_position_shadow,
                              RATIONAL_EXERCISE_DELTA, RATIONAL_EXERCISE_MARGIN)


# ============================================================
# The refined rule
# ============================================================

class TestRationalExercise:
    def _call(self, **kw):
        base = dict(strike=100.0, current_stock=105.0, current_option_ask=5.10,
                    days_to_exdiv=1, dividend_amount=0.50, delta=0.98)
        base.update(kw)
        return rational_exercise_emergency(**base)

    def test_fires_when_all_four_conditions_hold(self):
        """ITM, ex-div in 1d, extrinsic 0.10 < 0.50 x 1.5, delta 0.98."""
        fires, reason = self._call()
        assert fires is True
        assert 'Rational early exercise' in reason

    def test_silent_when_extrinsic_exceeds_the_margin(self):
        """extrinsic 1.00 >= 0.50 x 1.5 = 0.75 -> the holder gains by waiting."""
        fires, reason = self._call(current_option_ask=6.00)
        assert fires is False
        assert 'extrinsic' in reason

    def test_margin_is_what_makes_the_borderline_case_fire(self):
        """extrinsic 0.60 > the dividend (0.50) but < 0.50 x 1.5. The 1.5x
        safety margin is the only reason this still fires."""
        assert self._call(current_option_ask=5.60)[0] is True
        assert self._call(current_option_ask=5.60, safety_margin=1.0)[0] is False

    def test_silent_when_delta_too_low(self):
        fires, reason = self._call(delta=0.80)
        assert fires is False
        assert 'delta' in reason

    def test_delta_exactly_at_threshold_fires(self):
        assert self._call(delta=RATIONAL_EXERCISE_DELTA)[0] is True

    def test_silent_when_otm(self):
        assert self._call(current_stock=95.0)[0] is False

    def test_silent_when_no_exdiv_within_three_days(self):
        assert self._call(days_to_exdiv=4)[0] is False
        assert self._call(days_to_exdiv=None)[0] is False

    def test_exdiv_boundary_at_three_days_fires(self):
        assert self._call(days_to_exdiv=3)[0] is True

    def test_default_margin_is_conservative(self):
        """Documented as tune-upward-only; a value below 1 would be a loosening
        that no test authorised."""
        assert RATIONAL_EXERCISE_MARGIN >= 1.0


class TestFailSafe:
    """Missing data must never buy silence."""

    def _call(self, **kw):
        base = dict(strike=100.0, current_stock=105.0, current_option_ask=5.10,
                    days_to_exdiv=1, dividend_amount=0.50, delta=0.98)
        base.update(kw)
        return rational_exercise_emergency(**base)

    def test_missing_option_price_fires(self):
        fires, reason = self._call(current_option_ask=None)
        assert fires is True
        assert 'FAIL-SAFE' in reason

    def test_missing_dividend_amount_fires(self):
        fires, reason = self._call(dividend_amount=None)
        assert fires is True
        assert 'FAIL-SAFE' in reason

    def test_missing_delta_fires(self):
        fires, reason = self._call(delta=None)
        assert fires is True
        assert 'FAIL-SAFE' in reason

    def test_every_missing_input_still_fires(self):
        fires, _ = self._call(current_option_ask=None, dividend_amount=None, delta=None)
        assert fires is True

    # `is None` is not enough. A NaN dividend reaches this function whenever the
    # Yahoo proxy returns a NaN yield: float('nan') is not None and bool(nan) is
    # True, so it survives every truthiness guard upstream. Unchecked it wins
    # every comparison inside the rule (`extrinsic >= nan` is False) and the
    # rule falls through to SILENCE — missing data buying silence on the $400K
    # alert, which is the one thing this rule may never do.
    @pytest.mark.parametrize('bad', [float('nan'), float('inf'), -1.0, 'x'])
    def test_bad_dividend_fires(self, bad):
        fires, reason = self._call(dividend_amount=bad, delta=0.99)
        assert fires is True, f'dividend_amount={bad!r} produced silence'
        assert 'FAIL-SAFE' in reason

    def test_zero_dividend_fires(self):
        """A zero dividend makes the threshold zero, so every position looks
        like 'holder gains more by waiting'. Zero means no data here."""
        fires, reason = self._call(dividend_amount=0.0, delta=0.99)
        assert fires is True
        assert 'FAIL-SAFE' in reason

    @pytest.mark.parametrize('bad', [float('nan'), float('inf'), -1.0, 'x'])
    def test_bad_option_price_fires(self, bad):
        fires, reason = self._call(current_option_ask=bad, delta=0.60)
        assert fires is True, f'current_option_ask={bad!r} produced silence'
        assert 'FAIL-SAFE' in reason

    @pytest.mark.parametrize('bad', [float('nan'), float('inf'), -0.5, 'x'])
    def test_bad_delta_fires(self, bad):
        fires, reason = self._call(delta=bad)
        assert fires is True, f'delta={bad!r} produced silence'
        assert 'FAIL-SAFE' in reason

    def test_nan_cannot_reach_silence_through_any_single_input(self):
        """Belt and braces: NaN in any one slot, everything else valid."""
        nan = float('nan')
        for kw in ({'dividend_amount': nan}, {'current_option_ask': nan},
                   {'delta': nan}):
            fires, reason = self._call(**kw)
            assert fires is True, f'{kw} produced silence: {reason}'


# ============================================================
# The refined rule must be a strict subset of the current rule
# ============================================================

class TestShadowWrapper:
    def _shadow(self, **kw):
        base = dict(ticker='AAPL', strike=100.0, expiry='2025-07-18',
                    sold_price=3.0, contracts=1, current_stock=105.0,
                    current_option_ask=5.10, ex_div_date='2025-06-03',
                    earnings_date=None, as_of='2025-06-02')
        div = kw.pop('dividend_amount', 0.50)
        delta = kw.pop('delta', 0.98)
        base.update(kw)
        return assess_position_shadow(dividend_amount=div, delta=delta, **base)

    def test_live_alert_is_unchanged_by_shadow_mode(self):
        alert, _ = self._shadow()
        assert alert.level == 'EMERGENCY'

    def test_suppression_is_reported_when_refined_stays_silent(self):
        alert, shadow = self._shadow(current_option_ask=6.00)
        assert alert.level == 'EMERGENCY'         # live still fires
        assert shadow['refined_rule_fires'] is False
        assert shadow['disposition'] == 'SUPPRESSED'

    def test_agreement_is_reported_when_both_fire(self):
        _, shadow = self._shadow()
        assert shadow['disposition'] == 'AGREE_FIRE'

    def test_refined_never_fires_where_current_does_not(self):
        """The refined rule adds conditions to the current one, so it can never
        be the louder of the two. REFINED_ONLY should be unreachable."""
        cases = [
            dict(current_stock=95.0),                       # OTM
            dict(ex_div_date=None),                         # no dividend ahead
            dict(ex_div_date='2025-06-20'),                 # ex-div far away
            dict(current_stock=95.0, ex_div_date=None),
        ]
        for kw in cases:
            _, shadow = self._shadow(**kw)
            assert shadow['disposition'] != 'REFINED_ONLY', kw

    def test_missing_data_produces_agreement_not_suppression(self):
        _, shadow = self._shadow(delta=None)
        assert shadow['disposition'] == 'AGREE_FIRE'


# ============================================================
# BSM inputs
# ============================================================

class TestBSM:
    def test_implied_vol_round_trips(self):
        price = bsm.call_price(100, 100, 0.25, 0.04, 0.30)
        iv = bsm.implied_vol_call(price, 100, 100, 0.25, 0.04)
        assert iv == pytest.approx(0.30, abs=1e-3)

    def test_implied_vol_returns_none_below_intrinsic(self):
        """A price below intrinsic is a data error, not a low vol. It must not
        silently become a usable delta."""
        assert bsm.implied_vol_call(1.0, 120, 100, 0.25, 0.04) is None

    def test_implied_vol_returns_none_above_spot(self):
        assert bsm.implied_vol_call(101.0, 100, 100, 0.25, 0.04) is None

    def test_delta_is_between_zero_and_one(self):
        for S in (80, 95, 100, 105, 130):
            d = bsm.call_delta(S, 100, 0.25, 0.04, 0.30)
            assert 0.0 <= d <= 1.0

    def test_delta_increases_with_spot(self):
        deltas = [bsm.call_delta(S, 100, 0.25, 0.04, 0.30) for S in (80, 95, 105, 130)]
        assert deltas == sorted(deltas)

    def test_deep_itm_at_parity_is_delta_one(self):
        """No extrinsic left to invert: delta is 1 by definition, not None."""
        assert bsm.delta_from_price(20.0, 120, 100, 30) == 1.0

    def test_delta_from_price_returns_none_when_uninvertible(self):
        assert bsm.delta_from_price(200.0, 100, 100, 30) is None

    def test_zero_dte_is_a_step_function(self):
        """At 0 DTE delta is decided by moneyness alone; the price argument is
        not consulted. Asserted explicitly with contradictory prices so this
        cannot silently start depending on the price."""
        for price in (5.0, 0.0, None, 999.0):
            assert bsm.delta_from_price(price, 105, 100, 0) == 1.0
            assert bsm.delta_from_price(price, 95, 100, 0) == 0.0

    def test_delta_round_trips_at_the_same_maturity(self):
        """Price and invert at the SAME T, so a real inversion error would show
        up instead of being absorbed by a loose threshold."""
        T_days = 30
        T = T_days / 365.0
        price = bsm.call_price(100, 130, T, bsm.DEFAULT_RISK_FREE, 0.25)
        d = bsm.delta_from_price(price, 100, 130, T_days)
        expected = bsm.call_delta(100, 130, T, bsm.DEFAULT_RISK_FREE, 0.25)
        assert d == pytest.approx(expected, abs=1e-3)

    def test_a_far_otm_call_has_low_delta(self):
        T_days = 30
        price = bsm.call_price(100, 130, T_days / 365.0, bsm.DEFAULT_RISK_FREE, 0.25)
        d = bsm.delta_from_price(price, 100, 130, T_days)
        assert d < RATIONAL_EXERCISE_DELTA
        assert d < 0.10   # it is genuinely far OTM, not merely under the bar
