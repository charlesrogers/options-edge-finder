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
        ("predictions", "expected_move_pct", "REAL"),
        ("predictions", "actual_move_pct", "REAL"),
        ("predictions", "premium_estimate", "REAL"),
        ("predictions", "pnl_estimate", "REAL"),
        ("predictions", "pnl_pct", "REAL"),
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

            update_data = {
                "outcome_price": outcome_price,
                "outcome_return": round(outcome_return, 4),
                "outcome_rv": round(outcome_rv, 2) if outcome_rv else None,
                "outcome_date": outcome_date.strftime("%Y-%m-%d"),
                "scored": 1,
                "seller_won": seller_won,
                "expected_move_pct": round(expected_move_pct, 4),
                "actual_move_pct": round(actual_move_pct, 4),
                "premium_estimate": round(premium_estimate, 4),
                "pnl_estimate": round(pnl_estimate, 4),
                "pnl_pct": round(pnl_pct, 4),
            }

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

    results = {
        "total_predictions": len(df),
        "total_correct": int(df["seller_won"].sum()),
        "overall_accuracy": float(df["seller_won"].mean() * 100),
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
