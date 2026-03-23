"""
Experiment 002: Put Spread Backtest with REAL Option Prices

Pre-registered: 2026-03-23 (H35-H39)
Data: 3.6M rows of real option OHLCV from Databento

This is the definitive test: does the put spread strategy make money
after real-world friction?

Usage:
  python experiments/002_put_spread_real_prices/run.py
"""

import os
import sys
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
import pandas as pd
import databento as db


# ============================================================
# DATA LOADING
# ============================================================

def load_option_data(ticker):
    """Load Databento option OHLCV data for a ticker."""
    raw_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'databento', 'raw')

    # Find all files for this ticker
    files = sorted([f for f in os.listdir(raw_dir)
                     if f.startswith(f'{ticker}_ohlcv') and f.endswith('.dbn.zst')])
    if not files:
        return pd.DataFrame()

    dfs = []
    for f in files:
        path = os.path.join(raw_dir, f)
        data = db.DBNStore.from_file(path)
        df = data.to_df()
        dfs.append(df)

    combined = pd.concat(dfs).sort_index()
    # Remove duplicates (overlapping date ranges)
    combined = combined[~combined.index.duplicated(keep='first')]
    return combined


def load_stock_data(ticker, period="2y"):
    """Load stock OHLCV from Yahoo Finance."""
    try:
        import yfinance as yf
        hist = yf.download(ticker, period=period, progress=False)
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        return hist
    except Exception:
        return pd.DataFrame()


# ============================================================
# SIGNAL GENERATION
# ============================================================

def compute_signals(stock_hist, window=20, iv_rv_ratio=1.2):
    """Compute GREEN/YELLOW/RED signals from stock history."""
    close = stock_hist["Close"].values
    log_ret = np.log(close[1:] / close[:-1])

    rv = pd.Series(log_ret).rolling(window).std().values * np.sqrt(252) * 100
    iv_proxy = rv * iv_rv_ratio
    vrp = iv_proxy - rv  # always positive by construction with fixed ratio

    # But use actual VRP threshold logic
    iv_q30 = np.nanpercentile(iv_proxy, 30)

    signals = []
    for i in range(len(rv)):
        if np.isnan(rv[i]) or np.isnan(iv_proxy[i]):
            signals.append("SKIP")
            continue
        v = iv_proxy[i] - rv[i]
        if v > 2 and iv_proxy[i] > iv_q30:
            signals.append("GREEN")
        elif v > 0:
            signals.append("YELLOW")
        else:
            signals.append("RED")

    # Align with stock dates (log returns start at index 1)
    dates = stock_hist.index[1:]
    return pd.DataFrame({
        "date": dates[:len(signals)],
        "close": close[1:len(signals) + 1],
        "rv": rv[:len(signals)],
        "iv_proxy": iv_proxy[:len(signals)],
        "vrp": (iv_proxy - rv)[:len(signals)],
        "signal": signals,
    }).set_index("date")


# ============================================================
# SPREAD FINDING
# ============================================================

def find_put_spread(option_df, date, spot, sell_otm_pct=0.05, buy_otm_pct=0.10,
                     min_dte=15, max_dte=45):
    """
    Find a bull put spread from real option data on a given date.

    Args:
        option_df: Databento option OHLCV DataFrame (indexed by datetime)
        date: The trade date
        spot: Current stock price
        sell_otm_pct: How far OTM the sell leg is (0.05 = 5%)
        buy_otm_pct: How far OTM the buy leg is (0.10 = 10%)
        min_dte/max_dte: Expiration range

    Returns:
        dict with spread details or None
    """
    # Filter to this date
    date_str = pd.Timestamp(date).normalize()
    day_data = option_df[option_df.index.normalize() == date_str]

    if day_data.empty:
        return None

    # Filter to puts only (symbol contains 'P' in the right position)
    # Databento symbols: 'AAPL  260417P00240000' — P at position 12-ish
    puts = day_data[day_data['symbol'].str.contains('P', na=False)].copy()
    if puts.empty:
        return None

    # Parse strike and expiry from symbol
    # Format: 'ROOT  YYMMDDP/CSSSSSSSS' (padded)
    def parse_symbol(sym):
        sym = str(sym).strip()
        # Find P or C
        for i, c in enumerate(sym):
            if c == 'P' and i > 4:
                try:
                    date_part = sym[max(0, i - 6):i]
                    strike_part = sym[i + 1:]
                    exp = datetime.strptime('20' + date_part, '%Y%m%d')
                    strike = float(strike_part) / 1000
                    return exp, strike
                except Exception:
                    pass
        return None, None

    exps = []
    strikes = []
    for sym in puts['symbol']:
        e, s = parse_symbol(sym)
        exps.append(e)
        strikes.append(s)

    puts = puts.copy()
    puts['expiration'] = exps
    puts['strike'] = strikes
    puts = puts.dropna(subset=['expiration', 'strike'])

    if puts.empty:
        return None

    # Filter to target DTE range
    trade_date = pd.Timestamp(date)
    puts['dte'] = (puts['expiration'] - trade_date).dt.days
    puts = puts[(puts['dte'] >= min_dte) & (puts['dte'] <= max_dte)]

    if puts.empty:
        return None

    # Pick the nearest monthly expiration
    target_dte = 25  # ~1 month
    puts['dte_dist'] = abs(puts['dte'] - target_dte)
    best_exp = puts.loc[puts['dte_dist'].idxmin(), 'expiration']
    exp_puts = puts[puts['expiration'] == best_exp]

    # Sell leg: nearest to sell_otm_pct below spot
    sell_target = spot * (1 - sell_otm_pct)
    exp_puts = exp_puts.copy()
    exp_puts['sell_dist'] = abs(exp_puts['strike'] - sell_target)
    sell_row = exp_puts.loc[exp_puts['sell_dist'].idxmin()]

    # Buy leg: nearest to buy_otm_pct below spot
    buy_target = spot * (1 - buy_otm_pct)
    buy_candidates = exp_puts[exp_puts['strike'] < sell_row['strike']]
    if buy_candidates.empty:
        return None
    buy_candidates = buy_candidates.copy()
    buy_candidates['buy_dist'] = abs(buy_candidates['strike'] - buy_target)
    buy_row = buy_candidates.loc[buy_candidates['buy_dist'].idxmin()]

    sell_price = float(sell_row['close'])
    buy_price = float(buy_row['close'])
    credit = sell_price - buy_price

    if credit <= 0:
        return None

    return {
        "sell_strike": float(sell_row['strike']),
        "buy_strike": float(buy_row['strike']),
        "sell_symbol": str(sell_row['symbol']),
        "buy_symbol": str(buy_row['symbol']),
        "sell_price": sell_price,
        "buy_price": buy_price,
        "credit": credit,
        "expiration": best_exp,
        "dte": int(sell_row['dte']),
        "spread_width": float(sell_row['strike'] - buy_row['strike']),
    }


def reprice_spread(option_df, date, sell_symbol, buy_symbol):
    """Get current spread value from real option data on a given date."""
    date_str = pd.Timestamp(date).normalize()
    day_data = option_df[option_df.index.normalize() == date_str]

    if day_data.empty:
        return None

    sell_data = day_data[day_data['symbol'] == sell_symbol]
    buy_data = day_data[day_data['symbol'] == buy_symbol]

    if sell_data.empty or buy_data.empty:
        return None

    sell_close = float(sell_data['close'].iloc[0])
    buy_close = float(buy_data['close'].iloc[0])
    return sell_close - buy_close


# ============================================================
# BACKTEST ENGINE
# ============================================================

def backtest_ticker(ticker, option_df, stock_hist,
                     take_profit_pct=0.25, dte_floor=5,
                     slippage_pct=0.15, holding_period=20):
    """
    Run the full put spread backtest on one ticker using real option prices.
    """
    signals = compute_signals(stock_hist)
    green_days = signals[signals['signal'] == 'GREEN']

    trades = []
    skip_until = None

    for date, row in green_days.iterrows():
        # Don't overlap trades
        if skip_until and date < skip_until:
            continue

        spot = row['close']

        # Find spread from real data
        spread = find_put_spread(option_df, date, spot)
        if spread is None:
            continue

        # Apply entry slippage
        raw_credit = spread['credit']
        adj_credit = raw_credit * (1 - slippage_pct)

        # Take profit threshold (spread value at which we close)
        tp_value = raw_credit * (1 - take_profit_pct)

        # Track daily
        entry_date = date
        exit_date = None
        exit_reason = None
        exit_pnl = None

        for day_offset in range(1, holding_period + 1):
            check_date = date + pd.Timedelta(days=day_offset)
            dte_remaining = spread['dte'] - day_offset

            # Skip weekends
            if check_date.weekday() >= 5:
                continue

            # Reprice from real data
            current_value = reprice_spread(
                option_df, check_date,
                spread['sell_symbol'], spread['buy_symbol']
            )

            if current_value is None:
                continue  # No data for this day, skip

            # Check take profit
            if take_profit_pct < 1.0 and current_value <= tp_value:
                close_cost = current_value * (1 + slippage_pct)
                exit_pnl = (adj_credit - close_cost) * 100
                exit_date = check_date
                exit_reason = "take_profit"
                break

            # Check DTE floor
            if dte_floor > 0 and dte_remaining <= dte_floor:
                close_cost = current_value * (1 + slippage_pct)
                exit_pnl = (adj_credit - close_cost) * 100
                exit_date = check_date
                exit_reason = "dte_floor"
                break

        # If no exit triggered, settle at expiry
        if exit_pnl is None:
            # At expiry, spread value = max(0, sell_strike - stock_price) - max(0, buy_strike - stock_price)
            # We approximate by checking last available price
            final_date = entry_date + pd.Timedelta(days=holding_period)
            final_value = reprice_spread(
                option_df, final_date,
                spread['sell_symbol'], spread['buy_symbol']
            )
            if final_value is not None:
                close_cost = final_value * (1 + slippage_pct)
                exit_pnl = (adj_credit - close_cost) * 100
            else:
                # Use intrinsic value
                final_stock = stock_hist.loc[stock_hist.index >= final_date]
                if not final_stock.empty:
                    final_price = float(final_stock['Close'].iloc[0])
                    sell_intrinsic = max(0, spread['sell_strike'] - final_price)
                    buy_intrinsic = max(0, spread['buy_strike'] - final_price)
                    intrinsic_value = sell_intrinsic - buy_intrinsic
                    exit_pnl = (adj_credit - intrinsic_value) * 100
                else:
                    continue  # Can't determine outcome
            exit_date = final_date
            exit_reason = "expiry"

        trades.append({
            "ticker": ticker,
            "entry_date": str(entry_date)[:10],
            "exit_date": str(exit_date)[:10] if exit_date else None,
            "exit_reason": exit_reason,
            "spot": round(spot, 2),
            "sell_strike": spread['sell_strike'],
            "buy_strike": spread['buy_strike'],
            "spread_width": spread['spread_width'],
            "raw_credit": round(raw_credit * 100, 2),
            "adj_credit": round(adj_credit * 100, 2),
            "pnl": round(exit_pnl, 2),
            "dte": spread['dte'],
            "days_held": (exit_date - entry_date).days if exit_date else holding_period,
        })

        # Skip ahead to avoid overlapping trades
        skip_until = entry_date + pd.Timedelta(days=holding_period)

    return pd.DataFrame(trades)


# ============================================================
# ANALYSIS
# ============================================================

def analyze_results(trades_df):
    """Compute strategy metrics."""
    if trades_df.empty or len(trades_df) < 5:
        return {"error": "Too few trades"}

    pnl = trades_df['pnl']
    n = len(pnl)
    wins = (pnl > 0).sum()

    trades_per_year = 252 / trades_df['days_held'].mean() if trades_df['days_held'].mean() > 0 else 12
    sharpe = (pnl.mean() / pnl.std() * np.sqrt(trades_per_year)) if pnl.std() > 0 else 0

    downside = pnl[pnl < 0]
    down_std = downside.std() if len(downside) > 1 else pnl.std()
    sortino = (pnl.mean() / down_std * np.sqrt(trades_per_year)) if down_std > 0 else 0

    cum_pnl = pnl.cumsum()
    peak = cum_pnl.cummax()
    max_dd = (cum_pnl - peak).min()

    return {
        "n_trades": n,
        "win_rate": round(wins / n * 100, 1),
        "avg_pnl": round(float(pnl.mean()), 2),
        "total_pnl": round(float(pnl.sum()), 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "max_dd": round(float(max_dd), 2),
        "avg_days_held": round(trades_df['days_held'].mean(), 1),
        "exit_reasons": trades_df['exit_reason'].value_counts().to_dict(),
    }


def bootstrap_ci(pnl_series, n_boot=1000, ci=0.95):
    """Bootstrap confidence intervals for avg P&L and Sharpe."""
    np.random.seed(42)
    n = len(pnl_series)
    boot_means = []
    boot_sharpes = []
    boot_max_dds = []

    for _ in range(n_boot):
        sample = np.random.choice(pnl_series, size=n, replace=True)
        boot_means.append(sample.mean())
        if sample.std() > 0:
            boot_sharpes.append(sample.mean() / sample.std() * np.sqrt(12))
        boot_max_dds.append(np.cumsum(sample).min() - np.maximum.accumulate(np.cumsum(sample)).max())

    alpha = (1 - ci) / 2
    return {
        "mean_ci_lower": round(float(np.percentile(boot_means, alpha * 100)), 2),
        "mean_ci_upper": round(float(np.percentile(boot_means, (1 - alpha) * 100)), 2),
        "sharpe_ci_lower": round(float(np.percentile(boot_sharpes, alpha * 100)), 3) if boot_sharpes else 0,
        "sharpe_ci_upper": round(float(np.percentile(boot_sharpes, (1 - alpha) * 100)), 3) if boot_sharpes else 0,
        "prob_negative_mean": round(float(np.mean([m < 0 for m in boot_means]) * 100), 1),
        "prob_ruin_20pct": round(float(np.mean([d < -20 for d in boot_max_dds]) * 100), 1),
    }


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("EXPERIMENT 002: Put Spread Backtest with REAL Option Prices")
    print("Pre-registered: 2026-03-23 (H35-H39)")
    print("=" * 70)
    print()

    tickers = ['AAPL', 'DIS', 'TXN', 'TMUS', 'KKR']
    all_trades = []

    for ticker in tickers:
        print(f"\n{'=' * 50}")
        print(f"{ticker}")
        print(f"{'=' * 50}")

        # Load data
        print(f"  Loading Databento option data...", flush=True)
        option_df = load_option_data(ticker)
        if option_df.empty:
            print(f"  No option data found. Skipping.")
            continue
        print(f"  {len(option_df):,} option price rows")

        print(f"  Loading stock history...", flush=True)
        stock_hist = load_stock_data(ticker)
        if stock_hist.empty:
            print(f"  No stock data. Skipping.")
            continue
        print(f"  {len(stock_hist)} stock days")

        # Run backtest
        print(f"  Running backtest...", flush=True)
        trades = backtest_ticker(ticker, option_df, stock_hist)
        print(f"  {len(trades)} trades generated")

        if not trades.empty:
            metrics = analyze_results(trades)
            print(f"  Win rate: {metrics['win_rate']}%")
            print(f"  Avg P&L: ${metrics['avg_pnl']}")
            print(f"  Sharpe: {metrics['sharpe']}")
            print(f"  Max DD: ${metrics['max_dd']}")
            print(f"  Exits: {metrics['exit_reasons']}")
            all_trades.append(trades)

    if not all_trades:
        print("\nNo trades generated across any ticker. Check data.")
        return

    # Combine all trades
    combined = pd.concat(all_trades, ignore_index=True)
    print(f"\n{'=' * 70}")
    print(f"COMBINED RESULTS ({len(combined)} trades across {len(all_trades)} tickers)")
    print(f"{'=' * 70}")

    overall = analyze_results(combined)
    for k, v in overall.items():
        print(f"  {k}: {v}")

    # H35: Is it profitable?
    print(f"\n--- H35: Profitable with real prices? ---")
    h35_pass = overall['avg_pnl'] > 0 and overall['sharpe'] > 0.3
    print(f"  Avg P&L: ${overall['avg_pnl']} ({'> $0' if overall['avg_pnl'] > 0 else '<= $0'})")
    print(f"  Sharpe: {overall['sharpe']} ({'> 0.3' if overall['sharpe'] > 0.3 else '<= 0.3'})")
    print(f"  H35: {'PASSED' if h35_pass else 'FAILED'}")

    # H37: Is 25% TP still optimal?
    print(f"\n--- H37: 25% TP still optimal? ---")
    for tp in [0.25, 0.50, 0.75, 1.0]:
        tp_trades = []
        for ticker in tickers:
            option_df = load_option_data(ticker)
            stock_hist = load_stock_data(ticker)
            if option_df.empty or stock_hist.empty:
                continue
            t = backtest_ticker(ticker, option_df, stock_hist, take_profit_pct=tp)
            if not t.empty:
                tp_trades.append(t)
        if tp_trades:
            tp_combined = pd.concat(tp_trades, ignore_index=True)
            tp_metrics = analyze_results(tp_combined)
            print(f"  TP={tp:.0%}: avg P&L=${tp_metrics['avg_pnl']}, "
                  f"Sortino={tp_metrics['sortino']}, n={tp_metrics['n_trades']}")

    # H38: Holdout validation
    print(f"\n--- H38: Holdout validation ---")
    split = int(len(combined) * 0.8)
    train = combined.iloc[:split]
    test = combined.iloc[split:]
    train_metrics = analyze_results(train)
    test_metrics = analyze_results(test)
    holdout_ratio = test_metrics['sharpe'] / train_metrics['sharpe'] if train_metrics['sharpe'] != 0 else 0
    h38_pass = holdout_ratio > 0.5 and test_metrics['avg_pnl'] > 0
    print(f"  Train Sharpe: {train_metrics['sharpe']}, Test Sharpe: {test_metrics['sharpe']}")
    print(f"  Ratio: {holdout_ratio:.2f} ({'> 0.5' if holdout_ratio > 0.5 else '<= 0.5'})")
    print(f"  Test avg P&L: ${test_metrics['avg_pnl']}")
    print(f"  H38: {'PASSED' if h38_pass else 'FAILED'}")

    # H39: Bootstrap
    print(f"\n--- H39: Bootstrap stress test ---")
    boot = bootstrap_ci(combined['pnl'].values)
    h39_pass = boot['mean_ci_lower'] > 0 and boot['prob_ruin_20pct'] < 5
    print(f"  95% CI for avg P&L: [${boot['mean_ci_lower']}, ${boot['mean_ci_upper']}]")
    print(f"  P(negative avg P&L): {boot['prob_negative_mean']}%")
    print(f"  P(ruin >20% DD): {boot['prob_ruin_20pct']}%")
    print(f"  H39: {'PASSED' if h39_pass else 'FAILED'}")

    # Summary
    print(f"\n{'=' * 70}")
    print(f"EXPERIMENT 002 SUMMARY")
    print(f"{'=' * 70}")
    print(f"  H35 (Profitable): {'PASSED' if h35_pass else 'FAILED'}")
    print(f"  H38 (Holdout):    {'PASSED' if h38_pass else 'FAILED'}")
    print(f"  H39 (Bootstrap):  {'PASSED' if h39_pass else 'FAILED'}")

    if h35_pass and h38_pass and h39_pass:
        print(f"\n  ALL CORE HYPOTHESES PASSED.")
        print(f"  The put spread strategy survives real-world pricing.")
        print(f"  Proceed to paper trading.")
    else:
        failed = []
        if not h35_pass: failed.append("H35 (not profitable)")
        if not h38_pass: failed.append("H38 (holdout fails)")
        if not h39_pass: failed.append("H39 (ruin risk)")
        print(f"\n  FAILED: {', '.join(failed)}")
        print(f"  DO NOT proceed to real money until failures are resolved.")

    # Save results
    output = {
        "overall": overall,
        "h35_passed": h35_pass,
        "h38_passed": h38_pass,
        "h39_passed": h39_pass,
        "bootstrap": boot,
        "holdout_ratio": holdout_ratio,
        "trades": combined.to_dict("records"),
    }
    results_path = os.path.join(os.path.dirname(__file__), "results.json")
    with open(results_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to {results_path}")


if __name__ == "__main__":
    main()
