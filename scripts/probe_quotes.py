"""§0.5 probe — what a live decision-moment quote actually looks like.

Written for the paper-engine spec's §0 verification. It answers three questions
the engine's design depends on:

  1. What fields does the proxy return for the production strike, and are
     bid/ask actually populated on the thin names?
  2. What does a PROXY FAILURE look like? `yf_proxy._get` swallows every
     RequestException and returns `{}` — so an empty chain and a dead proxy are
     indistinguishable unless the caller checks explicitly. The engine must
     never treat silent-empty as data (spec §5.4).
  3. How wide is the spread at the strike we would actually sell?

Read-only. Costs nothing. Run: python3 scripts/probe_quotes.py [TICKER ...]
"""
import os
import sys
import json
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yf_proxy
import ticker_strategies


def _f(v):
    """Best-effort float; None for anything unusable."""
    try:
        x = float(v)
        return None if x != x else x
    except (TypeError, ValueError):
        return None


def probe(ticker):
    cfg = ticker_strategies.get_strategy(ticker) or {}
    otm = cfg.get("otm_pct", 0.15)
    min_dte, max_dte = cfg.get("min_dte", 20), cfg.get("max_dte", 45)

    out = {"ticker": ticker, "otm_pct": otm, "dte_band": [min_dte, max_dte]}

    exps = yf_proxy.get_expirations(ticker)
    if not exps:
        out["error"] = "no expirations returned (proxy failure or empty — INDISTINGUISHABLE)"
        return out

    today = datetime.now(timezone.utc).date()
    banded = []
    for e in exps:
        try:
            dte = (datetime.strptime(e, "%Y-%m-%d").date() - today).days
        except ValueError:
            continue
        if min_dte <= dte <= max_dte:
            banded.append((abs(dte - 30), dte, e))
    if not banded:
        out["error"] = f"no expiry in DTE band {min_dte}-{max_dte}; available={exps[:6]}"
        return out
    _, dte, expiry = sorted(banded)[0]
    out["expiry"], out["dte"] = expiry, dte

    chain = yf_proxy.get_option_chain(ticker, expiry)
    spot = _f(chain.underlying_price)
    out["spot"] = spot
    calls = chain.calls
    if spot is None or calls is None or calls.empty:
        out["error"] = "empty chain or no underlying price (proxy failure or empty)"
        return out

    target = spot * (1 + otm)
    row = calls.iloc[(calls["strike"].astype(float) - target).abs().argmin()]
    bid, ask = _f(row.get("bid")), _f(row.get("ask"))
    out["contract"] = {
        "symbol": row.get("contractSymbol"),
        "strike": _f(row.get("strike")),
        "target_strike": round(target, 2),
        "bid": bid,
        "ask": ask,
        "last": _f(row.get("lastPrice")),
        "volume": _f(row.get("volume")),
        "openInterest": _f(row.get("openInterest")),
        "impliedVolatility": _f(row.get("impliedVolatility")),
    }
    if bid is not None and ask is not None and ask > 0:
        out["contract"]["spread"] = round(ask - bid, 4)
        out["contract"]["spread_pct_of_bid"] = (
            round((ask - bid) / bid * 100, 1) if bid > 0 else None
        )
    # The entry liquidity floor of spec §5.2, evaluated against this quote.
    out["entry_floor"] = {
        "bid_ge_0.05": bid is not None and bid >= 0.05,
        "not_crossed": bid is not None and ask is not None and bid <= ask,
        "would_enter": (bid is not None and ask is not None
                        and bid >= 0.05 and bid <= ask),
    }
    return out


def probe_failure_shape():
    """Demonstrate what a dead proxy returns, so the engine can tell it apart."""
    real = yf_proxy.PROXY_URL
    try:
        yf_proxy.PROXY_URL = "https://invalid.invalid.example"
        data = yf_proxy._get("/stock/AAPL/options")
        return {
            "returned": repr(data),
            "type": type(data).__name__,
            "is_falsy_empty_dict": data == {},
            "verdict": ("A proxy failure returns {} — identical to an empty chain. "
                        "The engine MUST probe explicitly and never infer 'no data' "
                        "from an empty dict."),
        }
    finally:
        yf_proxy.PROXY_URL = real


def main():
    tickers = sys.argv[1:] or ["KKR", "AAPL"]
    report = {"probed_at_utc": datetime.now(timezone.utc).isoformat(),
              "tickers": [], "proxy_failure_shape": None}
    for i, t in enumerate(tickers, 1):
        print(f"\n=== [{i}/{len(tickers)}] {t} ===", flush=True)
        r = probe(t)
        report["tickers"].append(r)
        print(json.dumps(r, indent=2), flush=True)
    print("\n=== proxy failure shape ===", flush=True)
    report["proxy_failure_shape"] = probe_failure_shape()
    print(json.dumps(report["proxy_failure_shape"], indent=2), flush=True)
    return report


if __name__ == "__main__":
    main()
