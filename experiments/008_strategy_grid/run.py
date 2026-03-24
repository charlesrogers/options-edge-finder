"""
Experiment 008: Strategy Grid Search

Find the optimal covered call parameters across the tri-fold goal:
  1. Never get called away (0 assignments)
  2. Never lose money (net P&L > 0)
  3. Maximize premium income

Runs the copilot simulator across OTM% x DTE ranges x tickers.
Uses REAL Databento option prices.
"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd

# Import simulator from experiment 007
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '007_copilot_simulator'))
from run import simulate, load_data


# ============================================================
# Grid Parameters
# ============================================================

OTM_PCTS = [0.03, 0.05, 0.07, 0.10, 0.15]
DTE_RANGES = [
    (14, 30),   # Short monthly (~22 DTE target)
    (20, 45),   # Standard monthly (~30 DTE target)
    (30, 60),   # Long monthly (~45 DTE target)
]
TICKERS = ['AAPL', 'DIS', 'TXN', 'TMUS', 'KKR']


def score_trades(trades):
    """Compute the tri-fold scorecard for a set of trades."""
    if not trades:
        return {
            'num_trades': 0, 'assignments': 0, 'net_pnl': 0,
            'avg_pnl': 0, 'win_rate': 0, 'premium_retained_pct': 0,
            'worst_trade': 0, 'false_alarms': 0, 'false_alarm_cost': 0,
            'total_premium': 0, 'total_buyback': 0,
            'assignments_prevented': 0, 'tax_avoided': 0,
            'composite_score': 0,
        }

    total_premium = sum(t['sold_price'] for t in trades) * 100
    total_buyback = sum(t['buyback_price'] for t in trades) * 100
    net_pnl = sum(t['pnl_per_contract'] for t in trades)
    winners = [t for t in trades if t['pnl_per_contract'] >= 0]
    win_rate = len(winners) / len(trades) * 100 if trades else 0
    worst_trade = min(t['pnl_per_contract'] for t in trades) if trades else 0
    avg_pnl = net_pnl / len(trades) if trades else 0

    # Assignments: copilot should prevent all, but check
    assignments_prevented = sum(
        1 for t in trades
        if t['would_assign_at_expiry']
        and t['alert_at_close'] in ('CLOSE_NOW', 'EMERGENCY', 'CLOSE_SOON')
    )
    assignments_without_copilot = sum(1 for t in trades if t['would_assign_at_expiry'])

    # False alarms
    false_alarms = sum(
        1 for t in trades
        if t['alert_at_close'] in ('CLOSE_SOON', 'CLOSE_NOW')
        and not t['would_assign_at_expiry']
    )
    false_alarm_cost = sum(
        abs(t['pnl_per_contract']) for t in trades
        if t['alert_at_close'] in ('CLOSE_SOON', 'CLOSE_NOW')
        and not t['would_assign_at_expiry']
        and t['pnl_per_contract'] < 0
    )

    # Tax avoided
    tax_avoided = sum(t['tax_avoided'] for t in trades)

    # Premium retained
    premium_retained_pct = (net_pnl / total_premium * 100) if total_premium > 0 else 0

    # Composite score: 0 if any assignments slip through
    # Otherwise: reward net profit and penalize worst loss
    if assignments_without_copilot > assignments_prevented:
        composite_score = -999  # Assignment slipped through
    elif net_pnl <= 0:
        composite_score = net_pnl  # Negative = bad, but no assignment
    else:
        composite_score = (avg_pnl * win_rate / 100) - (abs(worst_trade) * 0.2)

    return {
        'num_trades': len(trades),
        'assignments': assignments_without_copilot - assignments_prevented,
        'assignments_prevented': assignments_prevented,
        'net_pnl': round(net_pnl, 2),
        'avg_pnl': round(avg_pnl, 2),
        'win_rate': round(win_rate, 1),
        'premium_retained_pct': round(premium_retained_pct, 1),
        'worst_trade': round(worst_trade, 2),
        'false_alarms': false_alarms,
        'false_alarm_cost': round(false_alarm_cost, 2),
        'total_premium': round(total_premium, 2),
        'total_buyback': round(total_buyback, 2),
        'tax_avoided': round(tax_avoided, 2),
        'composite_score': round(composite_score, 2),
    }


def run_grid():
    """Run the full parameter grid."""
    results = []
    total_combos = len(TICKERS) * len(OTM_PCTS) * len(DTE_RANGES)
    combo_num = 0

    for ticker in TICKERS:
        # Check if data exists
        raw_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'databento', 'raw')
        files = [f for f in os.listdir(raw_dir)
                 if f.startswith(f'{ticker}_ohlcv') and f.endswith('.dbn.zst')]
        if not files:
            print(f"  SKIP {ticker}: no Databento data")
            combo_num += len(OTM_PCTS) * len(DTE_RANGES)
            continue

        for otm_pct in OTM_PCTS:
            for min_dte, max_dte in DTE_RANGES:
                combo_num += 1
                label = f"{ticker} {otm_pct*100:.0f}% OTM, {min_dte}-{max_dte} DTE"
                print(f"  [{combo_num}/{total_combos}] {label}...", end=" ", flush=True)

                try:
                    trades, daily_log = simulate(
                        ticker=ticker,
                        otm_pct=otm_pct,
                        min_dte=min_dte,
                        max_dte=max_dte,
                    )
                    metrics = score_trades(trades)
                    results.append({
                        'ticker': ticker,
                        'otm_pct': otm_pct,
                        'min_dte': min_dte,
                        'max_dte': max_dte,
                        'dte_label': f"{min_dte}-{max_dte}",
                        **metrics,
                    })
                    print(f"{metrics['num_trades']} trades, PnL ${metrics['net_pnl']:+,.0f}, "
                          f"assign={metrics['assignments']}, win={metrics['win_rate']:.0f}%")
                except Exception as e:
                    print(f"FAILED: {e}")
                    results.append({
                        'ticker': ticker,
                        'otm_pct': otm_pct,
                        'min_dte': min_dte,
                        'max_dte': max_dte,
                        'dte_label': f"{min_dte}-{max_dte}",
                        'error': str(e),
                    })

    return results


def print_scorecard(results):
    """Print the tri-fold scorecard."""
    df = pd.DataFrame(results)
    df = df[df['num_trades'].notna() & (df['num_trades'] > 0)]

    if df.empty:
        print("No results to show.")
        return

    # ============================================================
    # OVERALL LEADERBOARD
    # ============================================================
    print("\n" + "=" * 90)
    print("TRI-FOLD SCORECARD: Which strategy wins?")
    print("=" * 90)

    print(f"\n{'Ticker':>6s} {'OTM%':>5s} {'DTE':>7s} | {'Trades':>6s} {'Win%':>5s} {'Net P&L':>9s} "
          f"{'Avg P&L':>8s} {'Worst':>8s} {'Assign':>6s} {'FA':>3s} {'Score':>8s}")
    print("-" * 90)

    # Sort by composite score descending
    sorted_df = df.sort_values('composite_score', ascending=False)
    for _, r in sorted_df.iterrows():
        assign_str = f"{int(r.get('assignments', 0))}" if r.get('assignments', 0) == 0 else f"**{int(r['assignments'])}**"
        print(f"{r['ticker']:>6s} {r['otm_pct']*100:>4.0f}% {r['dte_label']:>7s} | "
              f"{int(r['num_trades']):>6d} {r['win_rate']:>4.0f}% ${r['net_pnl']:>+8,.0f} "
              f"${r['avg_pnl']:>+7,.0f} ${r['worst_trade']:>+7,.0f} {assign_str:>6s} "
              f"{int(r.get('false_alarms', 0)):>3d} {r['composite_score']:>+8.1f}")

    # ============================================================
    # BEST STRATEGIES (0 assignments + positive P&L)
    # ============================================================
    print("\n" + "=" * 90)
    print("BEST STRATEGIES (0 assignments + positive net P&L)")
    print("=" * 90)

    best = df[(df['assignments'] == 0) & (df['net_pnl'] > 0)]
    if best.empty:
        print("\n  NO strategy achieved both 0 assignments AND positive P&L.")
        print("  The copilot prevents assignment but the strategy loses money on buybacks.")
        # Show closest to profitability
        zero_assign = df[df['assignments'] == 0].sort_values('net_pnl', ascending=False)
        if not zero_assign.empty:
            print(f"\n  Closest to profitability (0 assignments):")
            for _, r in zero_assign.head(5).iterrows():
                print(f"    {r['ticker']} {r['otm_pct']*100:.0f}% OTM {r['dte_label']} DTE: "
                      f"${r['net_pnl']:+,.0f} net, {r['win_rate']:.0f}% win rate")
    else:
        best_sorted = best.sort_values('composite_score', ascending=False)
        print(f"\n  Found {len(best)} profitable strategies with zero assignments!\n")
        for _, r in best_sorted.iterrows():
            print(f"  {r['ticker']} {r['otm_pct']*100:.0f}% OTM, {r['dte_label']} DTE:")
            print(f"    Net P&L: ${r['net_pnl']:+,.0f} | Win: {r['win_rate']:.0f}% | "
                  f"Avg: ${r['avg_pnl']:+,.0f}/trade | Worst: ${r['worst_trade']:+,.0f}")
            print(f"    Premium retained: {r['premium_retained_pct']:.0f}% | "
                  f"False alarms: {int(r['false_alarms'])} (${r['false_alarm_cost']:,.0f})")

    # ============================================================
    # OTM% AGGREGATED VIEW
    # ============================================================
    print("\n" + "=" * 90)
    print("OTM% COMPARISON (averaged across tickers and DTE ranges)")
    print("=" * 90)

    for otm in OTM_PCTS:
        subset = df[df['otm_pct'] == otm]
        if subset.empty:
            continue
        avg_pnl = subset['net_pnl'].mean()
        avg_win = subset['win_rate'].mean()
        total_assigns = int(subset['assignments'].sum())
        avg_trades = subset['num_trades'].mean()
        avg_worst = subset['worst_trade'].mean()
        profitable = len(subset[subset['net_pnl'] > 0])
        print(f"\n  {otm*100:.0f}% OTM: avg P&L ${avg_pnl:+,.0f} | win {avg_win:.0f}% | "
              f"assigns {total_assigns} | worst ${avg_worst:+,.0f} | "
              f"profitable {profitable}/{len(subset)} combos")

    return df


def main():
    print("=" * 90)
    print("EXPERIMENT 008: Strategy Grid Search — Tri-Fold Optimization")
    print("Find the covered call parameters that maximize ALL THREE goals")
    print("=" * 90)

    results = run_grid()

    if not results:
        print("No results generated.")
        return

    df = print_scorecard(results)

    # Save
    out = os.path.join(os.path.dirname(__file__), 'results.json')
    with open(out, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    main()
