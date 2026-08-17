"""
Tests for experiments/cc_sim.py — the Week 2 covered-call simulator.

This engine decides whether a $30-60K/yr change to the buyback rule ships. Every
number it produces is a financial claim, so the accounting is pinned to
hand-calculated examples here before any experiment is allowed to quote it.

Covered:
  - single-trade P&L accounting (close, expire worthless, expire assigned)
  - rational early exercise into a dividend (Natenberg Ch. 12)
  - the probability exit policy's thresholds
  - CLOSE_SOON's "close this week" delay
  - missing-price accounting (carried forward AND counted, never skipped)
  - walk-forward split integrity
  - scorecard invariants
"""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'experiments'))

import cc_sim
from cc_sim import (ChainData, DayContext, Trade, HOLD, CLOSE_SOON, CLOSE_NOW,
                    make_probability_policy, run_cohort, score,
                    walk_forward_split, paired_difference)


# ============================================================
# Synthetic chain builder
# ============================================================

def build_chain(spots, strike=100.0, expiry_offset=30, prices=None,
                dividends=(), symbol='TEST  250101C00100000', start='2025-01-02',
                pad_expiry_bar=True):
    """A one-strike, one-expiry chain with a hand-specified price path.

    spots:  list of daily stock closes, day 0 = entry day
    prices: list of daily option closes (None = no trade that day), same length
    pad_expiry_bar: append a bar on the expiration date so the position can
        settle. Set False to simulate an expiry that falls outside the data.
    """
    days = pd.bdate_range(start, periods=len(spots))
    expiration = days[0] + pd.Timedelta(days=expiry_offset)
    if prices is None:
        prices = [1.00] * len(spots)

    rows, price_map = [], {}
    for d, p in zip(days, prices):
        rows.append({'date': d, 'symbol': symbol, 'strike': strike,
                     'expiration': expiration, 'close': p if p is not None else 0.0})
        if p is not None:
            price_map[(symbol, d)] = p

    # Give the chain an expiry-day bar so settlement has a row to land on.
    exp_day = expiration
    if pad_expiry_bar and exp_day not in days:
        days = days.append(pd.DatetimeIndex([exp_day]))
        rows.append({'date': exp_day, 'symbol': symbol, 'strike': strike,
                     'expiration': expiration, 'close': 0.0})
        price_map[(symbol, exp_day)] = 0.0
        spots = list(spots) + [spots[-1]]

    frame = pd.DataFrame(rows)
    by_date = {d: g for d, g in frame.groupby('date')}
    stock = pd.Series(spots, index=days)

    return ChainData(
        ticker='TEST', by_date=by_date, price=price_map,
        option_days=sorted(by_date), stock=stock,
        dividends=[(pd.Timestamp(d), a) for d, a in dividends],
        iv_rank={str(d)[:10]: 100.0 for d in days},
    )


CFG = {'otm_pct': 0.0, 'min_dte': 1, 'max_dte': 400,
       'slippage': 0.0, 'close_soon_days': 5}

NEVER = lambda ctx: (HOLD, 'NEVER')
ALWAYS = lambda ctx: (CLOSE_NOW, 'ALWAYS')


# ============================================================
# P&L accounting — hand-calculated
# ============================================================

class TestPnLAccounting:
    def test_expires_worthless_keeps_full_premium(self):
        chain = build_chain(spots=[95] * 10, prices=[2.50] + [1.0] * 9)
        trade, _ = run_cohort(chain, chain.option_days[0], CFG, NEVER)
        assert trade.exit_reason == 'expiry_worthless'
        assert trade.buyback == 0.0
        assert trade.pnl_per_share == pytest.approx(2.50)
        assert trade.assigned is False

    def test_expires_itm_is_assigned_and_pays_intrinsic(self):
        """Premium 2.50, stock finishes 108 vs strike 100 -> P&L = 2.50 - 8."""
        chain = build_chain(spots=[95] * 9 + [108], prices=[2.50] + [1.0] * 9)
        trade, _ = run_cohort(chain, chain.option_days[0], CFG, NEVER)
        assert trade.exit_reason == 'expiry_assigned'
        assert trade.assigned is True
        assert trade.assignment_type == 'expiry'
        assert trade.buyback == pytest.approx(8.0)
        assert trade.pnl_per_share == pytest.approx(2.50 - 8.0)

    def test_policy_close_pays_the_days_option_price(self):
        chain = build_chain(spots=[95] * 10, prices=[3.00, 1.25] + [1.0] * 8)
        trade, _ = run_cohort(chain, chain.option_days[0], CFG, ALWAYS)
        assert trade.exit_reason == 'policy_close_now'
        assert trade.buyback == pytest.approx(1.25)
        assert trade.pnl_per_share == pytest.approx(1.75)
        assert trade.assigned is False

    def test_slippage_raises_the_buyback_cost(self):
        chain = build_chain(spots=[95] * 10, prices=[3.00, 1.00] + [1.0] * 8)
        cfg = {**CFG, 'slippage': 0.05}
        trade, _ = run_cohort(chain, chain.option_days[0], cfg, ALWAYS)
        assert trade.buyback == pytest.approx(1.05)

    def test_covered_call_pnl_never_exceeds_premium(self):
        """Sanity invariant: you cannot make more than you sold it for."""
        chain = build_chain(spots=[95, 90, 85, 80] + [80] * 6,
                            prices=[2.00] + [0.01] * 9)
        trade, _ = run_cohort(chain, chain.option_days[0], CFG, NEVER)
        assert trade.pnl_per_share <= trade.premium + 1e-9


# ============================================================
# Rational early exercise (Natenberg Ch. 12)
# ============================================================

class TestEarlyExercise:
    def _chain_with_div(self, option_price, div_amount, spot=105.0):
        # ex-div lands on the 4th bar; day 3 is therefore days_to_exdiv == 1
        days = pd.bdate_range('2025-01-02', periods=10)
        return build_chain(
            spots=[spot] * 10,
            prices=[3.00] + [option_price] * 9,
            dividends=[(str(days[3])[:10], div_amount)],
        )

    def test_assigned_when_extrinsic_below_dividend(self):
        """ITM, ex-div tomorrow, extrinsic 0.10 < dividend 0.50 -> exercised."""
        chain = self._chain_with_div(option_price=5.10, div_amount=0.50)
        trade, _ = run_cohort(chain, chain.option_days[0], CFG, NEVER)
        assert trade.exit_reason == 'early_exercise'
        assert trade.assigned is True
        assert trade.assignment_type == 'early_exdiv'
        assert trade.buyback == pytest.approx(5.0)   # intrinsic 105 - 100

    def test_not_assigned_when_extrinsic_above_dividend(self):
        """Same position, extrinsic 1.00 > dividend 0.50 -> holder waits."""
        chain = self._chain_with_div(option_price=6.00, div_amount=0.50)
        trade, _ = run_cohort(chain, chain.option_days[0], CFG, NEVER)
        assert trade.assignment_type != 'early_exdiv'

    def test_not_assigned_when_otm(self):
        chain = self._chain_with_div(option_price=0.05, div_amount=0.50, spot=95.0)
        trade, _ = run_cohort(chain, chain.option_days[0], CFG, NEVER)
        assert trade.assignment_type != 'early_exdiv'

    def test_closing_first_prevents_the_assignment(self):
        """The copilot acts in the morning; exercise is decided at that close.
        A policy that closes must therefore beat the assignment."""
        chain = self._chain_with_div(option_price=5.10, div_amount=0.50)
        trade, _ = run_cohort(chain, chain.option_days[0], CFG, ALWAYS)
        assert trade.assigned is False
        assert trade.exit_reason == 'policy_close_now'


# ============================================================
# Probability exit policy
# ============================================================

class TestProbabilityPolicy:
    def _ctx(self, pct_from_strike, dte, spot=100.0, **kw):
        strike = spot * (1 + pct_from_strike / 100)
        base = dict(ticker='TEST', date=pd.Timestamp('2025-06-01'), spot=spot,
                    strike=strike, option_price=1.0, sold_price=2.0, dte=dte,
                    days_to_exdiv=None, dividend=None,
                    expiration=pd.Timestamp('2025-07-01'), price_is_stale=False)
        base.update(kw)
        return DayContext(**base)

    def test_far_otm_short_dated_holds(self):
        """5-10% OTM at 3 DTE is 1.7% assignment risk — the whole point of H17
        is that a distance rule closes this and a probability rule does not."""
        policy = make_probability_policy(0.10, 0.25)
        action, _ = policy(self._ctx(pct_from_strike=7, dte=2))
        assert action == HOLD

    def test_same_distance_long_dated_closes(self):
        """Same 7% OTM at 40 DTE is 38% risk -> CLOSE_NOW."""
        policy = make_probability_policy(0.10, 0.25)
        action, _ = policy(self._ctx(pct_from_strike=7, dte=40))
        assert action == CLOSE_NOW

    def test_threshold_band_gives_close_soon(self):
        """>10% OTM at 40 DTE is 5.9% risk; a 5%/25% pair puts it in the band."""
        policy = make_probability_policy(0.05, 0.25)
        action, _ = policy(self._ctx(pct_from_strike=12, dte=40))
        assert action == CLOSE_SOON

    def test_emergency_overrides_probability(self):
        """ITM + ex-div <= 3 days fires regardless of the table. H17 must not
        touch the $400K rule."""
        policy = make_probability_policy(0.99, 0.99)
        ctx = self._ctx(pct_from_strike=-2, dte=20, days_to_exdiv=1, dividend=0.5)
        action, verdict = policy(ctx)
        assert action == CLOSE_NOW
        assert verdict == 'EMERGENCY'

    def test_higher_thresholds_never_close_more_often(self):
        """Monotonicity: loosening a threshold cannot produce more closes."""
        tight = make_probability_policy(0.05, 0.15)
        loose = make_probability_policy(0.30, 0.60)
        rank = {HOLD: 0, CLOSE_SOON: 1, CLOSE_NOW: 2}
        for pct in (-5, -1, 0, 1, 3, 6, 12):
            for dte in (1, 5, 10, 20, 45):
                ctx = self._ctx(pct_from_strike=pct, dte=dte)
                assert rank[loose(ctx)[0]] <= rank[tight(ctx)[0]]


# ============================================================
# CLOSE_SOON delay
# ============================================================

class TestCloseSoonDelay:
    def test_close_soon_waits_the_configured_window(self):
        chain = build_chain(spots=[95] * 12, prices=[2.00] + [1.0] * 11)
        soon = lambda ctx: (CLOSE_SOON, 'SOON')
        trade, _ = run_cohort(chain, chain.option_days[0],
                              {**CFG, 'close_soon_days': 5}, soon)
        assert trade.exit_reason == 'policy_close_soon'
        assert trade.days_held >= 5

    def test_close_soon_days_zero_closes_immediately(self):
        chain = build_chain(spots=[95] * 12, prices=[2.00] + [1.0] * 11)
        soon = lambda ctx: (CLOSE_SOON, 'SOON')
        trade, _ = run_cohort(chain, chain.option_days[0],
                              {**CFG, 'close_soon_days': 0}, soon)
        assert trade.exit_reason == 'policy_close_soon'
        assert trade.days_held <= 1   # the very first bar after entry

    def test_close_now_beats_an_armed_close_soon(self):
        calls = {'n': 0}

        def policy(ctx):
            calls['n'] += 1
            return (CLOSE_SOON, 'SOON') if calls['n'] < 3 else (CLOSE_NOW, 'NOW')

        chain = build_chain(spots=[95] * 12, prices=[2.00] + [1.0] * 11)
        trade, _ = run_cohort(chain, chain.option_days[0], CFG, policy)
        assert trade.exit_reason == 'policy_close_now'


# ============================================================
# Missing-price accounting
# ============================================================

class TestMissingPrices:
    def test_missing_price_is_carried_forward_and_counted(self):
        """tasks/lessons.md 2026-03-23: no silent skips. A day with no trade
        must reuse the last known price AND increment the counter."""
        chain = build_chain(spots=[95] * 10,
                            prices=[2.00, None, None, 0.40] + [0.40] * 6)
        trade, _ = run_cohort(chain, chain.option_days[0], CFG, NEVER)
        assert trade.missing_price_days == 2
        assert trade.priced_days == len(chain.option_days) - 1 - 2

    def test_never_repriced_trade_is_flagged(self):
        # expiry lands on the last bar (2025-01-09), which has no trade, so the
        # position lives its whole life on the carried-forward entry price.
        chain = build_chain(spots=[95] * 6, prices=[2.00] + [None] * 5,
                            expiry_offset=7)
        trades, diag = cc_sim.run(chain, CFG, NEVER, progress_every=0)
        assert diag['never_repriced_trades'] >= 1
        assert diag['missing_price_pct'] > 0

    def test_entry_beyond_data_window_is_rejected_not_truncated(self):
        chain = build_chain(spots=[95] * 5, prices=[2.00] * 5, expiry_offset=400,
                            pad_expiry_bar=False)
        trade, reason = run_cohort(chain, chain.option_days[0], CFG, NEVER)
        assert trade is None
        assert reason == 'expiry_beyond_data'


# ============================================================
# Walk-forward split
# ============================================================

class TestWalkForward:
    def _trades(self, dates):
        return [Trade(ticker='T', entry_date=d, exit_date=d, symbol='S',
                      strike=100, expiration=d, dte_at_entry=30, entry_spot=100,
                      exit_spot=100, premium=1.0, buyback=0.0, pnl_per_share=1.0,
                      exit_reason='x', assigned=False, assignment_type='',
                      days_held=1, missing_price_days=0, priced_days=1,
                      verdict_at_exit='v') for d in dates]

    def test_train_strictly_precedes_test(self):
        dates = [f'2025-01-{d:02d}' for d in range(1, 31)]
        train, test, cut = walk_forward_split(self._trades(dates), 0.67)
        assert max(t.entry_date for t in train) < min(t.entry_date for t in test)

    def test_split_is_exhaustive_and_disjoint(self):
        dates = [f'2025-01-{d:02d}' for d in range(1, 31)]
        trades = self._trades(dates)
        train, test, _ = walk_forward_split(trades, 0.67)
        assert len(train) + len(test) == len(trades)
        assert not (set(id(t) for t in train) & set(id(t) for t in test))

    def test_proportions_are_roughly_67_33(self):
        dates = [f'2025-{m:02d}-{d:02d}' for m in range(1, 13) for d in range(1, 26)]
        train, test, _ = walk_forward_split(self._trades(dates), 0.67)
        assert 0.6 < len(train) / (len(train) + len(test)) < 0.75

    def test_empty_input(self):
        assert walk_forward_split([], 0.67) == ([], [], None)


# ============================================================
# Scorecard
# ============================================================

class TestScore:
    def _t(self, premium, buyback, assigned=False, atype=''):
        return Trade(ticker='T', entry_date='2025-01-01', exit_date='2025-02-01',
                     symbol='S', strike=100, expiration='2025-02-01',
                     dte_at_entry=30, entry_spot=100, exit_spot=100,
                     premium=premium, buyback=buyback,
                     pnl_per_share=premium - buyback, exit_reason='policy_close_now',
                     assigned=assigned, assignment_type=atype, days_held=30,
                     missing_price_days=0, priced_days=30, verdict_at_exit='v')

    def test_retention_is_net_over_gross(self):
        s = score([self._t(2.0, 1.0), self._t(2.0, 1.0)])
        assert s['gross_premium'] == 400.0
        assert s['net_pnl'] == 200.0
        assert s['retention_pct'] == 50.0

    def test_assignments_split_by_type(self):
        s = score([self._t(2.0, 5.0, True, 'early_exdiv'),
                   self._t(2.0, 5.0, True, 'expiry'),
                   self._t(2.0, 1.0)])
        assert s['assignments'] == 2
        assert s['early_assignments'] == 1
        assert s['expiry_assignments'] == 1

    def test_win_and_loss_rates_sum_with_breakeven(self):
        s = score([self._t(2.0, 1.0), self._t(2.0, 3.0), self._t(2.0, 2.0)])
        assert s['win_rate'] + s['loss_rate'] == pytest.approx(66.7, abs=0.2)

    def test_empty_is_zeroed_not_crashing(self):
        s = score([])
        assert s['n_trades'] == 0 and s['retention_pct'] == 0.0


# ============================================================
# Paired comparison
# ============================================================

class TestPairedDifference:
    def _t(self, date, pnl):
        return Trade(ticker='T', entry_date=date, exit_date=date, symbol='S',
                     strike=100, expiration=date, dte_at_entry=30, entry_spot=100,
                     exit_spot=100, premium=2.0, buyback=2.0 - pnl,
                     pnl_per_share=pnl, exit_reason='x', assigned=False,
                     assignment_type='', days_held=1, missing_price_days=0,
                     priced_days=1, verdict_at_exit='v')

    def test_pairs_only_shared_entries(self):
        a = [self._t('2025-01-01', 1.0), self._t('2025-01-02', 1.0)]
        b = [self._t('2025-01-02', 2.0), self._t('2025-01-03', 5.0)]
        r = paired_difference(a, b)
        assert r['n_paired'] == 1
        assert r['mean_delta'] == pytest.approx(100.0)

    def test_counts_direction(self):
        a = [self._t('2025-01-01', 1.0), self._t('2025-01-02', 1.0),
             self._t('2025-01-03', 1.0)]
        b = [self._t('2025-01-01', 2.0), self._t('2025-01-02', 0.0),
             self._t('2025-01-03', 1.0)]
        r = paired_difference(a, b)
        assert (r['better'], r['worse'], r['same']) == (1, 1, 1)

    def test_no_overlap(self):
        r = paired_difference([self._t('2025-01-01', 1.0)],
                              [self._t('2025-02-01', 1.0)])
        assert r['n_paired'] == 0
