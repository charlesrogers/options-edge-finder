"""
Experiment 006: Covered Call Exit Timing Research

CONSTRAINT: Dad sells covered calls. Never wants to be called away.
This is empirical research, not a strategy backtest.

Studies A-F on TRAINING SET ONLY (AAPL Apr-Nov 2025 + KKR 2023-2024).
Validation and holdout sets sealed until thresholds are locked.
"""

import os
import sys
import re
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
import pandas as pd
import databento as db


def load_and_split():
    """Load data and apply train/validate/holdout split."""
    # Load AAPL
    aapl = db.DBNStore.from_file('data/databento/raw/AAPL_ohlcv_1d.dbn.zst').to_df()
    aapl = aapl.reset_index().drop_duplicates().set_index('ts_event')

    # Load DIS
    dis = db.DBNStore.from_file('data/databento/raw/DIS_ohlcv_1d.dbn.zst').to_df()
    dis = dis.reset_index().drop_duplicates().set_index('ts_event')

    # Load KKR (3 years)
    kkr_dfs = []
    for f in ['KKR_ohlcv_1d.dbn.zst', 'KKR_ohlcv_1d_yr2.dbn.zst', 'KKR_ohlcv_1d_yr3.dbn.zst']:
        path = f'data/databento/raw/{f}'
        if os.path.exists(path):
            d = db.DBNStore.from_file(path).to_df()
            kkr_dfs.append(d)
    kkr = pd.concat(kkr_dfs).reset_index().drop_duplicates().set_index('ts_event').sort_index()

    # Split dates
    # AAPL: Apr-Nov 2025 = train, Dec 2025-Mar 2026 = holdout
    aapl_train = aapl[(aapl.index >= '2025-04-01') & (aapl.index < '2025-12-01')]
    aapl_holdout = aapl[aapl.index >= '2025-12-01']

    # DIS: Apr-Nov 2025 = validate, Dec-Mar = holdout
    dis_validate = dis[(dis.index >= '2025-04-01') & (dis.index < '2025-12-01')]
    dis_holdout = dis[dis.index >= '2025-12-01']

    # KKR: 2023-2024 = train, Jan-Jun 2025 = validate, Jul-Dec 2025 = holdout
    kkr_train = kkr[kkr.index < '2025-01-01']
    kkr_validate = kkr[(kkr.index >= '2025-01-01') & (kkr.index < '2025-07-01')]
    kkr_holdout = kkr[kkr.index >= '2025-07-01']

    # Load stock data for spot prices
    import yfinance as yf
    aapl_stock = yf.download('AAPL', period='2y', progress=False)
    dis_stock = yf.download('DIS', period='2y', progress=False)
    kkr_stock = yf.download('KKR', period='5y', progress=False)
    for df in [aapl_stock, dis_stock, kkr_stock]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    train = {
        "AAPL": {"options": aapl_train, "stock": aapl_stock},
        "KKR": {"options": kkr_train, "stock": kkr_stock},
    }
    validate = {
        "DIS": {"options": dis_validate, "stock": dis_stock},
        "KKR_val": {"options": kkr_validate, "stock": kkr_stock},
    }
    holdout = {
        "AAPL_ho": {"options": aapl_holdout, "stock": aapl_stock},
        "DIS_ho": {"options": dis_holdout, "stock": dis_stock},
        "KKR_ho": {"options": kkr_holdout, "stock": kkr_stock},
    }

    return train, validate, holdout


def parse_call_symbol(sym):
    """Parse OCC call symbol → (expiration, strike)."""
    m = re.search(r'(\d{6})C(\d{8})', str(sym).strip())
    if m:
        try:
            exp = datetime.strptime('20' + m.group(1), '%Y%m%d')
            strike = float(m.group(2)) / 1000
            return exp, strike
        except:
            pass
    return None, None


def get_calls_with_metadata(option_df, stock_df):
    """
    Extract all call contracts with daily close, strike, DTE, moneyness.
    Returns DataFrame with one row per contract per day.
    """
    # Filter to calls
    calls = option_df[option_df['symbol'].str.match(r'.*\d{6}C\d+', na=False)].copy()
    if calls.empty:
        return pd.DataFrame()

    # Aggregate across exchanges
    calls_agg = calls.groupby([calls.index.normalize(), 'symbol']).agg(
        {'close': 'mean', 'volume': 'sum'}
    ).reset_index()
    calls_agg.columns = ['date', 'symbol', 'option_close', 'volume']

    # Parse symbols
    parsed = calls_agg['symbol'].apply(
        lambda s: pd.Series(parse_call_symbol(s), index=['expiration', 'strike'])
    )
    calls_agg = pd.concat([calls_agg, parsed], axis=1).dropna(subset=['expiration', 'strike'])

    # Add spot price
    stock_close = stock_df['Close'].copy()
    stock_close.index = stock_close.index.normalize()
    if stock_close.index.tz is None and calls_agg['date'].dt.tz is not None:
        calls_agg['date_naive'] = calls_agg['date'].dt.tz_localize(None)
    else:
        calls_agg['date_naive'] = calls_agg['date']

    calls_agg = calls_agg.merge(
        stock_close.reset_index().rename(columns={'Date': 'date_naive', 'Close': 'spot'}),
        on='date_naive', how='left'
    ).dropna(subset=['spot'])

    # Compute DTE and moneyness
    calls_agg['dte'] = (calls_agg['expiration'] - calls_agg['date_naive']).dt.days
    calls_agg['moneyness'] = calls_agg['spot'] / calls_agg['strike']  # >1 = ITM for calls
    calls_agg['itm'] = calls_agg['spot'] > calls_agg['strike']
    calls_agg['pct_from_strike'] = (calls_agg['strike'] - calls_agg['spot']) / calls_agg['spot'] * 100

    return calls_agg


def study_a_itm_probability(calls_df):
    """
    Study A: When stock is X% from strike with Y DTE, what's the probability of finishing ITM?
    """
    print("\n" + "=" * 60)
    print("STUDY A: ITM Probability by Moneyness + DTE")
    print("=" * 60)

    # For each call contract, check if it was ITM at expiration
    # Group by (moneyness bucket at observation, DTE bucket)
    # → what fraction ended up ITM?

    # We need to track each contract's final state
    contracts = calls_df.groupby('symbol').agg({
        'expiration': 'first',
        'strike': 'first',
    }).reset_index()

    # Get spot at expiration for each contract
    results = []
    for _, contract in contracts.iterrows():
        sym = contract['symbol']
        exp = contract['expiration']
        strike = contract['strike']

        # Get all daily observations for this contract
        daily = calls_df[calls_df['symbol'] == sym].sort_values('date')
        if daily.empty:
            continue

        # Get spot at or near expiration
        exp_data = daily[daily['date_naive'] >= exp - timedelta(days=1)]
        if exp_data.empty:
            # Use last available date
            final_spot = daily.iloc[-1]['spot']
        else:
            final_spot = exp_data.iloc[0]['spot']

        finished_itm = final_spot > strike

        # Record each observation point
        for _, obs in daily.iterrows():
            results.append({
                'pct_from_strike': obs['pct_from_strike'],
                'dte': obs['dte'],
                'finished_itm': finished_itm,
                'moneyness': obs['moneyness'],
            })

    if not results:
        print("  No data for Study A")
        return {}

    results_df = pd.DataFrame(results)

    # Bucket by distance-from-strike and DTE
    pct_bins = [-50, -10, -5, -3, -1, 0, 1, 3, 5, 10, 50]
    dte_bins = [0, 3, 7, 14, 30, 60, 120]

    results_df['pct_bin'] = pd.cut(results_df['pct_from_strike'], bins=pct_bins)
    results_df['dte_bin'] = pd.cut(results_df['dte'], bins=dte_bins)

    pivot = results_df.groupby(['pct_bin', 'dte_bin'])['finished_itm'].agg(['mean', 'count']).reset_index()
    pivot.columns = ['pct_from_strike', 'dte', 'prob_itm', 'n_obs']

    print("\n  P(finish ITM) by distance-from-strike × DTE:")
    print(f"  {'Distance':>15s} {'DTE':>12s} {'P(ITM)':>8s} {'n':>6s}")
    print("  " + "-" * 45)
    for _, row in pivot[pivot['n_obs'] >= 10].iterrows():
        print(f"  {str(row['pct_from_strike']):>15s} {str(row['dte']):>12s} "
              f"{row['prob_itm']:7.1%} {int(row['n_obs']):>6d}")

    # Key finding: at what % from strike does ITM probability exceed 50%?
    near_atm = results_df[abs(results_df['pct_from_strike']) < 3]
    if not near_atm.empty:
        p_itm_near = near_atm['finished_itm'].mean()
        print(f"\n  When stock is within 3% of strike: P(ITM) = {p_itm_near:.1%}")

    return {
        "pivot": pivot.to_dict('records'),
        "near_atm_prob": float(near_atm['finished_itm'].mean()) if not near_atm.empty else None,
    }


def study_b_take_profit(calls_df):
    """
    Study B: Optimal take-profit timing when things go RIGHT.
    Track how much premium decays over time for OTM calls.
    """
    print("\n" + "=" * 60)
    print("STUDY B: Optimal Take-Profit Timing")
    print("=" * 60)

    # For calls that stayed OTM throughout (winner scenario):
    # Track value as % of initial value over time
    contracts = calls_df.groupby('symbol').agg({
        'expiration': 'first', 'strike': 'first',
    }).reset_index()

    decay_curves = []
    for _, contract in contracts.iterrows():
        daily = calls_df[calls_df['symbol'] == contract['symbol']].sort_values('date')
        if len(daily) < 5:
            continue

        # Only OTM calls (stock below strike) at entry
        if daily.iloc[0]['spot'] >= contract['strike']:
            continue

        entry_price = daily.iloc[0]['option_close']
        if entry_price <= 0.05:
            continue

        # Track value as % of entry
        for _, obs in daily.iterrows():
            pct_of_entry = obs['option_close'] / entry_price * 100
            pct_captured = 100 - pct_of_entry  # how much premium has decayed
            decay_curves.append({
                'dte': obs['dte'],
                'pct_captured': pct_captured,
                'still_otm': obs['spot'] < contract['strike'],
            })

    if not decay_curves:
        print("  No data for Study B")
        return {}

    decay_df = pd.DataFrame(decay_curves)

    # Group by DTE bucket: what % of premium is captured?
    for dte_max in [30, 21, 14, 7, 5, 3, 1]:
        bucket = decay_df[decay_df['dte'] <= dte_max]
        if not bucket.empty:
            avg = bucket['pct_captured'].mean()
            otm_pct = bucket['still_otm'].mean() * 100
            print(f"  At {dte_max:2d} DTE: avg {avg:.0f}% captured, {otm_pct:.0f}% still OTM (n={len(bucket)})")

    # Key finding: at 50% captured, what's the expected additional gain from holding?
    at_50 = decay_df[(decay_df['pct_captured'] >= 45) & (decay_df['pct_captured'] <= 55)]
    if not at_50.empty:
        avg_dte_at_50 = at_50['dte'].mean()
        print(f"\n  When 50% captured: avg {avg_dte_at_50:.0f} DTE remaining")

    return {"decay_by_dte": decay_df.groupby('dte')['pct_captured'].mean().to_dict()}


def study_c_buyback_timing(calls_df):
    """
    Study C: When things go WRONG — optimal buy-back timing.
    For calls that went ITM: what happened if you bought back at various points?
    """
    print("\n" + "=" * 60)
    print("STUDY C: Optimal Buy-Back When Stock Approaches Strike")
    print("=" * 60)

    contracts = calls_df.groupby('symbol').agg({
        'expiration': 'first', 'strike': 'first',
    }).reset_index()

    buyback_scenarios = []
    for _, contract in contracts.iterrows():
        daily = calls_df[calls_df['symbol'] == contract['symbol']].sort_values('date')
        if len(daily) < 5:
            continue

        # Only calls that started OTM and eventually went ITM
        if daily.iloc[0]['spot'] >= contract['strike']:
            continue

        ever_itm = (daily['spot'] > contract['strike']).any()
        if not ever_itm:
            continue  # Never went ITM — no problem

        entry_price = daily.iloc[0]['option_close']
        if entry_price <= 0.05:
            continue

        # Track: at each observation, what would buyback cost vs what it cost at the end?
        final_price = daily.iloc[-1]['option_close']

        for _, obs in daily.iterrows():
            buyback_scenarios.append({
                'pct_from_strike': obs['pct_from_strike'],
                'dte': obs['dte'],
                'buyback_cost': obs['option_close'],
                'final_cost': final_price,
                'savings': final_price - obs['option_close'],  # positive = saved by buying early
                'entry_price': entry_price,
            })

    if not buyback_scenarios:
        print("  No ITM scenarios found in training data")
        return {}

    bb_df = pd.DataFrame(buyback_scenarios)

    # At what distance from strike does buying back start to save money?
    print("\n  When stock approaches strike, avg buyback savings vs waiting:")
    print(f"  {'Distance':>12s} {'Avg Savings':>12s} {'Avg Cost':>10s} {'n':>6s}")
    print("  " + "-" * 45)

    for lo, hi, label in [
        (5, 100, ">5% OTM"),
        (3, 5, "3-5% OTM"),
        (1, 3, "1-3% OTM"),
        (0, 1, "0-1% OTM"),
        (-1, 0, "0-1% ITM"),
        (-3, -1, "1-3% ITM"),
        (-5, -3, "3-5% ITM"),
        (-100, -5, ">5% ITM"),
    ]:
        bucket = bb_df[(bb_df['pct_from_strike'] >= lo) & (bb_df['pct_from_strike'] < hi)]
        if not bucket.empty:
            avg_savings = bucket['savings'].mean()
            avg_cost = bucket['buyback_cost'].mean()
            direction = "BUY NOW" if avg_savings > 0 else "wait"
            print(f"  {label:>12s} ${avg_savings:>10.2f} ${avg_cost:>8.2f} {len(bucket):>6d}  ← {direction}")

    return {"scenarios": len(bb_df)}


def study_e_gamma_danger(calls_df):
    """
    Study E: At what DTE does gamma become dangerous?
    Track: of calls that were OTM at X DTE, how many flipped to ITM by expiry?
    """
    print("\n" + "=" * 60)
    print("STUDY E: Gamma Danger Zone by DTE")
    print("=" * 60)

    contracts = calls_df.groupby('symbol').agg({
        'expiration': 'first', 'strike': 'first',
    }).reset_index()

    flip_data = []
    for _, contract in contracts.iterrows():
        daily = calls_df[calls_df['symbol'] == contract['symbol']].sort_values('date')
        if len(daily) < 3:
            continue

        # Check at each DTE: was it OTM? Did it end ITM?
        final_obs = daily.iloc[-1]
        finished_itm = final_obs['spot'] > contract['strike']

        for _, obs in daily.iterrows():
            was_otm = obs['spot'] < contract['strike']
            if was_otm:
                flip_data.append({
                    'dte': obs['dte'],
                    'pct_otm': obs['pct_from_strike'],
                    'flipped_to_itm': finished_itm,
                })

    if not flip_data:
        print("  No data")
        return {}

    flip_df = pd.DataFrame(flip_data)

    print("\n  P(OTM call flips to ITM by expiry) by DTE:")
    print(f"  {'DTE':>6s} {'P(flip)':>8s} {'n':>6s}")
    print("  " + "-" * 25)
    for dte_max in [30, 21, 14, 7, 5, 3, 1]:
        bucket = flip_df[flip_df['dte'] <= dte_max]
        if len(bucket) >= 10:
            p_flip = bucket['flipped_to_itm'].mean()
            print(f"  {dte_max:>5d}d {p_flip:>7.1%} {len(bucket):>6d}")

    # Break out by how far OTM
    print("\n  P(flip) by distance OTM × DTE:")
    for otm_label, otm_lo, otm_hi in [("1-3% OTM", 1, 3), ("3-5% OTM", 3, 5), ("5-10% OTM", 5, 10)]:
        subset = flip_df[(flip_df['pct_otm'] >= otm_lo) & (flip_df['pct_otm'] < otm_hi)]
        if not subset.empty:
            for dte_max in [14, 7, 3]:
                bucket = subset[subset['dte'] <= dte_max]
                if len(bucket) >= 5:
                    p = bucket['flipped_to_itm'].mean()
                    print(f"  {otm_label:>10s} + {dte_max:>2d}d DTE: P(flip)={p:.1%} (n={len(bucket)})")

    return {}


def main():
    print("=" * 70)
    print("EXPERIMENT 006: Covered Call Exit Timing Research")
    print("TRAINING SET ONLY — Holdout sealed")
    print("=" * 70)

    train, validate, holdout = load_and_split()

    # Combine training data
    all_train_calls = pd.DataFrame()
    for ticker, data in train.items():
        print(f"\n  Loading {ticker} training data...")
        calls = get_calls_with_metadata(data['options'], data['stock'])
        if not calls.empty:
            calls['ticker'] = ticker
            all_train_calls = pd.concat([all_train_calls, calls])
            print(f"    {len(calls):,} call observations, {calls['symbol'].nunique()} contracts")

    if all_train_calls.empty:
        print("No training data loaded.")
        return

    print(f"\nTotal training set: {len(all_train_calls):,} observations, "
          f"{all_train_calls['symbol'].nunique():,} unique contracts")

    # Run studies
    results = {}
    results['study_a'] = study_a_itm_probability(all_train_calls)
    results['study_b'] = study_b_take_profit(all_train_calls)
    results['study_c'] = study_c_buyback_timing(all_train_calls)
    results['study_e'] = study_e_gamma_danger(all_train_calls)

    # Study D (ex-dividend) requires dividend date data — note for now
    print("\n" + "=" * 60)
    print("STUDY D: Ex-Dividend (requires dividend date data)")
    print("=" * 60)
    print("  AAPL ex-div dates in 2025: ~Feb, May, Aug, Nov (quarterly)")
    print("  Need to cross-reference with option behavior around those dates.")
    print("  TODO: Fetch ex-div dates from Yahoo Finance and filter call data.")

    # Save results
    out = os.path.join(os.path.dirname(__file__), "results.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    main()
