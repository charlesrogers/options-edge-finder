"""
Module 4: Walk-Forward Backtest
===============================
Replaces one-pass backtest with proper out-of-sample validation.

Sub-modules:
  4A: Rolling Walk-Forward (train/test split with sliding windows)
  4B: IV Multiplier Sensitivity Analysis
  4C: Survivorship Bias Estimate
  4D: Transaction Cost Sensitivity
"""

import numpy as np
import pandas as pd
from eval_risk import calc_cvar, calc_max_drawdown, calc_omega_ratio


# ──────────────────────────────────────────────────────────────
# Core: Walk-forward backtest engine
# ──────────────────────────────────────────────────────────────

def _compute_signals_and_pnl(df, iv_col="iv_proxy", rv_col="rv_actual",
                             holding_period=20, commission=0.65, slippage=0.025):
    """
    Given a DataFrame with IV proxy, backward RV, forward actual RV,
    forward returns, and close prices, compute signals and P&L.
    Shared logic used by both walk-forward and one-pass backtests.
    """
    df = df.copy()
    df["vrp_proxy"] = df[iv_col] - df[rv_col]

    # Signal classification
    iv_q30 = df[iv_col].quantile(0.30)

    def classify(row):
        if row["vrp_proxy"] > 2 and row[iv_col] > iv_q30:
            return "GREEN"
        elif row["vrp_proxy"] > 0:
            return "YELLOW"
        else:
            return "RED"

    df["signal"] = df.apply(classify, axis=1)

    # Premium and P&L
    df["expected_move_pct"] = df[iv_col] / 100 * np.sqrt(holding_period / 252)
    df["actual_move_pct"] = df["fwd_return"].abs()
    df["seller_wins"] = df["actual_move_pct"] < df["expected_move_pct"]
    df["premium_pct"] = df[iv_col] / 100 * np.sqrt(holding_period / 252) * 100

    df["pnl_pct"] = np.where(
        df["seller_wins"],
        df["premium_pct"],
        df["premium_pct"] - (df["actual_move_pct"] * 100 - df["premium_pct"])
    )

    # Transaction costs
    total_cost = (commission + slippage) * 2
    df["cost_pct"] = total_cost / df["close"] * 100
    df["pnl_pct"] = df["pnl_pct"] - df["cost_pct"]

    return df


def _summarize_window(df, label=""):
    """Summarize a backtest window's results."""
    if df.empty:
        return None
    pnl = df["pnl_pct"]
    return {
        "label": label,
        "n_trades": len(df),
        "win_rate": float(df["seller_wins"].mean() * 100),
        "avg_pnl_pct": float(pnl.mean()),
        "total_pnl_pct": float(pnl.sum()),
        "std_pnl_pct": float(pnl.std()),
        "sharpe_per_trade": float(pnl.mean() / pnl.std()) if pnl.std() > 0 else 0,
        "worst_pnl_pct": float(pnl.min()),
        "best_pnl_pct": float(pnl.max()),
        "green_count": int((df["signal"] == "GREEN").sum()),
        "yellow_count": int((df["signal"] == "YELLOW").sum()),
        "red_count": int((df["signal"] == "RED").sum()),
        "green_win_rate": float(df[df["signal"] == "GREEN"]["seller_wins"].mean() * 100) if (df["signal"] == "GREEN").any() else None,
        "green_avg_pnl": float(df[df["signal"] == "GREEN"]["pnl_pct"].mean()) if (df["signal"] == "GREEN").any() else None,
    }


# ──────────────────────────────────────────────────────────────
# 4A: Rolling Walk-Forward
# ──────────────────────────────────────────────────────────────

def walk_forward_backtest(hist: pd.DataFrame,
                          train_days: int = 756,
                          test_days: int = 126,
                          step_days: int = 63,
                          holding_period: int = 20,
                          iv_rv_ratio: float = 1.2,
                          commission: float = 0.65,
                          slippage: float = 0.025) -> dict:
    """
    Rolling walk-forward backtest with train/test split.

    For each window:
      1. Use training window to establish IV quantiles for signal thresholds
      2. Apply those thresholds on test window (out-of-sample)
      3. Record OOS results

    Args:
        hist: OHLCV DataFrame
        train_days: Training window in trading days (default 756 = 3 years)
        test_days: Test window in trading days (default 126 = 6 months)
        step_days: Step size in trading days (default 63 = 3 months)
        holding_period: Holding period for each trade
        iv_rv_ratio: IV = RV * this ratio (de-biasing)
        commission: Per-contract commission
        slippage: Per-contract slippage

    Returns:
        dict with in_sample, out_of_sample summaries and window details
    """
    # Prepare full dataset
    log_ret = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
    rv_backward = log_ret.rolling(holding_period).std() * np.sqrt(252) * 100
    iv_estimate = rv_backward * iv_rv_ratio
    rv_forward = log_ret.rolling(holding_period).std().shift(-holding_period) * np.sqrt(252) * 100
    fwd_return = hist["Close"].pct_change(holding_period).shift(-holding_period)

    full_df = pd.DataFrame({
        "date": hist.index[1:],
        "close": hist["Close"].iloc[1:].values,
        "iv_proxy": iv_estimate.values,
        "rv_backward": rv_backward.values,
        "rv_actual": rv_forward.values,
        "fwd_return": fwd_return.iloc[1:].values,
    }).dropna().reset_index(drop=True)

    if len(full_df) < train_days + test_days:
        return {"error": f"Not enough data: {len(full_df)} rows, need {train_days + test_days}"}

    n_windows = 0
    oos_results = []
    is_results = []
    window_details = []

    total_possible = (len(full_df) - train_days - test_days) // step_days + 1
    print(f"  Walk-forward: {total_possible} windows "
          f"(train={train_days}d, test={test_days}d, step={step_days}d)")

    for start in range(0, len(full_df) - train_days - test_days + 1, step_days):
        train_end = start + train_days
        test_end = min(train_end + test_days, len(full_df))

        train_df = full_df.iloc[start:train_end].copy()
        test_df = full_df.iloc[train_end:test_end].copy()

        if len(test_df) < 10:
            continue

        # Compute signals using training-period thresholds
        train_with_signals = _compute_signals_and_pnl(
            train_df, holding_period=holding_period,
            commission=commission, slippage=slippage
        )

        # For OOS: use training period's IV quantile for signal thresholds
        # (this prevents look-ahead bias in signal classification)
        iv_q30_train = train_df["iv_proxy"].quantile(0.30)

        test_df["vrp_proxy"] = test_df["iv_proxy"] - test_df["rv_actual"]

        def classify_oos(row):
            if row["vrp_proxy"] > 2 and row["iv_proxy"] > iv_q30_train:
                return "GREEN"
            elif row["vrp_proxy"] > 0:
                return "YELLOW"
            else:
                return "RED"

        test_df["signal"] = test_df.apply(classify_oos, axis=1)
        test_df["expected_move_pct"] = test_df["iv_proxy"] / 100 * np.sqrt(holding_period / 252)
        test_df["actual_move_pct"] = test_df["fwd_return"].abs()
        test_df["seller_wins"] = test_df["actual_move_pct"] < test_df["expected_move_pct"]
        test_df["premium_pct"] = test_df["iv_proxy"] / 100 * np.sqrt(holding_period / 252) * 100
        test_df["pnl_pct"] = np.where(
            test_df["seller_wins"],
            test_df["premium_pct"],
            test_df["premium_pct"] - (test_df["actual_move_pct"] * 100 - test_df["premium_pct"])
        )
        total_cost = (commission + slippage) * 2
        test_df["cost_pct"] = total_cost / test_df["close"] * 100
        test_df["pnl_pct"] = test_df["pnl_pct"] - test_df["cost_pct"]

        # Summarize
        window_start_date = str(train_df["date"].iloc[0])[:10]
        window_test_start = str(test_df["date"].iloc[0])[:10]
        window_test_end = str(test_df["date"].iloc[-1])[:10]

        is_summary = _summarize_window(train_with_signals, f"IS {window_start_date}")
        oos_summary = _summarize_window(test_df, f"OOS {window_test_start}–{window_test_end}")

        if is_summary:
            is_results.append(is_summary)
        if oos_summary:
            oos_results.append(oos_summary)
            window_details.append({
                "window": n_windows + 1,
                "train_start": window_start_date,
                "test_start": window_test_start,
                "test_end": window_test_end,
                "is_win_rate": is_summary["win_rate"] if is_summary else None,
                "oos_win_rate": oos_summary["win_rate"],
                "is_avg_pnl": is_summary["avg_pnl_pct"] if is_summary else None,
                "oos_avg_pnl": oos_summary["avg_pnl_pct"],
                "is_sharpe": is_summary["sharpe_per_trade"] if is_summary else None,
                "oos_sharpe": oos_summary["sharpe_per_trade"],
                "oos_green_pct": oos_summary["green_count"] / oos_summary["n_trades"] * 100 if oos_summary["n_trades"] > 0 else 0,
            })

        n_windows += 1
        if n_windows % 5 == 0:
            print(f"    Window {n_windows}/{total_possible} complete...")

    if not oos_results:
        return {"error": "No valid walk-forward windows produced"}

    # Aggregate OOS results
    all_oos_pnl = [r["avg_pnl_pct"] for r in oos_results]
    all_is_pnl = [r["avg_pnl_pct"] for r in is_results]

    oos_agg = {
        "n_windows": n_windows,
        "avg_win_rate": float(np.mean([r["win_rate"] for r in oos_results])),
        "avg_pnl_pct": float(np.mean(all_oos_pnl)),
        "std_pnl_pct": float(np.std(all_oos_pnl)),
        "worst_window_pnl": float(np.min(all_oos_pnl)),
        "best_window_pnl": float(np.max(all_oos_pnl)),
        "pct_profitable_windows": float(np.mean([1 for p in all_oos_pnl if p > 0]) / len(all_oos_pnl) * 100) if all_oos_pnl else 0,
        "avg_sharpe": float(np.mean([r["sharpe_per_trade"] for r in oos_results])),
    }

    is_agg = {
        "avg_win_rate": float(np.mean([r["win_rate"] for r in is_results])),
        "avg_pnl_pct": float(np.mean(all_is_pnl)),
        "avg_sharpe": float(np.mean([r["sharpe_per_trade"] for r in is_results])),
    }

    # Overfitting indicator
    overfit_ratio = is_agg["avg_pnl_pct"] / oos_agg["avg_pnl_pct"] if oos_agg["avg_pnl_pct"] != 0 else float("inf")

    return {
        "oos_summary": oos_agg,
        "is_summary": is_agg,
        "overfit_ratio": round(overfit_ratio, 2),
        "window_details": window_details,
        "oos_by_window": oos_results,
    }


# ──────────────────────────────────────────────────────────────
# 4B: IV Multiplier Sensitivity
# ──────────────────────────────────────────────────────────────

def iv_multiplier_sensitivity(hist: pd.DataFrame,
                              multipliers: list = None,
                              holding_period: int = 20,
                              commission: float = 0.65,
                              slippage: float = 0.025) -> list:
    """
    Run backtest across different IV multiplier assumptions.
    Tests how fragile the strategy is to the IV de-biasing parameter.

    Returns list of dicts, one per multiplier.
    """
    if multipliers is None:
        multipliers = [1.0, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30]

    log_ret = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
    rv_backward = log_ret.rolling(holding_period).std() * np.sqrt(252) * 100
    rv_forward = log_ret.rolling(holding_period).std().shift(-holding_period) * np.sqrt(252) * 100
    fwd_return = hist["Close"].pct_change(holding_period).shift(-holding_period)

    results = []
    for mult in multipliers:
        iv_est = rv_backward * mult

        df = pd.DataFrame({
            "date": hist.index[1:],
            "close": hist["Close"].iloc[1:].values,
            "iv_proxy": iv_est.values,
            "rv_backward": rv_backward.values,
            "rv_actual": rv_forward.values,
            "fwd_return": fwd_return.iloc[1:].values,
        }).dropna()

        if df.empty:
            continue

        df = _compute_signals_and_pnl(df, holding_period=holding_period,
                                       commission=commission, slippage=slippage)

        pnl = df["pnl_pct"]
        green_df = df[df["signal"] == "GREEN"]

        dd = calc_max_drawdown(pnl)

        row = {
            "multiplier": mult,
            "n_trades": len(df),
            "win_rate": round(float(df["seller_wins"].mean() * 100), 2),
            "avg_pnl_pct": round(float(pnl.mean()), 4),
            "total_pnl_pct": round(float(pnl.sum()), 2),
            "max_drawdown_pct": round(dd["max_drawdown_pct"], 2) if dd else None,
            "sharpe": round(float(pnl.mean() / pnl.std()), 4) if pnl.std() > 0 else 0,
            "green_pct": round(float((df["signal"] == "GREEN").mean() * 100), 1),
            "green_win_rate": round(float(green_df["seller_wins"].mean() * 100), 2) if len(green_df) > 0 else None,
            "green_avg_pnl": round(float(green_df["pnl_pct"].mean()), 4) if len(green_df) > 0 else None,
        }
        results.append(row)
        print(f"    mult={mult:.2f}: win_rate={row['win_rate']:.1f}%, "
              f"avg_pnl={row['avg_pnl_pct']:+.3f}%, green={row['green_pct']:.0f}%")

    return results


# ──────────────────────────────────────────────────────────────
# 4C: Survivorship Bias Estimate
# ──────────────────────────────────────────────────────────────

def survivorship_bias_adjustment(annual_return_pct: float,
                                 years: float,
                                 haircut_bps: int = 150) -> dict:
    """
    Apply conservative survivorship bias haircut.
    Literature estimate: ~150 bps/year for US equity strategies.

    Args:
        annual_return_pct: Raw annualized return
        years: Number of years in backtest
        haircut_bps: Annual haircut in basis points (default 150)

    Returns:
        dict with raw and adjusted returns
    """
    haircut_pct = haircut_bps / 100  # 150 bps = 1.5%
    adjusted = annual_return_pct - haircut_pct

    return {
        "raw_annual_return_pct": round(annual_return_pct, 2),
        "adjusted_annual_return_pct": round(adjusted, 2),
        "haircut_pct_per_year": round(haircut_pct, 2),
        "total_haircut_pct": round(haircut_pct * years, 2),
        "years": round(years, 1),
        "still_profitable": adjusted > 0,
    }


# ──────────────────────────────────────────────────────────────
# 4D: Transaction Cost Sensitivity
# ──────────────────────────────────────────────────────────────

def transaction_cost_sensitivity(hist: pd.DataFrame,
                                 spread_assumptions: list = None,
                                 holding_period: int = 20,
                                 iv_rv_ratio: float = 1.2) -> list:
    """
    Test how sensitive profitability is to transaction cost assumptions.

    Args:
        spread_assumptions: Slippage values in dollars per contract
    """
    if spread_assumptions is None:
        spread_assumptions = [0.01, 0.03, 0.05, 0.10, 0.15, 0.20]

    log_ret = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
    rv_backward = log_ret.rolling(holding_period).std() * np.sqrt(252) * 100
    iv_estimate = rv_backward * iv_rv_ratio
    rv_forward = log_ret.rolling(holding_period).std().shift(-holding_period) * np.sqrt(252) * 100
    fwd_return = hist["Close"].pct_change(holding_period).shift(-holding_period)

    base_df = pd.DataFrame({
        "date": hist.index[1:],
        "close": hist["Close"].iloc[1:].values,
        "iv_proxy": iv_estimate.values,
        "rv_backward": rv_backward.values,
        "rv_actual": rv_forward.values,
        "fwd_return": fwd_return.iloc[1:].values,
    }).dropna()

    if base_df.empty:
        return []

    results = []
    for spread in spread_assumptions:
        df = _compute_signals_and_pnl(base_df, holding_period=holding_period,
                                       commission=0.65, slippage=spread)
        pnl = df["pnl_pct"]
        green_pnl = df[df["signal"] == "GREEN"]["pnl_pct"]

        row = {
            "slippage": spread,
            "total_cost_per_trade": round((0.65 + spread) * 2, 2),
            "avg_pnl_pct": round(float(pnl.mean()), 4),
            "total_pnl_pct": round(float(pnl.sum()), 2),
            "win_rate": round(float(df["seller_wins"].mean() * 100), 2),
            "green_avg_pnl": round(float(green_pnl.mean()), 4) if len(green_pnl) > 0 else None,
            "profitable": float(pnl.mean()) > 0,
        }
        results.append(row)

    # Find break-even spread
    for i in range(len(results) - 1):
        if results[i]["avg_pnl_pct"] > 0 and results[i + 1]["avg_pnl_pct"] <= 0:
            # Linear interpolation
            s1, p1 = results[i]["slippage"], results[i]["avg_pnl_pct"]
            s2, p2 = results[i + 1]["slippage"], results[i + 1]["avg_pnl_pct"]
            breakeven = s1 + (s2 - s1) * (0 - p1) / (p2 - p1)
            for r in results:
                r["breakeven_slippage"] = round(breakeven, 4)
            break

    return results


# ──────────────────────────────────────────────────────────────
# Combined: Run all Module 4 tests
# ──────────────────────────────────────────────────────────────

def run_all_backtest_eval(hist: pd.DataFrame, ticker: str = "",
                          holding_period: int = 20) -> dict:
    """
    Run all Module 4 evaluations on a single ticker's history.

    Args:
        hist: OHLCV DataFrame (at least 4+ years for meaningful walk-forward)
        ticker: Ticker symbol for display
        holding_period: Days per trade

    Returns:
        dict with all sub-module results
    """
    results = {"ticker": ticker}

    # 4A: Walk-Forward
    print(f"\n[4A] Walk-Forward Backtest...")
    wf = walk_forward_backtest(hist, holding_period=holding_period)
    results["walk_forward"] = wf

    # 4B: IV Multiplier Sensitivity
    print(f"\n[4B] IV Multiplier Sensitivity...")
    results["iv_sensitivity"] = iv_multiplier_sensitivity(hist, holding_period=holding_period)

    # 4C: Survivorship Bias
    if not wf.get("error"):
        oos = wf["oos_summary"]
        trades_per_year = 252 / holding_period
        total_trades = sum(r["n_trades"] for r in wf["oos_by_window"])
        years = total_trades / trades_per_year if trades_per_year > 0 else 1
        annual_return = oos["avg_pnl_pct"] * trades_per_year
        print(f"\n[4C] Survivorship Bias Adjustment...")
        results["survivorship"] = survivorship_bias_adjustment(annual_return, years)
    else:
        results["survivorship"] = None

    # 4D: Transaction Cost Sensitivity
    print(f"\n[4D] Transaction Cost Sensitivity...")
    results["cost_sensitivity"] = transaction_cost_sensitivity(hist, holding_period=holding_period)

    return results


# ──────────────────────────────────────────────────────────────
# CLI runner
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import yfinance as yf
    import sys

    # Default tickers to test, or pass via command line
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]

    print("=" * 70)
    print("MODULE 4: Walk-Forward Backtest Evaluation")
    print("=" * 70)
    print(f"Tickers: {tickers}")
    print(f"Fetching 5+ years of history for meaningful walk-forward...\n")

    all_results = {}
    for ticker in tickers:
        print(f"\n{'='*70}")
        print(f"  {ticker}")
        print(f"{'='*70}")

        try:
            hist = yf.download(ticker, period="6y", progress=False)
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.get_level_values(0)
            if hist.empty or len(hist) < 1000:
                print(f"  Skipping {ticker}: not enough data ({len(hist)} rows)")
                continue

            results = run_all_backtest_eval(hist, ticker=ticker)
            all_results[ticker] = results
        except Exception as e:
            print(f"  ERROR on {ticker}: {e}")
            continue

    # ── Print summary ──
    print("\n" + "=" * 70)
    print("SUMMARY — Walk-Forward Results")
    print("=" * 70)

    print(f"\n{'Ticker':<8} {'OOS Win%':>9} {'OOS P&L':>9} {'IS P&L':>9} "
          f"{'Overfit':>8} {'OOS Sharpe':>11} {'Windows':>8}")
    print("-" * 70)

    for ticker, res in all_results.items():
        wf = res.get("walk_forward", {})
        if wf.get("error"):
            print(f"{ticker:<8} ERROR: {wf['error']}")
            continue
        oos = wf["oos_summary"]
        is_ = wf["is_summary"]
        of = wf["overfit_ratio"]
        print(f"{ticker:<8} {oos['avg_win_rate']:>8.1f}% {oos['avg_pnl_pct']:>+8.3f}% "
              f"{is_['avg_pnl_pct']:>+8.3f}% {of:>7.2f}x {oos['avg_sharpe']:>10.3f} "
              f"{oos['n_windows']:>7}")

    # IV Sensitivity summary
    print(f"\n{'='*70}")
    print("IV Multiplier Sensitivity (first ticker)")
    print("=" * 70)
    first_ticker = list(all_results.keys())[0] if all_results else None
    if first_ticker:
        iv_sens = all_results[first_ticker].get("iv_sensitivity", [])
        if iv_sens:
            print(f"\n{'Mult':>6} {'Win%':>7} {'Avg P&L':>9} {'Total P&L':>10} "
                  f"{'MaxDD':>8} {'GREEN%':>8} {'GREEN P&L':>10}")
            print("-" * 60)
            for r in iv_sens:
                print(f"{r['multiplier']:>6.2f} {r['win_rate']:>6.1f}% {r['avg_pnl_pct']:>+8.3f}% "
                      f"{r['total_pnl_pct']:>+9.1f}% "
                      f"{r['max_drawdown_pct']:>+7.1f}% " if r['max_drawdown_pct'] else f"{'N/A':>8} ",
                      end="")
                print(f"{r['green_pct']:>7.0f}% "
                      f"{r['green_avg_pnl']:>+9.3f}%" if r['green_avg_pnl'] is not None else f"{'N/A':>10}")

    # Transaction cost summary
    if first_ticker:
        cost_sens = all_results[first_ticker].get("cost_sensitivity", [])
        if cost_sens:
            print(f"\n{'='*70}")
            print(f"Transaction Cost Sensitivity ({first_ticker})")
            print("=" * 70)
            print(f"\n{'Slippage':>10} {'Total Cost':>11} {'Avg P&L':>9} {'Win%':>7} {'Profitable':>11}")
            print("-" * 50)
            for r in cost_sens:
                print(f"${r['slippage']:>8.2f} ${r['total_cost_per_trade']:>9.2f} "
                      f"{r['avg_pnl_pct']:>+8.3f}% {r['win_rate']:>6.1f}% "
                      f"{'YES' if r['profitable'] else 'NO':>10}")
            if cost_sens[0].get("breakeven_slippage") is not None:
                print(f"\n  Break-even slippage: ${cost_sens[0]['breakeven_slippage']:.4f}/contract")

    # Survivorship bias
    if first_ticker:
        surv = all_results[first_ticker].get("survivorship")
        if surv:
            print(f"\n{'='*70}")
            print(f"Survivorship Bias Adjustment ({first_ticker})")
            print("=" * 70)
            print(f"  Raw annual return:      {surv['raw_annual_return_pct']:+.2f}%")
            print(f"  Haircut:                -{surv['haircut_pct_per_year']:.2f}%/year")
            print(f"  Adjusted annual return: {surv['adjusted_annual_return_pct']:+.2f}%")
            print(f"  Still profitable:       {'YES' if surv['still_profitable'] else 'NO'}")

    # ── Verdict ──
    print(f"\n{'='*70}")
    print("VERDICT")
    print("=" * 70)

    n_tested = len(all_results)
    if n_tested == 0:
        print("No tickers evaluated.")
    else:
        oos_positive = sum(
            1 for r in all_results.values()
            if not r.get("walk_forward", {}).get("error")
            and r["walk_forward"]["oos_summary"]["avg_pnl_pct"] > 0
        )
        overfit_flags = sum(
            1 for r in all_results.values()
            if not r.get("walk_forward", {}).get("error")
            and r["walk_forward"]["overfit_ratio"] > 2
        )

        print(f"  {oos_positive}/{n_tested} tickers have positive OOS P&L")
        print(f"  {overfit_flags}/{n_tested} tickers show overfitting (IS/OOS ratio > 2x)")

        if oos_positive >= n_tested * 0.6 and overfit_flags <= n_tested * 0.3:
            print("\n  PASS: Strategy shows robust out-of-sample performance.")
        elif oos_positive >= n_tested * 0.4:
            print("\n  MIXED: Strategy works on some tickers but not universally.")
        else:
            print("\n  FAIL: Strategy does not hold up out-of-sample.")
