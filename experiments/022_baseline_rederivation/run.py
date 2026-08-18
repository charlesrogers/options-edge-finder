"""
Experiment 022 — Baseline Re-derivation on the fixed engine (H25).

Pre-registration: experiments/022_baseline_rederivation/README.md (committed first,
pushed 2026-08-17T21:56:29Z in commit 01c40bf, before this file existed).

Re-derives every per-ticker number the product publishes — expected_pnl,
expected_win_rate, expected_trades, and the walk-forward table in
results/012_walk_forward.md — on experiments/cc_sim.py, which passes a real `as_of`,
real ex-dividend dates, and simulates assignment instead of inferring it. The
deployed values came from the simulator that pinned DTE to 0.

Nothing here spends money: owned Databento OHLCV, cached stock closes.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import numpy as np
import pandas as pd

import cc_sim
import lib_phase3 as P3
from ticker_strategies import TICKER_STRATEGIES

# Live tickers with real option data — these four are gating.
GATING = ['AAPL', 'DIS', 'TMUS', 'KKR']
# Production tier = skip. Reported, never gating, cannot deploy anything.
CONTROL = {'TXN': 0.10}   # the one OTM% Exp 008 did not reject for TXN

N_CHAINS = 25                 # staggered start offsets, as in Exp 020
PNL_TOLERANCE = 0.25          # +/-25% relative, immutable
WIN_RATE_TOLERANCE = 10.0     # +/-10 percentage points, immutable
COVERAGE_FLOOR = 70.0         # arbitrary, pre-registered; any value in 57-85% partitions alike


def production_cfg(ticker, otm_override=None):
    strat = TICKER_STRATEGIES.get(ticker, {})
    return {
        'otm_pct': otm_override if otm_override is not None else strat['otm_pct'],
        'min_dte': strat.get('min_dte') or 20,
        'max_dte': strat.get('max_dte') or 45,
        'slippage': 0.0,
        'close_soon_days': 5,
    }


def exit_is_real_fill(chain, trade):
    """
    Did this trade's exit price come from a real quote?

    Settlement exits (expiry, early exercise) are priced off the stock, so they need no
    option quote and count as real. A policy close is real only if Databento actually
    printed that symbol on that date; otherwise the buyback was paid at a price carried
    forward from an earlier day.
    """
    if trade.exit_reason.startswith('expiry') or trade.exit_reason == 'early_exercise':
        return True
    return chain.price.get((trade.symbol, pd.Timestamp(trade.exit_date))) is not None


def chain_stats(trades):
    """One sequential chain -> the numbers `expected_*` claims to be."""
    if len(trades) < 2:
        return None
    first = pd.Timestamp(min(t.entry_date for t in trades))
    last = pd.Timestamp(max(t.exit_date for t in trades))
    span = (last - first).days
    if span <= 0:
        return None
    net = sum(t.pnl_per_share for t in trades) * 100
    gross = sum(t.premium for t in trades) * 100
    wins = sum(1 for t in trades if t.pnl_per_share > 0)
    return {
        'n_trades': len(trades),
        'span_days': span,
        'net_pnl': round(net, 2),
        'annualised_pnl': round(net * 365.0 / span, 2),
        'trades_per_year': round(len(trades) * 365.0 / span, 1),
        'gross_premium': round(gross, 2),
        'retention_pct': round(net / gross * 100, 1) if gross > 0 else None,
        'win_rate': round(wins / len(trades) * 100, 1),
        'loss_rate': round(sum(1 for t in trades if t.pnl_per_share < 0) / len(trades) * 100, 1),
        'assignments': sum(1 for t in trades if t.assigned),
        'buybacks': sum(1 for t in trades if t.exit_reason.startswith('policy_')),
        'worst_trade': round(min(t.pnl_per_share for t in trades) * 100, 2),
    }


def summarise_chains(rows):
    """Median + min/max across staggered chains, with the undefined ones counted."""
    rows = [r for r in rows if r]
    if not rows:
        return {'n_chains': 0}

    def agg(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        if not vals:
            return {'median': None, 'min': None, 'max': None, 'n': 0}
        return {'median': round(float(np.median(vals)), 2),
                'min': round(float(np.min(vals)), 2),
                'max': round(float(np.max(vals)), 2),
                'n': len(vals)}

    return {
        'n_chains': len(rows),
        'annualised_pnl': agg('annualised_pnl'),
        'win_rate': agg('win_rate'),
        'loss_rate': agg('loss_rate'),
        'retention_pct': agg('retention_pct'),
        'retention_undefined_chains': sum(1 for r in rows if r.get('retention_pct') is None),
        'trades_per_year': agg('trades_per_year'),
        'buybacks': agg('buybacks'),
        'assignments_total': sum(r['assignments'] for r in rows),
        'worst_trade': agg('worst_trade'),
    }


def half_year_windows(trades):
    """Scorecard per calendar half-year of ENTRY date — regime luck, made visible."""
    buckets = {}
    for t in trades:
        d = pd.Timestamp(t.entry_date)
        buckets.setdefault(f"{d.year}H{1 if d.month <= 6 else 2}", []).append(t)
    out = []
    for label in sorted(buckets):
        s = cc_sim.score(buckets[label])
        out.append({
            'window': label, 'n_trades': s['n_trades'],
            'net_pnl': s['net_pnl'], 'net_per_trade': round(s['avg_pnl'], 2),
            'retention_pct': s['retention_pct'], 'win_rate': s['win_rate'],
            'loss_rate': s['loss_rate'], 'assignments': s['assignments'],
        })
    return out


def dte_bug_blast_radius():
    """
    Spec directive 3: verify (don't assume) that the two artefacts we still rely on are
    independent of the DTE bug.

    Both claims are structural, so a static trace answers them: does the derivation ever
    call assess_position(), and does it ever compute DTE from the wall clock?
    """
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
    findings = {}

    pm = open(os.path.join(root, 'position_monitor.py')).read()
    lookup_body = re.search(r'def lookup_itm_probability\([\s\S]*?(?=\n(?:def |@|# =))', pm)
    lookup_body = lookup_body.group(0) if lookup_body else ''
    findings['exp006_probability_table'] = {
        'file': 'position_monitor.py',
        # The table is a hardcoded literal derived from raw observations (Study A), and the
        # lookup takes DTE as an ARGUMENT. Neither can depend on assess_position, which is
        # the function the bug lived in. What would contaminate it is a wall-clock read
        # inside the lookup, or the table being computed at import time from a broken path.
        'table_is_literal': bool(re.search(r'^ITM_PROBABILITY\s*=\s*\{', pm, re.M)),
        'table_built_by_computation': not bool(re.search(
            r'^ITM_PROBABILITY\s*=\s*\{', pm, re.M)),
        'lookup_takes_dte_as_argument': 'def lookup_itm_probability(pct_from_strike, dte)' in pm,
        'lookup_calls_assess_position': 'assess_position(' in lookup_body,
        'wall_clock_in_lookup': bool(re.search(r'datetime\.now|date\.today', lookup_body)),
        'caveat': ('The table is clean; the BACKTESTS that consumed it through '
                   'assess_position() were not — those always asked it for dte=0.'),
    }

    exp014 = open(os.path.join(root, 'experiments', '014_validated_param_update', 'run.py')).read()
    findings['exp014_stock_close_walkforward'] = {
        'file': 'experiments/014_validated_param_update/run.py',
        'imports_position_monitor': 'position_monitor' in exp014,
        'calls_assess_position': 'assess_position(' in exp014,
        'uses_wall_clock': bool(re.search(r'datetime\.now|date\.today', exp014)),
    }
    return findings


def run_ticker(ticker, otm_override=None, gating=True):
    print(f"\n{'=' * 78}\n{ticker} — production settings on the fixed engine\n{'=' * 78}")
    # Baseline window pinned per the Phase 3 spec's binding ruling (caveat 1):
    # WINDOW_LEGACY_PRE_STRESS reproduces results/012's inputs exactly, so the
    # as_of clock fix stays the ONLY changed variable. Without it the loader
    # concatenates the purchased 2020/2022 stress files into the baseline.
    chain = cc_sim.load_ticker(ticker, *cc_sim.WINDOW_LEGACY_PRE_STRESS)
    cfg = production_cfg(ticker, otm_override)
    print(f"  cfg: {cfg['otm_pct']:.0%} OTM, {cfg['min_dte']}-{cfg['max_dte']} DTE, "
          f"gate=iv_rank>=50, policy=production copilot")

    trades, diag = cc_sim.run(chain, cfg, cc_sim.baseline_policy,
                              gate=cc_sim.iv_rank_gate(50), progress_every=100,
                              label=f'{ticker}/022')

    coverage = 100.0 - diag['missing_price_pct']
    real_fill = [t for t in trades if exit_is_real_fill(chain, t)]
    print(f"  {len(trades)} entries from {diag['candidate_days']} option days "
          f"(skipped: {diag['skipped']})")
    print(f"  repricing coverage {coverage:.1f}% "
          f"({diag['missing_price_days']} missing / {diag['priced_days']} priced position-days), "
          f"{diag['never_repriced_trades']} never-repriced trades, "
          f"{diag['data_ended_trades']} ran past the data")
    print(f"  real-fill exits: {len(real_fill)}/{len(trades)} "
          f"({len(real_fill) / len(trades) * 100:.1f}%)" if trades else "  no trades")

    chains = [chain_stats(P3.sequential_chain(trades, s)) for s in range(N_CHAINS)]
    chains_real = [chain_stats([t for t in P3.sequential_chain(trades, s)
                                if exit_is_real_fill(chain, t)]) for s in range(N_CHAINS)]
    summary = summarise_chains(chains)
    summary_real = summarise_chains(chains_real)

    if summary['n_chains']:
        a = summary['annualised_pnl']
        w = summary['win_rate']
        print(f"  corrected annualised net P&L/contract: median ${a['median']:,.0f} "
              f"[{a['min']:,.0f} .. {a['max']:,.0f}] across {summary['n_chains']} chains")
        print(f"  corrected win rate: median {w['median']:.0f}% "
              f"[{w['min']:.0f} .. {w['max']:.0f}]")
        print(f"  trades/yr median {summary['trades_per_year']['median']:.1f}, "
              f"assignments across all chains: {summary['assignments_total']}")

    strat = TICKER_STRATEGIES.get(ticker, {})
    dep_pnl, dep_wr = strat.get('expected_pnl'), strat.get('expected_win_rate')
    verdict = {'gating': gating}
    if gating and summary['n_chains'] and dep_pnl:
        got_pnl = summary['annualised_pnl']['median']
        got_wr = summary['win_rate']['median']
        pnl_rel = (got_pnl - dep_pnl) / abs(dep_pnl)
        wr_abs = got_wr - dep_wr if dep_wr is not None else None
        verdict.update({
            'deployed_expected_pnl': dep_pnl, 'corrected_expected_pnl': got_pnl,
            'pnl_relative_error': round(pnl_rel, 3),
            'pnl_within_tolerance': abs(pnl_rel) <= PNL_TOLERANCE,
            'deployed_expected_win_rate': dep_wr, 'corrected_win_rate': got_wr,
            'win_rate_abs_error_pp': round(wr_abs, 1) if wr_abs is not None else None,
            'win_rate_within_tolerance': (abs(wr_abs) <= WIN_RATE_TOLERANCE
                                          if wr_abs is not None else False),
        })
        verdict['passes'] = bool(verdict['pnl_within_tolerance']
                                 and verdict['win_rate_within_tolerance'])
        print(f"  H25 tolerance check: deployed ${dep_pnl:,}/yr vs corrected "
              f"${got_pnl:,.0f}/yr ({pnl_rel:+.0%}, limit +/-25%) | "
              f"win rate {dep_wr}% vs {got_wr:.0f}% ({wr_abs:+.1f}pp, limit +/-10pp) "
              f"-> {'WITHIN' if verdict['passes'] else 'OUTSIDE'}")

        # Deployment rule 2 — restricting only.
        low_coverage = coverage < COVERAGE_FLOOR
        non_positive = summary['annualised_pnl']['median'] <= 0
        verdict['demote_to_probation'] = bool(low_coverage or non_positive)
        verdict['demotion_reason'] = (
            'repricing coverage {:.1f}% < {:.0f}%'.format(coverage, COVERAGE_FLOOR)
            if low_coverage else
            'corrected median annualised net P&L <= $0' if non_positive else None)
        if verdict['demote_to_probation']:
            print(f"  DEPLOYMENT RULE 2 -> demote {ticker} to probation "
                  f"({verdict['demotion_reason']})")

    return {
        'ticker': ticker, 'cfg': cfg, 'gating': gating,
        'coverage': {
            'option_days': diag['candidate_days'], 'entries': len(trades),
            'skipped': diag['skipped'],
            'repricing_coverage_pct': round(coverage, 1),
            'missing_price_days': diag['missing_price_days'],
            'priced_days': diag['priced_days'],
            'never_repriced_trades': diag['never_repriced_trades'],
            'data_ended_trades': diag['data_ended_trades'],
            'real_fill_exits': len(real_fill),
            'real_fill_pct': round(len(real_fill) / len(trades) * 100, 1) if trades else None,
        },
        'window': [str(chain.option_days[0])[:10], str(chain.option_days[-1])[:10]],
        'all_trades': cc_sim.score(trades),
        'real_fill_trades': cc_sim.score(real_fill),
        'chains_all': summary,
        'chains_real_fill_only': summary_real,
        'half_year_windows': half_year_windows(trades),
        'verdict': verdict,
    }


def main():
    print("=" * 78)
    print("EXPERIMENT 022 — Baseline Re-derivation (H25)")
    print("Pre-registered in commit 01c40bf, pushed 2026-08-17T21:56:29Z")
    print("=" * 78)

    results = {'gating': {}, 'control': {}, 'dte_bug_blast_radius': dte_bug_blast_radius()}

    print("\nSPEC DIRECTIVE 3 — DTE-bug blast radius (static trace)")
    for k, v in results['dte_bug_blast_radius'].items():
        print(f"  {k}: {v}")

    for ticker in GATING:
        results['gating'][ticker] = run_ticker(ticker)
    for ticker, otm in CONTROL.items():
        results['control'][ticker] = run_ticker(ticker, otm_override=otm, gating=False)

    verdicts = {t: r['verdict'].get('passes') for t, r in results['gating'].items()}
    results['h25_verdict'] = {
        'per_ticker': verdicts,
        'passed': all(v is True for v in verdicts.values()),
        'demotions': {t: r['verdict'].get('demotion_reason')
                      for t, r in results['gating'].items()
                      if r['verdict'].get('demote_to_probation')},
    }

    print("\n" + "=" * 78)
    print(f"H25 VERDICT: {'PASS' if results['h25_verdict']['passed'] else 'FAIL'} — "
          f"per ticker {verdicts}")
    if results['h25_verdict']['demotions']:
        print(f"Demotions (restricting only): {results['h25_verdict']['demotions']}")
    print("=" * 78)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results.json')
    with open(out, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out}")


if __name__ == '__main__':
    main()
