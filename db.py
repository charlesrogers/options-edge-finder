"""
Database layer. Uses Supabase (Postgres) when configured, falls back to local SQLite.
Environment variables:
  SUPABASE_URL - your Supabase project URL
  SUPABASE_KEY - your Supabase anon/service key
"""

import os
import json
import sqlite3
from datetime import datetime, timedelta

# --- Supabase setup ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
_supabase_client = None


def _get_supabase():
    global _supabase_client
    if _supabase_client is None and SUPABASE_URL and SUPABASE_KEY:
        from supabase import create_client
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_client


def using_supabase():
    return bool(SUPABASE_URL and SUPABASE_KEY)


# --- SQLite fallback ---
DB_DIR = os.path.dirname(__file__)
SQLITE_PATH = os.path.join(DB_DIR, "local.db")


def _get_sqlite():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS iv_snapshots (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            atm_iv REAL,
            spot_price REAL,
            front_exp TEXT,
            rv_20 REAL,
            term_label TEXT,
            PRIMARY KEY (ticker, date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            option_type TEXT NOT NULL,
            strike REAL NOT NULL,
            expiration TEXT NOT NULL,
            premium_received REAL NOT NULL,
            contracts INTEGER NOT NULL,
            strategy TEXT,
            notes TEXT,
            opened TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            closed_at TEXT,
            close_price REAL,
            close_reason TEXT,
            entry_iv REAL,
            entry_rv REAL,
            entry_vrp REAL,
            entry_delta REAL
        )
    """)
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================
# IV SNAPSHOTS
# ============================================================

def record_iv(ticker, atm_iv, spot_price, front_exp, rv_20, term_label):
    today = datetime.now().strftime("%Y-%m-%d")
    sb = _get_supabase()
    if sb:
        sb.table("iv_snapshots").upsert({
            "ticker": ticker, "date": today, "atm_iv": atm_iv,
            "spot_price": spot_price, "front_exp": front_exp,
            "rv_20": rv_20, "term_label": term_label,
        }).execute()
    else:
        conn = _get_sqlite()
        conn.execute(
            "INSERT OR REPLACE INTO iv_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticker, today, atm_iv, spot_price, front_exp, rv_20, term_label),
        )
        conn.commit()
        conn.close()


def get_iv_history(ticker, days=365):
    import pandas as pd
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    sb = _get_supabase()
    if sb:
        resp = sb.table("iv_snapshots").select("*").eq("ticker", ticker).gte("date", cutoff).order("date").execute()
        return pd.DataFrame(resp.data) if resp.data else pd.DataFrame()
    else:
        conn = _get_sqlite()
        df = pd.read_sql_query(
            "SELECT * FROM iv_snapshots WHERE ticker = ? AND date >= ? ORDER BY date",
            conn, params=(ticker, cutoff),
        )
        conn.close()
        return df


def get_real_iv_rank(ticker, current_iv):
    df = get_iv_history(ticker)
    if df.empty or len(df) < 5:
        return None, None, len(df)
    iv_series = df["atm_iv"].dropna()
    if iv_series.empty:
        return None, None, 0
    iv_min, iv_max = iv_series.min(), iv_series.max()
    if iv_max == iv_min:
        return 50.0, 50.0, len(iv_series)
    iv_rank = max(0, min(100, ((current_iv - iv_min) / (iv_max - iv_min)) * 100))
    iv_pctl = (iv_series < current_iv).sum() / len(iv_series) * 100
    return iv_rank, iv_pctl, len(iv_series)


# ============================================================
# TRADES
# ============================================================

def add_trade(ticker, option_type, strike, expiration, premium, contracts,
              strategy="covered_call", notes=""):
    now = datetime.now().isoformat()
    sb = _get_supabase()
    if sb:
        resp = sb.table("trades").insert({
            "ticker": ticker.upper(), "option_type": option_type,
            "strike": strike, "expiration": expiration,
            "premium_received": premium, "contracts": contracts,
            "strategy": strategy, "notes": notes,
            "opened": now, "status": "open",
        }).execute()
        return resp.data[0] if resp.data else None
    else:
        conn = _get_sqlite()
        cur = conn.execute(
            """INSERT INTO trades (ticker, option_type, strike, expiration,
               premium_received, contracts, strategy, notes, opened, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
            (ticker.upper(), option_type, strike, expiration, premium, contracts, strategy, notes, now),
        )
        conn.commit()
        trade_id = cur.lastrowid
        conn.close()
        return {"id": trade_id, "ticker": ticker.upper(), "option_type": option_type,
                "strike": strike, "expiration": expiration, "premium_received": premium,
                "contracts": contracts, "strategy": strategy, "notes": notes,
                "opened": now, "status": "open"}


def close_trade(trade_id, close_price, reason="manual"):
    now = datetime.now().isoformat()
    sb = _get_supabase()
    if sb:
        sb.table("trades").update({
            "status": "closed", "closed_at": now,
            "close_price": close_price, "close_reason": reason,
        }).eq("id", trade_id).execute()
    else:
        conn = _get_sqlite()
        conn.execute(
            "UPDATE trades SET status='closed', closed_at=?, close_price=?, close_reason=? WHERE id=?",
            (now, close_price, reason, trade_id),
        )
        conn.commit()
        conn.close()


def get_open_trades():
    sb = _get_supabase()
    if sb:
        resp = sb.table("trades").select("*").eq("status", "open").execute()
        return resp.data or []
    else:
        conn = _get_sqlite()
        rows = conn.execute("SELECT * FROM trades WHERE status = 'open'").fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_all_trades():
    sb = _get_supabase()
    if sb:
        resp = sb.table("trades").select("*").order("opened", desc=True).execute()
        return resp.data or []
    else:
        conn = _get_sqlite()
        rows = conn.execute("SELECT * FROM trades ORDER BY opened DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]


def delete_trade(trade_id):
    sb = _get_supabase()
    if sb:
        sb.table("trades").delete().eq("id", trade_id).execute()
    else:
        conn = _get_sqlite()
        conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
        conn.commit()
        conn.close()
