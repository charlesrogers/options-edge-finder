"""
batch_sampler.py — Daily IV snapshot collector for building IV Rank history.

Runs through a list of tickers, fetches IV + vol data via the CF Worker proxy,
and records snapshots to Supabase. Designed to run as a GitHub Actions cron job.

Usage:
    python batch_sampler.py                    # Sample all default tickers
    python batch_sampler.py AAPL MSFT GOOGL    # Sample specific tickers
"""

import os
import sys
import time
import traceback
import numpy as np
import pandas as pd
from datetime import datetime

# --- Configuration ---
# Delay between tickers to avoid rate limiting (seconds)
DELAY_BETWEEN_TICKERS = 2.0
# Max tickers per run (safety limit)
MAX_TICKERS_PER_RUN = 200

# High-liquidity tickers with active options markets
# These cover: mega-cap tech, finance, healthcare, consumer, energy, ETFs
DEFAULT_TICKERS = [
    # Mega-cap tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "INTC", "CRM",
    "ORCL", "ADBE", "NFLX", "AVGO", "QCOM", "MU", "AMAT", "LRCX", "KLAC", "MRVL",
    # Finance
    "JPM", "BAC", "GS", "MS", "WFC", "C", "BLK", "SCHW", "AXP", "V",
    "MA", "PYPL", "SQ", "COIN", "HOOD",
    # Healthcare
    "UNH", "JNJ", "PFE", "ABBV", "MRK", "LLY", "BMY", "AMGN", "GILD", "MRNA",
    # Consumer
    "WMT", "COST", "HD", "LOW", "TGT", "NKE", "SBUX", "MCD", "DIS", "ABNB",
    # Energy
    "XOM", "CVX", "COP", "SLB", "OXY", "DVN", "HAL", "MPC", "PSX", "VLO",
    # Industrial / other
    "BA", "CAT", "DE", "GE", "UPS", "FDX", "LMT", "RTX", "HON", "MMM",
    # Popular options ETFs
    "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV", "XLP", "XLI",
    "GLD", "SLV", "TLT", "HYG", "EEM", "EFA", "VXX", "ARKK", "SOXX", "SMH",
    # Meme / high-vol favorites
    "GME", "AMC", "PLTR", "SOFI", "RIVN", "LCID", "NIO", "MARA", "RIOT", "SMCI",
]


def setup_supabase_env():
    """Ensure Supabase env vars are set (for GitHub Actions)."""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        print("ERROR: SUPABASE_URL and SUPABASE_KEY must be set as environment variables")
        sys.exit(1)
    return url, key


def sample_ticker(ticker):
    """
    Fetch IV + vol data for a single ticker and record to Supabase.
    Returns dict with results or None on failure.
    """
    import yf_proxy
    from analytics import (
        calc_realized_vol, calc_yang_zhang_vol, calc_garch_forecast,
        get_iv_rank_percentile, get_term_structure, classify_vol_regime,
        calc_vrp_signal, calc_skew_score, get_next_fomc_date,
    )
    from db import record_iv, get_real_iv_rank, log_prediction

    try:
        # Fetch history
        hist = yf_proxy.get_stock_history(ticker, period="1y")
        if hist.empty or len(hist) < 30:
            return {"ticker": ticker, "status": "skip", "reason": "insufficient history"}

        current_price = float(hist["Close"].iloc[-1])

        # Realized vols
        rv_10 = calc_realized_vol(hist, window=10)
        rv_20 = calc_realized_vol(hist, window=20)
        rv_30 = calc_realized_vol(hist, window=30)
        rv_60 = calc_realized_vol(hist, window=60) if len(hist) >= 60 else None
        yz_20 = calc_yang_zhang_vol(hist, window=20)

        # GARCH forecast
        garch_vol, garch_info = calc_garch_forecast(hist, horizon=20)

        # Best vol forecast
        if garch_vol is not None and garch_vol > 0:
            rv_forecast = garch_vol
            forecast_method = "GJR-GARCH"
        elif yz_20 > 0:
            rv_forecast = yz_20
            forecast_method = "Yang-Zhang"
        else:
            rv_forecast = rv_20
            forecast_method = "Close-to-Close"

        # Get options data for IV
        expirations = yf_proxy.get_expirations(ticker)
        current_iv = None
        term_label = "N/A"
        term_struct = None
        skew_value, skew_penalty, skew_details = None, 0, {}
        chains = {}

        if expirations:
            # Fetch front-month chain
            first_exp = expirations[0]
            try:
                chain = yf_proxy.get_option_chain(ticker, first_exp)
                chains[first_exp] = chain

                # ATM IV from front-month
                if not chain.calls.empty:
                    calls = chain.calls.copy()
                    calls["dist"] = abs(calls["strike"] - current_price)
                    atm_row = calls.loc[calls["dist"].idxmin()]
                    current_iv = float(atm_row["impliedVolatility"]) * 100
            except Exception:
                pass

            # Get second expiration for term structure if available
            if len(expirations) >= 2:
                try:
                    chain2 = yf_proxy.get_option_chain(ticker, expirations[1])
                    chains[expirations[1]] = chain2
                except Exception:
                    pass

            # Term structure
            if chains:
                term_struct, term_label = get_term_structure(chains, list(chains.keys()), current_price)

            # Skew
            if first_exp in chains:
                try:
                    dte_front = max((datetime.strptime(first_exp, "%Y-%m-%d") - datetime.now()).days, 1)
                    skew_value, skew_penalty, skew_details = calc_skew_score(
                        chains[first_exp].calls, chains[first_exp].puts, current_price, dte_front
                    )
                except Exception:
                    pass

        # IV Rank
        iv_rank, iv_pctl = get_iv_rank_percentile(hist, current_iv) if current_iv else (None, None)
        real_iv_rank, real_iv_pctl, iv_history_days = get_real_iv_rank(ticker, current_iv) if current_iv else (None, None, 0)
        if real_iv_rank is not None and iv_history_days >= 20:
            iv_rank = real_iv_rank
            iv_pctl = real_iv_pctl

        # Regime
        regime = "normal"
        regime_info = {}
        try:
            vix_df = yf_proxy.get_stock_history("^VIX", period="5d")
            vix3m_df = yf_proxy.get_stock_history("^VIX3M", period="5d")
            vix_level = float(vix_df["Close"].iloc[-1]) if not vix_df.empty else None
            vix_ratio = None
            if not vix_df.empty and not vix3m_df.empty:
                vix_ratio = float(vix_df["Close"].iloc[-1] / vix3m_df["Close"].iloc[-1])
            regime, regime_info = classify_vol_regime(vix_level, vix_ratio, rv_20, rv_60)
        except Exception:
            pass

        # Signal
        vrp = (current_iv - rv_forecast) if current_iv else None
        signal, signal_color, signal_reason = calc_vrp_signal(vrp, iv_rank, term_label, regime=regime)

        # FOMC / earnings
        fomc_date, fomc_days = get_next_fomc_date()
        earnings_days = None
        # Skip earnings lookup in batch mode (too slow per ticker)

        # Record IV snapshot
        first_exp_str = expirations[0] if expirations else ""
        p25 = skew_details.get("put_25d_iv")
        c25 = skew_details.get("call_25d_iv")
        record_iv(
            ticker, current_iv, current_price, first_exp_str, rv_20, term_label,
            put_25d_iv=p25, call_25d_iv=c25,
            rv_10=rv_10, rv_30=rv_30, rv_60=rv_60, yz_20=yz_20,
            garch_vol=garch_vol, iv_rank=iv_rank, iv_pctl=iv_pctl,
            vrp=vrp, signal=signal, regime=regime, skew=skew_value,
            fomc_days=fomc_days, earnings_days=earnings_days,
        )

        # Log prediction
        log_prediction(
            ticker=ticker, signal=signal, spot_price=current_price,
            atm_iv=current_iv, rv_forecast=rv_forecast, vrp=vrp,
            iv_rank=iv_rank, term_label=term_label, regime=regime,
            skew=skew_value, garch_vol=garch_vol, forecast_method=forecast_method,
            rv_20=rv_20, iv_pctl=iv_pctl, skew_penalty=skew_penalty,
            signal_reason=signal_reason, fomc_days=fomc_days,
        )

        return {
            "ticker": ticker, "status": "ok",
            "price": current_price, "iv": current_iv, "vrp": vrp, "signal": signal,
        }

    except Exception as e:
        return {"ticker": ticker, "status": "error", "reason": str(e)}


def is_market_day():
    """Check if today is a US market trading day (weekday, not a holiday)."""
    today = datetime.now()
    # Skip weekends
    if today.weekday() >= 5:
        return False
    # Major US market holidays (approximate — doesn't cover all)
    month_day = (today.month, today.day)
    holidays = [
        (1, 1), (1, 20), (2, 17), (4, 18), (5, 26),
        (6, 19), (7, 4), (9, 1), (11, 27), (12, 25),
    ]
    if month_day in holidays:
        return False
    return True


def main():
    print(f"=== Batch IV Sampler — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")

    if not is_market_day():
        print("Not a market day (weekend/holiday). Skipping.")
        return

    setup_supabase_env()

    # Use command-line tickers or defaults
    if len(sys.argv) > 1:
        tickers = [t.upper().strip() for t in sys.argv[1:]]
    else:
        tickers = DEFAULT_TICKERS

    tickers = tickers[:MAX_TICKERS_PER_RUN]
    print(f"Sampling {len(tickers)} tickers...")

    results = {"ok": 0, "skip": 0, "error": 0}
    errors = []

    for i, ticker in enumerate(tickers):
        print(f"\n[{i+1}/{len(tickers)}] {ticker}")
        result = sample_ticker(ticker)

        if result:
            status = result["status"]
            results[status] = results.get(status, 0) + 1

            if status == "ok":
                iv_str = f"IV={result['iv']:.1f}" if result.get("iv") else "IV=N/A"
                vrp_str = f"VRP={result['vrp']:+.1f}" if result.get("vrp") else "VRP=N/A"
                print(f"  -> ${result['price']:.2f} | {iv_str} | {vrp_str} | {result['signal']}")
            elif status == "error":
                print(f"  -> ERROR: {result['reason']}")
                errors.append(f"{ticker}: {result['reason']}")
            else:
                print(f"  -> SKIP: {result.get('reason', '')}")

        # Rate limiting delay
        if i < len(tickers) - 1:
            time.sleep(DELAY_BETWEEN_TICKERS)

    print(f"\n=== Done ===")
    print(f"OK: {results['ok']} | Skipped: {results['skip']} | Errors: {results['error']}")
    if errors:
        print(f"\nErrors:")
        for e in errors[:10]:
            print(f"  {e}")

    # Exit with error code if too many failures
    total = sum(results.values())
    if total > 0 and results["error"] / total > 0.5:
        print("\nMore than 50% failures — something may be wrong with the proxy or Yahoo.")
        sys.exit(1)


if __name__ == "__main__":
    main()
