"""
Pre-register hypotheses H01-H16 in the signal graveyard.

MUST be run BEFORE any testing. This is the scientific discipline that
prevents post-hoc rationalization ("we found a pattern!"). Every hypothesis
is documented before we look at the data.

Tier 1: Core signal (if these fail, stop everything)
Tier 2: Edge sizing (optimal thresholds)
Tier 3: Model adjustments (incremental improvements)

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
    # --- Tier 2: Edge Sizing ---
    {
        "signal_id": "H05",
        "name": "Optimal VRP Threshold",
        "tier": 2,
        "hypothesis": (
            "There exists an optimal minimum VRP threshold below which Realized VRP "
            "turns negative. Plot CLV-vs-VRP curve and find breakpoint. "
            "Pass: clear breakpoint, stable across time halves, optimal threshold CLV > 2%. "
            "Fail: monotonically increasing with no breakpoint (always trade higher VRP)."
        ),
    },
    {
        "signal_id": "H06",
        "name": "IV Rank Threshold",
        "tier": 2,
        "hypothesis": (
            "IV Rank has an optimal minimum below which selling premium has zero CLV. "
            "Current threshold: 30%. May be wrong. "
            "Pass: breakpoint between 15-40%, CLV below threshold near zero. "
            "Fail: IV Rank has no relationship to CLV after controlling for VRP (drop it)."
        ),
    },
    {
        "signal_id": "H07",
        "name": "IV Compression as Entry Signal",
        "tier": 2,
        "hypothesis": (
            "When IV has already dropped >5% from 10-day high by signal time, "
            "remaining VRP is smaller ('line has already moved'). "
            "Pass: CLV(fresh high IV) > CLV(compressing) by >1%, t-test p<0.05. "
            "Fail: no difference (IV compression speed doesn't matter)."
        ),
    },
    {
        "signal_id": "H08",
        "name": "VRP/IV Ratio vs Absolute VRP",
        "tier": 2,
        "hypothesis": (
            "VRP as percentage of IV (VRP/IV) is a better predictor than absolute VRP. "
            "Sinclair: low-vol VRP = 19% of IV, high-vol = 13%. "
            "Pass: Spearman rho(VRP/IV, CLV) > rho(VRP, CLV), permutation p<0.05. "
            "Fail: absolute VRP is equally predictive (keep current system)."
        ),
    },
    # --- Tier 3: Model Adjustments ---
    {
        "signal_id": "H09",
        "name": "Vol Surface VRP > ATM VRP",
        "tier": 3,
        "hypothesis": (
            "Selecting strikes based on VRP surface (where IV minus fair value is "
            "richest) produces higher CLV than always selling ATM. "
            "Pass: CLV uplift > 0.5%, works across 50%+ of tickers. "
            "Fail: surface VRP doesn't improve over ATM (save the complexity)."
        ),
    },
    {
        "signal_id": "H10",
        "name": "Bayesian Probability > Static Thresholds",
        "tier": 3,
        "hypothesis": (
            "Bayesian logistic regression produces better-calibrated probabilities "
            "than static point-scoring. "
            "Pass: calibration error <5%, CLV uplift >0.5%, OOS log-likelihood +5%. "
            "Fail: not better calibrated (static thresholds are fine)."
        ),
    },
    {
        "signal_id": "H11",
        "name": "HAR-RV + GARCH Blend",
        "tier": 3,
        "hypothesis": (
            "Blended forecast (GARCH + HAR-RV per Module 1D) beats either alone. "
            "Pass: blend QLIKE < min(GARCH, HAR-RV), improvement >3%, stable weights. "
            "Fail: one model dominates (use that model alone)."
        ),
    },
    {
        "signal_id": "H12",
        "name": "Regime Filter Adds Value",
        "tier": 3,
        "hypothesis": (
            "Excluding trades during unfavorable regimes (High Vol, Crisis) improves "
            "CLV vs trading all GREEN signals. Must beat random exclusion (Module 5C). "
            "Pass: CLV uplift >0.5%, z-test p<0.05 vs random. "
            "Fail: regime filter doesn't beat random exclusion (drop it)."
        ),
    },
    {
        "signal_id": "H13",
        "name": "Earnings Exclusion",
        "tier": 3,
        "hypothesis": (
            "Excluding trades within 5 days of earnings improves CLV because "
            "event vol is often justified. "
            "Pass: CLV(no-earnings) > CLV(near-earnings) by >1%, t-test p<0.05. "
            "Fail: no difference (earnings vol is also overpriced — interesting!)."
        ),
    },
    {
        "signal_id": "H14",
        "name": "FOMC Exclusion",
        "tier": 3,
        "hypothesis": (
            "Excluding trades within 2 days of FOMC improves CLV. "
            "Pass: CLV(away) significantly > CLV(near-FOMC). "
            "Fail: no difference (FOMC risk already overpriced in IV)."
        ),
    },
    {
        "signal_id": "H15",
        "name": "Term Structure as Independent Signal",
        "tier": 3,
        "hypothesis": (
            "Term structure (contango/backwardation) provides independent predictive "
            "power beyond VRP and IV Rank. "
            "Pass: Fama-MacBeth coefficient significant (t>2.0), VIF<5. "
            "Fail: redundant with VRP after controlling (drop from signal)."
        ),
    },
    {
        "signal_id": "H16",
        "name": "Skew-Adjusted Kelly > Fixed Quarter-Kelly",
        "tier": 3,
        "hypothesis": (
            "Position sizing that accounts for skewness produces better risk-adjusted "
            "returns than fixed 25% Kelly. Sinclair: halve, halve again, adjust for skew. "
            "Pass: Sortino improvement >0.2, max DD reduction >10%. "
            "Fail: skew adjustment reduces P&L more than drawdown (fixed is fine)."
        ),
    },
    # --- Exit Strategy Research (Experiment 001) ---
    {
        "signal_id": "H30",
        "name": "Optimal Take-Profit Level",
        "tier": 2,
        "hypothesis": (
            "There exists a take-profit % (25-75%) that maximizes risk-adjusted returns "
            "for put spreads. Holding to expiry loses money due to asymmetric risk. "
            "Pass: at least one TP level has Sortino >0.5 and avg P&L >0. "
            "Fail: no TP level is profitable (put spread structure is not viable)."
        ),
    },
    {
        "signal_id": "H31",
        "name": "Optimal Stop-Loss Level",
        "tier": 2,
        "hypothesis": (
            "A stop-loss at 1.5-2.5x premium collected improves risk-adjusted returns "
            "by cutting losers before max loss. "
            "Pass: at least one SL level improves Sortino vs no stop loss. "
            "Fail: all stop-loss levels produce worse results (whipsaw destroys value)."
        ),
    },
    {
        "signal_id": "H32",
        "name": "Time-Based Exit (DTE Floor)",
        "tier": 2,
        "hypothesis": (
            "Closing all positions at 7 DTE avoids gamma acceleration. "
            "Pass: DTE floor of 5-14 has higher Sortino than no floor. "
            "Fail: time-based exit doesn't improve returns."
        ),
    },
    {
        "signal_id": "H33",
        "name": "VRP-Based Exit",
        "tier": 2,
        "hypothesis": (
            "Closing when VRP flips negative captures 'edge disappearance' signal. "
            "Pass: VRP exit improves Sortino by >0.1 vs no VRP exit. "
            "Fail: VRP flip during trade doesn't predict outcome."
        ),
    },
    {
        "signal_id": "H34",
        "name": "Combined Exit Strategy",
        "tier": 2,
        "hypothesis": (
            "The optimal combination of take-profit + stop-loss + DTE floor + VRP exit "
            "outperforms any single exit type. Grid search over 300 combos with DSR correction. "
            "Pass: best combo Sortino > best single-type by >0.2. "
            "Fail: single exit type is sufficient (combined adds complexity without value)."
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
