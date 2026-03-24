"""
Experiment 003: AAPL-Only Strategy Validation

Pre-registered: 2026-03-23 (H40-H43)

Tests AAPL put spreads AND cash-secured puts with real Databento prices.
AAPL was the only profitable ticker in Exp 002 (Sharpe 1.5, 87.5% win rate).

Also grid-searches:
- Take-profit levels (25%, 50%, 75%, hold-to-expiry)
- VRP thresholds (>2, >5, >8)
- Spread width (5%, 10%, 15% OTM for buy leg)
- CSP vs spread (single leg vs two legs)
"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
import pandas as pd
import databento as db


def load_aapl_options():
    """Load AAPL Databento data."""
    path = 'data/databento/raw/AAPL_ohlcv_1d.dbn.zst'
    if not os.path.exists(path):
        path = os.path.join(os.path.dirname(__file__), '..', '..', path)
    data = db.DBNStore.from_file(path)
    df = data.to_df()
    return df


def load_aapl_stock():
    """Load AAPL stock OHLCV."""
    try:
        import yfinance as yf
        hist = yf.download('AAPL', period='2y', progress=False)
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        return hist
    except Exception:
        return pd.DataFrame()


def compute_signals(stock_hist, window=20, iv_rv_ratio=1.2):
    """Compute GREEN/YELLOW/RED signals."""
    close = stock_hist["Close"].values
    log_ret = np.log(close[1:] / close[:-1])
    rv = pd.Series(log_ret).rolling(window).std().values * np.sqrt(252) * 100
    iv_proxy = rv * iv_rv_ratio
    iv_q30 = np.nanpercentile(iv_proxy, 30)

    signals = []
    for i in range(len(rv)):
        if np.isnan(rv[i]) or np.isnan(iv_proxy[i]):
            signals.append(("SKIP", 0))
            continue
        vrp = iv_proxy[i] - rv[i]
        if vrp > 2 and iv_proxy[i] > iv_q30:
            signals.append(("GREEN", vrp))
        elif vrp > 0:
            signals.append(("YELLOW", vrp))
        else:
            signals.append(("RED", vrp))

    dates = stock_hist.index[1:]
    return pd.DataFrame({
        "date": dates[:len(signals)],
        "close": close[1:len(signals) + 1],
        "signal": [s[0] for s in signals],
        "vrp": [s[1] for s in signals],
    }).set_index("date")


def find_put(option_df, date, spot, otm_pct, min_dte=15, max_dte=45):
    """Find a specific put from real data."""
    import re
    date_ts = pd.Timestamp(date).normalize()
    if option_df.index.tz is not None:
        date_ts = date_ts.tz_localize(option_df.index.tz)
    day_data = option_df[option_df.index.normalize() == date_ts]
    if day_data.empty:
        return None

    day_agg = day_data.groupby('symbol').agg({
        'close': 'mean', 'volume': 'sum'
    }).reset_index()

    puts = day_agg[day_agg['symbol'].str.match(r'.*\d{6}P\d+')].copy()
    if puts.empty:
        return None

    def parse_sym(sym):
        m = re.search(r'(\d{6})P(\d{8})', str(sym).strip())
        if m:
            try:
                from datetime import datetime
                exp = datetime.strptime('20' + m.group(1), '%Y%m%d')
                strike = float(m.group(2)) / 1000
                return exp, strike
            except Exception:
                pass
        return None, None

    parsed = puts['symbol'].apply(lambda s: pd.Series(parse_sym(s), index=['expiration', 'strike']))
    puts = pd.concat([puts, parsed], axis=1).dropna(subset=['expiration', 'strike'])
    if puts.empty:
        return None

    trade_date = pd.Timestamp(date)
    puts['dte'] = (puts['expiration'] - trade_date).dt.days
    puts = puts[(puts['dte'] >= min_dte) & (puts['dte'] <= max_dte)]
    if puts.empty:
        return None

    # Nearest monthly expiry ~25 DTE
    puts['dte_dist'] = abs(puts['dte'] - 25)
    best_exp = puts.loc[puts['dte_dist'].idxmin(), 'expiration']
    exp_puts = puts[puts['expiration'] == best_exp]

    # Target strike
    target = spot * (1 - otm_pct)
    exp_puts = exp_puts.copy()
    exp_puts['dist'] = abs(exp_puts['strike'] - target)
    best = exp_puts.loc[exp_puts['dist'].idxmin()]

    return {
        "symbol": str(best['symbol']),
        "strike": float(best['strike']),
        "price": float(best['close']),
        "dte": int(best['dte']),
        "expiration": best['expiration'],
    }


def reprice(option_df, date, symbol):
    """Get option price on a date. Returns (price, found) tuple."""
    date_ts = pd.Timestamp(date).normalize()
    if option_df.index.tz is not None:
        date_ts = date_ts.tz_localize(option_df.index.tz)
    day_data = option_df[option_df.index.normalize() == date_ts]
    if day_data.empty:
        return None, False
    match = day_data[day_data['symbol'] == symbol]
    if match.empty:
        return None, False
    return float(match['close'].mean()), True


def backtest_aapl(option_df, stock_hist,
                   mode="spread",  # "spread" or "csp"
                   sell_otm_pct=0.05,
                   buy_otm_pct=0.10,  # ignored for csp
                   take_profit_pct=0.25,
                   dte_floor=5,
                   slippage_pct=0.05,  # AAPL-appropriate (not 15%)
                   min_vrp=2.0,
                   trade_skip_days=5):
    """
    Backtest AAPL put spread or cash-secured put.
    """
    signals = compute_signals(stock_hist)
    green_days = signals[(signals['signal'] == 'GREEN') & (signals['vrp'] >= min_vrp)]

    trades = []
    skip_until = None
    reprice_stats = {"found": 0, "missing": 0}

    for date, row in green_days.iterrows():
        if skip_until and date < skip_until:
            continue

        spot = row['close']

        # Find sell put
        sell_put = find_put(option_df, date, spot, sell_otm_pct)
        if sell_put is None:
            continue

        # Find buy put (for spread mode)
        buy_put = None
        if mode == "spread":
            buy_put = find_put(option_df, date, spot, buy_otm_pct)
            if buy_put is None:
                continue
            if buy_put['strike'] >= sell_put['strike']:
                continue

        # Compute credit
        if mode == "spread":
            raw_credit = sell_put['price'] - buy_put['price']
        else:
            raw_credit = sell_put['price']

        if raw_credit <= 0:
            continue

        adj_credit = raw_credit * (1 - slippage_pct)
        tp_value = raw_credit * (1 - take_profit_pct)

        # Track trade
        entry_date = date
        exit_date = None
        exit_reason = None
        exit_pnl = None
        last_known_sell = sell_put['price']
        last_known_buy = buy_put['price'] if buy_put else 0
        days_since_reprice = 0
        holding_period = sell_put['dte']

        for day_offset in range(1, holding_period + 5):
            check_date = date + pd.Timedelta(days=day_offset)
            dte_remaining = sell_put['dte'] - day_offset

            if check_date.weekday() >= 5:
                continue

            # DTE floor FIRST (priority)
            if dte_floor > 0 and dte_remaining <= dte_floor:
                if mode == "spread":
                    spread_val = last_known_sell - last_known_buy
                else:
                    spread_val = last_known_sell
                close_cost = spread_val * (1 + slippage_pct)
                exit_pnl = (adj_credit - close_cost) * 100
                exit_date = check_date
                exit_reason = "dte_floor"
                break

            # Reprice
            sell_price, sell_found = reprice(option_df, check_date, sell_put['symbol'])
            if sell_found:
                last_known_sell = sell_price
                reprice_stats["found"] += 1
                days_since_reprice = 0
            else:
                reprice_stats["missing"] += 1
                days_since_reprice += 1
                sell_price = last_known_sell

            buy_price = 0
            if mode == "spread" and buy_put:
                bp, bf = reprice(option_df, check_date, buy_put['symbol'])
                if bf:
                    last_known_buy = bp
                    buy_price = bp
                else:
                    buy_price = last_known_buy

            if mode == "spread":
                current_value = sell_price - buy_price
            else:
                current_value = sell_price

            # Stale data exit
            if days_since_reprice >= 5:
                close_cost = current_value * (1 + slippage_pct)
                exit_pnl = (adj_credit - close_cost) * 100
                exit_date = check_date
                exit_reason = "stale_data_exit"
                break

            # Take profit
            if take_profit_pct < 1.0 and current_value <= tp_value:
                close_cost = current_value * (1 + slippage_pct)
                exit_pnl = (adj_credit - close_cost) * 100
                exit_date = check_date
                exit_reason = "take_profit"
                break

        # Settle at expiry if no exit
        if exit_pnl is None:
            final_date = entry_date + pd.Timedelta(days=holding_period)
            final_stock = stock_hist.loc[stock_hist.index >= final_date]
            if not final_stock.empty:
                final_price = float(final_stock['Close'].iloc[0])
                sell_intrinsic = max(0, sell_put['strike'] - final_price)
                buy_intrinsic = max(0, buy_put['strike'] - final_price) if buy_put else 0
                if mode == "spread":
                    intrinsic = sell_intrinsic - buy_intrinsic
                else:
                    intrinsic = sell_intrinsic
                exit_pnl = (adj_credit - intrinsic * (1 + slippage_pct)) * 100
            else:
                exit_pnl = (adj_credit - last_known_sell * (1 + slippage_pct)) * 100
            exit_date = final_date
            exit_reason = "expiry"

        width = (sell_put['strike'] - buy_put['strike']) if buy_put else sell_put['strike']

        trades.append({
            "mode": mode,
            "entry_date": str(entry_date)[:10],
            "exit_date": str(exit_date)[:10] if exit_date else None,
            "exit_reason": exit_reason,
            "spot": round(spot, 2),
            "sell_strike": sell_put['strike'],
            "buy_strike": buy_put['strike'] if buy_put else 0,
            "width": round(width, 2),
            "raw_credit": round(raw_credit * 100, 2),
            "adj_credit": round(adj_credit * 100, 2),
            "pnl": round(exit_pnl, 2),
            "days_held": (exit_date - entry_date).days if exit_date else holding_period,
            "vrp_at_entry": round(row['vrp'], 2),
            "slippage_pct": slippage_pct,
            "tp_pct": take_profit_pct,
            "min_vrp": min_vrp,
        })

        skip_until = entry_date + pd.Timedelta(days=trade_skip_days)

    # Report
    total = reprice_stats["found"] + reprice_stats["missing"]
    if total > 0:
        miss = reprice_stats["missing"] / total * 100
        print(f"    Repricing: {reprice_stats['found']} found, {reprice_stats['missing']} missing ({miss:.0f}%)")

    return pd.DataFrame(trades)


def analyze(df, label=""):
    """Compute metrics."""
    if df.empty or len(df) < 3:
        return None
    pnl = df['pnl']
    n = len(pnl)
    tpy = 252 / max(df['days_held'].mean(), 1)
    sharpe = pnl.mean() / pnl.std() * np.sqrt(tpy) if pnl.std() > 0 else 0
    down = pnl[pnl < 0]
    down_std = down.std() if len(down) > 1 else pnl.std()
    sortino = pnl.mean() / down_std * np.sqrt(tpy) if down_std > 0 else 0
    cum = pnl.cumsum()
    max_dd = (cum - cum.cummax()).min()

    return {
        "label": label,
        "n": n,
        "win_rate": round((pnl > 0).sum() / n * 100, 1),
        "avg_pnl": round(float(pnl.mean()), 2),
        "total_pnl": round(float(pnl.sum()), 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "max_dd": round(float(max_dd), 2),
        "avg_days": round(df['days_held'].mean(), 1),
        "exits": df['exit_reason'].value_counts().to_dict(),
    }


def bootstrap_ci(pnl, n_boot=1000):
    """Bootstrap confidence intervals."""
    np.random.seed(42)
    means = [np.random.choice(pnl, size=len(pnl), replace=True).mean() for _ in range(n_boot)]
    dds = []
    for _ in range(n_boot):
        s = np.random.choice(pnl, size=len(pnl), replace=True)
        c = np.cumsum(s)
        dds.append((c - np.maximum.accumulate(c)).min())
    return {
        "ci_lower": round(float(np.percentile(means, 2.5)), 2),
        "ci_upper": round(float(np.percentile(means, 97.5)), 2),
        "prob_negative": round(float(np.mean([m < 0 for m in means]) * 100), 1),
        "prob_ruin": round(float(np.mean([d < -500 for d in dds]) * 100), 1),
    }


def main():
    print("=" * 70)
    print("EXPERIMENT 003: AAPL-Only Strategy Validation")
    print("Pre-registered: 2026-03-23 (H40-H43)")
    print("=" * 70)

    print("\nLoading data...")
    option_df = load_aapl_options()
    stock_hist = load_aapl_stock()
    print(f"  Options: {len(option_df):,} rows")
    print(f"  Stock: {len(stock_hist)} days")

    # =========================================================
    # H40 + H41: Put Spread vs Cash-Secured Put
    # =========================================================
    print("\n" + "=" * 50)
    print("H40/H41: Put Spread vs Cash-Secured Put (5% slippage)")
    print("=" * 50)

    for mode_label, mode in [("Put Spread (5%/10% OTM)", "spread"), ("Cash-Secured Put (5% OTM)", "csp")]:
        print(f"\n  --- {mode_label} ---")
        trades = backtest_aapl(option_df, stock_hist, mode=mode)
        if trades.empty:
            print("    No trades.")
            continue
        m = analyze(trades, mode_label)
        print(f"    Trades: {m['n']}, Win: {m['win_rate']}%, Avg P&L: ${m['avg_pnl']}, "
              f"Sharpe: {m['sharpe']}, Max DD: ${m['max_dd']}")
        print(f"    Exits: {m['exits']}")

    # =========================================================
    # H42: VRP Threshold Grid
    # =========================================================
    print("\n" + "=" * 50)
    print("H42: VRP Threshold (higher = more selective)")
    print("=" * 50)

    for min_vrp in [2.0, 4.0, 6.0, 8.0]:
        trades = backtest_aapl(option_df, stock_hist, mode="spread", min_vrp=min_vrp)
        if trades.empty:
            print(f"  VRP>{min_vrp}: no trades")
            continue
        m = analyze(trades)
        print(f"  VRP>{min_vrp}: {m['n']} trades, Win: {m['win_rate']}%, "
              f"Avg P&L: ${m['avg_pnl']}, Sharpe: {m['sharpe']}")

    # =========================================================
    # H37 revisited: Take-Profit Grid on AAPL
    # =========================================================
    print("\n" + "=" * 50)
    print("Take-Profit Grid (AAPL spread, 5% slippage)")
    print("=" * 50)

    for tp in [0.25, 0.50, 0.75, 1.0]:
        trades = backtest_aapl(option_df, stock_hist, mode="spread", take_profit_pct=tp)
        if trades.empty:
            continue
        m = analyze(trades)
        label = f"{tp:.0%}" if tp < 1 else "hold"
        print(f"  TP={label}: {m['n']} trades, Win: {m['win_rate']}%, "
              f"Avg P&L: ${m['avg_pnl']}, Sharpe: {m['sharpe']}, Sortino: {m['sortino']}")

    # =========================================================
    # Width Grid
    # =========================================================
    print("\n" + "=" * 50)
    print("Spread Width Grid (sell 5% OTM, vary buy leg)")
    print("=" * 50)

    for buy_otm in [0.08, 0.10, 0.15, 0.20]:
        trades = backtest_aapl(option_df, stock_hist, mode="spread", buy_otm_pct=buy_otm)
        if trades.empty:
            continue
        m = analyze(trades)
        width_pct = buy_otm - 0.05
        print(f"  Width={width_pct:.0%} ({buy_otm:.0%} buy): {m['n']} trades, "
              f"Win: {m['win_rate']}%, Avg P&L: ${m['avg_pnl']}, Sharpe: {m['sharpe']}")

    # =========================================================
    # H43: Best Strategy — Holdout + Bootstrap
    # =========================================================
    print("\n" + "=" * 50)
    print("H43: Holdout + Bootstrap on Best Configuration")
    print("=" * 50)

    # Run the best config (spread, 25% TP, 5% slippage, VRP>2)
    all_trades = backtest_aapl(option_df, stock_hist, mode="spread")
    if all_trades.empty:
        print("  No trades for validation.")
        return

    overall = analyze(all_trades, "AAPL Spread Overall")
    print(f"\n  Overall: {overall['n']} trades, Win: {overall['win_rate']}%, "
          f"Avg P&L: ${overall['avg_pnl']}, Sharpe: {overall['sharpe']}")

    # H40 check
    h40_pass = overall['avg_pnl'] > 0 and overall['sharpe'] > 0.5
    print(f"\n  H40 (Profitable): {'PASSED' if h40_pass else 'FAILED'} "
          f"(P&L=${overall['avg_pnl']}, Sharpe={overall['sharpe']})")

    # Holdout
    split = int(len(all_trades) * 0.8)
    train = analyze(all_trades.iloc[:split], "Train")
    test = analyze(all_trades.iloc[split:], "Test")

    if train and test and train['sharpe'] != 0:
        ratio = test['sharpe'] / train['sharpe'] if train['sharpe'] != 0 else 0
        h38_pass = ratio > 0.5 and test['avg_pnl'] > 0
        print(f"  H43 Holdout: Train Sharpe={train['sharpe']}, Test Sharpe={test['sharpe']}, "
              f"Ratio={ratio:.2f} {'PASSED' if h38_pass else 'FAILED'}")
    else:
        h38_pass = False
        print(f"  H43 Holdout: insufficient data")

    # Bootstrap
    boot = bootstrap_ci(all_trades['pnl'].values)
    h39_pass = boot['ci_lower'] > 0 and boot['prob_ruin'] < 5
    print(f"  H43 Bootstrap: 95% CI [${boot['ci_lower']}, ${boot['ci_upper']}], "
          f"P(neg)={boot['prob_negative']}%, P(ruin)={boot['prob_ruin']}%")
    print(f"  H43 Bootstrap: {'PASSED' if h39_pass else 'FAILED'}")

    # Summary
    print("\n" + "=" * 70)
    print("EXPERIMENT 003 SUMMARY")
    print("=" * 70)
    print(f"  H40 (AAPL Profitable): {'PASSED' if h40_pass else 'FAILED'}")
    print(f"  H43 (Holdout):         {'PASSED' if h38_pass else 'FAILED'}")
    print(f"  H43 (Bootstrap):       {'PASSED' if h39_pass else 'FAILED'}")

    if h40_pass and h38_pass and h39_pass:
        print("\n  ALL HYPOTHESES PASSED. AAPL strategy is viable.")
        print("  Next: Experiment 005 (wider spreads) or paper trading.")
    elif h40_pass:
        print("\n  Strategy is profitable but validation is weak.")
        print("  Proceed to paper trading with caution.")
    else:
        print("\n  FAILED. Follow decision tree to Experiment 006 (CSP) or 008 (index).")

    # Save
    results = {
        "overall": overall,
        "h40_pass": h40_pass,
        "h43_holdout_pass": h38_pass,
        "h43_bootstrap_pass": h39_pass,
        "bootstrap": boot,
        "trades": all_trades.to_dict("records"),
    }
    out = os.path.join(os.path.dirname(__file__), "results.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    main()
