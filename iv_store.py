"""
IV Recording System.
Snapshots ATM implied volatility daily into SQLite.
After ~30 days, we have real IV history for proper IV Rank/Percentile.
"""

import sqlite3
import os
from datetime import datetime, timedelta
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "iv_history.db")


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS iv_snapshots (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            atm_iv REAL,
            atm_strike REAL,
            spot_price REAL,
            front_exp TEXT,
            rv_20 REAL,
            term_label TEXT,
            PRIMARY KEY (ticker, date)
        )
    """)
    return conn


def record_iv(ticker, atm_iv, atm_strike, spot_price, front_exp, rv_20, term_label):
    """Record today's IV snapshot. Idempotent — overwrites if already recorded today."""
    conn = _get_conn()
    today = datetime.now().strftime("%Y-%m-%d")
    conn.execute(
        "INSERT OR REPLACE INTO iv_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ticker, today, atm_iv, atm_strike, spot_price, front_exp, rv_20, term_label),
    )
    conn.commit()
    conn.close()


def get_iv_history(ticker, days=365):
    """Get recorded IV history for a ticker."""
    conn = _get_conn()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    df = pd.read_sql_query(
        "SELECT * FROM iv_snapshots WHERE ticker = ? AND date >= ? ORDER BY date",
        conn,
        params=(ticker, cutoff),
    )
    conn.close()
    return df


def get_real_iv_rank(ticker, current_iv):
    """
    Calculate IV Rank using REAL recorded IV history.
    Returns (iv_rank, iv_percentile, days_of_history) or (None, None, 0) if insufficient data.
    """
    df = get_iv_history(ticker)
    if df.empty or len(df) < 5:
        return None, None, len(df)

    iv_series = df["atm_iv"].dropna()
    if iv_series.empty:
        return None, None, 0

    iv_min = iv_series.min()
    iv_max = iv_series.max()

    if iv_max == iv_min:
        return 50.0, 50.0, len(iv_series)

    iv_rank = ((current_iv - iv_min) / (iv_max - iv_min)) * 100
    iv_rank = max(0, min(100, iv_rank))
    iv_pctl = (iv_series < current_iv).sum() / len(iv_series) * 100

    return iv_rank, iv_pctl, len(iv_series)
