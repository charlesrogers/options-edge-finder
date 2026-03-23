"""
Research: Optimal Exit Strategy for Put Spreads

Grid search over take-profit, stop-loss, DTE floor, and VRP exit
to find the combination that maximizes risk-adjusted returns.

This is the most important research in the entire system.
Without active exit management, the put spread strategy LOSES money
despite 80% win rate (asymmetric risk/reward).

Pre-registered hypotheses: H30-H34

Usage:
  python research_exit_strategy.py
"""

import os
import sys
import json
import itertools

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pandas as pd


def fetch_history(ticker, period="2y"):
    """Fetch OHLCV from Yahoo Finance."""
    try:
        import yf_proxy
        hist = yf_proxy.get_stock_history(ticker, period=period)
        if not hist.empty:
            return hist
    except Exception:
        pass
    try:
        import yfinance as yf
        hist = yf.download(ticker, period=period, progress=False)
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        return hist
    except Exception:
        return pd.DataFrame()


def backtest_put_spread_with_exits(hist, spread_width_pct=0.10,
                                     sell_otm_pct=0.05,
                                     holding_period=20,
                                     iv_rv_ratio=1.2,
                                     take_profit_pct=0.50,
                                     stop_loss_mult=2.0,
                                     dte_floor=7,
                                     vrp_exit=True,
                                     slippage_pct=0.12):
    """
    Backtest a put spread strategy with active exit management.

    Simulates daily monitoring of spread value and applies exit rules.

    Args:
        hist: OHLCV DataFrame
        spread_width_pct: width as % of stock price (0.10 = 10%)
        sell_otm_pct: sell strike OTM % (0.05 = 5% below spot)
        holding_period: max holding in calendar days
        iv_rv_ratio: IV proxy = RV * this ratio
        take_profit_pct: close at this % of max profit (0.50 = 50%)
        stop_loss_mult: close at this multiple of credit (2.0 = 2x)
        dte_floor: close at this many DTE regardless
        vrp_exit: close if VRP flips negative
        slippage_pct: bid-ask friction as % of credit on each close

    Returns:
        DataFrame of trades with columns:
        [entry_date, exit_date, exit_reason, credit, max_loss, pnl, days_held]
    """
    if len(hist) < 60:
        return pd.DataFrame()

    close = hist["Close"].values
    dates = hist.index
    n = len(close)

    # Compute daily RVs and IV proxy
    log_ret = np.log(close[1:] / close[:-1])
    rv_20 = pd.Series(log_ret).rolling(20).std().values * np.sqrt(252) * 100
    iv_proxy = rv_20 * iv_rv_ratio

    # Forward-looking RV (for VRP check during hold)
    rv_fwd_20 = pd.Series(log_ret).rolling(20).std().shift(-20).values * np.sqrt(252) * 100

    trades = []

    # Entry every `holding_period` days when GREEN signal
    i = 25  # start after enough history
    while i < n - holding_period - 1:
        # Check GREEN signal at entry
        if i >= len(rv_20) or i >= len(iv_proxy):
            i += holding_period
            continue

        entry_iv = iv_proxy[i - 1] if i > 0 else None
        entry_rv = rv_20[i - 1] if i > 0 else None

        if entry_iv is None or entry_rv is None or np.isnan(entry_iv) or np.isnan(entry_rv):
            i += holding_period
            continue

        vrp = entry_iv - entry_rv
        iv_q30 = np.nanpercentile(iv_proxy[max(0, i - 252):i], 30)

        # GREEN signal check
        is_green = vrp > 2 and entry_iv > iv_q30
        if not is_green:
            i += holding_period
            continue

        # Define spread
        spot = close[i]
        sell_strike = spot * (1 - sell_otm_pct)
        buy_strike = sell_strike - (spot * spread_width_pct)
        width = sell_strike - buy_strike

        # Credit estimate: sell put premium - buy put premium
        # Approximate: credit ≈ (expected move at sell strike - expected move at buy strike)
        # Simplified: credit = VRP component of the sell leg * sqrt(T)
        credit_per_share = entry_iv / 100 * np.sqrt(holding_period / 252) * (sell_otm_pct + spread_width_pct / 2) * 2
        credit_per_share = min(credit_per_share, width * 0.30)  # cap at 30% of width
        credit_per_share = max(credit_per_share, width * 0.05)  # floor at 5% of width

        max_loss = (width - credit_per_share) * 100
        credit_total = credit_per_share * 100

        # Take profit and stop loss thresholds
        tp_threshold = credit_per_share * (1 - take_profit_pct)  # spread value at take profit
        sl_threshold = credit_per_share * stop_loss_mult  # spread value at stop loss

        # Simulate daily path
        exit_day = None
        exit_reason = "expiry"
        exit_pnl = None

        for d in range(1, holding_period + 1):
            if i + d >= n:
                break

            day_price = close[i + d]
            dte_remaining = holding_period - d

            # Estimate current spread value from stock price movement
            # Put spread value increases when stock drops toward sell strike
            move_pct = (spot - day_price) / spot  # positive = stock dropped

            # Spread value approximation:
            # If stock well above sell strike: spread worth ~0 (profit captured)
            # If stock near sell strike: spread worth ~width/2
            # If stock below buy strike: spread worth ~width (max loss)
            if day_price >= sell_strike:
                # Stock above sell strike — spread is winning
                # Value decays with time (theta helps seller)
                time_factor = dte_remaining / holding_period
                distance = (day_price - sell_strike) / (spot - sell_strike) if spot > sell_strike else 1
                spread_value = credit_per_share * time_factor * (1 - distance * 0.5)
                spread_value = max(0, spread_value)
            elif day_price >= buy_strike:
                # Stock between strikes — spread is losing
                intrinsic = sell_strike - day_price
                time_value = (width - intrinsic) * (dte_remaining / holding_period) * 0.3
                spread_value = intrinsic + time_value
            else:
                # Stock below buy strike — near max loss
                spread_value = width * 0.95  # near full width

            # Check exit triggers
            # 1. Take profit
            if take_profit_pct < 1.0 and spread_value <= tp_threshold:
                exit_day = d
                exit_reason = "take_profit"
                # P&L = credit collected - cost to close - slippage
                close_cost = spread_value * 100
                slippage = credit_total * slippage_pct
                exit_pnl = credit_total - close_cost - slippage
                break

            # 2. Stop loss
            if stop_loss_mult > 0 and spread_value >= sl_threshold:
                exit_day = d
                exit_reason = "stop_loss"
                close_cost = spread_value * 100
                slippage = credit_total * slippage_pct
                exit_pnl = credit_total - close_cost - slippage
                break

            # 3. DTE floor
            if dte_floor > 0 and dte_remaining <= dte_floor:
                exit_day = d
                exit_reason = "dte_floor"
                close_cost = spread_value * 100
                slippage = credit_total * slippage_pct
                exit_pnl = credit_total - close_cost - slippage
                break

            # 4. VRP exit
            if vrp_exit and i + d - 1 < len(iv_proxy) and i + d - 1 < len(rv_20):
                current_iv = iv_proxy[i + d - 1]
                current_rv = rv_20[i + d - 1]
                if not np.isnan(current_iv) and not np.isnan(current_rv):
                    current_vrp = current_iv - current_rv
                    if current_vrp < 0:
                        exit_day = d
                        exit_reason = "vrp_flip"
                        close_cost = spread_value * 100
                        slippage = credit_total * slippage_pct
                        exit_pnl = credit_total - close_cost - slippage
                        break

        # If no exit triggered, hold to expiry
        if exit_pnl is None:
            exit_day = holding_period
            final_price = close[min(i + holding_period, n - 1)]
            if final_price >= sell_strike:
                exit_pnl = credit_total  # full profit
            elif final_price >= buy_strike:
                intrinsic_loss = (sell_strike - final_price) * 100
                exit_pnl = credit_total - intrinsic_loss
            else:
                exit_pnl = credit_total - width * 100  # max loss
            exit_reason = "expiry"

        trades.append({
            "entry_date": str(dates[i])[:10],
            "exit_date": str(dates[min(i + exit_day, n - 1)])[:10],
            "exit_reason": exit_reason,
            "credit": round(credit_total, 2),
            "max_loss": round(max_loss, 2),
            "pnl": round(exit_pnl, 2),
            "days_held": exit_day,
            "entry_price": round(spot, 2),
            "sell_strike": round(sell_strike, 2),
            "buy_strike": round(buy_strike, 2),
            "vrp_at_entry": round(vrp, 2),
        })

        i += holding_period  # advance to next entry

    return pd.DataFrame(trades)


def evaluate_strategy(trades_df):
    """Compute strategy metrics from trades DataFrame."""
    if trades_df.empty or len(trades_df) < 5:
        return None

    pnl = trades_df["pnl"]
    credit = trades_df["credit"]
    max_loss = trades_df["max_loss"]

    n = len(pnl)
    wins = (pnl > 0).sum()
    win_rate = wins / n * 100
    avg_pnl = pnl.mean()
    total_pnl = pnl.sum()
    std_pnl = pnl.std()
    sharpe = avg_pnl / std_pnl * np.sqrt(252 / 20) if std_pnl > 0 else 0

    # Sortino
    downside = pnl[pnl < 0]
    downside_std = downside.std() if len(downside) > 1 else std_pnl
    sortino = avg_pnl / downside_std * np.sqrt(252 / 20) if downside_std > 0 else 0

    # Max drawdown
    cum_pnl = pnl.cumsum()
    peak = cum_pnl.cummax()
    dd = cum_pnl - peak
    max_dd = dd.min()

    # Average holding period
    avg_days = trades_df["days_held"].mean()

    # Exit reason breakdown
    reasons = trades_df["exit_reason"].value_counts().to_dict()

    # Return on risk (avg pnl / avg max loss)
    avg_max_loss = max_loss.mean()
    ror = avg_pnl / avg_max_loss * 100 if avg_max_loss > 0 else 0

    return {
        "n_trades": n,
        "win_rate": round(win_rate, 2),
        "avg_pnl": round(avg_pnl, 2),
        "total_pnl": round(total_pnl, 2),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "max_dd": round(max_dd, 2),
        "avg_days_held": round(avg_days, 1),
        "return_on_risk": round(ror, 4),
        "exit_reasons": reasons,
    }


def run_grid_search(tickers=None, period="2y"):
    """Run grid search across all parameter combinations."""
    if tickers is None:
        tickers = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TXN", "DIS"]

    # Parameter grid
    take_profits = [0.25, 0.50, 0.65, 0.75, 1.0]
    stop_losses = [1.0, 1.5, 2.0, 2.5, 3.0, 99.0]  # 99.0 = no stop
    dte_floors = [0, 3, 5, 7, 14]
    vrp_exits = [True, False]

    all_results = []
    n_combos = len(take_profits) * len(stop_losses) * len(dte_floors) * len(vrp_exits)
    print(f"Grid search: {n_combos} parameter combos x {len(tickers)} tickers")

    # Load history for all tickers
    histories = {}
    for ticker in tickers:
        print(f"  Fetching {ticker}...")
        hist = fetch_history(ticker, period)
        if not hist.empty and len(hist) >= 100:
            histories[ticker] = hist
            print(f"    Got {len(hist)} days")

    combo_num = 0
    for tp, sl, dte, vrp_ex in itertools.product(take_profits, stop_losses, dte_floors, vrp_exits):
        combo_num += 1
        if combo_num % 50 == 0:
            print(f"  Combo {combo_num}/{n_combos}...")

        # Run across all tickers
        all_trades = []
        for ticker, hist in histories.items():
            trades = backtest_put_spread_with_exits(
                hist,
                take_profit_pct=tp,
                stop_loss_mult=sl,
                dte_floor=dte,
                vrp_exit=vrp_ex,
            )
            if not trades.empty:
                trades["ticker"] = ticker
                all_trades.append(trades)

        if not all_trades:
            continue

        combined = pd.concat(all_trades, ignore_index=True)
        metrics = evaluate_strategy(combined)
        if metrics:
            metrics["take_profit"] = tp
            metrics["stop_loss"] = sl
            metrics["dte_floor"] = dte
            metrics["vrp_exit"] = vrp_ex
            all_results.append(metrics)

    return pd.DataFrame(all_results)


def main():
    print("=" * 70)
    print("EXIT STRATEGY RESEARCH — Put Spread Grid Search")
    print("=" * 70)
    print("Pre-registered: H30-H34")
    print("300 parameter combos × 7 tickers × 2 years")
    print()

    results_df = run_grid_search()

    if results_df.empty:
        print("No results produced.")
        return

    # Sort by Sortino (best risk-adjusted return)
    results_df = results_df.sort_values("sortino", ascending=False)

    # Top 10
    print("\n" + "=" * 70)
    print("TOP 10 PARAMETER COMBINATIONS (by Sortino)")
    print("=" * 70)
    cols = ["take_profit", "stop_loss", "dte_floor", "vrp_exit",
            "win_rate", "avg_pnl", "sharpe", "sortino", "max_dd",
            "avg_days_held", "n_trades"]
    print(results_df[cols].head(10).to_string(index=False))

    # Bottom 5 (worst)
    print("\nBOTTOM 5 (worst — these destroy money):")
    print(results_df[cols].tail(5).to_string(index=False))

    # H30: Take profit analysis
    print("\n" + "=" * 70)
    print("H30: TAKE PROFIT ANALYSIS")
    print("=" * 70)
    for tp in sorted(results_df["take_profit"].unique()):
        subset = results_df[results_df["take_profit"] == tp]
        print(f"  TP={tp:.0%}: avg Sortino={subset['sortino'].mean():.3f}, "
              f"avg P&L=${subset['avg_pnl'].mean():.1f}, "
              f"avg win={subset['win_rate'].mean():.1f}%")

    # H31: Stop loss analysis
    print("\n" + "=" * 70)
    print("H31: STOP LOSS ANALYSIS")
    print("=" * 70)
    for sl in sorted(results_df["stop_loss"].unique()):
        subset = results_df[results_df["stop_loss"] == sl]
        label = "none" if sl >= 99 else f"{sl:.1f}x"
        print(f"  SL={label}: avg Sortino={subset['sortino'].mean():.3f}, "
              f"avg P&L=${subset['avg_pnl'].mean():.1f}, "
              f"avg DD=${subset['max_dd'].mean():.0f}")

    # H32: DTE floor analysis
    print("\n" + "=" * 70)
    print("H32: DTE FLOOR ANALYSIS")
    print("=" * 70)
    for dte in sorted(results_df["dte_floor"].unique()):
        subset = results_df[results_df["dte_floor"] == dte]
        label = "none" if dte == 0 else f"{dte}d"
        print(f"  DTE floor={label}: avg Sortino={subset['sortino'].mean():.3f}, "
              f"avg days={subset['avg_days_held'].mean():.1f}")

    # H33: VRP exit analysis
    print("\n" + "=" * 70)
    print("H33: VRP EXIT ANALYSIS")
    print("=" * 70)
    for vrp in [True, False]:
        subset = results_df[results_df["vrp_exit"] == vrp]
        print(f"  VRP exit={'yes' if vrp else 'no'}: avg Sortino={subset['sortino'].mean():.3f}, "
              f"avg P&L=${subset['avg_pnl'].mean():.1f}")

    # Best overall
    best = results_df.iloc[0]
    print("\n" + "=" * 70)
    print("RECOMMENDED EXIT STRATEGY")
    print("=" * 70)
    print(f"  Take profit: {best['take_profit']:.0%} of max")
    sl_label = "none" if best['stop_loss'] >= 99 else f"{best['stop_loss']:.1f}x premium"
    print(f"  Stop loss: {sl_label}")
    dte_label = "none" if best['dte_floor'] == 0 else f"{best['dte_floor']} DTE"
    print(f"  DTE floor: {dte_label}")
    print(f"  VRP exit: {'yes' if best['vrp_exit'] else 'no'}")
    print(f"  Sortino: {best['sortino']:.3f}")
    print(f"  Sharpe: {best['sharpe']:.3f}")
    print(f"  Win rate: {best['win_rate']:.1f}%")
    print(f"  Avg P&L: ${best['avg_pnl']:.1f}")
    print(f"  Max DD: ${best['max_dd']:.0f}")
    print(f"  Avg hold: {best['avg_days_held']:.1f} days")
    print(f"  Trades: {best['n_trades']}")

    # Save results
    output_path = os.path.join(os.path.dirname(__file__), "exit_research_results.json")
    results_df.to_json(output_path, orient="records", indent=2)
    print(f"\nFull results saved to: {output_path}")


if __name__ == "__main__":
    main()
