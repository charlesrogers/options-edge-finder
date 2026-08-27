"""Regression tests for the 2026-08-21 correctness-review findings.

Every test here asserts the bug's premise first where the premise is cheap to
state (tasks/lessons.md 2026-08-18: a regression test that cannot reproduce
its bug passes vacuously), then asserts the fix.
"""
import json
from datetime import datetime, timezone

import pytest

import cc_core
from paper_engine import config, engine, killswitch, quotes, store


def utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


# 2026-09-18 is a Friday and a standard monthly expiry.
# 14:00 ET == 18:00 UTC (EDT); 15:45 ET == 19:45 UTC.
EXPIRY = "2026-09-18"
MIDDAY = utc(2026, 9, 18, 18, 0)
FINAL_TICK = utc(2026, 9, 18, 19, 45)


class Store:
    """Capture-only store double. No network, every write recorded."""

    def __init__(self, select_result=None):
        self.updates = []
        self.inserts = []
        self.events = []
        self.select_result = select_result or []

    def install(self, monkeypatch):
        monkeypatch.setattr(store, "update",
                            lambda table, patch, **f: self.updates.append(
                                (table, patch, f)) or [patch])
        monkeypatch.setattr(store, "insert",
                            lambda table, row, verify=True: self.inserts.append(
                                (table, row)) or dict(row, id="new"))
        monkeypatch.setattr(store, "insert_event",
                            lambda row: self.events.append(row) or "inserted")
        monkeypatch.setattr(store, "select_rows",
                            lambda table, q="": list(self.select_result))
        return self


def fresh_quote(**kw):
    q = quotes.Quote(contract_symbol="T260918C00110000", ticker="T",
                     tick_ts=kw.pop("tick_ts", MIDDAY))
    defaults = dict(bid=1.0, ask=1.2, last=1.1, volume=10, open_interest=100,
                    implied_volatility=0.3, spot=100.0, source_status=quotes.OK,
                    stale=False)
    defaults.update(kw)
    for k, v in defaults.items():
        setattr(q, k, v)
    return q


def trade_row(arm, **kw):
    row = {
        "id": "t1", "arm": arm, "ticker": "T", "cycle_seq": 1,
        "status": "open", "contract_symbol": "T260918C00110000",
        "strike": 110.0, "expiry": EXPIRY, "contracts": 7,
        "premium_per_share": 2.0, "entry_commission": 4.55,
        "entry_spread": 0.2, "close_soon_armed_on": None,
        "entry_decision_ts": "2026-09-01T19:45:00+00:00",
    }
    row.update(kw)
    return row


# ---------------------------------------------- F3: arm B early exercise ----

def test_arm_b_reaches_the_early_exercise_branch(monkeypatch):
    """Bug premise: cc_core.decide returns at the CLOSE_NOW step before its
    early-exercise branch, so an arm that ignores the copilot never reached the
    mechanics and arm B could never be assigned early — biasing H41 against
    the copilot. The fix re-decides under a HOLD policy for such arms."""
    ctx_state = dict(spot=120.0, strike=110.0)  # deep ITM, day before ex-div

    # Premise: for this state the copilot says CLOSE_NOW, and decide() returns
    # the policy decision without ever reaching early exercise.
    class C:
        ticker = "T"; date = MIDDAY.date(); spot = 120.0; strike = 110.0
        option_price = 10.05; sold_price = 2.0; dte = 10
        days_to_exdiv = 1; dividend = 0.75; expiration = EXPIRY
        price_is_stale = False
        pct_from_strike = (110.0 - 120.0) / 120.0 * 100
        is_itm = True; intrinsic = 10.0; extrinsic = 0.05

    d, _ = cc_core.decide(C(), config.POLICY_CFG,
                          lambda c: (cc_core.CLOSE_NOW, "CLOSE_NOW"))
    assert d.kind == "policy_close_now" and not d.assigned  # the premise

    # Fix: the engine settles arm B (exits='none') via the mechanics.
    st = Store().install(monkeypatch)
    eng = engine.PaperEngine(tick_ts=MIDDAY, universe=["T"])
    q = fresh_quote(spot=120.0, ask=10.1, bid=10.0)
    # Expiry weeks away: on expiry day itself the expiry branch would fire
    # first and mask the early-exercise path this test pins.
    eng.tick_position(trade_row("B", expiry="2026-10-16"), q,
                      ex_div="2026-09-19", earnings=None, dividend=0.75)
    closed = [u for u in st.updates if u[1].get("status") == "closed"]
    assert closed, "arm B never settled — early exercise still unreachable"
    assert closed[0][1]["assignment_type"] == "early_exdiv"
    assert eng.tally.modeled_assignments == 1


def test_dividend_amount_comes_from_the_committed_file():
    """Bug premise: the old implementation read a 'Dividends' column that
    yf_proxy.get_stock_history never returns (the worker requests no dividend
    events), so the dividend was ALWAYS None and the early-exercise branch was
    structurally unreachable."""
    import yf_proxy
    import pandas as pd
    # Premise, asserted against the real fetcher's contract: the column list
    # yf_proxy builds from the worker response has no 'Dividends'.
    import inspect
    src = inspect.getsource(yf_proxy.get_stock_history)
    assert "Dividends" not in src

    eng = engine.PaperEngine(tick_ts=MIDDAY, universe=["AAPL"])
    amt = eng.dividend_amount("AAPL")
    assert cc_core.is_usable_number(amt), "committed dividends.json unusable"
    with open(engine._DIVIDENDS_PATH) as f:
        committed = json.load(f)["tickers"]["AAPL"]["amount"]
    assert amt == committed


# ------------------------------------------------- F6: expiry settlement ----

def test_expiry_settlement_waits_for_the_final_tick(monkeypatch):
    """Bug premise: cc_core fires the expiry branch from the FIRST tick of
    expiry day (dte == 0), which would settle at a morning spot hours before
    expiry. The engine defers to the day's final tick."""
    C = trade_row("B")
    st = Store().install(monkeypatch)
    eng = engine.PaperEngine(tick_ts=MIDDAY, universe=["T"])
    q = fresh_quote(spot=120.0)
    eng.tick_position(C, q, ex_div=None, earnings=None, dividend=None)
    assert not [u for u in st.updates if u[1].get("status") == "closed"], \
        "settled at midday — should wait for the final tick"

    st2 = Store().install(monkeypatch)
    eng2 = engine.PaperEngine(tick_ts=FINAL_TICK, universe=["T"])
    q2 = fresh_quote(tick_ts=FINAL_TICK, spot=120.0)
    eng2.tick_position(C, q2, ex_div=None, earnings=None, dividend=None)
    closed = [u for u in st2.updates if u[1].get("status") == "closed"]
    assert closed and closed[0][1]["assignment_type"] == "expiry"
    assert closed[0][1]["real_fill"] is True


def test_settlement_defers_on_a_stale_spot(monkeypatch):
    """A carried-forward Friday spot must not price a settlement and must not
    land in the real-fill subset."""
    st = Store().install(monkeypatch)
    eng = engine.PaperEngine(tick_ts=FINAL_TICK, universe=["T"])
    q = fresh_quote(tick_ts=FINAL_TICK, spot=120.0, stale=True)
    eng.tick_position(trade_row("B"), q, ex_div=None, earnings=None,
                      dividend=None)
    assert not [u for u in st.updates if u[1].get("status") == "closed"], \
        "settled off a carried-forward spot"


# --------------------------------------------------- F4: kill enforcement ----

def test_entry_halts_maps_triggered_switches_to_stopped_entries():
    """Bug premise: kills were evaluated AFTER entries and consulted never, so
    a TRIGGERED switch stopped nothing."""
    ev = {"switches": [
        {"kind": killswitch.INTEGRITY, "state": killswitch.TRIGGERED,
         "name": "quote_coverage_5_sessions", "scope": None},
        {"kind": killswitch.STRATEGY, "state": killswitch.TRIGGERED,
         "name": "drawdown", "scope": "KKR"},
        {"kind": killswitch.STRATEGY, "state": killswitch.ARMED,
         "name": "drawdown", "scope": "AAPL"},
    ]}
    pause_all, per_ticker, global_arms = killswitch.entry_halts(ev)
    assert pause_all is True
    assert per_ticker == {"KKR": {"A"}}
    assert global_arms == set()

    ev2 = {"switches": [
        {"kind": killswitch.STRATEGY, "state": killswitch.TRIGGERED,
         "name": "emergency_cluster_30d", "scope": None}]}
    pause_all2, per2, global2 = killswitch.entry_halts(ev2)
    assert pause_all2 is False and global2 == {"A"} and per2 == {}


# ------------------------------------------------------- F7: stuck fills ----

def test_unfillable_entry_is_a_day_order(monkeypatch):
    st = Store().install(monkeypatch)
    eng = engine.PaperEngine(tick_ts=utc(2026, 9, 2, 18, 0), universe=["T"])
    t = trade_row("A", status="pending_entry",
                  entry_decision_ts="2026-09-01T19:45:00+00:00")
    q = fresh_quote(tick_ts=eng.tick_ts, bid=None)          # still no bid
    assert eng.execute_entry_fill(t, q) is False
    cancelled = [u for u in st.updates if u[1].get("status") == "cancelled"]
    assert cancelled, "entry order survived past its decision session"
    assert eng.tally.entries_cancelled == 1


def test_exit_falls_back_to_last_recorded_ask_after_a_session(monkeypatch):
    st = Store(select_result=[{"ask": 1.4, "ask_usable": True,
                               "tick_ts": "2026-09-01T19:45:00+00:00"}])
    st.install(monkeypatch)
    eng = engine.PaperEngine(tick_ts=utc(2026, 9, 2, 18, 0), universe=["T"])
    t = trade_row("A", status="pending_exit",
                  exit_decision_ts="2026-09-01T18:00:00+00:00",
                  exit_priced_from=cc_core.OPTION_QUOTE, exit_clause="x",
                  expiry="2026-10-16")                       # far from expiry
    q = fresh_quote(tick_ts=eng.tick_ts, ask=None)           # ask never returns
    assert eng.execute_exit_fill(t, q) is True
    closed = [u for u in st.updates if u[1].get("status") == "closed"][0][1]
    assert closed["exit_fill_price"] == 1.4
    assert closed["real_fill"] is False, "a fallback fill must never be 'real'"
    assert closed["exit_quote_stale"] is True
    assert eng.tally.stale_fallback_exits == 1


def test_pending_exit_past_expiry_settles_instead_of_waiting(monkeypatch):
    st = Store().install(monkeypatch)
    eng = engine.PaperEngine(tick_ts=utc(2026, 9, 21, 18, 0),  # Monday after
                             universe=["T"])
    t = trade_row("A", status="pending_exit",
                  exit_decision_ts="2026-09-18T18:00:00+00:00",
                  exit_priced_from=cc_core.OPTION_QUOTE, exit_clause="x")
    q = fresh_quote(tick_ts=eng.tick_ts, ask=None, spot=105.0)
    assert eng.execute_exit_fill(t, q) is True
    closed = [u for u in st.updates if u[1].get("status") == "closed"][0][1]
    assert closed["exit_kind"] == "expiry_worthless"


# -------------------------------------------------- F8: event dedup keys ----

def test_kill_state_changes_at_one_tick_do_not_collide(monkeypatch):
    """Bug premise: dedup_key was (kind, arm, ticker, cycle, tick), so every
    scope-None switch transitioning at the same tick collided and all but the
    first were dropped — making the dropped ones re-announce every tick."""
    st = Store().install(monkeypatch)
    eng = engine.PaperEngine(tick_ts=MIDDAY, universe=["T"])
    eng.event("kill_state_change", payload={"key": "a"})
    eng.event("kill_state_change", payload={"key": "b"})
    k1, k2 = st.events[0]["dedup_key"], st.events[1]["dedup_key"]
    assert k1 == k2, "premise gone: keys already differ without dedup_extra"

    st.events.clear()
    eng.event("kill_state_change", payload={"key": "a"}, dedup_extra="int:a:-")
    eng.event("kill_state_change", payload={"key": "b"}, dedup_extra="int:b:-")
    assert st.events[0]["dedup_key"] != st.events[1]["dedup_key"]


# ------------------------------------- F11: string dates from the proxy -----

def test_stock_dates_accepts_the_live_workers_string_dates(monkeypatch):
    """Bug premise: the deployed worker returns exDividendDate as an ISO STRING
    and earningsDate as a list of strings (probed 2026-08-21); the old
    isinstance(int, float) guard parsed both to None — EMERGENCY and every
    ex-div/earnings clause silently unreachable, in the paper engine AND the
    live monitor."""
    assert isinstance("2026-08-10", (int, float)) is False  # the old guard

    import yf_proxy
    monkeypatch.setattr(yf_proxy, "get_stock_info", lambda t: {
        "exDividendDate": "2026-11-10",
        "earningsDate": ["2026-10-29"],
        "dividendYield": 0.0035,
    })
    eng = engine.PaperEngine(tick_ts=MIDDAY, universe=["T"])
    ex_div, earnings, div_yield = eng.stock_dates("T")
    assert ex_div == "2026-11-10"
    assert earnings == "2026-10-29"
    assert div_yield == 0.0035


def test_past_dates_from_yahoo_never_become_days_to_exdiv_zero(monkeypatch):
    """Second-order bug in the string-date fix itself: Yahoo serves the MOST
    RECENT (usually past) ex-date, and position_monitor clamps with
    max(0, ...) — so a past date becomes days_to_exdiv=0 and an ITM covered
    call on any payer fires a false EMERGENCY every 15 minutes. Past event
    dates must parse to None."""
    assert max(0, -11) == 0                        # the clamp — the premise

    # Engine side: a past ex-div (AAPL's actual '2026-08-10' read later) is
    # dropped at parse time.
    import yf_proxy
    monkeypatch.setattr(yf_proxy, "get_stock_info", lambda t: {
        "exDividendDate": "2026-08-10",            # past relative to MIDDAY
        "earningsDate": ["2026-07-29"],            # past too
        "dividendYield": 0.0035,
    })
    eng = engine.PaperEngine(tick_ts=MIDDAY, universe=["T"])
    ex_div, earnings, _ = eng.stock_dates("T")
    assert ex_div is None
    assert earnings is None

    # And with a None ex-div, an ITM position cannot fire the ex-div EMERGENCY.
    from position_monitor import assess_position
    alert = assess_position(ticker="T", strike=110.0, expiry="2026-10-16",
                            sold_price=2.0, contracts=7, current_stock=120.0,
                            current_option_ask=10.1, ex_div_date=None,
                            as_of=MIDDAY.date().isoformat())
    assert alert.level != "EMERGENCY"


def test_monitor_positions_uses_the_shared_date_parser():
    """The live monitor had the identical dead guard on the $400K path. Pin the
    fix at source level so a revert is loud."""
    import inspect
    import monitor_positions
    src = inspect.getsource(monitor_positions)
    assert "upcoming_market_date(" in src
    assert 'isinstance(ex_div_ts, (int, float))' not in src


@pytest.mark.parametrize("value,expected", [
    ("2026-08-10", "2026-08-10"),
    (1786492800, "2026-08-12"),
    (float("nan"), None), ("", None), (None, None), (True, None),
    ("not-a-date", None), (-5, None),
])
def test_parse_market_date(value, expected):
    assert cc_core.parse_market_date(value) == expected


# ------------------------------------------------- F9: ATM IV for the gate --

def test_chain_fetch_extracts_atm_iv_not_the_otm_contracts_iv(monkeypatch):
    import pandas as pd

    def fake_get(path, params=None):
        if path.endswith("/options"):
            return {"expirations": ["2026-09-18"]}
        return {"underlyingPrice": 100.0, "calls": [
            {"contractSymbol": "T_ATM", "strike": 100.0, "bid": 3.0,
             "ask": 3.2, "lastPrice": 3.1, "volume": 50, "openInterest": 500,
             "impliedVolatility": 0.25},
            {"contractSymbol": "T_OTM", "strike": 115.0, "bid": 0.5,
             "ask": 0.7, "lastPrice": 0.6, "volume": 5, "openInterest": 50,
             "impliedVolatility": 0.40},
        ]}

    import yf_proxy
    monkeypatch.setattr(yf_proxy, "_get", fake_get)
    fetch = quotes.fetch_chain("T", utc(2026, 8, 21, 18, 0), 0.15, 20, 45)
    assert fetch.ok
    selected = list(fetch.quotes.values())[0]
    assert selected.contract_symbol == "T_OTM"          # sells the OTM strike
    assert selected.implied_volatility == 0.40
    assert fetch.atm_iv == 0.25, "gate must rank the ATM IV, not the OTM skew"


def test_past_expiry_settlement_never_books_worthless_without_a_spot(monkeypatch):
    """With NO spot at all, ITM cannot be told from OTM — settling worthless
    would book the full premium as kept on what might be a deep-ITM
    assignment. The cleanup path must defer instead."""
    st = Store().install(monkeypatch)
    eng = engine.PaperEngine(tick_ts=utc(2026, 9, 21, 18, 0), universe=["T"])
    t = trade_row("A", status="pending_exit",
                  exit_decision_ts="2026-09-18T18:00:00+00:00",
                  exit_priced_from=cc_core.OPTION_QUOTE, exit_clause="x")
    q = fresh_quote(tick_ts=eng.tick_ts, ask=None, spot=None)
    assert eng.execute_exit_fill(t, q) is False
    assert not st.updates, "settled with no spot knowledge at all"


def test_past_expiry_settlement_off_a_stale_spot_is_never_a_real_fill(monkeypatch):
    st = Store().install(monkeypatch)
    eng = engine.PaperEngine(tick_ts=utc(2026, 9, 21, 18, 0), universe=["T"])
    t = trade_row("A", status="pending_exit",
                  exit_decision_ts="2026-09-18T18:00:00+00:00",
                  exit_priced_from=cc_core.OPTION_QUOTE, exit_clause="x")
    q = fresh_quote(tick_ts=eng.tick_ts, ask=None, spot=120.0, stale=True)
    assert eng.execute_exit_fill(t, q) is True
    closed = [u for u in st.updates if u[1].get("status") == "closed"][0][1]
    assert closed["exit_kind"] == "expiry_assigned"
    assert closed["real_fill"] is False


def test_missing_quote_cannot_fabricate_an_early_exercise(monkeypatch):
    """With no usable option quote, _Ctx falls back to option_price=0.0 and
    extrinsic < dividend is unconditionally true — a data gap booked as a
    modeled assignment in the control arm. The decision must defer."""
    st = Store().install(monkeypatch)
    eng = engine.PaperEngine(tick_ts=MIDDAY, universe=["T"])
    q = fresh_quote(spot=120.0, bid=None, ask=None)   # contract went quoteless
    eng.tick_position(trade_row("B", expiry="2026-10-16"), q,
                      ex_div="2026-09-19", earnings=None, dividend=0.75)
    assert not [u for u in st.updates if u[1].get("status") == "closed"], \
        "booked an assignment off a fabricated 0.0 option price"
    assert eng.tally.modeled_assignments == 0


def test_late_settlement_is_never_a_real_fill(monkeypatch):
    """A settlement booked after expiry day prices off a LATER session's spot;
    a weekend gap can fabricate an assignment. Fresh Monday spot or not, a
    late settlement stays out of the real-fill subset."""
    st = Store().install(monkeypatch)
    eng = engine.PaperEngine(tick_ts=utc(2026, 9, 21, 18, 0), universe=["T"])
    t = trade_row("A", status="pending_exit",
                  exit_decision_ts="2026-09-18T18:00:00+00:00",
                  exit_priced_from=cc_core.OPTION_QUOTE, exit_clause="x")
    q = fresh_quote(tick_ts=eng.tick_ts, ask=None, spot=113.0, stale=False)
    assert eng.execute_exit_fill(t, q) is True
    closed = [u for u in st.updates if u[1].get("status") == "closed"][0][1]
    assert closed["exit_kind"] == "expiry_assigned"
    assert closed["real_fill"] is False


def test_warn_only_switches_do_not_pause_entries():
    """The stale-quotes switch says 'this warns, it does not halt' — and it
    was halting every ticker's entries for the day on one proxy blip."""
    ev = {"switches": [
        {"kind": killswitch.INTEGRITY, "state": killswitch.TRIGGERED,
         "name": "stale_quotes_this_run", "scope": None, "halts": False},
    ]}
    pause_all, per_ticker, global_arms = killswitch.entry_halts(ev)
    assert pause_all is False

    ev["switches"].append(
        {"kind": killswitch.INTEGRITY, "state": killswitch.TRIGGERED,
         "name": "quote_coverage_5_sessions", "scope": None, "halts": True})
    pause_all2, _, _ = killswitch.entry_halts(ev)
    assert pause_all2 is True


def test_a_stale_entry_fill_never_grades_as_a_real_fill(monkeypatch):
    """Stricter than cc_sim's exit-only definition, disclosed in the
    pre-registration: a cycle whose ENTRY filled on a carried-forward quote is
    excluded from the real-fill subset even when its exit quote was real."""
    st = Store().install(monkeypatch)
    eng = engine.PaperEngine(tick_ts=utc(2026, 9, 10, 18, 0), universe=["T"])
    t = trade_row("A", status="pending_exit", entry_quote_stale=True,
                  exit_decision_ts="2026-09-10T17:30:00+00:00",
                  exit_priced_from=cc_core.OPTION_QUOTE, exit_clause="x",
                  expiry="2026-10-16")
    q = fresh_quote(tick_ts=eng.tick_ts, ask=1.3, stale=False)
    assert eng.execute_exit_fill(t, q) is True
    closed = [u for u in st.updates if u[1].get("status") == "closed"][0][1]
    assert closed["real_fill"] is False


def test_query_timestamps_are_url_safe(monkeypatch):
    """isoformat()'s '+00:00' URL-decodes to a space inside a PostgREST query
    and 400s the filter — this killed the first live tick at the
    EMERGENCY-cluster kill query."""
    ts = utc(2026, 8, 27, 18, 52)
    assert "+" in ts.isoformat()                       # the premise
    assert store.ts_param(ts) == "2026-08-27T18:52:00Z"

    # And the one query that embeds a full timestamp actually uses it.
    captured = []
    monkeypatch.setattr(store, "select_rows",
                        lambda table, q="": captured.append(q) or [])
    killswitch.strategy_switches(ts)
    ts_queries = [q for q in captured if "event_ts=gte." in q]
    assert ts_queries, "the EMERGENCY-cluster query no longer runs?"
    assert all("+" not in q for q in ts_queries), \
        "a '+' in a query string reaches PostgREST as a space"
