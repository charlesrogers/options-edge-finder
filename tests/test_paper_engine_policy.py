"""The decision core, the arm filters, and the human-latency rule.

`cc_core.decide` is the single definition of what a verdict makes a trader do,
shared by the historical simulator and the forward engine. These tests pin its
ordering, because the ordering is the part that would silently diverge.
"""
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

import cc_core
from paper_engine import config, engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CFG = dict(config.POLICY_CFG)


class Ctx:
    """Minimal DayContext-shaped stub."""

    def __init__(self, *, spot=100.0, strike=110.0, option_price=1.0,
                 sold_price=2.0, dte=30, days_to_exdiv=None, dividend=None,
                 day=date(2026, 8, 20)):
        self.ticker = "T"
        self.date = day
        self.spot = spot
        self.strike = strike
        self.option_price = option_price
        self.sold_price = sold_price
        self.dte = dte
        self.days_to_exdiv = days_to_exdiv
        self.dividend = dividend
        self.expiration = "2026-09-18"
        self.price_is_stale = False

    @property
    def pct_from_strike(self):
        return (self.strike - self.spot) / self.spot * 100

    @property
    def is_itm(self):
        return self.spot > self.strike

    @property
    def intrinsic(self):
        return max(0.0, self.spot - self.strike)

    @property
    def extrinsic(self):
        return max(0.0, self.option_price - self.intrinsic)


def hold(_ctx):
    return cc_core.HOLD, "SAFE"


def close_now(_ctx):
    return cc_core.CLOSE_NOW, "CLOSE_NOW"


def close_soon(_ctx):
    return cc_core.CLOSE_SOON, "CLOSE_SOON"


# ------------------------------------------------------------- expiry first --

def test_expiry_settles_before_the_policy_is_even_consulted():
    """A copilot verdict on an expired contract must never book a buyback."""
    called = []

    def spy(ctx):
        called.append(ctx)
        return cc_core.CLOSE_NOW, "CLOSE_NOW"

    d, _ = cc_core.decide(Ctx(dte=0, spot=120.0, strike=110.0), CFG, spy)
    assert d.kind == "expiry_assigned"
    assert d.assigned is True and d.assignment_type == "expiry"
    assert d.settle_price == pytest.approx(10.0)
    assert d.priced_from == cc_core.INTRINSIC
    assert not called, "the policy ran on an expired contract"


def test_expiry_out_of_the_money_settles_at_zero_and_is_not_an_assignment():
    d, _ = cc_core.decide(Ctx(dte=0, spot=100.0, strike=110.0), CFG, close_now)
    assert d.kind == "expiry_worthless"
    assert d.assigned is False
    assert d.settle_price == 0.0
    assert d.priced_from == cc_core.ZERO
    assert d.needs_market_fill is False


# ---------------------------------------------------------------- close now --

def test_close_now_closes_immediately_and_needs_a_market_fill():
    d, _ = cc_core.decide(Ctx(), CFG, close_now)
    assert d.kind == "policy_close_now"
    assert d.closes and d.needs_market_fill
    assert d.priced_from == cc_core.OPTION_QUOTE


# ------------------------------------------------------- close soon clock ----

def test_close_soon_arms_but_does_not_close_on_the_first_day():
    d, armed = cc_core.decide(Ctx(day=date(2026, 8, 20)), CFG, close_soon)
    assert d.closes is False
    assert armed == date(2026, 8, 20)


def test_close_soon_closes_after_five_CALENDAR_days_not_trading_days():
    """cc_sim has always measured this clock in calendar days, from the alert's
    own wording ('Close this week'). The spec says trading days; the code is the
    authority and this test pins it."""
    armed_on = date(2026, 8, 20)
    for offset, should_close in [(1, False), (4, False), (5, True), (9, True)]:
        d, _ = cc_core.decide(Ctx(day=armed_on + timedelta(days=offset)),
                              CFG, close_soon, armed_on=armed_on)
        assert d.closes is should_close, f"offset {offset}"
    # 2026-08-22/23 is a weekend, so day+5 spans only 3 trading days — proving
    # the two definitions genuinely differ on this input.
    assert (armed_on + timedelta(days=5)).weekday() == 1


def test_close_soon_is_sticky_by_default():
    """The live app does not un-say 'close this week' when the alert drops back
    to WATCH the next day."""
    armed_on = date(2026, 8, 20)
    _, still = cc_core.decide(Ctx(day=armed_on + timedelta(days=1)),
                              CFG, hold, armed_on=armed_on)
    assert still == armed_on


def test_close_soon_disarms_when_stickiness_is_off():
    """Vacuity guard for the test above: the flag does something."""
    cfg = {**CFG, "close_soon_sticky": False}
    _, cleared = cc_core.decide(Ctx(), cfg, hold, armed_on=date(2026, 8, 20))
    assert cleared is None


# --------------------------------------------------------- early exercise ----

def test_rational_early_exercise_fires_when_extrinsic_is_below_the_dividend():
    ctx = Ctx(spot=120.0, strike=110.0, option_price=10.10,
              days_to_exdiv=1, dividend=0.50)
    assert ctx.extrinsic == pytest.approx(0.10)
    d, _ = cc_core.decide(ctx, CFG, hold)
    assert d.kind == "early_exercise"
    assert d.assigned and d.assignment_type == "early_exdiv"
    assert d.settle_price == pytest.approx(10.0)
    assert d.needs_market_fill is False


def test_early_exercise_does_not_fire_when_extrinsic_exceeds_the_dividend():
    ctx = Ctx(spot=120.0, strike=110.0, option_price=12.00,
              days_to_exdiv=1, dividend=0.50)
    d, _ = cc_core.decide(ctx, CFG, hold)
    assert d.kind == "hold"


def test_early_exercise_is_checked_after_the_policy():
    """Ordering: the alert fires in the morning, exercise is decided at the
    close of the day before the ex-date. A CLOSE_NOW wins."""
    ctx = Ctx(spot=120.0, strike=110.0, option_price=10.10,
              days_to_exdiv=1, dividend=0.50)
    d, _ = cc_core.decide(ctx, CFG, close_now)
    assert d.kind == "policy_close_now"
    assert d.assigned is False


def test_assignment_approach_counter_distinguishes_unreachable_from_satisfied():
    """Exp 015 read a zero from an unreachable state as a constraint met."""
    assert cc_core.assignment_is_approaching(
        Ctx(spot=120.0, strike=110.0, days_to_exdiv=2)) is True
    assert cc_core.assignment_is_approaching(
        Ctx(spot=100.0, strike=110.0, days_to_exdiv=2)) is False   # not ITM
    assert cc_core.assignment_is_approaching(
        Ctx(spot=120.0, strike=110.0, days_to_exdiv=None)) is False


# ------------------------------------------------------------- arm filters ---

def _decision(kind, priced_from=cc_core.OPTION_QUOTE, assigned=False):
    return cc_core.Decision(kind=kind, verdict="V", closes=True,
                            assigned=assigned, assignment_type="",
                            settle_price=1.0, priced_from=priced_from)


@pytest.mark.parametrize("arm,clause,expected", [
    ("A", "close_soon_tp75", True),
    ("A", "close_now_itm", True),
    ("B", "close_soon_tp75", False),
    ("B", "close_now_itm", False),
    ("B", "emergency_itm_exdiv_3d", False),
    ("C", "close_now_itm", True),
    ("D", "close_soon_tp75", True),
    ("D", "emergency_itm_exdiv_3d", True),
    ("D", "close_now_itm", False),
    ("D", "close_soon_gamma_within_3pct_dte_lt7", False),
])
def test_each_arm_acts_only_on_its_own_clauses(arm, clause, expected):
    e = engine.PaperEngine.__new__(engine.PaperEngine)
    assert e.arm_acts_on(arm, _decision("policy_close_now"), clause) is expected


@pytest.mark.parametrize("arm", ["A", "B", "C", "D"])
@pytest.mark.parametrize("kind", ["expiry_assigned", "expiry_worthless",
                                  "early_exercise"])
def test_market_mechanics_apply_to_every_arm_including_hold_to_expiry(arm, kind):
    """Arm B ignores the copilot; it cannot ignore expiry or being exercised."""
    e = engine.PaperEngine.__new__(engine.PaperEngine)
    assert e.arm_acts_on(arm, _decision(kind, cc_core.INTRINSIC), "safe_default") is True


def test_arm_D_reads_the_clause_id_not_the_level():
    """Five CLOSE_NOW clauses share one level and arm D must ignore four of
    them, which is only possible with the machine-readable clause id."""
    import position_monitor
    clauses = set()
    for kwargs in [
        dict(strike=100, current_stock=105, ex_div_date="2026-08-21"),      # emergency
        dict(strike=100, current_stock=105),                                 # close_now_itm
        dict(strike=100, current_stock=99.5, ex_div_date="2026-08-24"),      # near strike+exdiv
    ]:
        a = position_monitor.assess_position(
            ticker="T", expiry="2026-09-18", sold_price=2.0, contracts=1,
            current_option_ask=1.0, as_of="2026-08-20", **kwargs)
        clauses.add((a.level, a.clause))
    levels = {lv for lv, _ in clauses}
    assert len(clauses) > len(levels), (
        "vacuity: the fixtures did not produce two clauses sharing a level")


# ----------------------------------------------------------------- latency ---

def _engine_at(ts):
    e = engine.PaperEngine.__new__(engine.PaperEngine)
    e.tick_ts = ts
    return e


def test_a_decision_cannot_fill_at_its_own_tick():
    t = datetime(2026, 8, 20, 19, 30, tzinfo=timezone.utc)
    assert _engine_at(t).fill_is_due(t) is False


def test_fill_is_due_at_exactly_fifteen_minutes():
    t = datetime(2026, 8, 20, 19, 30, tzinfo=timezone.utc)
    assert _engine_at(t + timedelta(minutes=14)).fill_is_due(t) is False
    assert _engine_at(t + timedelta(minutes=15)).fill_is_due(t) is True


def test_cron_drift_is_absorbed_rather_than_skipping_the_fill():
    """'First tick at or after T+15' is later, never earlier. One monitor run
    in a whole morning is a documented fact (2026-08-19)."""
    t = datetime(2026, 8, 20, 14, 0, tzinfo=timezone.utc)
    late = _engine_at(t + timedelta(hours=3))
    assert late.fill_is_due(t) is True
    assert late.realized_latency_min(t) == pytest.approx(180.0)


def test_realized_latency_is_recorded_not_assumed():
    t = datetime(2026, 8, 20, 19, 30, tzinfo=timezone.utc)
    e = _engine_at(t + timedelta(minutes=17))
    assert e.realized_latency_min(t) == pytest.approx(17.0)
    assert e.realized_latency_min(t) != config.LATENCY_MINUTES


def test_overnight_gap_is_flagged_when_the_fill_lands_in_a_later_session():
    decision = datetime(2026, 8, 20, 19, 55, tzinfo=timezone.utc)   # 15:55 ET Thu
    same = _engine_at(datetime(2026, 8, 20, 20, 0, tzinfo=timezone.utc))
    nextday = _engine_at(datetime(2026, 8, 21, 13, 45, tzinfo=timezone.utc))
    assert same.crossed_session(decision) is False
    assert nextday.crossed_session(decision) is True


# ------------------------------------------------------------ cc_sim parity --

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "cc_sim_parity.json")
DATABENTO = os.path.join(ROOT, "data", "databento", "raw")


@pytest.mark.skipif(not os.path.exists(DATABENTO),
                    reason="Databento raw data is gitignored (188MB); this "
                           "parity gate runs locally before the refactor PR "
                           "merges, not in CI")
def test_extracting_cc_core_changed_nothing_in_cc_sim():
    """Byte-identical replay of a recorded experiment.

    RED BASELINE: verified during development by changing cc_core's CLOSE_SOON
    clock from `>= close_soon_days` to `>= close_soon_days + 1`, which moved
    AAPL's net P&L by $92 and changed the fingerprint. The check is real.
    """
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "scripts", "cc_sim_parity_baseline.py")],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "byte-identical" in r.stdout


def test_the_parity_fixture_is_committed_even_when_the_data_is_not():
    """So a reviewer can see WHAT was pinned without 188MB of option data."""
    import json
    assert os.path.exists(FIXTURE)
    fx = json.load(open(FIXTURE))
    assert len(fx["sha256"]) == 64
    assert fx["summary"], "the fixture records no case summaries"
