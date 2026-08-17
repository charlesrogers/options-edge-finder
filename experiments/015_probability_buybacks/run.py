"""
Experiment 015 (H17): Probability-Based Buyback Thresholds.

Pre-registration: experiments/015_probability_buybacks/README.md — frozen.
Do not read this file as the specification; the README is.

Swaps the copilot's distance-based CLOSE_SOON/CLOSE_NOW triggers for lookups
against the empirical 145,099-observation assignment table (moneyness x DTE)
and asks whether that keeps more premium without letting a single assignment
through.

Both arms see identical entries and identical price paths, so every comparison
here is paired.

    python3 experiments/015_probability_buybacks/run.py
"""

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import cc_sim
from ticker_strategies import TICKER_STRATEGIES

# --- pre-registered grid (arbitrary starting values, NOT derived) ---
CLOSE_SOON_P = [0.10, 0.15, 0.20]
CLOSE_NOW_P = [0.25, 0.35, 0.45]

# Production tickers with usable Databento option history. GOOGL (5 days) and
# AMZN (0 days) cannot be tested on real prices — see README.
PRODUCTION_TICKERS = ['AAPL', 'DIS', 'TMUS', 'KKR']
# Reported for completeness; production tier is 'skip', so it never counts
# toward the pass criterion. 10% OTM is Exp 008's only non-losing setting.
REFERENCE_TICKERS = {'TXN': {'otm_pct': 0.10, 'min_dte': 20, 'max_dte': 45}}

TRAIN_FRAC = 0.67
IV_THRESHOLD = 50


def ticker_config(ticker):
    if ticker in REFERENCE_TICKERS:
        return dict(REFERENCE_TICKERS[ticker])
    s = TICKER_STRATEGIES[ticker]
    return {'otm_pct': s['otm_pct'], 'min_dte': s['min_dte'], 'max_dte': s['max_dte']}


def select_on_train(arms, baseline_train):
    """Pick a threshold pair using TRAIN data only.

    Rule, fixed before the run: among pairs with zero train assignments and
    train net P&L at or above the train baseline, take the highest train
    retention; ties broken by train net P&L. If nothing qualifies, the ticker
    has no train-selected candidate and fails the secondary gate.
    """
    eligible = [a for a in arms
                if a['train']['assignments'] == 0
                and a['train']['net_pnl'] >= baseline_train['net_pnl']]
    if not eligible:
        return None
    eligible.sort(key=lambda a: (a['train']['retention_pct'], a['train']['net_pnl']),
                  reverse=True)
    return eligible[0]


def run_ticker(ticker, cfg_extra=None):
    cfg = {**ticker_config(ticker), **(cfg_extra or {})}
    chain = cc_sim.load_ticker(ticker)
    gate = cc_sim.iv_rank_gate(IV_THRESHOLD)

    print(f'\n  --- {ticker} @ {cfg["otm_pct"]*100:.0f}% OTM, '
          f'{cfg["min_dte"]}-{cfg["max_dte"]} DTE ---', flush=True)

    print('    baseline (current copilot, as_of + real ex-div)...', flush=True)
    base_trades, base_diag = cc_sim.run(chain, cfg, cc_sim.baseline_policy,
                                        gate=gate, progress_every=0,
                                        label=f'{ticker} base')
    base_train, base_test, cut = cc_sim.walk_forward_split(base_trades, TRAIN_FRAC)
    baseline = {
        'label': 'baseline',
        'all': cc_sim.score(base_trades),
        'train': cc_sim.score(base_train),
        'test': cc_sim.score(base_test),
        'diagnostics': base_diag,
        'exit_reasons': dict(Counter(t.exit_reason for t in base_trades)),
    }
    print(f'      {base_diag["entries"]} entries, split at {cut} '
          f'({len(base_train)} train / {len(base_test)} test), '
          f'{base_diag["missing_price_pct"]}% missing price days')
    print(f'      TEST  retention {baseline["test"]["retention_pct"]:5.1f}%  '
          f'net ${baseline["test"]["net_pnl"]:>9,.0f}  '
          f'assign {baseline["test"]["assignments"]}')

    arms = []
    n = 0
    for cs in CLOSE_SOON_P:
        for cn in CLOSE_NOW_P:
            n += 1
            policy = cc_sim.make_probability_policy(cs, cn)
            trades, diag = cc_sim.run(chain, cfg, policy, gate=gate,
                                      progress_every=0, label=policy.label)
            train, test, _ = cc_sim.walk_forward_split(trades, TRAIN_FRAC)
            arm = {
                'label': policy.label,
                'close_soon_p': cs,
                'close_now_p': cn,
                'all': cc_sim.score(trades),
                'train': cc_sim.score(train),
                'test': cc_sim.score(test),
                'diagnostics': diag,
                'exit_reasons': dict(Counter(t.exit_reason for t in trades)),
                'paired_vs_baseline_test': cc_sim.paired_difference(base_test, test),
            }
            arms.append(arm)
            t = arm['test']
            print(f'    [{n}/9] CS>{cs:.0%} CN>{cn:.0%}  '
                  f'TEST retention {t["retention_pct"]:5.1f}%  '
                  f'net ${t["net_pnl"]:>9,.0f}  assign {t["assignments"]}  '
                  f'buybacks {t["buyback_count"]:>3d}  '
                  f'worst ${t["worst_trade"]:>8,.0f}', flush=True)

    # --- primary criterion, exactly as pre-registered (selects on test) ---
    primary_pass = [
        a for a in arms
        if a['test']['retention_pct'] >= 20
        and a['test']['assignments'] == 0
        and a['test']['net_pnl'] >= baseline['test']['net_pnl']
    ]

    # --- secondary (honest walk-forward) gate ---
    selected = select_on_train(arms, baseline['train'])
    secondary_pass = False
    if selected:
        t = selected['test']
        secondary_pass = (t['retention_pct'] >= 20 and t['assignments'] == 0
                          and t['net_pnl'] >= baseline['test']['net_pnl'])
        print(f'    train-selected: {selected["label"]} -> '
              f'TEST retention {t["retention_pct"]:.1f}%, net ${t["net_pnl"]:,.0f}, '
              f'assign {t["assignments"]} => '
              f'{"PASS" if secondary_pass else "FAIL"}')
    else:
        print('    train-selected: none qualified on train => FAIL')

    return {
        'ticker': ticker,
        'config': cfg,
        'split_date': cut,
        'baseline': baseline,
        'arms': arms,
        'primary_pass_arms': [a['label'] for a in primary_pass],
        'primary_pass': bool(primary_pass),
        'train_selected': selected['label'] if selected else None,
        'secondary_pass': secondary_pass,
    }


def main():
    print('=' * 90)
    print('EXPERIMENT 015 (H17): Probability-Based Buyback Thresholds')
    print('Real Databento prices. as_of passed. Real ex-dividend dates.')
    print('=' * 90)

    for t, why in cc_sim.UNUSABLE_TICKERS.items():
        print(f'  EXCLUDED {t}: {why}')

    results = {}
    for ticker in PRODUCTION_TICKERS + list(REFERENCE_TICKERS):
        try:
            results[ticker] = run_ticker(ticker)
        except Exception as e:
            print(f'  {ticker} FAILED: {type(e).__name__}: {e}')
            results[ticker] = {'ticker': ticker, 'error': f'{type(e).__name__}: {e}'}

    # --- slippage sensitivity on the train-selected arm ---
    print('\n' + '=' * 90)
    print('SLIPPAGE SENSITIVITY (5% on every buyback, train-selected arm)')
    print('=' * 90)
    sensitivity = {}
    for ticker in PRODUCTION_TICKERS:
        r = results.get(ticker, {})
        if not r.get('train_selected'):
            continue
        arm = next(a for a in r['arms'] if a['label'] == r['train_selected'])
        cfg = {**ticker_config(ticker), 'slippage': 0.05}
        chain = cc_sim.load_ticker(ticker, verbose=False)
        gate = cc_sim.iv_rank_gate(IV_THRESHOLD)
        policy = cc_sim.make_probability_policy(arm['close_soon_p'], arm['close_now_p'])
        tr, _ = cc_sim.run(chain, cfg, policy, gate=gate, progress_every=0)
        _, test, _ = cc_sim.walk_forward_split(tr, TRAIN_FRAC)
        b, _ = cc_sim.run(chain, cfg, cc_sim.baseline_policy, gate=gate, progress_every=0)
        _, btest, _ = cc_sim.walk_forward_split(b, TRAIN_FRAC)
        s, bs = cc_sim.score(test), cc_sim.score(btest)
        sensitivity[ticker] = {'treatment': s, 'baseline': bs}
        print(f'  {ticker}: treatment retention {s["retention_pct"]:5.1f}% '
              f'net ${s["net_pnl"]:>9,.0f}  |  baseline {bs["retention_pct"]:5.1f}% '
              f'net ${bs["net_pnl"]:>9,.0f}')

    # --- verdict ---
    print('\n' + '=' * 90)
    print('VERDICT')
    print('=' * 90)
    prod = [results[t] for t in PRODUCTION_TICKERS if 'error' not in results.get(t, {})]
    n_primary = sum(1 for r in prod if r['primary_pass'])
    n_secondary = sum(1 for r in prod if r['secondary_pass'])

    print(f'\n  {"Ticker":<8} {"base ret":>9} {"best ret":>9} {"base net":>10} '
          f'{"best net":>10} {"assign":>7} {"primary":>8} {"secondary":>10}')
    print('  ' + '-' * 78)
    for r in prod:
        best = max(r['arms'], key=lambda a: a['test']['retention_pct'])
        print(f'  {r["ticker"]:<8} {r["baseline"]["test"]["retention_pct"]:>8.1f}% '
              f'{best["test"]["retention_pct"]:>8.1f}% '
              f'${r["baseline"]["test"]["net_pnl"]:>9,.0f} '
              f'${best["test"]["net_pnl"]:>9,.0f} '
              f'{best["test"]["assignments"]:>7d} '
              f'{"PASS" if r["primary_pass"] else "FAIL":>8} '
              f'{"PASS" if r["secondary_pass"] else "FAIL":>10}')

    print(f'\n  PRIMARY   (spec literal, selects on test): {n_primary}/4 tickers '
          f'=> {"PASS" if n_primary >= 3 else "FAIL"} (needs >= 3)')
    print(f'  SECONDARY (train-selected -> test):        {n_secondary}/4 tickers '
          f'=> {"PASS" if n_secondary >= 3 else "FAIL"} (needs >= 3)')
    print('\n  Only tickers clearing the SECONDARY gate are deployable, and only '
          'after 2 weeks of shadow mode.')

    out = os.path.join(os.path.dirname(__file__), 'results.json')
    with open(out, 'w') as f:
        json.dump({'results': results, 'slippage_sensitivity': sensitivity,
                   'n_primary': n_primary, 'n_secondary': n_secondary,
                   'grid': {'close_soon_p': CLOSE_SOON_P, 'close_now_p': CLOSE_NOW_P},
                   'train_frac': TRAIN_FRAC, 'iv_threshold': IV_THRESHOLD},
                  f, indent=2, default=str)
    print(f'\nResults saved to {out}')


if __name__ == '__main__':
    main()
