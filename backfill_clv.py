"""
One-time script to backfill Realized VRP for already-scored predictions.

Realized VRP = (IV_at_entry - RV_over_holding_period) / IV_at_entry

This is the primary edge metric: did we sell at higher IV than realized vol?
Positive Realized VRP = we consistently sold overpriced volatility.
(Stored in DB column `clv_realized` for historical compatibility.)

Run once after adding columns, then let score_pending_predictions() handle new ones.

Usage:
  python backfill_clv.py
  # Or via GitHub Actions / Heroku
"""

import os
import sys

# Allow imports from project root
sys.path.insert(0, os.path.dirname(__file__))

import db


def backfill():
    """Backfill clv_realized for scored predictions missing it."""
    import pandas as pd

    sb = db._get_supabase()
    if sb:
        # Fetch scored predictions missing CLV
        resp = sb.table("predictions").select(
            "id, ticker, atm_iv, outcome_rv, outcome_date"
        ).eq("scored", 1).is_("clv_realized", "null").execute()
        predictions = resp.data or []
    else:
        conn = db._get_sqlite()
        rows = conn.execute(
            "SELECT id, ticker, atm_iv, outcome_rv, outcome_date "
            "FROM predictions WHERE scored = 1 AND clv_realized IS NULL"
        ).fetchall()
        predictions = [dict(r) for r in rows]
        conn.close()

    if not predictions:
        print("[backfill] No predictions need CLV backfill.")
        return 0

    print(f"[backfill] Found {len(predictions)} predictions to backfill...")
    updated = 0

    for pred in predictions:
        atm_iv = pred.get("atm_iv")
        outcome_rv = pred.get("outcome_rv")
        outcome_date = pred.get("outcome_date")
        ticker = pred.get("ticker")

        # Compute CLV_realized from existing data
        clv_realized = None
        if atm_iv and outcome_rv and atm_iv > 0:
            clv_realized = round((atm_iv - outcome_rv) / atm_iv, 6)

        # Try to fetch IV at scoring date
        iv_at_scoring = None
        if outcome_date and ticker:
            iv_at_scoring = db.get_iv_on_date(ticker, outcome_date)

        update_data = {}
        if clv_realized is not None:
            update_data["clv_realized"] = clv_realized
        if iv_at_scoring is not None:
            update_data["iv_at_scoring"] = round(iv_at_scoring, 4)

        if not update_data:
            continue

        if sb:
            sb.table("predictions").update(update_data).eq("id", pred["id"]).execute()
        else:
            conn = db._get_sqlite()
            cols = ", ".join(f"{k} = ?" for k in update_data.keys())
            vals = list(update_data.values()) + [pred["id"]]
            conn.execute(f"UPDATE predictions SET {cols} WHERE id = ?", vals)
            conn.commit()
            conn.close()

        updated += 1
        if updated % 50 == 0:
            print(f"[backfill] Progress: {updated}/{len(predictions)}")

    print(f"[backfill] Done. Updated {updated} predictions with CLV data.")
    return updated


if __name__ == "__main__":
    count = backfill()
    print(f"\nBackfilled {count} predictions.")
