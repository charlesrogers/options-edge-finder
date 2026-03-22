"""
Pre-register core hypotheses H01-H04 in the signal graveyard.

MUST be run BEFORE any testing. This is the scientific discipline that
prevents post-hoc rationalization ("we found a pattern!"). Every hypothesis
is documented before we look at the data.

Usage:
  python register_hypotheses.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import db


HYPOTHESES = [
    {
        "signal_id": "H01",
        "name": "VRP Predicts Seller Wins",
        "tier": 1,
        "hypothesis": (
            "When IV exceeds GARCH-forecasted RV by >2 vol points, "
            "selling premium produces positive CLV over 20-day holding periods. "
            "Pass: CLV_realized > 1.5%, win rate > 55%, Sharpe > 0.8, n >= 500. "
            "Fail: CLV_realized < 0 over full sample (core thesis broken)."
        ),
    },
    {
        "signal_id": "H02",
        "name": "GARCH Beats Naive RV20",
        "tier": 1,
        "hypothesis": (
            "GJR-GARCH(1,1,1) produces lower QLIKE loss than 20-day close-to-close "
            "RV for 20-day-ahead volatility forecasting. "
            "Pass: QLIKE ratio < 0.95, Diebold-Mariano p < 0.05, positive in 60%+ tickers. "
            "Fail: QLIKE ratio > 1.0 (GARCH is worse — use RV20 or HAR-RV)."
        ),
    },
    {
        "signal_id": "H03",
        "name": "Signal Discrimination",
        "tier": 1,
        "hypothesis": (
            "GREEN signals produce higher CLV than YELLOW, which produce higher CLV "
            "than RED. The traffic light ordering is monotonic. "
            "Pass: CLV(GREEN) > CLV(YELLOW) > CLV(RED), CLV(GREEN) > 2%, "
            "GREEN-RED spread > 1.5%, each signal type has 100+ observations. "
            "Fail: CLV ordering is NOT monotonic (signal logic is broken)."
        ),
    },
    {
        "signal_id": "H04",
        "name": "VRP Magnitude Proportional to Edge",
        "tier": 1,
        "hypothesis": (
            "Higher VRP produces proportionally higher CLV. The CLV-vs-VRP curve "
            "is monotonically increasing (not flat/noisy). "
            "Pass: Spearman rho > 0.15, p < 0.01, CLV at VRP=6+ is 2x CLV at VRP=2-3. "
            "Fail: Flat or negative correlation (VRP magnitude doesn't matter, "
            "only its sign matters)."
        ),
    },
]


def register_all():
    count = 0
    for h in HYPOTHESES:
        db.register_hypothesis(
            signal_id=h["signal_id"],
            name=h["name"],
            tier=h["tier"],
            hypothesis=h["hypothesis"],
        )
        print(f"[registered] {h['signal_id']}: {h['name']}")
        count += 1

    print(f"\nPre-registered {count} hypotheses. Status: 'untested'.")
    print("These MUST be tested through the 10-layer gate before any conclusions.")

    # Show current graveyard
    df = db.get_graveyard()
    if not df.empty:
        print(f"\nSignal Graveyard ({len(df)} entries):")
        for _, row in df.iterrows():
            print(f"  {row['signal_id']}: {row['name']} [{row['status']}]")


if __name__ == "__main__":
    register_all()
