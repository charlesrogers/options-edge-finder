"""
Experiment 019b — Backwardation Guard (H22 pending / H22a testable).

Pre-registration: experiments/019b_backwardation_guard/README.md (committed first).

Engine: experiments/cc_sim.py. The guard is expressed as a cc_sim entry gate
(experiments/lib_phase3.py) and ANDed with the production IV-rank gate, so the two
arms differ in exactly one thing.

H22 proper needs 2020/2022 option prices that were not purchased — recorded PENDING.
H22a is the arm the data we already own can decide: the owned window
(2025-03-21 -> 2026-03-20) contains 24 VIX-backwardation days, clustered in the
April-2025 selloff.

Arms:
  A. baseline                 — IV-rank >= 50
  B. guard                    — IV-rank >= 50 AND NOT (VIX>VIX3M OR spot < 85% of 60d high)
  C. guard, backwardation leg only   (diagnostic, not a pre-registered clause)
  D. guard, drawdown leg only        (diagnostic, not a pre-registered clause)

A gate never alters a trade it allows, so a paired per-entry comparison between arms
is identically zero and tells you nothing. The diagnostic that does answer the
question is what the gate THREW AWAY: the count and mean P&L of the baseline entries
each arm no longer takes.
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

TICKERS = ['AAPL', 'DIS', 'TMUS', 'KKR']
CONTRACTS = 100                # 10,000 shares at 100% overwrite — production default
DRAWDOWN_PCT = 0.15            # arbitrary starting value (spec)
HIGH_LOOKBACK = 60             # arbitrary starting value (spec)
CALM_YEARS = [2021, 2023]
MIN_ENTRY_GAP = 25             # production re-entry cadence, for the calm control only


def dollars(trades):
    """Net call P&L in dollars at CONTRACTS contracts."""
    return sum(t.pnl_per_share for t in trades) * 100 * CONTRACTS


def arm_summary(trades, diag):
    s = cc_sim.score(trades)
    return {
        'n_trades': s['n_trades'],
        'entries': diag['entries'],
        'net_pnl': round(dollars(trades), 2),
        'gross_premium': round(s['gross_premium'] * CONTRACTS, 2),
        'buyback_cost': round(s['total_buyback'] * CONTRACTS, 2),
        'retention_pct': s['retention_pct'],
        'assignments': s['assignments'],
        'early_assignments': s['early_assignments'],
        'expiry_assignments': s['expiry_assignments'],
        'loss_rate_pct': s['loss_rate'],
        'worst_trade': round(s['worst_trade'] * CONTRACTS, 2),
        'missing_price_pct': diag['missing_price_pct'],
        'never_repriced_trades': diag['never_repriced_trades'],
    }


class _StockOnlyChain:
    """The gate only reads `.stock`; the calm control has no option data to give it."""
    def __init__(self, stock):
        self.stock = stock


def calm_control(ticker, vix, years):
    """
    Clause 4: on backwardation-free years, does the guard change anything?

    Uses the production re-entry cadence on stock data, then asks how many of
    THOSE entry dates the guard blocks. Counting blocked retries instead would
    inflate the denominator during long blocked stretches and make tickers
    incomparable. Loads its own long stock history — cc_sim's 5-year window
    starts in 2021-08 and would score a two-thirds-truncated 2021.
    """
    guard = P3.backwardation_gate(vix, DRAWDOWN_PCT, HIGH_LOOKBACK)
    stock = P3.load_long_stock(ticker, '2019-01-01', '2026-08-16')
    shim = _StockOnlyChain(stock)
    out = {}
    for year in years:
        dates = [d for d in stock.index if d.year == year]
        entry_dates, last = [], None
        for d in dates:
            if last is None or (d - last).days >= MIN_ENTRY_GAP:
                entry_dates.append(d)
                last = d
        blocked_back = blocked_dd = 0
        for d in entry_dates:
            ok, why = guard(shim, d, None)
            if not ok:
                if why == 'backwardation':
                    blocked_back += 1
                else:
                    blocked_dd += 1
        total = len(entry_dates)
        out[year] = {
            'entry_opportunities': total,
            'blocked_backwardation': blocked_back,
            'blocked_drawdown': blocked_dd,
            'blocked_pct': round((blocked_back + blocked_dd) / total * 100, 2) if total else 0.0,
        }
    return out


def main():
    print("=" * 88)
    print("EXPERIMENT 019b — Backwardation Guard (H22 pending / H22a)")
    print(f"Guard: VIX > VIX3M  OR  spot < {(1 - DRAWDOWN_PCT):.0%} x {HIGH_LOOKBACK}-day high")
    print("Both thresholds are ARBITRARY STARTING VALUES from the spec, not derived.")
    print("Engine = cc_sim; guard applied as an entry gate ANDed with the IV-rank gate.")
    print("=" * 88)

    vix = P3.load_vix_term_structure()
    back_days = int((vix['VIX'] > vix['VIX3M']).sum())
    print(f"VIX term structure: {len(vix)} days 2019-2026, {back_days} in backwardation")

    results = {
        'guard': {'drawdown_pct': DRAWDOWN_PCT, 'high_lookback': HIGH_LOOKBACK,
                  'note': 'arbitrary starting values from the spec'},
        'engine': 'experiments/cc_sim.py',
        'contracts': CONTRACTS,
        'vix_days': len(vix), 'vix_backwardation_days': back_days,
        'tickers': {}, 'calm_control': {},
    }

    agg = {a: 0.0 for a in ('baseline', 'guard', 'guard_backwardation_only', 'guard_drawdown_only')}
    agg_entries = {a: 0 for a in agg}
    agg_assign = {a: 0 for a in agg}

    for ticker in TICKERS:
        print(f"\n[{ticker}] loading")
        chain_data = cc_sim.load_ticker(ticker)
        s = TICKER_STRATEGIES[ticker]
        cfg = {'otm_pct': s['otm_pct'], 'min_dte': s['min_dte'], 'max_dte': s['max_dte']}
        iv = cc_sim.iv_rank_gate(DEFAULT_IV_THRESHOLD)

        gates = {
            'baseline': iv,
            'guard': P3.and_gates(iv, P3.backwardation_gate(vix, DRAWDOWN_PCT, HIGH_LOOKBACK)),
            'guard_backwardation_only': P3.and_gates(
                iv, P3.backwardation_gate(vix, DRAWDOWN_PCT, HIGH_LOOKBACK, use_drawdown=False)),
            'guard_drawdown_only': P3.and_gates(
                iv, P3.backwardation_gate(vix, DRAWDOWN_PCT, HIGH_LOOKBACK, use_backwardation=False)),
        }

        arms, arm_trades = {}, {}
        for name, gate in gates.items():
            trades, diag = cc_sim.run(chain_data, cfg, cc_sim.baseline_policy, gate,
                                      progress_every=0, label=f'{ticker}/{name}')
            arm_trades[name] = trades
            arms[name] = arm_summary(trades, diag)
            print(f"[{ticker}] {name:26s} {diag['entries']:4d} entries  "
                  f"net ${arms[name]['net_pnl']:+12,.0f}  "
                  f"retention {arms[name]['retention_pct']:>6}%  "
                  f"assignments {arms[name]['assignments']}")

        b = arms['baseline']
        entry = {'coverage': f"{str(chain_data.option_days[0])[:10]} -> "
                             f"{str(chain_data.option_days[-1])[:10]}",
                 'otm_pct': cfg['otm_pct'], 'dte': [cfg['min_dte'], cfg['max_dte']],
                 'missing_price_pct': b['missing_price_pct']}
        for name, a in arms.items():
            entry[name] = a
            if name != 'baseline':
                entry[f'{name}_entries_skipped_pct'] = round(
                    (b['entries'] - a['entries']) / b['entries'] * 100, 2) if b['entries'] else None
                entry[f'{name}_pnl_delta_pct'] = round(
                    (a['net_pnl'] - b['net_pnl']) / abs(b['net_pnl']) * 100, 2) if b['net_pnl'] else None
                entry[f'{name}_blocked'] = P3.blocked_entry_stats(
                    arm_trades['baseline'], arm_trades[name], CONTRACTS)
            agg[name] += a['net_pnl']
            agg_entries[name] += a['entries']
            agg_assign[name] += a['assignments']

        for name in ('guard', 'guard_backwardation_only', 'guard_drawdown_only'):
            blk = entry[f'{name}_blocked']
            print(f"[{ticker}] {name:26s} skipped {entry[f'{name}_entries_skipped_pct']}% "
                  f"of entries, P&L delta {entry[f'{name}_pnl_delta_pct']}% | "
                  f"blocked {blk.get('n_blocked')} entries worth "
                  f"${blk.get('blocked_mean_pnl')} mean "
                  f"({blk.get('blocked_winners')}W/{blk.get('blocked_losers')}L)")
        print(f"[{ticker}] missing prices {b['missing_price_pct']}% of lookups, "
              f"{b['never_repriced_trades']} trades never repriced")

        results['tickers'][ticker] = entry
        results['calm_control'][ticker] = calm_control(ticker, vix, CALM_YEARS)

    # ---------- H22a scoring ----------
    skipped_pct = (agg_entries['baseline'] - agg_entries['guard']) / agg_entries['baseline'] * 100
    pnl_delta = (agg['guard'] - agg['baseline']) / abs(agg['baseline']) * 100
    calm_max = max(v['blocked_pct'] for t in results['calm_control'].values()
                   for v in t.values())

    ex_kkr = {a: sum(results['tickers'][t][a]['net_pnl'] for t in TICKERS if t != 'KKR')
              for a in agg}
    results['aggregate'] = {a: round(v, 2) for a, v in agg.items()}
    results['aggregate_ex_kkr'] = {a: round(v, 2) for a, v in ex_kkr.items()}
    for a in ('guard', 'guard_backwardation_only', 'guard_drawdown_only'):
        results['aggregate_ex_kkr'][f'{a}_delta_pct'] = round(
            (ex_kkr[a] - ex_kkr['baseline']) / abs(ex_kkr['baseline']) * 100, 2)

    clauses = {
        'c1_entries_skipped_le_15pct': {'value': round(skipped_pct, 2), 'threshold': 15,
                                        'pass': skipped_pct <= 15},
        'c2_aggregate_pnl_ge_plus10pct': {'value': round(pnl_delta, 2), 'threshold': 10,
                                          'pass': pnl_delta >= 10},
        'c3_no_new_assignments': {'value': agg_assign['guard'],
                                  'threshold': agg_assign['baseline'],
                                  'pass': agg_assign['guard'] <= agg_assign['baseline']},
        'c4_calm_control_le_5pct': {'value': round(calm_max, 2), 'threshold': 5,
                                    'pass': calm_max <= 5},
    }
    all_pass = all(c['pass'] for c in clauses.values())
    marginal = (clauses['c1_entries_skipped_le_15pct']['pass']
                and clauses['c3_no_new_assignments']['pass']
                and clauses['c4_calm_control_le_5pct']['pass'] and abs(pnl_delta) < 10)
    verdict = 'PASS' if all_pass else ('MARGINAL' if marginal else 'FAIL')

    results['clauses'] = clauses
    results['verdict_H22a'] = verdict
    results['verdict_H22'] = 'PENDING — needs 2020/2022 option prices (Part A not purchased)'

    print("\n" + "=" * 88)
    print("H22a SCORING (thresholds fixed in README before this ran)")
    print("=" * 88)
    print(f"  baseline aggregate net P&L : ${agg['baseline']:+,.0f}")
    print(f"  guard    aggregate net P&L : ${agg['guard']:+,.0f}")
    for name, c in clauses.items():
        print(f"  {'PASS' if c['pass'] else 'FAIL'}  {name}: {c['value']} "
              f"(threshold {c['threshold']})")
    print(f"\n  VERDICT H22a: {verdict}")
    print(f"  VERDICT H22 : {results['verdict_H22']}")

    print("\nLEG SPLIT (diagnostic, aggregate excluding KKR — 60%+ missing prices)")
    ek = results['aggregate_ex_kkr']
    print(f"  baseline ${ek['baseline']:+,.0f}")
    print(f"  full guard          ${ek['guard']:+,.0f} ({ek['guard_delta_pct']:+.1f}%)")
    print(f"  backwardation only  ${ek['guard_backwardation_only']:+,.0f} "
          f"({ek['guard_backwardation_only_delta_pct']:+.1f}%)")
    print(f"  drawdown only       ${ek['guard_drawdown_only']:+,.0f} "
          f"({ek['guard_drawdown_only_delta_pct']:+.1f}%)")
    print(f"  NOTE: totals span every daily cohort x {CONTRACTS} contracts — overlapping "
          f"positions, not a tradeable P&L. Read the relative deltas and the blocked-entry diagnostics.")

    print("\nCALM CONTROL (entry opportunities blocked, stock data only)")
    for ticker, years in results['calm_control'].items():
        for year, v in years.items():
            print(f"  {ticker} {year}: {v['blocked_pct']}% blocked "
                  f"({v['blocked_backwardation']} backwardation, {v['blocked_drawdown']} drawdown "
                  f"of {v['entry_opportunities']} opportunities)")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results.json')
    with open(out, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    main()
