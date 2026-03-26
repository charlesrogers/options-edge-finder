"""
Backfill Paper Trades — Generate historical recommendations from model start.

Uses real stock prices + BSM-estimated option premiums to simulate what the
paper trade logger WOULD have recommended each day since inception.

All backfilled trades are flagged with strategy_params.backfilled = true.
"""

import os
import sys
import math
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pandas as pd
from scipy.stats import norm

import yf_proxy
from ticker_strategies import TICKER_STRATEGIES
from db import log_paper_trade


def bsm_call(S, K, T, r, sigma):
    """Black-Scholes call price."""
    if T <= 0 or sigma <= 0:
        return max(S - K, 0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)


def backfill_ticker(ticker, strat, stock_hist, start_date, interval_days=7):
    """Generate paper trades for one ticker going back to start_date."""
    otm_pct = strat['otm_pct']
    min_dte = strat.get('min_dte', 20)
    max_dte = strat.get('max_dte', 45)
    target_dte = (min_dte + max_dte) // 2

    # Compute rolling RV for BSM pricing
    returns = np.log(stock_hist['Close'] / stock_hist['Close'].shift(1)).dropna()
    rv_20 = returns.rolling(20).std() * np.sqrt(252)

    trades = []
    last_log = None

    for i in range(len(stock_hist)):
        date = stock_hist.index[i]
        date_str = str(date)[:10]

        if pd.Timestamp(date) < pd.Timestamp(start_date):
            continue

        # Log every interval_days (simulate monthly-ish recommendations)
        if last_log and (pd.Timestamp(date) - pd.Timestamp(last_log)).days < interval_days:
            continue

        if i >= len(rv_20) or pd.isna(rv_20.iloc[i]):
            continue

        spot = float(stock_hist['Close'].iloc[i])
        vol = float(rv_20.iloc[i]) * 1.2  # BSM IV estimate

        # Find recommended strike
        strike = round(spot * (1 + otm_pct), 0)
        T = target_dte / 252
        premium = bsm_call(spot, strike, T, 0.05, vol)

        if premium <= 0:
            continue

        actual_otm = (strike - spot) / spot * 100

        # Log it (with backfilled flag + historical date)
        log_paper_trade(
            ticker=ticker,
            strike=strike,
            premium=round(premium, 2),
            otm_pct=round(actual_otm, 2),
            dte=target_dte,
            expiration=(pd.Timestamp(date) + timedelta(days=target_dte)).strftime('%Y-%m-%d'),
            iv_rank=None,
            tier=strat['tier'],
            strategy_params={
                'target_otm': otm_pct,
                'expected_pnl': strat.get('expected_pnl'),
                'backfilled': True,
                'pricing': 'BSM (rv20*1.2)',
            },
            recommended_date=str(date)[:10],
        )

        trades.append({
            'date': date_str,
            'strike': strike,
            'premium': round(premium, 2),
            'otm_pct': round(actual_otm, 1),
        })
        last_log = date_str

    return trades


def main():
    print("=" * 60)
    print("Backfill Paper Trades")
    print("Generating historical recommendations since model start")
    print("=" * 60)

    # Start from as far back as stock data allows (1yr from Yahoo)
    start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    print(f"Backfilling from: {start_date}")
    print(f"Interval: every 7 days (weekly recommendations)\n")

    total = 0
    for ticker, strat in TICKER_STRATEGIES.items():
        if strat.get('skip') or strat.get('otm_pct') is None:
            print(f"  SKIP {ticker}")
            continue

        print(f"  {ticker} ({strat['tier']}, {strat['otm_pct']*100:.0f}% OTM)...", end=" ", flush=True)

        try:
            hist = yf_proxy.get_stock_history(ticker, period="1y")
            if hist.empty:
                print("no data")
                continue

            trades = backfill_ticker(ticker, strat, hist, start_date, interval_days=7)
            print(f"{len(trades)} paper trades")
            total += len(trades)

            # Show a few examples
            for t in trades[:2]:
                print(f"    {t['date']}: ${t['strike']:.0f} Call @ ${t['premium']:.2f} ({t['otm_pct']:.1f}% OTM)")
            if len(trades) > 2:
                print(f"    ... and {len(trades) - 2} more")

        except Exception as e:
            print(f"ERROR: {e}")

    print(f"\nTotal: {total} paper trades backfilled")
    print("NOTE: All backfilled trades use BSM pricing (not real market prices).")
    print("They are flagged with backfilled=true in strategy_params.")


if __name__ == "__main__":
    main()
