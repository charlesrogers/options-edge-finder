"""
Pre-register Phase 3 hypotheses H21–H24 (+ H22a) in the signal graveyard.

MUST be run BEFORE any Phase 3 experiment touches data. Pass/fail thresholds below are
immutable once this has run — see tasks/phase3-strategy-spec.md and each experiment's
README.md for the full text.

Requires the signal_graveyard table (migrations/001_signal_graveyard.sql) and
SUPABASE_URL / SUPABASE_KEY in the environment. Falls back to local SQLite otherwise.

Usage:
  SUPABASE_URL=... SUPABASE_KEY=... python register_h21_h24.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
import signal_registry


HYPOTHESES = [
    {
        "signal_id": "H21",
        "name": "Bear/Rebound Stress Replay",
        "tier": 1,
        "hypothesis": (
            "The production covered-call system (per-ticker OTM%/DTE, IV-rank >= 50 gate, "
            "copilot exits) produces, on REAL 2020 and 2022 option prices: zero assignments; "
            "per-ticker annual loss rates within 10 percentage points of their 2025-26 "
            "walk-forward values; and total return >= stock-only buy-and-hold (the overlay "
            "never amplifies losses)."
        ),
        "filter_desc": "AAPL and TMUS, calendar years 2020 and 2022, real option OHLCV",
        "trade_direction": "Covered calls, production settings frozen at pre-registration",
        "primary_metric": "Assignments / loss rate delta vs 2025-26 / overlay-vs-stock return",
        "pass_thresholds": {
            "assignments": "0",
            "loss_rate_delta": "<= 10pp vs 2025-26 walk-forward",
            "overlay_vs_stock": ">= 0 (never amplifies losses)",
        },
        "fail_criteria": (
            "Any assignment, or loss rate >10pp worse, or overlay amplifies losses in "
            "either year. Marginal: loss rates hold but retention drops >50% relative."
        ),
        "experiment": "019",
    },
    {
        "signal_id": "H22",
        "name": "Backwardation Entry Guard",
        "tier": 2,
        "hypothesis": (
            "Suppressing new call sales when VIX > VIX3M OR the stock is >15% below its "
            "60-day high improves 2020 stress-year P&L by >= 20% relative, with <= 10% of "
            "entries skipped across 2019-2023, and changes 2022 / 2024-26 results by "
            "<= +/-5% (dormant outside crash regimes)."
        ),
        "filter_desc": "All tradeable tickers; guard thresholds 15% / 60-day are arbitrary starting values",
        "trade_direction": "Suppress new covered-call entries; existing positions untouched",
        "primary_metric": "Stress-year net P&L (relative), entries skipped %",
        "pass_thresholds": {
            "2020_pnl": ">= +20% relative",
            "entries_skipped": "<= 10% over 2019-2023",
            "calm_regime_drift": "<= +/-5%",
        },
        "fail_criteria": "Any clause missed. Source: Sinclair & Mack Ch. 10.",
        "experiment": "019b",
    },
    {
        "signal_id": "H22a",
        "name": "Backwardation Guard — Real-Price Vol-Spike Arm",
        "tier": 2,
        "hypothesis": (
            "On the real option prices we already own (2025-03-21 to 2026-03-20, which "
            "contains 24 backwardation days incl. the April-2025 selloff), adding the "
            "backwardation guard to the production entry gate skips <= 15% of otherwise-valid "
            "entries, improves aggregate net call P&L by >= 10% relative across AAPL/DIS/TMUS/KKR, "
            "adds zero assignments, and stays dormant (<= +/-5% entry-count change) in the "
            "backwardation-free control years 2021 and 2023."
        ),
        "filter_desc": "AAPL, DIS, TMUS, KKR; production OTM%/DTE; 25 staggered entry cohorts",
        "trade_direction": "Suppress new covered-call entries under backwardation / drawdown",
        "primary_metric": "Aggregate net call P&L (relative), entries skipped %, assignments",
        "pass_thresholds": {
            "entries_skipped": "<= 15%",
            "aggregate_pnl": ">= +10% relative",
            "assignments": "0",
            "calm_control_entry_drift": "<= +/-5%",
        },
        "fail_criteria": (
            "Skips >15% of entries, or reduces aggregate net call P&L, or adds an assignment, "
            "or fires materially in the calm control. Marginal: P&L change within +/-10%."
        ),
        "experiment": "019b",
    },
    {
        "signal_id": "H23",
        "name": "Partial Overwriting (50-70% of shares)",
        "tier": 2,
        "hypothesis": (
            "Overwriting 50-70% of shares per ticker (vs the implicit 100%) produces a higher "
            "full-period total return per unit of worst drawdown, on 2025-26 data AND on the "
            "stress years, than 100% overwrite, while cutting buyback friction roughly "
            "proportionally. Source: Sinclair, Skewness and the Kelly Criterion — short-call "
            "P&L is negatively skewed and Kelly prescribes sizing below full."
        ),
        "filter_desc": "AAPL, DIS, TMUS, KKR at 10,000 shares each; ratios {50%, 70%, 100%}",
        "trade_direction": "Sell calls on a fraction of the share count",
        "primary_metric": "Total return / max drawdown on the daily equity curve",
        "pass_thresholds": {
            "return_over_drawdown": "some ratio <100% beats 100% in the walk-forward TEST period",
            "stress_years": "and in >= 1 stress year",
            "absolute_income": ">= 70% of the 100%-overwrite level",
        },
        "fail_criteria": "No ratio <100% beats 100% on return/drawdown, or income falls below 70%.",
        "experiment": "020",
    },
    {
        "signal_id": "H24",
        "name": "Capacity Expansion — GOOGL real-price, MSFT/AMZN probation",
        "tier": 2,
        "hypothesis": (
            "(a) GOOGL's deployed 10% OTM / 20-45 DTE setting holds on a real option year: "
            "test-period loss rate <= 15% and net P&L > 0. "
            "(b) MSFT and AMZN at 15% OTM / 20-45 DTE show walk-forward stock-data loss rates "
            "<= 10%, qualifying them for a probation tier (recommendable, flagged "
            "'stock-data validated only', at half size) pending 6 months of accrued chain capture."
        ),
        "filter_desc": "(a) GOOGL real options; (b) MSFT, AMZN stock closes, 2y walk-forward 67/33",
        "trade_direction": "Covered calls at the stated OTM%/DTE",
        "primary_metric": "Test-period loss rate; net P&L for clause (a)",
        "pass_thresholds": {
            "googl_loss_rate": "<= 15% and net P&L > 0",
            "msft_amzn_loss_rate": "<= 10% on the test window, per ticker",
        },
        "fail_criteria": (
            "Per clause. Clause (b) failure for a ticker means it stays out entirely — no "
            "production change. Probation tier must NOT reuse the 'untested' badge."
        ),
        "experiment": "021",
    },
]


def register_all():
    existing = set()
    try:
        df = db.get_graveyard()
        if not df.empty:
            existing = set(df["signal_id"].tolist())
    except Exception as e:
        print(f"[warn] could not read graveyard: {e}")

    collisions = existing & {h["signal_id"] for h in HYPOTHESES}
    if collisions:
        print(f"ERROR: these IDs are already registered: {sorted(collisions)}")
        print("Pick fresh IDs rather than overwriting a pre-registration.")
        return 1

    for i, h in enumerate(HYPOTHESES, 1):
        signal_registry.pre_register(
            signal_id=h["signal_id"],
            name=h["name"],
            tier=h["tier"],
            hypothesis=h["hypothesis"] + f"\nExperiment: {h['experiment']}",
            filter_desc=h["filter_desc"],
            trade_direction=h["trade_direction"],
            primary_metric=h["primary_metric"],
            pass_thresholds=h["pass_thresholds"],
            fail_criteria=h["fail_criteria"],
        )
        print(f"  [{i}/{len(HYPOTHESES)}] {h['signal_id']} registered")

    print()
    signal_registry.summary()
    return 0


if __name__ == "__main__":
    sys.exit(register_all())
