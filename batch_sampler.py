"""
batch_sampler.py — Daily IV snapshot collector for building IV Rank history.

Runs through ~350 liquid option tickers near market close, fetches IV + vol data
via the CF Worker proxy, and records snapshots to Supabase.

Designed to run as a GitHub Actions cron job once per day at ~3:55 PM ET.

On first run, bootstraps 90 days of pseudo-IV (RV * 1.1) so IV Rank works
immediately rather than waiting 90 days for real data.

Usage:
    python batch_sampler.py                    # Sample all default tickers
    python batch_sampler.py AAPL MSFT GOOGL    # Sample specific tickers
    python batch_sampler.py --bootstrap        # Backfill 90 days of pseudo-IV
"""

import os
import sys
import time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# --- Configuration ---
DELAY_BETWEEN_TICKERS = 3.0  # seconds — safe for Yahoo rate limits
MAX_TICKERS_PER_RUN = 400

# ~350 liquid option tickers: S&P components + high-volume ETFs + popular names
# Filtered for tickers with tight option spreads and reliable Yahoo data
DEFAULT_TICKERS = [
    # Index ETFs (most liquid options in the world)
    "SPY", "QQQ", "IWM", "DIA",
    # Sector ETFs
    "XLF", "XLE", "XLK", "XLV", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC", "XBI",
    # Commodity / Bond / Intl ETFs
    "GLD", "SLV", "TLT", "HYG", "EEM", "EFA", "USO", "UNG",
    # Thematic ETFs
    "ARKK", "SOXX", "SMH", "KWEB", "XHB", "KRE", "JETS", "GDXJ", "GDX",
    # Volatility
    "VXX", "UVXY", "SVXY",
    # Mega-cap tech (20)
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA", "AMD", "INTC",
    "CRM", "ORCL", "ADBE", "NFLX", "AVGO", "QCOM", "MU", "AMAT", "LRCX", "KLAC",
    # More tech (20)
    "MRVL", "SNPS", "CDNS", "PANW", "CRWD", "ZS", "FTNT", "DDOG", "SNOW", "MDB",
    "NET", "SHOP", "XYZ", "UBER", "LYFT", "DASH", "ABNB", "RBLX", "U", "TWLO",
    # Finance (20)
    "JPM", "BAC", "GS", "MS", "WFC", "C", "BLK", "SCHW", "AXP", "V",
    "MA", "PYPL", "COIN", "HOOD", "ICE", "CME", "NDAQ", "BX", "KKR", "APO",
    # Healthcare (20)
    "UNH", "JNJ", "PFE", "ABBV", "MRK", "LLY", "BMY", "AMGN", "GILD", "MRNA",
    "REGN", "VRTX", "ISRG", "DXCM", "ZTS", "CI", "HUM", "ELV", "CVS", "MCK",
    # Consumer (20)
    "WMT", "COST", "HD", "LOW", "TGT", "NKE", "SBUX", "MCD", "DIS", "CMCSA",
    "PEP", "KO", "PG", "CL", "EL", "LULU", "ROST", "TJX", "DG", "DLTR",
    # Energy (15)
    "XOM", "CVX", "COP", "SLB", "OXY", "DVN", "HAL", "MPC", "PSX", "VLO",
    "EOG", "FANG", "APA", "DINO", "TPL",
    # Industrial / Aerospace (20)
    "BA", "CAT", "DE", "GE", "UPS", "FDX", "LMT", "RTX", "HON", "MMM",
    "GD", "NOC", "WM", "RSG", "CSX", "UNP", "NSC", "DAL", "UAL", "AAL",
    # Telecom / Media (10)
    "T", "VZ", "TMUS", "CHTR", "WBD", "NWSA", "FOX", "LYV", "MTCH", "SPOT",
    # Auto / EV (10)
    "F", "GM", "RIVN", "LCID", "NIO", "LI", "XPEV", "TM", "HMC", "STLA",
    # Real estate / REITs (10)
    "AMT", "PLD", "CCI", "EQIX", "SPG", "O", "DLR", "PSA", "WELL", "AVB",
    # Biotech small-mid (10)
    "SRPT", "ALNY", "BMRN", "EXAS", "HALO", "IONS", "RARE", "PCVX", "CRSP", "EXEL",
    # Crypto-adjacent (5)
    "MARA", "RIOT", "MSTR", "HUT", "BITF",
    # High-vol / popular options (20)
    "GME", "AMC", "PLTR", "SOFI", "SMCI", "ARM", "AI", "IONQ", "RGTI", "QUBT",
    "AFRM", "UPST", "CLOV", "BB", "NOK", "SNAP", "PINS", "ROKU", "Z", "RDDT",
    # Materials / Mining (10)
    "FCX", "NEM", "GOLD", "BHP", "RIO", "VALE", "NUE", "STLD", "CLF", "AA",
    # Utilities (5)
    "NEE", "DUK", "SO", "D", "AEP",
    # Cannabis (5)
    "TLRY", "CGC", "ACB", "CRON", "MO",
    # China ADRs (10)
    "BABA", "JD", "PDD", "BIDU", "BILI", "TME", "VNET", "ZTO", "TCOM", "MNSO",
    # Defense / Gov tech (5)
    "PLTR", "DDOG", "SNOW", "OKTA", "ZS",
]

# Deduplicate while preserving order
_seen = set()
DEFAULT_TICKERS = [t for t in DEFAULT_TICKERS if not (t in _seen or _seen.add(t))]


def setup_supabase_env():
    """Ensure Supabase env vars are set (for GitHub Actions)."""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        print("ERROR: SUPABASE_URL and SUPABASE_KEY must be set as environment variables")
        sys.exit(1)
    return url, key


def bootstrap_pseudo_iv(tickers, days=90):
    """
    Backfill 90 days of pseudo-IV using realized_vol * 1.1.
    This gives IV Rank something to work with immediately instead of
    waiting 90 days for real IV data to accumulate.
    """
    import yf_proxy
    from analytics import calc_realized_vol
    from db import record_iv

    print(f"\n=== BOOTSTRAP MODE: Backfilling {days} days of pseudo-IV for {len(tickers)} tickers ===")
    print("Using pseudo_IV = realized_vol_30 * 1.1 (standard quant approximation)\n")

    today = datetime.now()
    success = 0
    errors = 0

    for i, ticker in enumerate(tickers):
        print(f"[{i+1}/{len(tickers)}] Bootstrapping {ticker}...", end=" ", flush=True)
        try:
            hist = yf_proxy.get_stock_history(ticker, period="2y")
            if hist.empty or len(hist) < 60:
                print("SKIP (insufficient history)")
                continue

            hist.index = pd.to_datetime(hist.index)
            filled_days = 0

            # Walk backwards through trading days
            for day_offset in range(days, 0, -1):
                target_date = today - timedelta(days=day_offset)
                date_str = target_date.strftime("%Y-%m-%d")

                # Get history up to that date
                hist_to_date = hist[hist.index <= pd.Timestamp(date_str)]
                if len(hist_to_date) < 30:
                    continue

                spot = float(hist_to_date["Close"].iloc[-1])

                # Realized vol as of that date
                log_ret = np.log(hist_to_date["Close"] / hist_to_date["Close"].shift(1)).dropna()
                if len(log_ret) < 20:
                    continue
                rv_30 = float(log_ret.tail(30).std() * np.sqrt(252) * 100)
                rv_20 = float(log_ret.tail(20).std() * np.sqrt(252) * 100)
                rv_10 = float(log_ret.tail(10).std() * np.sqrt(252) * 100)

                # Pseudo-IV: standard approximation
                pseudo_iv = rv_30 * 1.1

                # Write directly to Supabase with the historical date
                from db import _get_supabase
                sb = _get_supabase()
                if sb:
                    sb.table("iv_snapshots").upsert({
                        "ticker": ticker,
                        "date": date_str,
                        "atm_iv": round(pseudo_iv, 2),
                        "spot_price": round(spot, 2),
                        "rv_20": round(rv_20, 2),
                        "rv_10": round(rv_10, 2),
                        "rv_30": round(rv_30, 2),
                        "term_label": "N/A",
                        "signal": "BOOTSTRAP",
                        "regime": "unknown",
                    }).execute()
                    filled_days += 1

            print(f"OK ({filled_days} days)")
            success += 1

        except Exception as e:
            print(f"ERROR: {e}")
            errors += 1

        if i < len(tickers) - 1:
            time.sleep(1)  # Lighter delay for bootstrap (fewer API calls per ticker)

    print(f"\n=== Bootstrap complete: {success} tickers filled, {errors} errors ===")


def sample_ticker(ticker, vix_data=None):
    """
    Fetch IV + vol data for a single ticker and record to Supabase.
    Accepts pre-fetched VIX data to avoid redundant API calls.
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
        skew_value, skew_penalty, skew_details = None, 0, {}
        chains = {}

        if expirations:
            # Fetch front-month chain only (saves API calls)
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

            # Second expiration for term structure (only if first succeeded)
            if chains and len(expirations) >= 2:
                try:
                    chain2 = yf_proxy.get_option_chain(ticker, expirations[1])
                    chains[expirations[1]] = chain2
                except Exception:
                    pass

            # Term structure
            if len(chains) >= 2:
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

        # If no options IV available, use pseudo-IV for the snapshot
        if current_iv is None:
            current_iv = rv_30 * 1.1 if rv_30 else (rv_20 * 1.1 if rv_20 else None)

        # IV Rank
        iv_rank, iv_pctl = get_iv_rank_percentile(hist, current_iv) if current_iv else (None, None)
        real_iv_rank, real_iv_pctl, iv_history_days = get_real_iv_rank(ticker, current_iv) if current_iv else (None, None, 0)
        if real_iv_rank is not None and iv_history_days >= 20:
            iv_rank = real_iv_rank
            iv_pctl = real_iv_pctl

        # Regime (use pre-fetched VIX data)
        regime = "normal"
        if vix_data:
            regime, _ = classify_vol_regime(
                vix_data.get("vix_level"), vix_data.get("vix_ratio"), rv_20, rv_60
            )

        # Signal
        vrp = (current_iv - rv_forecast) if current_iv else None
        signal, signal_color, signal_reason = calc_vrp_signal(vrp, iv_rank, term_label, regime=regime)

        # FOMC
        fomc_date, fomc_days = get_next_fomc_date()

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
            fomc_days=fomc_days, earnings_days=None,
        )

        # Discipline check — would we actually trade this?
        try:
            from discipline import check_trade_filters, get_severity
            should_trade, filter_reasons = check_trade_filters(
                vrp=vrp, iv_rank=iv_rank, term_label=term_label,
                regime=regime, fomc_days=fomc_days, atm_iv=current_iv,
            )
            trade_severity = get_severity(filter_reasons)
        except Exception:
            should_trade, filter_reasons, trade_severity = True, [], "TRADE"

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
            "should_trade": should_trade, "trade_severity": trade_severity,
        }

    except Exception as e:
        return {"ticker": ticker, "status": "error", "reason": str(e)}


def is_market_day():
    """Check if today is a US market trading day (weekday, not a holiday)."""
    today = datetime.now()
    if today.weekday() >= 5:
        return False
    # Major US market holidays 2025-2026 (approximate)
    holidays = [
        (1, 1), (1, 20), (2, 17), (4, 18), (5, 26),
        (6, 19), (7, 4), (9, 1), (11, 27), (12, 25),
    ]
    if (today.month, today.day) in holidays:
        return False
    return True


def fetch_vix_data():
    """Fetch VIX and VIX3M once for the entire batch run."""
    import yf_proxy
    try:
        vix_df = yf_proxy.get_stock_history("^VIX", period="5d")
        vix3m_df = yf_proxy.get_stock_history("^VIX3M", period="5d")
        vix_level = float(vix_df["Close"].iloc[-1]) if not vix_df.empty else None
        vix_ratio = None
        if not vix_df.empty and not vix3m_df.empty:
            vix_ratio = float(vix_df["Close"].iloc[-1] / vix3m_df["Close"].iloc[-1])
        print(f"VIX: {vix_level:.1f}, VIX/VIX3M ratio: {vix_ratio:.3f}" if vix_level else "VIX: unavailable")
        return {"vix_level": vix_level, "vix_ratio": vix_ratio}
    except Exception as e:
        print(f"VIX fetch failed: {e}")
        return {}


def main():
    print(f"=== Batch IV Sampler — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")

    # Bootstrap mode: backfill 90 days of pseudo-IV
    if "--bootstrap" in sys.argv:
        setup_supabase_env()
        args = [a for a in sys.argv[1:] if a != "--bootstrap"]
        tickers = [t.upper().strip() for t in args] if args else DEFAULT_TICKERS[:MAX_TICKERS_PER_RUN]
        bootstrap_pseudo_iv(tickers)
        return

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
    print(f"Sampling {len(tickers)} tickers with {DELAY_BETWEEN_TICKERS}s delay...")
    est_minutes = len(tickers) * DELAY_BETWEEN_TICKERS / 60
    print(f"Estimated runtime: ~{est_minutes:.0f} minutes")

    # Fetch VIX once for all tickers
    vix_data = fetch_vix_data()

    results = {"ok": 0, "skip": 0, "error": 0}
    errors = []

    for i, ticker in enumerate(tickers):
        print(f"\n[{i+1}/{len(tickers)}] {ticker}")
        result = sample_ticker(ticker, vix_data=vix_data)

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

        # Progress update every 50 tickers
        if (i + 1) % 50 == 0:
            print(f"\n--- Progress: {i+1}/{len(tickers)} | OK: {results['ok']} | Errors: {results['error']} ---")

        # Rate limiting delay
        if i < len(tickers) - 1:
            time.sleep(DELAY_BETWEEN_TICKERS)

    print(f"\n=== Done ===")
    print(f"OK: {results['ok']} | Skipped: {results['skip']} | Errors: {results['error']}")
    print(f"Total tickers: {sum(results.values())}")
    if errors:
        print(f"\nFirst 10 errors:")
        for e in errors[:10]:
            print(f"  {e}")

    # Exit with error code if too many failures
    total = sum(results.values())
    if total > 0 and results["error"] / total > 0.5:
        print("\nMore than 50% failures — something may be wrong with the proxy or Yahoo.")
        sys.exit(1)


if __name__ == "__main__":
    main()
