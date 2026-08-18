"""
Tests for the Phase 3 research layer (experiments/lib_phase3.py).

Not production code, but H23's verdict rests entirely on the equity curve and the guard,
so both get boundary tests. A curve that silently double-counts a closed trade, or a guard
that peeks at tomorrow's VIX, would have produced a confident wrong answer.
"""

import os
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'experiments'))

import lib_phase3 as P3


@dataclass
class FakeTrade:
    entry_date: str
    exit_date: str
    symbol: str = 'X'
    premium: float = 1.0
    buyback: float = 0.0
    pnl_per_share: float = 1.0
    assigned: bool = False


class FakeChain:
    """Minimum surface equity_curve() touches: option_days, spot(), price."""
    def __init__(self, dates, spots, prices=None):
        self.option_days = list(dates)
        self._spot = dict(zip(dates, spots))
        self.price = prices or {}
        self.stock = pd.Series(spots, index=pd.DatetimeIndex(dates))

    def spot(self, date):
        return self._spot.get(pd.Timestamp(date))


def days(n, start='2025-01-01'):
    return list(pd.date_range(start, periods=n, freq='D'))


# ------------------------------------------------------------
# sequential_chain
# ------------------------------------------------------------

def test_chain_never_holds_two_positions_at_once():
    trades = [FakeTrade('2025-01-01', '2025-01-10'),
              FakeTrade('2025-01-05', '2025-01-15'),   # overlaps the first
              FakeTrade('2025-01-12', '2025-01-20')]
    chain = P3.sequential_chain(trades, 0)
    assert [t.entry_date for t in chain] == ['2025-01-01', '2025-01-12']
    for a, b in zip(chain, chain[1:]):
        assert b.entry_date >= a.exit_date


def test_chain_stagger_produces_a_different_path():
    trades = [FakeTrade('2025-01-01', '2025-01-10'),
              FakeTrade('2025-01-05', '2025-01-15'),
              FakeTrade('2025-01-12', '2025-01-20')]
    assert P3.sequential_chain(trades, 0) != P3.sequential_chain(trades, 1)
    assert [t.entry_date for t in P3.sequential_chain(trades, 1)] == ['2025-01-05']


def test_chain_start_index_past_the_end_is_empty_not_an_error():
    assert P3.sequential_chain([FakeTrade('2025-01-01', '2025-01-02')], 5) == []


def test_chain_accepts_reentry_on_the_exit_day():
    """Closing and re-selling the same day is legal, and must not be dropped."""
    trades = [FakeTrade('2025-01-01', '2025-01-10'), FakeTrade('2025-01-10', '2025-01-20')]
    assert len(P3.sequential_chain(trades, 0)) == 2


# ------------------------------------------------------------
# equity_curve
# ------------------------------------------------------------

def test_stock_only_curve_is_exactly_the_share_value():
    d = days(5)
    chain = FakeChain(d, [100, 101, 102, 103, 104])
    eq = P3.equity_curve(chain, [], shares=1000, contracts=0)
    assert list(eq) == [100_000, 101_000, 102_000, 103_000, 104_000]


def test_zero_contracts_ignores_the_overlay_entirely():
    d = days(4)
    chain = FakeChain(d, [100, 100, 100, 100])
    t = FakeTrade(str(d[0])[:10], str(d[2])[:10], pnl_per_share=5.0)
    eq = P3.equity_curve(chain, [t], shares=1000, contracts=0)
    assert eq.nunique() == 1, 'a 0% overwrite must not move the curve'


def test_realised_pnl_is_added_once_and_stays():
    d = days(4)
    chain = FakeChain(d, [100, 100, 100, 100])
    t = FakeTrade(str(d[0])[:10], str(d[2])[:10], pnl_per_share=2.0)
    eq = P3.equity_curve(chain, [t], shares=100, contracts=1)
    # day0 entry (unrealised 0), day1 open, day2 exit -> +2/share x100, day3 unchanged
    assert eq.iloc[0] == pytest.approx(10_000)
    assert eq.iloc[2] == pytest.approx(10_200)
    assert eq.iloc[3] == pytest.approx(10_200), 'realised P&L must not be re-credited'


def test_unrealised_tracks_the_daily_option_price():
    d = days(3)
    chain = FakeChain(d, [100, 100, 100], prices={('X', d[1]): 0.25})
    t = FakeTrade(str(d[0])[:10], str(d[2])[:10], premium=1.0, pnl_per_share=1.0)
    eq = P3.equity_curve(chain, [t], shares=100, contracts=1)
    # day1: sold at 1.00, marked at 0.25 -> +0.75/share x100 = +75 unrealised
    assert eq.iloc[1] == pytest.approx(10_075)


def test_missing_price_carries_the_last_mark_forward():
    d = days(4)
    chain = FakeChain(d, [100] * 4, prices={('X', d[1]): 0.25})   # no bar on day 2
    t = FakeTrade(str(d[0])[:10], str(d[3])[:10], premium=1.0, pnl_per_share=1.0)
    eq = P3.equity_curve(chain, [t], shares=100, contracts=1)
    assert eq.iloc[2] == pytest.approx(eq.iloc[1]), 'a missing bar must not reprice to zero'


def test_overlay_scales_linearly_with_contracts():
    d = days(4)
    chain = FakeChain(d, [100] * 4)
    t = FakeTrade(str(d[0])[:10], str(d[2])[:10], pnl_per_share=3.0)
    base = P3.equity_curve(chain, [t], 10_000, 100).iloc[-1] - 1_000_000
    half = P3.equity_curve(chain, [t], 10_000, 50).iloc[-1] - 1_000_000
    assert half == pytest.approx(base / 2), 'income must be exactly linear in the ratio'


# ------------------------------------------------------------
# drawdown
# ------------------------------------------------------------

def test_drawdown_of_a_monotonic_rise_is_zero():
    assert P3.drawdown_pct(pd.Series([100, 110, 120])) == pytest.approx(0.0)


def test_drawdown_is_peak_to_trough_not_first_to_last():
    # 100 -> 150 -> 75 -> 140: worst is 150 -> 75 = 50%, not 100 -> 75 = 25%
    assert P3.drawdown_pct(pd.Series([100, 150, 75, 140])) == pytest.approx(50.0)


def test_drawdown_of_an_empty_curve_is_zero_not_an_exception():
    assert P3.drawdown_pct(pd.Series([], dtype=float)) == 0.0


# ------------------------------------------------------------
# the H22 guard
# ------------------------------------------------------------

def vix_frame(rows):
    idx = pd.DatetimeIndex([r[0] for r in rows])
    return pd.DataFrame({'VIX': [r[1] for r in rows], 'VIX3M': [r[2] for r in rows]}, index=idx)


def test_guard_blocks_on_backwardation():
    vix = vix_frame([('2025-01-01', 30, 25)])
    chain = FakeChain(days(1), [100])
    ok, why = P3.backwardation_gate(vix)(chain, pd.Timestamp('2025-01-01'), 100)
    assert not ok and why == 'backwardation'


def test_guard_allows_in_contango():
    vix = vix_frame([('2025-01-01', 15, 20)])
    chain = FakeChain(days(1), [100])
    ok, _ = P3.backwardation_gate(vix)(chain, pd.Timestamp('2025-01-01'), 100)
    assert ok


def test_guard_blocks_on_drawdown_from_the_rolling_high():
    d = days(15)
    spots = [100] * 14 + [80]        # 20% below the high, threshold is 15%
    vix = vix_frame([(str(x)[:10], 15, 20) for x in d])
    chain = FakeChain(d, spots)
    ok, why = P3.backwardation_gate(vix, drawdown_pct=0.15, high_lookback=10)(chain, d[-1], 80)
    assert not ok and why == 'drawdown'


def test_guard_drawdown_boundary_is_not_triggered_just_inside():
    d = days(15)
    spots = [100] * 14 + [85.5]      # 14.5% down — inside the 15% threshold
    vix = vix_frame([(str(x)[:10], 15, 20) for x in d])
    chain = FakeChain(d, spots)
    ok, _ = P3.backwardation_gate(vix, drawdown_pct=0.15, high_lookback=10)(chain, d[-1], 85.5)
    assert ok


def test_guard_legs_can_be_disabled_independently():
    vix = vix_frame([('2025-01-01', 30, 25)])
    chain = FakeChain(days(1), [100])
    ok, _ = P3.backwardation_gate(vix, use_backwardation=False)(
        chain, pd.Timestamp('2025-01-01'), 100)
    assert ok, 'disabling the backwardation leg must disable its block'


def test_guard_never_reads_the_future():
    """Tomorrow's spike must not block today's entry."""
    d = days(3)
    vix = vix_frame([('2025-01-01', 15, 20), ('2025-01-02', 15, 20), ('2025-01-03', 40, 25)])
    chain = FakeChain(d, [100, 100, 100])
    ok, _ = P3.backwardation_gate(vix)(chain, d[1], 100)
    assert ok


def test_and_gates_blocks_if_any_gate_blocks():
    allow = lambda c, d, s: (True, '')
    deny = lambda c, d, s: (False, 'nope')
    ok, why = P3.and_gates(allow, deny, allow)(None, None, None)
    assert not ok and why == 'nope'
    assert P3.and_gates(allow, allow)(None, None, None)[0]


# ------------------------------------------------------------
# blocked-entry diagnostic
# ------------------------------------------------------------

def test_blocked_entry_stats_measures_what_the_gate_threw_away():
    baseline = [FakeTrade('2025-01-01', '2025-01-05', pnl_per_share=1.0),
                FakeTrade('2025-01-06', '2025-01-10', pnl_per_share=-3.0)]
    kept = [baseline[0]]
    stats = P3.blocked_entry_stats(baseline, kept)
    assert stats['n_blocked'] == 1
    assert stats['blocked_mean_pnl'] == pytest.approx(-300.0)
    assert stats['blocked_losers'] == 1


def test_blocked_entry_stats_when_nothing_was_blocked():
    trades = [FakeTrade('2025-01-01', '2025-01-05')]
    assert P3.blocked_entry_stats(trades, trades) == {'n_blocked': 0}
