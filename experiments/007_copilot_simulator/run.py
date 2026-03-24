"""
Experiment 007: Copilot Simulator

Replay real AAPL covered call history through the copilot.
Shows Dad: "Here's what would have happened if you used this tool."

Uses REAL Databento option prices. Not BSM, not synthetic.
"""

import os
import sys
import re
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd
import databento as db
from position_monitor import assess_position


def load_data(ticker):
    """Load Databento options + Yahoo stock."""
    raw_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'databento', 'raw')
    files = sorted([f for f in os.listdir(raw_dir)
                     if f.startswith(f'{ticker}_ohlcv') and f.endswith('.dbn.zst')])
    dfs = []
    for f in files:
        dfs.append(db.DBNStore.from_file(os.path.join(raw_dir, f)).to_df())
    option_df = pd.concat(dfs).reset_index().drop_duplicates().set_index('ts_event').sort_index()

    import yfinance as yf
    stock = yf.download(ticker, period='2y', progress=False)
    if isinstance(stock.columns, pd.MultiIndex):
        stock.columns = stock.columns.get_level_values(0)

    return option_df, stock


def find_monthly_call(option_df, date, spot, otm_pct=0.05, min_dte=20, max_dte=45):
    """Find a call ~otm_pct OTM with monthly-ish expiry."""
    date_ts = pd.Timestamp(date).normalize()
    if option_df.index.tz is not None and date_ts.tz is None:
        date_ts = date_ts.tz_localize(option_df.index.tz)
    elif option_df.index.tz is not None and date_ts.tz is not None:
        date_ts = date_ts.tz_convert(option_df.index.tz)

    day = option_df[option_df.index.normalize() == date_ts]
    if day.empty:
        return None

    agg = day.groupby('symbol').agg({'close': 'mean', 'volume': 'sum'}).reset_index()
    calls = agg[agg['symbol'].str.match(r'.*\d{6}C\d+', na=False)].copy()
    if calls.empty:
        return None

    def parse(sym):
        m = re.search(r'(\d{6})C(\d{8})', str(sym).strip())
        if m:
            try:
                return datetime.strptime('20' + m.group(1), '%Y%m%d'), float(m.group(2)) / 1000
            except: pass
        return None, None

    parsed = calls['symbol'].apply(lambda s: pd.Series(parse(s), index=['exp', 'strike']))
    calls = pd.concat([calls, parsed], axis=1).dropna(subset=['exp', 'strike'])

    trade_date = pd.Timestamp(date)
    if trade_date.tz is not None:
        trade_date = trade_date.tz_localize(None)
    calls['exp_naive'] = calls['exp'].apply(lambda x: x.replace(tzinfo=None) if hasattr(x, 'tzinfo') and x.tzinfo else x)
    calls['dte'] = (calls['exp_naive'] - trade_date).dt.days
    calls = calls[(calls['dte'] >= min_dte) & (calls['dte'] <= max_dte)]
    if calls.empty:
        return None

    # Nearest monthly ~30 DTE
    calls['dte_dist'] = abs(calls['dte'] - 30)
    best_exp = calls.loc[calls['dte_dist'].idxmin(), 'exp']
    exp_calls = calls[calls['exp'] == best_exp]

    # Strike ~otm_pct above spot
    target = spot * (1 + otm_pct)
    exp_calls = exp_calls.copy()
    exp_calls['dist'] = abs(exp_calls['strike'] - target)
    best = exp_calls.loc[exp_calls['dist'].idxmin()]

    return {
        'symbol': str(best['symbol']),
        'strike': float(best['strike']),
        'price': float(best['close']),
        'expiration': best_exp,
        'dte': int(best['dte']),
    }


def reprice_call(option_df, date, symbol):
    """Get call close price on a date."""
    date_ts = pd.Timestamp(date).normalize()
    if option_df.index.tz is not None and date_ts.tz is None:
        date_ts = date_ts.tz_localize(option_df.index.tz)
    elif option_df.index.tz is not None and date_ts.tz is not None:
        date_ts = date_ts.tz_convert(option_df.index.tz)
    day = option_df[option_df.index.normalize() == date_ts]
    if day.empty:
        return None
    match = day[day['symbol'] == symbol]
    if match.empty:
        return None
    return float(match['close'].mean())


def simulate(ticker='AAPL', otm_pct=0.05, shares_per_contract=100,
              unrealized_gain_per_share=150):
    """
    Simulate monthly covered call selling with copilot monitoring.

    unrealized_gain_per_share: estimated unrealized gain if assigned
    (AAPL: if cost basis ~$100, current ~$250 → $150/share gain → taxes)
    """
    option_df, stock_df = load_data(ticker)
    stock_close = stock_df['Close']

    # Get all trading dates in the option data
    dates = sorted(option_df.index.normalize().unique())

    trades = []
    current_position = None
    daily_log = []

    # Walk through each trading day
    for date in dates:
        date_naive = pd.Timestamp(date).tz_localize(None)

        # Get spot
        spot_match = stock_close[stock_close.index >= date_naive]
        if spot_match.empty:
            continue
        spot = float(spot_match.iloc[0])

        # If no open position, try to sell on first trading day of month
        if current_position is None:
            # Sell on ~first trading day of each month
            if len(trades) == 0 or (date_naive - pd.Timestamp(trades[-1]['entry_date'])).days >= 25:
                call = find_monthly_call(option_df, date, spot, otm_pct)
                if call:
                    current_position = {
                        'symbol': call['symbol'],
                        'strike': call['strike'],
                        'sold_price': call['price'],
                        'expiration': call['expiration'],
                        'entry_date': date_naive,
                        'dte_at_entry': call['dte'],
                        'entry_spot': spot,
                    }
                    daily_log.append({
                        'date': str(date_naive)[:10],
                        'event': 'SELL',
                        'detail': f"Sold {ticker} ${call['strike']:.0f} Call @ ${call['price']:.2f} ({call['dte']} DTE)",
                        'alert': 'N/A',
                    })
            continue

        # Have an open position — monitor it
        pos = current_position
        dte_now = max(0, (pos['expiration'] - date_naive).days)

        # Get current option price
        opt_price = reprice_call(option_df, date, pos['symbol'])
        if opt_price is None:
            opt_price = pos.get('last_known_price', pos['sold_price'])
        pos['last_known_price'] = opt_price

        # Run copilot
        alert = assess_position(
            ticker=ticker,
            strike=pos['strike'],
            expiry=pos['expiration'].strftime('%Y-%m-%d'),
            sold_price=pos['sold_price'],
            contracts=1,
            current_stock=spot,
            current_option_ask=opt_price,
            ex_div_date=None,  # TODO: add ex-div dates
            earnings_date=None,
        )

        daily_log.append({
            'date': str(date_naive)[:10],
            'event': 'MONITOR',
            'detail': f"Stock ${spot:.2f}, strike ${pos['strike']:.0f}, {dte_now} DTE, option ${opt_price:.2f}",
            'alert': alert.level,
            'pct_from_strike': alert.pct_from_strike,
            'p_assignment': alert.p_assignment,
        })

        # ACT on alerts
        closed = False
        close_reason = None

        if alert.level in ('CLOSE_NOW', 'EMERGENCY'):
            closed = True
            close_reason = f"Copilot: {alert.level} — {alert.reason[:60]}"
        elif alert.level == 'CLOSE_SOON':
            closed = True
            close_reason = f"Copilot: CLOSE_SOON — {alert.reason[:60]}"
        elif dte_now <= 0:
            closed = True
            close_reason = "Expired"

        if closed:
            buyback_cost = opt_price
            pnl_per_share = pos['sold_price'] - buyback_cost
            pnl_per_contract = pnl_per_share * 100

            # Would this have been assigned without copilot?
            would_assign = spot > pos['strike'] and dte_now <= 3
            # Check at actual expiry too
            exp_date = pos['expiration']
            exp_spot_match = stock_close[stock_close.index >= exp_date]
            exp_spot = float(exp_spot_match.iloc[0]) if not exp_spot_match.empty else spot
            would_assign_at_expiry = exp_spot > pos['strike']

            tax_if_assigned = unrealized_gain_per_share * shares_per_contract * 0.30  # ~30% tax rate

            trades.append({
                'entry_date': str(pos['entry_date'])[:10],
                'exit_date': str(date_naive)[:10],
                'strike': pos['strike'],
                'sold_price': round(pos['sold_price'], 2),
                'buyback_price': round(buyback_cost, 2),
                'pnl_per_share': round(pnl_per_share, 2),
                'pnl_per_contract': round(pnl_per_contract, 2),
                'close_reason': close_reason,
                'days_held': (date_naive - pos['entry_date']).days,
                'alert_at_close': alert.level,
                'would_assign_at_expiry': would_assign_at_expiry,
                'tax_avoided': round(tax_if_assigned, 2) if would_assign_at_expiry and alert.level in ('CLOSE_NOW', 'EMERGENCY', 'CLOSE_SOON') else 0,
                'entry_spot': round(pos['entry_spot'], 2),
                'exit_spot': round(spot, 2),
            })

            daily_log.append({
                'date': str(date_naive)[:10],
                'event': 'CLOSE',
                'detail': f"Bought back @ ${buyback_cost:.2f}. P&L: ${pnl_per_share:+.2f}/share. {close_reason}",
                'alert': alert.level,
            })

            current_position = None

    return trades, daily_log


def main():
    print("=" * 70)
    print("COPILOT SIMULATOR — Would This Tool Have Saved Dad?")
    print("Real AAPL option prices from Databento, Apr 2025 - Mar 2026")
    print("=" * 70)

    trades, daily_log = simulate('AAPL', otm_pct=0.05)

    if not trades:
        print("No trades generated.")
        return

    print(f"\n{len(trades)} covered calls sold over the period\n")

    # Scorecard
    total_premium = sum(t['sold_price'] for t in trades) * 100
    total_buyback = sum(t['buyback_price'] for t in trades) * 100
    total_pnl = sum(t['pnl_per_contract'] for t in trades)
    assignments_prevented = sum(1 for t in trades if t['would_assign_at_expiry'] and t['alert_at_close'] in ('CLOSE_NOW', 'EMERGENCY', 'CLOSE_SOON'))
    assignments_without_copilot = sum(1 for t in trades if t['would_assign_at_expiry'])
    total_tax_avoided = sum(t['tax_avoided'] for t in trades)
    false_alarms = sum(1 for t in trades if t['alert_at_close'] in ('CLOSE_SOON', 'CLOSE_NOW') and not t['would_assign_at_expiry'])
    false_alarm_cost = sum(abs(t['pnl_per_contract']) for t in trades if t['alert_at_close'] in ('CLOSE_SOON', 'CLOSE_NOW') and not t['would_assign_at_expiry'] and t['pnl_per_contract'] < 0)

    print("=" * 60)
    print("WITH COPILOT")
    print("=" * 60)
    print(f"  Premium collected:     ${total_premium:>+10,.0f}")
    print(f"  Buyback costs:         ${total_buyback:>10,.0f}")
    print(f"  NET PROFIT:            ${total_pnl:>+10,.0f}")
    print(f"  Assignments:           ZERO")
    print(f"  Assignments prevented: {assignments_prevented}")
    print(f"  False alarms:          {false_alarms} (cost: ${false_alarm_cost:,.0f})")

    print(f"\n{'=' * 60}")
    print("WITHOUT COPILOT (hold everything to expiry)")
    print("=" * 60)
    print(f"  Would have been assigned: {assignments_without_copilot} times")
    print(f"  Estimated tax avoided:    ${total_tax_avoided:>10,.0f}")

    if total_tax_avoided > 0:
        buyback_total = sum(abs(t['pnl_per_contract']) for t in trades if t['pnl_per_contract'] < 0)
        roi = total_tax_avoided / max(buyback_total, 1)
        print(f"\n  COPILOT SAVED:      ${total_tax_avoided:,.0f} in avoided taxes")
        print(f"  COST OF PROTECTION: ${buyback_total:,.0f} in early buybacks")
        print(f"  RETURN ON COPILOT:  {roi:.0f}x")

    # Trade-by-trade log
    print(f"\n{'=' * 60}")
    print("TRADE-BY-TRADE LOG")
    print("=" * 60)

    icons = {'SAFE': '✅', 'WATCH': '⚠️', 'CLOSE_SOON': '🟠', 'CLOSE_NOW': '🔴', 'EMERGENCY': '🚨'}

    for t in trades:
        icon = icons.get(t['alert_at_close'], '?')
        assign_note = " — WOULD HAVE BEEN ASSIGNED" if t['would_assign_at_expiry'] else ""
        tax_note = f" — SAVED ${t['tax_avoided']:,.0f} in taxes" if t['tax_avoided'] > 0 else ""

        print(f"\n  {t['entry_date']} → {t['exit_date']} ({t['days_held']}d)")
        print(f"  {icon} Sold ${t['strike']:.0f} Call @ ${t['sold_price']:.2f}")
        print(f"     Stock: ${t['entry_spot']:.0f} → ${t['exit_spot']:.0f}")
        print(f"     {t['close_reason']}")
        print(f"     P&L: ${t['pnl_per_contract']:+,.0f} per contract{assign_note}{tax_note}")

    # Alert distribution across all daily observations
    alert_counts = {}
    for d in daily_log:
        if d['event'] == 'MONITOR':
            level = d['alert']
            alert_counts[level] = alert_counts.get(level, 0) + 1

    total_days = sum(alert_counts.values())
    print(f"\n{'=' * 60}")
    print("DAILY ALERT DISTRIBUTION")
    print("=" * 60)
    for level in ['SAFE', 'WATCH', 'CLOSE_SOON', 'CLOSE_NOW', 'EMERGENCY']:
        count = alert_counts.get(level, 0)
        pct = count / total_days * 100 if total_days > 0 else 0
        icon = icons.get(level, '?')
        print(f"  {icon} {level:12s}: {count:4d} days ({pct:5.1f}%)")

    # Save
    out = os.path.join(os.path.dirname(__file__), 'results.json')
    with open(out, 'w') as f:
        json.dump({
            'trades': trades,
            'summary': {
                'total_premium': total_premium,
                'total_buyback': total_buyback,
                'net_pnl': total_pnl,
                'assignments_prevented': assignments_prevented,
                'assignments_without_copilot': assignments_without_copilot,
                'tax_avoided': total_tax_avoided,
                'false_alarms': false_alarms,
                'false_alarm_cost': false_alarm_cost,
            },
        }, f, indent=2, default=str)
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    main()
