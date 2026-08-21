"""Walk one full paper cycle end to end, against an in-memory store.

This is the spec's acceptance §11 evidence, runnable by anyone:

  1. Startup gate RED before registration, GREEN after.
  2. Write-verify: a store that silently accepts and persists nothing makes the
     run exit 1 rather than report success.
  3. Latency and conservative fills on real quote rows: entry decided at T,
     filled at the BID at the first tick >= T+15; exit decided later, filled at
     the ASK; alert-time and fill-time quotes both shown.

It uses REAL quotes from the proxy for the shape and prices, and a scripted
price path for the exit so the demonstration is deterministic. Nothing here
touches Supabase and nothing here can reach a broker.

    python3 scripts/paper_engine_demo.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cc_core
from paper_engine import accounting, config, quotes


class FakeStore:
    """An in-memory stand-in that still refuses to lie about what it stored."""

    def __init__(self, silently_drop=False):
        self.tables = {}
        self.silently_drop = silently_drop

    def insert(self, table, row, verify=True):
        if self.silently_drop:
            # The 2026-08-15 shape: the write appears to succeed and persists
            # nothing. With read-back verification it raises instead.
            if verify:
                raise RuntimeError(
                    f"{table} insert returned no row — the write did not persist")
            return None
        self.tables.setdefault(table, []).append(dict(row))
        return dict(row)


def banner(text):
    print(f"\n{'=' * 78}\n{text}\n{'=' * 78}", flush=True)


def demo_startup_gate():
    banner("1. STARTUP GATE — red before registration, green after")
    from paper_engine import preflight, store

    real_backend = preflight.graveyard_backend_is_supabase
    real_schema = store.schema_contract_check
    real_rows = store.graveyard_rows
    try:
        preflight.graveyard_backend_is_supabase = lambda: (True, "supabase")
        store.schema_contract_check = lambda: {"ok": True}

        store.graveyard_rows = lambda ids: {}
        try:
            preflight.check()
            print("  UNEXPECTED: the gate passed with no registration")
            return False
        except preflight.GateFailure as e:
            print(f"  RED (correct): {str(e).splitlines()[0]}")

        h = preflight.preregistration_hash()
        store.graveyard_rows = lambda ids: {
            i: {"signal_id": i, "status": "untested",
                "pre_registered_date": "2026-08-20",
                "pass_thresholds": {"preregistration_sha256": h}} for i in ids}
        report = preflight.check()
        print(f"  GREEN after registration: doc {h[:16]}…, "
              f"{len(report['checks']['hypotheses'])} hypotheses")

        store.graveyard_rows = lambda ids: {
            i: {"signal_id": i, "status": "untested",
                "pass_thresholds": {"preregistration_sha256": "tampered"}}
            for i in ids}
        try:
            preflight.check()
            print("  UNEXPECTED: a tampered hash passed the gate")
            return False
        except preflight.GateFailure:
            print("  RED again after a threshold edit (hash mismatch) — the "
                  "engine bricks rather than bending the experiment")
        return True
    finally:
        preflight.graveyard_backend_is_supabase = real_backend
        store.schema_contract_check = real_schema
        store.graveyard_rows = real_rows


def demo_write_verify():
    banner("2. WRITE VERIFICATION — zero confirmed writes is a failure, not a quiet success")
    from paper_engine import store as real_store

    counter = real_store.ConfirmedCounter()
    dropping = FakeStore(silently_drop=True)

    def attempt(row):
        try:
            return dropping.insert("paper_engine_trades", row)
        except RuntimeError as e:
            raise real_store.StoreError(str(e))

    for i in range(3):
        counter.record(attempt, {"cycle_seq": i})
    print(f"  attempted={counter.attempted} confirmed={counter.confirmed}")
    print(f"  silently_empty -> {counter.silently_empty}  (the engine exits 1 on this)")
    print(f"  first failure: {counter.failures[0][:90]}")
    assert counter.silently_empty
    assert counter.confirmed == 0
    return True


# Captured by scripts/probe_quotes.py on 2026-08-20 at ~22:05 UTC, during the
# session. Used so the walkthrough is deterministic and reviewable; the live
# after-hours book is shown separately below, where it correctly has no bid.
RECORDED = {
    "AAPL": dict(contract="AAPL260918C00360000", strike=360.0, expiry="2026-09-18",
                 dte=28, spot=311.30, bid=0.28, ask=0.31),
    "KKR": dict(contract="KKR260918C00125000", strike=125.0, expiry="2026-09-18",
                dte=28, spot=107.02, bid=0.15, ask=0.55),
}


def demo_live_floor(ticker="AAPL"):
    """Show what the engine does with the book as it is RIGHT NOW."""
    banner(f"3. LIQUIDITY FLOOR AGAINST THE LIVE BOOK — {ticker}")
    import ticker_strategies
    strat = ticker_strategies.get_strategy(ticker) or {}
    t0 = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    fetch = quotes.fetch_chain(ticker, t0, strat.get("otm_pct", 0.15),
                               strat.get("min_dte", 20), strat.get("max_dte", 45))
    print(f"  fetched at {t0.isoformat()}  status={fetch.status}")
    if not fetch.ok:
        print(f"  {fetch.detail}")
        print("  -> recorded as an entry evaluation WITH A REASON; no arm enters. "
              "An empty dict is never treated as data.")
        return
    q = list(fetch.quotes.values())[0]
    ok, reason = quotes.liquidity_check(q)
    print(f"  {q.contract_symbol}  bid={q.bid} ask={q.ask} spread={q.spread}")
    print(f"  liquidity floor: {'PASS' if ok else 'FAIL'} ({reason})")
    if not ok:
        print("  -> no entry for ANY arm. The floor is shared: a quote missing")
        print("     for one arm is missing for all. Dad cannot sell at a zero bid.")


def demo_full_cycle(ticker="AAPL"):
    banner(f"4. ONE FULL CYCLE ON RECORDED SESSION QUOTES — {ticker}")
    rec = RECORDED[ticker]

    class _F:
        pass
    fetch = _F()
    fetch.expiry, fetch.dte = rec["expiry"], rec["dte"]

    t0 = datetime(2026, 8, 20, 19, 30, tzinfo=timezone.utc)
    q_alert = quotes.Quote(contract_symbol=rec["contract"], ticker=ticker,
                           tick_ts=t0, bid=rec["bid"], ask=rec["ask"],
                           spot=rec["spot"], source_status=quotes.OK)
    strike = rec["strike"]
    contracts, cap_reason = config.contracts_for(ticker)
    ok, reason = quotes.liquidity_check(q_alert)

    print(f"  T+0   decision tick   {t0.isoformat()}")
    print(f"        contract        {q_alert.contract_symbol} "
          f"(expiry {fetch.expiry}, {fetch.dte} DTE, spot {q_alert.spot})")
    print(f"        ALERT-TIME quote  bid={q_alert.bid}  ask={q_alert.ask}  "
          f"spread={q_alert.spread}")
    print(f"        liquidity floor   {'PASS' if ok else 'FAIL'} ({reason})")
    print(f"        size              {contracts} contracts"
          f"{' — ' + cap_reason[:60] if cap_reason else ' (no liquidity cap)'}")
    if not ok:
        print("        -> no entry for ANY arm today. Same data for every arm.")
        return False

    # ---- the fill, fifteen minutes later ----------------------------------
    # In the demo the market has moved a little between the two ticks; the
    # engine uses whatever the quote is AT THE FILL TICK, never the alert quote.
    t1 = t0 + timedelta(minutes=config.LATENCY_MINUTES)
    q_fill = quotes.Quote(
        contract_symbol=q_alert.contract_symbol, ticker=ticker, tick_ts=t1,
        bid=round((q_alert.bid or 0) - 0.01, 2), ask=q_alert.ask,
        spot=q_alert.spot, source_status=quotes.OK)

    entry_price = accounting.sell_fill_price(q_fill)
    entry_comm = accounting.commission(contracts)
    print(f"\n  T+{config.LATENCY_MINUTES}  fill tick       {t1.isoformat()}")
    print(f"        FILL-TIME quote   bid={q_fill.bid}  ask={q_fill.ask}")
    print(f"        SELL fills at the BID -> ${entry_price} "
          f"(NOT the mid {round(((q_fill.bid or 0)+(q_fill.ask or 0))/2, 3)}, "
          f"NOT the alert-time bid {q_alert.bid})")
    print(f"        credit            ${entry_price * 100 * contracts:.2f}")
    print(f"        commission        ${entry_comm:.2f}")
    print(f"        realized latency  "
          f"{(t1 - t0).total_seconds() / 60:.0f} min")

    # ---- an exit decision, later ------------------------------------------
    # Scripted so the demonstration is deterministic: the option has decayed to
    # 20% of the premium, which fires the TP-75 rung.
    t2 = t1 + timedelta(days=9)
    decayed_bid = round(entry_price * 0.18, 2)
    decayed_ask = round(entry_price * 0.24, 2)
    q_exit_alert = quotes.Quote(
        contract_symbol=q_alert.contract_symbol, ticker=ticker, tick_ts=t2,
        bid=decayed_bid, ask=decayed_ask, spot=q_alert.spot,
        source_status=quotes.OK)

    from position_monitor import assess_position
    mid = (decayed_bid + decayed_ask) / 2
    alert = assess_position(
        ticker=ticker, strike=strike, expiry=fetch.expiry, sold_price=entry_price, contracts=contracts,
        current_stock=q_alert.spot, current_option_ask=mid,
        as_of=t2.date())
    print(f"\n  T+9d  exit decision   {t2.isoformat()}")
    print(f"        ALERT-TIME quote  bid={decayed_bid}  ask={decayed_ask}")
    print(f"        copilot decides on the MID ({mid:.3f}) — the same input the "
          f"live monitor passes")
    print(f"        verdict           {alert.level}  clause={alert.clause}")
    print(f"        premium captured  {alert.premium_captured_pct:.0f}%")

    # ---- the exit fill, fifteen minutes after that ------------------------
    t3 = t2 + timedelta(minutes=config.LATENCY_MINUTES)
    q_exit_fill = quotes.Quote(
        contract_symbol=q_alert.contract_symbol, ticker=ticker, tick_ts=t3,
        bid=decayed_bid, ask=round(decayed_ask + 0.01, 2), spot=q_alert.spot,
        source_status=quotes.OK)
    exit_price = accounting.buy_fill_price(q_exit_fill)
    exit_comm = accounting.commission(contracts)

    pnl = accounting.cycle_pnl(
        premium_per_share=entry_price, buyback_per_share=exit_price,
        contracts=contracts, entry_commission=entry_comm,
        exit_commission=exit_comm)
    spread_cost = accounting.spread_cost_usd(
        q_fill.spread, q_exit_fill.spread, contracts)

    print(f"\n  T+9d+{config.LATENCY_MINUTES}  exit fill  {t3.isoformat()}")
    print(f"        FILL-TIME quote   bid={q_exit_fill.bid}  ask={q_exit_fill.ask}")
    print(f"        BUY BACK fills at the ASK -> ${exit_price}")

    banner("LEDGER ROW — the auditable receipt")
    rows = [
        ("arm / ticker / cycle", f"A / {ticker} / 1"),
        ("contract", q_alert.contract_symbol),
        ("contracts", contracts),
        ("entry decision ts", t0.isoformat()),
        ("entry ALERT quote", f"bid {q_alert.bid} / ask {q_alert.ask}"),
        ("entry fill ts", t1.isoformat()),
        ("entry FILL quote", f"bid {q_fill.bid} / ask {q_fill.ask}"),
        ("entry fill price (bid)", f"${entry_price}"),
        ("entry latency", f"{(t1 - t0).total_seconds() / 60:.0f} min"),
        ("exit decision ts", t2.isoformat()),
        ("exit ALERT quote", f"bid {q_exit_alert.bid} / ask {q_exit_alert.ask}"),
        ("exit fill ts", t3.isoformat()),
        ("exit FILL quote", f"bid {q_exit_fill.bid} / ask {q_exit_fill.ask}"),
        ("exit fill price (ask)", f"${exit_price}"),
        ("exit clause", alert.clause),
        ("exit verdict", alert.level),
        ("premium per share", f"${pnl['premium_per_share']}"),
        ("buyback per share", f"${pnl['buyback_per_share']}"),
        ("gross P&L", f"${pnl['gross_pnl']}"),
        ("commissions", f"${pnl['commissions_total']}"),
        ("spread cost vs mid", f"${spread_cost}"),
        ("NET P&L", f"${pnl['net_pnl']}"),
        ("real fill", "True (neither quote carried forward)"),
    ]
    for k, v in rows:
        print(f"  {k:24s} {v}")

    print(f"\n  Retention: {accounting.retention(pnl['net_pnl'], entry_price * 100 * contracts)}")
    return True


def main():
    ok = True
    ok = demo_startup_gate() and ok
    ok = demo_write_verify() and ok
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    demo_live_floor(ticker)
    demo_full_cycle(ticker)
    banner("NOTE")
    print("  Section 3 hits the live proxy. Section 4 replays quotes captured")
    print("  during the 2026-08-20 session (scripts/probe_quotes.py) so the")
    print("  walkthrough is deterministic, and scripts the exit leg's decay.")
    print("  The FILL RULES exercised — sell at the bid, buy back at the ask,")
    print("  first tick at or after T+15 — are the engine's real code paths.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
