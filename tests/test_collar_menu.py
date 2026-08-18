"""
Tests for collar_menu.py — the zero-cost collar menu generator.

This prices six-figure hedges on $10M+ concentrated positions. A sign error on
the net cost, or a basis that doesn't roll the net in, silently flips "risking
10% to make 20%" into a materially different trade. Every number that appears
in the published table is checked here against hand arithmetic.

No network: every test builds its own chain rows.
"""

import math
import sys
import os
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import collar_menu as cm


NOW = datetime(2026, 8, 17, 18, 0, tzinfo=timezone.utc)


def make_row(strike, bid, ask, last=None, oi=5000, volume=100,
             iv=0.30, traded=NOW, symbol="TEST"):
    return {
        "contractSymbol": symbol,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "lastPrice": last if last is not None else (bid + ask) / 2,
        "volume": volume,
        "openInterest": oi,
        "impliedVolatility": iv,
        "lastTradeDate": traded.isoformat().replace("+00:00", "Z"),
    }


def make_leg(strike, bid, ask, kind="p", spot=100.0, T=1.0, r=0.045, q=0.0,
             **kw):
    return cm.Leg(make_row(strike, bid, ask, **kw), kind, spot, T, r, q, NOW)


# ============================================================
# Leg quotes: mid, width, fallback
# ============================================================

def test_two_sided_quote_uses_mid_and_width():
    leg = make_leg(90, bid=4.00, ask=4.40)
    assert leg.quoted is True
    assert leg.mid == pytest.approx(4.20)
    assert leg.width == pytest.approx(0.40)
    assert leg.price_source == "mid"
    assert "no-bid" not in leg.flags


def test_zero_bid_falls_back_to_last_and_is_flagged():
    """Outside RTH Yahoo returns bid=ask=0. That must never read as tradeable."""
    leg = make_leg(90, bid=0.0, ask=0.0, last=4.92)
    assert leg.quoted is False
    assert leg.mid == pytest.approx(4.92)
    assert leg.width is None
    assert leg.price_source == "last"
    assert "no-bid" in leg.flags and "no-ask" in leg.flags


def test_nan_bid_is_treated_as_no_bid():
    leg = make_leg(90, bid=float("nan"), ask=1.00, last=0.90)
    assert leg.quoted is False
    assert "no-bid" in leg.flags


def test_crossed_market_is_not_treated_as_quoted():
    leg = make_leg(90, bid=5.00, ask=4.00, last=4.50)
    assert leg.quoted is False


def test_width_flags_fire_at_the_documented_thresholds():
    # width/mid = 0.10 -> clean
    assert not [f for f in make_leg(90, 0.95, 1.05).flags if "wide" in f or "absurd" in f]
    # width/mid = 0.50/1.25 = 40% -> wide, not absurd
    assert any(f.startswith("wide") for f in make_leg(90, 1.00, 1.50).flags)
    # width/mid = 1.80/1.10 = 164% -> absurd
    assert any(f.startswith("absurd-width") for f in make_leg(90, 0.20, 2.00).flags)


def test_thin_oi_and_stale_flags():
    leg = make_leg(90, 1.00, 1.10, oi=3,
                   traded=NOW - timedelta(days=cm.STALE_DAYS + 5))
    assert any(f.startswith("thin OI") for f in leg.flags)
    assert any(f.startswith("stale") for f in leg.flags)


def test_cross_cost_is_width_times_multiplier_times_contracts():
    leg = make_leg(90, 4.00, 4.40)          # $0.40 wide
    assert leg.cross_cost(100) == pytest.approx(0.40 * 100 * 100)   # $4,000


def test_cross_cost_is_none_without_a_two_sided_market():
    assert make_leg(90, 0.0, 0.0, last=4.0).cross_cost(100) is None


# ============================================================
# Implied vol solved from the mid
# ============================================================

def test_iv_round_trips_through_the_pricer():
    """Price at a known sigma, then confirm the leg recovers it from the mid."""
    S, K, T, r, q, sigma = 100.0, 90.0, 1.0, 0.045, 0.02, 0.31
    px = cm._bsm_price("p", S, K, T, r, sigma, q)
    leg = make_leg(K, bid=px - 0.005, ask=px + 0.005, spot=S, T=T, r=r, q=q)
    assert leg.iv == pytest.approx(sigma, abs=1e-3)


def test_iv_round_trips_for_calls_too():
    S, K, T, r, q, sigma = 100.0, 115.0, 0.25, 0.045, 0.02, 0.42
    px = cm._bsm_price("c", S, K, T, r, sigma, q)
    leg = make_leg(K, bid=px - 0.005, ask=px + 0.005, kind="c",
                   spot=S, T=T, r=r, q=q)
    assert leg.iv == pytest.approx(sigma, abs=1e-3)


def test_iv_is_none_when_price_is_at_or_below_intrinsic():
    # Deep ITM call marked at intrinsic — unsolvable, must not invent a number.
    leg = make_leg(50, bid=49.5, ask=50.5, kind="c", spot=100.0, T=1.0)
    assert leg.iv is None


def test_bisection_fallback_matches_vollib():
    """The no-py_vollib path must produce the same vol, not a silent divergence."""
    S, K, T, r, q, sigma = 100.0, 90.0, 0.5, 0.045, 0.01, 0.27
    px = cm._bsm_price("p", S, K, T, r, sigma, q)
    assert cm._bisect_iv(px, S, K, T, r, q, "p") == pytest.approx(sigma, abs=1e-3)


def test_bsm_price_matches_a_published_reference():
    """S=100 K=100 T=1 r=5% q=0 sigma=20% -> call 10.4506 (Hull, standard case)."""
    assert cm._bsm_price("c", 100, 100, 1.0, 0.05, 0.20, 0.0) == pytest.approx(10.4506, abs=1e-3)
    # Put-call parity must hold at the same inputs.
    c = cm._bsm_price("c", 100, 95, 1.0, 0.05, 0.20, 0.03)
    p = cm._bsm_price("p", 100, 95, 1.0, 0.05, 0.20, 0.03)
    assert c - p == pytest.approx(100 * math.exp(-0.03) - 95 * math.exp(-0.05), abs=1e-6)


# ============================================================
# Zero-cost strike interpolation
# ============================================================

def _calls(pairs):
    return [make_leg(k, bid=m - 0.05, ask=m + 0.05, kind="c", spot=100.0)
            for k, m in pairs]


def test_interpolates_between_the_bracketing_strikes():
    # Put costs 3.00. Calls: 110 -> 4.00, 120 -> 2.00.
    # Zero cost sits where the call mid == 3.00, i.e. halfway: K* = 115.
    k, status = cm.interpolate_zero_cost_strike(_calls([(110, 4.0), (120, 2.0)]), 3.0)
    assert status == "ok"
    assert k == pytest.approx(115.0)


def test_interpolation_is_linear_not_midpoint():
    # 110 -> 5.00, 120 -> 1.00, target 4.00 -> 25% of the way -> K* = 112.5
    k, status = cm.interpolate_zero_cost_strike(_calls([(110, 5.0), (120, 1.0)]), 4.0)
    assert status == "ok"
    assert k == pytest.approx(112.5)


def test_put_more_expensive_than_every_otm_call_reports_below_chain():
    """Heavy put skew: no zero-cost collar exists without selling an ITM call."""
    k, status = cm.interpolate_zero_cost_strike(_calls([(110, 2.0), (120, 1.0)]), 9.0)
    assert status == "below_chain"
    assert k is None


def test_put_cheaper_than_every_listed_call_reports_above_chain():
    k, status = cm.interpolate_zero_cost_strike(_calls([(110, 5.0), (120, 3.0)]), 0.25)
    assert status == "above_chain"
    assert k is None


def test_too_few_priced_strikes_is_unpriceable():
    k, status = cm.interpolate_zero_cost_strike(_calls([(110, 5.0)]), 3.0)
    assert status == "unpriceable"
    assert k is None


def test_unsorted_and_unpriced_strikes_do_not_break_the_bracket_scan():
    legs = _calls([(120, 2.0), (110, 4.0), (130, 1.0)])
    legs.append(make_leg(115, bid=0.0, ask=0.0, last=0.0, kind="c", spot=100.0))
    k, status = cm.interpolate_zero_cost_strike(legs, 3.0)
    assert status == "ok"
    assert k == pytest.approx(115.0)


# ============================================================
# Collar economics — the numbers Charles and Dad will read
# ============================================================

def _row(spot=100.0, put_k=90.0, put_bid=4.90, put_ask=5.10,
         call_k=115.0, call_bid=4.40, call_ask=4.60, contracts=100):
    put = make_leg(put_k, put_bid, put_ask, kind="p", spot=spot)
    call = make_leg(call_k, call_bid, call_ask, kind="c", spot=spot)
    return cm.build_collar_row(0.10, spot, put, call, 114.0, "ok", contracts)


def test_net_cost_is_put_paid_minus_call_received():
    r = _row()
    assert r["net_per_share"] == pytest.approx(5.00 - 4.50)      # $0.50 debit


def test_credit_collar_carries_a_negative_net():
    r = _row(put_bid=3.90, put_ask=4.10, call_bid=4.40, call_ask=4.60)
    assert r["net_per_share"] == pytest.approx(4.00 - 4.50)      # -$0.50 credit


def test_worst_case_fill_crosses_both_spreads():
    """Pay the ask on the put, hit the bid on the call — the honest fill at size."""
    r = _row()
    assert r["net_per_share_cross"] == pytest.approx(5.10 - 4.40)     # $0.70
    assert r["net_per_share_cross"] > r["net_per_share"]


def test_net_total_scales_by_multiplier_and_contracts():
    r = _row(contracts=100)
    assert r["net_total"] == pytest.approx(0.50 * 100 * 100)          # $5,000


def test_basis_rolls_the_net_cost_in():
    r = _row()
    assert r["effective_basis"] == pytest.approx(100.0 + 0.50)


def test_max_loss_and_gain_are_measured_off_the_effective_basis():
    r = _row()
    basis = 100.50
    assert r["max_loss_pct"] == pytest.approx((90.0 - basis) / basis)
    assert r["max_gain_pct"] == pytest.approx((115.0 - basis) / basis)
    # A debit makes the floor hurt more than the raw 10% strike distance.
    assert r["max_loss_pct"] < -0.10


def test_a_credit_improves_both_sides_versus_a_debit():
    debit = _row(put_bid=4.90, put_ask=5.10)
    credit = _row(put_bid=3.90, put_ask=4.10)
    assert credit["max_loss_pct"] > debit["max_loss_pct"]     # loses less
    assert credit["max_gain_pct"] > debit["max_gain_pct"]     # gains more


def test_risk_reward_is_gain_over_absolute_loss():
    r = _row()
    assert r["risk_reward"] == pytest.approx(
        r["max_gain_pct"] / abs(r["max_loss_pct"]))
    assert r["risk_reward"] > 0


def test_a_collar_can_never_lose_more_than_the_floor_allows():
    """Sanity floor: the put caps the loss. Max loss must stay above -100%."""
    for put_k, net_bid, net_ask in [(90.0, 4.90, 5.10), (80.0, 1.90, 2.10),
                                    (70.0, 0.40, 0.60)]:
        r = _row(put_k=put_k, put_bid=net_bid, put_ask=net_ask)
        assert -1.0 < r["max_loss_pct"] < 0.0
        assert r["max_gain_pct"] > 0.0


def test_otm_percentages_are_reported_off_spot():
    r = _row(spot=100.0, put_k=90.0, call_k=115.0)
    assert r["put_otm_pct"] == pytest.approx(0.10)
    assert r["call_otm_pct"] == pytest.approx(0.15)


def test_row_is_marked_indicative_when_a_leg_has_no_two_sided_market():
    put = make_leg(90.0, 0.0, 0.0, last=5.00, kind="p", spot=100.0)
    call = make_leg(115.0, 4.40, 4.60, kind="c", spot=100.0)
    r = cm.build_collar_row(0.10, 100.0, put, call, 114.0, "ok", 100)
    assert r["indicative"] is True
    assert r["net_per_share_cross"] is None      # can't cross a spread that isn't there


def test_unpriceable_row_is_marked_not_priceable_rather_than_guessed():
    put = make_leg(90.0, 0.0, 0.0, last=0.0, kind="p", spot=100.0)
    call = make_leg(115.0, 4.40, 4.60, kind="c", spot=100.0)
    r = cm.build_collar_row(0.10, 100.0, put, call, None, "ok", 100)
    assert r["priceable"] is False
    assert "net_per_share" not in r


# ============================================================
# Expiry selection
# ============================================================

def test_picks_the_listed_expiry_nearest_each_target():
    today = date(2026, 8, 17)
    exps = ["2026-08-21", "2026-11-20", "2027-06-17", "2027-09-17", "2028-01-21"]
    picks = cm.pick_expiries("X", exps, today, cm.TENORS)
    assert picks[0][2][0][0] == "2026-11-20"    # 95 DTE, nearest to 91
    assert picks[1][2][0][0] == "2027-09-17"    # 396 DTE, nearest to 365


def test_expired_and_malformed_dates_are_dropped():
    today = date(2026, 8, 17)
    exps = ["2026-01-01", "not-a-date", "2026-11-20"]
    picks = cm.pick_expiries("X", exps, today, [("t", 91)])
    dates = [d for d, _ in picks[0][2]]
    assert dates == ["2026-11-20"]


def test_ranked_fallbacks_are_returned_for_flaky_expiries():
    """Some listed expiries 500 on the proxy; the caller needs a second choice."""
    today = date(2026, 8, 17)
    exps = ["2026-11-20", "2026-12-18", "2027-01-15"]
    picks = cm.pick_expiries("X", exps, today, [("t", 91)])
    assert len(picks[0][2]) == 3
    assert picks[0][2][0][0] == "2026-11-20"


# ============================================================
# Rendering — the page must carry its caveats
# ============================================================

class _Args:
    rate = 0.045
    contracts = 100
    shares = 10_000


def _menu():
    put = make_leg(90.0, 4.90, 5.10, kind="p", spot=100.0)
    call = make_leg(115.0, 4.40, 4.60, kind="c", spot=100.0)
    row = cm.build_collar_row(0.10, 100.0, put, call, 114.0, "ok", 100)
    return {
        "ticker": "TEST", "name": "Test Co", "dividend_yield": 0.02,
        "ex_dividend_date": "2026-09-01", "earnings_date": "2026-10-01",
        "contracts": 100, "shares": 10_000,
        "tenors": [{
            "label": "~3 month", "target_dte": 91, "expiration": "2026-11-20",
            "dte": 95, "spot": 100.0,
            "quote_health": {"legs": 100, "quoted": 95, "quoted_frac": 0.95},
            "rows": [row],
        }],
    }


def test_document_carries_the_tax_caveat_verbatim():
    doc = cm.render_document([_menu()], _Args())
    assert cm.TAX_CAVEAT in doc


def test_document_states_it_is_not_a_recommendation():
    doc = cm.render_document([_menu()], _Args())
    assert "not a recommendation" in doc.lower()


def test_document_never_claims_exact_zero_cost():
    doc = cm.render_document([_menu()], _Args())
    assert "zero-cost does not exist" in doc.lower()


def test_row_renders_the_one_line_risk_reward_framing():
    doc = cm.render_document([_menu()], _Args())
    assert "risking" in doc and "to make" in doc


def test_dead_quote_banner_appears_only_when_quotes_are_dead():
    healthy = _menu()
    assert "Quotes are mostly dead" not in cm.render_document([healthy], _Args())
    dead = _menu()
    dead["tenors"][0]["quote_health"] = {"legs": 100, "quoted": 2, "quoted_frac": 0.02}
    assert "Quotes are mostly dead" in cm.render_document([dead], _Args())


def test_menu_table_has_one_cell_per_header_column():
    doc = cm.render_document([_menu()], _Args())
    lines = [l for l in doc.splitlines() if l.startswith("| ")]
    header = next(l for l in lines if "Zero-cost K" in l)
    ncols = header.count("|") - 1
    body = [l for l in lines if l.startswith("| 10% OTM")]
    assert body, "menu row missing"
    for l in body:
        assert l.count("|") - 1 == ncols


def test_unpriceable_row_renders_without_crashing():
    menu = _menu()
    menu["tenors"][0]["rows"] = [{"floor_target_pct": 0.10, "priceable": False,
                                  "status": "no_put_price", "put": None,
                                  "call": None}]
    doc = cm.render_document([menu], _Args())
    assert "no usable price on the put leg" in doc


def test_errored_ticker_renders_without_crashing():
    doc = cm.render_document([{"ticker": "BAD", "error": "no expirations"}], _Args())
    assert "Could not price" in doc


def test_verify_worksheet_shows_the_arithmetic_and_the_contract_symbols():
    text = cm.render_verify(_menu())
    assert "net/share" in text and "basis" in text
    assert "max loss" in text and "max gain" in text
    assert "BUY  PUT" in text and "SELL CALL" in text


def test_leg_picker_prefers_a_priced_strike_over_a_nearer_unquoted_stub():
    """Sparse chains list stub strikes with no price; picking one is a false negative."""
    legs = [
        make_leg(92.5, bid=0.0, ask=0.0, last=0.0, kind="p", spot=100.0),  # nearer, dead
        make_leg(90.0, bid=4.90, ask=5.10, kind="p", spot=100.0),          # priced
    ]
    assert cm.nearest_strike_leg(legs, 92.0).strike == 90.0


def test_leg_picker_falls_back_to_nearest_listed_when_nothing_is_priced():
    legs = [make_leg(92.5, bid=0.0, ask=0.0, last=0.0, kind="p", spot=100.0),
            make_leg(80.0, bid=0.0, ask=0.0, last=0.0, kind="p", spot=100.0)]
    assert cm.nearest_strike_leg(legs, 92.0).strike == 92.5


def test_leg_picker_returns_none_on_an_empty_chain():
    assert cm.nearest_strike_leg([], 100.0) is None
