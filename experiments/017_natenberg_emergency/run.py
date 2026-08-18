"""
Experiment 017 (H19): EMERGENCY Rational-Exercise Refinement — BACKTEST HALF.

Pre-registration: experiments/017_natenberg_emergency/README.md — frozen.

SHADOW MODE ONLY. Nothing here changes the live alert. The shadow logger lives
in monitor_positions.py; this script measures how often the current rule fires
historically, how often the refined rule would have stayed silent, and — the
only number that can kill the hypothesis — whether it would ever have been
silent on a call that was actually exercised.

Observation pass, not a trading pass: positions are held to expiry so that
every ITM + ex-div day is observed. A policy that closes on EMERGENCY would
destroy the very sample we are trying to count.

    python3 experiments/017_natenberg_emergency/run.py
"""

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd

import bsm
import cc_sim
from position_monitor import lookup_itm_probability, rational_exercise_emergency
from ticker_strategies import TICKER_STRATEGIES

TICKERS = ['AAPL', 'DIS', 'TMUS', 'KKR', 'TXN']
REFERENCE = {'TXN': {'otm_pct': 0.10, 'min_dte': 20, 'max_dte': 45}}

MIN_EVENTS_FOR_A_VERDICT = 20       # pre-registered
SUPPRESSION_TARGET = 50.0           # pre-registered, %
ASSIGNMENT_TABLE_CERTAINTY = 0.90   # pre-registered


def ticker_config(ticker):
    if ticker in REFERENCE:
        return dict(REFERENCE[ticker])
    s = TICKER_STRATEGIES[ticker]
    return {'otm_pct': s['otm_pct'], 'min_dte': s['min_dte'], 'max_dte': s['max_dte']}


def observe(chain, cfg):
    """Hold every cohort to expiry, recording both rules' verdicts each day."""
    events = []
    gate = cc_sim.iv_rank_gate(50)

    for entry_date in chain.option_days:
        spot0 = chain.spot(entry_date)
        if spot0 is None:
            continue
        ok, _ = gate(chain, entry_date, spot0)
        if not ok:
            continue
        call = cc_sim.find_call(chain, entry_date, spot0, cfg['otm_pct'],
                                cfg['min_dte'], cfg['max_dte'])
        if not call or call['price'] <= 0 or call['expiration'] > chain.option_days[-1]:
            continue

        symbol, strike, expiration = call['symbol'], call['strike'], call['expiration']
        last_price = call['price']
        exercised_on = None
        days = [d for d in chain.option_days if entry_date < d <= expiration]
        pending = []

        for date in days:
            spot = chain.spot(date)
            if spot is None:
                continue
            px = chain.price.get((symbol, date))
            stale = px is None
            if stale:
                px = last_price
            else:
                last_price = px

            dte = (expiration - date).days
            exdiv_date, div_amt = chain.next_exdiv(date)
            if exdiv_date is not None and exdiv_date > expiration:
                exdiv_date, div_amt = None, None
            days_to_exdiv = (exdiv_date - date).days if exdiv_date is not None else None

            is_itm = spot > strike
            current_fires = is_itm and days_to_exdiv is not None and days_to_exdiv <= 3
            if not current_fires:
                continue

            delta = bsm.delta_from_price(px, spot, strike, dte)
            refined_fires, reason = rational_exercise_emergency(
                strike=strike, current_stock=spot, current_option_ask=px,
                days_to_exdiv=days_to_exdiv, dividend_amount=div_amt, delta=delta)

            intrinsic = max(0.0, spot - strike)
            extrinsic = max(0.0, px - intrinsic)
            pct_from_strike = (strike - spot) / spot * 100

            pending.append({
                'ticker': chain.ticker, 'entry_date': str(entry_date)[:10],
                'date': str(date)[:10], 'symbol': symbol, 'strike': strike,
                'expiration': str(expiration)[:10], 'spot': round(spot, 2),
                'option_price': round(px, 4), 'price_is_stale': stale,
                'dte': dte, 'days_to_exdiv': days_to_exdiv,
                'exdiv_date': str(exdiv_date)[:10],
                'dividend': round(div_amt, 4) if div_amt is not None else None,
                'intrinsic': round(intrinsic, 4), 'extrinsic': round(extrinsic, 4),
                'delta': round(delta, 4) if delta is not None else None,
                'current_fires': True, 'refined_fires': refined_fires,
                'refined_reason': reason,
                'table_p_assignment': lookup_itm_probability(pct_from_strike, dte),
            })

            # Was it actually exercised at this ex-dividend?
            if days_to_exdiv <= 1 and div_amt is not None and extrinsic < div_amt:
                exercised_on = str(date)[:10]
                break

        # Did the call finish ITM if it survived to expiry?
        finished_itm = None
        if exercised_on is None and days:
            exp_spot = chain.spot(expiration)
            finished_itm = bool(exp_spot is not None and exp_spot > strike)

        for e in pending:
            e['exercised_early_on'] = exercised_on
            e['exercised_at_this_event'] = (exercised_on == e['date'])
            e['finished_itm'] = finished_itm
            events.append(e)

    return events


def analyse(events):
    n = len(events)
    if n == 0:
        return {'events': 0}

    suppressed = [e for e in events if not e['refined_fires']]
    agreed = [e for e in events if e['refined_fires']]

    # A miss is a suppression on a day the call was actually exercised, or a day
    # the empirical table put assignment at >= 90%. Both are pre-registered.
    missed_exercise = [e for e in suppressed if e['exercised_at_this_event']]
    missed_table = [e for e in suppressed
                    if e['table_p_assignment'] >= ASSIGNMENT_TABLE_CERTAINTY]
    misses = {id(e): e for e in missed_exercise + missed_table}.values()

    # Supporting statistic, fully independent of the exercise model.
    suppressed_finished_itm = [e for e in suppressed if e['finished_itm']]

    def reason_kind(e):
        return 'delta_too_low' if e['refined_reason'].startswith('delta') \
            else 'extrinsic_exceeds_dividend'

    return {
        'events': n,
        # Overlapping cohorts can hold the same contract on the same day, so
        # `events` overstates how many distinct market situations were seen.
        'distinct_situations': len({(e['ticker'], e['date'], e['symbol'])
                                    for e in events}),
        'positions': len({(e['ticker'], e['entry_date']) for e in events}),
        'suppressed': len(suppressed),
        'suppression_pct': round(len(suppressed) / n * 100, 1),
        'agreed_fire': len(agreed),
        'missed_actual_exercise': len(missed_exercise),
        'missed_table_ge_90pct': len(missed_table),
        'missed_total': len(list(misses)),
        'missed_distinct_situations': len({(e['ticker'], e['date'], e['symbol'])
                                           for e in missed_exercise + missed_table}),
        'suppressed_that_finished_itm': len(suppressed_finished_itm),
        'suppression_reasons': dict(Counter(reason_kind(e) for e in suppressed)),
        'miss_causes': dict(Counter(reason_kind(e)
                                    for e in missed_exercise + missed_table)),
        'delta_range_of_exercised_calls': (
            [round(min(e['delta'] for e in missed_exercise if e['delta'] is not None), 3),
             round(max(e['delta'] for e in missed_exercise if e['delta'] is not None), 3)]
            if any(e['delta'] is not None for e in missed_exercise) else None),
        'stale_price_events': sum(1 for e in events if e['price_is_stale']),
        'stale_price_among_suppressed': sum(1 for e in suppressed if e['price_is_stale']),
        'events_with_no_delta': sum(1 for e in events if e['delta'] is None),
    }


def counterfactual_sweep(events):
    """Re-score the SAME observed events under other delta/margin settings.

    Diagnosis only — H19 is decided on the pre-registered (0.95, 1.5) pair
    alone, and this sweep is NOT a re-grid looking for a passing setting. It
    exists to answer one question: is zero misses reachable by tuning at all?
    Printed and persisted so the claim in results/017 can be regenerated rather
    than taken on trust.
    """
    rows = []
    for delta_thresh in (0.95, 0.90, 0.85, 0.80, 0.0):
        for margin in (1.5, 2.0, 3.0):
            suppressed = []
            for e in events:
                # Must replicate the real rule's FAIL-SAFE, or the sweep quietly
                # counts missing-data events as suppressions and reports both a
                # higher suppression rate and more misses than the rule can
                # actually produce. The (0.95, 1.5) row is asserted below to
                # reproduce the headline numbers exactly.
                if (e['option_price'] is None or e['dividend'] is None
                        or e['delta'] is None):
                    fires = True                       # fail-safe
                else:
                    fires = (e['delta'] >= delta_thresh
                             and e['extrinsic'] < e['dividend'] * margin)
                if not fires:
                    suppressed.append(e)
            misses = [e for e in suppressed
                      if e['exercised_at_this_event']
                      or e['table_p_assignment'] >= ASSIGNMENT_TABLE_CERTAINTY]
            rows.append({
                'delta_threshold': delta_thresh, 'safety_margin': margin,
                'suppressed': len(suppressed),
                'suppression_pct': round(len(suppressed) / len(events) * 100, 1)
                                   if events else 0.0,
                'misses': len(misses),
            })
    return rows


def main():
    print('=' * 92)
    print('EXPERIMENT 017 (H19): EMERGENCY Rational-Exercise Refinement')
    print('SHADOW MODE ONLY — this changes nothing in production.')
    print('=' * 92)
    print('\nData caveat: Supabase chain capture was dead 2026-03-30 -> 2026-08-15,')
    print('so the live snapshot history has a 4.5-month hole and cannot be used as')
    print('a second source. Only the Databento window below is usable.\n')

    all_events = []
    per_ticker = {}
    for ticker in TICKERS:
        try:
            chain = cc_sim.load_ticker(ticker, *cc_sim.WINDOW_LEGACY_PRE_STRESS)
        except Exception as e:
            print(f'  {ticker}: SKIP ({type(e).__name__}: {e})')
            continue
        cfg = ticker_config(ticker)
        events = observe(chain, cfg)
        stats = analyse(events)
        per_ticker[ticker] = stats
        all_events.extend(events)
        print(f'  {ticker}: {stats.get("events", 0)} ITM+ex-div<=3d observation days '
              f'across {stats.get("positions", 0)} positions, '
              f'{stats.get("suppressed", 0)} suppressed, '
              f'{stats.get("missed_total", 0)} misses', flush=True)

    combined = analyse(all_events)

    print('\n' + '=' * 92)
    print('COMBINED BACKTEST')
    print('=' * 92)
    for k, v in combined.items():
        print(f'  {k:<32} {v}')

    print('\n' + '=' * 92)
    print('VERDICT')
    print('=' * 92)

    n = combined.get('events', 0)
    if n < MIN_EVENTS_FOR_A_VERDICT:
        verdict = 'UNDERPOWERED'
        print(f'  {n} historical ITM + ex-div<=3d events < the pre-registered floor '
              f'of {MIN_EVENTS_FOR_A_VERDICT}.')
        print('  No verdict may be declared from the backtest. H19 stays in testing;')
        print('  the burden falls entirely on shadow mode.')
    elif combined['missed_total'] > 0:
        verdict = 'FAIL'
        print(f'  {combined["missed_total"]} missed true-assignment scenario(s). '
              f'One miss kills the hypothesis regardless of the false-positive win.')
    elif combined['suppression_pct'] < SUPPRESSION_TARGET:
        verdict = 'FAIL'
        print(f'  Zero misses, but only {combined["suppression_pct"]}% suppressed '
              f'(needs >= {SUPPRESSION_TARGET}%).')
    else:
        verdict = 'BACKTEST_PASS_PENDING_SHADOW'
        print(f'  Zero misses and {combined["suppression_pct"]}% suppressed on the '
              f'backtest.')
        print('  This is NOT a pass. The pre-registration requires >= 2 weeks of '
              'shadow logging')
        print('  AND explicit sign-off from Charles before any production change.')

    sweep = counterfactual_sweep(all_events)
    # Self-consistency: the registered (0.95, 1.5) cell must reproduce the
    # headline numbers, or the sweep is measuring a different rule than the one
    # that produced the verdict.
    registered = next((r for r in sweep if r['delta_threshold'] == 0.95
                       and r['safety_margin'] == 1.5), None)
    if registered and combined.get('events'):
        ok = (registered['suppressed'] == combined['suppressed']
              and registered['misses'] == combined['missed_total'])
        print(f'\n  [sweep self-check] registered cell reproduces headline: '
              f'{"YES" if ok else "NO"} '
              f'(sweep {registered["suppressed"]}/{registered["misses"]} vs '
              f'headline {combined["suppressed"]}/{combined["missed_total"]})')

    print('\n' + '=' * 92)
    print('COUNTERFACTUAL SWEEP — is zero misses reachable by tuning at all?')
    print('(diagnosis only; the verdict above stands on the pre-registered pair)')
    print('=' * 92)
    print(f'  {"delta >=":>9} {"margin":>7} {"suppressed":>12} {"suppression%":>13} '
          f'{"misses":>8}')
    for r in sweep:
        print(f'  {r["delta_threshold"]:>9.2f} {r["safety_margin"]:>7.1f} '
              f'{r["suppressed"]:>12d} {r["suppression_pct"]:>12.1f}% '
              f'{r["misses"]:>8d}')
    if sweep and min(r['misses'] for r in sweep) > 0:
        print(f'\n  Minimum misses over the whole sweep: '
              f'{min(r["misses"] for r in sweep)}. Zero is not reachable — the '
              f'failure is structural, not a tuning problem.')

    print('\n  Partial circularity, stated plainly: the simulator\'s early-exercise')
    print('  trigger (extrinsic < dividend) and the refined rule share a term, so the')
    print('  "missed actual exercise" count mostly tests the delta and 1.5x margin')
    print('  conditions. The table-based >= 90% check and the finished-ITM statistic')
    print('  are independent of that trigger.')

    out = os.path.join(os.path.dirname(__file__), 'results.json')
    with open(out, 'w') as f:
        json.dump({'verdict': verdict, 'combined': combined,
                   'per_ticker': per_ticker, 'events': all_events,
                   'counterfactual_sweep': sweep,
                   'min_events_for_a_verdict': MIN_EVENTS_FOR_A_VERDICT,
                   'suppression_target_pct': SUPPRESSION_TARGET},
                  f, indent=2, default=str)
    print(f'\nResults saved to {out}')


if __name__ == '__main__':
    main()
