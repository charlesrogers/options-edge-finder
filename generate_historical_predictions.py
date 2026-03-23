"""
Generate historical scored predictions from Yahoo Finance OHLCV data.

This uses the existing backtest engine (analytics.backtest_vrp_strategy)
to reconstruct what the system WOULD have signaled on historical dates,
then scores them immediately since outcomes have already occurred.

Produces hundreds of scored predictions with Realized VRP right now,
no need to wait for the 20-day holding period.

Usage:
  python generate_historical_predictions.py
  # Or via GitHub Actions with Supabase credentials
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pandas as pd
import db


# Tickers to generate predictions for (the 5 basket test tickers + key ETFs)
TICKERS = [
    "SPY", "QQQ", "IWM", "DIA",
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "JPM", "GS", "XOM", "UNH", "JNJ",
    "GLD", "TLT", "XLF", "XLE",
]


def fetch_history(ticker, period="2y"):
    """Fetch OHLCV from Yahoo Finance."""
    try:
        import yf_proxy
        hist = yf_proxy.get_stock_history(ticker, period=period)
        if not hist.empty:
            return hist
    except Exception:
        pass

    # Fallback to direct yfinance
    try:
        import yfinance as yf
        hist = yf.download(ticker, period=period, progress=False)
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        return hist
    except Exception:
        return pd.DataFrame()


def generate_predictions_for_ticker(ticker, hist, holding_period=20):
    """
    Run backtest on historical data and produce scored prediction records.

    Returns list of dicts ready for Supabase insertion.
    """
    from analytics import backtest_vrp_strategy

    bt = backtest_vrp_strategy(hist, window=20, holding_period=holding_period)
    if bt is None or bt.empty:
        return []

    # Sample every `holding_period` days to avoid overlapping trades
    bt = bt.iloc[::holding_period].copy()

    predictions = []
    for _, row in bt.iterrows():
        date_str = str(row["date"])[:10]
        iv = row.get("iv_proxy")
        rv_fwd = row.get("rv_actual")
        vrp = row.get("vrp_proxy")
        signal = row.get("signal", "YELLOW")
        spot = row.get("close")
        seller_won = 1 if row.get("seller_wins") else 0
        pnl_pct = row.get("pnl_pct")
        expected_move = row.get("expected_move_pct")
        actual_move = row.get("actual_move_pct")
        premium = row.get("premium_pct")

        # Compute Realized VRP
        clv_realized = None
        if expected_move and actual_move and expected_move > 0:
            clv_realized = round((expected_move - actual_move) / expected_move, 6)

        # Outcome date (calendar days)
        from datetime import datetime, timedelta
        pred_date = datetime.strptime(date_str, "%Y-%m-%d")
        outcome_date = pred_date + timedelta(days=holding_period)

        # Outcome price (approximate from forward return)
        fwd_ret = row.get("fwd_return", 0) or 0
        outcome_price = spot * (1 + fwd_ret) if spot else None
        outcome_return = fwd_ret * 100 if fwd_ret else None

        predictions.append({
            "ticker": ticker,
            "date": date_str,
            "signal": signal,
            "spot_price": round(float(spot), 2) if spot else None,
            "atm_iv": round(float(iv), 4) if iv else None,
            "rv_forecast": round(float(row.get("rv_backward", 0)), 4),
            "vrp": round(float(vrp), 4) if vrp else None,
            "holding_days": holding_period,
            "scored": 1,
            "seller_won": seller_won,
            "outcome_price": round(float(outcome_price), 2) if outcome_price else None,
            "outcome_return": round(float(outcome_return), 4) if outcome_return is not None else None,
            "outcome_rv": round(float(rv_fwd), 4) if rv_fwd else None,
            "outcome_date": outcome_date.strftime("%Y-%m-%d"),
            "expected_move_pct": round(float(expected_move * 100), 4) if expected_move else None,
            "actual_move_pct": round(float(actual_move * 100), 4) if actual_move else None,
            "premium_estimate": round(float(premium), 4) if premium else None,
            "pnl_pct": round(float(pnl_pct), 4) if pnl_pct else None,
            "clv_realized": clv_realized,
            "forecast_method": "backtest_historical",
            "signal_reason": f"Historical backtest reconstruction (IV={iv:.1f}, RV_fwd={rv_fwd:.1f})" if iv and rv_fwd else None,
        })

    return predictions


def insert_predictions(predictions, batch_size=50):
    """Insert predictions into Supabase/SQLite."""
    sb = db._get_supabase()
    inserted = 0

    for i in range(0, len(predictions), batch_size):
        batch = predictions[i:i + batch_size]
        for pred in batch:
            pred = db._sanitize_row(pred)
            try:
                if sb:
                    sb.table("predictions").upsert(
                        pred, on_conflict="ticker,date,holding_days"
                    ).execute()
                else:
                    conn = db._get_sqlite()
                    cols = ", ".join(pred.keys())
                    placeholders = ", ".join(["?"] * len(pred))
                    conn.execute(
                        f"INSERT OR REPLACE INTO predictions ({cols}) VALUES ({placeholders})",
                        tuple(pred.values()),
                    )
                    conn.commit()
                    conn.close()
                inserted += 1
            except Exception as e:
                print(f"  Error inserting {pred.get('ticker')} {pred.get('date')}: {e}")
                continue

        if (i + batch_size) % 200 == 0:
            print(f"  Progress: {min(i + batch_size, len(predictions))}/{len(predictions)}")

    return inserted


def main():
    print("=" * 60)
    print("Generating Historical Scored Predictions")
    print("=" * 60)

    all_predictions = []

    for ticker in TICKERS:
        print(f"\n[{ticker}] Fetching 2y history...")
        hist = fetch_history(ticker, period="2y")
        if hist.empty or len(hist) < 100:
            print(f"  Skipped (insufficient data: {len(hist)} days)")
            continue

        print(f"  Got {len(hist)} days. Running backtest...")
        preds = generate_predictions_for_ticker(ticker, hist)
        print(f"  Generated {len(preds)} predictions")

        if preds:
            # Show sample
            greens = [p for p in preds if p["signal"] == "GREEN"]
            reds = [p for p in preds if p["signal"] == "RED"]
            rvrps = [p["clv_realized"] for p in preds if p["clv_realized"] is not None]
            avg_rvrp = np.mean(rvrps) if rvrps else 0
            pct_pos = np.mean([r > 0 for r in rvrps]) * 100 if rvrps else 0
            print(f"  Signals: {len(greens)} GREEN, {len(reds)} RED")
            print(f"  Avg Realized VRP: {avg_rvrp:.1%} ({pct_pos:.0f}% positive)")
            all_predictions.extend(preds)

    print(f"\n{'=' * 60}")
    print(f"Total predictions generated: {len(all_predictions)}")

    if not all_predictions:
        print("No predictions generated.")
        return

    # Summary stats
    rvrps = [p["clv_realized"] for p in all_predictions if p["clv_realized"] is not None]
    signals = pd.Series([p["signal"] for p in all_predictions])
    print(f"Avg Realized VRP: {np.mean(rvrps):.1%}")
    print(f"Signal breakdown: {dict(signals.value_counts())}")
    print(f"Date range: {all_predictions[0]['date']} → {all_predictions[-1]['date']}")

    print(f"\nInserting into database...")
    count = insert_predictions(all_predictions)
    print(f"Inserted {count} predictions.")

    # Now we can run the gate!
    print(f"\nYou can now run the testing gate:")
    print(f"  python run_gate_h01_h04.py")
    print(f"  # Or: gh workflow run force-score.yml")


if __name__ == "__main__":
    main()
