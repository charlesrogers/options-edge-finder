"""
Pre-register the Week 2 hypotheses H17-H20 in the signal graveyard.

MUST run before any of experiments 015-018 touch data. Full pre-registration
text (method, sample, immutable thresholds) lives in each experiment's
README.md; this records the falsifiable claim and its pass/fail gates in the
graveyard so the Deflated Sharpe denominator counts them whether they pass or
fail.

Usage:
  python3 experiments/register_week2.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import signal_registry


HYPOTHESES = [
    {
        "signal_id": "H17",
        "name": "Probability-Based Buyback Thresholds",
        "tier": 1,
        "hypothesis": (
            "Replacing distance-based CLOSE_SOON/CLOSE_NOW triggers with "
            "assignment-probability triggers (empirical 145,099-observation table "
            "lookup on moneyness x DTE) raises simulated premium retention to >= 20% "
            "while keeping assignments at zero and net P&L >= the current-rule "
            "baseline, on walk-forward test data."
        ),
        "filter_desc": (
            "AAPL, DIS, TMUS, KKR at production OTM%/DTE, IV rank >= 50 entry gate. "
            "GOOGL and AMZN excluded: no usable Databento option history "
            "(GOOGL 5 days, AMZN 0). TXN reported but not counted (production skip)."
        ),
        "trade_direction": "Exit timing only. Entry rules and EMERGENCY logic unchanged.",
        "primary_metric": "Premium retention % on walk-forward test period",
        "pass_thresholds": {
            "retention": ">= 20%",
            "assignments": "0",
            "net_pnl": ">= baseline",
            "tickers_passing": ">= 3 of 4 production tickers",
        },
        "fail_criteria": (
            "No threshold pair beats baseline retention without either an assignment "
            "or lower net P&L."
        ),
    },
    {
        "signal_id": "H18",
        "name": "Trend Gate on Call Entry",
        "tier": 2,
        "hypothesis": (
            "Suppressing new call sales when the stock is in a strong uptrend reduces "
            "per-ticker loss rate by >= 30% relative while skipping <= 25% of "
            "otherwise-valid entries, walk-forward. Source: Sinclair & Mack (2024) "
            "Ch. 10 & 15 — options on trending stocks are systematically cheap "
            "because BSM is fooled by trends."
        ),
        "filter_desc": (
            "Targets AAPL, TMUS. Controls KKR, DIS (already ~0-2% loss rates; if the "
            "gate moves a control by more than +/-1 loss, the framework is suspect and "
            "the result is void). Gates tested independently, never combined."
        ),
        "trade_direction": "Entry suppression only. Exit rules held at production baseline.",
        "primary_metric": "Relative loss-rate reduction on walk-forward test period",
        "pass_thresholds": {
            "loss_rate_reduction": ">= 30% relative on >= 2 loss-bearing tickers",
            "entries_skipped": "<= 25%",
            "control_drift": "<= +/-1 loss on KKR and DIS",
        },
        "fail_criteria": (
            "Loss reduction < 30% relative, or > 25% of entries skipped, or a control "
            "ticker shifts by more than +/-1 loss."
        ),
    },
    {
        "signal_id": "H19",
        "name": "Natenberg EMERGENCY Rational-Exercise Refinement",
        "tier": 2,
        "hypothesis": (
            "Conditioning EMERGENCY on Natenberg's rational early-exercise criteria "
            "(ITM AND ex-div <= 3 days AND dividend > remaining extrinsic AND "
            "delta >= 0.95) reduces false-positive emergency buybacks by >= 50% with "
            "ZERO missed true-assignment scenarios."
        ),
        "filter_desc": (
            "SHADOW MODE ONLY — no production change. This loosens the $400K alert. "
            "Suppression margin extrinsic < dividend x 1.5 (arbitrary, tune upward "
            "only). Missing price or delta => the refined rule FIRES. Chain capture "
            "was dead 2026-03-30 to 2026-08-15, so only the Databento window is usable; "
            "if historical ITM+ex-div events < 20 the backtest is underpowered and no "
            "verdict may be declared from it."
        ),
        "trade_direction": "Alert suppression only. Live alert path untouched in Week 2.",
        "primary_metric": "False-positive EMERGENCY firings suppressed, with zero misses",
        "pass_thresholds": {
            "false_positives_suppressed": ">= 50%",
            "missed_true_assignments": "0 (absolute)",
            "shadow_logging": ">= 2 weeks before any verdict",
        },
        "fail_criteria": (
            "ANY missed true-assignment scenario. One miss kills the hypothesis "
            "regardless of the false-positive win. Deployment additionally requires "
            "explicit sign-off from Charles."
        ),
    },
    {
        "signal_id": "H20",
        "name": "Roll-at-CLOSE_SOON Under Probability Triggers",
        "tier": 3,
        "hypothesis": (
            "Rolling instead of closing at CLOSE_SOON, evaluated under H17's winning "
            "probability triggers rather than the old distance triggers, achieves "
            "retention >= 25% with 0 assignments and aggregate net P&L above the "
            "close-only arm, walk-forward."
        ),
        "filter_desc": (
            "Conditional on H17 passing. If H17 fails this is skipped entirely — "
            "there is no point re-testing rolling under a trigger rule that did not "
            "work. Roll window 7 <= DTE <= 14, new premium >= 50% of original."
        ),
        "trade_direction": "Exit action only (roll vs close).",
        "primary_metric": "Premium retention % on walk-forward test period",
        "pass_thresholds": {
            "retention": ">= 25%",
            "assignments": "0",
            "net_pnl": "> close-only arm",
        },
        "fail_criteria": "Any of the three thresholds not met.",
    },
]


def main():
    print("=" * 78)
    print("WEEK 2 PRE-REGISTRATION — H17-H20")
    print("=" * 78)
    print(f"Graveyard backend: {signal_registry.backend()}")
    print()

    for h in HYPOTHESES:
        signal_registry.pre_register(**h)

    print()
    signal_registry.summary()

    print()
    print("Registered. Experiments 015-018 may now touch data.")


if __name__ == "__main__":
    main()
