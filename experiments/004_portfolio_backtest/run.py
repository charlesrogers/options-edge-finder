"""
Experiment 004: Portfolio-Level Backtest with Correct Methodology

Uses the ONE correct backtest engine. Tests multiple configurations.
"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
from backtest_engine import PortfolioBacktest, load_option_data, load_stock_data


def run_variant(label, tickers, option_data, stock_data, **kwargs):
    """Run one backtest variant and print results."""
    print(f"\n  --- {label} ---")
    bt = PortfolioBacktest(**kwargs)
    bt.run(tickers, option_data, stock_data)

    metrics = bt.get_portfolio_metrics()
    holdout = bt.holdout_validate()
    boot = bt.bootstrap()

    print(f"    Trades: {metrics['n_trades']}, Days: {metrics['n_days']}")
    print(f"    Win rate: {metrics['win_rate']}%")
    print(f"    Total P&L: ${metrics['total_pnl']:+,.2f}")
    print(f"    Daily Sharpe: {metrics['daily_sharpe']}")
    print(f"    Max DD: ${metrics['max_dd']:,.2f} ({metrics['max_dd_pct']:.1f}%)")
    print(f"    Avg open positions: {metrics['avg_positions']}")
    print(f"    Exits: {metrics['exit_reasons']}")
    print(f"    Repricing missing: {metrics['reprice_missing_pct']:.0f}%")
    print(f"    Skipped (at limit): {metrics['skipped_at_limit']}")

    if isinstance(holdout, dict) and 'error' not in holdout:
        print(f"    Holdout: train={holdout['train_sharpe']}, test={holdout['test_sharpe']}, "
              f"ratio={holdout['ratio']} {'PASS' if holdout['passed'] else 'FAIL'}")
    else:
        print(f"    Holdout: {holdout.get('error', 'N/A')}")

    print(f"    Bootstrap: Sharpe CI [{boot.get('sharpe_ci_lower', 'N/A')}, {boot.get('sharpe_ci_upper', 'N/A')}], "
          f"P(neg)={boot.get('prob_negative_return', 'N/A')}%")

    return {
        "label": label,
        "metrics": metrics,
        "holdout": holdout,
        "bootstrap": boot,
        "trades": [{"ticker": t.ticker, "entry": t.entry_date, "exit": t.exit_date,
                     "reason": t.exit_reason, "pnl": t.pnl, "days": t.days_held}
                    for t in bt.closed_trades],
    }


def main():
    print("=" * 70)
    print("EXPERIMENT 004: Portfolio-Level Backtest")
    print("Pre-registered: 2026-03-23")
    print("=" * 70)

    # Load all data
    tickers = ['AAPL', 'DIS', 'TXN', 'TMUS', 'KKR']

    print("\nLoading data...")
    option_data = {}
    stock_data = {}
    for ticker in tickers:
        print(f"  {ticker}...", end=" ", flush=True)
        od = load_option_data(ticker)
        sd = load_stock_data(ticker)
        if not od.empty and not sd.empty:
            option_data[ticker] = od
            stock_data[ticker] = sd
            print(f"options={len(od):,}, stock={len(sd)}")
        else:
            print("SKIPPED (no data)")

    available = list(option_data.keys())
    print(f"\nTickers with data: {available}")

    all_results = []

    # =========================================================
    print("\n" + "=" * 70)
    print("VARIANT 1: All tickers, put spread, max 3/ticker")
    print("=" * 70)
    r = run_variant("All tickers, spread, 3/ticker",
                     available, option_data, stock_data,
                     mode="spread", max_positions_per_ticker=3, max_total_positions=10)
    all_results.append(r)

    # =========================================================
    print("\n" + "=" * 70)
    print("VARIANT 2: AAPL only, put spread, max 3")
    print("=" * 70)
    r = run_variant("AAPL only, spread, 3",
                     ['AAPL'], option_data, stock_data,
                     mode="spread", max_positions_per_ticker=3, max_total_positions=3)
    all_results.append(r)

    # =========================================================
    print("\n" + "=" * 70)
    print("VARIANT 3: AAPL only, CSP, max 3")
    print("=" * 70)
    r = run_variant("AAPL only, CSP, 3",
                     ['AAPL'], option_data, stock_data,
                     mode="csp", max_positions_per_ticker=3, max_total_positions=3)
    all_results.append(r)

    # =========================================================
    print("\n" + "=" * 70)
    print("VARIANT 4: Position limit sweep (AAPL spread)")
    print("=" * 70)
    for max_pos in [1, 2, 3, 5]:
        r = run_variant(f"AAPL spread, max {max_pos}",
                         ['AAPL'], option_data, stock_data,
                         mode="spread", max_positions_per_ticker=max_pos,
                         max_total_positions=max_pos)
        all_results.append(r)

    # =========================================================
    print("\n" + "=" * 70)
    print("VARIANT 5: Take-profit sweep (AAPL spread, max 3)")
    print("=" * 70)
    for tp in [0.25, 0.50, 0.75, 1.0]:
        label = f"{tp:.0%}" if tp < 1 else "hold"
        r = run_variant(f"AAPL spread, TP={label}",
                         ['AAPL'], option_data, stock_data,
                         mode="spread", take_profit_pct=tp,
                         max_positions_per_ticker=3, max_total_positions=3)
        all_results.append(r)

    # =========================================================
    # SUMMARY
    # =========================================================
    print("\n" + "=" * 70)
    print("SUMMARY TABLE")
    print("=" * 70)
    print(f"{'Variant':<35s} {'Trades':>6s} {'Win%':>6s} {'P&L':>10s} {'Sharpe':>7s} {'MaxDD%':>7s} {'Holdout':>8s}")
    print("-" * 85)
    for r in all_results:
        m = r['metrics']
        h = r['holdout']
        holdout_str = "PASS" if isinstance(h, dict) and h.get('passed') else "FAIL"
        print(f"{r['label']:<35s} {m['n_trades']:>6d} {m['win_rate']:>5.1f}% "
              f"${m['total_pnl']:>+9,.0f} {m['daily_sharpe']:>6.3f} {m['max_dd_pct']:>6.1f}% {holdout_str:>8s}")

    # Pass/fail
    print("\n" + "=" * 70)
    print("PASS/FAIL ASSESSMENT")
    print("=" * 70)

    # Use the "all tickers" variant as the primary test
    primary = all_results[0]
    pm = primary['metrics']
    ph = primary['holdout']
    pb = primary['bootstrap']

    checks = {
        "Daily Sharpe > 0.3": pm['daily_sharpe'] > 0.3,
        "Max DD > -20%": pm['max_dd_pct'] > -20,
        "Holdout passed": isinstance(ph, dict) and ph.get('passed', False),
        "Bootstrap CI > 0": pb.get('sharpe_ci_lower', 0) > 0,
        "Win rate > 60%": pm['win_rate'] > 60,
    }

    for check, result in checks.items():
        print(f"  [{'PASS' if result else 'FAIL'}] {check}")

    all_pass = all(checks.values())
    print(f"\n  OVERALL: {'ALL PASSED — proceed to paper trading' if all_pass else 'FAILED — do not proceed'}")

    # Save
    output = {
        "variants": [{k: v for k, v in r.items() if k != "trades"} for r in all_results],
        "primary_checks": {k: v for k, v in checks.items()},
        "all_passed": all_pass,
    }
    out_path = os.path.join(os.path.dirname(__file__), "results.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
