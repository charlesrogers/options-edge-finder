"""
Experiment 005: Straddles/Strangles on Dad's Stocks

CONSTRAINT: Only trade AAPL, DIS, TXN, TMUS, KKR (Dad's stocks with Databento data)
Uses corrected portfolio engine with daily P&L as CHANGE not level.
Real Databento prices. Position limits. Sanity checks.
"""

import os
import sys
import json
import re
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
import pandas as pd
from backtest_engine import (
    load_option_data, load_stock_data, compute_daily_signals,
    reprice_option, parse_option_symbol, get_puts_on_date
)


def get_calls_on_date(option_df, date):
    """Get all calls available on a date."""
    date_ts = pd.Timestamp(date).normalize()
    if option_df.index.tz is not None:
        date_ts = date_ts.tz_localize(option_df.index.tz)
    day_data = option_df[option_df.index.normalize() == date_ts]
    if day_data.empty:
        return pd.DataFrame()

    agg = day_data.groupby('symbol').agg({'close': 'mean', 'volume': 'sum'}).reset_index()
    calls = agg[agg['symbol'].str.match(r'.*\d{6}C\d+', na=False)].copy()
    if calls.empty:
        return pd.DataFrame()

    def parse_call(sym):
        m = re.search(r'(\d{6})C(\d{8})', str(sym).strip())
        if m:
            try:
                exp = datetime.strptime('20' + m.group(1), '%Y%m%d')
                strike = float(m.group(2)) / 1000
                return exp, strike
            except:
                pass
        return None, None

    parsed = calls['symbol'].apply(lambda s: pd.Series(parse_call(s), index=['expiration', 'strike']))
    calls = pd.concat([calls, parsed], axis=1).dropna(subset=['expiration', 'strike'])
    return calls


def find_straddle(option_df, date, spot, min_dte=3, max_dte=10, otm_pct=0):
    """
    Find ATM straddle (or OTM strangle if otm_pct > 0).

    Returns dict with call + put legs or None.
    """
    puts = get_puts_on_date(option_df, date)
    calls = get_calls_on_date(option_df, date)

    if puts.empty or calls.empty:
        return None

    trade_date = pd.Timestamp(date)

    # Add DTE
    puts['dte'] = (puts['expiration'] - trade_date).dt.days
    calls['dte'] = (calls['expiration'] - trade_date).dt.days

    # Filter DTE range
    puts = puts[(puts['dte'] >= min_dte) & (puts['dte'] <= max_dte)]
    calls = calls[(calls['dte'] >= min_dte) & (calls['dte'] <= max_dte)]

    if puts.empty or calls.empty:
        return None

    # Find nearest weekly expiry
    target_dte = (min_dte + max_dte) // 2
    puts['dte_dist'] = abs(puts['dte'] - target_dte)
    best_exp = puts.loc[puts['dte_dist'].idxmin(), 'expiration']
    exp_puts = puts[puts['expiration'] == best_exp]
    exp_calls = calls[calls['expiration'] == best_exp]

    if exp_puts.empty or exp_calls.empty:
        return None

    # Find ATM (or OTM for strangle)
    put_target = spot * (1 - otm_pct)
    call_target = spot * (1 + otm_pct)

    exp_puts = exp_puts.copy()
    exp_puts['dist'] = abs(exp_puts['strike'] - put_target)
    put_row = exp_puts.loc[exp_puts['dist'].idxmin()]

    exp_calls = exp_calls.copy()
    exp_calls['dist'] = abs(exp_calls['strike'] - call_target)
    call_row = exp_calls.loc[exp_calls['dist'].idxmin()]

    put_price = float(put_row['close'])
    call_price = float(call_row['close'])
    total_credit = put_price + call_price

    if total_credit <= 0:
        return None

    return {
        "put_symbol": str(put_row['symbol']),
        "call_symbol": str(call_row['symbol']),
        "put_strike": float(put_row['strike']),
        "call_strike": float(call_row['strike']),
        "put_price": put_price,
        "call_price": call_price,
        "total_credit": total_credit,
        "expiration": best_exp,
        "dte": int(put_row['dte']),
    }


def backtest_straddles(tickers, option_data, stock_data,
                        mode="straddle",  # "straddle" or "strangle"
                        otm_pct=0,  # 0 for straddle, 0.05 for strangle
                        min_dte=3, max_dte=10,  # weekly
                        take_profit_pct=0.50,
                        dte_floor=2,
                        slippage_pct=0.05,
                        max_per_ticker=1,
                        min_vrp=2.0,
                        capital=100000):
    """
    Portfolio-level straddle/strangle backtest.
    Daily P&L as CHANGE (not level). Per lessons.md.
    """
    # Compute signals
    signals = {}
    for t in tickers:
        if t in stock_data:
            signals[t] = compute_daily_signals(stock_data[t])

    # All trading days
    all_dates = set()
    for s in signals.values():
        all_dates.update(s.index)
    all_dates = sorted(all_dates)

    # State
    positions = []  # list of dicts
    closed_trades = []
    daily_pnl_list = []
    prev_portfolio_value = 0.0
    reprice_stats = {"found": 0, "missing": 0}
    skipped = 0

    for date in all_dates:
        if date.weekday() >= 5:
            continue

        realized_today = 0.0

        # 1. Check exits on open positions
        to_close = []
        for i, pos in enumerate(positions):
            dte_remaining = (pos['expiration'] - date).days

            # DTE floor FIRST
            if dte_floor > 0 and dte_remaining <= dte_floor:
                to_close.append((i, "dte_floor"))
                continue

            # Reprice both legs
            ticker = pos['ticker']
            opt_df = option_data.get(ticker, pd.DataFrame())

            put_p, put_found = reprice_option(opt_df, date, pos['put_symbol'])
            call_p, call_found = reprice_option(opt_df, date, pos['call_symbol'])

            if put_found:
                pos['last_put'] = put_p
                reprice_stats["found"] += 1
            else:
                reprice_stats["missing"] += 1
                put_p = pos['last_put']

            if call_found:
                pos['last_call'] = call_p
                reprice_stats["found"] += 1
            else:
                reprice_stats["missing"] += 1
                call_p = pos['last_call']

            pos['days_stale'] = 0 if (put_found or call_found) else pos.get('days_stale', 0) + 1

            current_value = put_p + call_p

            # Stale exit
            if pos['days_stale'] >= 3:
                to_close.append((i, "stale"))
                continue

            # Take profit
            tp_threshold = pos['raw_credit'] * (1 - take_profit_pct)
            if take_profit_pct < 1.0 and current_value <= tp_threshold:
                to_close.append((i, "take_profit"))
                continue

        # Close positions
        for idx, reason in sorted(to_close, key=lambda x: x[0], reverse=True):
            pos = positions[idx]
            current_value = pos['last_put'] + pos['last_call']
            close_cost = current_value * (1 + slippage_pct)
            pnl = (pos['adj_credit'] - close_cost) * 100

            closed_trades.append({
                "ticker": pos['ticker'],
                "entry_date": str(pos['entry_date'])[:10],
                "exit_date": str(date)[:10],
                "exit_reason": reason,
                "raw_credit": round(pos['raw_credit'] * 100, 2),
                "pnl": round(pnl, 2),
                "days_held": (date - pos['entry_date']).days,
                "put_strike": pos['put_strike'],
                "call_strike": pos['call_strike'],
            })
            realized_today += pnl
            positions.pop(idx)

        # 2. Open new positions
        for ticker in tickers:
            if ticker not in signals or ticker not in option_data:
                continue
            if date not in signals[ticker].index:
                continue

            row = signals[ticker].loc[date]
            if row['signal'] != 'GREEN' or row['vrp'] < min_vrp:
                continue

            # Position limit
            ticker_open = sum(1 for p in positions if p['ticker'] == ticker)
            if ticker_open >= max_per_ticker:
                skipped += 1
                continue

            # Find straddle/strangle
            strad = find_straddle(option_data[ticker], date, row['close'],
                                   min_dte=min_dte, max_dte=max_dte, otm_pct=otm_pct)
            if strad is None:
                continue

            adj_credit = strad['total_credit'] * (1 - slippage_pct)

            positions.append({
                "ticker": ticker,
                "entry_date": date,
                "put_symbol": strad['put_symbol'],
                "call_symbol": strad['call_symbol'],
                "put_strike": strad['put_strike'],
                "call_strike": strad['call_strike'],
                "raw_credit": strad['total_credit'],
                "adj_credit": adj_credit,
                "expiration": strad['expiration'],
                "last_put": strad['put_price'],
                "last_call": strad['call_price'],
                "days_stale": 0,
            })

        # 3. Daily P&L = change in portfolio value + realized
        today_value = 0.0
        for pos in positions:
            cv = pos['last_put'] + pos['last_call']
            today_value += (pos['adj_credit'] - cv) * 100

        daily_change = (today_value - prev_portfolio_value) + realized_today
        prev_portfolio_value = today_value
        daily_pnl_list.append((date, daily_change, len(positions)))

    # Close remaining
    for pos in positions:
        cv = pos['last_put'] + pos['last_call']
        pnl = (pos['adj_credit'] - cv * (1 + slippage_pct)) * 100
        closed_trades.append({
            "ticker": pos['ticker'],
            "entry_date": str(pos['entry_date'])[:10],
            "exit_date": str(all_dates[-1])[:10],
            "exit_reason": "end_of_data",
            "raw_credit": round(pos['raw_credit'] * 100, 2),
            "pnl": round(pnl, 2),
            "days_held": (all_dates[-1] - pos['entry_date']).days,
            "put_strike": pos['put_strike'],
            "call_strike": pos['call_strike'],
        })

    # Report
    total_checks = reprice_stats["found"] + reprice_stats["missing"]
    miss_pct = reprice_stats["missing"] / total_checks * 100 if total_checks > 0 else 0

    return closed_trades, daily_pnl_list, {
        "reprice_found": reprice_stats["found"],
        "reprice_missing": reprice_stats["missing"],
        "reprice_miss_pct": round(miss_pct, 1),
        "skipped_at_limit": skipped,
    }


def analyze(daily_pnl, closed_trades, capital=100000):
    """Compute metrics. SANITY CHECKS per lessons.md."""
    pnls = np.array([d[1] for d in daily_pnl])
    n_pos = [d[2] for d in daily_pnl]
    trade_pnls = [t['pnl'] for t in closed_trades]

    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    max_dd = (cum - peak).min()

    sharpe = pnls.mean() / pnls.std() * np.sqrt(252) if pnls.std() > 0 else 0

    # SANITY CHECK 1: sum(daily) ≈ sum(trades)
    daily_total = float(cum[-1]) if len(cum) > 0 else 0
    trade_total = sum(trade_pnls)
    pnl_divergence = abs(daily_total - trade_total) / max(abs(trade_total), 1) * 100

    # SANITY CHECK 2: max loss < capital
    max_loss_ok = max_dd > -capital

    # SANITY CHECK 3: Sharpe < 3
    sharpe_suspicious = sharpe > 3.0 and len(closed_trades) > 50

    n = len(trade_pnls)
    wins = sum(1 for p in trade_pnls if p > 0)

    return {
        "n_days": len(pnls),
        "n_trades": n,
        "win_rate": round(wins / n * 100, 1) if n > 0 else 0,
        "total_pnl": round(daily_total, 2),
        "sharpe": round(float(sharpe), 3),
        "max_dd": round(float(max_dd), 2),
        "max_dd_pct": round(float(max_dd / capital * 100), 1),
        "avg_positions": round(float(np.mean(n_pos)), 1),
        "avg_trade_pnl": round(float(np.mean(trade_pnls)), 2) if trade_pnls else 0,
        "sanity_pnl_divergence": round(pnl_divergence, 1),
        "sanity_max_loss_ok": max_loss_ok,
        "sanity_sharpe_suspicious": sharpe_suspicious,
    }


def holdout_and_bootstrap(daily_pnl, capital=100000):
    """Holdout + bootstrap on daily returns."""
    pnls = np.array([d[1] for d in daily_pnl])
    returns = pnls / capital

    # Holdout
    s = int(len(returns) * 0.8)
    train, test = returns[:s], returns[s:]
    ho = {"error": f"Only {len(test)} test days"} if len(test) < 50 else {
        "train_sharpe": round(float(train.mean() / train.std() * np.sqrt(252)) if train.std() > 0 else 0, 3),
        "test_sharpe": round(float(test.mean() / test.std() * np.sqrt(252)) if test.std() > 0 else 0, 3),
    }
    if 'train_sharpe' in ho and ho['train_sharpe'] != 0:
        ho['ratio'] = round(ho['test_sharpe'] / ho['train_sharpe'], 3)
        ho['passed'] = ho['ratio'] > 0.5 and test.mean() > 0
    elif 'train_sharpe' in ho:
        ho['ratio'] = 0
        ho['passed'] = False

    # Bootstrap
    np.random.seed(42)
    sharpes = []
    for _ in range(1000):
        sample = np.random.choice(returns, size=len(returns), replace=True)
        if sample.std() > 0:
            sharpes.append(sample.mean() / sample.std() * np.sqrt(252))
    bs = {
        "ci_lower": round(float(np.percentile(sharpes, 2.5)), 3) if sharpes else 0,
        "ci_upper": round(float(np.percentile(sharpes, 97.5)), 3) if sharpes else 0,
        "prob_neg": round(float(np.mean([s < 0 for s in sharpes]) * 100), 1),
    }

    return ho, bs


def main():
    print("=" * 70)
    print("EXPERIMENT 005: Straddles on Dad's Stocks")
    print("CONSTRAINT: Only AAPL, DIS, TXN, TMUS, KKR")
    print("Pre-registered: 2026-03-24")
    print("=" * 70)

    tickers = ['AAPL', 'DIS', 'TXN', 'TMUS', 'KKR']

    print("\nLoading data...")
    option_data = {}
    stock_data = {}
    for t in tickers:
        od = load_option_data(t)
        sd = load_stock_data(t)
        if not od.empty and not sd.empty:
            option_data[t] = od
            stock_data[t] = sd
            print(f"  {t}: {len(od):,} options, {len(sd)} stock days")

    available = list(option_data.keys())
    all_results = []

    # --- VARIANT 1: Weekly straddle, all tickers ---
    for label, dte_range, tp in [
        ("Weekly straddle, TP=50%", (3, 10), 0.50),
        ("Weekly straddle, TP=25%", (3, 10), 0.25),
        ("Weekly straddle, hold", (3, 10), 1.0),
        ("Monthly straddle, TP=50%", (15, 45), 0.50),
        ("Weekly strangle 5% OTM, TP=50%", (3, 10), 0.50),
    ]:
        otm = 0.05 if "strangle" in label else 0
        min_d, max_d = dte_range

        print(f"\n{'=' * 50}")
        print(f"  {label}")
        print(f"{'=' * 50}")

        trades, daily, stats = backtest_straddles(
            available, option_data, stock_data,
            otm_pct=otm, min_dte=min_d, max_dte=max_d,
            take_profit_pct=tp, slippage_pct=0.05,
        )
        m = analyze(daily, trades)
        ho, bs = holdout_and_bootstrap(daily)

        print(f"  Trades: {m['n_trades']}, Win: {m['win_rate']}%")
        print(f"  Total P&L: ${m['total_pnl']:+,.2f}, Sharpe: {m['sharpe']}")
        print(f"  Max DD: {m['max_dd_pct']:.1f}%, Avg positions: {m['avg_positions']}")
        print(f"  Repricing missing: {stats['reprice_miss_pct']:.0f}%, Skipped: {stats['skipped_at_limit']}")
        print(f"  SANITY: P&L divergence={m['sanity_pnl_divergence']:.1f}%, "
              f"MaxLoss OK={m['sanity_max_loss_ok']}, Sharpe suspicious={m['sanity_sharpe_suspicious']}")
        if 'error' not in ho:
            print(f"  Holdout: train={ho['train_sharpe']}, test={ho['test_sharpe']}, "
                  f"ratio={ho.get('ratio','N/A')} {'PASS' if ho.get('passed') else 'FAIL'}")
        print(f"  Bootstrap: Sharpe CI [{bs['ci_lower']}, {bs['ci_upper']}], P(neg)={bs['prob_neg']}%")

        # Per-ticker breakdown
        for t in available:
            t_trades = [tr for tr in trades if tr['ticker'] == t]
            if t_trades:
                t_pnl = sum(tr['pnl'] for tr in t_trades)
                t_wins = sum(1 for tr in t_trades if tr['pnl'] > 0)
                print(f"    {t}: {len(t_trades)} trades, ${t_pnl:+,.0f}, "
                      f"win={t_wins/len(t_trades)*100:.0f}%")

        all_results.append({
            "label": label, "metrics": m, "holdout": ho,
            "bootstrap": bs, "stats": stats,
        })

    # --- VARIANT: AAPL + DIS only (liquid only) ---
    print(f"\n{'=' * 50}")
    print(f"  AAPL + DIS only (liquid), weekly straddle, TP=50%")
    print(f"{'=' * 50}")

    trades, daily, stats = backtest_straddles(
        ['AAPL', 'DIS'], option_data, stock_data,
        min_dte=3, max_dte=10, take_profit_pct=0.50,
    )
    m = analyze(daily, trades)
    ho, bs = holdout_and_bootstrap(daily)
    print(f"  Trades: {m['n_trades']}, Win: {m['win_rate']}%, P&L: ${m['total_pnl']:+,.2f}, Sharpe: {m['sharpe']}")
    if 'error' not in ho:
        print(f"  Holdout: ratio={ho.get('ratio','N/A')} {'PASS' if ho.get('passed') else 'FAIL'}")
    print(f"  Bootstrap: CI [{bs['ci_lower']}, {bs['ci_upper']}], P(neg)={bs['prob_neg']}%")

    all_results.append({
        "label": "AAPL+DIS liquid only", "metrics": m,
        "holdout": ho, "bootstrap": bs, "stats": stats,
    })

    # --- SUMMARY ---
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    print(f"{'Variant':<40s} {'Trades':>6s} {'Win%':>6s} {'P&L':>10s} {'Sharpe':>7s} {'DD%':>6s}")
    print("-" * 80)
    for r in all_results:
        m = r['metrics']
        print(f"{r['label']:<40s} {m['n_trades']:>6d} {m['win_rate']:>5.1f}% "
              f"${m['total_pnl']:>+9,.0f} {m['sharpe']:>6.3f} {m['max_dd_pct']:>5.1f}%")

    # Pass/fail
    best = max(all_results, key=lambda r: r['metrics']['sharpe'])
    h44_pass = best['metrics']['sharpe'] > 0.3
    print(f"\nBest variant: {best['label']} (Sharpe {best['metrics']['sharpe']})")
    print(f"H44 (Sharpe > 0.3): {'PASSED' if h44_pass else 'FAILED'}")

    if h44_pass:
        print("\nSTRADDLES ON DAD'S STOCKS SHOW PROMISE. Paper trade to validate.")
    else:
        print("\nSTRADDLES ALSO FAIL THRESHOLD.")
        print("VRP harvesting via options on individual stocks may not be viable.")

    # Save
    out = os.path.join(os.path.dirname(__file__), "results.json")
    with open(out, "w") as f:
        json.dump(all_results, f, indent=2, default=str)


if __name__ == "__main__":
    main()
