"""
Record the Phase 3 verdicts in the signal graveyard — pass AND fail, per the
research discipline (the Deflated Sharpe denominator is everything ever tested;
deleting or omitting a failure silently inflates every later result).

Run AFTER the experiments, never before.

  SUPABASE_URL=... SUPABASE_KEY=... python record_h21_h24_results.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import signal_registry

# layer: how far each hypothesis got through the 10-layer gate.
# 0 = never testable with the data we have.
RESULTS = [
    {
        'signal_id': 'H21', 'passed': False, 'layer': 0,
        'failure_reason': 'BLOCKED — no 2020/2022 option prices; Databento purchase not made',
        'metrics': {'n_trades': 0,
                    'note': 'real-price hypothesis, no proxy substituted; see results/019_stress_replay.md'},
    },
    {
        'signal_id': 'H22', 'passed': False, 'layer': 0,
        'failure_reason': 'PENDING — 2020/2022 arms need option prices that were not purchased',
        'metrics': {'n_trades': 0,
                    'note': 'not failed on evidence; the deciding regime is unbought. See H22a.'},
    },
    {
        'signal_id': 'H22a', 'passed': False, 'layer': 3,
        'failure_reason': ('FAIL on 3 of 4 clauses: 27.5% of entries skipped (limit 15%), '
                           'aggregate net P&L -1.0% (needed +10%), calm-control blocks 13.3% '
                           'of entries in backwardation-free years (limit 5%)'),
        'metrics': {'n_trades': 1046,
                    'note': ('helps the two tickers with usable coverage (AAPL +21.6%, DIS +62.2%) '
                             'and hurts the two with 44-64% missing prices; drawdown leg fires in '
                             'calm years; leg ordering reversed between simulators — not settled')},
    },
    {
        'signal_id': 'H23', 'passed': False, 'layer': 4,
        'failure_reason': ('FAIL — 70% overwrite beats 100% on return/drawdown in 4 of 25 chains '
                           '(AAPL) and 0 of 25 (DIS) on the walk-forward holdout; wins only where '
                           'the overlay loses money'),
        'metrics': {'n_trades': 723,
                    'note': ('structural: at 10,000 shares the overlay moves max drawdown by '
                             '0.00-1.45pp, so return/drawdown ranks on income, which is linear in '
                             'the ratio. The ratio is an income-vs-upside dial, not a risk dial. '
                             'Stress-year clause never testable — not purchased.')},
    },
    {
        'signal_id': 'H24', 'passed': False, 'layer': 2,
        'failure_reason': ('clause (a) PENDING (5 days of GOOGL option data); clause (b) FAIL — '
                           'MSFT 20.0% and AMZN 22.9% test-window loss rate against a 10% gate'),
        'metrics': {'n_trades': 70,
                    'note': ('controls fail the same window (AAPL 11.4%, DIS 20.0%), so this is a '
                             'regime result not a ticker result; MSFT/AMZN both pass on 2019-2026 '
                             '(9.2% / 9.9%) but that window was not the pre-registered gate. '
                             'KKR liquidity cap derived and deployed: 7 contracts / 700 shares.')},
    },
]


def main():
    for r in RESULTS:
        signal_registry.mark_result(
            signal_id=r['signal_id'], passed=r['passed'], layer=r['layer'],
            metrics=r['metrics'], failure_reason=r['failure_reason'])
    print()
    signal_registry.summary()


if __name__ == '__main__':
    main()
