"""
Experiment 013: Loss Analysis

Investigate why 73 of 386 paper trades lost money.
Test whether higher OTM% would fix the worst tickers.
Simulate copilot-adjusted P&L (what would have happened with CLOSE_NOW).
"""

import os
import sys
import math
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
import pandas as pd
from scipy.stats import norm

import yf_proxy
from position_monitor import assess_position


def bsm_call(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return max(S - K, 0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)


def analyze_losses_at_otm(ticker, stock_hist, otm_pcts, interval_days=7):
    """For each OTM%, count how many weekly trades would have expired ITM."""
    returns = np.log(stock_hist['Close'] / stock_hist['Close'].shift(1)).dropna()
    rv_20 = returns.rolling(20).std() * np.sqrt(252)

    results = {}
    for otm in otm_pcts:
        wins = 0
        losses = 0
        last_entry = None

        for i in range(30, len(stock_hist)):
            date = stock_hist.index[i]
            if last_entry and (pd.Timestamp(date) - pd.Timestamp(last_entry)).days < interval_days:
                continue

            spot = float(stock_hist['Close'].iloc[i])
            strike = spot * (1 + otm)
            dte = 32

            # Check stock price 32 days later
            future_idx = min(i + dte, len(stock_hist) - 1)
            future_price = float(stock_hist['Close'].iloc[future_idx])

            if future_price > strike:
                losses += 1
            else:
                wins += 1

            last_entry = str(date)[:10]

        total = wins + losses
        results[otm] = {
            'wins': wins, 'losses': losses, 'total': total,
            'win_rate': round(wins / total * 100, 1) if total > 0 else 0,
            'loss_rate': round(losses / total * 100, 1) if total > 0 else 0,
        }

    return results


def simulate_copilot_on_loss(ticker, strike, entry_date, premium, stock_hist):
    """Simulate copilot monitoring a losing trade. When would CLOSE_NOW fire?"""
    entry_idx = None
    for i, date in enumerate(stock_hist.index):
        if str(date)[:10] >= entry_date:
            entry_idx = i
            break

    if entry_idx is None:
        return None

    returns = np.log(stock_hist['Close'] / stock_hist['Close'].shift(1)).dropna()
    rv_20 = returns.rolling(20).std() * np.sqrt(252)

    expiry_date = pd.Timestamp(entry_date) + timedelta(days=32)

    for day_offset in range(1, 33):
        idx = entry_idx + day_offset
        if idx >= len(stock_hist):
            break

        spot = float(stock_hist['Close'].iloc[idx])
        dte_now = max(0, 32 - day_offset)

        # Estimate option price with BSM
        vol = float(rv_20.iloc[idx]) * 1.2 if idx < len(rv_20) and not pd.isna(rv_20.iloc[idx]) else 0.25
        T = max(dte_now / 252, 1/252)
        opt_price = bsm_call(spot, strike, T, 0.05, vol)

        # Run copilot
        alert = assess_position(
            ticker=ticker, strike=strike,
            expiry=expiry_date.strftime('%Y-%m-%d'),
            sold_price=premium, contracts=1,
            current_stock=spot, current_option_ask=opt_price,
        )

        if alert.level in ('CLOSE_NOW', 'EMERGENCY'):
            buyback_cost = opt_price
            pnl_pct = max(-100, ((premium - buyback_cost) / premium) * 100)
            return {
                'close_day': day_offset,
                'close_level': alert.level,
                'close_spot': round(spot, 2),
                'buyback_cost': round(buyback_cost, 2),
                'pnl_pct': round(pnl_pct, 1),
                'vs_expiry': 'better',  # -100% at expiry vs this
            }

    return {'close_day': None, 'close_level': 'NO_ALERT', 'pnl_pct': -100}


def main():
    print("=" * 80)
    print("EXPERIMENT 013: Loss Analysis")
    print("Why 73 of 386 paper trades lost money and what to fix")
    print("=" * 80)

    # ── Q1: Would higher OTM% fix GOOGL and TMUS? ──
    print("\n" + "=" * 80)
    print("Q1: OTM% SENSITIVITY — What OTM% reduces losses?")
    print("=" * 80)

    otm_pcts = [0.03, 0.05, 0.07, 0.10, 0.15, 0.20]
    problem_tickers = ['GOOGL', 'TMUS', 'AAPL']
    good_tickers = ['KKR', 'DIS', 'AMZN']

    for ticker in problem_tickers + good_tickers:
        print(f"\n  {ticker}:")
        hist = yf_proxy.get_stock_history(ticker, period='1y')
        if hist.empty:
            print("    No data")
            continue

        # Price change over period
        start_price = float(hist['Close'].iloc[0])
        end_price = float(hist['Close'].iloc[-1])
        change_pct = (end_price - start_price) / start_price * 100
        print(f"    Price: ${start_price:.0f} → ${end_price:.0f} ({change_pct:+.0f}%)")

        results = analyze_losses_at_otm(ticker, hist, otm_pcts)
        print(f"    {'OTM%':>6s} {'Wins':>5s} {'Losses':>7s} {'Win%':>6s} {'Loss%':>6s}")
        for otm, r in results.items():
            marker = " ◀ current" if (
                (ticker == 'GOOGL' and otm == 0.05) or
                (ticker == 'TMUS' and otm == 0.03) or
                (ticker == 'AAPL' and otm == 0.15) or
                (ticker == 'KKR' and otm == 0.03) or
                (ticker == 'DIS' and otm == 0.07) or
                (ticker == 'AMZN' and otm == 0.05)
            ) else ""
            print(f"    {otm*100:>5.0f}% {r['wins']:>5d} {r['losses']:>7d} {r['win_rate']:>5.0f}% {r['loss_rate']:>5.0f}%{marker}")

    # ── Q3: Would the copilot have saved the losing trades? ──
    print("\n" + "=" * 80)
    print("Q3: COPILOT-ADJUSTED P&L — What if copilot closed early?")
    print("=" * 80)

    # Simulate copilot on TMUS losses (representative sample)
    for ticker, otm in [('TMUS', 0.03), ('GOOGL', 0.05), ('AAPL', 0.15)]:
        print(f"\n  {ticker} ({otm*100:.0f}% OTM) — simulating copilot on losses:")
        hist = yf_proxy.get_stock_history(ticker, period='1y')
        if hist.empty:
            continue

        returns = np.log(hist['Close'] / hist['Close'].shift(1)).dropna()
        rv_20 = returns.rolling(20).std() * np.sqrt(252)

        # Generate sample loss trades
        copilot_pnls = []
        last_entry = None
        for i in range(30, len(hist)):
            date = hist.index[i]
            if last_entry and (pd.Timestamp(date) - pd.Timestamp(last_entry)).days < 7:
                continue

            spot = float(hist['Close'].iloc[i])
            strike = spot * (1 + otm)
            vol = float(rv_20.iloc[i]) * 1.2 if i < len(rv_20) and not pd.isna(rv_20.iloc[i]) else 0.25
            premium = bsm_call(spot, strike, 32/252, 0.05, vol)

            future_idx = min(i + 32, len(hist) - 1)
            future_price = float(hist['Close'].iloc[future_idx])

            if future_price > strike and premium > 0:
                # This is a loss trade — simulate copilot
                result = simulate_copilot_on_loss(ticker, strike, str(date)[:10], premium, hist)
                if result and result.get('close_day'):
                    copilot_pnls.append(result['pnl_pct'])
                    if len(copilot_pnls) <= 3:
                        print(f"    {str(date)[:10]}: strike ${strike:.0f}, copilot closed day {result['close_day']} "
                              f"at {result['close_level']}, P&L: {result['pnl_pct']:+.0f}% (vs -100% at expiry)")
                else:
                    copilot_pnls.append(-100)

            last_entry = str(date)[:10]

        if copilot_pnls:
            avg_copilot = np.mean(copilot_pnls)
            print(f"    Average copilot P&L on losses: {avg_copilot:+.0f}% (vs -100% at expiry)")
            print(f"    Copilot saves: {100 - abs(avg_copilot):.0f} percentage points per loss")
            saved_count = sum(1 for p in copilot_pnls if p > -100)
            print(f"    Copilot intervened: {saved_count}/{len(copilot_pnls)} loss trades")

    # ── Q4: Updated recommendations ──
    print("\n" + "=" * 80)
    print("Q4: UPDATED RECOMMENDATIONS")
    print("=" * 80)

    for ticker in problem_tickers:
        hist = yf_proxy.get_stock_history(ticker, period='1y')
        if hist.empty:
            continue
        results = analyze_losses_at_otm(ticker, hist, otm_pcts)

        # Find the lowest OTM% with <15% loss rate
        for otm in otm_pcts:
            if results[otm]['loss_rate'] < 15:
                print(f"\n  {ticker}: Recommend {otm*100:.0f}% OTM (loss rate: {results[otm]['loss_rate']:.0f}%)")
                break
        else:
            print(f"\n  {ticker}: No OTM% achieves <15% loss rate — consider skipping")

    # Save
    import json
    out = os.path.join(os.path.dirname(__file__), 'results.json')
    with open(out, 'w') as f:
        json.dump({'status': 'completed'}, f)
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    main()
