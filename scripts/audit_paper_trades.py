#!/usr/bin/env python3
"""
Audit the paper-trade record that the /sell scorecard publishes.

The scorecard renders a win rate, an average P&L and a W/L record taken from
every row in `paper_trades`, with the caption "Every recommendation logged and
scored automatically". Two things have to be separated before any of that can be
believed:

  1. BSM-backfilled rows. `backfill_paper_trades.py` seeded history by pricing
     synthetic trades with Black-Scholes off stock history. Those rows carry
     `strategy_params.backfilled = true`. They measure the pricing model, not
     the strategy, and not a single one is a real recommendation anyone could
     have traded.
  2. The 2026-03-30 -> 2026-08-15 outage, during which the logger wrote nothing.

Usage:
    python3 scripts/audit_paper_trades.py                    # live DB, else the public API
    python3 scripts/audit_paper_trades.py --json path.json   # a saved payload
    python3 scripts/audit_paper_trades.py --markdown         # emit the results table

Source precedence is DB -> API so this stays runnable in CI (no creds) and on a
laptop (creds), and prints WHICH source it used — a number whose provenance is
ambiguous is exactly what this script exists to prevent.
"""

import argparse
import json
import os
import sys
import urllib.request
from collections import Counter
from datetime import date

PROD_API = "https://options.imprevista.com/api/paper-trades?detail=true"


def load_from_db():
    """Return rows from Supabase, or None if unavailable."""
    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY")):
        return None
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from db import get_supabase  # noqa: PLC0415
    except Exception:
        return None
    try:
        sb = get_supabase()
        res = sb.from_("paper_trades").select("*").order("recommended_at", desc=False).execute()
        return res.data
    except Exception as exc:  # pragma: no cover - network path
        print(f"  (DB read failed: {exc})", file=sys.stderr)
        return None


def load_from_api():
    with urllib.request.urlopen(PROD_API, timeout=60) as fh:
        return json.load(fh)["trades"]


def load(args):
    if args.json:
        with open(args.json) as fh:
            payload = json.load(fh)
        return payload["trades"] if isinstance(payload, dict) else payload, f"file {args.json}"
    rows = load_from_db()
    if rows is not None:
        return rows, "Supabase (paper_trades)"
    return load_from_api(), "production API (options.imprevista.com)"


def is_backfilled(row) -> bool:
    raw = row.get("strategy_params") or "{}"
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return False
    return bool(raw.get("backfilled", False))


def headline(rows):
    """Win rate / avg P&L over the SCORED subset, or None when nothing is scored."""
    scored = [r for r in rows if r.get("scored")]
    if not scored:
        return None
    winners = [r for r in scored if (r.get("pnl_pct") or 0) > 0]
    return {
        "n": len(scored),
        "winners": len(winners),
        "losers": len(scored) - len(winners),
        "win_rate": round(100 * len(winners) / len(scored), 1),
        "avg_pnl": round(sum(r.get("pnl_pct") or 0 for r in scored) / len(scored), 2),
    }


def find_gaps(rows, min_days=7):
    days = sorted({r["recommended_at"] for r in rows})
    gaps = []
    for a, b in zip(days, days[1:]):
        delta = (date.fromisoformat(b) - date.fromisoformat(a)).days
        if delta > min_days:
            gaps.append((a, b, delta))
    return gaps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="read a saved API payload instead of the network")
    ap.add_argument("--markdown", action="store_true", help="emit the results-file table")
    args = ap.parse_args()

    rows, source = load(args)
    for r in rows:
        r["_backfilled"] = is_backfilled(r)

    synthetic = [r for r in rows if r["_backfilled"]]
    real = [r for r in rows if not r["_backfilled"]]

    all_stats = headline(rows)
    syn_stats = headline(synthetic)
    real_stats = headline(real)
    gaps = find_gaps(rows)

    if args.markdown:
        def fmt(s):
            if s is None:
                return "| — | — | — | *nothing scored* |"
            return f"| {s['n']} | {s['win_rate']}% | {s['avg_pnl']:+.2f}% | {s['winners']}W / {s['losers']}L |"

        print(f"**Source:** {source}\n")
        print("| Set | Scored | Win rate | Avg P&L | Record |")
        print("|---|---:|---:|---:|---|")
        print(f"| All rows — *what the scorecard publishes* {fmt(all_stats)}")
        print(f"| BSM-backfilled (synthetic prices) {fmt(syn_stats)}")
        print(f"| Live-chain (real quoted prices) {fmt(real_stats)}")
        return 0

    print(f"Source: {source}")
    print(f"Rows: {len(rows)}  (backfilled {len(synthetic)}, live-chain {len(real)})")
    print()
    for label, subset, stats in (
        ("ALL ROWS (published)", rows, all_stats),
        ("BSM-BACKFILLED", synthetic, syn_stats),
        ("LIVE-CHAIN", real, real_stats),
    ):
        if subset:
            span = sorted(r["recommended_at"] for r in subset)
            print(f"{label}: {len(subset)} rows, {span[0]} -> {span[-1]}")
        else:
            print(f"{label}: 0 rows")
        if stats is None:
            print("   scored: 0 — NO headline statistic can be computed from this set")
        else:
            print(
                f"   scored: {stats['n']}  win rate {stats['win_rate']}%  "
                f"avg P&L {stats['avg_pnl']:+.2f}%  ({stats['winners']}W/{stats['losers']}L)"
            )
        print()

    print("Logging gaps (>7 days with no recommendation written):")
    if not gaps:
        print("   none")
    for a, b, n in gaps:
        print(f"   {a} -> {b}   {n} days")
    print()

    tiers = Counter(r["tier"] for r in real)
    print(f"Live-chain rows by tier as logged: {dict(tiers)}")

    if real_stats is None:
        print()
        print("VERDICT: the published win rate and average P&L come entirely from")
        print("synthetic Black-Scholes prices. No real-price recommendation has ever")
        print("been scored. The scorecard may not present these as the strategy's record.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
