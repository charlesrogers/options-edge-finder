"""
Experiment 021 — Capacity Expansion (H24).

Pre-registration: experiments/021_capacity_expansion/README.md (committed first).

Clause (a) — GOOGL on a real option year — is NOT run: we own 5 trading days of GOOGL
option data and no credits were spent to buy the year. The spec's pre-authorised fallback
is taken and reported explicitly rather than skipped silently.

Clause (b) — MSFT and AMZN at 15% OTM / 20-45 DTE — is run in full. The hypothesis
specifies STOCK-DATA walk-forward, which is free, so this is the complete test, not a
degraded substitute. It reuses experiments/014_validated_param_update/run.py::simulate_at_otm
verbatim so MSFT/AMZN face exactly the yardstick that qualified the deployed tickers.

Also computes the KKR liquidity cap from owned Databento contract volume.
"""

import os
import sys
import json
import importlib.util

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import numpy as np
import pandas as pd

import cc_sim
import lib_phase3 as P3
from ticker_strategies import TICKER_STRATEGIES

# Import Exp 014's scorer by path — its package directory starts with a digit.
_EXP014 = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                       '014_validated_param_update', 'run.py')
_spec = importlib.util.spec_from_file_location('exp014', _EXP014)
exp014 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(exp014)
simulate_at_otm = exp014.simulate_at_otm

CANDIDATES = {'MSFT': 0.15, 'AMZN': 0.15}          # clause (b)
CONTROLS = {'AAPL': 0.15, 'DIS': 0.07}             # already deployed and validated
PRIMARY_START, PRIMARY_END = '2024-08-16', '2026-08-16'   # the gating 2-year window
SECONDARY_START, SECONDARY_END = '2019-01-01', '2026-08-16'
LOSS_RATE_GATE = 10.0                              # H24(b), immutable
KKR_VOLUME_SHARE_CAP = 0.20                        # spec's arbitrary starting value


def walk_forward(ticker, otm_pct, start, end, label):
    """Exp 014's walk-forward: train first 67%, test last 33%, gate on the test window."""
    hist = P3.load_long_stock(ticker, start, end).to_frame(name='Close')
    n = len(hist)
    split = int(n * 0.67)
    train = simulate_at_otm(hist, otm_pct, start_idx=0, end_idx=split)
    test = simulate_at_otm(hist, otm_pct, start_idx=split, end_idx=n)
    row = {
        'ticker': ticker, 'otm_pct': otm_pct, 'window': label,
        'range': [str(hist.index[0])[:10], str(hist.index[-1])[:10]],
        'n_days': n,
        'train_trades': train['total'], 'train_loss_rate': train['loss_rate'],
        'test_trades': test['total'], 'test_loss_rate': test['loss_rate'],
        'test_wins': test['wins'], 'test_losses': test['losses'],
    }
    print(f"  {ticker:5s} {otm_pct:.0%} OTM [{label}] "
          f"train {train['wins']}W/{train['losses']}L ({train['loss_rate']:.1f}%) | "
          f"test {test['wins']}W/{test['losses']}L ({test['loss_rate']:.1f}%)")
    return row


def kkr_liquidity_cap():
    """
    Average daily contract volume in the strikes the strategy actually sells, from the
    KKR option OHLCV we own. Cap = 20% of that (spec's arbitrary starting value).
    """
    print("\n[KKR] computing liquidity cap from owned Databento volume")
    # Legacy window pinned: this experiment ran before the 2020/2022 purchase;
    # without it the loader would now concatenate stress data into its inputs.
    chain = cc_sim.load_ticker('KKR', *cc_sim.WINDOW_LEGACY_PRE_STRESS)
    strat = TICKER_STRATEGIES['KKR']

    volumes, days_with_contract, days_missing = [], 0, 0
    for i, date in enumerate(chain.option_days):
        spot = chain.spot(date)
        if spot is None:
            days_missing += 1
            continue
        call = cc_sim.find_call(chain, date, spot, strat['otm_pct'],
                                strat['min_dte'], strat['max_dte'])
        if call is None:
            days_missing += 1
            continue
        day = chain.by_date[date]
        vol = float(day.loc[day['symbol'] == call['symbol'], 'volume'].sum())
        volumes.append(vol)
        days_with_contract += 1
        if (i + 1) % 150 == 0:
            print(f"    {i + 1} days scanned, {days_with_contract} with a sellable contract")

    arr = np.array(volumes) if volumes else np.array([0.0])
    mean_v, median_v = float(arr.mean()), float(np.median(arr))
    p25, p75 = float(np.percentile(arr, 25)), float(np.percentile(arr, 75))
    cap_median = int(np.floor(median_v * KKR_VOLUME_SHARE_CAP))
    cap_mean = int(np.floor(mean_v * KKR_VOLUME_SHARE_CAP))

    print(f"[KKR] {days_with_contract} days with a sellable 15% OTM 20-45 DTE contract, "
          f"{days_missing} without")
    print(f"[KKR] volume in that strike: mean {mean_v:.1f}/day, median {median_v:.1f}/day, "
          f"p25 {p25:.1f}, p75 {p75:.1f}, zero-volume days {int((arr == 0).sum())}")
    print(f"[KKR] cap at {KKR_VOLUME_SHARE_CAP:.0%} of volume:")
    print(f"        median basis -> {cap_median} contracts ({cap_median * 100:,} shares)")
    print(f"        mean basis   -> {cap_mean} contracts ({cap_mean * 100:,} shares)  "
          f"[generous: the mean is skewed by a few heavy days]")
    print(f"[KKR] even the generous reading caps KKR at "
          f"{cap_mean * 100 / 10000:.0%} of a 10,000-share position.")
    return {
        'coverage': f"{str(chain.option_days[0])[:10]} -> {str(chain.option_days[-1])[:10]}",
        'days_scanned': len(chain.option_days),
        'days_with_sellable_contract': days_with_contract,
        'days_without': days_missing,
        'mean_daily_contract_volume': round(mean_v, 2),
        'median_daily_contract_volume': round(median_v, 2),
        'p25_daily_contract_volume': round(p25, 2),
        'p75_daily_contract_volume': round(p75, 2),
        'zero_volume_days': int((arr == 0).sum()),
        'volume_share_cap': KKR_VOLUME_SHARE_CAP,
        'cap_contracts_median_basis': cap_median,
        'cap_shares_median_basis': cap_median * 100,
        'cap_contracts_mean_basis': cap_mean,
        'cap_shares_mean_basis': cap_mean * 100,
        'recommended_cap_contracts': cap_mean,
        'note': ('Derivation: for every trading day we own, find the exact contract the '
                 'production rule would sell (15% OTM, 20-45 DTE), take its total daily '
                 'volume, then cap at 20% of that (the spec\'s arbitrary starting share). '
                 'Median and mean disagree by 12x because volume is spiky, so both are '
                 'reported. The mean basis is the generous reading and is the one deployed.'),
    }


def main():
    print("=" * 84)
    print("EXPERIMENT 021 — Capacity Expansion (H24)")
    print("=" * 84)

    results = {'clause_a_googl': {}, 'clause_b': {}, 'controls': {}, 'kkr_capacity': {}}

    # ---------- clause (a) ----------
    print("\nCLAUSE (a) — GOOGL on real option prices")
    try:
        gcalls = cc_sim.load_calls('GOOGL')
        gdays = sorted(gcalls['date'].unique())
        days = len(gdays)
        coverage = f"{str(gdays[0])[:10]} -> {str(gdays[-1])[:10]}"
    except (FileNotFoundError, IndexError):
        days, coverage = 0, 'none'
    print(f"  GOOGL option data owned: {days} trading days ({coverage})")
    print(f"  cc_sim marks GOOGL unusable: {cc_sim.UNUSABLE_TICKERS.get('GOOGL')}")
    print("  NOT RUN — the GOOGL year is Databento purchase item #5 and no credits were spent.")
    print("  Fallback (pre-authorised by the spec): GOOGL stays on extended probation at its")
    print("  current 10% OTM / 20-45 DTE, stock-data validated only, upgraded from accrued")
    print("  daily chain captures at a 6-month review.")
    results['clause_a_googl'] = {
        'status': 'NOT RUN — blocked on unpurchased data',
        'option_days_owned': days, 'coverage': coverage,
        'minimum_useful': 'one full year of option OHLCV + definitions',
        'fallback': ('extend GOOGL probation, unchanged production setting, upgrade from '
                     'accrued chain captures at a 6-month review (~2027-02)'),
    }

    # ---------- clause (b) ----------
    print(f"\nCLAUSE (b) — MSFT / AMZN at 15% OTM, gate = test loss rate <= {LOSS_RATE_GATE}%")
    print(f"  primary (gating) window {PRIMARY_START} -> {PRIMARY_END}")
    rows = []
    for ticker, otm in CANDIDATES.items():
        rows.append(walk_forward(ticker, otm, PRIMARY_START, PRIMARY_END, 'primary_2y'))
    print(f"  secondary (reported, non-gating) window {SECONDARY_START} -> {SECONDARY_END}")
    secondary = [walk_forward(t, o, SECONDARY_START, SECONDARY_END, 'secondary_2019_2026')
                 for t, o in CANDIDATES.items()]

    print("\n  CONTROLS — deployed tickers through the identical harness")
    controls = [walk_forward(t, o, PRIMARY_START, PRIMARY_END, 'primary_2y')
                for t, o in CONTROLS.items()]

    for row in rows:
        row['passed'] = row['test_loss_rate'] <= LOSS_RATE_GATE
        row['verdict'] = 'PASS — qualifies for probation tier' if row['passed'] else 'FAIL — stays out'
    results['clause_b'] = {'primary': rows, 'secondary': secondary,
                           'gate': f'test loss rate <= {LOSS_RATE_GATE}%'}
    results['controls'] = controls

    print("\n  VERDICTS")
    for row in rows:
        print(f"    {row['ticker']}: test loss rate {row['test_loss_rate']:.1f}% "
              f"({row['test_losses']}L of {row['test_trades']}) -> {row['verdict']}")
        sec = next(s for s in secondary if s['ticker'] == row['ticker'])
        print(f"      2019-2026 context (non-gating): train {sec['train_loss_rate']:.1f}%, "
              f"test {sec['test_loss_rate']:.1f}%")

    # ---------- KKR capacity ----------
    results['kkr_capacity'] = kkr_liquidity_cap()

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results.json')
    with open(out, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    main()
