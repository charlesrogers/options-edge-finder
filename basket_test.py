"""
Basket Performance Tester
=========================
Runs the full eval pipeline on a sample basket of tickers and tracks
results over time. Designed to answer: "Does this strategy actually work?"

Usage:
  python3 basket_test.py                    # Run on default basket
  python3 basket_test.py SPY QQQ AAPL      # Run on custom tickers
  python3 basket_test.py --quick            # Quick mode (5 tickers)

Results are saved to basket_results/ directory and Supabase (if configured).
"""

import numpy as np
import pandas as pd
import json
import os
import sys
from datetime import datetime

from eval_backtest import walk_forward_backtest, iv_multiplier_sensitivity, survivorship_bias_adjustment
from eval_risk import calc_cvar, calc_max_drawdown, calc_omega_ratio, calc_sortino_ratio


# ──────────────────────────────────────────────────────────────
# Sample Baskets
# ──────────────────────────────────────────────────────────────

# Diversified 20-ticker basket: the "dad portfolio" for covered call/put selling
CORE_BASKET = [
    # Index ETFs (highest liquidity)
    "SPY", "QQQ", "IWM",
    # Mega-cap tech (biggest option markets)
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META",
    # Finance
    "JPM", "GS",
    # Healthcare
    "UNH", "JNJ",
    # Consumer
    "WMT", "HD", "DIS",
    # Energy
    "XOM",
    # Commodities
    "GLD",
    # Industrial
    "BA",
    # Telecom
    "T",
]

# Quick test basket (5 most liquid)
QUICK_BASKET = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]

# Full universe (top 50 by options volume)
FULL_BASKET = [
    "SPY", "QQQ", "IWM", "DIA",
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD", "NFLX",
    "JPM", "GS", "BAC", "V", "MA",
    "UNH", "JNJ", "PFE", "LLY", "ABBV",
    "WMT", "HD", "COST", "DIS", "NKE", "SBUX", "MCD",
    "XOM", "CVX", "COP",
    "GLD", "SLV", "TLT",
    "BA", "CAT", "GE", "HON",
    "T", "VZ",
    "XLF", "XLE", "XLK", "XLV",
    "SOXX", "SMH",
    "PLTR", "COIN", "SOFI",
]


# ──────────────────────────────────────────────────────────────
# Core: Run backtest on a single ticker
# ──────────────────────────────────────────────────────────────

def test_ticker(ticker: str, hist: pd.DataFrame, holding_period: int = 20) -> dict:
    """
    Run full evaluation on one ticker.

    Returns:
        dict with backtest results, risk metrics, signal quality
    """
    result = {"ticker": ticker, "n_days": len(hist)}

    # One-pass backtest (quick)
    from analytics import backtest_vrp_strategy, summarize_backtest
    bt = backtest_vrp_strategy(hist, window=20, holding_period=holding_period)
    if bt is not None and not bt.empty:
        summary = summarize_backtest(bt)
        pnl = bt["pnl_pct"]

        result["one_pass"] = {
            "n_trades": len(bt),
            "overall_win_rate": round(float(bt["seller_wins"].mean() * 100), 1),
            "overall_avg_pnl": round(float(pnl.mean()), 4),
            "overall_total_pnl": round(float(pnl.sum()), 2),
            "overall_sharpe": round(float(pnl.mean() / pnl.std()), 4) if pnl.std() > 0 else 0,
            "skewness": round(float(pnl.skew()), 3),
            "by_signal": summary,
        }

        # Risk metrics on one-pass P&L
        result["risk"] = {
            "cvar": calc_cvar(pnl),
            "max_drawdown": calc_max_drawdown(pnl),
            "omega": calc_omega_ratio(pnl),
            "sortino": calc_sortino_ratio(pnl, holding_days=holding_period),
        }

        # GREEN-only metrics (what we actually recommend trading)
        green = bt[bt["signal"] == "GREEN"]
        if len(green) >= 10:
            g_pnl = green["pnl_pct"]
            result["green_only"] = {
                "n_trades": len(green),
                "win_rate": round(float(green["seller_wins"].mean() * 100), 1),
                "avg_pnl": round(float(g_pnl.mean()), 4),
                "total_pnl": round(float(g_pnl.sum()), 2),
                "sharpe": round(float(g_pnl.mean() / g_pnl.std()), 4) if g_pnl.std() > 0 else 0,
                "worst": round(float(g_pnl.min()), 2),
            }
    else:
        result["one_pass"] = {"error": "Not enough data for backtest"}

    # Walk-forward (if enough history)
    if len(hist) >= 1100:
        wf = walk_forward_backtest(hist, holding_period=holding_period)
        if not wf.get("error"):
            result["walk_forward"] = {
                "n_windows": wf["oos_summary"]["n_windows"],
                "oos_win_rate": wf["oos_summary"]["avg_win_rate"],
                "oos_avg_pnl": wf["oos_summary"]["avg_pnl_pct"],
                "oos_sharpe": wf["oos_summary"]["avg_sharpe"],
                "is_avg_pnl": wf["is_summary"]["avg_pnl_pct"],
                "overfit_ratio": wf["overfit_ratio"],
            }
        else:
            result["walk_forward"] = {"error": wf["error"]}
    else:
        result["walk_forward"] = {"error": f"Need 1100+ days, have {len(hist)}"}

    return result


# ──────────────────────────────────────────────────────────────
# Run basket test
# ──────────────────────────────────────────────────────────────

def run_basket_test(tickers: list, period: str = "6y",
                    holding_period: int = 20) -> dict:
    """
    Run full evaluation on a basket of tickers.

    Returns comprehensive results with per-ticker and aggregate stats.
    """
    import yfinance as yf

    print(f"{'='*70}")
    print(f"BASKET TEST — {len(tickers)} tickers")
    print(f"Period: {period}, Holding: {holding_period}d")
    print(f"{'='*70}")

    results = {
        "run_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "n_tickers": len(tickers),
        "period": period,
        "holding_period": holding_period,
        "tickers": {},
    }

    for i, ticker in enumerate(tickers):
        print(f"\n[{i+1}/{len(tickers)}] {ticker}...")
        try:
            hist = yf.download(ticker, period=period, progress=False)
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.get_level_values(0)

            if hist.empty or len(hist) < 252:
                print(f"  Skipping: only {len(hist)} rows")
                results["tickers"][ticker] = {"error": f"Insufficient data ({len(hist)} rows)"}
                continue

            result = test_ticker(ticker, hist, holding_period)
            results["tickers"][ticker] = result

            # Print quick summary
            op = result.get("one_pass", {})
            if not op.get("error"):
                green = result.get("green_only", {})
                print(f"  One-pass: win={op['overall_win_rate']:.0f}%, "
                      f"P&L={op['overall_avg_pnl']:+.3f}%, "
                      f"Sharpe={op['overall_sharpe']:.3f}")
                if green:
                    print(f"  GREEN:    win={green['win_rate']:.0f}%, "
                          f"P&L={green['avg_pnl']:+.3f}%, "
                          f"n={green['n_trades']}")

                wf = result.get("walk_forward", {})
                if not wf.get("error"):
                    print(f"  OOS:      win={wf['oos_win_rate']:.0f}%, "
                          f"P&L={wf['oos_avg_pnl']:+.3f}%, "
                          f"overfit={wf['overfit_ratio']:.2f}x")

        except Exception as e:
            print(f"  ERROR: {e}")
            results["tickers"][ticker] = {"error": str(e)}

    # ── Aggregate ──
    results["aggregate"] = _compute_aggregate(results["tickers"])

    return results


def _compute_aggregate(ticker_results: dict) -> dict:
    """Compute aggregate stats across all tickers."""
    one_pass_pnls = []
    one_pass_wins = []
    green_pnls = []
    green_wins = []
    oos_pnls = []
    oos_wins = []
    overfit_ratios = []
    sharpes = []

    for ticker, r in ticker_results.items():
        if isinstance(r, dict) and r.get("error"):
            continue

        op = r.get("one_pass", {})
        if not op.get("error"):
            one_pass_pnls.append(op["overall_avg_pnl"])
            one_pass_wins.append(op["overall_win_rate"])
            sharpes.append(op["overall_sharpe"])

        green = r.get("green_only", {})
        if green and not green.get("error"):
            green_pnls.append(green["avg_pnl"])
            green_wins.append(green["win_rate"])

        wf = r.get("walk_forward", {})
        if not wf.get("error"):
            oos_pnls.append(wf["oos_avg_pnl"])
            oos_wins.append(wf["oos_win_rate"])
            overfit_ratios.append(wf["overfit_ratio"])

    agg = {
        "n_successful": len(one_pass_pnls),
        "n_with_oos": len(oos_pnls),
    }

    if one_pass_pnls:
        agg["one_pass"] = {
            "avg_win_rate": round(float(np.mean(one_pass_wins)), 1),
            "avg_pnl": round(float(np.mean(one_pass_pnls)), 4),
            "median_pnl": round(float(np.median(one_pass_pnls)), 4),
            "pct_profitable": round(sum(1 for p in one_pass_pnls if p > 0) / len(one_pass_pnls) * 100, 0),
            "avg_sharpe": round(float(np.mean(sharpes)), 4),
            "worst_ticker_pnl": round(float(min(one_pass_pnls)), 4),
            "best_ticker_pnl": round(float(max(one_pass_pnls)), 4),
        }

    if green_pnls:
        agg["green_only"] = {
            "avg_win_rate": round(float(np.mean(green_wins)), 1),
            "avg_pnl": round(float(np.mean(green_pnls)), 4),
            "median_pnl": round(float(np.median(green_pnls)), 4),
            "pct_profitable": round(sum(1 for p in green_pnls if p > 0) / len(green_pnls) * 100, 0),
        }

    if oos_pnls:
        agg["walk_forward"] = {
            "avg_win_rate": round(float(np.mean(oos_wins)), 1),
            "avg_pnl": round(float(np.mean(oos_pnls)), 4),
            "median_pnl": round(float(np.median(oos_pnls)), 4),
            "pct_profitable_oos": round(sum(1 for p in oos_pnls if p > 0) / len(oos_pnls) * 100, 0),
            "avg_overfit_ratio": round(float(np.mean(overfit_ratios)), 2),
        }

        # Survivorship adjustment on OOS results
        avg_oos = float(np.mean(oos_pnls))
        trades_per_year = 252 / 20  # ~12.6
        annual_oos = avg_oos * trades_per_year
        surv = survivorship_bias_adjustment(annual_oos, 3.0)
        agg["survivorship_adjusted"] = surv

    return agg


# ──────────────────────────────────────────────────────────────
# Save / Load results
# ──────────────────────────────────────────────────────────────

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "basket_results")


def save_results(results: dict, filename: str = None):
    """Save results to JSON file for historical tracking."""
    os.makedirs(RESULTS_DIR, exist_ok=True)

    if filename is None:
        filename = f"basket_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    filepath = os.path.join(RESULTS_DIR, filename)

    # Make JSON-serializable
    def clean(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, pd.Timestamp):
            return str(obj)
        if isinstance(obj, (dict,)):
            return {k: clean(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [clean(v) for v in obj]
        return obj

    clean_results = clean(results)
    with open(filepath, "w") as f:
        json.dump(clean_results, f, indent=2, default=str)

    print(f"\nResults saved to {filepath}")
    return filepath


def load_all_results() -> list:
    """Load all historical basket results for comparison."""
    if not os.path.exists(RESULTS_DIR):
        return []

    results = []
    for fname in sorted(os.listdir(RESULTS_DIR)):
        if fname.endswith(".json"):
            with open(os.path.join(RESULTS_DIR, fname)) as f:
                try:
                    data = json.load(f)
                    data["_filename"] = fname
                    results.append(data)
                except Exception:
                    continue
    return results


# ──────────────────────────────────────────────────────────────
# Save to Supabase for cloud tracking
# ──────────────────────────────────────────────────────────────

def save_to_supabase(results: dict):
    """Save aggregate basket results to Supabase for cross-session tracking."""
    try:
        from db import _get_supabase
        sb = _get_supabase()
        if not sb:
            return False

        agg = results.get("aggregate", {})
        op = agg.get("one_pass", {})
        gr = agg.get("green_only", {})
        wf = agg.get("walk_forward", {})

        row = {
            "run_date": results["run_date"],
            "n_tickers": results["n_tickers"],
            "n_successful": agg.get("n_successful", 0),
            "holding_period": results["holding_period"],
            "avg_win_rate": op.get("avg_win_rate"),
            "avg_pnl_pct": op.get("avg_pnl"),
            "avg_sharpe": op.get("avg_sharpe"),
            "green_avg_pnl": gr.get("avg_pnl"),
            "green_win_rate": gr.get("avg_win_rate"),
            "oos_avg_pnl": wf.get("avg_pnl"),
            "oos_win_rate": wf.get("avg_win_rate"),
            "avg_overfit_ratio": wf.get("avg_overfit_ratio"),
        }

        sb.table("basket_results").insert(row).execute()
        print("[supabase] Basket results saved")
        return True
    except Exception as e:
        print(f"[supabase] Could not save basket results: {e}")
        return False


# ──────────────────────────────────────────────────────────────
# Print report
# ──────────────────────────────────────────────────────────────

def print_report(results: dict):
    """Print a formatted report of basket test results."""
    agg = results.get("aggregate", {})

    print(f"\n{'='*70}")
    print(f"BASKET TEST REPORT — {results['run_date']}")
    print(f"{'='*70}")
    print(f"Tickers: {results['n_tickers']} requested, "
          f"{agg.get('n_successful', 0)} successful, "
          f"{agg.get('n_with_oos', 0)} with walk-forward")

    # Per-ticker table
    print(f"\n{'Ticker':<8} {'Win%':>6} {'AvgP&L':>8} {'Sharpe':>7} "
          f"{'GreenP&L':>9} {'OOS P&L':>8} {'Overfit':>8}")
    print("-" * 62)

    for ticker, r in sorted(results["tickers"].items()):
        if isinstance(r, dict) and r.get("error"):
            print(f"{ticker:<8} {'ERROR':>6} {str(r['error'])[:40]}")
            continue

        op = r.get("one_pass", {})
        gr = r.get("green_only", {})
        wf = r.get("walk_forward", {})

        win = f"{op['overall_win_rate']:.0f}%" if not op.get("error") else "N/A"
        pnl = f"{op['overall_avg_pnl']:+.3f}%" if not op.get("error") else "N/A"
        shp = f"{op['overall_sharpe']:.3f}" if not op.get("error") else "N/A"
        gpnl = f"{gr['avg_pnl']:+.3f}%" if gr and not gr.get("error") else "N/A"
        opnl = f"{wf['oos_avg_pnl']:+.3f}%" if not wf.get("error") else "N/A"
        ofit = f"{wf['overfit_ratio']:.2f}x" if not wf.get("error") else "N/A"

        print(f"{ticker:<8} {win:>6} {pnl:>8} {shp:>7} {gpnl:>9} {opnl:>8} {ofit:>8}")

    # Aggregate
    op = agg.get("one_pass", {})
    gr = agg.get("green_only", {})
    wf = agg.get("walk_forward", {})

    if op:
        print(f"\n{'='*70}")
        print("AGGREGATE — One-Pass Backtest")
        print(f"{'='*70}")
        print(f"  Avg win rate:        {op['avg_win_rate']:.1f}%")
        print(f"  Avg P&L per trade:   {op['avg_pnl']:+.4f}%")
        print(f"  Median P&L:          {op['median_pnl']:+.4f}%")
        print(f"  Avg Sharpe:          {op['avg_sharpe']:.4f}")
        print(f"  % tickers profitable: {op['pct_profitable']:.0f}%")
        print(f"  Best ticker:         {op['best_ticker_pnl']:+.4f}%")
        print(f"  Worst ticker:        {op['worst_ticker_pnl']:+.4f}%")

    if gr:
        print(f"\n  --- GREEN-only (what we recommend trading) ---")
        print(f"  Avg win rate:        {gr['avg_win_rate']:.1f}%")
        print(f"  Avg P&L per trade:   {gr['avg_pnl']:+.4f}%")
        print(f"  % tickers profitable: {gr['pct_profitable']:.0f}%")

    if wf:
        print(f"\n{'='*70}")
        print("AGGREGATE — Walk-Forward (Out-of-Sample)")
        print(f"{'='*70}")
        print(f"  Avg OOS win rate:     {wf['avg_win_rate']:.1f}%")
        print(f"  Avg OOS P&L:          {wf['avg_pnl']:+.4f}%")
        print(f"  % tickers OOS profit: {wf['pct_profitable_oos']:.0f}%")
        print(f"  Avg overfit ratio:    {wf['avg_overfit_ratio']:.2f}x")

    surv = agg.get("survivorship_adjusted")
    if surv:
        print(f"\n  --- Survivorship Bias Adjustment ---")
        print(f"  Raw annual return:      {surv['raw_annual_return_pct']:+.2f}%")
        print(f"  After -150bps haircut:  {surv['adjusted_annual_return_pct']:+.2f}%")
        print(f"  Still profitable:       {'YES' if surv['still_profitable'] else 'NO'}")

    # Verdict
    print(f"\n{'='*70}")
    print("VERDICT")
    print(f"{'='*70}")

    if not op:
        print("  No results to evaluate.")
        return

    issues = []
    positives = []

    if op["avg_pnl"] > 0:
        positives.append(f"Positive avg P&L ({op['avg_pnl']:+.4f}%)")
    else:
        issues.append(f"Negative avg P&L ({op['avg_pnl']:+.4f}%)")

    if op["pct_profitable"] >= 60:
        positives.append(f"{op['pct_profitable']:.0f}% of tickers profitable")
    elif op["pct_profitable"] < 50:
        issues.append(f"Only {op['pct_profitable']:.0f}% of tickers profitable")

    if gr and gr["avg_pnl"] > op["avg_pnl"]:
        positives.append("GREEN signals outperform overall — signals add value")
    elif gr:
        issues.append("GREEN signals don't outperform — signals may not be working")

    if wf:
        if wf["avg_pnl"] > 0:
            positives.append(f"Positive OOS P&L ({wf['avg_pnl']:+.4f}%) — strategy works out-of-sample")
        else:
            issues.append(f"Negative OOS P&L — strategy may be overfit")

        if wf["avg_overfit_ratio"] > 2:
            issues.append(f"High avg overfit ratio ({wf['avg_overfit_ratio']:.1f}x)")

    if surv and not surv["still_profitable"]:
        issues.append("Not profitable after survivorship bias adjustment")

    if positives:
        print("POSITIVES:")
        for p in positives:
            print(f"  + {p}")
    if issues:
        print("CONCERNS:")
        for i in issues:
            print(f"  - {i}")

    if not issues:
        print("\nStrategy passes all basket tests. Looks viable across the universe.")
    elif len(issues) <= 1:
        print("\nMostly positive with minor concerns. Strategy appears workable.")
    else:
        print("\nMultiple concerns. Review strategy parameters before deploying capital.")


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--quick" in args:
        args.remove("--quick")
        basket = QUICK_BASKET
        print("Quick mode: 5 tickers\n")
    elif "--full" in args:
        args.remove("--full")
        basket = FULL_BASKET
        print(f"Full mode: {len(FULL_BASKET)} tickers\n")
    elif args:
        basket = [t.upper().strip() for t in args]
    else:
        basket = CORE_BASKET
        print(f"Core basket: {len(CORE_BASKET)} tickers\n")

    results = run_basket_test(basket)

    # Save
    filepath = save_results(results)
    save_to_supabase(results)

    # Report
    print_report(results)

    # Show historical comparison if available
    history = load_all_results()
    if len(history) > 1:
        print(f"\n{'='*70}")
        print(f"HISTORICAL RUNS ({len(history)} total)")
        print(f"{'='*70}")
        print(f"{'Date':<20} {'Tickers':>8} {'AvgP&L':>8} {'GreenP&L':>9} {'OOS P&L':>8}")
        print("-" * 55)
        for h in history[-10:]:  # last 10
            ha = h.get("aggregate", {})
            hop = ha.get("one_pass", {})
            hgr = ha.get("green_only", {})
            hwf = ha.get("walk_forward", {})
            print(f"{h.get('run_date', '?'):<20} "
                  f"{h.get('n_tickers', '?'):>8} "
                  f"{hop.get('avg_pnl', 0):>+7.4f}% "
                  f"{hgr.get('avg_pnl', 0):>+8.4f}% "
                  f"{hwf.get('avg_pnl', 0):>+7.4f}%")
