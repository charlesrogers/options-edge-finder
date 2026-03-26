"""
Experiment 011: Yahoo Finance Option Data Quality Test

Compare YF option prices against Databento ground truth on AAPL.
Gates whether we can use YF data for GOOGL/AMZN/MSFT backtesting.
"""

import os
import sys
import re
import json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
import pandas as pd
import databento as db
import yf_proxy


def load_databento_aapl():
    """Load AAPL Databento OHLCV and extract ATM call close prices by date."""
    raw_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'databento', 'raw')
    files = sorted([f for f in os.listdir(raw_dir) if f.startswith('AAPL_ohlcv') and f.endswith('.dbn.zst')])

    dfs = []
    for f in files:
        dfs.append(db.DBNStore.from_file(os.path.join(raw_dir, f)).to_df())
    option_df = pd.concat(dfs).reset_index().drop_duplicates().set_index('ts_event').sort_index()

    # Get stock prices
    import yfinance as yf
    stock = yf.download('AAPL', period='2y', progress=False)
    if isinstance(stock.columns, pd.MultiIndex):
        stock.columns = stock.columns.get_level_values(0)

    return option_df, stock


def extract_atm_calls(option_df, stock_df, sample_dates=20):
    """For N sample dates, find ATM call close prices from Databento."""
    stock_close = stock_df['Close']
    dates = sorted(option_df.index.normalize().unique())

    # Sample evenly across the date range
    step = max(1, len(dates) // sample_dates)
    sample = dates[::step][:sample_dates]

    records = []
    for date in sample:
        date_naive = pd.Timestamp(date).tz_localize(None)
        spot_match = stock_close[stock_close.index >= date_naive]
        if spot_match.empty:
            continue
        spot = float(spot_match.iloc[0])

        # Get ATM call from Databento
        date_ts = pd.Timestamp(date).normalize()
        if option_df.index.tz is not None and date_ts.tz is None:
            date_ts = date_ts.tz_localize(option_df.index.tz)

        day = option_df[option_df.index.normalize() == date_ts]
        if day.empty:
            continue

        agg = day.groupby('symbol').agg({'close': 'mean'}).reset_index()
        calls = agg[agg['symbol'].str.match(r'.*\d{6}C\d+', na=False)].copy()
        if calls.empty:
            continue

        # Parse strikes
        def parse(sym):
            m = re.search(r'(\d{6})C(\d{8})', str(sym).strip())
            if m:
                try:
                    exp = datetime.strptime('20' + m.group(1), '%Y%m%d')
                    strike = float(m.group(2)) / 1000
                    return exp, strike
                except:
                    pass
            return None, None

        parsed = calls['symbol'].apply(lambda s: pd.Series(parse(s), index=['exp', 'strike']))
        calls = pd.concat([calls, parsed], axis=1).dropna(subset=['exp', 'strike'])

        # Filter to 20-45 DTE
        calls['dte'] = (calls['exp'] - date_naive).dt.days
        calls = calls[(calls['dte'] >= 20) & (calls['dte'] <= 45)]
        if calls.empty:
            continue

        # Find ATM call
        calls['dist'] = abs(calls['strike'] - spot)
        atm = calls.loc[calls['dist'].idxmin()]

        records.append({
            'date': str(date_naive)[:10],
            'spot': spot,
            'strike': float(atm['strike']),
            'dte': int(atm['dte']),
            'expiration': atm['exp'].strftime('%Y-%m-%d'),
            'databento_close': float(atm['close']),
        })

    return records


def fetch_yahoo_prices(records):
    """For each record, fetch the corresponding YF option price."""
    for rec in records:
        try:
            chain = yf_proxy.get_option_chain('AAPL', rec['expiration'])
            if chain and hasattr(chain, 'calls') and not chain.calls.empty:
                match = chain.calls[chain.calls['strike'] == rec['strike']]
                if not match.empty:
                    row = match.iloc[0]
                    bid = row.get('bid', 0) or 0
                    ask = row.get('ask', 0) or 0
                    last = row.get('lastPrice', 0) or 0
                    mid = (bid + ask) / 2 if bid > 0 and ask > 0 else last
                    rec['yahoo_mid'] = float(mid)
                    rec['yahoo_last'] = float(last)
                    rec['yahoo_bid'] = float(bid)
                    rec['yahoo_ask'] = float(ask)
                else:
                    rec['yahoo_mid'] = None
            else:
                rec['yahoo_mid'] = None
        except Exception as e:
            rec['yahoo_mid'] = None
            print(f"    Error fetching YF for {rec['date']} {rec['strike']}: {e}")

    return records


def main():
    print("=" * 70)
    print("EXPERIMENT 011: Yahoo Finance Option Data Quality Test")
    print("Comparing YF vs Databento ground truth on AAPL")
    print("=" * 70)

    print("\nLoading Databento AAPL data...")
    option_df, stock_df = load_databento_aapl()
    print(f"  {len(option_df)} option observations")

    print("\nExtracting ATM call prices for 20 sample dates...")
    records = extract_atm_calls(option_df, stock_df, sample_dates=20)
    print(f"  Found {len(records)} ATM call samples")

    print("\nFetching Yahoo Finance prices for same strikes...")
    records = fetch_yahoo_prices(records)

    # Filter to records where both sources have data
    valid = [r for r in records if r.get('yahoo_mid') and r['yahoo_mid'] > 0]
    print(f"\n  Valid comparisons: {len(valid)} of {len(records)}")

    if len(valid) < 5:
        print("\nINSUFFICIENT DATA — can't compare (YF may not have historical chains)")
        print("NOTE: YF only returns CURRENT option chains, not historical.")
        print("This test can only run on dates where both have live data.")
        print("\nVERDICT: INCONCLUSIVE — YF doesn't provide historical option data.")
        print("For backtesting, Databento remains the only source of real prices.")
        print("YF is usable for LIVE recommendations (current chains) but NOT for backtesting.")

        out = os.path.join(os.path.dirname(__file__), 'results.json')
        with open(out, 'w') as f:
            json.dump({
                'status': 'inconclusive',
                'reason': 'YF only provides current option chains, not historical',
                'valid_comparisons': len(valid),
                'total_samples': len(records),
                'records': records,
            }, f, indent=2, default=str)
        print(f"Results saved to {out}")
        return

    # Compare
    db_prices = np.array([r['databento_close'] for r in valid])
    yf_prices = np.array([r['yahoo_mid'] for r in valid])

    correlation = np.corrcoef(db_prices, yf_prices)[0, 1]
    abs_errors = np.abs(db_prices - yf_prices)
    pct_errors = abs_errors / db_prices * 100
    mean_pct_error = np.mean(pct_errors)
    max_pct_error = np.max(pct_errors)

    print(f"\n{'=' * 70}")
    print("RESULTS")
    print(f"{'=' * 70}")
    print(f"  Correlation:      {correlation:.4f}  (threshold: > 0.90)")
    print(f"  Mean % error:     {mean_pct_error:.1f}%  (threshold: < 10%)")
    print(f"  Max % error:      {max_pct_error:.1f}%")
    print(f"  Samples:          {len(valid)}")

    if correlation > 0.90 and mean_pct_error < 10:
        verdict = "PASS"
        print(f"\n  VERDICT: PASS — YF data is reliable for strategy validation")
    elif correlation > 0.80 or mean_pct_error < 20:
        verdict = "MARGINAL"
        print(f"\n  VERDICT: MARGINAL — YF data is directionally correct but noisy")
    else:
        verdict = "FAIL"
        print(f"\n  VERDICT: FAIL — YF data is too inaccurate for backtesting")

    print(f"\n{'=' * 70}")
    print("SAMPLE COMPARISON")
    print(f"{'=' * 70}")
    print(f"{'Date':>12s} {'Strike':>8s} {'DTE':>5s} {'Databento':>10s} {'Yahoo':>10s} {'Error':>8s}")
    print("-" * 60)
    for r in valid:
        err = abs(r['databento_close'] - r['yahoo_mid']) / r['databento_close'] * 100
        print(f"{r['date']:>12s} ${r['strike']:>6.0f} {r['dte']:>4d}d "
              f"${r['databento_close']:>8.2f} ${r['yahoo_mid']:>8.2f} {err:>7.1f}%")

    out = os.path.join(os.path.dirname(__file__), 'results.json')
    with open(out, 'w') as f:
        json.dump({
            'status': verdict.lower(),
            'correlation': round(correlation, 4),
            'mean_pct_error': round(mean_pct_error, 2),
            'max_pct_error': round(max_pct_error, 2),
            'n_samples': len(valid),
            'records': valid,
        }, f, indent=2, default=str)
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    main()
