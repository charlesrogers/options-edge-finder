"""
Record the Week 2 verdicts (H17-H20) in the signal graveyard.

Failures are recorded as prominently as passes — the graveyard is the Deflated
Sharpe denominator, and a graveyard that only remembers winners inflates every
later result.

Run AFTER the experiments, never before.

  python3 experiments/record_week2_results.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import signal_registry


RESULTS = [
    dict(
        signal_id='H17', passed=False, layer=2,
        metrics={'n_trades': 233, 'tickers_passing_primary': '1/4',
                 'tickers_passing_walkforward': '0/4',
                 'baseline_test_retention_pct': 'AAPL 49.1 / DIS 84.8 / TMUS -98.2 / KKR 34.5',
                 'best_arm_test_retention_pct': 'AAPL 59.9 / DIS 23.5 / TMUS -14.7 / KKR 22.5',
                 'assignments': '0 in every arm, but non-binding by construction',
                 'stale_exit_fills_baseline': 'AAPL 3.6% / DIS 25.6% / TMUS 3.0% / KKR 44.4%',
                 'result_file': 'results/015_probability_buybacks.md'},
        failure_reason=(
            'Probability triggers lose to the corrected baseline on 3 of 4 tickers. '
            'Premise was also wrong: 42-95% of baseline closes come from the '
            '75%-premium-captured take-profit clause, not from distance triggers, and the '
            'probability policy deletes it. The 13% baseline from Exp 009 was an artefact '
            'of assess_position() evaluating every historical observation at DTE=0 (fixed '
            'in 8040440). Caveats: the 0-assignment constraint never bound (every arm '
            'keeps EMERGENCY + ITM CLOSE_NOW, so nothing survived to an ex-div or expiry); '
            'the treatment arm is in-sample because the ITM_PROBABILITY table was fit on '
            'the same AAPL/KKR windows; only AAPL is measured on clean fills (KKR 44% of '
            'exits are carried-forward prices).'),
    ),
    dict(
        signal_id='H18', passed=False, layer=2,
        metrics={'n_trades': 233, 'gates_tested': 6, 'targets_qualifying': '0-1 of 2',
                 'control_drift': 'KKR -1 loss on autocorr gates, DIS 0 on all',
                 'gates_making_it_worse': '4 of 6 (other 2 suppress nothing)',
                 'result_file': 'results/016_trend_gate.md'},
        failure_reason=(
            'No gate cleared >=30% relative loss reduction on >=2 loss-bearing tickers. '
            'Four of six gates raise the loss rate. The single hit (AAPL autocorr '
            'percentile>70, 4 losses -> 0) rests on 4 losses in 30 trades, moves a '
            'control, and is the worst gate on GOOGL. Controls behaved correctly, so '
            'the framework is sound and the answer is no. GOOGL — the ticker that '
            'motivated the hypothesis — has 5 days of option data and cannot be tested.'),
    ),
    dict(
        signal_id='H19', passed=False, layer=2,
        metrics={'n_trades': 172, 'distinct_situations': 127,
                 'suppression_pct': 61.6, 'missed_true_assignments': 38,
                 'missed_actual_early_exercises': 9,
                 'delta_range_of_exercised_calls': '0.79-0.946',
                 'shadow_mode': 'shipped, live alert unchanged',
                 'result_file': 'results/017_natenberg_emergency.md'},
        failure_reason=(
            '38 missed true-assignment scenarios on 172 events, including 9 calls '
            'actually exercised early at delta 0.79-0.946 — every one silenced by the '
            'delta>=0.95 condition. Suppression hit 61.6% (target 50%) but one miss kills '
            'the hypothesis. Failure is structural: the current ITM+ex-div rule also '
            'catches near-certain assignment AT EXPIRY, which Natenberg early-exercise '
            'criteria do not address. No delta/margin combination reaches zero misses.'),
    ),
    dict(
        signal_id='H20', passed=False, layer=0,
        metrics={'result_file': 'results/018_roll_revisit.md'},
        failure_reason=(
            'skipped_dependency — not tested. H20 was pre-registered as conditional on '
            'H17 passing; H17 failed, so the winning probability triggers this hypothesis '
            'was defined against do not exist. Running it would mean selecting an arm of '
            'a failed grid post hoc.'),
    ),
]


def main():
    print('=' * 78)
    print('WEEK 2 RESULTS — H17-H20')
    print('=' * 78)
    print(f'Graveyard backend: {signal_registry.backend()}')
    print()

    for r in RESULTS:
        signal_registry.mark_result(**r)

    print()
    signal_registry.summary()


if __name__ == '__main__':
    main()
