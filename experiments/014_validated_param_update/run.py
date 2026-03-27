"""
Experiment 014: Validated Parameter Update

Walk-forward validation of proposed parameter changes from Experiment 013.
Train on first 67%, test on last 33%. Only deploy if test loss rate < 15%.
"""

import os
import sys
import json
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
import pandas as pd
import yf_proxy


def simulate_at_otm(stock_hist, otm_pct, interval_days=7, start_idx=0, end_idx=None):
    """Simulate weekly covered calls at a given OTM%. Returns win/loss counts."""
    if end_idx is None:
        end_idx = len(stock_hist)

    wins = 0
    losses = 0
    trades = []
    last_entry = None

    for i in range(max(start_idx, 30), end_idx):
        date = stock_hist.index[i]
        if last_entry and (pd.Timestamp(date) - pd.Timestamp(last_entry)).days < interval_days:
            continue

        spot = float(stock_hist['Close'].iloc[i])
        strike = spot * (1 + otm_pct)
        dte = 32

        future_idx = min(i + dte, len(stock_hist) - 1)
        if future_idx >= end_idx:
            future_idx = min(future_idx, len(stock_hist) - 1)

        future_price = float(stock_hist['Close'].iloc[future_idx])

        won = future_price <= strike
        if won:
            wins += 1
        else:
            losses += 1

        trades.append({
            'date': str(date)[:10],
            'spot': round(spot, 2),
            'strike': round(strike, 2),
            'future_price': round(future_price, 2),
            'won': won,
        })
        last_entry = str(date)[:10]

    total = wins + losses
    return {
        'wins': wins,
        'losses': losses,
        'total': total,
        'win_rate': round(wins / total * 100, 1) if total > 0 else 0,
        'loss_rate': round(losses / total * 100, 1) if total > 0 else 0,
        'trades': trades,
    }


def run_walk_forward(ticker, proposed_otm, fallback_otm=None):
    """Run walk-forward validation for one ticker."""
    hist = yf_proxy.get_stock_history(ticker, period='1y')
    if hist.empty:
        return None

    n = len(hist)
    split = int(n * 0.67)

    start_price = float(hist['Close'].iloc[0])
    end_price = float(hist['Close'].iloc[-1])
    train_end_price = float(hist['Close'].iloc[split])

    print(f"\n{'=' * 60}")
    print(f"  {ticker}: proposed {proposed_otm*100:.0f}% OTM")
    print(f"  Price: ${start_price:.0f} → ${train_end_price:.0f} (train) → ${end_price:.0f} (test)")
    print(f"  Train: {str(hist.index[0])[:10]} to {str(hist.index[split])[:10]} ({split} days)")
    print(f"  Test:  {str(hist.index[split])[:10]} to {str(hist.index[-1])[:10]} ({n - split} days)")

    # Train period — for reference only (not used for parameter selection)
    train = simulate_at_otm(hist, proposed_otm, start_idx=0, end_idx=split)
    print(f"\n  TRAIN: {train['wins']}W / {train['losses']}L ({train['loss_rate']:.0f}% loss rate)")

    # TEST period — this is what matters
    test = simulate_at_otm(hist, proposed_otm, start_idx=split, end_idx=n)
    print(f"  TEST:  {test['wins']}W / {test['losses']}L ({test['loss_rate']:.0f}% loss rate)")

    passed = test['loss_rate'] < 15
    print(f"\n  VERDICT: {'PASS' if passed else 'FAIL'} — test loss rate {test['loss_rate']:.0f}% {'<' if passed else '>='} 15%")

    result = {
        'ticker': ticker,
        'proposed_otm': proposed_otm,
        'train_loss_rate': train['loss_rate'],
        'test_loss_rate': test['loss_rate'],
        'test_wins': test['wins'],
        'test_losses': test['losses'],
        'test_total': test['total'],
        'passed': passed,
    }

    # Fallback if failed
    if not passed and fallback_otm:
        print(f"\n  Trying fallback: {fallback_otm*100:.0f}% OTM...")
        fb_test = simulate_at_otm(hist, fallback_otm, start_idx=split, end_idx=n)
        fb_passed = fb_test['loss_rate'] < 15
        print(f"  FALLBACK TEST: {fb_test['wins']}W / {fb_test['losses']}L ({fb_test['loss_rate']:.0f}% loss rate)")
        print(f"  FALLBACK VERDICT: {'PASS' if fb_passed else 'FAIL'}")
        result['fallback_otm'] = fallback_otm
        result['fallback_loss_rate'] = fb_test['loss_rate']
        result['fallback_passed'] = fb_passed

    return result


def run_googl_skip_validation():
    """Validate that GOOGL should be skipped — test multiple OTM% on holdout."""
    hist = yf_proxy.get_stock_history('GOOGL', period='1y')
    if hist.empty:
        return None

    n = len(hist)
    split = int(n * 0.67)

    print(f"\n{'=' * 60}")
    print(f"  GOOGL: validating SKIP recommendation")
    print(f"  Test period: {str(hist.index[split])[:10]} to {str(hist.index[-1])[:10]}")

    results = {}
    for otm in [0.05, 0.10, 0.15, 0.20]:
        test = simulate_at_otm(hist, otm, start_idx=split, end_idx=n)
        results[otm] = test['loss_rate']
        print(f"  {otm*100:.0f}% OTM: {test['wins']}W / {test['losses']}L ({test['loss_rate']:.0f}% loss rate)")

    # SKIP confirmed if 10% OTM still has >25% loss rate on test
    skip_confirmed = results.get(0.10, 100) > 25
    print(f"\n  SKIP CONFIRMED: {'YES' if skip_confirmed else 'NO'} — 10% OTM loss rate {results.get(0.10, 0):.0f}% {'>' if skip_confirmed else '<='} 25%")

    return {
        'ticker': 'GOOGL',
        'action': 'skip',
        'otm_loss_rates': {f"{k*100:.0f}%": v for k, v in results.items()},
        'skip_confirmed': skip_confirmed,
    }


def main():
    print("=" * 60)
    print("EXPERIMENT 014: Validated Parameter Update")
    print("Walk-forward validation before deploying to production")
    print("=" * 60)

    results = []

    # H1: TMUS at 10% OTM
    r = run_walk_forward('TMUS', proposed_otm=0.10, fallback_otm=0.15)
    if r:
        results.append(r)

    # H2: KKR at 15% OTM
    r = run_walk_forward('KKR', proposed_otm=0.15, fallback_otm=0.20)
    if r:
        results.append(r)

    # H3: GOOGL skip validation
    r = run_googl_skip_validation()
    if r:
        results.append(r)

    # Also validate current parameters haven't degraded
    print(f"\n{'=' * 60}")
    print("CONTROL: Current parameters on test period")
    print("=" * 60)

    for ticker, otm in [('AAPL', 0.15), ('DIS', 0.07), ('AMZN', 0.05)]:
        r = run_walk_forward(ticker, proposed_otm=otm)
        if r:
            results.append(r)

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY — Deploy Gate")
    print("=" * 60)

    deployable = []
    for r in results:
        if 'passed' in r:
            status = 'PASS' if r['passed'] else 'FAIL'
            print(f"\n  {r['ticker']} {r.get('proposed_otm', 0)*100:.0f}% OTM: {status} (test loss rate: {r['test_loss_rate']:.0f}%)")
            if r['passed']:
                deployable.append(r)
            elif r.get('fallback_passed'):
                print(f"    Fallback {r['fallback_otm']*100:.0f}% OTM: PASS ({r['fallback_loss_rate']:.0f}% loss rate)")
                deployable.append({**r, 'proposed_otm': r['fallback_otm'], 'passed': True})
        elif 'skip_confirmed' in r:
            status = 'SKIP CONFIRMED' if r['skip_confirmed'] else 'SKIP NOT CONFIRMED'
            print(f"\n  {r['ticker']}: {status}")
            if r['skip_confirmed']:
                deployable.append(r)

    print(f"\n{'=' * 60}")
    print(f"DEPLOYABLE CHANGES: {len(deployable)}")
    for d in deployable:
        if d.get('action') == 'skip':
            print(f"  {d['ticker']}: SKIP (confirmed)")
        else:
            print(f"  {d['ticker']}: {d['proposed_otm']*100:.0f}% OTM (test loss rate: {d['test_loss_rate']:.0f}%)")
    print("=" * 60)

    # Save
    out = os.path.join(os.path.dirname(__file__), 'results.json')
    with open(out, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    main()
