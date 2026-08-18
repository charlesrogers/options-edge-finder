"""
Tests for the mandatory loader date window (Exp 019 blocking precondition).

Background: the Exp 019 purchase (2026-08-17) put 2020 and 2022 option files
into data/databento/raw/ alongside the 2023-26 data. Both loaders glob
'{ticker}_ohlcv*' and concatenate every match, so an implicit window silently
mixes eras. Exp 022's corrected baseline is defined on the recent era; if it
ingested the stress years, H21 would later compare the stress years against
themselves and the comparison would be meaningless.

These tests assert the window is required, is actually applied, and that the
cache cannot serve one window's data for another.

Run: pytest tests/test_loader_date_window.py -v
"""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'experiments'))

import cc_sim
import backtest_engine


RAW_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'databento', 'raw')
HAVE_DATA = os.path.exists(RAW_DIR) and any(
    f.endswith('.dbn.zst') for f in os.listdir(RAW_DIR)
) if os.path.exists(RAW_DIR) else False

needs_data = pytest.mark.skipif(not HAVE_DATA,
                                reason='Databento raw archive not present')


# ------------------------------------------------------------------
# The window is REQUIRED — omission must fail loudly, never default.
# ------------------------------------------------------------------

def test_cc_sim_load_calls_requires_window():
    with pytest.raises(ValueError, match='requires an explicit start and end'):
        cc_sim.load_calls('AAPL', None, None)


def test_cc_sim_load_ticker_requires_window():
    with pytest.raises(ValueError, match='requires an explicit start and end'):
        cc_sim.load_ticker('AAPL')


def test_backtest_engine_requires_window():
    with pytest.raises(ValueError, match='requires an explicit start and end'):
        backtest_engine.load_option_data('AAPL')


def test_reversed_window_rejected():
    with pytest.raises(ValueError, match='is after end'):
        cc_sim.load_calls('AAPL', '2026-01-01', '2020-01-01')


# ------------------------------------------------------------------
# The window constants must not overlap — that is the whole point.
# ------------------------------------------------------------------

def test_windows_are_disjoint():
    """Legacy baseline and stress windows must not share a single day."""
    legacy = (pd.Timestamp(cc_sim.WINDOW_LEGACY_PRE_STRESS[0]),
              pd.Timestamp(cc_sim.WINDOW_LEGACY_PRE_STRESS[1]))
    for name in ('WINDOW_STRESS_2020', 'WINDOW_STRESS_2020_CRASH',
                 'WINDOW_STRESS_2022'):
        lo, hi = (pd.Timestamp(x) for x in getattr(cc_sim, name))
        assert hi < legacy[0] or lo > legacy[1], (
            f'{name} overlaps WINDOW_LEGACY_PRE_STRESS — a baseline run would '
            f'ingest stress data')


def test_engine_and_cc_sim_windows_agree():
    """The duplicated constants must stay in sync across the two modules."""
    assert backtest_engine.WINDOW_LEGACY_PRE_STRESS == cc_sim.WINDOW_LEGACY_PRE_STRESS
    assert backtest_engine.WINDOW_STRESS_2020 == cc_sim.WINDOW_STRESS_2020
    assert backtest_engine.WINDOW_STRESS_2022 == cc_sim.WINDOW_STRESS_2022


# ------------------------------------------------------------------
# The window must actually be applied to real data.
# ------------------------------------------------------------------

@needs_data
def test_legacy_window_excludes_stress_years():
    """The regression this whole change exists to prevent."""
    df = backtest_engine.load_option_data('AAPL', *backtest_engine.WINDOW_LEGACY_PRE_STRESS)
    assert not df.empty, 'AAPL legacy window returned nothing'
    years = set(df.index.year)
    assert 2020 not in years, f'2020 leaked into the legacy baseline: {sorted(years)}'
    assert 2022 not in years, f'2022 leaked into the legacy baseline: {sorted(years)}'


@needs_data
def test_stress_window_excludes_recent_years():
    """The mirror case: a stress run must not pick up 2025-26 data."""
    df = backtest_engine.load_option_data('AAPL', *backtest_engine.WINDOW_STRESS_2020)
    assert not df.empty, 'AAPL 2020 stress window returned nothing'
    years = set(df.index.year)
    assert years == {2020}, f'stress window is not 2020-only: {sorted(years)}'


@needs_data
def test_windows_partition_the_archive():
    """Legacy + stress must together account for every AAPL row, with no double
    counting. Catches a window constant that silently drops or duplicates data."""
    legacy = backtest_engine.load_option_data('AAPL', *backtest_engine.WINDOW_LEGACY_PRE_STRESS)
    stress = backtest_engine.load_option_data('AAPL', *backtest_engine.WINDOW_STRESS_2020)
    both = backtest_engine.load_option_data('AAPL', '2019-01-01', '2027-01-01')
    assert len(legacy) + len(stress) == len(both), (
        f'legacy {len(legacy):,} + stress {len(stress):,} != all {len(both):,} — '
        f'the windows do not partition the archive')


@needs_data
def test_empty_window_raises_rather_than_returning_empty():
    """A window with no data is a spec error. Silent empties are the project's
    signature bug class (see the KKR '0.0% + ALL VALID' incident)."""
    with pytest.raises(ValueError, match='no option data in that window'):
        cc_sim.load_calls('AAPL', '2014-01-01', '2014-12-31')


@needs_data
def test_cache_is_keyed_by_window():
    """Two windows must never share a cache entry. Before this fix the cache key
    was '{ticker}_calls.parquet' for every window."""
    a = cc_sim._cache_path('AAPL_calls_2020-02-01_2020-09-30.parquet')
    b = cc_sim._cache_path('AAPL_calls_2023-01-01_2026-12-31.parquet')
    assert a != b
    # And the loader must produce distinct row counts for the two eras.
    stress = cc_sim.load_calls('AAPL', *cc_sim.WINDOW_STRESS_2020)
    legacy = cc_sim.load_calls('AAPL', *cc_sim.WINDOW_LEGACY_PRE_STRESS)
    assert set(pd.to_datetime(stress['date']).dt.year) == {2020}
    assert 2020 not in set(pd.to_datetime(legacy['date']).dt.year)


@needs_data
def test_googl_usable_in_2020_but_not_recent():
    """GOOGL gained 2020 data in Exp 019; it is still unusable for baselines."""
    with pytest.raises(ValueError, match='not backtestable'):
        cc_sim.load_ticker('GOOGL', *cc_sim.WINDOW_LEGACY_PRE_STRESS, verbose=False)
    # Does not raise for the 2020 crash window.
    chain = cc_sim.load_ticker('GOOGL', *cc_sim.WINDOW_STRESS_2020_CRASH, verbose=False)
    assert chain is not None
