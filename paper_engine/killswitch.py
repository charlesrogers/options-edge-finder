"""Kill switches: two classes, never conflated.

"Turn the strategy off" has to be a pre-registered, mechanical decision rather
than a mood, and it has to distinguish two things that look identical on a
dashboard and mean opposite things:

  * **Engine-integrity pause** — the DATA is bad. Entries stop, monitoring
    continues, and NO strategy conclusion may be drawn from the affected
    period. A period paused for bad data is a period with no evidence in it,
    not a period of evidence against the strategy.
  * **Strategy kill** — the STRATEGY is behaving outside its pre-registered
    envelope. Entries halt in the affected arm/ticker, Charles is alerted, and
    the milestone review convenes early.

A TRIGGERED kill is advisory to production and nothing more. It halts a paper
arm and sends a message. It never edits `ticker_strategies.py` — that path stays
behind pre-registration -> walk-forward -> approval gate -> one variable per
commit (tasks/lessons.md 2026-03-27, Exp 013's direct deploy and revert).

Thresholds are not defined here. They are read from `thresholds.json`, which is
embedded verbatim in `PREREGISTRATION.md`, whose SHA-256 the startup gate
checks. Moving a threshold means editing the document, which bricks the engine
until someone re-registers deliberately.
"""
import json
import os
from datetime import timedelta

import market_calendar

from . import config, store

HERE = os.path.dirname(os.path.abspath(__file__))
THRESHOLDS_PATH = os.path.join(
    os.path.dirname(HERE), "experiments", "024_paper_engine", "thresholds.json")

ARMED, TRIGGERED, DISARMED = "ARMED", "TRIGGERED", "DISARMED"
INTEGRITY, STRATEGY = "engine_integrity", "strategy"

_cache = None


def thresholds():
    global _cache
    if _cache is None:
        with open(THRESHOLDS_PATH) as f:
            _cache = json.load(f)
    return _cache


def _switch(name, kind, state, value, threshold, detail, scope=None,
            halts=True):
    """`halts=False` marks a warn-only switch: it renders on the board and
    alerts on transition, but never pauses entries. Without the flag, the
    stale-quotes warning — whose own detail says "this warns, it does not
    halt" — was pausing every ticker's entries for a whole day on one proxy
    blip (correctness review, 2026-08-27)."""
    return {"name": name, "kind": kind, "state": state, "value": value,
            "threshold": threshold, "detail": detail, "scope": scope,
            "halts": halts}


# ------------------------------------------------------------- integrity ----

def integrity_switches(tick_ts, tally):
    t = thresholds()["kills"]["engine_integrity"]
    out = []

    cov_threshold = t["quote_coverage_pct_trailing_5_sessions"]["threshold"]
    coverage = trailing_quote_coverage(tick_ts)
    out.append(_switch(
        "quote_coverage_5_sessions", INTEGRITY,
        TRIGGERED if (coverage is not None and coverage < cov_threshold) else ARMED,
        coverage, cov_threshold,
        "usable quotes / captured quotes over the trailing 5 sessions. Below "
        "this, entries pause: a strategy cannot be graded on a period whose "
        "prices we could not see."))

    ask_threshold = t["assessed_without_ask_pct"]["threshold"]
    total = max(1, tally.quotes_expected)
    ask_pct = round(tally.assessed_without_ask / total * 100, 1)
    out.append(_switch(
        "assessed_without_ask_pct", INTEGRITY,
        TRIGGERED if ask_pct > ask_threshold else ARMED, ask_pct, ask_threshold,
        "share of assessments run with no usable option quote. "
        "assess_position defaults premium_captured_pct to 0 in that case, which "
        "silently disables TP-75 and TP-50 — the forward-time twin of the DTE "
        "bug. Above this, no exit result from the period means anything."))

    stale_threshold = t["consecutive_stale_ticks_warning"]["threshold"]
    out.append(_switch(
        "stale_quotes_this_run", INTEGRITY,
        TRIGGERED if tally.quotes_stale >= stale_threshold else ARMED,
        tally.quotes_stale, stale_threshold,
        "carried-forward quotes this tick. A data problem, not a strategy "
        "problem — this warns, it does not halt.",
        halts=False))

    return out


def trailing_quote_coverage(tick_ts, sessions=5):
    """Usable / captured quotes over the trailing `sessions` trading days."""
    since = (tick_ts - timedelta(days=sessions * 3)).date().isoformat()
    rows = store.select_rows(
        config.TABLES["quotes"],
        f"trading_day=gte.{since}&select=bid_usable,ask_usable,stale")
    if not rows:
        return None
    usable = sum(1 for r in rows
                 if (r["bid_usable"] or r["ask_usable"]) and not r["stale"])
    return round(usable / len(rows) * 100, 1)


# -------------------------------------------------------------- strategy ----

def strategy_switches(tick_ts):
    t = thresholds()["kills"]["strategy"]
    out = []
    closed = store.select_rows(
        config.TABLES["trades"],
        "status=eq.closed&select=arm,ticker,cycle_seq,net_pnl,real_fill,"
        "assigned,assignment_type,closed_at,exit_clause&order=closed_at")

    # 1. Drawdown, per ticker, arm A, real-fill accounting.
    for ticker, cfg in t["drawdown"]["per_ticker"].items():
        dd = worst_trailing_drawdown(
            [c for c in closed
             if c["arm"] == "A" and c["ticker"] == ticker and c["real_fill"]])
        out.append(_switch(
            "drawdown", STRATEGY,
            TRIGGERED if (dd is not None and dd > cfg["threshold_usd_per_contract"])
            else ARMED,
            dd, cfg["threshold_usd_per_contract"], cfg["derivation"],
            scope=ticker))

    # 2. Any modeled assignment in arm A. Reported WITH the reachability count —
    #    a zero from a state that was never reached is non-binding, not a pass.
    for ticker in sorted({c["ticker"] for c in closed} |
                         set(t["drawdown"]["per_ticker"])):
        n = sum(1 for c in closed
                if c["arm"] == "A" and c["ticker"] == ticker and c["assigned"])
        out.append(_switch(
            "modeled_assignment_arm_A", STRATEGY,
            TRIGGERED if n >= 1 else ARMED, n, 1,
            "Any modeled assignment in arm A halts that ticker. A paper "
            "position cannot truly be assigned; this is cc_core's "
            "rational-exercise model. A count of zero must be read next to the "
            "approach count on the health page — zero from an unreachable "
            "state is 'non-binding', not 'constraint met'.",
            scope=ticker))

    # 3. Consecutive losing cycles, per ticker, where the reference gave a
    #    calibratable win rate.
    for ticker, cfg in t["consecutive_losses"].items():
        if not cfg.get("armed"):
            out.append(_switch(
                "consecutive_losses", STRATEGY, DISARMED, None, None,
                cfg["derivation"], scope=ticker))
            continue
        run = current_loss_run(
            [c for c in closed
             if c["arm"] == "A" and c["ticker"] == ticker and c["real_fill"]])
        out.append(_switch(
            "consecutive_losses", STRATEGY,
            TRIGGERED if run >= cfg["M"] else ARMED, run, cfg["M"],
            cfg["derivation"], scope=ticker))

    # 4. EMERGENCY cluster in the trailing 30 days.
    ec = t["emergency_cluster_30d"]
    if ec.get("armed"):
        since = (tick_ts - timedelta(days=30)).isoformat()
        rows = store.select_rows(
            config.TABLES["events"],
            f"kind=eq.exit_pending&event_ts=gte.{since}&select=payload")
        n = sum(1 for r in rows
                if (r.get("payload") or {}).get("verdict") == "EMERGENCY")
        out.append(_switch(
            "emergency_cluster_30d", STRATEGY,
            TRIGGERED if n >= ec["E"] else ARMED, n, ec["E"],
            ec["derivation"] + " " + ec.get("floor_reason", "")))
    return out


def worst_trailing_drawdown(closed_trades, window_days=30):
    """Worst peak-to-trough of realised net P&L inside any 30-day window.

    Same definition as the reference table's, so the live number and the
    threshold it is compared against are the same measurement. A threshold
    computed one way and evaluated another is not a threshold.
    """
    if not closed_trades:
        return None
    from datetime import datetime
    pts = sorted(
        ((datetime.fromisoformat(c["closed_at"].replace("Z", "+00:00")),
          float(c["net_pnl"] or 0)) for c in closed_trades if c.get("closed_at")),
        key=lambda x: x[0])
    if not pts:
        return None
    dates = [p[0] for p in pts]
    cum, running = [], 0.0
    for _, v in pts:
        running += v
        cum.append(running)
    worst = 0.0
    for i, d in enumerate(dates):
        lo = d - timedelta(days=window_days)
        prior = [cum[j] for j in range(i + 1) if dates[j] >= lo]
        start_level = cum[i - len(prior)] if len(prior) <= i else 0.0
        worst = max(worst, max(prior + [start_level]) - cum[i])
    return round(worst, 2)


def current_loss_run(closed_trades):
    """Length of the run of losses ending at the most recent closed cycle."""
    run = 0
    for c in sorted(closed_trades, key=lambda x: x.get("closed_at") or "",
                    reverse=True):
        if float(c["net_pnl"] or 0) < 0:
            run += 1
        else:
            break
    return run


# ------------------------------------------------------------ evaluation ----

def evaluate(tick_ts, tally):
    """Every switch, with its live value. Pure read — this never alerts."""
    switches = integrity_switches(tick_ts, tally) + strategy_switches(tick_ts)
    return {
        "evaluated_at": tick_ts.isoformat(),
        "switches": switches,
        "triggered": [s for s in switches if s["state"] == TRIGGERED],
        "entries_paused": any(
            s["state"] == TRIGGERED and s["kind"] == INTEGRITY
            and s.get("halts", True) for s in switches),
    }


def _key(switch):
    return f"{switch['kind']}:{switch['name']}:{switch.get('scope') or '-'}"


def entry_halts(evaluation):
    """What a TRIGGERED switch actually stops, made consultable.

    Returns (pause_all, per_ticker_arms, global_arms):
      * pause_all — any INTEGRITY switch TRIGGERED: NO entry evaluation at all.
        The paused period contains no evidence, so it must contain no entries.
      * per_ticker_arms — {ticker: {arm, ...}} halted by a scoped STRATEGY kill.
      * global_arms — arms halted by an unscoped STRATEGY kill (the EMERGENCY
        cluster has no ticker scope).

    Every strategy switch measures arm A, so strategy halts apply to arm A —
    the pre-registration's words are "entries halt in the affected arm/ticker".
    A switch that is computed but never consulted is not a switch (correctness
    review, 2026-08-21: kills were evaluated AFTER entries and enforced never).
    """
    pause_all = any(s["state"] == TRIGGERED and s["kind"] == INTEGRITY
                    and s.get("halts", True)
                    for s in evaluation["switches"])
    per_ticker, global_arms = {}, set()
    for s in evaluation["switches"]:
        if s["state"] == TRIGGERED and s["kind"] == STRATEGY:
            if s.get("scope"):
                per_ticker.setdefault(s["scope"], set()).add("A")
            else:
                global_arms.add("A")
    return pause_all, per_ticker, global_arms


def last_states():
    """The most recent recorded state of every switch."""
    rows = store.select_rows(
        config.TABLES["events"],
        "kind=eq.kill_state_change&select=payload,event_ts"
        "&order=event_ts.desc&limit=500")
    seen = {}
    for r in rows:
        p = r.get("payload") or {}
        k = p.get("key")
        if k and k not in seen:
            seen[k] = p.get("state")
    return seen


def transitions(evaluation, engine):
    """Alert once when a switch CHANGES state, never once per tick it stays there.

    A health endpoint that alerted on every poll produced one alert per minute
    for hours off a single stale heartbeat (tasks/lessons.md 2026-08-19). The
    fix is not "alert less often", it is "alert on the transition" — and the
    transition is derived from persisted state, so a restart cannot re-announce
    a switch that has been TRIGGERED for a week.
    """
    previous = last_states()
    messages = []
    for s in evaluation["switches"]:
        k = _key(s)
        if previous.get(k) == s["state"]:
            continue
        engine.event("kill_state_change",
                     ticker=s.get("scope"),
                     severity="critical" if s["state"] == TRIGGERED else "info",
                     dedup_extra=k,
                     payload={"key": k, "state": s["state"],
                              "previous": previous.get(k),
                              "value": s["value"], "threshold": s["threshold"],
                              "kind": s["kind"], "detail": s["detail"]})
        if s["state"] == TRIGGERED:
            what = ("ENGINE INTEGRITY — entries pause, and NO strategy "
                    "conclusion may be drawn from this period"
                    if s["kind"] == INTEGRITY else
                    "STRATEGY KILL — the paper arm halts and the milestone "
                    "review convenes early. This changes nothing in production")
            messages.append(
                f"TRIGGERED: {k} = {s['value']} (threshold {s['threshold']}). {what}.")
    return messages
