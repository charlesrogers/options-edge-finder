"""
Record the Part 0 verdicts (H25-H26) in the signal graveyard.

Failures are recorded as prominently as passes — the graveyard is the Deflated Sharpe
denominator, and a graveyard that only remembers winners inflates every later result.

Run AFTER the experiments, never before. On a dev machine this lands in gitignored SQLite;
run it through .github/workflows/registry-sync.yml, which holds the Supabase secrets:

  gh workflow run registry-sync.yml -f script=experiments/record_part0_results.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import signal_registry


RESULTS = [
    dict(
        signal_id='H25', passed=False, layer=2,
        metrics={
            'n_trades': 855,
            'tickers_within_tolerance': '1/4 (AAPL only)',
            'corrected_annual_pnl_per_contract':
                'AAPL 141 / DIS 442 / TMUS 178 / KKR 329 (medians of 25 chains, '
                'FULLY CORRECTED engine incl. commit bbbddaa)',
            'superseded_first_run':
                'AAPL 299 / DIS 267 / TMUS 151 / KKR 316 — measured on an engine that '
                'fabricated iv_rank=50.0 for the first ~9 days of every ticker, which '
                'passes the >=50 gate; every ticker carried 9 phantom entries',
            'deployed_values_were': 'AAPL 351 / DIS 822 / TMUS 447 / KKR 386',
            'corrected_win_rate': 'AAPL 90.9 / DIS 88.9 / TMUS 91.7 / KKR 69.2',
            'real_fill_only_annual_pnl':
                'AAPL 141 / DIS 442 / TMUS 9 / KKR -17 (TMUS and KKR collapse to ~zero; '
                'AAPL unchanged by fill definition)',
            'repricing_coverage_pct': 'AAPL 97.1 / DIS 87.6 / TMUS 56.7 / KKR 35.7',
            'assignments': 0,
            'result_file': 'results/022_baseline_rederivation.md',
        },
        failure_reason=(
            'H25 FAILS on both engine lineages. Which tickers sit inside tolerance '
            'REVERSED when six reviewed simulator defects were removed (first run: AAPL '
            'only; corrected: TMUS and KKR only), so the per-ticker tolerance result is '
            'recorded as an unstable intermediate, not a verdict. Stable across both: '
            'zero assignments, both coverage demotions, AAPL alone unmoved by fill '
            'definition. Originally: '
            'DIS (-68%), TMUS (-66%) and KKR (-36.7pp on win rate) all fall outside the '
            'pre-registered tolerances; only AAPL reproduces. The larger result is outside '
            'the hypothesis: restricted to exits priced by a real Databento print, TMUS '
            'goes +$151 -> -$81/yr per contract and KKR +$316 -> -$88, while AAPL (97.5% '
            'coverage) does not move. Deployed: corrected expected_* on all four tickers, '
            'TMUS and KKR demoted to probation by the pre-registered coverage rule, '
            'results/012_walk_forward.md marked superseded.'
        ),
    ),
    dict(
        signal_id='H26', passed=False, layer=3,
        metrics={
            'n_trades': 2143,
            'clause_1_passing': '3/4 (AAPL +20.7%, DIS +90.4%, KKR +286.2%; TMUS fails)',
            'clause_2_passing': '1/4 (DIS at threshold 75, +58.1% on the holdout)',
            'tmus_blocked_entries': '109 blocked, averaging +$48.36 each (103W/6L)',
            'aapl_contradiction':
                'passes per-entry (+20.7%) but loses per year ($299 vs $453 ungated)',
            'assignments': 0,
            'result_file': 'results/023_iv_rank_gate.md',
        },
        failure_reason=(
            'Recorded as failed overall because H26 is a conjunction and clause 2 resolves '
            'for only one ticker. Clause 1 is the first pre-registered clause in this '
            'programme to PASS, and it passes for 3 of 4 tickers: the live IV-rank >= 50 '
            'gate does beat no gate on holdout mean P&L per entry for AAPL, DIS and KKR. '
            'It FAILS for TMUS, where it blocks the winners and keeps the losers. Deployed: '
            'DIS iv_threshold = 75 (the only clause-2 pass, holdout n=5 — the thinnest '
            'evidence behind any live parameter). TMUS keeps the gate despite its failure: '
            'removing a restriction is a loosening change and needs its own experiment.'
        ),
    ),
]


def main():
    print("=" * 78)
    print("RECORDING PART 0 VERDICTS (H25-H26)")
    print(f"graveyard backend: {signal_registry.backend()}")
    print("=" * 78)
    for r in RESULTS:
        signal_registry.mark_result(**r)
    print("\nVerdicts recorded. Full write-ups: results/022_baseline_rederivation.md, "
          "results/023_iv_rank_gate.md")


if __name__ == "__main__":
    main()
