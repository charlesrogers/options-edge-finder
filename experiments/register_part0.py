"""
Pre-register the Part 0 hypotheses H25-H26 in the signal graveyard.

MUST run before experiments 022/023 touch data. Full pre-registration text
(method, sample, immutable thresholds, deployment rules) lives in each
experiment's README.md; this records the falsifiable claim and its gates in the
graveyard so the Deflated Sharpe denominator counts them whether they pass or fail.

The graveyard backend is announced on every call. This machine has no Supabase
credentials, so a local run lands in gitignored SQLite — which is the exact
failure mode tasks/lessons.md (2026-08-15) documents. Run it through
.github/workflows/registry-sync.yml, which has the real secrets, and check the
printed backend says `supabase`.

Usage:
  python3 experiments/register_part0.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import signal_registry


HYPOTHESES = [
    {
        "signal_id": "H25",
        "name": "Baseline Re-derivation on the Fixed Engine",
        "tier": 1,
        "hypothesis": (
            "The expected_pnl and expected_win_rate fields deployed in "
            "ticker_strategies.py (derived from Exp 008/009 on the simulator that "
            "measured DTE from datetime.now(), so every observation was evaluated at "
            "DTE=0 with ex_div_date=None) are reproduced by the fixed engine "
            "experiments/cc_sim.py, on the same production per-ticker settings and the "
            "same production IV-rank >= 50 entry gate, within +/-25% relative "
            "(annualised net P&L per contract, median of 25 staggered sequential "
            "chains) and +/-10 percentage points (win rate), for each of AAPL, DIS, "
            "TMUS and KKR."
        ),
        "filter_desc": (
            "AAPL, DIS, TMUS, KKR at production OTM%/DTE with the production IV-rank "
            ">= 50 gate and the production copilot exit policy. TXN descriptive control "
            "only (production tier = skip). GOOGL (5 days of option data) and AMZN "
            "(none) cannot be run."
        ),
        "trade_direction": (
            "No strategy change. This measures our own published numbers. Deployment is "
            "restricting-only: corrected expected_* fields, and demotion to probation "
            "tier where repricing coverage < 70% or corrected median annualised net P&L "
            "<= 0. No promotions under any outcome."
        ),
        "primary_metric": (
            "Annualised net P&L per contract (median of 25 staggered sequential chains) "
            "and chain win rate"
        ),
        "pass_thresholds": {
            "expected_pnl": "within +/-25% relative for all 4 tickers",
            "expected_win_rate": "within +/-10pp for all 4 tickers",
        },
        "fail_criteria": (
            "Any of the 4 tickers outside either tolerance. Fail replaces that ticker's "
            "expected_* fields with the corrected values (one commit per ticker) and "
            "marks results/012_walk_forward.md superseded."
        ),
    },
    {
        "signal_id": "H26",
        "name": "IV-Rank >= 50 Entry Gate on Trial",
        "tier": 1,
        "hypothesis": (
            "Clause 1: entries taken under the live IV-rank >= 50 gate return a higher "
            "mean net P&L per entry on the walk-forward holdout than entries taken with "
            "no gate, by >= 10% relative, per ticker. Clause 2: a per-ticker threshold "
            "chosen from {25, 50, 75} on the TRAINING window only beats the global 50 on "
            "the holdout by >= 10% relative, per ticker. Where the comparison baseline is "
            "<= 0, '10% relative' means an improvement of >= 10% of its magnitude AND a "
            "resulting mean > 0. Source of the incumbent: Exp 009, one un-staggered path "
            "on the DTE-broken simulator; Exp 019b's control then observed the gate "
            "rescuing DIS/KKR while costing AAPL/TMUS."
        ),
        "filter_desc": (
            "AAPL, DIS, TMUS, KKR at production OTM%/DTE and production exit policy; only "
            "the entry gate varies. TXN descriptive control only. Single calendar "
            "walk-forward cut at 67% of the option-day window, identical across arms."
        ),
        "trade_direction": (
            "Entry timing only. Deployment is asymmetric by design: a clause-2 pass with a "
            "winning threshold >= 50 and no extra assignments deploys as a per-ticker "
            "iv_threshold (one commit per ticker); a clause-1 fail deploys NOTHING (a "
            "failed test of a restriction is not evidence for removing it); a winning "
            "threshold below 50 is a loosening change and needs its own experiment."
        ),
        "primary_metric": "Mean net P&L per entry ($/contract) on the walk-forward holdout",
        "pass_thresholds": {
            "clause_1": "gate50 mean per-entry P&L >= 1.10x no-gate, per ticker",
            "clause_2": "train-selected per-ticker threshold >= 1.10x global 50, per ticker",
            "hard_constraint": "deployed arm's holdout assignments <= production arm's",
        },
        "fail_criteria": (
            "Clause 1 fails for a ticker when the gate does not clear the 10% margin over "
            "no-gate on the holdout; clause 2 fails when no per-ticker threshold clears "
            "10% over the global 50. Either failure deploys nothing for that ticker."
        ),
    },
]


def main():
    print("=" * 78)
    print("PRE-REGISTERING PART 0 HYPOTHESES (H25-H26)")
    print(f"graveyard backend: {signal_registry.backend()}")
    print("=" * 78)
    for h in HYPOTHESES:
        signal_registry.pre_register(**h)
    print("\nPre-registration complete. Experiments 022/023 may now run.")
    print("Full text: experiments/022_baseline_rederivation/README.md, "
          "experiments/023_iv_rank_gate/README.md")


if __name__ == "__main__":
    main()
