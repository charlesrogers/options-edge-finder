"""
Experiment 012: Walk-Forward Validation

Split data into train (first 8mo) and test (last 4mo).
Find optimal OTM% on train, validate on test.
Confirms or challenges Experiment 008 findings.
"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '007_copilot_simulator'))

import numpy as np
import pandas as pd
from run import load_data, find_monthly_call, reprice_call
from position_monitor import assess_position

# Reuse simulate from experiment 008
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '008_strategy_grid'))
from run import score_trades

# Import the enhanced simulator
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '007_copilot_simulator'))
from run import simulate

OTM_PCTS = [0.03, 0.05, 0.07, 0.10, 0.15]
DTE_RANGE = (20, 45)  # Standard monthly
TICKERS = ['AAPL', 'DIS', 'TXN', 'TMUS', 'KKR']


def split_dates(option_df, train_frac=0.67):
    """Split option data into train and test periods."""
    dates = sorted(option_df.index.normalize().unique())
    split_idx = int(len(dates) * train_frac)
    train_end = dates[split_idx]
    return train_end


def simulate_period(ticker, otm_pct, option_df, stock_df, start_date=None, end_date=None):
    """Run the simulator on a subset of dates."""
    stock_close = stock_df['Close']
    dates = sorted(option_df.index.normalize().unique())

    if start_date:
        start_ts = pd.Timestamp(start_date)
        if dates[0].tz is not None and start_ts.tz is None:
            start_ts = start_ts.tz_localize(dates[0].tz)
        dates = [d for d in dates if d >= start_ts]
    if end_date:
        end_ts = pd.Timestamp(end_date)
        if dates[0].tz is not None and end_ts.tz is None:
            end_ts = end_ts.tz_localize(dates[0].tz)
        dates = [d for d in dates if d <= end_ts]

    trades = []
    current_position = None
    min_dte, max_dte = DTE_RANGE

    for date in dates:
        date_naive = pd.Timestamp(date).tz_localize(None)
        spot_match = stock_close[stock_close.index >= date_naive]
        if spot_match.empty:
            continue
        spot = float(spot_match.iloc[0])

        if current_position is None:
            if len(trades) == 0 or (date_naive - pd.Timestamp(trades[-1]['entry_date'])).days >= 25:
                call = find_monthly_call(option_df, date, spot, otm_pct, min_dte, max_dte)
                if call:
                    current_position = {
                        'symbol': call['symbol'], 'strike': call['strike'],
                        'sold_price': call['price'], 'expiration': call['expiration'],
                        'entry_date': date_naive, 'dte_at_entry': call['dte'],
                        'entry_spot': spot,
                    }
            continue

        pos = current_position
        dte_now = max(0, (pos['expiration'] - date_naive).days)
        opt_price = reprice_call(option_df, date, pos['symbol'])
        if opt_price is None:
            opt_price = pos.get('last_known_price', pos['sold_price'])
        pos['last_known_price'] = opt_price

        alert = assess_position(
            ticker=ticker, strike=pos['strike'],
            expiry=pos['expiration'].strftime('%Y-%m-%d'),
            sold_price=pos['sold_price'], contracts=1,
            current_stock=spot, current_option_ask=opt_price,
        )

        closed = False
        close_reason = None
        if alert.level in ('CLOSE_NOW', 'EMERGENCY'):
            closed = True
            close_reason = f"{alert.level}"
        elif alert.level == 'CLOSE_SOON':
            closed = True
            close_reason = "CLOSE_SOON"
        elif dte_now <= 0:
            closed = True
            close_reason = "Expired"

        if closed:
            buyback_cost = opt_price
            pnl = pos['sold_price'] - buyback_cost

            exp_date = pos['expiration']
            exp_spot_match = stock_close[stock_close.index >= exp_date]
            exp_spot = float(exp_spot_match.iloc[0]) if not exp_spot_match.empty else spot
            would_assign = exp_spot > pos['strike']

            trades.append({
                'entry_date': str(pos['entry_date'])[:10],
                'exit_date': str(date_naive)[:10],
                'strike': pos['strike'],
                'sold_price': round(pos['sold_price'], 2),
                'buyback_price': round(buyback_cost, 2),
                'pnl_per_share': round(pnl, 2),
                'pnl_per_contract': round(pnl * 100, 2),
                'close_reason': close_reason,
                'days_held': (date_naive - pos['entry_date']).days,
                'alert_at_close': alert.level,
                'would_assign_at_expiry': would_assign,
                'tax_avoided': 0,
                'entry_spot': round(pos['entry_spot'], 2),
                'exit_spot': round(spot, 2),
            })
            current_position = None

    return trades


def main():
    print("=" * 80)
    print("EXPERIMENT 012: Walk-Forward Validation")
    print("Train on first 2/3 of data, test on last 1/3")
    print("=" * 80)

    results = []

    for ticker in TICKERS:
        print(f"\n{'=' * 80}")
        print(f"TICKER: {ticker}")

        try:
            option_df, stock_df = load_data(ticker)
        except Exception as e:
            print(f"  SKIP: {e}")
            continue

        dates = sorted(option_df.index.normalize().unique())
        train_end = dates[int(len(dates) * 0.67)]
        test_start = train_end

        print(f"  Data: {str(dates[0])[:10]} → {str(dates[-1])[:10]} ({len(dates)} days)")
        print(f"  Train: → {str(train_end)[:10]}")
        print(f"  Test:  {str(test_start)[:10]} →")

        # Find optimal OTM% on TRAIN period
        train_results = []
        for otm in OTM_PCTS:
            trades = simulate_period(ticker, otm, option_df, stock_df, end_date=train_end)
            metrics = score_trades(trades)
            train_results.append({
                'otm_pct': otm,
                'net_pnl': metrics['net_pnl'],
                'win_rate': metrics['win_rate'],
                'num_trades': metrics['num_trades'],
            })
            print(f"  TRAIN {otm*100:.0f}% OTM: {metrics['num_trades']}t, PnL ${metrics['net_pnl']:+,.0f}, win={metrics['win_rate']:.0f}%")

        # Best OTM% from training
        best_train = max(train_results, key=lambda x: x['net_pnl'])
        best_otm = best_train['otm_pct']
        print(f"\n  BEST TRAIN: {best_otm*100:.0f}% OTM (PnL ${best_train['net_pnl']:+,.0f})")

        # Run BEST on TEST period
        test_trades = simulate_period(ticker, best_otm, option_df, stock_df, start_date=test_start)
        test_metrics = score_trades(test_trades)

        print(f"  TEST:  {test_metrics['num_trades']}t, PnL ${test_metrics['net_pnl']:+,.0f}, win={test_metrics['win_rate']:.0f}%")

        # Also run Experiment 008's recommended OTM% on test
        from ticker_strategies import TICKER_STRATEGIES
        rec_otm = TICKER_STRATEGIES.get(ticker, {}).get('otm_pct')
        if rec_otm and rec_otm != best_otm:
            rec_test_trades = simulate_period(ticker, rec_otm, option_df, stock_df, start_date=test_start)
            rec_test_metrics = score_trades(rec_test_trades)
            print(f"  TEST (Exp 008 rec {rec_otm*100:.0f}%): {rec_test_metrics['num_trades']}t, PnL ${rec_test_metrics['net_pnl']:+,.0f}")
        else:
            rec_test_metrics = test_metrics

        # Ratio
        ratio = test_metrics['net_pnl'] / best_train['net_pnl'] if best_train['net_pnl'] != 0 else 0

        results.append({
            'ticker': ticker,
            'best_train_otm': best_otm,
            'train_pnl': best_train['net_pnl'],
            'train_win_rate': best_train['win_rate'],
            'train_trades': best_train['num_trades'],
            'test_pnl': test_metrics['net_pnl'],
            'test_win_rate': test_metrics['win_rate'],
            'test_trades': test_metrics['num_trades'],
            'oos_ratio': round(ratio, 2),
            'test_positive': test_metrics['net_pnl'] > 0,
            'exp008_rec_otm': rec_otm,
            'exp008_test_pnl': rec_test_metrics['net_pnl'],
        })

    # Summary
    print(f"\n{'=' * 80}")
    print("WALK-FORWARD SUMMARY")
    print(f"{'=' * 80}")

    print(f"\n{'Ticker':>6s} {'Train OTM':>10s} {'Train PnL':>10s} {'Test PnL':>10s} {'OOS Ratio':>10s} {'Pass?':>6s}")
    print("-" * 60)
    positive_count = 0
    for r in results:
        passed = "YES" if r['test_positive'] else "NO"
        if r['test_positive']:
            positive_count += 1
        print(f"{r['ticker']:>6s} {r['best_train_otm']*100:>8.0f}% ${r['train_pnl']:>+9,.0f} ${r['test_pnl']:>+9,.0f} {r['oos_ratio']:>9.2f}x {passed:>6s}")

    print(f"\nPositive out-of-sample: {positive_count} of {len(results)} tickers")
    if positive_count >= 3:
        print("VERDICT: PASS — strategies hold out-of-sample")
    elif positive_count >= 2:
        print("VERDICT: MARGINAL — some strategies hold, some don't")
    else:
        print("VERDICT: FAIL — strategies are overfit to training period")

    out = os.path.join(os.path.dirname(__file__), 'results.json')
    with open(out, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    main()
