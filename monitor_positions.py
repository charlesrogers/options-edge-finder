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

import yf_proxy
from position_monitor import assess_position

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

# Pushover config
PUSHOVER_TOKEN = os.environ.get("PUSHOVER_TOKEN", "")
PUSHOVER_USER = os.environ.get("PUSHOVER_USER", "")

# Supabase config
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# Local dry runs may skip the credential preflight; CI and cron never set this.
DRY_RUN = os.environ.get("MONITOR_DRY_RUN", "").strip().lower() in ("1", "true", "yes")


class MonitorError(RuntimeError):
    """A condition that makes the monitor's output untrustworthy."""


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
        ("PUSHOVER_TOKEN", PUSHOVER_TOKEN),
        ("PUSHOVER_USER", PUSHOVER_USER),
    ) if not val]
    if missing and not DRY_RUN:
        # Missing Pushover creds are as fatal as missing DB creds: the previous
        # version printed "[NO PUSHOVER]" and exited 0, so a rotated token would
        # have silenced every EMERGENCY alert with a green run.
        raise MonitorError(
            f"missing required credentials: {', '.join(missing)} — "
            "refusing to run a monitor that cannot read positions or deliver alerts"
        )


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
    now = datetime.now(tz=ET)
    print(f"Position Monitor — {now.strftime('%Y-%m-%d %H:%M %Z')}")
    print("=" * 60)

    preflight()

    if _SHADOW_IMPORT_ERROR:
        print(f"[shadow disabled — {_SHADOW_IMPORT_ERROR}] "
              "Live alerts are unaffected.")

    trades = get_open_trades()
    if not trades:
        print("No open trades. (Trades read succeeded and returned zero rows.)")
        return

    print(f"Checking {len(trades)} open positions...")

    alerts_to_send = []
    summary = {"SAFE": 0, "WATCH": 0, "CLOSE_SOON": 0, "CLOSE_NOW": 0, "EMERGENCY": 0}
    unassessed = []   # positions we could not evaluate — each one is a failure
    degraded = []     # assessed, but with a non-critical input missing

    for trade in trades:
        ticker = trade.get("ticker", "")
        strike = trade.get("strike", 0)
        expiration = trade.get("expiration", "")
        premium = trade.get("premium_received", 0)
        contracts = trade.get("contracts", 1)

        print(f"\n  {ticker} ${strike} Call (exp {expiration})...", end=" ")

        label = f"{ticker} ${strike} exp {expiration}"

        try:
            # Get current stock price — no price, no assessment. Never skip silently.
            hist = yf_proxy.get_stock_history(ticker, period="5d")
            if hist.empty:
                print("NO PRICE DATA — position unassessed")
                unassessed.append(f"{label}: no price data")
                continue
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
                unassessed.append(f"{label}: ex-div lookup failed ({e})")
                continue
            if info is None:
                print("EX-DIV LOOKUP RETURNED NOTHING — position unassessed")
                unassessed.append(f"{label}: ex-div lookup returned no data")
                continue

            ex_div_str = None
            earn_str = None
            div_yield = info.get("dividendYield")   # H19 shadow mode input
            ex_div_ts = info.get("exDividendDate")
            if ex_div_ts and isinstance(ex_div_ts, (int, float)):
                ex_div_str = epoch_to_date(ex_div_ts)
            earn_ts = info.get("earningsDate")
            if earn_ts:
                if isinstance(earn_ts, (list, tuple)):
                    earn_ts = earn_ts[0] if earn_ts else None
                if isinstance(earn_ts, (int, float)):
                    earn_str = epoch_to_date(earn_ts)

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
            print(f"ERROR: {e}")
            unassessed.append(f"{label}: {e}")

    # Send alerts
    print(f"\n{'=' * 60}")
    print(f"Summary: {summary}")
    print(f"Assessed: {sum(summary.values())}/{len(trades)} positions")
    print(f"Alerts to send: {len(alerts_to_send)}")

    delivery_failures = []
    for alert in alerts_to_send:
        if not send_pushover(**alert):
            delivery_failures.append(f"{alert['priority']}: {alert['title']}")

    # Daily summary at 4 PM ET. `now` is timezone-aware ET — the previous naive
    # datetime.now() ran as UTC on the GitHub runner, firing this at 11 AM ET.
    hour = now.hour
    if 15 <= hour <= 16:
        total = sum(summary.values())
        urgent = summary.get("CLOSE_NOW", 0) + summary.get("EMERGENCY", 0)
        if urgent > 0:
            send_pushover(
                title="Daily Summary — Action Needed",
                message=f"{total} positions: {urgent} need immediate action, {summary.get('SAFE', 0)} safe.",
                priority=0,
            )
        elif total > 0:
            send_pushover(
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

    if unassessed or delivery_failures:
        print(f"\nFAILURES ({len(unassessed)} unassessed, {len(delivery_failures)} undelivered):")
        for f in unassessed + delivery_failures:
            print(f"  - {f}")

        detail = "\n".join(f"• {f}" for f in (unassessed + delivery_failures)[:6])
        send_pushover(
            title=f"⚠️ Monitor DEGRADED — {len(unassessed)} position(s) unchecked",
            message=(
                f"{len(unassessed)} of {len(trades)} positions could not be assessed. "
                f"Their alert level is UNKNOWN, not safe.\n\n{detail}"
            ),
            priority=1,
            sound="persistent",
        )
        raise MonitorError(
            f"{len(unassessed)} position(s) unassessed, {len(delivery_failures)} alert(s) undelivered"
        )


if __name__ == "__main__":
    try:
        main()
    except MonitorError as e:
        print(f"\nFATAL: {e}")
        sys.exit(1)
