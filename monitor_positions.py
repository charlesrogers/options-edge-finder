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
"""

import os
import sys
import json
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

import yf_proxy
from position_monitor import assess_position

# Pushover config
PUSHOVER_TOKEN = os.environ.get("PUSHOVER_TOKEN", "")
PUSHOVER_USER = os.environ.get("PUSHOVER_USER", "")

# Supabase config
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")


def get_open_trades():
    """Fetch open trades from Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("No Supabase credentials — skipping")
        return []

    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/trades?status=eq.open&select=*",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
        },
        timeout=15,
    )
    if resp.status_code == 200:
        return resp.json()
    print(f"Supabase error: {resp.status_code} {resp.text[:100]}")
    return []


def send_pushover(title, message, priority=0, sound="pushover"):
    """Send a Pushover notification."""
    if not PUSHOVER_TOKEN or not PUSHOVER_USER:
        print(f"  [NO PUSHOVER] {title}: {message}")
        return

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
        else:
            print(f"  [FAILED] {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        print(f"  [ERROR] {e}")


def main():
    now = datetime.now()
    print(f"Position Monitor — {now.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    trades = get_open_trades()
    if not trades:
        print("No open trades.")
        return

    print(f"Checking {len(trades)} open positions...")

    alerts_to_send = []
    summary = {"SAFE": 0, "WATCH": 0, "CLOSE_SOON": 0, "CLOSE_NOW": 0, "EMERGENCY": 0}

    for trade in trades:
        ticker = trade.get("ticker", "")
        strike = trade.get("strike", 0)
        expiration = trade.get("expiration", "")
        premium = trade.get("premium_received", 0)
        contracts = trade.get("contracts", 1)

        print(f"\n  {ticker} ${strike} Call (exp {expiration})...", end=" ")

        try:
            # Get current stock price
            hist = yf_proxy.get_stock_history(ticker, period="5d")
            if hist.empty:
                print("no price data")
                continue
            spot = float(hist["Close"].iloc[-1])

            # Get current option price
            opt_ask = None
            try:
                chain = yf_proxy.get_option_chain(ticker, expiration)
                if chain and hasattr(chain, 'calls') and not chain.calls.empty:
                    match = chain.calls[chain.calls["strike"] == strike]
                    if not match.empty:
                        bid = match.iloc[0].get("bid", 0) or 0
                        ask = match.iloc[0].get("ask", 0) or 0
                        opt_ask = (bid + ask) / 2 if bid > 0 else float(match.iloc[0].get("lastPrice", 0))
            except Exception:
                pass

            # Get ex-div date
            ex_div_str = None
            earn_str = None
            try:
                info = yf_proxy.get_stock_info(ticker)
                ex_div_ts = info.get("exDividendDate")
                if ex_div_ts and isinstance(ex_div_ts, (int, float)):
                    ex_div_str = datetime.fromtimestamp(ex_div_ts).strftime("%Y-%m-%d")
                earn_ts = info.get("earningsDate")
                if earn_ts:
                    if isinstance(earn_ts, (list, tuple)):
                        earn_ts = earn_ts[0]
                    if isinstance(earn_ts, (int, float)):
                        earn_str = datetime.fromtimestamp(earn_ts).strftime("%Y-%m-%d")
            except Exception:
                pass

            # Run copilot
            alert = assess_position(
                ticker=ticker, strike=strike, expiry=expiration,
                sold_price=premium, contracts=contracts,
                current_stock=spot, current_option_ask=opt_ask,
                ex_div_date=ex_div_str, earnings_date=earn_str,
            )

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

    # Send alerts
    print(f"\n{'=' * 60}")
    print(f"Summary: {summary}")
    print(f"Alerts to send: {len(alerts_to_send)}")

    for alert in alerts_to_send:
        send_pushover(**alert)

    # Daily summary at 4 PM
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


if __name__ == "__main__":
    main()
