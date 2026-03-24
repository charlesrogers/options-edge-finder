"""
Experiment 005: Index Straddle Backtest (BSM Proxy)

Sinclair's actual recommendation: sell weekly straddles on SPY/QQQ/IWM.
Uses BSM pricing (ATM options where BSM is most accurate).

CAVEAT: BSM proxy. If results look good, must validate with real data.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
import pandas as pd
import json


def load_stock(ticker, period="5y"):
    """Load stock OHLCV."""
    import yfinance as yf
    hist = yf.download(ticker, period=period, progress=False)
    if isinstance(hist.columns, pd.MultiIndex):
        hist.columns = hist.columns.get_level_values(0)
    return hist


def bsm_straddle_price(spot, T, rv, iv_multiplier=1.2, r=0.045):
    """
    BSM price of an ATM straddle.

    ATM straddle ≈ spot × σ × sqrt(T) × 0.8 (simplified BSM approximation)
    This is the standard approximation used in Sinclair Ch 4.
    """
    iv = rv * iv_multiplier
    if iv <= 0 or T <= 0:
        return 0, 0
    straddle_price = spot * iv * np.sqrt(T) * 0.8
    return straddle_price, iv


def backtest_weekly_straddle(stock_hist, ticker,
                               slippage_pct=0.02,  # SPY = ultra tight
                               iv_multiplier=1.2,
                               entry_day=4,  # Friday (0=Mon)
                               holding_days=5,  # 1 week
                               skip_backwardation=False,
                               vix_data=None):
    """
    Backtest selling weekly ATM straddles on an index.

    Each week:
    1. Sell ATM straddle (call + put at spot price)
    2. Hold for 5 trading days (1 week)
    3. At expiry, P&L = premium - |stock_move|
    """
    close = stock_hist["Close"].values
    dates = stock_hist.index
    n = len(close)

    # Compute rolling RV
    log_ret = np.log(close[1:] / close[:-1])
    rv_20 = pd.Series(log_ret).rolling(20).std().values * np.sqrt(252)

    trades = []
    daily_portfolio_pnl = []
    prev_unrealized = 0.0

    open_straddle = None  # (entry_date, entry_price, straddle_premium, entry_spot)

    for i in range(25, n):
        date = dates[i]
        spot = close[i]
        rv = rv_20[i - 1] if i > 0 and i - 1 < len(rv_20) else None

        if rv is None or np.isnan(rv):
            daily_portfolio_pnl.append((date, 0.0))
            continue

        # Check if we have an open position
        realized_today = 0.0
        today_unrealized = 0.0

        if open_straddle is not None:
            entry_date, entry_price, premium, entry_spot = open_straddle
            days_held = (date - entry_date).days

            # Current straddle value = intrinsic + time value
            # At any point: straddle value ≈ |spot - strike| + remaining_time_value
            move = abs(spot - entry_spot)
            remaining_T = max(0, (holding_days - days_held)) / 252
            remaining_time_value = entry_spot * rv * iv_multiplier * np.sqrt(remaining_T) * 0.8 if remaining_T > 0 else 0
            current_value = move + remaining_time_value

            today_unrealized = (premium - current_value) * (1 - slippage_pct)

            # Check expiry (holding period elapsed)
            if days_held >= holding_days:
                # Settle: P&L = premium collected - actual move - slippage
                actual_move = abs(spot - entry_spot)
                pnl = (premium * (1 - slippage_pct)) - actual_move - (premium * slippage_pct)
                # Simpler: pnl = premium * (1 - 2*slippage) - actual_move
                pnl_per_contract = pnl  # dollar P&L per share (x100 for contract)

                trades.append({
                    "ticker": ticker,
                    "entry_date": str(entry_date)[:10],
                    "exit_date": str(date)[:10],
                    "premium": round(premium, 4),
                    "actual_move": round(actual_move, 4),
                    "pnl": round(pnl_per_contract * 100, 2),  # per contract
                    "days_held": days_held,
                    "entry_spot": round(entry_spot, 2),
                    "exit_spot": round(spot, 2),
                    "rv_at_entry": round(rv * 100, 2),
                })

                realized_today = pnl_per_contract * 100
                today_unrealized = 0.0
                open_straddle = None

        # Daily P&L = change in unrealized + realized
        daily_change = (today_unrealized - prev_unrealized) * 100 + realized_today
        prev_unrealized = today_unrealized
        daily_portfolio_pnl.append((date, daily_change))

        # Entry: sell new straddle on the designated day (if no open position)
        if open_straddle is None and date.weekday() == entry_day:
            # Check backwardation filter
            if skip_backwardation and vix_data is not None:
                # Simple proxy: RV is increasing (short-term > long-term)
                rv_5 = pd.Series(log_ret[max(0, i - 6):i]).std() * np.sqrt(252) if i > 5 else rv
                if not np.isnan(rv_5) and rv_5 > rv * 1.3:
                    continue  # Skip — short-term vol spiking

            T = holding_days / 252
            premium, iv = bsm_straddle_price(spot, T, rv, iv_multiplier)
            if premium > 0:
                open_straddle = (date, spot, premium, spot)

    return pd.DataFrame(trades), daily_portfolio_pnl


def analyze_portfolio(daily_pnl, capital=100000):
    """Compute portfolio metrics from daily P&L."""
    pnls = np.array([d[1] for d in daily_pnl])
    dates = [d[0] for d in daily_pnl]
    returns = pnls / capital

    sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    max_dd = (cum - peak).min()
    max_dd_pct = max_dd / capital * 100

    return {
        "n_days": len(pnls),
        "total_pnl": round(float(cum[-1]), 2),
        "daily_sharpe": round(float(sharpe), 3),
        "max_dd": round(float(max_dd), 2),
        "max_dd_pct": round(float(max_dd_pct), 1),
        "avg_daily_pnl": round(float(pnls.mean()), 2),
    }


def holdout(daily_pnl, capital=100000, split=0.8):
    """Calendar-day holdout."""
    pnls = np.array([d[1] for d in daily_pnl])
    returns = pnls / capital
    s = int(len(returns) * split)
    train = returns[:s]
    test = returns[s:]

    if len(test) < 50:
        return {"error": f"Only {len(test)} test days"}

    train_sharpe = train.mean() / train.std() * np.sqrt(252) if train.std() > 0 else 0
    test_sharpe = test.mean() / test.std() * np.sqrt(252) if test.std() > 0 else 0
    ratio = test_sharpe / train_sharpe if train_sharpe != 0 else 0

    return {
        "train_days": len(train),
        "test_days": len(test),
        "train_sharpe": round(float(train_sharpe), 3),
        "test_sharpe": round(float(test_sharpe), 3),
        "ratio": round(float(ratio), 3),
        "passed": ratio > 0.5 and test.mean() > 0,
    }


def bootstrap(daily_pnl, capital=100000, n_boot=1000):
    """Bootstrap on daily returns."""
    pnls = np.array([d[1] for d in daily_pnl])
    returns = pnls / capital
    np.random.seed(42)

    sharpes = []
    for _ in range(n_boot):
        s = np.random.choice(returns, size=len(returns), replace=True)
        if s.std() > 0:
            sharpes.append(s.mean() / s.std() * np.sqrt(252))

    return {
        "sharpe_ci_lower": round(float(np.percentile(sharpes, 2.5)), 3) if sharpes else 0,
        "sharpe_ci_upper": round(float(np.percentile(sharpes, 97.5)), 3) if sharpes else 0,
        "prob_sharpe_negative": round(float(np.mean([s < 0 for s in sharpes]) * 100), 1),
    }


def main():
    print("=" * 70)
    print("EXPERIMENT 005: Index Straddles (BSM Proxy)")
    print("Pre-registered: 2026-03-24 (H44-H46)")
    print("CAVEAT: BSM pricing. Results are directional, not deployable.")
    print("=" * 70)

    tickers = ["SPY", "QQQ", "IWM"]

    print("\nLoading data...")
    stock_data = {}
    for t in tickers:
        hist = load_stock(t, "5y")
        if not hist.empty:
            stock_data[t] = hist
            print(f"  {t}: {len(hist)} days")

    all_results = []

    # =========================================================
    print("\n" + "=" * 50)
    print("H44: Single-Index Weekly Straddles")
    print("=" * 50)

    for ticker in tickers:
        print(f"\n  --- {ticker} ---")
        trades, daily_pnl = backtest_weekly_straddle(stock_data[ticker], ticker)

        if trades.empty:
            print(f"    No trades")
            continue

        pm = analyze_portfolio(daily_pnl)
        ho = holdout(daily_pnl)
        bs = bootstrap(daily_pnl)

        wins = (trades['pnl'] > 0).sum()
        n = len(trades)
        print(f"    Trades: {n}, Win: {wins / n * 100:.1f}%")
        print(f"    Total P&L: ${pm['total_pnl']:+,.2f}")
        print(f"    Daily Sharpe: {pm['daily_sharpe']}")
        print(f"    Max DD: ${pm['max_dd']:,.2f} ({pm['max_dd_pct']:.1f}%)")
        if 'error' not in ho:
            print(f"    Holdout: train={ho['train_sharpe']}, test={ho['test_sharpe']}, "
                  f"ratio={ho['ratio']} {'PASS' if ho['passed'] else 'FAIL'}")
        print(f"    Bootstrap: Sharpe CI [{bs['sharpe_ci_lower']}, {bs['sharpe_ci_upper']}], "
              f"P(neg)={bs['prob_sharpe_negative']}%")

        all_results.append({
            "ticker": ticker, "mode": "single", "trades": n,
            "win_rate": round(wins / n * 100, 1),
            "total_pnl": pm["total_pnl"], "sharpe": pm["daily_sharpe"],
            "max_dd_pct": pm["max_dd_pct"], "holdout": ho, "bootstrap": bs,
        })

    # =========================================================
    print("\n" + "=" * 50)
    print("H45: Multi-Index Portfolio (SPY + QQQ + IWM)")
    print("=" * 50)

    # Combine daily P&L across all 3 indices
    all_daily = {}
    for ticker in tickers:
        _, daily_pnl = backtest_weekly_straddle(stock_data[ticker], ticker)
        for date, pnl in daily_pnl:
            if date not in all_daily:
                all_daily[date] = 0
            all_daily[date] += pnl

    combined_daily = sorted(all_daily.items())
    pm = analyze_portfolio(combined_daily)
    ho = holdout(combined_daily)
    bs = bootstrap(combined_daily)

    print(f"    Total P&L: ${pm['total_pnl']:+,.2f}")
    print(f"    Daily Sharpe: {pm['daily_sharpe']}")
    print(f"    Max DD: ${pm['max_dd']:,.2f} ({pm['max_dd_pct']:.1f}%)")
    if 'error' not in ho:
        print(f"    Holdout: train={ho['train_sharpe']}, test={ho['test_sharpe']}, "
              f"ratio={ho['ratio']} {'PASS' if ho['passed'] else 'FAIL'}")
    print(f"    Bootstrap: Sharpe CI [{bs['sharpe_ci_lower']}, {bs['sharpe_ci_upper']}], "
          f"P(neg)={bs['prob_sharpe_negative']}%")

    # Compare single vs multi
    spy_sharpe = next((r["sharpe"] for r in all_results if r["ticker"] == "SPY"), 0)
    multi_sharpe = pm["daily_sharpe"]
    diversification_benefit = multi_sharpe / spy_sharpe if spy_sharpe != 0 else 0
    print(f"\n    SPY alone Sharpe: {spy_sharpe}")
    print(f"    3-index Sharpe: {multi_sharpe}")
    print(f"    Diversification: {diversification_benefit:.2f}x")
    h45_pass = diversification_benefit > 1.5
    print(f"    H45: {'PASSED' if h45_pass else 'FAILED'}")

    all_results.append({
        "ticker": "COMBINED", "mode": "multi", "trades": "N/A",
        "total_pnl": pm["total_pnl"], "sharpe": pm["daily_sharpe"],
        "max_dd_pct": pm["max_dd_pct"], "holdout": ho, "bootstrap": bs,
    })

    # =========================================================
    print("\n" + "=" * 50)
    print("H46: Backwardation Filter (SPY)")
    print("=" * 50)

    trades_filtered, daily_filtered = backtest_weekly_straddle(
        stock_data["SPY"], "SPY", skip_backwardation=True
    )
    pm_f = analyze_portfolio(daily_filtered)
    print(f"    Filtered: {len(trades_filtered)} trades, Sharpe: {pm_f['daily_sharpe']}")
    print(f"    Unfiltered: Sharpe: {spy_sharpe}")
    h46_pass = pm_f["daily_sharpe"] > spy_sharpe
    print(f"    H46: {'PASSED' if h46_pass else 'FAILED'}")

    # =========================================================
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"{'Variant':<25s} {'P&L':>10s} {'Sharpe':>8s} {'MaxDD%':>8s}")
    print("-" * 55)
    for r in all_results:
        print(f"{r['ticker'] + ' ' + r['mode']:<25s} ${r['total_pnl']:>+9,.0f} {r['sharpe']:>7.3f} {r['max_dd_pct']:>7.1f}%")

    # Pass/fail
    spy_result = next((r for r in all_results if r["ticker"] == "SPY"), None)
    h44_pass = spy_result and spy_result["sharpe"] > 0.3
    print(f"\n  H44 (SPY Sharpe > 0.3): {'PASSED' if h44_pass else 'FAILED'} ({spy_result['sharpe'] if spy_result else 'N/A'})")
    print(f"  H45 (Diversification > 1.5x): {'PASSED' if h45_pass else 'FAILED'}")
    print(f"  H46 (Backwardation filter helps): {'PASSED' if h46_pass else 'FAILED'}")

    if h44_pass:
        print(f"\n  SPY straddles show promise. VALIDATE WITH REAL DATA before deploying.")
    else:
        print(f"\n  Index straddles also fail Sharpe threshold on BSM proxy.")
        print(f"  VRP harvesting may not be viable for Dad's constraints.")

    # Save
    output = {"results": all_results, "h44": h44_pass, "h45": h45_pass, "h46": h46_pass}
    out_path = os.path.join(os.path.dirname(__file__), "results.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
