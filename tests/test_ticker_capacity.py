"""
Tests for the Exp 021 production changes: the liquidity cap and the probation tier.

The cap is the only thing standing between a 10,000-share KKR position and an order for
100 contracts into a strike that trades a median of 3 a day, so it gets boundary tests
rather than a smoke test.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ticker_strategies import (
    TICKER_STRATEGIES, TIER_CONFIG, get_max_contracts, get_strategy,
    get_recommended_tickers,
)


# ------------------------------------------------------------
# get_max_contracts
# ------------------------------------------------------------

def test_uncapped_ticker_is_plain_share_division():
    contracts, reason = get_max_contracts('AAPL', 10_000)
    assert contracts == 100
    assert reason is None


def test_kkr_is_capped_below_its_share_count():
    contracts, reason = get_max_contracts('KKR', 10_000)
    assert contracts == 7, "KKR must not be sized off share count alone"
    assert reason and 'iquidity' in reason


def test_cap_does_not_inflate_a_small_position():
    """The cap is a ceiling, never a floor — 300 shares is 3 contracts, not 7."""
    contracts, reason = get_max_contracts('KKR', 300)
    assert contracts == 3
    assert reason is None


def test_cap_boundary_exactly_at_the_limit():
    """700 shares = 7 contracts = exactly the cap: allowed, and not flagged as capped."""
    contracts, reason = get_max_contracts('KKR', 700)
    assert contracts == 7
    assert reason is None


def test_cap_boundary_one_contract_over():
    contracts, reason = get_max_contracts('KKR', 800)
    assert contracts == 7
    assert reason is not None


@pytest.mark.parametrize('shares', [0, 1, 99])
def test_fewer_than_one_contract_of_shares_sells_nothing(shares):
    for ticker in ('AAPL', 'KKR'):
        contracts, reason = get_max_contracts(ticker, shares)
        assert contracts == 0
        assert reason is None


def test_unknown_ticker_is_uncapped_not_crashing():
    contracts, reason = get_max_contracts('NVDA', 1_000)
    assert contracts == 10
    assert reason is None


def test_no_capped_ticker_can_ever_exceed_its_cap():
    """Property check across every configured cap, at absurd share counts."""
    for ticker, strat in TICKER_STRATEGIES.items():
        cap = strat.get('max_contracts')
        if cap is None:
            continue
        for shares in (10_000, 100_000, 1_000_000):
            contracts, _ = get_max_contracts(ticker, shares)
            assert contracts <= cap, f'{ticker} exceeded its cap at {shares} shares'


def test_every_cap_has_a_reason_the_ui_can_show():
    for ticker, strat in TICKER_STRATEGIES.items():
        if strat.get('max_contracts') is not None:
            assert strat.get('max_contracts_reason'), \
                f'{ticker} has a cap with no explanation to surface'


# ------------------------------------------------------------
# probation tier
# ------------------------------------------------------------

def test_probation_tier_exists_and_is_distinct_from_untested():
    assert 'probation' in TIER_CONFIG
    assert TIER_CONFIG['probation'] != TIER_CONFIG['untested'], \
        "the spec forbids reusing the 'untested' badge for probation"
    assert TIER_CONFIG['probation']['label'].lower() == 'probation'


def test_googl_is_on_probation_not_good():
    """GOOGL has 5 days of real option data; it must not claim a real-price validation."""
    assert get_strategy('GOOGL')['tier'] == 'probation'


def test_every_configured_tier_has_a_badge():
    for ticker, strat in TICKER_STRATEGIES.items():
        assert strat['tier'] in TIER_CONFIG, f'{ticker} uses an unrendered tier'


def test_probation_tickers_are_still_recommendable():
    """Probation means 'flagged', not 'hidden' — GOOGL still appears in the Sell tab."""
    tickers = [t for t, _, _ in get_recommended_tickers()]
    assert 'GOOGL' in tickers
