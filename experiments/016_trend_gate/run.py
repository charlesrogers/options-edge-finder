"""
Experiment 016 (H18): Trend Gate on Call Entry.

Pre-registration: experiments/016_trend_gate/README.md — frozen.

Sinclair & Mack (2024) Ch. 10 & 15: options on trending stocks are
systematically cheap because BSM is fooled by trends, so selling calls into a
strong uptrend is selling underpriced insurance. Does suppressing those entries
cut the loss rate?

Implementation note: the gate only affects ENTRY. So the simulation is run once
per ticker with the production exit policy and the production IV gate, and each
candidate trend gate is then applied by partitioning those trades into kept and
skipped. The kept trades are therefore bit-identical to the ungated ones — no
second simulation, no chance of the two arms diverging for an unrelated reason.

    python3 experiments/016_trend_gate/run.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd

import cc_sim
from ticker_strategies import TICKER_STRATEGIES

# Pre-registered candidate gates. Arbitrary starting values, NOT derived.
# Tested independently — never combined (that surface overfits).
GATES = [
    ('r20_gt_5', 'r20', 0.05),
    ('r20_gt_8', 'r20', 0.08),
    ('r60_gt_12', 'r60', 0.12),
    ('r60_gt_18', 'r60', 0.18),
    ('autocorr_pct_gt_70', 'autocorr_pct', 70.0),
    ('autocorr_pct_gt_85', 'autocorr_pct', 85.0),
]

TARGETS = ['AAPL', 'TMUS']          # loss-bearing
CONTROLS = ['KKR', 'DIS']           # already clean — must not move
REFERENCE = {'TXN': {'otm_pct': 0.10, 'min_dte': 20, 'max_dte': 45}}

TRAIN_FRAC = 0.67
IV_THRESHOLD = 50

MAX_SKIP_PCT = 25.0
MIN_RELATIVE_REDUCTION = 30.0
CONTROL_TOLERANCE = 1


def ticker_config(ticker):
    if ticker in REFERENCE:
        return dict(REFERENCE[ticker])
    s = TICKER_STRATEGIES[ticker]
    return {'otm_pct': s['otm_pct'], 'min_dte': s['min_dte'], 'max_dte': s['max_dte']}


def loss_stats(trades):
    if not trades:
        return {'n': 0, 'losses': 0, 'loss_rate': 0.0, 'net_pnl': 0.0}
    losses = sum(1 for t in trades if t.pnl_per_share < 0)
    return {
        'n': len(trades),
        'losses': losses,
        'loss_rate': round(losses / len(trades) * 100, 1),
        'net_pnl': round(sum(t.pnl_per_share for t in trades) * 100, 2),
    }


def run_ticker(ticker):
    cfg = ticker_config(ticker)
    chain = cc_sim.load_ticker(ticker)
    gate = cc_sim.iv_rank_gate(IV_THRESHOLD)

    print(f'\n  --- {ticker} @ {cfg["otm_pct"]*100:.0f}% OTM, '
          f'{cfg["min_dte"]}-{cfg["max_dte"]} DTE ---', flush=True)

    trades, diag = cc_sim.run(chain, cfg, cc_sim.baseline_policy, gate=gate,
                              progress_every=0, label=ticker)
    train, test, cut = cc_sim.walk_forward_split(trades, TRAIN_FRAC)
    base_test = loss_stats(test)
    print(f'    {len(trades)} entries, split {cut} '
          f'({len(train)} train / {len(test)} test), '
          f'{diag["missing_price_pct"]}% missing price days')
    print(f'    ungated TEST: {base_test["losses"]}/{base_test["n"]} losses '
          f'({base_test["loss_rate"]:.1f}%), net ${base_test["net_pnl"]:,.0f}')

    results = []
    for name, feature, threshold in GATES:
        # One cohort per trading day, so entry_date uniquely identifies a trade.
        blocked_dates = set()
        no_data = 0
        for t in trades:
            blocked, val = cc_sim.trend_blocks(chain, t.entry_date, feature, threshold)
            if val is None:
                no_data += 1
            if blocked:
                blocked_dates.add(t.entry_date)

        kept_test = [t for t in test if t.entry_date not in blocked_dates]
        skipped_test = [t for t in test if t.entry_date in blocked_dates]

        g = loss_stats(kept_test)
        s = loss_stats(skipped_test)
        skip_pct = round(len(skipped_test) / len(test) * 100, 1) if test else 0.0
        rel_red = (round((base_test['loss_rate'] - g['loss_rate'])
                         / base_test['loss_rate'] * 100, 1)
                   if base_test['loss_rate'] > 0 else 0.0)
        winners_skipped = sum(1 for t in skipped_test if t.pnl_per_share > 0)
        fair_share = (round(np.mean([t.pnl_per_share for t in test
                                     if t.pnl_per_share > 0]) * 100 * winners_skipped, 2)
                      if winners_skipped else 0.0)
        pnl_given_up = round(base_test['net_pnl'] - g['net_pnl'], 2)

        results.append({
            'gate': name, 'feature': feature, 'threshold': threshold,
            'kept': g, 'skipped': s, 'skip_pct': skip_pct,
            'loss_delta': g['losses'] - base_test['losses'],
            'relative_reduction_pct': rel_red,
            'winners_skipped': winners_skipped,
            'winners_fair_share': fair_share,
            'pnl_given_up': pnl_given_up,
            'entries_without_trend_data': no_data,
        })
        print(f'    {name:<20} skip {skip_pct:5.1f}%  '
              f'losses {base_test["losses"]:>2d} -> {g["losses"]:>2d} '
              f'({rel_red:+6.1f}% rel)  net ${g["net_pnl"]:>9,.0f} '
              f'(gave up ${pnl_given_up:>8,.0f}, fair share ${fair_share:>8,.0f})')

    return {
        'ticker': ticker, 'config': cfg, 'split_date': cut,
        'diagnostics': diag, 'ungated_test': base_test, 'gates': results,
    }


def googl_stock_only():
    """GOOGL motivated this hypothesis but has 5 days of option data. This is a
    stock-only proxy: an entry 'loses' if the stock finishes above the strike at
    ~32 days. It ignores premium entirely, so it cannot say whether a trade made
    money. DIRECTIONAL ESTIMATE ONLY — NOT DEPLOYABLE.
    """
    print('\n  --- GOOGL (stock-only proxy, DIRECTIONAL ESTIMATE ONLY) ---')
    stock = cc_sim.load_stock('GOOGL')
    trend = cc_sim.compute_trend_features(stock)
    otm = TICKER_STRATEGIES['GOOGL']['otm_pct']
    dte = 32

    rows = []
    idx = stock.index
    for i in range(60, len(idx) - dte):
        d = idx[i]
        spot = float(stock.iloc[i])
        strike = spot * (1 + otm)
        future = float(stock.iloc[min(i + dte, len(idx) - 1)])
        rows.append({'date': d, 'lost': future > strike})
    df = pd.DataFrame(rows).set_index('date')
    df = df.join(trend, how='left')

    cut = df.index[int(len(df) * TRAIN_FRAC)]
    test = df[df.index >= cut]
    base_rate = test['lost'].mean() * 100

    print(f'    ungated TEST: {int(test["lost"].sum())}/{len(test)} '
          f'({base_rate:.1f}% would finish above strike)')

    out = []
    for name, feature, threshold in GATES:
        kept = test[~(test[feature] > threshold).fillna(False)]
        rate = kept['lost'].mean() * 100 if len(kept) else 0.0
        skip_pct = (1 - len(kept) / len(test)) * 100
        rel = (base_rate - rate) / base_rate * 100 if base_rate > 0 else 0.0
        out.append({'gate': name, 'kept': len(kept), 'rate': round(rate, 1),
                    'skip_pct': round(skip_pct, 1), 'relative_reduction_pct': round(rel, 1)})
        print(f'    {name:<20} skip {skip_pct:5.1f}%  '
              f'above-strike {base_rate:5.1f}% -> {rate:5.1f}% ({rel:+6.1f}% rel)')
    return {'ticker': 'GOOGL', 'directional_only': True,
            'ungated_above_strike_pct': round(base_rate, 1), 'gates': out}


def main():
    print('=' * 96)
    print('EXPERIMENT 016 (H18): Trend Gate on Call Entry')
    print('Targets: AAPL, TMUS   Controls: KKR, DIS   Reference: TXN')
    print('=' * 96)

    results = {}
    for ticker in TARGETS + CONTROLS + list(REFERENCE):
        try:
            results[ticker] = run_ticker(ticker)
        except Exception as e:
            print(f'  {ticker} FAILED: {type(e).__name__}: {e}')
            results[ticker] = {'ticker': ticker, 'error': f'{type(e).__name__}: {e}'}

    googl = googl_stock_only()

    # ---- control check FIRST: a broken framework invalidates everything ----
    print('\n' + '=' * 96)
    print('CONTROL CHECK (must come first — a control that moves means the '
          'framework is wrong, not that we found something)')
    print('=' * 96)
    control_ok = {}
    for name, _, _ in GATES:
        drifts = {}
        for c in CONTROLS:
            r = results.get(c, {})
            if 'error' in r:
                continue
            g = next(x for x in r['gates'] if x['gate'] == name)
            drifts[c] = g['loss_delta']
        ok = all(abs(v) <= CONTROL_TOLERANCE for v in drifts.values())
        control_ok[name] = ok
        detail = '  '.join(f'{k} {v:+d}' for k, v in drifts.items())
        print(f'  {name:<20} {detail:<24} => {"OK" if ok else "FRAMEWORK-SUSPECT"}')

    # ---- target check ----
    print('\n' + '=' * 96)
    print('TARGET CHECK')
    print('=' * 96)
    verdicts = {}
    for name, _, _ in GATES:
        hits = []
        for t in TARGETS:
            r = results.get(t, {})
            if 'error' in r:
                continue
            g = next(x for x in r['gates'] if x['gate'] == name)
            qualifies = (g['relative_reduction_pct'] >= MIN_RELATIVE_REDUCTION
                         and g['skip_pct'] <= MAX_SKIP_PCT
                         and g['pnl_given_up'] <= max(g['winners_fair_share'], 0))
            hits.append((t, g, qualifies))
        n_ok = sum(1 for _, _, q in hits if q)
        passed = n_ok >= 2 and control_ok[name]
        verdicts[name] = {'targets_qualifying': n_ok, 'controls_ok': control_ok[name],
                          'pass': passed}
        detail = '  '.join(
            f'{t} {g["relative_reduction_pct"]:+.0f}%/skip{g["skip_pct"]:.0f}%'
            f'{"*" if q else ""}' for t, g, q in hits)
        print(f'  {name:<20} {detail:<44} '
              f'targets {n_ok}/2  controls {"OK" if control_ok[name] else "BAD"}  '
              f'=> {"PASS" if passed else "FAIL"}')

    overall = any(v['pass'] for v in verdicts.values())
    print('\n' + '=' * 96)
    print(f'H18 VERDICT: {"PASS" if overall else "FAIL"}')
    print('=' * 96)

    out = os.path.join(os.path.dirname(__file__), 'results.json')
    with open(out, 'w') as f:
        json.dump({'results': results, 'googl_directional': googl,
                   'control_ok': control_ok, 'verdicts': verdicts,
                   'overall_pass': overall, 'gates': GATES,
                   'train_frac': TRAIN_FRAC}, f, indent=2, default=str)
    print(f'\nResults saved to {out}')


if __name__ == '__main__':
    main()
