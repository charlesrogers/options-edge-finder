"""
Experiment 023 — The IV-rank entry gate on trial (H26).

Pre-registration: experiments/023_iv_rank_gate/README.md (committed first, pushed
2026-08-17T21:56:29Z in commit 01c40bf, before this file existed).

`DEFAULT_IV_THRESHOLD = 50` is live on every ticker and its evidence is Experiment 009 —
one un-staggered path on the simulator with the broken DTE clock. This runs the gate
against no gate and against per-ticker alternatives on the fixed engine, walk-forward.

Nothing here spends money: owned Databento OHLCV, cached stock closes.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import numpy as np
import pandas as pd

import cc_sim
import lib_phase3 as P3
from ticker_strategies import TICKER_STRATEGIES

GATING = ['AAPL', 'DIS', 'TMUS', 'KKR']
CONTROL = {'TXN': 0.10}
THRESHOLDS = [25, 50, 75]      # arm C is chosen from these on the TRAIN window only
PRODUCTION_THRESHOLD = 50
MARGIN = 0.10                  # 10% relative, immutable
TRAIN_FRAC = 0.67
N_CHAINS = 25


def production_cfg(ticker, otm_override=None):
    strat = TICKER_STRATEGIES.get(ticker, {})
    return {
        'otm_pct': otm_override if otm_override is not None else strat['otm_pct'],
        'min_dte': strat.get('min_dte') or 20,
        'max_dte': strat.get('max_dte') or 45,
        'slippage': 0.0,
        'close_soon_days': 5,
    }


def split(trades, cut):
    """Calendar split — the SAME cut date for every arm, so arms with different entry
    counts are still divided at the same moment in time."""
    cut = str(cut)[:10]
    return ([t for t in trades if t.entry_date < cut],
            [t for t in trades if t.entry_date >= cut])


def arm_stats(trades):
    if not trades:
        return {'n_entries': 0, 'mean_pnl_per_entry': None, 'total_pnl': 0.0,
                'loss_rate': None, 'retention_pct': None, 'assignments': 0}
    s = cc_sim.score(trades)
    pnl = np.array([t.pnl_per_share for t in trades]) * 100
    return {
        'n_entries': len(trades),
        'mean_pnl_per_entry': round(float(pnl.mean()), 2),
        'median_pnl_per_entry': round(float(np.median(pnl)), 2),
        'total_pnl': round(float(pnl.sum()), 2),
        'loss_rate': s['loss_rate'],
        'win_rate': s['win_rate'],
        'retention_pct': s['retention_pct'],
        'gross_premium': s['gross_premium'],
        'net_pnl': s['net_pnl'],
        'assignments': s['assignments'],
        'worst_trade': s['worst_trade'],
    }


def beats(candidate, baseline, margin=MARGIN):
    """
    Does `candidate` beat `baseline` by >= `margin` relative?

    Sign convention fixed in the pre-registration, because a relative comparison is
    undefined-to-misleading when the baseline is <= 0 (the H23 lesson): when the baseline
    is non-positive, the candidate must improve on it by at least `margin` x |baseline|
    AND end up positive. Both operands are always reported alongside the verdict.
    """
    if candidate is None or baseline is None:
        return None, None
    if baseline > 0:
        return bool(candidate >= baseline * (1 + margin)), round(candidate / baseline - 1, 4)
    required = baseline + margin * abs(baseline)
    return bool(candidate >= required and candidate > 0), None


def chain_annualised(trades):
    """Decision-relevant view: annualised net P&L per contract over staggered chains."""
    vals = []
    for s in range(N_CHAINS):
        chain = P3.sequential_chain(trades, s)
        if len(chain) < 2:
            continue
        first = pd.Timestamp(min(t.entry_date for t in chain))
        last = pd.Timestamp(max(t.exit_date for t in chain))
        span = (last - first).days
        if span <= 0:
            continue
        net = sum(t.pnl_per_share for t in chain) * 100
        vals.append(net * 365.0 / span)
    if not vals:
        return {'n_chains': 0}
    return {'n_chains': len(vals),
            'median': round(float(np.median(vals)), 2),
            'min': round(float(np.min(vals)), 2),
            'max': round(float(np.max(vals)), 2)}


def run_ticker(ticker, otm_override=None, gating=True):
    print(f"\n{'=' * 78}\n{ticker} — IV-rank gate arms on the fixed engine\n{'=' * 78}")
    # Baseline window pinned per the Phase 3 spec's binding ruling (caveat 1):
    # WINDOW_LEGACY_PRE_STRESS reproduces results/012's inputs exactly, so the
    # as_of clock fix stays the ONLY changed variable. Without it the loader
    # concatenates the purchased 2020/2022 stress files into the baseline.
    chain = cc_sim.load_ticker(ticker, *cc_sim.WINDOW_LEGACY_PRE_STRESS)
    cfg = production_cfg(ticker, otm_override)
    cut = chain.option_days[int(len(chain.option_days) * TRAIN_FRAC)]
    print(f"  cfg: {cfg['otm_pct']:.0%} OTM, {cfg['min_dte']}-{cfg['max_dte']} DTE; "
          f"walk-forward cut {str(cut)[:10]} "
          f"(train {str(chain.option_days[0])[:10]}..{str(cut)[:10]}, "
          f"holdout {str(cut)[:10]}..{str(chain.option_days[-1])[:10]})")

    arms = {}
    coverage = {}
    trades_by_arm = {}
    for name, gate in [('no_gate', cc_sim.no_gate())] + \
                      [(f'iv{k}', cc_sim.iv_rank_gate(k)) for k in THRESHOLDS]:
        trades, diag = cc_sim.run(chain, cfg, cc_sim.baseline_policy, gate=gate,
                                  progress_every=0, label=f'{ticker}/{name}')
        train, hold = split(trades, cut)
        trades_by_arm[name] = trades
        arms[name] = {
            'train': arm_stats(train), 'holdout': arm_stats(hold), 'full': arm_stats(trades),
            'chains_annualised_full': chain_annualised(trades),
        }
        coverage[name] = {
            'repricing_coverage_pct': round(100.0 - diag['missing_price_pct'], 1),
            'never_repriced_trades': diag['never_repriced_trades'],
            'skipped': diag['skipped'],
        }
        h = arms[name]['holdout']
        print(f"    {name:8s} entries {arms[name]['full']['n_entries']:4d} "
              f"(train {arms[name]['train']['n_entries']:3d} / holdout {h['n_entries']:3d})  "
              f"holdout mean ${h['mean_pnl_per_entry'] if h['mean_pnl_per_entry'] is not None else float('nan'):8.2f}/entry  "
              f"total ${h['total_pnl']:9.2f}  assign {h['assignments']}  "
              f"coverage {coverage[name]['repricing_coverage_pct']:.1f}%")

    # ---- clause 1: does the production gate beat no gate on the holdout? ----
    prod = f'iv{PRODUCTION_THRESHOLD}'
    c1_pass, c1_rel = beats(arms[prod]['holdout']['mean_pnl_per_entry'],
                            arms['no_gate']['holdout']['mean_pnl_per_entry'])
    blocked = P3.blocked_entry_stats(trades_by_arm['no_gate'], trades_by_arm[prod])

    # ---- clause 2: per-ticker threshold, CHOSEN ON TRAIN ONLY ----
    train_means = {f'iv{k}': arms[f'iv{k}']['train']['mean_pnl_per_entry'] for k in THRESHOLDS}
    pickable = {k: v for k, v in train_means.items() if v is not None}
    arm_c = max(pickable, key=pickable.get) if pickable else prod
    c2_pass, c2_rel = beats(arms[arm_c]['holdout']['mean_pnl_per_entry'],
                            arms[prod]['holdout']['mean_pnl_per_entry'])
    c_threshold = int(arm_c.replace('iv', ''))
    no_extra_assignments = (arms[arm_c]['holdout']['assignments']
                            <= arms[prod]['holdout']['assignments'])

    deploy = bool(gating and c2_pass and c_threshold >= PRODUCTION_THRESHOLD
                  and no_extra_assignments and arm_c != prod)
    if gating and c2_pass and c_threshold < PRODUCTION_THRESHOLD:
        deploy_note = (f'clause 2 passes at iv{c_threshold}, which is LOOSER than the live 50 '
                       f'— not deployed (pre-registration rule 4: needs its own experiment)')
    elif gating and c2_pass and not no_extra_assignments:
        deploy_note = 'clause 2 passes but the arm adds assignments — hard constraint blocks it'
    elif deploy:
        deploy_note = f'deploy per-ticker iv_threshold = {c_threshold}'
    else:
        deploy_note = 'no production change'

    print(f"  CLAUSE 1 (gate vs no gate, holdout mean/entry): "
          f"${arms[prod]['holdout']['mean_pnl_per_entry']} vs "
          f"${arms['no_gate']['holdout']['mean_pnl_per_entry']} "
          f"({'+' if (c1_rel or 0) >= 0 else ''}{f'{c1_rel:.1%}' if c1_rel is not None else 'n/a (baseline <= 0)'}) "
          f"-> {'PASS' if c1_pass else 'FAIL'}")
    print(f"    the gate blocked {blocked.get('n_blocked', 0)} entries worth "
          f"${blocked.get('blocked_mean_pnl', 0)}/entry on average "
          f"({blocked.get('blocked_winners', 0)}W/{blocked.get('blocked_losers', 0)}L)")
    print(f"  CLAUSE 2 (train-picked {arm_c} vs live iv50, holdout mean/entry): "
          f"${arms[arm_c]['holdout']['mean_pnl_per_entry']} vs "
          f"${arms[prod]['holdout']['mean_pnl_per_entry']} -> "
          f"{'PASS' if c2_pass else 'FAIL'} | {deploy_note}")
    print(f"  annualised chain view (non-gating): "
          + ", ".join(f"{n}=${arms[n]['chains_annualised_full'].get('median')}"
                      for n in arms))

    return {
        'ticker': ticker, 'cfg': cfg, 'gating': gating,
        'walk_forward_cut': str(cut)[:10],
        'arms': arms, 'coverage': coverage,
        'clause_1': {
            'production_holdout_mean': arms[prod]['holdout']['mean_pnl_per_entry'],
            'no_gate_holdout_mean': arms['no_gate']['holdout']['mean_pnl_per_entry'],
            'relative': c1_rel, 'passes': c1_pass,
            'blocked_entries': blocked,
        },
        'clause_2': {
            'train_means': train_means, 'arm_selected_on_train': arm_c,
            'selected_holdout_mean': arms[arm_c]['holdout']['mean_pnl_per_entry'],
            'production_holdout_mean': arms[prod]['holdout']['mean_pnl_per_entry'],
            'relative': c2_rel, 'passes': c2_pass,
            'holdout_assignments_selected': arms[arm_c]['holdout']['assignments'],
            'holdout_assignments_production': arms[prod]['holdout']['assignments'],
            'no_extra_assignments': no_extra_assignments,
            'deploy': deploy, 'deploy_note': deploy_note,
        },
    }


def main():
    print("=" * 78)
    print("EXPERIMENT 023 — IV-rank entry gate on trial (H26)")
    print("Pre-registered in commit 01c40bf, pushed 2026-08-17T21:56:29Z")
    print("=" * 78)

    results = {'gating': {}, 'control': {}}
    for ticker in GATING:
        results['gating'][ticker] = run_ticker(ticker)
    for ticker, otm in CONTROL.items():
        results['control'][ticker] = run_ticker(ticker, otm_override=otm, gating=False)

    results['h26_verdict'] = {
        'clause_1_per_ticker': {t: r['clause_1']['passes'] for t, r in results['gating'].items()},
        'clause_2_per_ticker': {t: r['clause_2']['passes'] for t, r in results['gating'].items()},
        'deployments': {t: r['clause_2']['deploy_note'] for t, r in results['gating'].items()
                        if r['clause_2']['deploy']},
    }
    print("\n" + "=" * 78)
    print(f"H26 clause 1 (gate earns its place): {results['h26_verdict']['clause_1_per_ticker']}")
    print(f"H26 clause 2 (per-ticker beats 50):  {results['h26_verdict']['clause_2_per_ticker']}")
    print(f"Deployments: {results['h26_verdict']['deployments'] or 'none'}")
    print("=" * 78)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results.json')
    with open(out, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out}")


if __name__ == '__main__':
    main()
