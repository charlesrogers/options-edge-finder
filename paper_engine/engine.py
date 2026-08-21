"""The run loop. Stateless: reads its whole world from Supabase, acts, writes.

One invocation = one 15-minute tick. Order within a tick is load-bearing:

  1. startup gate            — never trade against criteria that have moved
  2. calendar check          — closed market: heartbeat and leave
  3. load state              — open positions, pending fills, armed CLOSE_SOONs
  4. capture quotes          — at THIS tick, for every contract in play
  5. execute pending fills   — decisions from >= 15 minutes ago fill now
  6. tick open positions     — new decisions become pending fills
  7. entry evaluation        — once per ticker per day, near 15:30 ET
  8. kill switches           — evaluate, alert on transition only
  9. heartbeat               — always, including on failure

Fills execute BEFORE new decisions so that a decision made at T can never fill
at T. That is the human-latency rule expressed as control flow rather than as a
comparison someone could forget.

Idempotency comes from the database, not from the code remembering: unique keys
on (ticker, trading_day), (contract_symbol, tick_ts), (arm, ticker, cycle_seq)
and events.dedup_key mean a re-run, a missed tick, or a crash between deciding
and filling all converge to the same state. GitHub Actions cron drift is a
documented fact here — one monitor run in a whole morning, 2026-08-19 — and the
"first tick at or after T+15" rule absorbs it by construction.
"""
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone

import cc_core
import market_calendar
import ticker_strategies
import yf_proxy
from position_monitor import assess_position

from . import accounting, config, killswitch, preflight, quotes, store

OPEN_STATUSES = ("pending_entry", "open", "pending_exit")

_DIVIDENDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "dividends.json")
_dividends_cache = None


def _dividends_file():
    global _dividends_cache
    if _dividends_cache is None:
        import json
        with open(_DIVIDENDS_PATH) as f:
            _dividends_cache = json.load(f)
    return _dividends_cache


class Tally:
    """Everything this run needs to be able to say about its own data quality.

    Counted, never inferred. A run that cannot say how many quotes it failed to
    get is a run whose numbers cannot be graded.
    """

    def __init__(self):
        self.quotes_expected = 0
        self.quotes_usable = 0
        self.quotes_stale = 0
        self.proxy_failures = 0
        self.empty_chains = 0
        self.contract_missing = 0
        # The premium-captured trap: assess_position defaults
        # premium_captured_pct to 0 when the ask is None, which silently
        # disables TP-75 and TP-50 and holds a position longer than the
        # strategy intends. This is the forward-time twin of the DTE bug, so it
        # gets a counter and a red threshold on the health page.
        self.assessed_without_ask = 0
        self.positions_unassessed = 0
        self.dividend_unknown = 0
        self.dividend_stale = 0
        self.entries_cancelled = 0
        self.stale_fallback_exits = 0
        self.entry_evals = 0
        self.entries_opened = 0
        self.fills_executed = 0
        self.exits_decided = 0
        self.assignment_approaches = 0
        self.modeled_assignments = 0
        self.clause_fires = {}

    def clause(self, name):
        self.clause_fires[name] = self.clause_fires.get(name, 0) + 1

    def as_dict(self):
        d = {k: v for k, v in self.__dict__.items()}
        d["quote_coverage_pct"] = (
            round(self.quotes_usable / self.quotes_expected * 100, 1)
            if self.quotes_expected else None)
        return d


class PaperEngine:
    def __init__(self, tick_ts=None, universe=None):
        self.tick_ts = (tick_ts or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self.universe = universe or config.universe()
        self.tally = Tally()
        self.writes = store.ConfirmedCounter()
        self.alerts = []
        self.notes = []

    # ------------------------------------------------------------ calendar --
    @property
    def et_day(self):
        return market_calendar.et_date(self.tick_ts)

    def market_is_open(self):
        return market_calendar.is_market_open(self.tick_ts)

    def is_entry_eval_tick(self):
        """The first tick of the day at or after 15:30 ET.

        Computed from the ET calendar, never from a fixed UTC hour: GitHub cron
        schedules do not observe DST and a fixed-UTC entry time drifts an hour
        twice a year (docs/crons.md). "At or after" rather than "equal to" is
        what makes a drifted or skipped 15:30 run still produce the day's
        evaluation at 15:45 — and the unique (ticker, trading_day) key is what
        stops it producing two.
        """
        et = self.tick_ts.astimezone(market_calendar.ET)
        return et.hour * 60 + et.minute >= config.ENTRY_EVAL_ET_MINUTES

    # --------------------------------------------------------------- state --
    def load_trades(self):
        status_filter = ",".join(OPEN_STATUSES)
        return store.select_rows(
            config.TABLES["trades"],
            f"status=in.({status_filter})&order=ticker,arm,cycle_seq")

    def already_evaluated_today(self):
        rows = store.select_rows(
            config.TABLES["entry_evals"],
            f"trading_day=eq.{self.et_day}&select=ticker")
        return {r["ticker"] for r in rows}

    def next_cycle_seq(self, arm, ticker):
        rows = store.select_rows(
            config.TABLES["trades"],
            f"arm=eq.{arm}&ticker=eq.{ticker}&select=cycle_seq"
            f"&order=cycle_seq.desc&limit=1")
        return (rows[0]["cycle_seq"] + 1) if rows else 1

    def last_quote(self, contract_symbol):
        rows = store.select_rows(
            config.TABLES["quotes"],
            f"contract_symbol=eq.{contract_symbol}&order=tick_ts.desc&limit=1")
        if not rows:
            return None
        r = rows[0]
        q = quotes.Quote(
            contract_symbol=contract_symbol, ticker=r["ticker"],
            tick_ts=datetime.fromisoformat(r["tick_ts"].replace("Z", "+00:00")),
            bid=r["bid"], ask=r["ask"], last=r["last"], volume=r["volume"],
            open_interest=r["open_interest"],
            implied_volatility=r["implied_volatility"], spot=r["spot"],
            source_status=r["source_status"], stale=r["stale"])
        if r.get("stale_from_tick_ts"):
            q.stale_from_tick_ts = datetime.fromisoformat(
                r["stale_from_tick_ts"].replace("Z", "+00:00"))
        return q

    # -------------------------------------------------------------- quotes --
    def capture_quote(self, ticker, contract_symbol, expiry):
        """Fetch this contract's market now; carry forward and mark if we can't."""
        self.tally.quotes_expected += 1
        q = quotes.quote_for_contract(ticker, contract_symbol, expiry, self.tick_ts)
        if q.source_status == quotes.PROXY_FAILED:
            self.tally.proxy_failures += 1
        elif q.source_status == quotes.EMPTY_CHAIN:
            self.tally.empty_chains += 1
        elif q.source_status == quotes.CONTRACT_MISSING:
            self.tally.contract_missing += 1

        if not (q.bid_usable or q.ask_usable):
            previous = self.last_quote(contract_symbol)
            if previous is not None and (previous.bid_usable or previous.ask_usable):
                q = quotes.carry_forward(previous, self.tick_ts)
                self.tally.quotes_stale += 1
            # else: genuinely nothing to carry. The position is unassessable
            # this tick, which is a fact, not a zero.
        else:
            self.tally.quotes_usable += 1

        self.writes.record(store.upsert, config.TABLES["quotes"],
                           q.as_row(self.et_day), "contract_symbol,tick_ts")
        return q

    def stock_dates(self, ticker):
        """Ex-dividend and earnings dates. A FAILED LOOKUP IS NOT 'NO DIVIDEND'.

        Same contract as the live monitor: only a successful lookup that simply
        has no exDividendDate (a non-payer) yields a legitimate None. Anything
        else raises and the position goes unassessed for this tick.
        """
        info = yf_proxy.get_stock_info(ticker)
        if not info:
            raise RuntimeError(f"{ticker}: stock info lookup returned nothing — "
                               f"cannot rule out an imminent ex-dividend")
        # The deployed worker serves exDividendDate as an ISO STRING and
        # earningsDate as a list of strings (probed live 2026-08-21). The old
        # isinstance(int, float) guard parsed both to None on every lookup —
        # the DTE-bug shape, on the ex-div path. parse_market_date accepts
        # epoch, ISO string, and date, and validates all three.
        ex_div = cc_core.parse_market_date(info.get("exDividendDate"))
        ets = info.get("earningsDate")
        if isinstance(ets, (list, tuple)):
            ets = ets[0] if ets else None
        earnings = cc_core.parse_market_date(ets)
        # A NaN dividend yield sails through a None-guard, so it is validated
        # rather than truth-tested (tasks/lessons.md 2026-08-16).
        raw_yield = info.get("dividendYield")
        div_yield = raw_yield if cc_core.is_usable_number(raw_yield) else None
        return ex_div, earnings, div_yield

    def dividend_amount(self, ticker):
        """The most recent ACTUAL dividend, never spot x dividendYield.

        Read from the committed paper_engine/dividends.json, derived by
        experiments/024_paper_engine/derive_dividends.py from real paid
        dividends. There is no trustworthy LIVE source at run time: the
        worker's /history endpoint requests no dividend events and its /info
        drops dividendRate — the review found the previous implementation
        reading a 'Dividends' column yf_proxy never returns, which made the
        rational-early-exercise branch structurally unreachable and biased the
        H41 (A-B) readout for the whole study.

        Staleness is loud, not silent: past twice the ticker's own measured
        payment interval, the amount is still used (it moves cents per
        quarter) but the run notes it and counts it, so the health page shows
        the file needs regenerating.
        """
        divs = _dividends_file()
        entry = (divs.get("tickers") or {}).get(ticker)
        if not entry:
            self.tally.dividend_unknown += 1
            self.note(f"{ticker}: no entry in dividends.json — early-exercise "
                      f"model cannot price the dividend")
            return None
        amt = entry.get("amount")
        if not cc_core.is_usable_number(amt):
            return None                       # non-payer: a legitimate None
        last_paid = cc_core.parse_market_date(entry.get("last_paid"))
        interval = entry.get("interval_days")
        if last_paid and cc_core.is_usable_number(interval):
            age = (self.tick_ts.date() - datetime.strptime(
                last_paid, "%Y-%m-%d").date()).days
            if age > 2 * float(interval):
                self.tally.dividend_stale += 1
                self.note(f"{ticker}: dividends.json is {age}d past the last "
                          f"payment (interval {interval}d) — regenerate it")
        return float(amt)

    def is_settlement_tick(self, expiry_str):
        """Expiry settlement books at the LAST tick of expiry day, or later.

        cc_core's expiry branch fires from the first tick of expiry day
        (dte == 0), but settling at 09:45 prices the settlement off a morning
        spot hours before the contract expires — and a Friday-morning decision
        filled Monday would price off the weekend gap instead. The simulator
        settles at expiry-day close; the engine matches it: parity, not
        preference.
        """
        exp = str(expiry_str)[:10]
        if self.et_day > exp:
            return True
        if self.et_day < exp:
            return False
        et = self.tick_ts.astimezone(market_calendar.ET)
        final_tick = (market_calendar.close_minutes_et(self.et_day)
                      - config.TICK_GRID_MINUTES)
        return et.hour * 60 + et.minute >= final_tick

    def settle_position(self, trade, quote, decision, ctx, alert):
        """Book an expiry/assignment settlement — mechanical, so it books at
        the DECISION tick with the decision spot. The +15-minute latency rule
        models Dad reacting to an alert; expiry does not wait for Dad.

        A settlement's price is the spot, so it is only 'real' if the spot is
        fresh. A carried-forward Friday spot pricing a Monday settlement was
        exactly the kind of stale number the real-fill subset exists to
        exclude — deferring on a stale spot keeps it out.
        """
        intrinsic_priced = decision.priced_from == cc_core.INTRINSIC
        spot_fresh = quote.spot_usable and not quote.stale
        if intrinsic_priced and not spot_fresh:
            self.note(f"{trade['arm']}/{trade['ticker']} settlement deferred: "
                      f"no fresh spot at {self.tick_ts.isoformat()}")
            return False
        price = (max(0.0, quote.spot - float(trade["strike"]))
                 if intrinsic_priced else 0.0)
        premium = float(trade["premium_per_share"])
        contracts = trade["contracts"]
        pnl = accounting.cycle_pnl(
            premium_per_share=premium, buyback_per_share=price,
            contracts=contracts,
            entry_commission=float(trade.get("entry_commission") or 0),
            exit_commission=0.0)
        patch = {
            "status": "closed",
            "exit_decision_ts": self.tick_ts.isoformat(),
            "exit_decision_spot": quote.spot,
            "exit_fill_ts": self.tick_ts.isoformat(),
            "exit_fill_spot": quote.spot,
            "exit_fill_price": price,
            "exit_latency_min": 0.0,
            "exit_overnight_gap": False,
            "exit_quote_stale": quote.stale,
            "exit_commission": 0.0,
            "exit_kind": decision.kind,
            "exit_clause": alert.clause if alert else None,
            "exit_verdict": decision.verdict,
            "exit_priced_from": decision.priced_from,
            "spread_cost_total": accounting.spread_cost_usd(
                trade.get("entry_spread"), None, contracts),
            "real_fill": spot_fresh if intrinsic_priced else True,
            "assigned": decision.assigned,
            "assignment_type": decision.assignment_type,
            "assignment_modeled": True,
            "assignment_inputs": store.json_safe({
                "spot": quote.spot, "strike": float(trade["strike"]),
                "dividend": getattr(ctx, "dividend", None) if ctx else None,
                "days_to_exdiv": getattr(ctx, "days_to_exdiv", None) if ctx else None,
                "extrinsic": getattr(ctx, "extrinsic", None) if ctx else None,
                "spot_fresh": spot_fresh}),
            "closed_at": self.tick_ts.isoformat(),
            **pnl,
        }
        self.writes.record(store.update, config.TABLES["trades"], patch,
                           id=trade["id"])
        if decision.assigned:
            self.tally.modeled_assignments += 1
            self.event("modeled_assignment", trade["arm"], trade["ticker"],
                       trade["cycle_seq"], severity="critical",
                       payload={"assignment_type": decision.assignment_type,
                                "spot": quote.spot,
                                "strike": float(trade["strike"]),
                                "modeled": True,
                                "note": ("A paper position cannot be assigned. "
                                         "This is a MODEL of assignment, from "
                                         "cc_core's mechanics.")})
            self.alerts.append(
                f"MODELED ASSIGNMENT {trade['arm']}/{trade['ticker']} "
                f"({decision.assignment_type}): spot {quote.spot} vs strike "
                f"{trade['strike']}")
        self.event("exit_filled", trade["arm"], trade["ticker"],
                   trade["cycle_seq"],
                   payload={"fill_price": price,
                            "priced_from": decision.priced_from,
                            "kind": decision.kind,
                            "net_pnl": pnl["net_pnl"],
                            "real_fill": patch["real_fill"]})
        self.tally.fills_executed += 1
        return True

    # --------------------------------------------------------------- fills --
    def fill_is_due(self, decision_ts):
        """First tick at or after decision + LATENCY_MINUTES."""
        return self.tick_ts >= decision_ts + timedelta(minutes=config.LATENCY_MINUTES)

    def realized_latency_min(self, decision_ts):
        return round((self.tick_ts - decision_ts).total_seconds() / 60.0, 1)

    def crossed_session(self, decision_ts):
        """Did the fill land in a later session than the decision?"""
        return market_calendar.et_date(decision_ts) != self.et_day

    def execute_entry_fill(self, trade, quote):
        """Sell to open, at the bid, at this tick."""
        decision_ts = datetime.fromisoformat(
            trade["entry_decision_ts"].replace("Z", "+00:00"))
        if not self.fill_is_due(decision_ts):
            return False
        price = accounting.sell_fill_price(quote)
        if price is None:
            if self.crossed_session(decision_ts):
                # Day-order realism: an entry that found no usable bid for the
                # rest of its decision session expires. Without this, an
                # unfillable order blocks its (arm, ticker) slot forever and
                # the next daily evaluation can never enter.
                self.writes.record(
                    store.update, config.TABLES["trades"],
                    {"status": "cancelled",
                     "exit_kind": "entry_cancelled_no_fill",
                     "closed_at": self.tick_ts.isoformat()},
                    id=trade["id"])
                self.event("entry_cancelled", trade["arm"], trade["ticker"],
                           trade["cycle_seq"],
                           payload={"reason": "no usable bid before the "
                                              "decision session ended"})
                self.tally.entries_cancelled += 1
                self.note(f"{trade['arm']}/{trade['ticker']} entry cancelled: "
                          f"day order, no usable bid")
                return False
            # No usable bid at the fill tick. The order does not fill; it waits.
            # Silently pretending it filled at the last known bid would be the
            # carried-forward-fill bug in forward time.
            self.note(f"{trade['arm']}/{trade['ticker']} entry fill deferred: "
                      f"no usable bid at {self.tick_ts.isoformat()}")
            return False
        contracts = trade["contracts"]
        comm = accounting.commission(contracts)
        patch = {
            "status": "open",
            "entry_fill_ts": self.tick_ts.isoformat(),
            "entry_fill_bid": quote.bid, "entry_fill_ask": quote.ask,
            "entry_fill_spot": quote.spot,
            "entry_fill_price": price,
            "entry_spread": quote.spread,
            "entry_spread_pct": accounting.spread_pct_of(quote, price),
            "entry_latency_min": self.realized_latency_min(decision_ts),
            "entry_overnight_gap": self.crossed_session(decision_ts),
            "entry_quote_stale": quote.stale,
            "entry_commission": comm,
            "premium_per_share": price,
        }
        self.writes.record(store.update, config.TABLES["trades"], patch,
                           id=trade["id"])
        self.event("entry_filled", trade["arm"], trade["ticker"],
                   trade["cycle_seq"],
                   payload={"fill_price": price, "bid": quote.bid,
                            "ask": quote.ask, "stale": quote.stale,
                            "latency_min": patch["entry_latency_min"]})
        self.tally.fills_executed += 1
        return True

    def execute_exit_fill(self, trade, quote):
        """Buy to close, at the ask. Settlements never come here any more —
        they book inline at the decision tick (`settle_position`)."""
        decision_ts = datetime.fromisoformat(
            trade["exit_decision_ts"].replace("Z", "+00:00"))

        # A pending buyback that survives past expiry is no longer a buyback:
        # the market for it is gone and the mechanics take over. ITM means the
        # stock was called away; OTM means it expired worthless. Without this,
        # a permanently no-ask contract (thin KKR) blocks its slot forever.
        if self.is_settlement_tick(trade["expiry"]):
            spot_fresh = quote.spot_usable and not quote.stale
            itm = spot_fresh and quote.spot > float(trade["strike"])
            decision = cc_core.Decision(
                kind="expiry_assigned" if itm else "expiry_worthless",
                verdict="EXPIRY", closes=True, assigned=itm,
                assignment_type="expiry" if itm else "",
                settle_price=(quote.spot - float(trade["strike"])) if itm else 0.0,
                priced_from=cc_core.INTRINSIC if itm else cc_core.ZERO)
            if not spot_fresh and quote.spot_usable:
                # Stale spot: cannot tell ITM from OTM trustworthily — settle
                # at intrinsic off the stale spot, flagged not-real.
                itm_stale = quote.spot > float(trade["strike"])
                decision = cc_core.Decision(
                    kind="expiry_assigned" if itm_stale else "expiry_worthless",
                    verdict="EXPIRY", closes=True, assigned=itm_stale,
                    assignment_type="expiry" if itm_stale else "",
                    settle_price=max(0.0, quote.spot - float(trade["strike"])),
                    priced_from=cc_core.INTRINSIC if itm_stale else cc_core.ZERO)
            return self.settle_position(trade, quote, decision, None, None)

        if not self.fill_is_due(decision_ts):
            return False

        contracts = trade["contracts"]
        used_fallback = False

        price = accounting.buy_fill_price(quote)
        if price is None and self.crossed_session(decision_ts):
            # The decision session ended with no usable ask. Spec §5.4: after a
            # session boundary the exit fills at the last recorded usable ask,
            # flagged stale and excluded from the real-fill subset — an open
            # risk position cannot wait forever on a quote that may never come
            # back (the liquidity floor guarantees one usable ask exists: the
            # entry required it).
            rows = store.select_rows(
                config.TABLES["quotes"],
                f"contract_symbol=eq.{trade['contract_symbol']}"
                f"&ask_usable=eq.true&order=tick_ts.desc&limit=1")
            if rows and cc_core.is_usable_number(rows[0].get("ask")):
                price = float(rows[0]["ask"])
                used_fallback = True
                self.tally.stale_fallback_exits += 1
                self.note(f"{trade['arm']}/{trade['ticker']} exit filled at the "
                          f"last recorded ask ({price}) after a session with no "
                          f"usable quote — stale fill, excluded from real-fill")
        if price is None:
            self.note(f"{trade['arm']}/{trade['ticker']} exit fill deferred: "
                      f"no usable ask at {self.tick_ts.isoformat()}")
            return False
        exit_comm = accounting.commission(contracts)
        spread = quote.spread

        premium = float(trade["premium_per_share"])
        pnl = accounting.cycle_pnl(
            premium_per_share=premium, buyback_per_share=price,
            contracts=contracts,
            entry_commission=float(trade.get("entry_commission") or 0),
            exit_commission=exit_comm)

        # A buyback is real only if the quote that filled it was neither
        # carried forward nor a post-session fallback.
        real_fill = not (quote.stale or used_fallback)

        patch = {
            "status": "closed",
            "exit_fill_ts": self.tick_ts.isoformat(),
            "exit_fill_bid": quote.bid, "exit_fill_ask": quote.ask,
            "exit_fill_spot": quote.spot,
            "exit_fill_price": price,
            "exit_spread": spread,
            "exit_spread_pct": accounting.spread_pct_of(quote, premium)
                               if spread is not None else None,
            "exit_latency_min": self.realized_latency_min(decision_ts),
            "exit_overnight_gap": self.crossed_session(decision_ts),
            "exit_quote_stale": quote.stale or used_fallback,
            "exit_commission": exit_comm,
            "spread_cost_total": accounting.spread_cost_usd(
                trade.get("entry_spread"), spread, contracts),
            "real_fill": real_fill,
            "closed_at": self.tick_ts.isoformat(),
            **pnl,
        }
        self.writes.record(store.update, config.TABLES["trades"], patch,
                           id=trade["id"])
        self.event("exit_filled", trade["arm"], trade["ticker"],
                   trade["cycle_seq"],
                   payload={"fill_price": price,
                            "priced_from": cc_core.OPTION_QUOTE,
                            "clause": trade.get("exit_clause"),
                            "net_pnl": pnl["net_pnl"], "real_fill": real_fill,
                            "latency_min": patch["exit_latency_min"]})
        self.tally.fills_executed += 1
        return True

    # ------------------------------------------------------------ decisions --
    def arm_acts_on(self, arm, decision, clause):
        """Does this arm act on this decision?

        Arms differ ONLY here. Every arm sees the identical decision computed
        from the identical quote; what differs is whether it trades on it.
        """
        if decision.kind in ("expiry_assigned", "expiry_worthless", "early_exercise"):
            # Market mechanics, not copilot rules. Every arm lives them.
            return True
        spec = config.ARMS[arm]["exits"]
        if spec == "none":
            return False
        if spec == "tp_and_emergency":
            return clause in config.ARM_D_CLAUSES
        return True

    def tick_position(self, trade, quote, ex_div, earnings, dividend):
        """One open position, one observation. The verdict comes from the one
        authority; this function never contains an alert rule."""
        strike = float(trade["strike"])
        premium = float(trade["premium_per_share"])
        contracts = trade["contracts"]

        if not quote.spot_usable:
            self.tally.positions_unassessed += 1
            self.note(f"{trade['arm']}/{trade['ticker']} unassessed: no usable spot")
            return

        # The copilot decides on the MID, because that is what the live monitor
        # passes (monitor_positions.py: `(bid + ask) / 2`) and what the
        # simulator's daily close approximates. The FILL pays the ask. Deciding
        # on the ask would make arm A a different strategy from the shipped one.
        mid = None
        if quote.bid_usable and quote.ask_usable:
            mid = (quote.bid + quote.ask) / 2
        elif quote.ask_usable:
            mid = quote.ask
        if mid is None:
            self.tally.assessed_without_ask += 1

        alert = assess_position(
            ticker=trade["ticker"], strike=strike, expiry=trade["expiry"],
            sold_price=premium, contracts=contracts,
            current_stock=quote.spot, current_option_ask=mid,
            ex_div_date=ex_div, earnings_date=earnings,
            as_of=self.tick_ts.astimezone(market_calendar.ET).date())
        self.tally.clause(alert.clause)

        ctx = _Ctx(trade, quote, alert, mid, ex_div, earnings, dividend,
                   self.tick_ts.astimezone(market_calendar.ET).date())
        if cc_core.assignment_is_approaching(ctx):
            self.tally.assignment_approaches += 1

        armed_on = trade.get("close_soon_armed_on")
        armed = (datetime.strptime(armed_on, "%Y-%m-%d").date()
                 if armed_on else None)

        def policy(_ctx):
            if alert.level in ("CLOSE_NOW", "EMERGENCY"):
                return cc_core.CLOSE_NOW, alert.level
            if alert.level == "CLOSE_SOON":
                return cc_core.CLOSE_SOON, alert.level
            return cc_core.HOLD, alert.level

        decision, new_armed = cc_core.decide(ctx, config.POLICY_CFG, policy,
                                             armed_on=armed)

        if new_armed != armed:
            self.writes.record(
                store.update, config.TABLES["trades"],
                {"close_soon_armed_on": new_armed.isoformat() if new_armed else None},
                id=trade["id"])

        if decision.closes and not self.arm_acts_on(trade["arm"], decision,
                                                    alert.clause):
            # The arm ignores the copilot, but market mechanics — expiry and
            # rational early exercise into the dividend — still apply.
            # cc_core.decide returns at the CLOSE_NOW step before ever reaching
            # its early-exercise branch, so a policy-ignoring arm must
            # re-decide under a HOLD policy; without this, arm B could never be
            # assigned early and the H41 (A-B) readout would be biased against
            # the copilot for the whole study (correctness review, 2026-08-21).
            decision, _ = cc_core.decide(
                ctx, config.POLICY_CFG,
                lambda _c: (cc_core.HOLD, alert.level), armed_on=None)
        if not decision.closes:
            return

        if decision.priced_from in (cc_core.INTRINSIC, cc_core.ZERO):
            # Settlements are mechanical: they book at the decision tick, and
            # expiry settlements wait for the day's FINAL tick so the spot that
            # prices them is the one nearest actual expiry.
            if decision.kind in ("expiry_assigned", "expiry_worthless") \
                    and not self.is_settlement_tick(trade["expiry"]):
                return
            self.settle_position(trade, quote, decision, ctx, alert)
            return

        patch = {
            "status": "pending_exit",
            "exit_decision_ts": self.tick_ts.isoformat(),
            "exit_decision_bid": quote.bid, "exit_decision_ask": quote.ask,
            "exit_decision_spot": quote.spot,
            "exit_kind": decision.kind,
            "exit_clause": alert.clause,
            "exit_verdict": decision.verdict,
            "exit_priced_from": decision.priced_from,
            "assigned": decision.assigned,
            "assignment_type": decision.assignment_type,
            "assignment_modeled": True,
            "assignment_inputs": store.json_safe({
                "spot": quote.spot, "strike": strike, "dividend": dividend,
                "ex_div_date": ex_div, "days_to_exdiv": ctx.days_to_exdiv,
                "extrinsic": ctx.extrinsic, "dte": alert.dte}),
        }
        self.writes.record(store.update, config.TABLES["trades"], patch,
                           id=trade["id"])
        self.event("exit_pending", trade["arm"], trade["ticker"],
                   trade["cycle_seq"],
                   payload={"kind": decision.kind, "clause": alert.clause,
                            "verdict": decision.verdict,
                            "decision_bid": quote.bid, "decision_ask": quote.ask})
        self.tally.exits_decided += 1

    # ---------------------------------------------------------- entry eval --
    def evaluate_entry(self, ticker, open_by_arm, halted_arms=frozenset()):
        """One ticker, one trading day. Contract selection runs BEFORE the gates."""
        strat = ticker_strategies.get_strategy(ticker) or {}
        otm = strat.get("otm_pct", 0.15)
        min_dte, max_dte = strat.get("min_dte", 20), strat.get("max_dte", 45)
        threshold = ticker_strategies.get_iv_threshold(ticker)

        fetch = quotes.fetch_chain(ticker, self.tick_ts, otm, min_dte, max_dte)
        row = {
            "tick_ts": self.tick_ts.isoformat(), "trading_day": self.et_day,
            "ticker": ticker, "chain_status": fetch.status,
            "spot": fetch.spot,
            "spot_usable": cc_core.is_usable_number(fetch.spot),
            "expiry": fetch.expiry, "dte": fetch.dte,
            "iv_threshold": threshold, "arm_results": {},
        }
        if fetch.status == quotes.PROXY_FAILED:
            self.tally.proxy_failures += 1
        elif fetch.status == quotes.EMPTY_CHAIN:
            self.tally.empty_chains += 1

        if not fetch.ok:
            row["liquidity_ok"] = False
            row["liquidity_reason"] = fetch.status
            row["arm_results"] = {a: {"entered": False, "reason": fetch.status,
                                      "gate_passed": None}
                                  for a in config.ARM_ORDER}
            self.writes.record(store.upsert, config.TABLES["entry_evals"],
                               store.json_safe(row), "ticker,trading_day")
            self.tally.entry_evals += 1
            return

        quote = list(fetch.quotes.values())[0]
        self.tally.quotes_expected += 1
        if quote.bid_usable or quote.ask_usable:
            self.tally.quotes_usable += 1
        self.writes.record(store.upsert, config.TABLES["quotes"],
                           quote.as_row(self.et_day), "contract_symbol,tick_ts")

        row.update({
            "contract_symbol": quote.contract_symbol,
            "strike": float(fetch.calls.loc[
                fetch.calls["contractSymbol"] == quote.contract_symbol,
                "strike"].iloc[0]),
            "bid": quote.bid, "ask": quote.ask, "last": quote.last,
            "volume": quote.volume, "open_interest": quote.open_interest,
            "implied_volatility": quote.implied_volatility,
        })

        liq_ok, liq_reason = quotes.liquidity_check(quote)
        row["liquidity_ok"], row["liquidity_reason"] = liq_ok, liq_reason

        # The gate ranks the ATM IV, never the selected OTM contract's IV: the
        # rank history is ATM history, and skew would shift every reading.
        atm_iv_pct = (fetch.atm_iv * 100
                      if cc_core.is_usable_number(fetch.atm_iv) else None)
        iv_rank, iv_source, iv_detail = quotes.iv_rank_for(ticker, atm_iv_pct)
        row["iv_rank"] = iv_rank
        row["iv_rank_source"] = f"{iv_source}: {iv_detail} (ATM IV)"

        for arm in config.ARM_ORDER:
            result = {"entered": False, "gate_passed": None, "reason": ""}
            if arm in halted_arms:
                # The pre-registration's words, enforced: "entries halt in the
                # affected arm/ticker" when a strategy kill is TRIGGERED.
                result["reason"] = "strategy kill TRIGGERED — entries halted"
            elif arm in open_by_arm:
                result["reason"] = "position already open"
            elif not liq_ok:
                # The floor is shared: a quote missing for one arm is missing
                # for all. Arms must never differ in their data.
                result["reason"] = f"liquidity: {liq_reason}"
            elif config.ARMS[arm]["iv_gate"]:
                if iv_rank is None:
                    result["gate_passed"] = False
                    result["reason"] = f"no IV rank ({iv_detail})"
                else:
                    result["gate_passed"] = iv_rank >= threshold
                    result["reason"] = f"iv_rank={iv_rank:.0f} vs {threshold}"
                    result["entered"] = result["gate_passed"]
            else:
                result["gate_passed"] = True
                result["reason"] = "no IV gate (arm C)"
                result["entered"] = True
            row["arm_results"][arm] = result

        self.writes.record(store.upsert, config.TABLES["entry_evals"],
                           store.json_safe(row), "ticker,trading_day")
        self.tally.entry_evals += 1

        contracts, _reason = config.contracts_for(ticker)
        for arm, result in row["arm_results"].items():
            if not result["entered"]:
                continue
            seq = self.next_cycle_seq(arm, ticker)
            trade = {
                "arm": arm, "ticker": ticker, "cycle_seq": seq,
                "status": "pending_entry",
                "contract_symbol": quote.contract_symbol,
                "strike": row["strike"], "expiry": fetch.expiry,
                "dte_at_entry": fetch.dte, "contracts": contracts,
                "entry_decision_ts": self.tick_ts.isoformat(),
                "entry_decision_bid": quote.bid,
                "entry_decision_ask": quote.ask,
                "entry_decision_spot": quote.spot,
            }
            if self.writes.record(store.insert, config.TABLES["trades"],
                                  store.json_safe(trade)):
                self.event("entry_pending", arm, ticker, seq,
                           payload={"contract": quote.contract_symbol,
                                    "decision_bid": quote.bid,
                                    "decision_ask": quote.ask,
                                    "iv_rank": iv_rank})
                self.tally.entries_opened += 1

    # -------------------------------------------------------------- events --
    def event(self, kind, arm=None, ticker=None, cycle_seq=None,
              severity="info", payload=None, dedup_extra=None):
        """`dedup_extra` distinguishes events that share (kind, arm, ticker,
        cycle, tick): without it, every scope-None kill switch transitioning at
        the same tick collided on one dedup_key and all but the first were
        silently dropped — so a dropped switch re-announced itself every tick,
        the exact alert-per-tick failure the dedup exists to prevent."""
        key_parts = [kind, arm or "-", ticker or "-", str(cycle_seq or "-"),
                     self.tick_ts.isoformat()]
        if dedup_extra:
            key_parts.append(str(dedup_extra))
        return self.writes.record(store.insert_event, {
            "event_ts": self.tick_ts.isoformat(), "trading_day": self.et_day,
            "kind": kind, "severity": severity, "arm": arm, "ticker": ticker,
            "cycle_seq": cycle_seq, "dedup_key": "|".join(key_parts),
            "payload": store.json_safe(payload or {}),
        })

    def note(self, message):
        print(f"  [note] {message}", flush=True)
        self.notes.append(message)

    # ----------------------------------------------------------------- run --
    def run(self):
        print(f"[paper_engine {config.ENGINE_VERSION}] tick "
              f"{self.tick_ts.isoformat()} (ET day {self.et_day})", flush=True)

        gate = preflight.check()
        print(f"  startup gate: PASS "
              f"(preregistration {gate['checks']['preregistration_doc']['sha256'][:12]})",
              flush=True)

        if not self.market_is_open():
            print("  market closed — heartbeat and exit", flush=True)
            store.write_heartbeat(ok=True, detail={
                "market_closed": True, "tick_ts": self.tick_ts.isoformat(),
                "engine": config.ENGINE_NAME})
            return 0

        trades = self.load_trades()
        print(f"  {len(trades)} open/pending trade rows", flush=True)

        by_contract = {}
        for t in trades:
            by_contract.setdefault(
                (t["ticker"], t["contract_symbol"], t["expiry"]), []).append(t)

        # 4 + 5: capture, then fill what is due.
        captured = {}
        for (ticker, symbol, expiry), rows in by_contract.items():
            q = self.capture_quote(ticker, symbol, expiry)
            captured[symbol] = q
            for t in rows:
                if t["status"] == "pending_entry":
                    self.execute_entry_fill(t, q)
                elif t["status"] == "pending_exit":
                    self.execute_exit_fill(t, q)

        # 6: tick everything that is open (including anything just filled).
        trades = self.load_trades()
        info_cache = {}
        for t in trades:
            if t["status"] != "open":
                continue
            ticker = t["ticker"]
            if ticker not in info_cache:
                try:
                    info_cache[ticker] = (*self.stock_dates(ticker),
                                          self.dividend_amount(ticker))
                except Exception as e:
                    self.tally.positions_unassessed += 1
                    self.note(f"{ticker}: {e} — positions unassessed this tick")
                    info_cache[ticker] = None
            if info_cache[ticker] is None:
                continue
            ex_div, earnings, _yield, dividend = info_cache[ticker]
            q = captured.get(t["contract_symbol"])
            if q is None:
                q = self.capture_quote(ticker, t["contract_symbol"], t["expiry"])
                captured[t["contract_symbol"]] = q
            self.tick_position(t, q, ex_div, earnings, dividend)

        # 7: kill switches — evaluated BEFORE entries so a TRIGGERED switch
        #    actually stops them. A switch computed after the entries it was
        #    supposed to prevent is decoration, not a switch. Alerting stays
        #    transition-only.
        kills = killswitch.evaluate(self.tick_ts, self.tally)
        for k in killswitch.transitions(kills, self):
            self.alerts.append(k)
        pause_all, halted_by_ticker, halted_global = killswitch.entry_halts(kills)

        # 8: entry evaluation, once per ticker per day.
        if self.is_entry_eval_tick():
            if pause_all:
                # The paused period must contain no evidence, so it contains no
                # entries — and no evaluation rows built from data the same
                # integrity failure has already impeached.
                self.note("entries paused: an ENGINE INTEGRITY kill is "
                          "TRIGGERED — no entry evaluation this tick")
            else:
                done = self.already_evaluated_today()
                open_arms = {}
                for t in self.load_trades():
                    open_arms.setdefault(t["ticker"], set()).add(t["arm"])
                for ticker in self.universe:
                    if ticker in done:
                        continue
                    self.evaluate_entry(
                        ticker, open_arms.get(ticker, set()),
                        halted_arms=(halted_by_ticker.get(ticker, set())
                                     | halted_global))

        # 9: heartbeat. A run that attempted writes and confirmed none is the
        #    shape of a silent outage and must not exit 0.
        detail = {
            "tick_ts": self.tick_ts.isoformat(),
            "tally": self.tally.as_dict(),
            "writes": self.writes.as_dict(),
            "kills": kills,
            "notes": self.notes[:20],
            "positions_unassessed": self.tally.positions_unassessed,
        }
        ok = not self.writes.silently_empty
        store.write_heartbeat(ok=ok, detail=store.json_safe(detail),
                              positions_checked=len(trades),
                              alerts_fired=len(self.alerts))
        print(f"  {self.writes} | coverage "
              f"{detail['tally']['quote_coverage_pct']}% | "
              f"{len(self.alerts)} alerts", flush=True)

        if self.alerts:
            _notify("\n".join(self.alerts))

        if self.writes.silently_empty:
            print("FAIL: attempted writes, confirmed none. Exiting 1.", flush=True)
            return 1
        return 0


class _Ctx:
    """A cc_sim.DayContext-shaped view of a live position, for cc_core.decide.

    Deliberately duck-typed rather than importing DayContext: cc_sim pulls in
    pandas and numpy, and a research import at module scope is what took the
    safety-critical monitor down on 2026-08-16. The attribute contract is
    asserted by tests/test_paper_engine_policy.py.
    """

    def __init__(self, trade, quote, alert, mid, ex_div, earnings, dividend, as_of):
        self.ticker = trade["ticker"]
        self.date = as_of
        self.spot = quote.spot
        self.strike = float(trade["strike"])
        self.option_price = mid if mid is not None else 0.0
        self.sold_price = float(trade["premium_per_share"])
        self.dte = alert.dte
        self.days_to_exdiv = alert.days_to_exdiv
        self.dividend = dividend
        self.expiration = trade["expiry"]
        self.price_is_stale = quote.stale

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


def _notify(message):
    """Discord only, and only from scheduled engine runs.

    The health API reports; it never alerts. One stale heartbeat behind an
    alerting health endpoint produced an alert per minute for hours
    (tasks/lessons.md 2026-08-19), so the two roles are kept apart by
    construction: this function lives in the engine and nowhere else.
    """
    webhook = os.environ.get("DISCORD_WEBHOOK", "")
    if not webhook:
        print(f"  [alert, undelivered — no DISCORD_WEBHOOK]\n{message}", flush=True)
        return False
    import requests
    try:
        requests.post(webhook, json={"content": f"**Paper engine**\n{message}"},
                      timeout=10)
        return True
    except Exception as e:                                     # pragma: no cover
        print(f"  [alert delivery failed] {e}", flush=True)
        return False


def main():                                                    # pragma: no cover
    try:
        return PaperEngine().run()
    except (preflight.GateFailure, store.StoreError) as e:
        print(f"FATAL: {e}", flush=True)
        try:
            store.write_heartbeat(ok=False, detail={"fatal": str(e)[:2000]})
        except Exception:
            print("  (could not write the failure heartbeat)", flush=True)
        return 1
    except Exception:
        traceback.print_exc()
        try:
            store.write_heartbeat(
                ok=False, detail={"fatal": traceback.format_exc()[:2000]})
        except Exception:
            pass
        return 1


if __name__ == "__main__":                                     # pragma: no cover
    sys.exit(main())
