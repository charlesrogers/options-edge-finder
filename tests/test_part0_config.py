"""
Tests for the Part 0 production changes (Exp 022 / H25 and Exp 023 / H26).

Everything here guards a number a user acts on: the per-ticker IV threshold that decides
whether a call is sold at all, the tier badges that tell Dad how much evidence sits behind
a ticker, and the skip flags on the two tickers that failed validation while live.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ticker_strategies import (
    TICKER_STRATEGIES, TIER_CONFIG, DEFAULT_IV_THRESHOLD,
    get_iv_threshold, get_strategy, get_recommended_tickers,
)


# ------------------------------------------------------------
# get_iv_threshold — the entry gate (Exp 023)
# ------------------------------------------------------------

def test_dis_uses_its_own_threshold():
    """Exp 023 clause 2 was the only pass; DIS sells only above IV rank 75."""
    assert get_iv_threshold('DIS') == 75


def test_every_other_configured_ticker_keeps_the_global_default():
    for ticker in TICKER_STRATEGIES:
        if ticker == 'DIS':
            continue
        assert get_iv_threshold(ticker) == DEFAULT_IV_THRESHOLD, \
            f'{ticker} silently acquired a per-ticker threshold'


def test_unknown_ticker_falls_back_to_the_default():
    assert get_iv_threshold('NVDA') == DEFAULT_IV_THRESHOLD


def test_tmus_gate_was_not_removed_despite_failing_its_trial():
    """
    H26 clause 1 FAILED for TMUS — the gate blocks its winners. The pre-registration is
    explicit that a failed test of a restriction does not license removing it: removal
    means selling MORE calls, which needs its own experiment. Regression guard against a
    future session 'fixing' TMUS by loosening it.
    """
    assert get_iv_threshold('TMUS') == DEFAULT_IV_THRESHOLD


def test_no_deployed_threshold_is_looser_than_the_global_default():
    """
    Pre-registered deployment rule 4: a winning threshold below 50 is a loosening change
    and may not be deployed off Exp 023. This asserts the whole config obeys it.
    """
    for ticker, strat in TICKER_STRATEGIES.items():
        threshold = strat.get('iv_threshold')
        if threshold is not None:
            assert threshold >= DEFAULT_IV_THRESHOLD, \
                f'{ticker} deploys a looser gate than the global rule'


def test_threshold_is_a_usable_percentile():
    for ticker, strat in TICKER_STRATEGIES.items():
        threshold = strat.get('iv_threshold')
        if threshold is not None:
            assert 0 <= threshold <= 100


# ------------------------------------------------------------
# corrected expected_* fields (Exp 022)
# ------------------------------------------------------------

CORRECTED = {'DIS': (267, 80), 'TMUS': (151, 92), 'KKR': (316, 63)}


@pytest.mark.parametrize('ticker,expected', CORRECTED.items())
def test_corrected_expected_fields_are_deployed(ticker, expected):
    """The three tickers that failed H25 carry the fixed engine's numbers, not Exp 008's."""
    pnl, win_rate = expected
    strat = TICKER_STRATEGIES[ticker]
    assert strat['expected_pnl'] == pnl
    assert strat['expected_win_rate'] == win_rate


def test_no_ticker_still_claims_a_100_percent_win_rate():
    """
    Exp 022 killed both 100% win-rate claims (KKR measured 63.3%). A displayed 100% tells
    a user the strategy cannot lose, which is the single most expensive thing this app
    could get wrong.
    """
    for ticker, strat in TICKER_STRATEGIES.items():
        assert strat.get('expected_win_rate') != 100, \
            f'{ticker} claims it never loses'


def test_expected_pnl_is_never_negative_while_recommendable():
    """A ticker whose corrected expectation is a loss must not be in the sell list."""
    for ticker, strat, pnl in get_recommended_tickers():
        assert (strat.get('expected_pnl') or 0) >= 0, \
            f'{ticker} is recommended with a negative expectation'


# ------------------------------------------------------------
# tiers and skips (Exp 022 rule 2, spec directive 8)
# ------------------------------------------------------------

@pytest.mark.parametrize('ticker', ['TMUS', 'KKR'])
def test_low_coverage_tickers_are_on_probation(ticker):
    """TMUS 56.0% and KKR 36.3% repricing coverage, both under the pre-registered 70%."""
    assert get_strategy(ticker)['tier'] == 'probation'


def test_aapl_keeps_its_tier_on_coverage():
    """
    97.1% repricing coverage clears the 70% floor, so no demotion is licensed.

    The rationale changed: on PR #4's engine AAPL was also inside its H25 tolerance.
    On the fully corrected engine it is NOT (measured $141 vs the $299 then deployed).
    The tier survives on coverage alone; the P&L claim was corrected instead.
    """
    assert get_strategy('AAPL')['tier'] == 'conservative'


@pytest.mark.parametrize('ticker', ['AMZN', 'MSFT'])
def test_unvalidated_tickers_are_skipped_not_recommended(ticker):
    strat = get_strategy(ticker)
    assert strat['tier'] == 'skip'
    assert strat['skip'] is True
    assert ticker not in [t for t, _, _ in get_recommended_tickers()]


def test_no_ticker_without_option_data_is_recommendable():
    """
    Spec directive 8's general form: anything the recommendation set returns must have been
    validated on something. Both tickers with zero Databento option history are now skips,
    and GOOGL (5 days) carries the probation badge rather than a clean one.
    """
    recommended = {t for t, _, _ in get_recommended_tickers()}
    assert 'AMZN' not in recommended
    assert 'MSFT' not in recommended
    assert get_strategy('GOOGL')['tier'] == 'probation'


def test_every_skip_explains_itself():
    for ticker, strat in TICKER_STRATEGIES.items():
        if strat.get('skip'):
            assert strat.get('note'), f'{ticker} is skipped with no reason to show'


# ------------------------------------------------------------
# no live claim above the best available measurement (Exp 022 addendum)
# ------------------------------------------------------------

# Median annualised net P&L per contract, measured by Exp 022's re-run on the
# FULLY corrected engine (commit bbbddaa: fabricated IV rank, look-ahead spot,
# stale fills, sticky CLOSE_SOON, NaN dividend guard, uncounted skips).
# Exp 022 as run in PR #4 predates all six fixes, so its numbers sit above these
# for AAPL and below them for the rest.
FIXED_ENGINE_MEASURED_PNL = {'AAPL': 141, 'DIS': 442, 'TMUS': 178, 'KKR': 329}


@pytest.mark.parametrize('ticker', sorted(FIXED_ENGINE_MEASURED_PNL))
def test_no_deployed_pnl_claim_exceeds_the_fixed_engine_measurement(ticker):
    """
    Standing rule: a live income claim may sit BELOW the best available measurement
    (conservative) but never ABOVE it (overstated to the user).

    This is the guard for the specific regression that produced it — AAPL shipped at
    $299 while the corrected engine measured $141, because the engine that produced
    $299 fabricated an IV rank of 50.0 for the first ~9 days of every ticker, and
    50.0 passes the >=50 production gate.
    """
    claimed = TICKER_STRATEGIES[ticker].get('expected_pnl')
    if claimed is None:
        return
    assert claimed <= FIXED_ENGINE_MEASURED_PNL[ticker], (
        f'{ticker} claims ${claimed}/yr per contract but the fixed engine measures '
        f'${FIXED_ENGINE_MEASURED_PNL[ticker]}. Lower the claim or re-measure.'
    )


def test_aapl_carries_the_fixed_engine_number():
    """AAPL has been corrected downward twice, each time for a named engine defect."""
    assert TICKER_STRATEGIES['AAPL']['expected_pnl'] == 141
    assert TICKER_STRATEGIES['AAPL']['expected_win_rate'] == 91
