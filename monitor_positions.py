"""
Position Monitor — Pushover push notifications for covered call alerts.

Runs every 15 min during market hours via GitHub Actions.
Checks all open trades, runs the copilot, sends alerts via Pushover.

Alert levels → Pushover priority:
  SAFE       → no notification
  WATCH      → daily summary only
  CLOSE_SOON → normal notification (priority 0)
  CLOSE_NOW  → high priority (priority 1)
  EMERGENCY  → emergency, repeats every 30s until acknowledged (priority 2)

FAILURE POLICY (added 2026-08-17 — this file previously could not fail):
  A monitor that cannot assess a position must say so loudly. It must never
  report "all clear" because a lookup failed. Concretely:
    - missing credentials            → exit 1 before checking anything
    - trades read fails              → exit 1 (never "no open trades")
    - price lookup fails             → position is UNASSESSED → exit 1
    - ex-div lookup RAISES           → position is UNASSESSED → exit 1
      (an absent exDividendDate field on a non-payer is fine and is not an error;
       a failed lookup is not the same thing as "pays no dividend". Conflating
       the two silently downgrades EMERGENCY to SAFE — the $400K bug.)
    - Pushover delivery fails        → exit 1
  Exit 1 is what makes the workflow's `if: failure()` Discord step fire.
"""

import os
import sys
import json
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))

import cc_core   # stdlib-only; safe on the monitor's critical import path
import yf_proxy
from position_monitor import assess_position
from trade_schema import parse_trade_row, TradeRowError

ET = ZoneInfo("America/New_York")

# H19 / Experiment 017 — shadow mode. This records what a refined EMERGENCY rule
# WOULD have done so Charles can review real verdicts before deciding whether to
# loosen the $400K alert. It is research instrumentation bolted onto a
# safety-critical job, so it is isolated three ways:
#   1. imported lazily and non-fatally (scipy is not in this job's install set;
#      a hard `import bsm` at module scope took the whole monitor down)
#   2. every shadow computation runs inside _shadow_verdict()'s own try/except
#   3. the log write is separately guarded
# If any of that fails, the alert path continues exactly as if shadow mode did
# not exist.
_SHADOW_IMPORT_ERROR = None
try:
    import bsm
    from position_monitor import assess_position_shadow
except Exception as _e:            # pragma: no cover — depends on install set
    bsm = None
    assess_position_shadow = None
    _SHADOW_IMPORT_ERROR = f"{type(_e).__name__}: {_e}"

SHADOW_LOG = os.environ.get(
    "EMERGENCY_SHADOW_LOG",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "emergency_shadow.jsonl"),
)

# Alert delivery config. Pushover is the preferred channel (phone, priority-2
# repeats); Discord is an acceptable fallback. At least ONE must be configured.
PUSHOVER_TOKEN = os.environ.get("PUSHOVER_TOKEN", "")
PUSHOVER_USER = os.environ.get("PUSHOVER_USER", "")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")

# Supabase config
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# Local dry runs may skip the credential preflight; CI and cron never set this.
DRY_RUN = os.environ.get("MONITOR_DRY_RUN", "").strip().lower() in ("1", "true", "yes")


class MonitorError(RuntimeError):
    """A condition that makes the monitor's output untrustworthy."""


class Unassessable(Exception):
    """This one position cannot be evaluated.

    Raised rather than `continue`d so that every such path funnels through the
    single handler that records an UNASSESSED verdict. Three `continue`
    statements used to skip that handler, which meant a position dropping out of
    monitoring left its last good verdict on screen — a stale SAFE, displayed
    with full confidence.
    """


def epoch_to_date(ts):
    """Yahoo returns UTC-midnight epochs. Naive fromtimestamp() renders them in the
    host's local timezone, which shifts the date back a day on any US-timezone box —
    a one-day error against a three-day EMERGENCY window. Always interpret as UTC."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def preflight():
    """Refuse to run at all rather than run blind."""
    missing = [name for name, val in (
        ("SUPABASE_URL", SUPABASE_URL),
        ("SUPABASE_KEY", SUPABASE_KEY),
    ) if not val]
    if missing and not DRY_RUN:
        raise MonitorError(
            f"missing required credentials: {', '.join(missing)} — "
            "refusing to run a monitor that cannot read positions"
        )
    # Delivery gate: the invariant is "never run a monitor that cannot deliver
    # alerts" (a rotated token once silenced every EMERGENCY with a green run).
    # Pushover-specific was a proxy for that; the real requirement is at least
    # one working channel. Discord qualifies. Pushover absence stays LOUD in
    # every run's output and heartbeat until it is configured.
    has_pushover = bool(PUSHOVER_TOKEN and PUSHOVER_USER)
    has_discord = bool(DISCORD_WEBHOOK)
    if not (has_pushover or has_discord) and not DRY_RUN:
        raise MonitorError(
            "no alert delivery channel configured (need PUSHOVER_TOKEN+PUSHOVER_USER "
            "or DISCORD_WEBHOOK) — refusing to run a monitor that cannot deliver alerts"
        )
    if not has_pushover and not DRY_RUN:
        print("  [WARN] Pushover NOT configured — phone alerts (incl. EMERGENCY "
              "priority-2 repeats) cannot fire; delivering via Discord only")


def get_open_trades():
    """Fetch open trades from Supabase. Raises rather than returning [] on error —
    an empty list must mean 'there are genuinely no open positions'."""
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/trades?status=eq.open&select=*",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
            },
            timeout=15,
        )
    except Exception as e:
        raise MonitorError(f"trades read failed: {e}") from e

    if resp.status_code != 200:
        raise MonitorError(f"trades read returned {resp.status_code}: {resp.text[:200]}")
    return resp.json()


# ── Persistence: heartbeat + stored assessments ───────────────────────────────
#
# ENGINE_VERSION is stamped on every stored assessment. When the alert rules
# change, bump it — otherwise a verdict recorded under old thresholds is
# indistinguishable from one recorded under new thresholds, and the shadow-mode
# comparison in Week 2 has nothing to key on.
ENGINE = "position_monitor.py"
ENGINE_VERSION = "2026-08-18"

# Which copy of the monitor this is. The Hetzner cron is 'primary' and owns
# notifications; GitHub Actions runs as 'fallback' and stays silent unless the
# primary has gone quiet. Without this both would buzz Dad's phone for the same
# EMERGENCY, and duplicate alerts are how an alert channel gets muted.
SOURCE = os.environ.get("MONITOR_SOURCE", "unknown")
ROLE = os.environ.get("MONITOR_ROLE", "primary").strip().lower()

# How stale the primary's heartbeat must be before a fallback run takes over
# notifications. Two missed 15-minute cycles.
PRIMARY_STALE_MINUTES = int(os.environ.get("PRIMARY_STALE_MINUTES", "35"))


def _sb_headers(extra=None):
    h = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def _sb_insert(table, row, verify=True):
    """Insert one row and confirm the database actually returned it.

    `Prefer: return=representation` makes PostgREST echo the stored row, so a
    write that silently did nothing cannot be reported as a success. This is the
    same shape of bug as record_chain_snapshot's `except: pass` — a job printing
    a row count it never verified.
    """
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers=_sb_headers({"Prefer": "return=representation"}),
        json=row,
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise MonitorError(f"{table} insert returned {resp.status_code}: {resp.text[:300]}")
    if verify:
        data = resp.json()
        if not data:
            raise MonitorError(f"{table} insert returned no row — the write did not persist")
        return data[0]
    return None


def latest_heartbeat(role="primary"):
    """Newest heartbeat for a role, or None. Raises on a read failure — 'I could
    not check' must never be reported as 'the primary is fine'."""
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/monitor_heartbeats"
        f"?role=eq.{role}&order=ran_at.desc&limit=1&select=ran_at,ok",
        headers=_sb_headers(),
        timeout=15,
    )
    if resp.status_code != 200:
        raise MonitorError(
            f"heartbeat read returned {resp.status_code}: {resp.text[:200]}"
        )
    rows = resp.json()
    return rows[0] if rows else None


def primary_is_alive():
    """True when a healthy primary heartbeat is recent enough that this fallback
    run should not also notify. Any doubt resolves to False — a duplicate alert
    is annoying, a missing one is the $400K event."""
    try:
        hb = latest_heartbeat("primary")
    except MonitorError as e:
        print(f"  [fallback] cannot read primary heartbeat ({e}) — assuming primary is DOWN")
        return False
    if not hb or not hb.get("ok"):
        return False
    try:
        ran_at = datetime.fromisoformat(hb["ran_at"].replace("Z", "+00:00"))
    except Exception:
        return False
    age_min = (datetime.now(tz=timezone.utc) - ran_at).total_seconds() / 60
    print(f"  [fallback] primary heartbeat is {age_min:.0f} min old "
          f"(stale at {PRIMARY_STALE_MINUTES})")
    return age_min <= PRIMARY_STALE_MINUTES


def write_heartbeat(*, ok, checked, unassessed_n, alerts_n, undelivered_n, detail):
    """Record that this run happened. Written on EVERY exit path, including
    failures — the health check alarms on the absence of a heartbeat, so a run
    that dies without writing one is indistinguishable from a cron that never
    fired. That is the correct default, but it means the heartbeat itself must
    be the last thing to fail."""
    return _sb_insert("monitor_heartbeats", {
        "source": SOURCE,
        "role": ROLE,
        "engine": ENGINE,
        "engine_version": ENGINE_VERSION,
        "positions_checked": checked,
        "positions_unassessed": unassessed_n,
        "alerts_fired": alerts_n,
        "alerts_undelivered": undelivered_n,
        "ok": bool(ok),
        "detail": detail,
    })


def store_assessment(pos, alert, inputs, level=None, reason=None, action=None):
    """Persist one verdict so the web can display it instead of re-deriving it.

    Failing to store is a real failure: a UI reading stored assessments shows a
    stale verdict when this silently stops working, which is worse than showing
    nothing. The caller counts these and fails the run.
    """
    return _sb_insert("position_assessments", {
        "trade_id": pos.id,
        "ticker": pos.ticker,
        "strike": pos.strike,
        "expiry": pos.expiry,
        "contracts": pos.contracts,
        "level": level or (alert.level if alert else "UNASSESSED"),
        "reason": reason if reason is not None else (alert.reason if alert else None),
        "action": action if action is not None else (alert.action if alert else None),
        "inputs": inputs,
        "engine": ENGINE,
        "engine_version": ENGINE_VERSION,
        "source": SOURCE,
    })


def send_pushover(title, message, priority=0, sound="pushover"):
    """Send a Pushover notification. Returns True on confirmed delivery, False otherwise.
    Callers must treat False as a failure — an undelivered EMERGENCY is an outage."""
    if not PUSHOVER_TOKEN or not PUSHOVER_USER:
        print(f"  [NO PUSHOVER] {title}: {message}")
        return False

    data = {
        "token": PUSHOVER_TOKEN,
        "user": PUSHOVER_USER,
        "title": title,
        "message": message,
        "priority": priority,
        "sound": sound,
    }

    # Emergency priority requires retry/expire params
    if priority == 2:
        data["retry"] = 30    # repeat every 30 seconds
        data["expire"] = 300  # stop after 5 minutes

    try:
        resp = requests.post("https://api.pushover.net/1/messages.json", data=data, timeout=10)
        if resp.status_code == 200:
            print(f"  [SENT] {title}")
            return True
        print(f"  [FAILED] {resp.status_code}: {resp.text[:100]}")
        return False
    except Exception as e:
        print(f"  [ERROR] {e}")
        return False


def send_discord(title, message, priority=0):
    """Deliver an alert via the Discord webhook. Returns True on confirmed delivery.
    The fallback channel when Pushover is unconfigured — same loud-failure contract."""
    if not DISCORD_WEBHOOK:
        print(f"  [NO DISCORD] {title}: {message}")
        return False
    prefix = "🚨🚨 " if priority == 2 else ("🚨 " if priority >= 1 else "")
    try:
        resp = requests.post(DISCORD_WEBHOOK, json={
            "content": f"{prefix}**{title}**\n{message}"
            + ("\n(Pushover not configured — phone alert did NOT fire)" if not (PUSHOVER_TOKEN and PUSHOVER_USER) else ""),
        }, timeout=10)
        if resp.status_code in (200, 204):
            print(f"  [SENT discord] {title}")
            return True
        print(f"  [FAILED discord] {resp.status_code}: {resp.text[:100]}")
        return False
    except Exception as e:
        print(f"  [ERROR discord] {e}")
        return False


def send_alert(title=None, message=None, priority=0, sound="pushover", **kw):
    """Deliver via every configured channel. True if AT LEAST ONE confirmed delivery.
    Pushover (phone) is primary; Discord is fallback/secondary. An alert that reaches
    no channel is an outage and callers must treat False accordingly."""
    delivered = False
    if PUSHOVER_TOKEN and PUSHOVER_USER:
        delivered = send_pushover(title=title, message=message, priority=priority, sound=sound) or delivered
    if DISCORD_WEBHOOK and (not delivered or priority >= 2):
        # Discord always mirrors EMERGENCY even when Pushover delivered.
        delivered = send_discord(title, message, priority) or delivered
    if not delivered:
        print(f"  [UNDELIVERED] {title}: no channel confirmed delivery")
    return delivered


def log_shadow(record):
    """Append one H19 shadow verdict. Never allowed to break the live monitor."""
    try:
        with open(SHADOW_LOG, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as e:
        # Deliberately non-fatal: a research log must never take down the alert
        # path. But it is printed, not swallowed (tasks/lessons.md 2026-08-15).
        print(f"  [shadow-log FAILED] {type(e).__name__}: {e}")


def _shadow_verdict(now, ticker, strike, expiration, premium, contracts,
                    spot, opt_ask, ex_div_str, earn_str, div_yield, alert):
    """Compute and log the H19 shadow verdict. Returns nothing; raises nothing.

    Every statement that exists only for research lives in here. `alert` is the
    already-computed LIVE alert and is never modified — if anything in this
    function goes wrong the caller still has it.
    """
    if assess_position_shadow is None:
        return
    try:
        # The dividend AMOUNT is not in the proxy feed — only an annual yield —
        # so the full annual dividend is used as an upper bound on any single
        # payment. Over-stating the dividend makes the refined rule fire MORE
        # often, which is the safe direction. A real per-payment dividend
        # calendar (Week 1 item 5) would let the rule be tighter. Semi-annual
        # payers like DIS are why annual/4 was not used.
        div_amount = None
        if div_yield is not None:
            try:
                div_amount = float(spot) * float(div_yield)
            except (TypeError, ValueError):
                div_amount = None

        dte_est = None
        try:
            exp_dt = datetime.strptime(str(expiration)[:10], "%Y-%m-%d")
            # `now` is timezone-aware ET; naive - aware raises, which the except
            # below would swallow into dte_est=None and silently disable delta.
            if now.tzinfo is not None:
                exp_dt = exp_dt.replace(tzinfo=now.tzinfo)
            dte_est = max(0, (exp_dt - now).days)
        except Exception:
            pass

        delta_est = None
        if opt_ask and dte_est is not None and bsm is not None:
            delta_est = bsm.delta_from_price(opt_ask, spot, strike, dte_est)

        _, shadow = assess_position_shadow(
            ticker=ticker, strike=strike, expiry=expiration,
            sold_price=premium, contracts=contracts,
            current_stock=spot, current_option_ask=opt_ask,
            ex_div_date=ex_div_str, earnings_date=earn_str,
            dividend_amount=div_amount, delta=delta_est,
        )

        if shadow["current_rule_fires"] or shadow["refined_rule_fires"]:
            log_shadow({
                "logged_at": now.isoformat(), "ticker": ticker,
                "strike": strike, "expiration": str(expiration)[:10],
                "spot": round(spot, 2), "option_ask": opt_ask,
                "dte": dte_est, "days_to_exdiv": alert.days_to_exdiv,
                "dividend_source": "annual_yield_upper_bound",
                "live_level": alert.level, **shadow,
            })
            print(f"[shadow:{shadow['disposition']}] ", end="")
    except Exception as e:
        print(f"  [shadow FAILED, live alert unaffected] {type(e).__name__}: {e}")


def main():
    """Run the monitor and guarantee a heartbeat row either way.

    The heartbeat is the positive signal the dead-man's switch watches. Its
    ABSENCE is the alarm, so it has to be written on the failure path too —
    otherwise a monitor that crashes looks identical to a cron that never fired,
    and the health check cannot tell you which. On the success path a failed
    heartbeat write fails the run: silently skipping it would leave the health
    check alarming with no explanation.
    """
    stats = {"checked": 0, "unassessed": 0, "alerts": 0, "undelivered": 0, "detail": {}}
    try:
        _run(stats)
    except BaseException as e:
        stats["detail"]["error"] = f"{type(e).__name__}: {e}"
        try:
            write_heartbeat(
                ok=False, checked=stats["checked"], unassessed_n=stats["unassessed"],
                alerts_n=stats["alerts"], undelivered_n=stats["undelivered"],
                detail=stats["detail"],
            )
            print("  [heartbeat] recorded FAILED run")
        except Exception as hb:
            # Never let the heartbeat write hide the real failure.
            print(f"  [heartbeat] could not record failed run: {hb}")
        raise

    write_heartbeat(
        ok=True, checked=stats["checked"], unassessed_n=stats["unassessed"],
        alerts_n=stats["alerts"], undelivered_n=stats["undelivered"],
        detail=stats["detail"],
    )
    print(f"  [heartbeat] recorded OK run ({SOURCE}/{ROLE})")


def _run(stats):
    now = datetime.now(tz=ET)
    print(f"Position Monitor — {now.strftime('%Y-%m-%d %H:%M %Z')} [{SOURCE}/{ROLE}]")
    print("=" * 60)

    preflight()

    # A fallback run assesses and stores exactly like the primary, but stays
    # silent while the primary is healthy. Two monitors both notifying would put
    # every EMERGENCY on Dad's phone twice, and an alert channel that cries twice
    # is an alert channel that gets muted.
    notify_enabled = True
    if ROLE == "fallback":
        notify_enabled = not primary_is_alive()
        stats["detail"]["notifications_suppressed"] = not notify_enabled
        print("Notifications: " + ("TAKING OVER — primary is silent" if notify_enabled
                                   else "suppressed (primary is alive)"))

    if _SHADOW_IMPORT_ERROR:
        print(f"[shadow disabled — {_SHADOW_IMPORT_ERROR}] "
              "Live alerts are unaffected.")

    trades = get_open_trades()
    if not trades:
        print("No open trades. (Trades read succeeded and returned zero rows.)")
        stats["detail"]["note"] = "no open positions"
        return

    print(f"Checking {len(trades)} open positions...")

    alerts_to_send = []
    summary = {"SAFE": 0, "WATCH": 0, "CLOSE_SOON": 0, "CLOSE_NOW": 0, "EMERGENCY": 0}
    unassessed = []      # positions we could not evaluate — each one is a failure
    degraded = []        # assessed, but with a non-critical input missing
    store_failures = []  # verdicts computed but not persisted — the UI would go stale

    for trade in trades:
        # Field names come from trade_schema, which is the single description of
        # what `public.trades` actually contains. Reading them inline with
        # .get(col, default) is what let this file spend months pointed at
        # `expiration`/`premium_received` — columns this table has never had —
        # while the default values made every row look assessable.
        try:
            pos = parse_trade_row(trade)
        except TradeRowError as e:
            print(f"\n  UNREADABLE ROW — {e}")
            unassessed.append(f"trades row {trade.get('id', '?')}: {e}")
            continue

        ticker = pos.ticker
        strike = pos.strike
        expiration = pos.expiry
        premium = pos.sold_price
        contracts = pos.contracts
        label = pos.label

        print(f"\n  {ticker} ${strike} Call (exp {expiration})...", end=" ")

        try:
            # Get current stock price — no price, no assessment. Never skip silently.
            hist = yf_proxy.get_stock_history(ticker, period="5d")
            if hist.empty:
                print("NO PRICE DATA — position unassessed")
                raise Unassessable("no price data")
            spot = float(hist["Close"].iloc[-1])

            # Get current option price. Only affects the cost-to-close figure shown
            # in the alert body, not the alert level — so this one degrades, not fails.
            opt_ask = None
            try:
                chain = yf_proxy.get_option_chain(ticker, expiration)
                if chain and hasattr(chain, 'calls') and not chain.calls.empty:
                    match = chain.calls[chain.calls["strike"] == strike]
                    if not match.empty:
                        bid = match.iloc[0].get("bid", 0) or 0
                        ask = match.iloc[0].get("ask", 0) or 0
                        opt_ask = (bid + ask) / 2 if bid > 0 else float(match.iloc[0].get("lastPrice", 0))
            except Exception as e:
                degraded.append(f"{label}: option quote unavailable ({e})")

            # Get ex-div / earnings dates. A FAILED LOOKUP IS NOT "NO DIVIDEND".
            # If this raises we cannot rule out an imminent ex-div, so the position
            # is unassessable and the run fails. Only a successful lookup that
            # simply has no exDividendDate (a non-payer) yields a legitimate None.
            try:
                info = yf_proxy.get_stock_info(ticker)
            except Exception as e:
                print(f"EX-DIV LOOKUP FAILED — position unassessed ({e})")
                raise Unassessable(f"ex-div lookup failed ({e})") from e
            if info is None:
                print("EX-DIV LOOKUP RETURNED NOTHING — position unassessed")
                raise Unassessable("ex-div lookup returned no data")

            # The deployed worker returns exDividendDate as a STRING
            # ('2026-08-10') and earningsDate as a list of strings; the old
            # isinstance(int, float) guard parsed both to None on every lookup,
            # which made EMERGENCY and every ex-div/earnings clause silently
            # unreachable against the live proxy (probed 2026-08-21).
            # cc_core.parse_market_date accepts epoch, ISO string, and date.
            div_yield = info.get("dividendYield")   # H19 shadow mode input
            ex_div_str = cc_core.parse_market_date(info.get("exDividendDate"))
            earn_ts = info.get("earningsDate")
            if isinstance(earn_ts, (list, tuple)):
                earn_ts = earn_ts[0] if earn_ts else None
            earn_str = cc_core.parse_market_date(earn_ts)

            # Run copilot — the LIVE path, unchanged from before shadow mode.
            alert = assess_position(
                ticker=ticker, strike=strike, expiry=expiration,
                sold_price=premium, contracts=contracts,
                current_stock=spot, current_option_ask=opt_ask,
                ex_div_date=ex_div_str, earnings_date=earn_str,
            )

            # Research only. Cannot raise, cannot alter `alert`.
            _shadow_verdict(now, ticker, strike, expiration, premium, contracts,
                            spot, opt_ask, ex_div_str, earn_str, div_yield, alert)

            level = alert.level
            summary[level] = summary.get(level, 0) + 1
            print(f"{level} (stock ${spot:.2f}, {alert.pct_from_strike:+.1f}% from strike)")

            # Persist the verdict with every input it was computed from. The web
            # reads these rows rather than recomputing in TypeScript, so the
            # screen and the phone cannot drift. Without the inputs a stored
            # SAFE is unauditable — you cannot tell a correct one from one
            # produced by a stale quote.
            try:
                store_assessment(pos, alert, {
                    "spot": round(spot, 4),
                    "option_ask": opt_ask,
                    "ex_div_date": ex_div_str,
                    "earnings_date": earn_str,
                    "dte": alert.dte,
                    "pct_from_strike": round(alert.pct_from_strike, 4),
                    "assessed_at_et": now.isoformat(),
                })
            except Exception as e:
                # A verdict that did not persist is a verdict the UI will not
                # show — it would keep displaying the previous one. Loud.
                print(f"  [assessment NOT STORED] {e}")
                store_failures.append(f"{label}: {e}")

            # Determine notification
            if level == "EMERGENCY":
                alerts_to_send.append({
                    "title": f"🚨 EMERGENCY: {ticker} ${strike} Call",
                    "message": f"{alert.reason}\n\n{alert.action}",
                    "priority": 2,
                    "sound": "siren",
                })
            elif level == "CLOSE_NOW":
                alerts_to_send.append({
                    "title": f"🔴 CLOSE NOW: {ticker} ${strike} Call",
                    "message": f"{alert.reason}\n\n{alert.action}",
                    "priority": 1,
                    "sound": "persistent",
                })
            elif level == "CLOSE_SOON":
                alerts_to_send.append({
                    "title": f"🟠 Close Soon: {ticker} ${strike} Call",
                    "message": f"{alert.reason}\n\n{alert.action}",
                    "priority": 0,
                    "sound": "pushover",
                })

        except Exception as e:
            if not isinstance(e, Unassessable):
                print(f"ERROR: {e}")
            unassessed.append(f"{label}: {e}")
            # Record the UNASSESSED verdict too. If we store nothing, the web
            # keeps rendering the last good assessment for this position with
            # full confidence — the exact failure mode stored verdicts create.
            try:
                store_assessment(pos, None, {"error": str(e)},
                                 level="UNASSESSED", reason=str(e),
                                 action="Do not rely on this position's status — the monitor could not evaluate it.")
            except Exception as se:
                print(f"  [UNASSESSED marker NOT STORED] {se}")
                store_failures.append(f"{label}: unassessed marker: {se}")

    # Send alerts
    print(f"\n{'=' * 60}")
    print(f"Summary: {summary}")
    print(f"Assessed: {sum(summary.values())}/{len(trades)} positions")
    print(f"Alerts to send: {len(alerts_to_send)}")

    delivery_failures = []
    if not notify_enabled:
        # Suppressed, not skipped: the verdicts are already stored, and the count
        # is recorded so a fallback run that stayed quiet is still auditable.
        print(f"  {len(alerts_to_send)} alert(s) NOT sent — primary owns notifications")
        stats["detail"]["alerts_suppressed"] = [a["title"] for a in alerts_to_send]
    else:
        for alert in alerts_to_send:
            if not send_alert(**alert):
                delivery_failures.append(f"{alert['priority']}: {alert['title']}")

    # Daily summary at 4 PM ET. `now` is timezone-aware ET — the previous naive
    # datetime.now() ran as UTC on the GitHub runner, firing this at 11 AM ET.
    hour = now.hour
    if notify_enabled and 15 <= hour <= 16:
        total = sum(summary.values())
        urgent = summary.get("CLOSE_NOW", 0) + summary.get("EMERGENCY", 0)
        if urgent > 0:
            send_alert(
                title="Daily Summary — Action Needed",
                message=f"{total} positions: {urgent} need immediate action, {summary.get('SAFE', 0)} safe.",
                priority=0,
            )
        elif total > 0:
            send_alert(
                title="Daily Summary — All Clear",
                message=f"{total} positions, all safe. No action needed.",
                priority=-1,  # lowest priority, no sound
                sound="none",
            )

    # A run that could not assess every position did NOT produce an all-clear.
    # Tell the human, then fail so the workflow's `if: failure()` Discord step fires.
    if degraded:
        print(f"\nDEGRADED ({len(degraded)}):")
        for d in degraded:
            print(f"  - {d}")

    stats["checked"] = sum(summary.values())
    stats["unassessed"] = len(unassessed)
    stats["alerts"] = len(alerts_to_send)
    stats["undelivered"] = len(delivery_failures)
    stats["detail"]["summary"] = summary
    stats["detail"]["open_positions"] = len(trades)
    if degraded:
        stats["detail"]["degraded"] = degraded[:10]
    if unassessed:
        stats["detail"]["unassessed"] = unassessed[:10]
    if store_failures:
        stats["detail"]["store_failures"] = store_failures[:10]

    if unassessed or delivery_failures or store_failures:
        print(f"\nFAILURES ({len(unassessed)} unassessed, "
              f"{len(delivery_failures)} undelivered, {len(store_failures)} unstored):")
        for f in unassessed + delivery_failures + store_failures:
            print(f"  - {f}")

        detail = "\n".join(f"• {f}" for f in (unassessed + delivery_failures + store_failures)[:6])
        if notify_enabled:
            send_alert(
                title=f"⚠️ Monitor DEGRADED — {len(unassessed)} position(s) unchecked",
                message=(
                    f"{len(unassessed)} of {len(trades)} positions could not be assessed. "
                    f"Their alert level is UNKNOWN, not safe.\n\n{detail}"
                ),
                priority=1,
                sound="persistent",
            )
        raise MonitorError(
            f"{len(unassessed)} position(s) unassessed, "
            f"{len(delivery_failures)} alert(s) undelivered, "
            f"{len(store_failures)} verdict(s) not persisted"
        )


if __name__ == "__main__":
    try:
        main()
    except MonitorError as e:
        print(f"\nFATAL: {e}")
        sys.exit(1)
