"""
Paper Trade Logger — CLV tracking for covered call recommendations.

Runs daily at 4 PM ET. For each ticker in TICKER_STRATEGIES (excluding skips):
1. Fetch current stock price + option chain
2. Find the recommended call (per-ticker optimal OTM%, target DTE)
3. Log to paper_trades table

This runs automatically — even if Dad never opens the app.
Every recommendation is tracked and scored 30 days later.
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

import yf_proxy
from ticker_strategies import TICKER_STRATEGIES
from db import log_paper_trade


def find_recommended_call(ticker, current_price, otm_pct, min_dte, max_dte):
    """Find the call option matching the recommended strategy."""
    expirations = yf_proxy.get_expirations(ticker)
    if not expirations:
        return None

    target_strike = current_price * (1 + otm_pct)
    best = None

    for exp in expirations:
        try:
            exp_date = datetime.strptime(exp, "%Y-%m-%d")
            dte = (exp_date - datetime.now()).days
            if dte < min_dte or dte > max_dte:
                continue
        except Exception:
            continue

        chain = yf_proxy.get_option_chain(ticker, exp)
        if not chain or not hasattr(chain, 'calls') or chain.calls.empty:
            continue

        calls = chain.calls[chain.calls["strike"] > 0].copy()
        if calls.empty:
            continue

        calls["dist"] = abs(calls["strike"] - target_strike)
        row = calls.loc[calls["dist"].idxmin()]

        strike = float(row["strike"])
        bid = row.get("bid", 0) or 0
        ask = row.get("ask", 0) or 0
        premium = round((bid + ask) / 2, 2) if bid > 0 else float(row.get("lastPrice", 0))

        if premium <= 0:
            continue

        actual_otm = (strike - current_price) / current_price * 100

        if best is None or abs(dte - 30) < abs(best["dte"] - 30):
            best = {
                "strike": strike,
                "premium": premium,
                "dte": dte,
                "otm_pct": actual_otm,
                "expiration": exp,
            }

    return best


def main():
    print("=" * 60)
    print(f"Paper Trade Logger — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    logged = 0
    skipped = 0

    for ticker, strat in TICKER_STRATEGIES.items():
        if strat.get("skip") or strat.get("otm_pct") is None:
            print(f"  SKIP {ticker}: {strat.get('note', 'skipped')}")
            skipped += 1
            continue

        print(f"  {ticker}...", end=" ", flush=True)

        try:
            # Get current price
            hist = yf_proxy.get_stock_history(ticker, period="5d")
            if hist.empty:
                print("no price data")
                continue
            current_price = float(hist["Close"].iloc[-1])

            # Get IV rank from stock info
            info = yf_proxy.get_stock_info(ticker)
            iv_rank = None  # TODO: fetch from iv_snapshots table

            # Find recommended call
            call = find_recommended_call(
                ticker, current_price,
                strat["otm_pct"], strat.get("min_dte", 20), strat.get("max_dte", 45)
            )

            if not call:
                print(f"no suitable call found (${current_price:.0f})")
                continue

            # Log paper trade
            log_paper_trade(
                ticker=ticker,
                strike=call["strike"],
                premium=call["premium"],
                otm_pct=call["otm_pct"],
                dte=call["dte"],
                expiration=call["expiration"],
                iv_rank=iv_rank,
                tier=strat["tier"],
                strategy_params={
                    "target_otm": strat["otm_pct"],
                    "expected_pnl": strat.get("expected_pnl"),
                    "expected_win_rate": strat.get("expected_win_rate"),
                },
            )

            print(f"${call['strike']:.0f} Call @ ${call['premium']:.2f} "
                  f"({call['otm_pct']:.1f}% OTM, {call['dte']} DTE)")
            logged += 1

        except Exception as e:
            print(f"ERROR: {e}")

    print(f"\nLogged {logged} paper trades, skipped {skipped}")


if __name__ == "__main__":
    main()
