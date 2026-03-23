"""
Database layer. Uses Supabase (Postgres) when configured, falls back to local SQLite.
Includes prediction logging for scorecard verification.
Environment variables:
  SUPABASE_URL - your Supabase project URL
  SUPABASE_KEY - your Supabase anon/service key
"""

import os
import json
import math
import sqlite3
from datetime import datetime, timedelta


def _sanitize_row(row):
    """Replace NaN/Infinity floats with None — Supabase JSON can't handle them."""
    cleaned = {}
    for k, v in row.items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            cleaned[k] = None
        else:
            cleaned[k] = v
    return cleaned


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
        ("predictions", "expected_move_pct", "REAL"),
        ("predictions", "actual_move_pct", "REAL"),
        ("predictions", "premium_estimate", "REAL"),
        ("predictions", "pnl_estimate", "REAL"),
        ("predictions", "pnl_pct", "REAL"),
        ("predictions", "iv_at_scoring", "REAL"),
        ("predictions", "clv_realized", "REAL"),
    ]
    for table, col, coltype in _pred_migrate:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
        except Exception:
            pass
    # Signal graveyard — tracks all tested hypotheses (pass + fail) for Deflated Sharpe
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_graveyard (
            signal_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            tier INTEGER,
            hypothesis TEXT,
            pre_registered_date TEXT NOT NULL,
            tested_date TEXT,
            status TEXT DEFAULT 'untested',
            layer_reached INTEGER DEFAULT 0,
            best_sharpe REAL,
            best_clv REAL,
            n_trades INTEGER,
            failure_reason TEXT,
            notes TEXT
        )
    """)
    # Vol surface snapshots — SABR params per ticker/expiry/date
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vol_surface_snapshots (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            expiration TEXT NOT NULL,
            sabr_alpha REAL,
            sabr_rho REAL,
            sabr_nu REAL,
            sabr_beta REAL DEFAULT 0.5,
            atm_iv REAL,
            calibration_rmse REAL,
            n_strikes INTEGER,
            dte INTEGER,
            richest_strike REAL,
            richest_vrp REAL,
            PRIMARY KEY (ticker, date, expiration)
        )
    """)
    # Option chain snapshots — full chain data per ticker/date/expiry/strike
    conn.execute("""
        CREATE TABLE IF NOT EXISTS option_chain_snapshots (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            expiration TEXT NOT NULL,
            option_type TEXT NOT NULL,
            strike REAL NOT NULL,
            bid REAL,
            ask REAL,
            last_price REAL,
            volume INTEGER,
            open_interest INTEGER,
            implied_volatility REAL,
            in_the_money INTEGER,
            PRIMARY KEY (ticker, date, expiration, option_type, strike)
        )
    """)
    # Portfolio holdings — shares owned per ticker
    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_holdings (
            ticker TEXT PRIMARY KEY,
            shares INTEGER DEFAULT 0,
            avg_cost REAL,
            last_updated TEXT
        )
    """)
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================
# PORTFOLIO HOLDINGS
# ============================================================

def save_holding(ticker, shares, avg_cost=None):
    """Save or update share count for a ticker."""
    today = datetime.now().strftime("%Y-%m-%d")
    row = _sanitize_row({
        "ticker": ticker.upper(), "shares": int(shares),
        "avg_cost": avg_cost, "last_updated": today,
    })
    sb = _get_supabase()
    if sb:
        sb.table("portfolio_holdings").upsert(row, on_conflict="ticker").execute()
    else:
        conn = _get_sqlite()
        conn.execute(
            "INSERT OR REPLACE INTO portfolio_holdings (ticker, shares, avg_cost, last_updated) "
            "VALUES (?, ?, ?, ?)",
            (row["ticker"], row["shares"], row["avg_cost"], row["last_updated"]),
        )
        conn.commit()
        conn.close()


def get_holdings():
    """Get all portfolio holdings as a dict {ticker: {shares, avg_cost}}."""
    sb = _get_supabase()
    if sb:
        resp = sb.table("portfolio_holdings").select("*").execute()
        data = resp.data or []
    else:
        conn = _get_sqlite()
        try:
            rows = conn.execute("SELECT * FROM portfolio_holdings").fetchall()
            data = [dict(r) for r in rows]
        except Exception:
            data = []
        conn.close()
    return {r["ticker"]: {"shares": r.get("shares", 0), "avg_cost": r.get("avg_cost")}
            for r in data if r.get("shares", 0) > 0}


def delete_holding(ticker):
    """Remove a ticker from holdings."""
    sb = _get_supabase()
    if sb:
        sb.table("portfolio_holdings").delete().eq("ticker", ticker.upper()).execute()
    else:
        conn = _get_sqlite()
        conn.execute("DELETE FROM portfolio_holdings WHERE ticker = ?", (ticker.upper(),))
        conn.commit()
        conn.close()


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
    row = _sanitize_row({
        "ticker": ticker, "date": today, "atm_iv": atm_iv,
        "spot_price": spot_price, "front_exp": front_exp,
        "rv_20": rv_20, "term_label": term_label,
        "put_25d_iv": put_25d_iv, "call_25d_iv": call_25d_iv,
        "rv_10": rv_10, "rv_30": rv_30, "rv_60": rv_60, "yz_20": yz_20,
        "garch_vol": garch_vol, "iv_rank": iv_rank, "iv_pctl": iv_pctl,
        "vrp": vrp, "signal": signal, "regime": regime, "skew": skew,
        "fomc_days": fomc_days, "earnings_days": earnings_days,
    })
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
# IV LOOKUP (for CLV computation)
# ============================================================

def get_iv_on_date(ticker, date_str):
    """
    Fetch ATM IV for a ticker on or near a specific date.
    Looks in iv_snapshots for exact date, then tries up to 5 prior days.
    Returns atm_iv float or None.
    """
    import pandas as pd
    target = datetime.strptime(date_str, "%Y-%m-%d") if isinstance(date_str, str) else date_str
    sb = _get_supabase()
    # Try exact date first, then look back up to 5 days
    for offset in range(6):
        check_date = (target - timedelta(days=offset)).strftime("%Y-%m-%d")
        if sb:
            resp = sb.table("iv_snapshots").select("atm_iv").eq("ticker", ticker).eq("date", check_date).execute()
            if resp.data and resp.data[0].get("atm_iv") is not None:
                return float(resp.data[0]["atm_iv"])
        else:
            conn = _get_sqlite()
            row = conn.execute(
                "SELECT atm_iv FROM iv_snapshots WHERE ticker = ? AND date = ?",
                (ticker, check_date),
            ).fetchone()
            conn.close()
            if row and row["atm_iv"] is not None:
                return float(row["atm_iv"])
    return None


# ============================================================
# OPTION CHAIN SNAPSHOTS — full chain data for backtesting
# ============================================================

def record_chain_snapshot(ticker, expiry, chain):
    """
    Store full option chain (all strikes, bids, asks, IVs) for a ticker/expiry.
    This is the raw data needed for proper backtesting with real option prices.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    sb = _get_supabase()
    rows = []

    for opt_type, df in [("call", chain.calls), ("put", chain.puts)]:
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            r = _sanitize_row({
                "ticker": ticker,
                "date": today,
                "expiration": expiry,
                "option_type": opt_type,
                "strike": float(row.get("strike", 0)),
                "bid": float(row.get("bid", 0) or 0),
                "ask": float(row.get("ask", 0) or 0),
                "last_price": float(row.get("lastPrice", 0) or 0),
                "volume": int(row.get("volume", 0) or 0),
                "open_interest": int(row.get("openInterest", 0) or 0),
                "implied_volatility": float(row.get("impliedVolatility", 0) or 0),
                "in_the_money": 1 if row.get("inTheMoney") else 0,
            })
            if r["strike"] > 0:
                rows.append(r)

    if not rows:
        return 0

    if sb:
        # Batch upsert (Supabase supports bulk)
        for i in range(0, len(rows), 50):
            batch = rows[i:i + 50]
            try:
                sb.table("option_chain_snapshots").upsert(
                    batch, on_conflict="ticker,date,expiration,option_type,strike"
                ).execute()
            except Exception:
                # Fall back to individual inserts
                for r in batch:
                    try:
                        sb.table("option_chain_snapshots").upsert(
                            r, on_conflict="ticker,date,expiration,option_type,strike"
                        ).execute()
                    except Exception:
                        pass
    else:
        conn = _get_sqlite()
        for r in rows:
            cols = ", ".join(r.keys())
            placeholders = ", ".join(["?"] * len(r))
            try:
                conn.execute(
                    f"INSERT OR REPLACE INTO option_chain_snapshots ({cols}) VALUES ({placeholders})",
                    tuple(r.values()),
                )
            except Exception:
                pass
        conn.commit()
        conn.close()

    return len(rows)


# ============================================================
# VOL SURFACE SNAPSHOTS — SABR params per ticker/expiry/date
# ============================================================

def record_surface(ticker, expiry, sabr_params, richest_strike=None, richest_vrp=None):
    """Store SABR calibration results for one ticker/expiration."""
    today = datetime.now().strftime("%Y-%m-%d")
    if not sabr_params:
        return
    row = _sanitize_row({
        "ticker": ticker, "date": today, "expiration": expiry,
        "sabr_alpha": sabr_params.get("alpha"),
        "sabr_rho": sabr_params.get("rho"),
        "sabr_nu": sabr_params.get("nu"),
        "sabr_beta": sabr_params.get("beta", 0.5),
        "atm_iv": sabr_params.get("atm_iv"),
        "calibration_rmse": sabr_params.get("rmse"),
        "n_strikes": sabr_params.get("n_strikes"),
        "dte": sabr_params.get("dte"),
        "richest_strike": richest_strike,
        "richest_vrp": richest_vrp,
    })
    sb = _get_supabase()
    if sb:
        sb.table("vol_surface_snapshots").upsert(
            row, on_conflict="ticker,date,expiration"
        ).execute()
    else:
        conn = _get_sqlite()
        cols = ", ".join(row.keys())
        placeholders = ", ".join(["?"] * len(row))
        conn.execute(
            f"INSERT OR REPLACE INTO vol_surface_snapshots ({cols}) VALUES ({placeholders})",
            tuple(row.values()),
        )
        conn.commit()
        conn.close()


# ============================================================
# SIGNAL GRAVEYARD — hypothesis tracking for Deflated Sharpe
# ============================================================

def register_hypothesis(signal_id, name, tier, hypothesis):
    """Pre-register a hypothesis BEFORE testing. Returns True on success."""
    today = datetime.now().strftime("%Y-%m-%d")
    row = {
        "signal_id": signal_id, "name": name, "tier": tier,
        "hypothesis": hypothesis, "pre_registered_date": today,
        "status": "untested", "layer_reached": 0,
    }
    sb = _get_supabase()
    if sb:
        sb.table("signal_graveyard").upsert(row, on_conflict="signal_id").execute()
    else:
        conn = _get_sqlite()
        conn.execute(
            "INSERT OR REPLACE INTO signal_graveyard "
            "(signal_id, name, tier, hypothesis, pre_registered_date, status, layer_reached) "
            "VALUES (?, ?, ?, ?, ?, 'untested', 0)",
            (signal_id, name, tier, hypothesis, today),
        )
        conn.commit()
        conn.close()
    return True


def update_hypothesis_result(signal_id, status, layer_reached,
                              best_sharpe=None, best_clv=None, n_trades=None,
                              failure_reason=None, notes=None):
    """Record test results for a hypothesis."""
    today = datetime.now().strftime("%Y-%m-%d")
    update = {
        "status": status, "layer_reached": layer_reached,
        "tested_date": today, "best_sharpe": best_sharpe,
        "best_clv": best_clv, "n_trades": n_trades,
        "failure_reason": failure_reason, "notes": notes,
    }
    sb = _get_supabase()
    if sb:
        sb.table("signal_graveyard").update(update).eq("signal_id", signal_id).execute()
    else:
        conn = _get_sqlite()
        cols = ", ".join(f"{k} = ?" for k in update.keys())
        vals = list(update.values()) + [signal_id]
        conn.execute(f"UPDATE signal_graveyard SET {cols} WHERE signal_id = ?", vals)
        conn.commit()
        conn.close()


def get_graveyard():
    """Return all signal graveyard entries as a DataFrame."""
    import pandas as pd
    sb = _get_supabase()
    if sb:
        resp = sb.table("signal_graveyard").select("*").order("pre_registered_date").execute()
        return pd.DataFrame(resp.data) if resp.data else pd.DataFrame()
    else:
        conn = _get_sqlite()
        df = pd.read_sql_query("SELECT * FROM signal_graveyard ORDER BY pre_registered_date", conn)
        conn.close()
        return df


def get_graveyard_count():
    """Total hypotheses ever tested (for Deflated Sharpe denominator)."""
    sb = _get_supabase()
    if sb:
        resp = sb.table("signal_graveyard").select("signal_id").neq("status", "untested").execute()
        return len(resp.data) if resp.data else 0
    else:
        conn = _get_sqlite()
        count = conn.execute(
            "SELECT COUNT(*) FROM signal_graveyard WHERE status != 'untested'"
        ).fetchone()[0]
        conn.close()
        return count


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
    row = _sanitize_row({
        "ticker": ticker, "date": today, "signal": signal,
        "spot_price": spot_price, "atm_iv": atm_iv, "rv_forecast": rv_forecast,
        "vrp": vrp, "iv_rank": iv_rank, "term_label": term_label,
        "regime": regime, "skew": skew, "garch_vol": garch_vol,
        "forecast_method": forecast_method, "holding_days": holding_days,
        "rv_20": rv_20, "iv_pctl": iv_pctl, "skew_penalty": skew_penalty,
        "signal_reason": signal_reason, "earnings_days": earnings_days,
        "fomc_days": fomc_days, "scored": 0,
    })
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

    sb = _get_supabase()
    if sb:
        resp = sb.table("predictions").select("*").eq("scored", 0).execute()
        predictions = resp.data or []
    else:
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
            # Seller wins if the stock didn't move more than the expected move
            iv = pred.get("atm_iv") or pred.get("rv_forecast") or 25
            expected_move_pct = iv / 100 * np.sqrt(holding_days / 252) * 100
            actual_move_pct = abs(outcome_return)
            seller_won = 1 if actual_move_pct < expected_move_pct else 0

            # P&L estimation (approximate ATM straddle)
            # Premium ≈ IV * sqrt(T) * spot (ATM straddle approximation)
            spot = pred["spot_price"]
            premium_estimate = iv / 100 * np.sqrt(holding_days / 252) * spot
            actual_move_dollars = abs(outcome_price - spot)

            if actual_move_dollars <= premium_estimate:
                # Seller keeps full premium (option expires worthless or partial)
                pnl_estimate = premium_estimate - actual_move_dollars
            else:
                # Seller loses: premium minus intrinsic loss
                pnl_estimate = premium_estimate - actual_move_dollars

            pnl_pct = pnl_estimate / spot * 100

            # CLV computation — the primary edge metric
            outcome_date_str = outcome_date.strftime("%Y-%m-%d")
            iv_at_scoring = get_iv_on_date(pred["ticker"], outcome_date_str)
            atm_iv_entry = pred.get("atm_iv")
            clv_realized = None
            if atm_iv_entry and outcome_rv and atm_iv_entry > 0:
                clv_realized = round((atm_iv_entry - outcome_rv) / atm_iv_entry, 6)

            update_data = _sanitize_row({
                "outcome_price": outcome_price,
                "outcome_return": round(outcome_return, 4),
                "outcome_rv": round(outcome_rv, 2) if outcome_rv else None,
                "outcome_date": outcome_date_str,
                "scored": 1,
                "seller_won": seller_won,
                "expected_move_pct": round(expected_move_pct, 4),
                "actual_move_pct": round(actual_move_pct, 4),
                "premium_estimate": round(premium_estimate, 4),
                "pnl_estimate": round(pnl_estimate, 4),
                "pnl_pct": round(pnl_pct, 4),
                "iv_at_scoring": round(iv_at_scoring, 4) if iv_at_scoring else None,
                "clv_realized": clv_realized,
            })

            if sb:
                sb.table("predictions").update(update_data).eq("id", pred["id"]).execute()
            else:
                conn = _get_sqlite()
                cols = ", ".join(f"{k} = ?" for k in update_data.keys())
                vals = list(update_data.values()) + [pred["id"]]
                conn.execute(f"UPDATE predictions SET {cols} WHERE id = ?", vals)
                conn.commit()
                conn.close()
            scored_count += 1
            print(f"[scoring] {pred['ticker']} {pred['date']}: return={outcome_return:+.1f}%, seller_won={seller_won}")

        except Exception as e:
            print(f"[scoring] Error scoring {pred['ticker']} {pred['date']}: {e}")
            continue

    return scored_count


def get_prediction_scorecard():
    """
    Get scored predictions grouped by signal type.
    Returns dict with accuracy stats per signal, plus baseline comparison
    and rolling accuracy for tracking improvement over time.
    """
    import pandas as pd

    sb = _get_supabase()
    if sb:
        resp = sb.table("predictions").select("*").eq("scored", 1).order("date").execute()
        data = resp.data or []
        df = pd.DataFrame(data) if data else pd.DataFrame()
    else:
        conn = _get_sqlite()
        df = pd.read_sql_query(
            "SELECT * FROM predictions WHERE scored = 1 ORDER BY date",
            conn
        )
        conn.close()

    if df.empty:
        return None

    # Check if P&L columns exist
    has_pnl = "pnl_pct" in df.columns and df["pnl_pct"].notna().any()

    # Trade recommendation counts (across ALL predictions, not just scored)
    sb2 = _get_supabase()
    if sb2:
        all_resp = sb2.table("predictions").select("signal").execute()
        all_signals = [r["signal"] for r in (all_resp.data or [])]
    else:
        conn2 = _get_sqlite()
        all_signals = [r["signal"] for r in conn2.execute("SELECT signal FROM predictions").fetchall()]
        conn2.close()
    total_all = len(all_signals)
    total_recommended = sum(1 for s in all_signals if s == "GREEN")
    total_cautioned = sum(1 for s in all_signals if s == "YELLOW")
    total_avoided = sum(1 for s in all_signals if s == "RED")

    results = {
        "total_predictions": len(df),
        "total_correct": int(df["seller_won"].sum()),
        "overall_accuracy": float(df["seller_won"].mean() * 100),
        "total_signals_generated": total_all,
        "total_recommended": total_recommended,
        "total_cautioned": total_cautioned,
        "total_avoided": total_avoided,
        "recommendation_rate": round(total_recommended / total_all * 100, 1) if total_all else 0,
        "by_signal": {},
        "by_regime": {},
        "by_ticker": {},
        "recent": df.tail(20).to_dict("records"),
    }

    # --- P&L summary (the real measure) ---
    if has_pnl:
        pnl = df["pnl_pct"].dropna()
        results["pnl_summary"] = {
            "avg_pnl_pct": round(float(pnl.mean()), 4),
            "median_pnl_pct": round(float(pnl.median()), 4),
            "total_pnl_pct": round(float(pnl.sum()), 4),
            "std_pnl_pct": round(float(pnl.std()), 4),
            "skewness": round(float(pnl.skew()), 4),
            "kurtosis": round(float(pnl.kurtosis()), 4),
            "worst_pnl_pct": round(float(pnl.min()), 4),
            "best_pnl_pct": round(float(pnl.max()), 4),
            "pct_positive": round(float((pnl > 0).mean() * 100), 2),
            "avg_win_pct": round(float(pnl[pnl > 0].mean()), 4) if (pnl > 0).any() else 0,
            "avg_loss_pct": round(float(pnl[pnl <= 0].mean()), 4) if (pnl <= 0).any() else 0,
            "win_loss_ratio": round(
                abs(float(pnl[pnl > 0].mean()) / float(pnl[pnl <= 0].mean())), 2
            ) if (pnl > 0).any() and (pnl <= 0).any() and pnl[pnl <= 0].mean() != 0 else None,
        }
    else:
        results["pnl_summary"] = None

    # --- CLV summary (the primary edge metric) ---
    has_clv = "clv_realized" in df.columns and df["clv_realized"].notna().any()
    if has_clv:
        clv = df["clv_realized"].dropna()
        results["rvrp_summary"] = {
            "avg_rvrp": round(float(clv.mean()), 6),
            "median_rvrp": round(float(clv.median()), 6),
            "std_rvrp": round(float(clv.std()), 6),
            "pct_positive_rvrp": round(float((clv > 0).mean() * 100), 2),
            "count": len(clv),
            "best_clv": round(float(clv.max()), 6),
            "worst_rvrp": round(float(clv.min()), 6),
        }
        # CLV by signal
        rvrp_by_signal = {}
        for sig in ["GREEN", "YELLOW", "RED"]:
            sig_clv = df[df["signal"] == sig]["clv_realized"].dropna()
            if len(sig_clv) > 0:
                rvrp_by_signal[sig] = {
                    "avg_rvrp": round(float(sig_clv.mean()), 6),
                    "median_rvrp": round(float(sig_clv.median()), 6),
                    "count": len(sig_clv),
                    "pct_positive": round(float((sig_clv > 0).mean() * 100), 2),
                }
        results["rvrp_by_signal"] = rvrp_by_signal
    else:
        results["rvrp_summary"] = None
        results["rvrp_by_signal"] = {}

    # --- Baseline comparison ---
    results["baseline_accuracy"] = results["overall_accuracy"]

    # --- Signal separation (the core test) ---
    for sig in ["GREEN", "YELLOW", "RED"]:
        subset = df[df["signal"] == sig]
        if subset.empty:
            continue
        sig_stats = {
            "count": len(subset),
            "accuracy": float(subset["seller_won"].mean() * 100),
            "avg_return": float(subset["outcome_return"].mean()),
            "avg_vrp": float(subset["vrp"].mean()) if "vrp" in subset.columns and subset["vrp"].notna().any() else None,
            "worst_return": float(subset["outcome_return"].min()),
            "best_return": float(subset["outcome_return"].max()),
        }
        # P&L by signal
        if has_pnl and subset["pnl_pct"].notna().any():
            spnl = subset["pnl_pct"].dropna()
            sig_stats["avg_pnl_pct"] = round(float(spnl.mean()), 4)
            sig_stats["median_pnl_pct"] = round(float(spnl.median()), 4)
            sig_stats["worst_pnl_pct"] = round(float(spnl.min()), 4)
            sig_stats["total_pnl_pct"] = round(float(spnl.sum()), 4)
            sig_stats["skewness"] = round(float(spnl.skew()), 4) if len(spnl) >= 3 else None
        results["by_signal"][sig] = sig_stats

    # --- Rolling accuracy + P&L (is the model improving over time?) ---
    df["date_dt"] = pd.to_datetime(df["date"])
    df = df.sort_values("date_dt")
    rolling_windows = []
    if len(df) >= 20:
        window = min(30, len(df))
        for i in range(window, len(df) + 1):
            window_df = df.iloc[i - window:i]
            entry = {
                "end_date": str(window_df["date"].iloc[-1]),
                "accuracy": float(window_df["seller_won"].mean() * 100),
                "count": len(window_df),
            }
            if has_pnl and window_df["pnl_pct"].notna().any():
                entry["avg_pnl_pct"] = float(window_df["pnl_pct"].dropna().mean())
            rolling_windows.append(entry)
    results["rolling_accuracy"] = rolling_windows

    # --- Cumulative P&L curve ---
    if has_pnl:
        cum_pnl = df["pnl_pct"].dropna().cumsum()
        results["cumulative_pnl"] = [
            {"date": str(df.iloc[i]["date"]), "cum_pnl_pct": round(float(v), 4)}
            for i, v in enumerate(cum_pnl) if not pd.isna(v)
        ]
    else:
        results["cumulative_pnl"] = []

    # --- VRP as predictor (does higher VRP = better outcomes?) ---
    if "vrp" in df.columns and df["vrp"].notna().sum() >= 10:
        high_vrp = df[df["vrp"] >= 5]
        low_vrp = df[df["vrp"] < 5]
        vrp_result = {
            "high_vrp_accuracy": float(high_vrp["seller_won"].mean() * 100) if len(high_vrp) >= 5 else None,
            "high_vrp_count": len(high_vrp),
            "low_vrp_accuracy": float(low_vrp["seller_won"].mean() * 100) if len(low_vrp) >= 5 else None,
            "low_vrp_count": len(low_vrp),
        }
        if has_pnl:
            if len(high_vrp) >= 5 and high_vrp["pnl_pct"].notna().any():
                vrp_result["high_vrp_avg_pnl"] = round(float(high_vrp["pnl_pct"].dropna().mean()), 4)
            if len(low_vrp) >= 5 and low_vrp["pnl_pct"].notna().any():
                vrp_result["low_vrp_avg_pnl"] = round(float(low_vrp["pnl_pct"].dropna().mean()), 4)
        results["vrp_analysis"] = vrp_result
    else:
        results["vrp_analysis"] = None

    # By regime
    if "regime" in df.columns:
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


def reset_predictions_missing_pnl():
    """Reset scored predictions that are missing P&L data so they get re-scored."""
    sb = _get_supabase()
    if sb:
        # Find scored predictions missing pnl_pct
        resp = sb.table("predictions").select("id").eq("scored", 1).is_("pnl_pct", "null").execute()
        ids = [r["id"] for r in (resp.data or [])]
        if not ids:
            return 0
        for pid in ids:
            sb.table("predictions").update({
                "scored": 0,
                "outcome_price": None,
                "outcome_return": None,
                "seller_won": None,
            }).eq("id", pid).execute()
        print(f"[reset] Reset {len(ids)} predictions missing P&L data for re-scoring")
        return len(ids)
    else:
        conn = _get_sqlite()
        cur = conn.execute(
            "UPDATE predictions SET scored = 0, outcome_price = NULL, outcome_return = NULL, seller_won = NULL "
            "WHERE scored = 1 AND pnl_pct IS NULL"
        )
        count = cur.rowcount
        conn.commit()
        conn.close()
        if count:
            print(f"[reset] Reset {count} predictions missing P&L data for re-scoring")
        return count


def get_pending_predictions_count():
    """How many predictions are waiting to be scored."""
    sb = _get_supabase()
    if sb:
        resp = sb.table("predictions").select("id", count="exact").eq("scored", 0).execute()
        return resp.count or 0
    else:
        conn = _get_sqlite()
        row = conn.execute("SELECT COUNT(*) as cnt FROM predictions WHERE scored = 0").fetchone()
        conn.close()
        return dict(row)["cnt"]


def get_all_predictions():
    """Get all predictions for display."""
    import pandas as pd
    sb = _get_supabase()
    if sb:
        resp = sb.table("predictions").select("*").order("date", desc=True).execute()
        return pd.DataFrame(resp.data) if resp.data else pd.DataFrame()
    else:
        conn = _get_sqlite()
        df = pd.read_sql_query("SELECT * FROM predictions ORDER BY date DESC", conn)
        conn.close()
        return df
