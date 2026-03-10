"""
Module 6: Portfolio Risk
========================
Portfolio-level risk analysis for the multi-name option selling universe.

Sub-modules:
  6A: Crisis Correlation Modeling (normal vs crisis, effective independent bets)
  6B: Portfolio Vega Stress Test (10-point VIX spike impact)
  6C: Theta/Risk Ratios (theta-vega, theta-gamma, breakeven move)
  6D: Historical Stress Test (COVID, Volmageddon, Yen unwind scenarios)
"""

import numpy as np
import pandas as pd


# ──────────────────────────────────────────────────────────────
# 6A: Crisis Correlation Modeling
# ──────────────────────────────────────────────────────────────

def crisis_correlation_analysis(tickers: list, period: str = "2y") -> dict:
    """
    Compare normal vs crisis correlations across portfolio holdings.

    Normal: all days over the past period.
    Crisis: only days where SPY return < -1%.

    N_eff = N / (1 + (N-1) * avg_corr)
    Reveals how many truly independent bets you have.

    Args:
        tickers: List of ticker symbols in portfolio
        period: yfinance-style period string

    Returns:
        dict with normal/crisis correlations, N_eff, avg correlations
    """
    try:
        import yfinance as yf
    except ImportError:
        return {"error": "yfinance not installed"}

    if len(tickers) < 2:
        return {"error": "Need at least 2 tickers"}

    # Fetch all prices + SPY
    all_tickers = list(set(tickers + ["SPY"]))
    print(f"  Fetching {len(all_tickers)} tickers for correlation analysis...")

    try:
        data = yf.download(all_tickers, period=period, progress=False)
        if data.empty:
            return {"error": "No data returned from yfinance"}

        if isinstance(data.columns, pd.MultiIndex):
            prices = data["Close"]
        else:
            prices = data[["Close"]]
            prices.columns = all_tickers[:1]
    except Exception as e:
        return {"error": f"Download failed: {e}"}

    # Ensure we have columns for the tickers we need
    available = [t for t in tickers if t in prices.columns]
    if len(available) < 2:
        return {"error": f"Only {len(available)} tickers had data"}

    returns = prices.pct_change().dropna()

    if "SPY" not in returns.columns:
        return {"error": "SPY data missing"}

    spy_ret = returns["SPY"]
    port_ret = returns[available]

    # Normal correlation
    normal_corr = port_ret.corr()
    n = len(available)
    mask = np.triu(np.ones((n, n), dtype=bool), k=1)
    normal_vals = normal_corr.values[mask]
    avg_normal = float(np.mean(normal_vals)) if len(normal_vals) > 0 else 0

    # Crisis correlation (SPY < -1%)
    crisis_mask = spy_ret < -0.01
    n_crisis_days = int(crisis_mask.sum())

    if n_crisis_days >= 10:
        crisis_ret = port_ret[crisis_mask]
        crisis_corr = crisis_ret.corr()
        crisis_vals = crisis_corr.values[mask]
        avg_crisis = float(np.mean(crisis_vals)) if len(crisis_vals) > 0 else 0
    else:
        crisis_corr = None
        avg_crisis = None

    # Effective independent bets
    n_eff_normal = n / (1 + (n - 1) * avg_normal) if avg_normal < 1 else 1
    n_eff_crisis = n / (1 + (n - 1) * avg_crisis) if avg_crisis is not None and avg_crisis < 1 else 1

    # Top correlated pairs
    high_pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            c = normal_corr.iloc[i, j]
            if abs(c) > 0.7:
                high_pairs.append({
                    "pair": f"{available[i]} × {available[j]}",
                    "normal_corr": round(float(c), 3),
                    "crisis_corr": round(float(crisis_corr.iloc[i, j]), 3) if crisis_corr is not None else None,
                })

    return {
        "n_tickers": n,
        "n_available": len(available),
        "n_crisis_days": n_crisis_days,
        "n_total_days": len(returns),
        "avg_normal_corr": round(avg_normal, 3),
        "avg_crisis_corr": round(avg_crisis, 3) if avg_crisis is not None else None,
        "n_eff_normal": round(n_eff_normal, 1),
        "n_eff_crisis": round(n_eff_crisis, 1) if avg_crisis is not None else None,
        "diversification_illusion": round(n / n_eff_normal, 1) if n_eff_normal > 0 else None,
        "high_corr_pairs": sorted(high_pairs, key=lambda x: abs(x["normal_corr"]), reverse=True)[:10],
    }


# ──────────────────────────────────────────────────────────────
# 6B: Portfolio Vega Stress Test
# ──────────────────────────────────────────────────────────────

def portfolio_vega_stress(open_trades: list, portfolio_value: float = None) -> dict:
    """
    Estimate portfolio loss from a VIX spike.

    For each open position, estimate vega from trade parameters.
    Stress: 10-point VIX spike → portfolio_loss = sum(vega * 10) * contracts * 100

    Args:
        open_trades: List of trade dicts from get_open_trades()
        portfolio_value: Total portfolio value for % calculations

    Returns:
        dict with vega exposure, stress loss estimate
    """
    if not open_trades:
        return {"error": "No open trades"}

    positions = []
    total_vega = 0
    total_notional = 0

    for t in open_trades:
        try:
            spot = float(t.get("spot_at_open", 0) or t.get("spot_price", 0) or 100)
            strike = float(t.get("strike", spot))
            contracts = int(t.get("contracts", 1))
            premium = float(t.get("premium_received", 0))
            option_type = t.get("option_type", "call")

            # Estimate vega: ATM vega ≈ S * sqrt(T) * N'(d1) / 100
            # Simplified: vega ≈ spot * sqrt(DTE/365) * 0.4 / 100
            # (0.4 ≈ N'(0) for ATM)
            try:
                from datetime import datetime
                exp = datetime.strptime(t["expiration"], "%Y-%m-%d")
                dte = max((exp - datetime.now()).days, 1)
            except Exception:
                dte = 30

            vega_per_contract = spot * np.sqrt(dte / 365) * 0.4 / 100
            total_pos_vega = vega_per_contract * contracts
            notional = spot * 100 * contracts

            positions.append({
                "ticker": t.get("ticker", "?"),
                "type": option_type,
                "strike": strike,
                "contracts": contracts,
                "dte": dte,
                "vega_per_contract": round(vega_per_contract, 2),
                "total_vega": round(total_pos_vega, 2),
                "notional": round(notional, 0),
            })

            # Short options have negative vega (you lose when IV rises)
            total_vega -= total_pos_vega
            total_notional += notional

        except Exception:
            continue

    if not positions:
        return {"error": "Could not parse any trades"}

    # Stress scenarios
    stress_5pt = total_vega * 5 * 100   # 5-point VIX rise, * 100 for contract multiplier
    stress_10pt = total_vega * 10 * 100  # 10-point VIX rise
    stress_20pt = total_vega * 20 * 100  # 20-point VIX rise (Volmageddon-scale)

    result = {
        "n_positions": len(positions),
        "total_vega": round(total_vega, 2),
        "total_notional": round(total_notional, 0),
        "positions": positions,
        "stress_5pt_loss": round(stress_5pt, 0),
        "stress_10pt_loss": round(stress_10pt, 0),
        "stress_20pt_loss": round(stress_20pt, 0),
    }

    if portfolio_value and portfolio_value > 0:
        result["stress_5pt_pct"] = round(stress_5pt / portfolio_value * 100, 2)
        result["stress_10pt_pct"] = round(stress_10pt / portfolio_value * 100, 2)
        result["stress_20pt_pct"] = round(stress_20pt / portfolio_value * 100, 2)
        result["passes_5pct_test"] = abs(stress_10pt / portfolio_value) < 0.05

    return result


# ──────────────────────────────────────────────────────────────
# 6C: Theta/Risk Ratios
# ──────────────────────────────────────────────────────────────

def portfolio_theta_risk(open_trades: list) -> dict:
    """
    Portfolio-level Greeks ratios.

    theta_vega_ratio: days of theta to offset 1-point IV expansion
    breakeven_daily_move: sqrt(2 * theta / gamma) — stock move that wipes daily theta

    Args:
        open_trades: List of trade dicts
    """
    if not open_trades:
        return {"error": "No open trades"}

    total_theta = 0
    total_vega = 0
    total_gamma = 0
    total_delta = 0
    n_parsed = 0

    for t in open_trades:
        try:
            spot = float(t.get("spot_at_open", 0) or t.get("spot_price", 0) or 100)
            contracts = int(t.get("contracts", 1))

            try:
                from datetime import datetime
                exp = datetime.strptime(t["expiration"], "%Y-%m-%d")
                dte = max((exp - datetime.now()).days, 1)
            except Exception:
                dte = 30

            # Approximate Greeks for short ATM option
            # theta ≈ -S * σ * N'(0) / (2 * sqrt(T)) per share
            # Using σ ≈ 0.25 (25% vol), N'(0) ≈ 0.4
            sigma = 0.25
            T = dte / 365
            sqrt_T = np.sqrt(T)

            theta_per = -spot * sigma * 0.4 / (2 * sqrt_T) / 365  # daily, per share
            vega_per = spot * sqrt_T * 0.4 / 100  # per 1% IV move, per share
            gamma_per = 0.4 / (spot * sigma * sqrt_T)  # per share
            delta_per = 0.5  # ATM approximation

            # Short position: flip signs (seller benefits from theta)
            pos_theta = -theta_per * contracts * 100  # positive for seller
            pos_vega = -vega_per * contracts * 100     # negative for seller (lose on IV up)
            pos_gamma = -gamma_per * contracts * 100   # negative for seller
            pos_delta = -delta_per * contracts * 100

            total_theta += pos_theta
            total_vega += pos_vega
            total_gamma += pos_gamma
            total_delta += pos_delta
            n_parsed += 1

        except Exception:
            continue

    if n_parsed == 0:
        return {"error": "Could not parse any trades"}

    # Ratios
    theta_vega_ratio = abs(total_theta / total_vega) if total_vega != 0 else None
    breakeven_move = np.sqrt(abs(2 * total_theta / total_gamma)) if total_gamma != 0 else None

    return {
        "n_positions": n_parsed,
        "portfolio_theta_daily": round(total_theta, 2),
        "portfolio_vega": round(total_vega, 2),
        "portfolio_gamma": round(total_gamma, 4),
        "portfolio_delta": round(total_delta, 2),
        "theta_vega_ratio": round(theta_vega_ratio, 2) if theta_vega_ratio else None,
        "breakeven_daily_move": round(breakeven_move, 2) if breakeven_move else None,
    }


# ──────────────────────────────────────────────────────────────
# 6D: Historical Stress Test
# ──────────────────────────────────────────────────────────────

# Historical crisis parameters
STRESS_SCENARIOS = {
    "COVID Mar 2020": {
        "spy_drop_pct": -34.0,
        "vix_level": 82,
        "vix_change": 65,  # from ~17 to 82
        "corr_assumption": 0.95,
        "description": "Pandemic crash, circuit breakers, 35% SPY decline in 23 days",
    },
    "Volmageddon Feb 2018": {
        "spy_drop_pct": -10.0,
        "vix_level": 37,
        "vix_change": 20,  # from ~17 to 37
        "corr_assumption": 0.85,
        "description": "VIX doubles overnight, XIV goes to zero, vol selling blowup",
    },
    "Yen Unwind Aug 2024": {
        "spy_drop_pct": -8.0,
        "vix_level": 65,
        "vix_change": 50,  # intraday spike from ~15 to 65
        "corr_assumption": 0.90,
        "description": "BOJ rate hike triggers carry trade unwind, VIX intraday to 65",
    },
}


def historical_stress_test(open_trades: list, portfolio_value: float = None) -> dict:
    """
    Reprice portfolio under historical crisis scenarios.

    For each scenario, estimate:
    - Directional loss from SPY drop (using position delta and beta)
    - Vega loss from VIX spike
    - Combined estimated P&L

    Args:
        open_trades: List of trade dicts
        portfolio_value: Total portfolio value
    """
    if not open_trades:
        return {"error": "No open trades"}

    # First compute aggregate portfolio Greeks
    greeks = portfolio_theta_risk(open_trades)
    if greeks.get("error"):
        return greeks

    vega_stress = portfolio_vega_stress(open_trades, portfolio_value)

    results = {}
    for name, scenario in STRESS_SCENARIOS.items():
        # Vega loss: portfolio_vega * VIX change * 100
        vega_loss = greeks["portfolio_vega"] * scenario["vix_change"] * 100

        # Delta loss: portfolio_delta * spot_move
        # Approximate: SPY drop % * average notional * delta exposure
        total_notional = vega_stress.get("total_notional", 0)
        delta_loss = greeks["portfolio_delta"] * (scenario["spy_drop_pct"] / 100) * total_notional / 100
        # For short puts, delta loss is positive in a drop (you lose)
        # Sign convention: short put has negative delta, SPY drops, loss = -delta * -drop = positive loss

        combined_loss = vega_loss + delta_loss

        scenario_result = {
            "description": scenario["description"],
            "spy_drop_pct": scenario["spy_drop_pct"],
            "vix_level": scenario["vix_level"],
            "vix_change": scenario["vix_change"],
            "vega_loss": round(vega_loss, 0),
            "delta_loss": round(delta_loss, 0),
            "combined_loss": round(combined_loss, 0),
        }

        if portfolio_value and portfolio_value > 0:
            scenario_result["loss_pct"] = round(combined_loss / portfolio_value * 100, 2)
            scenario_result["surviving"] = abs(combined_loss / portfolio_value) < 0.25

        results[name] = scenario_result

    return results


# ──────────────────────────────────────────────────────────────
# Combined: Run all Module 6 tests
# ──────────────────────────────────────────────────────────────

def run_all_portfolio_risk(open_trades: list = None,
                           tickers: list = None,
                           portfolio_value: float = None) -> dict:
    """
    Run all portfolio risk analysis.

    Args:
        open_trades: Current open positions
        tickers: List of tickers for correlation analysis
        portfolio_value: Total portfolio value

    Returns:
        dict with all sub-module results
    """
    results = {}

    # 6A: Crisis Correlation
    if tickers and len(tickers) >= 2:
        print("[6A] Crisis correlation analysis...")
        results["crisis_corr"] = crisis_correlation_analysis(tickers)
    else:
        results["crisis_corr"] = {"error": "Need 2+ tickers for correlation analysis"}

    # 6B: Vega Stress
    if open_trades:
        print("[6B] Vega stress test...")
        results["vega_stress"] = portfolio_vega_stress(open_trades, portfolio_value)
    else:
        results["vega_stress"] = {"error": "No open trades"}

    # 6C: Theta/Risk Ratios
    if open_trades:
        print("[6C] Theta/risk ratios...")
        results["theta_risk"] = portfolio_theta_risk(open_trades)
    else:
        results["theta_risk"] = {"error": "No open trades"}

    # 6D: Historical Stress
    if open_trades:
        print("[6D] Historical stress test...")
        results["stress_test"] = historical_stress_test(open_trades, portfolio_value)
    else:
        results["stress_test"] = {"error": "No open trades"}

    return results


# ──────────────────────────────────────────────────────────────
# CLI runner
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from db import get_open_trades
    import sys

    print("=" * 70)
    print("MODULE 6: Portfolio Risk")
    print("=" * 70)

    trades = get_open_trades()
    print(f"[portfolio] {len(trades)} open trades loaded")

    if not trades:
        print("No open trades. Testing with correlation analysis on default tickers...")
        tickers = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META",
                    "AMZN", "GOOGL", "JPM", "GS", "XOM", "GLD", "IWM"]
    else:
        tickers = list(set(t.get("ticker", "") for t in trades if t.get("ticker")))

    portfolio_value = float(sys.argv[1]) if len(sys.argv) > 1 else None

    results = run_all_portfolio_risk(trades, tickers, portfolio_value)

    # ── Print results ──
    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)

    # 6A: Crisis Correlation
    print("\n--- 6A: Crisis Correlation ---")
    cc = results.get("crisis_corr", {})
    if cc.get("error"):
        print(f"  Error: {cc['error']}")
    else:
        print(f"  Tickers analyzed: {cc['n_available']}")
        print(f"  Total days: {cc['n_total_days']} ({cc['n_crisis_days']} crisis days)")
        print(f"\n  {'Metric':<30} {'Normal':>10} {'Crisis':>10}")
        print("  " + "-" * 52)
        print(f"  {'Avg pairwise correlation':<30} {cc['avg_normal_corr']:>10.3f} "
              f"{cc['avg_crisis_corr']:>10.3f}" if cc['avg_crisis_corr'] is not None else "")
        print(f"  {'Effective independent bets':<30} {cc['n_eff_normal']:>10.1f} "
              f"{cc['n_eff_crisis']:>10.1f}" if cc['n_eff_crisis'] is not None else "")

        if cc.get("diversification_illusion"):
            print(f"\n  Diversification illusion: {cc['diversification_illusion']:.1f}x "
                  f"(you think you have {cc['n_available']} bets but really have "
                  f"{cc['n_eff_normal']:.1f})")

        if cc["high_corr_pairs"]:
            print(f"\n  Highly correlated pairs (|r| > 0.7):")
            for p in cc["high_corr_pairs"][:5]:
                crisis_str = f", crisis={p['crisis_corr']:.3f}" if p.get("crisis_corr") else ""
                print(f"    {p['pair']}: normal={p['normal_corr']:.3f}{crisis_str}")

    # 6B: Vega Stress
    print("\n--- 6B: Vega Stress Test ---")
    vs = results.get("vega_stress", {})
    if vs.get("error"):
        print(f"  Error: {vs['error']}")
    else:
        print(f"  Positions: {vs['n_positions']}, Total vega: {vs['total_vega']:.2f}")
        print(f"  VIX +5:  ${vs['stress_5pt_loss']:+,.0f}")
        print(f"  VIX +10: ${vs['stress_10pt_loss']:+,.0f}")
        print(f"  VIX +20: ${vs['stress_20pt_loss']:+,.0f}")
        if vs.get("stress_10pt_pct") is not None:
            print(f"  10-pt loss as % portfolio: {vs['stress_10pt_pct']:+.1f}%")
            if vs["passes_5pct_test"]:
                print("  ✓ Passes 5% portfolio limit")
            else:
                print("  ✗ EXCEEDS 5% portfolio limit — reduce positions or hedge")

    # 6C: Theta/Risk
    print("\n--- 6C: Theta/Risk Ratios ---")
    tr = results.get("theta_risk", {})
    if tr.get("error"):
        print(f"  Error: {tr['error']}")
    else:
        print(f"  Daily theta: ${tr['portfolio_theta_daily']:+.2f}")
        print(f"  Portfolio vega: {tr['portfolio_vega']:.2f}")
        print(f"  Portfolio gamma: {tr['portfolio_gamma']:.4f}")
        if tr.get("theta_vega_ratio"):
            print(f"  Theta/Vega ratio: {tr['theta_vega_ratio']:.2f} "
                  f"(days of theta to offset 1-pt IV rise)")
        if tr.get("breakeven_daily_move"):
            print(f"  Breakeven daily move: ${tr['breakeven_daily_move']:.2f} "
                  f"(stock move that wipes one day's theta)")

    # 6D: Stress Test
    print("\n--- 6D: Historical Stress Tests ---")
    st_results = results.get("stress_test", {})
    if isinstance(st_results, dict) and st_results.get("error"):
        print(f"  Error: {st_results['error']}")
    elif isinstance(st_results, dict):
        for name, s in st_results.items():
            if isinstance(s, dict) and "combined_loss" in s:
                print(f"\n  {name}: {s['description']}")
                print(f"    SPY: {s['spy_drop_pct']:+.0f}%, VIX: {s['vix_level']} (+{s['vix_change']})")
                print(f"    Vega loss: ${s['vega_loss']:+,.0f}")
                print(f"    Delta loss: ${s['delta_loss']:+,.0f}")
                print(f"    Combined: ${s['combined_loss']:+,.0f}")
                if s.get("loss_pct") is not None:
                    print(f"    Portfolio impact: {s['loss_pct']:+.1f}%")
                    if s["surviving"]:
                        print(f"    ✓ Survivable (<25% loss)")
                    else:
                        print(f"    ✗ CRITICAL — loss exceeds 25% of portfolio")

    print(f"\n{'='*70}")
    print("VERDICT")
    print("=" * 70)

    issues = []
    positives = []

    if not cc.get("error"):
        if cc["n_eff_normal"] < 3:
            issues.append(f"Only {cc['n_eff_normal']:.1f} effective bets "
                          f"(despite {cc['n_available']} tickers)")
        else:
            positives.append(f"{cc['n_eff_normal']:.1f} effective independent bets")

    if not vs.get("error") and vs.get("passes_5pct_test") is False:
        issues.append("VIX +10 loss exceeds 5% of portfolio")
    elif not vs.get("error") and vs.get("passes_5pct_test") is True:
        positives.append("Vega exposure within 5% limit")

    if isinstance(st_results, dict):
        for name, s in st_results.items():
            if isinstance(s, dict) and s.get("surviving") is False:
                issues.append(f"{name} scenario: >{25}% portfolio loss")

    if positives:
        print("POSITIVES:")
        for p in positives:
            print(f"  + {p}")
    if issues:
        print("CONCERNS:")
        for i in issues:
            print(f"  - {i}")

    if not issues:
        print("\nPortfolio risk looks manageable.")
    else:
        print("\nPortfolio risk flags detected. Review position sizing and hedging.")
