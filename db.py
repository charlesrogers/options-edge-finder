"""
Database layer. Uses Supabase (Postgres) when configured, falls back to local SQLite.
Includes prediction logging for scorecard verification.
Environment variables:
  SUPABASE_URL - your Supabase project URL
  SUPABASE_KEY - your Supabase anon/service key
"""

import os
import json
import sqlite3
from datetime import datetime, timedelta

# --- Supabase setup ---
def _read_secret(key):
    """Read from os.environ first, then st.secrets (Streamlit Cloud)."""
    val = os.environ.get(key, "")
    if not val:
        try:
            import streamlit as st
            val = st.secrets.get(key, "")
        except Exception:
            pass
    return val or ""

SUPABASE_URL = _read_secret("SUPABASE_URL")
SUPABASE_KEY = _read_secret("SUPABASE_KEY")
_supabase_client = None


def _get_supabase():
    global _supabase_client, SUPABASE_URL, SUPABASE_KEY
    # Re-read secrets on first call in case module loaded before st.secrets was ready
    if not SUPABASE_URL:
        SUPABASE_URL = _read_secret("SUPABASE_URL")
        SUPABASE_KEY = _read_secret("SUPABASE_KEY")
    if _supabase_client is None and SUPABASE_URL and SUPABASE_KEY:
        from supabase import create_client
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_client


def using_supabase():
    if not SUPABASE_URL:
        # Try re-reading in case secrets loaded late
        url = _read_secret("SUPABASE_URL")
        return bool(url)
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
            put_25d_iv REAL,
            call_25d_iv REAL,
            PRIMARY KEY (ticker, date)
        )
    """)
    # Migration: add columns if they don't exist yet (for existing DBs)
    _migrate_cols = [
        ("iv_snapshots", "put_25d_iv", "REAL"),
        ("iv_snapshots", "call_25d_iv", "REAL"),
        ("iv_snapshots", "rv_10", "REAL"),
        ("iv_snapshots", "rv_30", "REAL"),
        ("iv_snapshots", "rv_60", "REAL"),
        ("iv_snapshots", "yz_20", "REAL"),
        ("iv_snapshots", "garch_vol", "REAL"),
        ("iv_snapshots", "iv_rank", "REAL"),
        ("iv_snapshots", "iv_pctl", "REAL"),
        ("iv_snapshots", "vrp", "REAL"),
        ("iv_snapshots", "signal", "TEXT"),
        ("iv_snapshots", "regime", "TEXT"),
        ("iv_snapshots", "skew", "REAL"),
        ("iv_snapshots", "fomc_days", "INTEGER"),
        ("iv_snapshots", "earnings_days", "INTEGER"),
    ]
    for table, col, coltype in _migrate_cols:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
        except Exception:
            pass
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            signal TEXT NOT NULL,
            spot_price REAL,
            atm_iv REAL,
            rv_forecast REAL,
            vrp REAL,
            iv_rank REAL,
            term_label TEXT,
            regime TEXT,
            skew REAL,
            garch_vol REAL,
            forecast_method TEXT,
            holding_days INTEGER DEFAULT 20,
            outcome_price REAL,
            outcome_return REAL,
            outcome_rv REAL,
            outcome_date TEXT,
            scored INTEGER DEFAULT 0,
            seller_won INTEGER,
            UNIQUE(ticker, date, holding_days)
        )
    """)
    # Migration: predictions extra columns
    _pred_migrate = [
        ("predictions", "rv_20", "REAL"),
        ("predictions", "iv_pctl", "REAL"),
        ("predictions", "skew_penalty", "REAL"),
        ("predictions", "signal_reason", "TEXT"),
        ("predictions", "earnings_days", "INTEGER"),
        ("predictions", "fomc_days", "INTEGER"),
    ]
    for table, col, coltype in _pred_migrate:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
        except Exception:
            pass
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================
# IV SNAPSHOTS
# ============================================================

def record_iv(ticker, atm_iv, spot_price, front_exp, rv_20, term_label,
              put_25d_iv=None, call_25d_iv=None,
              rv_10=None, rv_30=None, rv_60=None, yz_20=None,
              garch_vol=None, iv_rank=None, iv_pctl=None,
              vrp=None, signal=None, regime=None, skew=None,
              fomc_days=None, earnings_days=None):
    today = datetime.now().strftime("%Y-%m-%d")
    row = {
        "ticker": ticker, "date": today, "atm_iv": atm_iv,
        "spot_price": spot_price, "front_exp": front_exp,
        "rv_20": rv_20, "term_label": term_label,
        "put_25d_iv": put_25d_iv, "call_25d_iv": call_25d_iv,
        "rv_10": rv_10, "rv_30": rv_30, "rv_60": rv_60, "yz_20": yz_20,
        "garch_vol": garch_vol, "iv_rank": iv_rank, "iv_pctl": iv_pctl,
        "vrp": vrp, "signal": signal, "regime": regime, "skew": skew,
        "fomc_days": fomc_days, "earnings_days": earnings_days,
    }
    sb = _get_supabase()
    if sb:
        sb.table("iv_snapshots").upsert(row).execute()
    else:
        conn = _get_sqlite()
        cols = ", ".join(row.keys())
        placeholders = ", ".join(["?"] * len(row))
        conn.execute(
            f"INSERT OR REPLACE INTO iv_snapshots ({cols}) VALUES ({placeholders})",
            tuple(row.values()),
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


# ============================================================
# PREDICTION LOG — record signals, score them later
# ============================================================

def log_prediction(ticker, signal, spot_price, atm_iv=None, rv_forecast=None,
                   vrp=None, iv_rank=None, term_label=None, regime=None,
                   skew=None, garch_vol=None, forecast_method=None, holding_days=20,
                   rv_20=None, iv_pctl=None, skew_penalty=None, signal_reason=None,
                   earnings_days=None, fomc_days=None):
    """Log today's prediction for a ticker. One prediction per ticker per day per holding period."""
    today = datetime.now().strftime("%Y-%m-%d")
    row = {
        "ticker": ticker, "date": today, "signal": signal,
        "spot_price": spot_price, "atm_iv": atm_iv, "rv_forecast": rv_forecast,
        "vrp": vrp, "iv_rank": iv_rank, "term_label": term_label,
        "regime": regime, "skew": skew, "garch_vol": garch_vol,
        "forecast_method": forecast_method, "holding_days": holding_days,
        "rv_20": rv_20, "iv_pctl": iv_pctl, "skew_penalty": skew_penalty,
        "signal_reason": signal_reason, "earnings_days": earnings_days,
        "fomc_days": fomc_days, "scored": 0,
    }
    sb = _get_supabase()
    if sb:
        sb.table("predictions").upsert(row, on_conflict="ticker,date,holding_days").execute()
    else:
        conn = _get_sqlite()
        cols = ", ".join(row.keys())
        placeholders = ", ".join(["?"] * len(row))
        conn.execute(
            f"INSERT OR REPLACE INTO predictions ({cols}) VALUES ({placeholders})",
            tuple(row.values()),
        )
        conn.commit()
        conn.close()


def score_pending_predictions():
    """
    Check all unscored predictions where enough time has passed.
    Fetches actual stock prices and scores whether the signal was correct.
    Returns number of predictions scored.
    """
    import yf_proxy
    import pandas as pd
    import numpy as np

    conn = _get_sqlite()
    rows = conn.execute(
        "SELECT * FROM predictions WHERE scored = 0"
    ).fetchall()
    predictions = [dict(r) for r in rows]
    conn.close()

    scored_count = 0
    for pred in predictions:
        pred_date = datetime.strptime(pred["date"], "%Y-%m-%d")
        holding_days = pred.get("holding_days", 20)
        outcome_date = pred_date + timedelta(days=holding_days)

        # Only score if enough time has passed
        if datetime.now() < outcome_date + timedelta(days=1):
            continue

        try:
            hist = yf_proxy.get_stock_history(pred["ticker"], period="3mo")
            if hist.empty:
                continue

            hist.index = pd.to_datetime(hist.index)

            # Find the closest trading day to the outcome date
            mask = hist.index >= pd.Timestamp(outcome_date.strftime("%Y-%m-%d"))
            if mask.sum() == 0:
                # Outcome date hasn't been reached in market data yet
                continue
            outcome_row = hist[mask].iloc[0]
            outcome_price = float(outcome_row["Close"])

            # Calculate return and realized vol over the holding period
            pred_mask = hist.index >= pd.Timestamp(pred["date"])
            holding_hist = hist[pred_mask].head(holding_days + 1)
            outcome_return = (outcome_price - pred["spot_price"]) / pred["spot_price"] * 100

            # Realized vol over the holding period
            if len(holding_hist) >= 5:
                log_ret = np.log(holding_hist["Close"] / holding_hist["Close"].shift(1)).dropna()
                outcome_rv = float(log_ret.std() * np.sqrt(252) * 100)
            else:
                outcome_rv = None

            # Did the option seller win?
            # Seller wins if the stock didn't move more than the expected move (IV/sqrt(252/holding))
            iv = pred.get("atm_iv") or pred.get("rv_forecast") or 25
            expected_move_pct = iv / 100 * np.sqrt(holding_days / 252) * 100
            actual_move_pct = abs(outcome_return)
            seller_won = 1 if actual_move_pct < expected_move_pct else 0

            # Update the prediction
            conn = _get_sqlite()
            conn.execute("""
                UPDATE predictions SET
                    outcome_price = ?, outcome_return = ?, outcome_rv = ?,
                    outcome_date = ?, scored = 1, seller_won = ?
                WHERE id = ?
            """, (outcome_price, outcome_return, outcome_rv,
                  outcome_date.strftime("%Y-%m-%d"), seller_won, pred["id"]))
            conn.commit()
            conn.close()
            scored_count += 1

        except Exception as e:
            print(f"[predictions] Error scoring {pred['ticker']} {pred['date']}: {e}")
            continue

    return scored_count


def get_prediction_scorecard():
    """
    Get scored predictions grouped by signal type.
    Returns dict with accuracy stats per signal.
    """
    import pandas as pd
    conn = _get_sqlite()
    df = pd.read_sql_query(
        "SELECT * FROM predictions WHERE scored = 1 ORDER BY date",
        conn
    )
    conn.close()

    if df.empty:
        return None

    results = {
        "total_predictions": len(df),
        "total_correct": int(df["seller_won"].sum()),
        "overall_accuracy": float(df["seller_won"].mean() * 100),
        "by_signal": {},
        "by_regime": {},
        "by_ticker": {},
        "recent": df.tail(20).to_dict("records"),
    }

    # By signal
    for sig in ["GREEN", "YELLOW", "RED"]:
        subset = df[df["signal"] == sig]
        if subset.empty:
            continue
        results["by_signal"][sig] = {
            "count": len(subset),
            "accuracy": float(subset["seller_won"].mean() * 100),
            "avg_return": float(subset["outcome_return"].mean()),
            "avg_vrp": float(subset["vrp"].mean()) if subset["vrp"].notna().any() else None,
            "worst_return": float(subset["outcome_return"].min()),
            "best_return": float(subset["outcome_return"].max()),
        }

    # By regime
    for reg in df["regime"].dropna().unique():
        subset = df[df["regime"] == reg]
        if len(subset) < 3:
            continue
        results["by_regime"][reg] = {
            "count": len(subset),
            "accuracy": float(subset["seller_won"].mean() * 100),
            "avg_return": float(subset["outcome_return"].mean()),
        }

    # By ticker
    for tick in df["ticker"].unique():
        subset = df[df["ticker"] == tick]
        results["by_ticker"][tick] = {
            "count": len(subset),
            "accuracy": float(subset["seller_won"].mean() * 100),
            "avg_return": float(subset["outcome_return"].mean()),
        }

    return results


def get_pending_predictions_count():
    """How many predictions are waiting to be scored."""
    conn = _get_sqlite()
    row = conn.execute("SELECT COUNT(*) as cnt FROM predictions WHERE scored = 0").fetchone()
    conn.close()
    return dict(row)["cnt"]


def get_all_predictions():
    """Get all predictions for display."""
    import pandas as pd
    conn = _get_sqlite()
    df = pd.read_sql_query("SELECT * FROM predictions ORDER BY date DESC", conn)
    conn.close()
    return df
