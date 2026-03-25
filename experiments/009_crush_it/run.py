"""
Experiment 009: Make It Crush — IV-Aware Entry + Early Rolling

Two levers to improve covered call premium retention from 26% to 40%+:
  1. IV-aware entry: only sell when IV is elevated (iv_rank >= 50)
  2. Early rolling: at CLOSE_SOON, roll to next month instead of closing

Uses REAL Databento option prices. Not BSM, not synthetic.
"""

import os
import sys
import json
import re
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '007_copilot_simulator'))

import numpy as np
import pandas as pd

from run import load_data, find_monthly_call, reprice_call
from position_monitor import assess_position


def compute_daily_atm_iv_proxy(option_df, stock_df):
    """
    Compute a daily ATM IV proxy from option prices.

    Uses ATM call price as % of stock price as a proxy for IV level.
    Higher ratio = higher IV. We rank this to get iv_rank.
    """
    stock_close = stock_df['Close']
    dates = sorted(option_df.index.normalize().unique())

    daily_iv = {}
    for date in dates:
        date_naive = pd.Timestamp(date).tz_localize(None)

        # Get spot
        spot_match = stock_close[stock_close.index >= date_naive]
        if spot_match.empty:
            continue
        spot = float(spot_match.iloc[0])

        # Get ATM call price (nearest strike to spot, 20-45 DTE)
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

        # Parse strikes and expirations
        def parse(sym):
            m = re.search(r'(\d{6})C(\d{8})', str(sym).strip())
            if m:
                try:
                    return datetime.strptime('20' + m.group(1), '%Y%m%d'), float(m.group(2)) / 1000
                except:
                    pass
            return None, None

        parsed = calls['symbol'].apply(lambda s: pd.Series(parse(s), index=['exp', 'strike']))
        calls = pd.concat([calls, parsed], axis=1).dropna(subset=['exp', 'strike'])

        # Filter to 20-45 DTE
        trade_date = date_naive
        calls['exp_naive'] = calls['exp'].apply(lambda x: x.replace(tzinfo=None) if hasattr(x, 'tzinfo') and x.tzinfo else x)
        calls['dte'] = (calls['exp_naive'] - trade_date).dt.days
        calls = calls[(calls['dte'] >= 20) & (calls['dte'] <= 45)]
        if calls.empty:
            continue

        # Find ATM call (nearest strike to spot)
        calls['dist'] = abs(calls['strike'] - spot)
        atm = calls.loc[calls['dist'].idxmin()]

        # IV proxy: ATM call price as % of stock (rough but directional)
        iv_proxy = float(atm['close']) / spot * 100
        daily_iv[str(date_naive)[:10]] = iv_proxy

    # Compute rolling iv_rank (percentile over trailing 60 days)
    iv_series = pd.Series(daily_iv).sort_index()
    iv_rank = {}
    for i, (date, val) in enumerate(iv_series.items()):
        lookback = iv_series.iloc[max(0, i-60):i+1]
        if len(lookback) >= 10:
            rank = (lookback < val).sum() / len(lookback) * 100
        else:
            rank = 50  # default when insufficient history
        iv_rank[date] = rank

    return daily_iv, iv_rank


def simulate_enhanced(ticker='AAPL', otm_pct=0.05, min_dte=20, max_dte=45,
                       shares_per_contract=100, unrealized_gain_per_share=150,
                       iv_filter=False, iv_threshold=50,
                       allow_roll=False, roll_min_premium_ratio=0.5):
    """
    Enhanced simulator with IV-aware entry and early rolling.
    """
    option_df, stock_df = load_data(ticker)
    stock_close = stock_df['Close']
    dates = sorted(option_df.index.normalize().unique())

    # Compute IV data if needed
    iv_proxy = {}
    iv_rank = {}
    if iv_filter:
        print(f"    Computing IV proxy for {ticker}...", end=" ", flush=True)
        iv_proxy, iv_rank = compute_daily_atm_iv_proxy(option_df, stock_df)
        print(f"{len(iv_rank)} days")

    trades = []
    current_position = None
    daily_log = []
    roll_count = 0
    iv_skips = 0

    for date in dates:
        date_naive = pd.Timestamp(date).tz_localize(None)

        spot_match = stock_close[stock_close.index >= date_naive]
        if spot_match.empty:
            continue
        spot = float(spot_match.iloc[0])

        # --- ENTRY ---
        if current_position is None:
            if len(trades) == 0 or (date_naive - pd.Timestamp(trades[-1]['entry_date'])).days >= 25:

                # IV filter check
                if iv_filter:
                    date_str = str(date_naive)[:10]
                    rank = iv_rank.get(date_str, 50)
                    if rank < iv_threshold:
                        iv_skips += 1
                        daily_log.append({
                            'date': date_str,
                            'event': 'IV_SKIP',
                            'detail': f"IV rank {rank:.0f} < {iv_threshold} threshold. Skipping entry.",
                        })
                        continue

                call = find_monthly_call(option_df, date, spot, otm_pct, min_dte, max_dte)
                if call:
                    current_position = {
                        'symbol': call['symbol'],
                        'strike': call['strike'],
                        'sold_price': call['price'],
                        'expiration': call['expiration'],
                        'entry_date': date_naive,
                        'dte_at_entry': call['dte'],
                        'entry_spot': spot,
                        'roll_count': 0,
                    }
            continue

        # --- MONITOR ---
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
            ex_div_date=None, earnings_date=None,
        )

        # --- ACT ---
        closed = False
        close_reason = None
        rolled = False

        if alert.level in ('CLOSE_NOW', 'EMERGENCY'):
            closed = True
            close_reason = f"Copilot: {alert.level} — {alert.reason[:60]}"

        elif alert.level == 'CLOSE_SOON':
            # Try to roll if enabled
            if allow_roll and dte_now >= 7 and dte_now <= 14:
                next_call = find_monthly_call(option_df, date, spot, otm_pct, min_dte, max_dte)
                if next_call and next_call['symbol'] != pos['symbol']:
                    new_premium = next_call['price']
                    if new_premium >= pos['sold_price'] * roll_min_premium_ratio:
                        # Execute roll
                        roll_cost = opt_price  # buy back current
                        roll_credit = new_premium  # sell new

                        # Record the partial trade (close of current leg)
                        pnl_current_leg = pos['sold_price'] - roll_cost

                        daily_log.append({
                            'date': str(date_naive)[:10],
                            'event': 'ROLL',
                            'detail': (f"Rolled {pos['symbol']} (buy back ${opt_price:.2f}) "
                                       f"→ {next_call['symbol']} (sell ${new_premium:.2f}). "
                                       f"Net roll cost: ${opt_price - new_premium:.2f}"),
                        })

                        # Update position to new call
                        current_position = {
                            'symbol': next_call['symbol'],
                            'strike': next_call['strike'],
                            'sold_price': new_premium,
                            'expiration': next_call['expiration'],
                            'entry_date': pos['entry_date'],  # keep original entry
                            'dte_at_entry': pos['dte_at_entry'],
                            'entry_spot': pos['entry_spot'],
                            'roll_count': pos.get('roll_count', 0) + 1,
                            'cumulative_premium': pos.get('cumulative_premium', pos['sold_price']) + new_premium,
                            'cumulative_buyback': pos.get('cumulative_buyback', 0) + roll_cost,
                        }
                        roll_count += 1
                        rolled = True

            if not rolled:
                closed = True
                close_reason = f"Copilot: CLOSE_SOON — {alert.reason[:60]}"

        elif dte_now <= 0:
            closed = True
            close_reason = "Expired"

        if closed:
            buyback_cost = opt_price

            # Account for cumulative premium/buyback from rolls
            total_premium = pos.get('cumulative_premium', pos['sold_price'])
            total_buyback = pos.get('cumulative_buyback', 0) + buyback_cost
            pnl_per_share = total_premium - total_buyback
            pnl_per_contract = pnl_per_share * 100

            # Assignment check
            exp_date = pos['expiration']
            exp_spot_match = stock_close[stock_close.index >= exp_date]
            exp_spot = float(exp_spot_match.iloc[0]) if not exp_spot_match.empty else spot
            would_assign_at_expiry = exp_spot > pos['strike']

            tax_if_assigned = unrealized_gain_per_share * shares_per_contract * 0.30

            trades.append({
                'entry_date': str(pos['entry_date'])[:10],
                'exit_date': str(date_naive)[:10],
                'strike': pos['strike'],
                'sold_price': round(total_premium, 2),
                'buyback_price': round(total_buyback, 2),
                'pnl_per_share': round(pnl_per_share, 2),
                'pnl_per_contract': round(pnl_per_contract, 2),
                'close_reason': close_reason,
                'days_held': (date_naive - pos['entry_date']).days,
                'alert_at_close': alert.level,
                'would_assign_at_expiry': would_assign_at_expiry,
                'tax_avoided': round(tax_if_assigned, 2) if would_assign_at_expiry and alert.level in ('CLOSE_NOW', 'EMERGENCY', 'CLOSE_SOON') else 0,
                'entry_spot': round(pos['entry_spot'], 2),
                'exit_spot': round(spot, 2),
                'roll_count': pos.get('roll_count', 0),
            })

            current_position = None

    return trades, daily_log, {'roll_count': roll_count, 'iv_skips': iv_skips}


def score_trades(trades):
    """Same scoring as experiment 008."""
    if not trades:
        return {'num_trades': 0, 'net_pnl': 0, 'win_rate': 0, 'premium_retained_pct': 0,
                'worst_trade': 0, 'assignments': 0, 'false_alarms': 0, 'composite_score': 0,
                'total_premium': 0, 'total_buyback': 0, 'avg_pnl': 0, 'rolls': 0}

    total_premium = sum(t['sold_price'] for t in trades) * 100
    total_buyback = sum(t['buyback_price'] for t in trades) * 100
    net_pnl = sum(t['pnl_per_contract'] for t in trades)
    winners = [t for t in trades if t['pnl_per_contract'] >= 0]
    win_rate = len(winners) / len(trades) * 100
    worst_trade = min(t['pnl_per_contract'] for t in trades)
    avg_pnl = net_pnl / len(trades)
    rolls = sum(t.get('roll_count', 0) for t in trades)

    prevented = sum(1 for t in trades if t['would_assign_at_expiry'] and t['alert_at_close'] in ('CLOSE_NOW', 'EMERGENCY', 'CLOSE_SOON'))
    total_would = sum(1 for t in trades if t['would_assign_at_expiry'])
    assignments = total_would - prevented

    false_alarms = sum(1 for t in trades if t['alert_at_close'] in ('CLOSE_SOON', 'CLOSE_NOW') and not t['would_assign_at_expiry'])

    premium_retained_pct = (net_pnl / total_premium * 100) if total_premium > 0 else 0

    if assignments > 0:
        composite_score = -999
    elif net_pnl <= 0:
        composite_score = net_pnl
    else:
        composite_score = (avg_pnl * win_rate / 100) - (abs(worst_trade) * 0.2)

    return {
        'num_trades': len(trades), 'net_pnl': round(net_pnl, 2),
        'avg_pnl': round(avg_pnl, 2), 'win_rate': round(win_rate, 1),
        'worst_trade': round(worst_trade, 2), 'assignments': assignments,
        'false_alarms': false_alarms, 'premium_retained_pct': round(premium_retained_pct, 1),
        'total_premium': round(total_premium, 2), 'total_buyback': round(total_buyback, 2),
        'composite_score': round(composite_score, 2), 'rolls': rolls,
    }


# ============================================================
# GRID
# ============================================================

OTM_PCTS = [0.03, 0.05, 0.07, 0.10, 0.15]
DTE_RANGES = [(14, 30), (20, 45), (30, 60)]
TICKERS = ['AAPL', 'DIS', 'TXN', 'TMUS', 'KKR']

VARIANTS = [
    ('B_iv_only',   True,  False),
    ('C_roll_only', False, True),
    ('D_both',      True,  True),
]


def main():
    print("=" * 90)
    print("EXPERIMENT 009: Make It Crush — IV-Aware Entry + Early Rolling")
    print("=" * 90)

    all_results = {}

    for variant_name, use_iv, use_roll in VARIANTS:
        print(f"\n{'=' * 90}")
        print(f"VARIANT {variant_name}: IV filter={'ON' if use_iv else 'OFF'}, Rolling={'ON' if use_roll else 'OFF'}")
        print(f"{'=' * 90}")

        results = []
        total = len(TICKERS) * len(OTM_PCTS) * len(DTE_RANGES)
        n = 0

        for ticker in TICKERS:
            raw_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'databento', 'raw')
            files = [f for f in os.listdir(raw_dir) if f.startswith(f'{ticker}_ohlcv') and f.endswith('.dbn.zst')]
            if not files:
                n += len(OTM_PCTS) * len(DTE_RANGES)
                continue

            for otm in OTM_PCTS:
                for min_dte, max_dte in DTE_RANGES:
                    n += 1
                    label = f"{ticker} {otm*100:.0f}% {min_dte}-{max_dte}"
                    print(f"  [{n}/{total}] {label}...", end=" ", flush=True)

                    try:
                        trades, log, meta = simulate_enhanced(
                            ticker=ticker, otm_pct=otm, min_dte=min_dte, max_dte=max_dte,
                            iv_filter=use_iv, iv_threshold=50,
                            allow_roll=use_roll, roll_min_premium_ratio=0.5,
                        )
                        metrics = score_trades(trades)
                        results.append({
                            'variant': variant_name, 'ticker': ticker,
                            'otm_pct': otm, 'min_dte': min_dte, 'max_dte': max_dte,
                            'dte_label': f"{min_dte}-{max_dte}",
                            'iv_skips': meta['iv_skips'], 'roll_count': meta['roll_count'],
                            **metrics,
                        })
                        print(f"{metrics['num_trades']}t PnL ${metrics['net_pnl']:+,.0f} "
                              f"win={metrics['win_rate']:.0f}% ret={metrics['premium_retained_pct']:.0f}% "
                              f"rolls={metrics['rolls']} skip={meta['iv_skips']}")
                    except Exception as e:
                        print(f"FAILED: {e}")

        all_results[variant_name] = results

    # ============================================================
    # COMPARISON vs BASELINE
    # ============================================================
    print("\n" + "=" * 90)
    print("HEAD-TO-HEAD: Variant D (IV+Roll) vs Baseline (Experiment 008)")
    print("=" * 90)

    # Load baseline
    baseline_path = os.path.join(os.path.dirname(__file__), '..', '008_strategy_grid', 'results.json')
    with open(baseline_path) as f:
        baseline = json.load(f)

    for variant_name in ['B_iv_only', 'C_roll_only', 'D_both']:
        variant = all_results[variant_name]
        if not variant:
            continue

        v_df = pd.DataFrame(variant)
        v_df = v_df[v_df['num_trades'] > 0]
        b_df = pd.DataFrame(baseline)
        b_df = b_df[b_df.get('num_trades', pd.Series(dtype=float)).notna() & (b_df['num_trades'] > 0)]

        if v_df.empty or b_df.empty:
            continue

        v_pnl = v_df['net_pnl'].mean()
        b_pnl = b_df['net_pnl'].mean()
        v_ret = v_df['premium_retained_pct'].mean()
        b_ret = b_df['premium_retained_pct'].mean() if 'premium_retained_pct' in b_df.columns else 0
        v_win = v_df['win_rate'].mean()
        b_win = b_df['win_rate'].mean()
        v_assign = int(v_df['assignments'].sum())
        v_profitable = len(v_df[v_df['net_pnl'] > 0])
        b_profitable = len(b_df[b_df['net_pnl'] > 0])

        print(f"\n  {variant_name}:")
        print(f"    Avg P&L:     ${v_pnl:+,.0f} vs ${b_pnl:+,.0f} baseline ({'+' if v_pnl > b_pnl else ''}{v_pnl - b_pnl:+,.0f})")
        print(f"    Retention:   {v_ret:.0f}% vs {b_ret:.0f}% baseline")
        print(f"    Win rate:    {v_win:.0f}% vs {b_win:.0f}% baseline")
        print(f"    Profitable:  {v_profitable}/{len(v_df)} vs {b_profitable}/{len(b_df)} baseline")
        print(f"    Assignments: {v_assign}")
        if variant_name == 'D_both':
            total_rolls = int(v_df['rolls'].sum()) if 'rolls' in v_df.columns else 0
            total_skips = int(v_df['iv_skips'].sum()) if 'iv_skips' in v_df.columns else 0
            print(f"    Rolls: {total_rolls}, IV skips: {total_skips}")

    # Save
    out = os.path.join(os.path.dirname(__file__), 'results.json')
    with open(out, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    main()
