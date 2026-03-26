"""
Daily Option Chain Capture — Databento-level live data logging.

Captures full option chains (all strikes, bids, asks, IVs, OI) for Dad's
tickers every trading day. This means we NEVER need to buy historical data
again — we're building our own Databento-quality dataset from today forward.

Runs at 3:50 PM ET (just before market close) via GitHub Actions.
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

import yf_proxy
from db import record_chain_snapshot, record_iv
from analytics import calc_realized_vol, calc_yang_zhang_vol, calc_garch_forecast
from analytics import get_iv_rank_percentile, get_term_structure, calc_vrp_signal
from analytics import classify_vol_regime, calc_skew_score

# Dad's tickers + a few liquid extras for context
CAPTURE_TICKERS = ['AAPL', 'TMUS', 'KKR', 'DIS', 'TXN', 'GOOGL', 'AMZN']


def capture_ticker(ticker):
    """Capture full chain + IV snapshot for one ticker."""
    print(f"  {ticker}...", end=" ", flush=True)

    # Stock history
    hist = yf_proxy.get_stock_history(ticker, period="1y")
    if hist.empty:
        print("no stock data")
        return 0

    current_price = float(hist["Close"].iloc[-1])

    # Get expirations
    expirations = yf_proxy.get_expirations(ticker)
    if not expirations:
        print("no expirations")
        return 0

    # Capture first 4 expirations (covers ~2 months of chains)
    total_rows = 0
    chains_for_iv = {}
    for exp in expirations[:4]:
        chain = yf_proxy.get_option_chain(ticker, exp)
        if chain is None:
            continue
        chains_for_iv[exp] = chain
        n = record_chain_snapshot(ticker, exp, chain)
        total_rows += n

    # Also record IV summary snapshot
    try:
        current_iv = None
        if chains_for_iv:
            first_exp = list(chains_for_iv.keys())[0]
            calls = chains_for_iv[first_exp].calls
            if not calls.empty and "impliedVolatility" in calls.columns:
                calls_sorted = calls.copy()
                calls_sorted["dist"] = abs(calls_sorted["strike"] - current_price)
                atm_row = calls_sorted.loc[calls_sorted["dist"].idxmin()]
                current_iv = float(atm_row["impliedVolatility"]) * 100

        rv_20 = calc_realized_vol(hist, window=20)
        rv_10 = calc_realized_vol(hist, window=10)
        rv_30 = calc_realized_vol(hist, window=30)
        rv_60 = calc_realized_vol(hist, window=60) if len(hist) >= 60 else None
        yz_20 = calc_yang_zhang_vol(hist, window=20)
        garch_vol, _ = calc_garch_forecast(hist, horizon=20)

        rv_forecast = garch_vol if garch_vol and garch_vol > 0 else (yz_20 if yz_20 > 0 else rv_20)
        vrp = (current_iv - rv_forecast) if current_iv else None

        iv_rank, iv_pctl = get_iv_rank_percentile(hist, current_iv)
        term_struct, term_label = get_term_structure(chains_for_iv, expirations, current_price)

        regime = "normal"
        try:
            vix_df = yf_proxy.get_stock_history("^VIX", period="5d")
            vix3m_df = yf_proxy.get_stock_history("^VIX3M", period="5d")
            vix_level = float(vix_df["Close"].iloc[-1]) if not vix_df.empty else None
            vix_ratio = float(vix_df["Close"].iloc[-1] / vix3m_df["Close"].iloc[-1]) if not vix_df.empty and not vix3m_df.empty else None
            regime, _ = classify_vol_regime(vix_level, vix_ratio, rv_20, rv_60)
        except Exception:
            pass

        signal, _, _ = calc_vrp_signal(vrp, iv_rank, term_label, regime=regime)

        skew_value = None
        if chains_for_iv:
            first_exp = list(chains_for_iv.keys())[0]
            try:
                from datetime import datetime as dt
                dte_front = max((dt.strptime(first_exp, "%Y-%m-%d") - dt.now()).days, 1)
                skew_value, _, skew_details = calc_skew_score(
                    chains_for_iv[first_exp].calls, chains_for_iv[first_exp].puts,
                    current_price, dte_front
                )
                p25 = skew_details.get("put_25d_iv")
                c25 = skew_details.get("call_25d_iv")
            except Exception:
                p25, c25 = None, None
        else:
            p25, c25 = None, None

        record_iv(ticker, current_iv, current_price,
                  expirations[0] if expirations else "", rv_20, term_label,
                  put_25d_iv=p25, call_25d_iv=c25,
                  rv_10=rv_10, rv_30=rv_30, rv_60=rv_60, yz_20=yz_20,
                  garch_vol=garch_vol, iv_rank=iv_rank, iv_pctl=iv_pctl,
                  vrp=vrp, signal=signal, regime=regime, skew=skew_value)
    except Exception as e:
        print(f"IV snapshot error: {e}", end=" ")

    print(f"{total_rows} rows across {min(4, len(expirations))} expirations")
    return total_rows


def main():
    print("=" * 60)
    print(f"Daily Option Chain Capture — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("Building our own Databento-quality dataset")
    print("=" * 60)

    total = 0
    for ticker in CAPTURE_TICKERS:
        try:
            total += capture_ticker(ticker)
        except Exception as e:
            print(f"  {ticker} FAILED: {e}")

    print(f"\nTotal: {total} option chain rows captured")


if __name__ == "__main__":
    main()
