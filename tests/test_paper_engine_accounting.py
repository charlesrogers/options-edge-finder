"""Accounting and fill-rule tests. Financial logic ships with tests, no exceptions.

Each test that asserts "X does not happen" first demonstrates the setup CAN
produce X (tasks/lessons.md 2026-08-18, the vacuity guard). A test that passes
because it never exercised the code is worse than no test, because it reports
confidence.
"""
import math

import pytest

from paper_engine import accounting, config, quotes


def _q(bid=None, ask=None, spot=100.0, status=quotes.OK, stale=False):
    from datetime import datetime, timezone
    q = quotes.Quote(contract_symbol="X", ticker="T",
                     tick_ts=datetime(2026, 8, 20, 19, 30, tzinfo=timezone.utc),
                     bid=bid, ask=ask, spot=spot, source_status=status)
    q.stale = stale
    return q


# ---------------------------------------------------------------- fill side --

def test_sell_fills_at_bid_and_buy_fills_at_ask():
    """Never mid, never last. The whole conservative-fill guarantee is this."""
    q = _q(bid=0.15, ask=0.55)
    assert accounting.sell_fill_price(q) == 0.15
    assert accounting.buy_fill_price(q) == 0.55
    mid = (0.15 + 0.55) / 2
    assert accounting.sell_fill_price(q) != mid
    assert accounting.buy_fill_price(q) != mid


def test_unusable_side_yields_no_fill_price_rather_than_zero():
    """A missing bid is 'we cannot sell', not 'we sell for nothing'."""
    assert accounting.sell_fill_price(_q(bid=None, ask=0.55)) is None
    assert accounting.sell_fill_price(_q(bid=float("nan"), ask=0.55)) is None
    assert accounting.buy_fill_price(_q(bid=0.15, ask=None)) is None


# ------------------------------------------------------------- hand-checked --

def test_one_cycle_to_the_cent():
    """A full KKR-shaped cycle, computed by hand and asserted exactly.

    Sell 7 contracts at the bid of $0.15, buy back at the ask of $0.55.
      premium  = 0.15 * 100 * 7 = $105.00
      buyback  = 0.55 * 100 * 7 = $385.00
      gross    = (0.15 - 0.55) * 100 * 7 = -$280.00
      commission = 0.65 * 7 * 2 sides    =  $9.10
      net      = -280.00 - 9.10          = -$289.10
    """
    contracts = 7
    entry_comm = accounting.commission(contracts)
    exit_comm = accounting.commission(contracts)
    assert entry_comm == pytest.approx(4.55)
    assert exit_comm == pytest.approx(4.55)

    out = accounting.cycle_pnl(
        premium_per_share=0.15, buyback_per_share=0.55, contracts=contracts,
        entry_commission=entry_comm, exit_commission=exit_comm)

    assert out["gross_pnl"] == pytest.approx(-280.00)
    assert out["commissions_total"] == pytest.approx(9.10)
    assert out["net_pnl"] == pytest.approx(-289.10)
    # Commissions are their own line and are NOT folded into gross.
    assert out["gross_pnl"] != out["net_pnl"]


def test_profitable_cycle_to_the_cent():
    """The other direction, so the sign convention is pinned from both sides."""
    out = accounting.cycle_pnl(premium_per_share=2.00, buyback_per_share=0.50,
                               contracts=1, entry_commission=0.65,
                               exit_commission=0.65)
    assert out["gross_pnl"] == pytest.approx(150.00)
    assert out["net_pnl"] == pytest.approx(148.70)


def test_expiry_worthless_keeps_the_whole_premium_less_one_commission():
    """Nobody trades on a worthless expiry, so there is no exit commission."""
    out = accounting.cycle_pnl(premium_per_share=0.28, buyback_per_share=0.0,
                               contracts=1, entry_commission=0.65,
                               exit_commission=0.0)
    assert out["gross_pnl"] == pytest.approx(28.00)
    assert out["net_pnl"] == pytest.approx(27.35)


def test_defined_risk_sanity_holds_across_a_price_path():
    """A covered call's option leg cannot lose more than buyback minus premium.

    Vacuity guard first: show the ceiling is a real constraint by exhibiting a
    path that approaches it, so a passing assertion is not passing on an empty
    set.
    """
    premium, contracts = 1.00, 3
    losses_seen = []
    for buyback in (0.0, 0.5, 1.0, 5.0, 25.0):
        out = accounting.cycle_pnl(
            premium_per_share=premium, buyback_per_share=buyback,
            contracts=contracts, entry_commission=0, exit_commission=0)
        ceiling = accounting.defined_risk_ceiling(premium, buyback, contracts)
        assert out["gross_pnl"] == pytest.approx(-ceiling)
        if out["gross_pnl"] < 0:
            losses_seen.append(out["gross_pnl"])
    assert losses_seen, "vacuity: no losing path was exercised"
    assert min(losses_seen) == pytest.approx(-7200.0)


# --------------------------------------------------------------- retention --

def test_retention_shows_both_halves_and_flags_a_negative_numerator():
    r = accounting.retention(kept_usd=-4043.94, collected_usd=32295.37)
    assert r["pct"] == pytest.approx(-12.5, abs=0.1)
    assert r["kept_usd"] == pytest.approx(-4043.94)
    assert r["collected_usd"] == pytest.approx(32295.37)
    assert r["numerator_negative"] is True


def test_retention_with_no_premium_is_undefined_not_zero():
    r = accounting.retention(kept_usd=0, collected_usd=0)
    assert r["pct"] is None
    assert "undefined" in r["note"]


# ------------------------------------------------------------------ spread --

def test_spread_cost_is_half_a_spread_each_way():
    # 0.40 entry + 0.40 exit, half each, x100 x7 contracts = $280
    assert accounting.spread_cost_usd(0.40, 0.40, 7) == pytest.approx(280.0)


def test_a_settlement_contributes_no_spread_rather_than_zero_as_a_fact():
    """None on the exit side means nobody traded, which is not a $0 spread we
    observed. Both produce 0 dollars here, but only one of them is a claim."""
    assert accounting.spread_cost_usd(0.40, None, 1) == pytest.approx(20.0)


def test_kkr_round_trip_costs_more_than_the_credit():
    """The 2026-08-20 probe, asserted so a future change cannot quietly make
    this strike look tradeable. KKR: bid 0.15, ask 0.55."""
    q = _q(bid=0.15, ask=0.55)
    credit = accounting.sell_fill_price(q) * 100
    cost = accounting.buy_fill_price(q) * 100
    assert cost > credit * 2.5
    assert accounting.spread_pct_of(q, 0.15) == pytest.approx(266.7, abs=0.5)


# -------------------------------------------------------- liquidity floor ---

@pytest.mark.parametrize("kwargs,reason", [
    (dict(bid=None, ask=0.55), "no_bid"),
    (dict(bid=0.15, ask=None), "no_ask"),
    (dict(bid=0.60, ask=0.55), "crossed"),
    (dict(bid=0.01, ask=0.05), "bid_below_floor"),
    (dict(bid=None, ask=None, status=quotes.PROXY_FAILED), "proxy_failed"),
    (dict(bid=None, ask=None, status=quotes.EMPTY_CHAIN), "empty_chain"),
    (dict(bid=None, ask=None, status=quotes.CONTRACT_MISSING), "contract_missing"),
])
def test_liquidity_floor_gives_a_specific_reason_for_every_refusal(kwargs, reason):
    ok, why = quotes.liquidity_check(_q(**kwargs))
    assert ok is False
    assert why.startswith(reason), f"expected {reason}, got {why}"


def test_liquidity_floor_passes_a_real_market():
    ok, why = quotes.liquidity_check(_q(bid=0.15, ask=0.55))
    assert ok is True and why == "ok"
    # Vacuity guard: the same function CAN refuse, proven above, so this pass
    # is a decision rather than a function that always says yes.


def test_proxy_failure_and_empty_chain_are_distinguishable():
    """yf_proxy._get returns {} for both a dead proxy and an empty response.
    The engine must not collapse them into one reason."""
    _, a = quotes.liquidity_check(_q(status=quotes.PROXY_FAILED))
    _, b = quotes.liquidity_check(_q(status=quotes.EMPTY_CHAIN))
    assert a != b
