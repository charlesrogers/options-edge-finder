"""
Experiment 020 — Partial Overwriting (H23).

Pre-registration: experiments/020_partial_overwriting/README.md (committed first).
Nothing here may change a threshold that README already fixed.

Engine: experiments/cc_sim.py (Phase 1's simulator — correct `as_of` clock, real
ex-dividend dates, simulated assignment, one independent cohort per trading day).
Phase 3 adds only the daily equity curve, in experiments/lib_phase3.py, because
"return per unit of worst drawdown" is undefined on a bare trade list.

What runs:
  * Real Databento option prices over the window we already own. No purchase.
  * Overwrite ratios {50%, 70%, 100%} of 10,000 shares per ticker, plus a
    0% (stock-only) reference row so the overlay's share of the drawdown is visible.
  * Walk-forward 67/33 split on entry date. The grid is fixed in advance, so the
    test period is a clean comparison of three pre-specified configurations.
  * 25 staggered sequential chains per ticker: cc_sim opens a cohort every day,
    but one account holding 100 shares can only run one call at a time, so each
    chain is a real portfolio path. Chains overlap and are NOT independent —
    reported as a spread, never as a significance test.

The stress-year clause of H23 is NOT tested: it needs 2020/2022 option prices that
were not purchased. H23 is a conjunction and therefore cannot be marked PASS.
"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import numpy as np
import pandas as pd

import cc_sim
import lib_phase3 as P3
from ticker_strategies import TICKER_STRATEGIES, DEFAULT_IV_THRESHOLD

SHARES = 10_000
RATIOS = [0.50, 0.70, 1.00]            # the H23 grid
RATIOS_REPORT = [0.00] + RATIOS        # 0% = stock only, reference row
N_CHAINS = 25
TICKERS = ['AAPL', 'DIS', 'TMUS', 'KKR']   # TXN is tier 'skip'; GOOGL/AMZN have no data


def cfg_for(ticker):
    s = TICKER_STRATEGIES[ticker]
    return {'otm_pct': s['otm_pct'], 'min_dte': s['min_dte'], 'max_dte': s['max_dte']}


def chains_for(chain_data, trades, window):
    """25 staggered sequential portfolio paths inside `window` = (start, end)."""
    start, end = window
    in_window = [t for t in trades if start <= pd.Timestamp(t.entry_date) <= end]
    return [P3.sequential_chain(in_window, i) for i in range(min(N_CHAINS, len(in_window)))]


def summarise(chain_data, paths, window, ratio):
    """Median-across-paths summary for one overwrite ratio."""
    contracts = int(round(SHARES / 100 * ratio))
    rows = []
    for path in paths:
        eq = P3.equity_curve(chain_data, path, SHARES, contracts,
                             start_date=window[0], end_date=window[1])
        st = P3.curve_stats(eq, path, SHARES, contracts)
        if st:
            rows.append(st)
    if not rows:
        return None
    return {
        'ratio': ratio, 'contracts': contracts, 'n_paths': len(rows),
        'total_trades': sum(r['n_trades'] for r in rows),
        'median_return_over_dd': P3.median_of(rows, 'return_over_drawdown'),
        'median_total_return_pct': P3.median_of(rows, 'total_return_pct'),
        'median_max_dd_pct': P3.median_of(rows, 'max_drawdown_pct'),
        'median_net_income': P3.median_of(rows, 'net_income'),
        'median_gross_premium': P3.median_of(rows, 'gross_premium'),
        'median_buyback_cost': P3.median_of(rows, 'buyback_cost'),
        'median_retention_pct': P3.median_of(rows, 'retention_pct'),
        'median_loss_rate_pct': P3.median_of(rows, 'loss_rate_pct'),
        'median_worst_trade': P3.median_of(rows, 'worst_trade'),
        'total_assignments': sum(r['assignments'] for r in rows),
        'per_path_return_over_dd': [r['return_over_drawdown'] for r in rows],
    }


def beat_fraction(chain_data, paths, window, ratio, baseline_ratio=1.00):
    """Fraction of paths where `ratio` beats `baseline_ratio` on return/drawdown."""
    ca = int(round(SHARES / 100 * ratio))
    cb = int(round(SHARES / 100 * baseline_ratio))
    wins = n = 0
    for path in paths:
        ea = P3.equity_curve(chain_data, path, SHARES, ca, window[0], window[1])
        eb = P3.equity_curve(chain_data, path, SHARES, cb, window[0], window[1])
        sa, sb = P3.curve_stats(ea, path, SHARES, ca), P3.curve_stats(eb, path, SHARES, cb)
        if not sa or not sb or sa['return_over_drawdown'] is None or sb['return_over_drawdown'] is None:
            continue
        n += 1
        if sa['return_over_drawdown'] > sb['return_over_drawdown']:
            wins += 1
    return {'wins': wins, 'n': n, 'pct': round(wins / n * 100, 1) if n else None}


def main():
    print("=" * 88)
    print("EXPERIMENT 020 — Partial Overwriting (H23)")
    print(f"{SHARES:,} shares/ticker; ratios {[f'{r:.0%}' for r in RATIOS_REPORT]}; "
          f"{N_CHAINS} staggered sequential chains; engine = cc_sim")
    print("=" * 88)

    results = {'shares': SHARES, 'ratios': RATIOS, 'n_chains': N_CHAINS,
               'engine': 'experiments/cc_sim.py', 'tickers': {}, 'diagnostics': {},
               'iv_gate_control': {}}
    store = {}

    for ticker in TICKERS:
        print(f"\n[{ticker}] loading")
        chain_data = cc_sim.load_ticker(ticker)
        cfg = cfg_for(ticker)
        gate = cc_sim.iv_rank_gate(DEFAULT_IV_THRESHOLD)

        print(f"[{ticker}] production settings {cfg['otm_pct']:.0%} OTM "
              f"{cfg['min_dte']}-{cfg['max_dte']} DTE, IV-rank gate >= {DEFAULT_IV_THRESHOLD}")
        trades, diag = cc_sim.run(chain_data, cfg, cc_sim.baseline_policy, gate,
                                  progress_every=100, label=f'{ticker}/prod')
        print(f"[{ticker}] {diag['entries']} cohort entries of {diag['candidate_days']} days; "
              f"missing prices {diag['missing_price_pct']}%; "
              f"never-repriced trades {diag['never_repriced_trades']}; "
              f"skipped {diag['skipped']}")

        days = chain_data.option_days
        cut = days[int(len(days) * 0.67)]
        windows = {
            'full': (days[0], days[-1]),
            'train': (days[0], cut),
            'test': (cut, days[-1]),
        }
        print(f"[{ticker}] train {str(days[0])[:10]}..{str(cut)[:10]} | "
              f"test {str(cut)[:10]}..{str(days[-1])[:10]}")

        entry = {'otm_pct': cfg['otm_pct'], 'dte': [cfg['min_dte'], cfg['max_dte']],
                 'window': {k: [str(v[0])[:10], str(v[1])[:10]] for k, v in windows.items()}}
        paths_by_window = {}
        for wname, window in windows.items():
            paths = chains_for(chain_data, trades, window)
            paths_by_window[wname] = paths
            entry[wname] = {f"{r:.0%}": summarise(chain_data, paths, window, r)
                            for r in RATIOS_REPORT}
            print(f"[{ticker}] {wname}: {len(paths)} chains, "
                  f"{sum(len(p) for p in paths)} trades")

        entry['beat_100_test'] = {f"{r:.0%}": beat_fraction(
            chain_data, paths_by_window['test'], windows['test'], r) for r in RATIOS[:-1]}
        entry['beat_100_full'] = {f"{r:.0%}": beat_fraction(
            chain_data, paths_by_window['full'], windows['full'], r) for r in RATIOS[:-1]}
        results['tickers'][ticker] = entry
        results['diagnostics'][ticker] = diag
        store[ticker] = (chain_data, paths_by_window, windows)

        # DESCRIPTIVE CONTROL — not a hypothesis test, nothing deploys off it.
        # Exp 009 put the IV-rank >= 50 gate into production on the claim that it
        # triples P&L, measured on one un-staggered path. Same engine, gate on vs off.
        print(f"[{ticker}] IV-gate descriptive control (gate off)")
        ng_trades, ng_diag = cc_sim.run(chain_data, cfg, cc_sim.baseline_policy,
                                        cc_sim.no_gate(), progress_every=0,
                                        label=f'{ticker}/nogate')
        ng_paths = chains_for(chain_data, ng_trades, windows['full'])
        results['iv_gate_control'][ticker] = {
            'gate_on': entry['full']['100%'],
            'gate_off': summarise(chain_data, ng_paths, windows['full'], 1.00),
            'entries_on': diag['entries'], 'entries_off': ng_diag['entries'],
        }

    # ---------- portfolio ----------
    print("\n" + "=" * 88)
    print("PORTFOLIO (10,000 shares of each ticker)")
    print("=" * 88)
    results['portfolio'] = {}
    for label, subset in (('all', TICKERS), ('ex_kkr', [t for t in TICKERS if t != 'KKR'])):
        for wname in ('full', 'test'):
            key = f'{label}_{wname}'
            results['portfolio'][key] = {}
            base_curves = None
            for ratio in RATIOS_REPORT:
                contracts = int(round(SHARES / 100 * ratio))
                n = min(len(store[t][1][wname]) for t in subset)
                rows, per_path = [], []
                for i in range(n):
                    curves = []
                    income = 0.0
                    for t in subset:
                        cd, paths, wins = store[t]
                        path = paths[wname][i]
                        curves.append(P3.equity_curve(cd, path, SHARES, contracts,
                                                      wins[wname][0], wins[wname][1]))
                        income += sum(x.pnl_per_share for x in path) * 100 * contracts
                    eq = pd.concat(curves, axis=1).sort_index().ffill().dropna().sum(axis=1)
                    ret = (float(eq.iloc[-1]) - float(eq.iloc[0])) / float(eq.iloc[0]) * 100
                    dd = P3.drawdown_pct(eq)
                    rows.append({'total_return_pct': ret, 'max_drawdown_pct': dd,
                                 'return_over_drawdown': ret / dd if dd > 0 else None,
                                 'net_income': income})
                    per_path.append(ret / dd if dd > 0 else None)
                results['portfolio'][key][f"{ratio:.0%}"] = {
                    'median_return_over_dd': P3.median_of(rows, 'return_over_drawdown'),
                    'median_total_return_pct': P3.median_of(rows, 'total_return_pct'),
                    'median_max_dd_pct': P3.median_of(rows, 'max_drawdown_pct'),
                    'median_net_income': P3.median_of(rows, 'net_income'),
                    'per_path_return_over_dd': per_path,
                }
                if ratio == 1.00:
                    base_curves = per_path
                name = 'stock only' if ratio == 0 else f"{ratio:.0%}"
                r = results['portfolio'][key][f"{ratio:.0%}"]
                print(f"  {key:12s} {name:>10s}: return/DD {r['median_return_over_dd']}  "
                      f"return {r['median_total_return_pct']:+.2f}%  "
                      f"DD {r['median_max_dd_pct']:.2f}%  "
                      f"income ${r['median_net_income']:+,.0f}")
            for ratio in RATIOS[:-1]:
                a = results['portfolio'][key][f"{ratio:.0%}"]['per_path_return_over_dd']
                pairs = [(x, y) for x, y in zip(a, base_curves) if x is not None and y is not None]
                wins = sum(1 for x, y in pairs if x > y)
                results['portfolio'][key][f"{ratio:.0%}"]['beats_100'] = f"{wins}/{len(pairs)}"
                print(f"        {ratio:.0%} beats 100% in {wins}/{len(pairs)} chains")

    # ---------- per-ticker table ----------
    print("\n" + "=" * 88)
    print("WALK-FORWARD TEST PERIOD — median across chains")
    print("=" * 88)
    print(f"{'Ticker':>6s} {'Ratio':>6s} {'ret/DD':>9s} {'return%':>9s} {'maxDD%':>8s} "
          f"{'income$':>11s} {'buyback$':>11s} {'beats100':>9s} {'assign':>7s}")
    print("-" * 88)
    for ticker in TICKERS:
        for ratio in RATIOS_REPORT:
            s = results['tickers'][ticker]['test'][f"{ratio:.0%}"]
            if not s:
                continue
            b = results['tickers'][ticker]['beat_100_test'].get(f"{ratio:.0%}")
            bs = f"{b['wins']}/{b['n']}" if b else "—"
            print(f"{ticker:>6s} {ratio:>5.0%} {str(s['median_return_over_dd']):>9s} "
                  f"{s['median_total_return_pct']:>8.2f}% {s['median_max_dd_pct']:>7.2f}% "
                  f"{s['median_net_income']:>+11,.0f} {s['median_buyback_cost']:>11,.0f} "
                  f"{bs:>9s} {s['total_assignments']:>7d}")

    print("\n" + "=" * 88)
    print("IV-GATE DESCRIPTIVE CONTROL (not a hypothesis test — flagged for follow-up)")
    print("Median chain net income at 100% overwrite, full period, gate on vs off")
    print("=" * 88)
    for ticker in TICKERS:
        c = results['iv_gate_control'][ticker]
        print(f"  {ticker}: gate ON ${c['gate_on']['median_net_income']:+,.0f} "
              f"({c['entries_on']} cohort entries) | "
              f"gate OFF ${c['gate_off']['median_net_income']:+,.0f} "
              f"({c['entries_off']} cohort entries)")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results.json')
    with open(out, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    main()
