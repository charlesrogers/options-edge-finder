"""
yf_proxy.py — Drop-in replacement for yfinance calls, routing through the
Cloudflare Worker caching proxy instead of hitting Yahoo Finance directly.

Usage:
    import yf_proxy
    df = yf_proxy.get_stock_history("AAPL", period="1y")
    info = yf_proxy.get_stock_info("AAPL")
    exps = yf_proxy.get_expirations("AAPL")
    chain = yf_proxy.get_option_chain("AAPL", "2024-06-21")

Set YF_PROXY_URL env var to override the default proxy URL.
"""

import os
from types import SimpleNamespace

import pandas as pd
import requests

PROXY_URL = os.environ.get(
    "YF_PROXY_URL",
    "https://yfinance-proxy.charlesrogers.workers.dev",
).rstrip("/")

# Timeout for proxy requests (seconds)
REQUEST_TIMEOUT = 30


def _get(endpoint: str, params: dict = None) -> dict:
    """Make a GET request to the proxy and return parsed JSON."""
    url = f"{PROXY_URL}{endpoint}"
    print(f"[yf_proxy] Fetching {url} ...", end=" ", flush=True)
    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        cache_status = resp.headers.get("X-Cache", "UNKNOWN")
        print(f"OK (cache: {cache_status})")
        return data
    except requests.RequestException as e:
        print(f"FAILED: {e}")
        return {}


def get_stock_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    """
    Fetch historical OHLCV data for a ticker.

    Returns a DataFrame with columns: Open, High, Low, Close, Volume
    indexed by datetime (matching yfinance's .history() output).
    """
    print(f"[yf_proxy] Getting {period} history for {ticker}")
    data = _get(f"/stock/{ticker}/history", params={"period": period})

    rows = data.get("rows", [])
    if not rows:
        print(f"[yf_proxy] No history rows returned for {ticker}")
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df = df.rename(columns={
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
        "adjClose": "Adj Close",
    })
    # Keep only the columns yfinance typically returns
    cols = [c for c in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if c in df.columns]
    df = df[cols]
    df.index.name = "Date"
    print(f"[yf_proxy] Got {len(df)} rows of history for {ticker}")
    return df


def get_stock_info(ticker: str) -> dict:
    """
    Fetch stock info (company name, earnings dates, key stats, etc.).

    Returns a flat dict matching common yfinance .info keys.
    """
    print(f"[yf_proxy] Getting info for {ticker}")
    data = _get(f"/stock/{ticker}/info")

    if not data or data.get("error"):
        print(f"[yf_proxy] Info unavailable for {ticker}: {data.get('error', 'empty response')}")
        return {}

    # Map proxy keys to yfinance-style keys for compatibility
    info = {
        "shortName": data.get("shortName"),
        "longName": data.get("longName"),
        "currency": data.get("currency"),
        "exchange": data.get("exchange"),
        "marketCap": data.get("marketCap"),
        "regularMarketPrice": data.get("regularMarketPrice"),
        "regularMarketChange": data.get("regularMarketChange"),
        "regularMarketChangePercent": data.get("regularMarketChangePercent"),
        "fiftyTwoWeekHigh": data.get("fiftyTwoWeekHigh"),
        "fiftyTwoWeekLow": data.get("fiftyTwoWeekLow"),
        "dividendYield": data.get("dividendYield"),
        "trailingPE": data.get("trailingPE"),
        "forwardPE": data.get("forwardPE"),
        "beta": data.get("beta"),
        "earningsDate": data.get("earningsDate", []),
        "exDividendDate": data.get("exDividendDate"),
    }
    print(f"[yf_proxy] Got info for {ticker}: {info.get('shortName', 'N/A')}")
    return info


def get_expirations(ticker: str) -> list:
    """
    Fetch available option expiration dates for a ticker.

    Returns a list of date strings like ["2024-06-21", "2024-07-19", ...].
    """
    print(f"[yf_proxy] Getting option expirations for {ticker}")
    data = _get(f"/stock/{ticker}/options")

    expirations = data.get("expirations", [])
    print(f"[yf_proxy] Got {len(expirations)} expiration dates for {ticker}")
    return expirations


def get_option_chain(ticker: str, expiration: str) -> SimpleNamespace:
    """
    Fetch the options chain (calls + puts) for a specific expiration date.

    Returns a SimpleNamespace with .calls and .puts as DataFrames,
    matching yfinance's option_chain() return format.

    expiration should be a date string like "2024-06-21".
    """
    print(f"[yf_proxy] Getting option chain for {ticker} @ {expiration}")
    data = _get(f"/stock/{ticker}/options/{expiration}")

    calls_data = data.get("calls", [])
    puts_data = data.get("puts", [])

    if calls_data:
        calls_df = pd.DataFrame(calls_data)
    else:
        calls_df = pd.DataFrame(columns=[
            "contractSymbol", "strike", "lastPrice", "bid", "ask",
            "change", "percentChange", "volume", "openInterest",
            "impliedVolatility", "inTheMoney",
        ])

    if puts_data:
        puts_df = pd.DataFrame(puts_data)
    else:
        puts_df = pd.DataFrame(columns=[
            "contractSymbol", "strike", "lastPrice", "bid", "ask",
            "change", "percentChange", "volume", "openInterest",
            "impliedVolatility", "inTheMoney",
        ])

    print(f"[yf_proxy] Got {len(calls_df)} calls, {len(puts_df)} puts for {ticker} @ {expiration}")

    return SimpleNamespace(
        calls=calls_df,
        puts=puts_df,
        underlying_price=data.get("underlyingPrice"),
    )
