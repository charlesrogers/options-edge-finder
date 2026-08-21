"""Record (or check) a byte-exact fingerprint of cc_sim's output.

The paper engine extracts cc_sim's decision core into `cc_core.py` so there is
exactly one definition of what a verdict makes a trader do. "The refactor
changed nothing" is a claim, and an unverified claim about a financial engine is
how this project lost six experiments to a silently-pinned DTE. So: run a fixed
cohort set through cc_sim, hash every trade field, and commit the hash.

  python3 scripts/cc_sim_parity_baseline.py --write   # record
  python3 scripts/cc_sim_parity_baseline.py           # check (exit 1 on drift)

The fixture is deliberately small and fully deterministic — one ticker, one
fixed window, production config — so it runs inside the normal pytest step.
"""
import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'experiments'))

import cc_sim

FIXTURE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'tests', 'fixtures', 'cc_sim_parity.json')

# Production settings for AAPL (ticker_strategies.py), the only ticker with
# essentially complete repricing coverage — so the fingerprint is not itself
# dominated by carried-forward prices.
CASES = [
    {'ticker': 'AAPL', 'start': '2025-01-02', 'end': '2025-06-30',
     'cfg': {'otm_pct': 0.15, 'min_dte': 20, 'max_dte': 45}, 'gate': 'iv50'},
    {'ticker': 'AAPL', 'start': '2025-01-02', 'end': '2025-06-30',
     'cfg': {'otm_pct': 0.15, 'min_dte': 20, 'max_dte': 45}, 'gate': 'none'},
]


def run_case(case):
    chain = cc_sim.load_ticker(case['ticker'], case['start'], case['end'], verbose=False)
    gate = cc_sim.iv_rank_gate(50) if case['gate'] == 'iv50' else cc_sim.no_gate()
    trades, diag = cc_sim.run(chain, case['cfg'], cc_sim.baseline_policy,
                              gate=gate, progress_every=0,
                              label=f"parity/{case['ticker']}/{case['gate']}")
    records = cc_sim.trades_to_records(trades)
    # Sort so the fingerprint cannot drift on iteration order alone.
    records.sort(key=lambda r: (r['entry_date'], r['symbol'], r['exit_date']))
    return {'case': case, 'n_trades': len(records),
            'score': cc_sim.score(trades),
            'diagnostics': diag,
            'trades': records}


def fingerprint(payload):
    blob = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', action='store_true')
    args = ap.parse_args()

    results = []
    for i, case in enumerate(CASES, 1):
        print(f'[{i}/{len(CASES)}] {case["ticker"]} {case["start"]}..{case["end"]} '
              f'gate={case["gate"]}', flush=True)
        results.append(run_case(case))
        print(f'    -> {results[-1]["n_trades"]} trades, '
              f'net {results[-1]["score"]["net_pnl"]}', flush=True)

    digest = fingerprint(results)
    print(f'fingerprint: {digest}')

    if args.write:
        os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
        with open(FIXTURE, 'w') as f:
            json.dump({'sha256': digest, 'cases': CASES,
                       'summary': [{'ticker': r['case']['ticker'],
                                    'gate': r['case']['gate'],
                                    'n_trades': r['n_trades'],
                                    'net_pnl': r['score']['net_pnl'],
                                    'retention_pct': r['score']['retention_pct']}
                                   for r in results]}, f, indent=2)
        print(f'wrote {FIXTURE}')
        return 0

    if not os.path.exists(FIXTURE):
        print(f'FAIL: no fixture at {FIXTURE} — run with --write first')
        return 1
    with open(FIXTURE) as f:
        expected = json.load(f)['sha256']
    if digest != expected:
        print(f'FAIL: cc_sim output changed.\n  expected {expected}\n  got      {digest}')
        return 1
    print('OK: cc_sim output is byte-identical to the committed baseline')
    return 0


if __name__ == '__main__':
    sys.exit(main())
