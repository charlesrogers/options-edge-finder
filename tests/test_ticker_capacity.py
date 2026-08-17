"""
Tests for the Exp 021 liquidity cap.

The cap is the only thing standing between a 10,000-share KKR position and an order for
100 contracts into a strike that trades a median of 3 a day, so it gets boundary tests
rather than a smoke test.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ticker_strategies import TICKER_STRATEGIES, get_max_contracts


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
