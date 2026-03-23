"""
EODHD Historical Options Data Fetcher

Downloads full option chain history from EODHD API.
Saves raw JSON first (never lose data), then processes into structured format.

API budget: 500 starter calls + 20/day on free tier.
Each ticker = 1 API call (returns ALL strikes, ALL expirations).

Usage:
  export EODHD_API_TOKEN=your_token_here
  python fetch_eodhd.py

Or for specific tickers:
  python fetch_eodhd.py AAPL GOOGL SPY
"""

import os
import sys
import json
import time
import requests
from datetime import datetime

# Security: token from env only
API_TOKEN = os.environ.get("EODHD_API_TOKEN", "")
BASE_URL = "https://eodhd.com/api/options"

DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "eodhd")
RAW_DIR = os.path.join(DATA_DIR, "raw")
LOG_FILE = os.path.join(DATA_DIR, "api_calls.log")

# Dad's tickers + key benchmarks
DEFAULT_TICKERS = [
    # Dad's portfolio
    "TXN", "TMUS", "GOOGL", "AMZN", "AAPL", "KKR", "DIS",
    # Key benchmarks for backtesting
    "SPY", "QQQ", "IWM",
    # Additional high-liquidity names
    "MSFT", "META", "NVDA", "JPM", "GS",
    "GLD", "TLT", "XLF", "XLE", "XOM",
]


def log_call(ticker, endpoint, status_code, n_rows, elapsed_ms):
    """Log every API call for tracking."""
    os.makedirs(DATA_DIR, exist_ok=True)
    timestamp = datetime.now().isoformat()
    with open(LOG_FILE, "a") as f:
        f.write(f"{timestamp}\t{endpoint}\t{ticker}\t{status_code}\t{n_rows}\t{elapsed_ms}ms\n")


def get_calls_used_today():
    """Count API calls made today from the log."""
    today = datetime.now().strftime("%Y-%m-%d")
    if not os.path.exists(LOG_FILE):
        return 0
    count = 0
    with open(LOG_FILE) as f:
        for line in f:
            if line.startswith(today):
                count += 1
    return count


def fetch_options(ticker, from_date=None, to_date=None):
    """
    Fetch options data for a ticker from EODHD.

    Args:
        ticker: Stock symbol (e.g., "AAPL")
        from_date: Optional start date (YYYY-MM-DD) for historical data
        to_date: Optional end date (YYYY-MM-DD)

    Returns:
        dict (raw API response) or None on error
    """
    if not API_TOKEN:
        print("ERROR: EODHD_API_TOKEN not set. Run: export EODHD_API_TOKEN=your_token")
        return None

    url = f"{BASE_URL}/{ticker}.US"
    params = {"api_token": API_TOKEN, "fmt": "json"}
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date

    start = time.time()
    try:
        resp = requests.get(url, params=params, timeout=30)
        elapsed = int((time.time() - start) * 1000)

        # Count rows
        n_rows = 0
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and "data" in data:
                for exp in data.get("data", []):
                    options = exp.get("options", {})
                    n_rows += len(options.get("CALL", []))
                    n_rows += len(options.get("PUT", []))
            elif isinstance(data, list):
                n_rows = len(data)

        log_call(ticker, url.split("?")[0], resp.status_code, n_rows, elapsed)

        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"  ERROR: HTTP {resp.status_code} for {ticker}: {resp.text[:200]}")
            return None

    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        log_call(ticker, url.split("?")[0], 0, 0, elapsed)
        print(f"  ERROR: {ticker}: {e}")
        return None


def save_raw(ticker, data, suffix=""):
    """Save raw JSON response to file. NEVER lose raw data."""
    os.makedirs(RAW_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    filename = f"{ticker}_options_{today}{suffix}.json"
    path = os.path.join(RAW_DIR, filename)

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    size_kb = os.path.getsize(path) / 1024
    print(f"  Saved: {filename} ({size_kb:.0f} KB, {count_contracts(data)} contracts)")
    return path


def count_contracts(data):
    """Count total option contracts in EODHD response."""
    n = 0
    if isinstance(data, dict) and "data" in data:
        for exp in data.get("data", []):
            options = exp.get("options", {})
            n += len(options.get("CALL", []))
            n += len(options.get("PUT", []))
    return n


def parse_to_dataframe(data, ticker):
    """Parse EODHD options response into a flat DataFrame."""
    import pandas as pd

    rows = []
    if not isinstance(data, dict) or "data" not in data:
        return pd.DataFrame()

    for exp_group in data.get("data", []):
        expiry = exp_group.get("expirationDate", "")
        options = exp_group.get("options", {})

        for opt_type in ["CALL", "PUT"]:
            for contract in options.get(opt_type, []):
                rows.append({
                    "ticker": ticker,
                    "expiration": expiry,
                    "option_type": opt_type.lower(),
                    "strike": contract.get("strike"),
                    "bid": contract.get("bid"),
                    "ask": contract.get("ask"),
                    "last_price": contract.get("lastPrice"),
                    "volume": contract.get("volume"),
                    "open_interest": contract.get("openInterest"),
                    "implied_volatility": contract.get("impliedVolatility"),
                    "contract_name": contract.get("contractName"),
                    "contract_size": contract.get("contractSize"),
                    "currency": contract.get("currency"),
                    "last_trade_date": contract.get("lastTradeDateTime"),
                    "in_the_money": 1 if contract.get("inTheMoney") == "True" else 0,
                })

    return pd.DataFrame(rows)


def fetch_all(tickers=None, save_parquet=True):
    """Fetch options data for all tickers."""
    import pandas as pd

    if tickers is None:
        tickers = DEFAULT_TICKERS

    calls_used = get_calls_used_today()
    print(f"API calls used today: {calls_used}")
    print(f"Fetching {len(tickers)} tickers...")
    print()

    all_dfs = []
    fetched = 0

    for ticker in tickers:
        print(f"[{fetched + 1}/{len(tickers)}] {ticker}...")

        # Check budget
        if calls_used + fetched >= 18:  # leave 2 calls buffer
            print(f"  STOPPING: approaching daily limit ({calls_used + fetched} calls used)")
            break

        data = fetch_options(ticker)
        if data:
            # Save raw FIRST
            save_raw(ticker, data)

            # Parse to DataFrame
            df = parse_to_dataframe(data, ticker)
            if not df.empty:
                all_dfs.append(df)
                print(f"  Parsed: {len(df)} contracts across "
                      f"{df['expiration'].nunique()} expirations")
            else:
                print(f"  WARNING: No contracts parsed from response")

            fetched += 1
        else:
            print(f"  SKIPPED (API error)")

        # Rate limit: 1 second between calls
        time.sleep(1)

    print(f"\nDone. Fetched {fetched} tickers, {calls_used + fetched} total calls today.")

    # Combine all DataFrames
    if all_dfs:
        combined = pd.concat(all_dfs, ignore_index=True)
        print(f"\nTotal: {len(combined)} contracts across {combined['ticker'].nunique()} tickers")

        # Summary
        for ticker in combined["ticker"].unique():
            t_df = combined[combined["ticker"] == ticker]
            n_exp = t_df["expiration"].nunique()
            n_calls = len(t_df[t_df["option_type"] == "call"])
            n_puts = len(t_df[t_df["option_type"] == "put"])
            print(f"  {ticker}: {n_exp} expirations, {n_calls} calls, {n_puts} puts")

        # Save parquet
        if save_parquet:
            parquet_dir = os.path.join(DATA_DIR, "processed")
            os.makedirs(parquet_dir, exist_ok=True)
            today = datetime.now().strftime("%Y-%m-%d")
            parquet_path = os.path.join(parquet_dir, f"option_chains_{today}.parquet")
            combined.to_parquet(parquet_path, index=False)
            size_mb = os.path.getsize(parquet_path) / (1024 * 1024)
            print(f"\nSaved: {parquet_path} ({size_mb:.1f} MB)")

        return combined

    return pd.DataFrame()


if __name__ == "__main__":
    # Custom tickers from command line, or default
    if len(sys.argv) > 1:
        tickers = [t.upper() for t in sys.argv[1:]]
    else:
        tickers = DEFAULT_TICKERS

    print("=" * 60)
    print("EODHD Options Data Fetcher")
    print("=" * 60)
    print(f"Tickers: {tickers}")
    print(f"Token: {'set' if API_TOKEN else 'NOT SET'}")
    print()

    if not API_TOKEN:
        print("ERROR: Set EODHD_API_TOKEN environment variable first.")
        print("  export EODHD_API_TOKEN=your_token_here")
        sys.exit(1)

    df = fetch_all(tickers)
    if not df.empty:
        print(f"\nSuccess! {len(df)} option contracts downloaded.")
        print("Raw JSON saved to data/eodhd/raw/")
        print("Parquet saved to data/eodhd/processed/")
    else:
        print("\nNo data fetched. Check API token and network.")
