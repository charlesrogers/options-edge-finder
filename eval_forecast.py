"""
eval_forecast.py — Module 1: GARCH Forecast Evaluation

Tests whether the GJR-GARCH(1,1,1) volatility forecast is any good by:
  1A. Mincer-Zarnowitz regression (is the forecast unbiased?)
  1B. HAR-RV alternative model (does a simpler model beat GARCH?)
  1C. Diebold-Mariano test (is the difference statistically significant?)
  1D. Forecast combination (should we blend GARCH + HAR-RV?)

Usage:
    python eval_forecast.py                    # Run on 20 default tickers
    python eval_forecast.py AAPL MSFT NVDA     # Run on specific tickers
    python eval_forecast.py --full             # Run on all 50 test tickers
"""

import sys
import numpy as np
import pandas as pd
from datetime import datetime
from scipy import stats as sp_stats


# ============================================================
# YANG-ZHANG REALIZED VARIANCE (benchmark truth)
# ============================================================

def yang_zhang_rv(hist, window=20):
    """
    Yang-Zhang realized variance for a window.
    Returns VARIANCE (not vol) — needed for regressions on variance.
    Uses OHLC data for 14x efficiency over close-to-close.
    """
    if len(hist) < window + 1:
        return np.nan

    recent = hist.tail(window + 1)

    overnight = np.log(recent["Open"].iloc[1:].values / recent["Close"].iloc[:-1].values)
    close_open = np.log(recent["Close"].iloc[1:].values / recent["Open"].iloc[1:].values)
    hi = np.log(recent["High"].iloc[1:].values / recent["Open"].iloc[1:].values)
    lo = np.log(recent["Low"].iloc[1:].values / recent["Open"].iloc[1:].values)
    cl = np.log(recent["Close"].iloc[1:].values / recent["Open"].iloc[1:].values)

    rs = (hi * (hi - cl) + lo * (lo - cl)).mean()
    n = window
    k = 0.34 / (1.34 + (n + 1) / (n - 1))

    overnight_var = overnight.var(ddof=1)
    close_open_var = close_open.var(ddof=1)
    yz_var = overnight_var + k * close_open_var + (1 - k) * rs

    # Return daily variance (not annualized)
    return max(yz_var, 1e-10)


def realized_variance_forward(hist, start_idx, window=20):
    """
    Realized variance over the NEXT `window` days from start_idx.
    Uses Yang-Zhang on the forward window. This is the 'truth' we forecast.
    """
    end_idx = start_idx + window + 1
    if end_idx > len(hist):
        return np.nan
    forward_slice = hist.iloc[start_idx:end_idx]
    return yang_zhang_rv(forward_slice, window)


# ============================================================
# 1A: GARCH FORECAST ENGINE
# ============================================================

def garch_rolling_forecasts(hist, train_window=252, forecast_horizon=20, step=1):
    """
    Generate rolling out-of-sample GARCH forecasts.

    For each step:
      - Train GJR-GARCH on the prior `train_window` days
      - Forecast variance over next `forecast_horizon` days
      - Record forecast vs realized (Yang-Zhang) variance

    Returns DataFrame with columns:
      date, forecast_var, realized_var
    """
    from arch import arch_model

    log_ret = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
    returns_pct = log_ret * 100

    results = []
    n = len(returns_pct)

    # Start from train_window, step forward
    total_steps = (n - train_window - forecast_horizon) // step
    print(f"  GARCH: {total_steps} forecast windows (train={train_window}, horizon={forecast_horizon})")

    for i in range(0, n - train_window - forecast_horizon, step):
        train_end = train_window + i
        train_data = returns_pct.iloc[i:train_end]

        try:
            model = arch_model(train_data, vol="Garch", p=1, o=1, q=1,
                               mean="Constant", rescale=False)
            result = model.fit(disp="off", show_warning=False)

            # Multi-step forecast: average daily variance over horizon
            forecast = result.forecast(horizon=forecast_horizon)
            # forecast.variance is in pct^2 units, convert back to decimal
            avg_daily_var_pct2 = forecast.variance.iloc[-1].mean()
            # Convert from pct^2 to decimal variance: divide by 100^2
            forecast_daily_var = avg_daily_var_pct2 / (100 ** 2)

            # Realized variance over the same forward window
            # Use the original hist (with OHLC) for Yang-Zhang
            hist_idx = hist.index[train_end] if train_end < len(hist) else None
            if hist_idx is None:
                continue

            # Map returns index position to hist position
            rv_start = train_end + 1  # +1 because log_ret drops first row
            realized_var = realized_variance_forward(hist, rv_start, forecast_horizon)

            if np.isnan(realized_var):
                continue

            results.append({
                "date": str(hist.index[rv_start]) if rv_start < len(hist) else "",
                "forecast_var": forecast_daily_var,
                "realized_var": realized_var,
            })

        except Exception:
            continue

        # Progress
        if len(results) % 50 == 0 and len(results) > 0:
            print(f"    ... {len(results)} forecasts generated")

    print(f"  GARCH: {len(results)} valid forecasts")
    return pd.DataFrame(results)


# ============================================================
# 1B: HAR-RV MODEL
# ============================================================

def har_rv_rolling_forecasts(hist, train_window=252, forecast_horizon=20, step=1):
    """
    HAR-RV (Heterogeneous Autoregressive) model for realized volatility.

    RV_t = c + β_d × RV_1d + β_w × RV_5d + β_m × RV_22d + ε

    Simple OLS, no iterative fitting. Often beats GARCH for equities.

    Returns DataFrame with same format as garch_rolling_forecasts.
    """
    # Pre-compute daily Yang-Zhang variance for all days
    daily_vars = []
    for i in range(1, len(hist)):
        if i < 2:
            daily_vars.append(np.nan)
            continue
        # Use 1-day YZ (need at least 2 rows for the calculation)
        window = min(i, 1)
        slc = hist.iloc[max(0, i - 1):i + 1]
        if len(slc) >= 2:
            o = np.log(slc["Open"].iloc[-1] / slc["Close"].iloc[-2])
            c = np.log(slc["Close"].iloc[-1] / slc["Open"].iloc[-1])
            h = np.log(slc["High"].iloc[-1] / slc["Open"].iloc[-1])
            l = np.log(slc["Low"].iloc[-1] / slc["Open"].iloc[-1])
            # Parkinson-like daily variance
            daily_var = max((h - l) ** 2 / (4 * np.log(2)), 1e-10)
            daily_vars.append(daily_var)
        else:
            daily_vars.append(np.nan)

    daily_vars = pd.Series(daily_vars, index=hist.index[1:])

    # Compute HAR components: RV_1d, RV_5d, RV_22d
    rv_1d = daily_vars
    rv_5d = daily_vars.rolling(5).mean()
    rv_22d = daily_vars.rolling(22).mean()

    # Forward realized variance (target)
    fwd_rv = daily_vars.rolling(forecast_horizon).mean().shift(-forecast_horizon)

    # Combine into regression DataFrame
    har_df = pd.DataFrame({
        "rv_1d": rv_1d,
        "rv_5d": rv_5d,
        "rv_22d": rv_22d,
        "fwd_rv": fwd_rv,
    }).dropna()

    results = []
    n = len(har_df)
    total_steps = (n - train_window) // step

    print(f"  HAR-RV: {total_steps} forecast windows (train={train_window}, horizon={forecast_horizon})")

    for i in range(0, n - train_window, step):
        train = har_df.iloc[i:i + train_window]
        test_idx = i + train_window

        if test_idx >= n:
            break

        # OLS fit on training window
        X_train = train[["rv_1d", "rv_5d", "rv_22d"]].values
        X_train = np.column_stack([np.ones(len(X_train)), X_train])  # add intercept
        y_train = train["fwd_rv"].values

        try:
            # OLS: β = (X'X)^{-1} X'y
            beta = np.linalg.lstsq(X_train, y_train, rcond=None)[0]

            # Forecast for test point
            test_row = har_df.iloc[test_idx]
            x_test = np.array([1, test_row["rv_1d"], test_row["rv_5d"], test_row["rv_22d"]])
            forecast_var = max(float(x_test @ beta), 1e-10)

            # Realized variance (the target we already computed)
            realized_var = test_row["fwd_rv"]

            results.append({
                "date": str(har_df.index[test_idx]),
                "forecast_var": forecast_var,
                "realized_var": realized_var,
            })
        except Exception:
            continue

        if len(results) % 50 == 0 and len(results) > 0:
            print(f"    ... {len(results)} forecasts generated")

    print(f"  HAR-RV: {len(results)} valid forecasts")
    return pd.DataFrame(results)


# ============================================================
# 1A: MINCER-ZARNOWITZ REGRESSION
# ============================================================

def mincer_zarnowitz(forecasts_df, model_name="Model"):
    """
    Mincer-Zarnowitz regression: RV_realized = α + β × σ²_forecast + ε

    Tests unbiasedness:
      - α = 0 (no constant bias)
      - β = 1 (forecast scales correctly)
      - Joint test: F-test for α=0, β=1

    Returns dict with results.
    """
    df = forecasts_df.dropna(subset=["forecast_var", "realized_var"])
    if len(df) < 30:
        return {"model": model_name, "status": "insufficient_data", "n": len(df)}

    y = df["realized_var"].values
    x = df["forecast_var"].values

    # OLS with intercept
    X = np.column_stack([np.ones(len(x)), x])
    beta_hat = np.linalg.lstsq(X, y, rcond=None)[0]
    alpha, beta = beta_hat[0], beta_hat[1]

    # Residuals and stats
    y_hat = X @ beta_hat
    resid = y - y_hat
    n = len(y)
    sse = float(np.sum(resid ** 2))
    sst = float(np.sum((y - y.mean()) ** 2))
    r_squared = 1 - sse / sst if sst > 0 else 0

    # Standard errors (OLS)
    mse = sse / (n - 2)
    var_beta = mse * np.linalg.inv(X.T @ X)
    se_alpha = np.sqrt(var_beta[0, 0])
    se_beta = np.sqrt(var_beta[1, 1])

    # t-tests
    t_alpha = alpha / se_alpha if se_alpha > 0 else 0
    t_beta = (beta - 1) / se_beta if se_beta > 0 else 0
    p_alpha = 2 * (1 - sp_stats.t.cdf(abs(t_alpha), n - 2))
    p_beta = 2 * (1 - sp_stats.t.cdf(abs(t_beta), n - 2))

    # Joint F-test: H0: α=0, β=1
    # F = [(R*β - r)'(R*Σ*R')^{-1}(R*β - r)] / q
    R = np.array([[1, 0], [0, 1]])
    r = np.array([0, 1])
    diff = beta_hat - r
    f_stat = float(diff @ np.linalg.inv(var_beta) @ diff) / 2
    p_joint = 1 - sp_stats.f.cdf(f_stat, 2, n - 2)

    # Diagnosis
    if p_joint > 0.05 and r_squared > 0.10:
        diagnosis = "well_calibrated"
    elif beta > 1.2:
        diagnosis = "biased_high"
    elif beta < 0.8:
        diagnosis = "biased_low"
    elif r_squared < 0.05:
        diagnosis = "poor_tracking"
    else:
        diagnosis = "marginally_calibrated"

    return {
        "model": model_name,
        "status": "ok",
        "n": n,
        "alpha": round(float(alpha), 8),
        "beta": round(float(beta), 4),
        "r_squared": round(r_squared, 4),
        "se_alpha": round(float(se_alpha), 8),
        "se_beta": round(float(se_beta), 4),
        "p_alpha": round(p_alpha, 4),
        "p_beta": round(p_beta, 4),
        "f_stat_joint": round(float(f_stat), 4),
        "p_joint": round(p_joint, 4),
        "diagnosis": diagnosis,
    }


# ============================================================
# 1C: DIEBOLD-MARIANO TEST
# ============================================================

def qlike_loss(forecast_var, realized_var):
    """
    QLIKE loss function: L = log(σ²) + RV²/σ²
    Preferred for vol forecasting (Patton 2011).
    Penalizes underestimation more than overestimation.
    """
    fv = np.maximum(forecast_var, 1e-12)
    return np.log(fv) + realized_var / fv


def diebold_mariano(garch_forecasts, harv_forecasts, model_a="GARCH", model_b="HAR-RV"):
    """
    Diebold-Mariano test comparing two forecast models using QLIKE loss.

    H0: Equal predictive accuracy
    Uses Newey-West HAC standard errors.

    Returns dict with test results.
    """
    # Align on common dates
    garch_df = garch_forecasts.set_index("date") if "date" in garch_forecasts.columns else garch_forecasts
    harv_df = harv_forecasts.set_index("date") if "date" in harv_forecasts.columns else harv_forecasts

    # Align by position (both have same number of rolling windows, slightly different sizes)
    min_len = min(len(garch_df), len(harv_df))
    if min_len < 30:
        return {"status": "insufficient_overlap", "n": min_len}

    # Use tail of longer series to align end dates
    garch_aligned = garch_df.tail(min_len).reset_index(drop=True)
    harv_aligned = harv_df.tail(min_len).reset_index(drop=True)

    # QLIKE losses
    loss_a = qlike_loss(garch_aligned["forecast_var"].values, garch_aligned["realized_var"].values)
    loss_b = qlike_loss(harv_aligned["forecast_var"].values, harv_aligned["realized_var"].values)

    # Loss differential
    d = loss_a - loss_b  # positive = GARCH is worse
    n = len(d)
    d_mean = np.mean(d)

    # Newey-West HAC standard error
    max_lag = int(np.floor(np.sqrt(n)))
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for lag in range(1, max_lag + 1):
        weight = 1 - lag / (max_lag + 1)  # Bartlett kernel
        gamma_j = np.cov(d[lag:], d[:-lag])[0, 1] if len(d) > lag else 0
        gamma_sum += 2 * weight * gamma_j

    hac_var = (gamma_0 + gamma_sum) / n
    hac_se = np.sqrt(max(hac_var, 1e-12))

    # DM statistic
    dm_stat = d_mean / hac_se
    p_value = 2 * (1 - sp_stats.norm.cdf(abs(dm_stat)))

    # Average losses
    avg_qlike_a = float(np.mean(loss_a))
    avg_qlike_b = float(np.mean(loss_b))

    # Winner
    if p_value < 0.05:
        winner = model_b if dm_stat > 0 else model_a
    else:
        winner = "no_significant_difference"

    return {
        "status": "ok",
        "n": n,
        "dm_statistic": round(float(dm_stat), 4),
        "p_value": round(float(p_value), 4),
        "winner": winner,
        f"avg_qlike_{model_a}": round(avg_qlike_a, 6),
        f"avg_qlike_{model_b}": round(avg_qlike_b, 6),
        "loss_diff_mean": round(float(d_mean), 6),
    }


# ============================================================
# 1D: FORECAST COMBINATION (ENCOMPASSING TEST)
# ============================================================

def encompassing_test(garch_forecasts, harv_forecasts):
    """
    Encompassing regression:
      RV_realized = α + β₁×GARCH + β₂×HAR-RV + ε

    If both β₁ and β₂ are significant, combine forecasts.
    If only one is significant, use that model alone.
    """
    garch_df = garch_forecasts.set_index("date") if "date" in garch_forecasts.columns else garch_forecasts
    harv_df = harv_forecasts.set_index("date") if "date" in harv_forecasts.columns else harv_forecasts

    min_len = min(len(garch_df), len(harv_df))
    if min_len < 30:
        return {"status": "insufficient_overlap", "n": min_len}

    garch_aligned = garch_df.tail(min_len).reset_index(drop=True)
    harv_aligned = harv_df.tail(min_len).reset_index(drop=True)

    y = garch_aligned["realized_var"].values
    x1 = garch_aligned["forecast_var"].values
    x2 = harv_aligned["forecast_var"].values

    X = np.column_stack([np.ones(len(y)), x1, x2])
    beta_hat = np.linalg.lstsq(X, y, rcond=None)[0]

    y_hat = X @ beta_hat
    resid = y - y_hat
    n = len(y)
    mse = np.sum(resid ** 2) / (n - 3)
    var_beta = mse * np.linalg.inv(X.T @ X)

    p_garch = 2 * (1 - sp_stats.t.cdf(abs(beta_hat[1] / np.sqrt(var_beta[1, 1])), n - 3))
    p_harv = 2 * (1 - sp_stats.t.cdf(abs(beta_hat[2] / np.sqrt(var_beta[2, 2])), n - 3))

    garch_sig = p_garch < 0.05
    harv_sig = p_harv < 0.05

    if garch_sig and harv_sig:
        recommendation = "combine"
        # Normalize weights (exclude intercept)
        total = abs(beta_hat[1]) + abs(beta_hat[2])
        garch_weight = abs(beta_hat[1]) / total
        harv_weight = abs(beta_hat[2]) / total
    elif garch_sig:
        recommendation = "GARCH_only"
        garch_weight = 1.0
        harv_weight = 0.0
    elif harv_sig:
        recommendation = "HAR-RV_only"
        garch_weight = 0.0
        harv_weight = 1.0
    else:
        recommendation = "neither_significant"
        garch_weight = 0.5
        harv_weight = 0.5

    return {
        "status": "ok",
        "n": n,
        "intercept": round(float(beta_hat[0]), 8),
        "beta_garch": round(float(beta_hat[1]), 4),
        "beta_harv": round(float(beta_hat[2]), 4),
        "p_garch": round(float(p_garch), 4),
        "p_harv": round(float(p_harv), 4),
        "recommendation": recommendation,
        "garch_weight": round(garch_weight, 3),
        "harv_weight": round(harv_weight, 3),
    }


# ============================================================
# MAIN: RUN FULL EVALUATION
# ============================================================

TEST_TICKERS_DEFAULT = [
    "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META",
    "JPM", "GS", "XOM", "GLD", "IWM", "XLF", "AMZN", "GOOGL",
    "BA", "DIS", "NFLX", "PFE",
]

TEST_TICKERS_FULL = TEST_TICKERS_DEFAULT + [
    "BAC", "WFC", "V", "MA", "HD", "WMT", "COST", "UNH", "JNJ",
    "MRK", "ABBV", "LLY", "COP", "CVX", "SLB", "CAT", "DE", "GE",
    "UPS", "LMT", "COIN", "PLTR", "SOFI", "GME", "MRNA", "SMCI",
    "XLE", "XLK", "XLV", "TLT",
]


def evaluate_ticker(ticker, train_window=252, forecast_horizon=20, step=5):
    """Run full forecast evaluation for a single ticker."""
    import yf_proxy

    print(f"\n{'='*60}")
    print(f"Evaluating: {ticker}")
    print(f"{'='*60}")

    # Fetch 2 years of history
    hist = yf_proxy.get_stock_history(ticker, period="2y")
    if hist.empty or len(hist) < train_window + forecast_horizon + 50:
        print(f"  SKIP: insufficient data ({len(hist)} days)")
        return None

    print(f"  Data: {len(hist)} trading days")

    # 1A/1B: Generate rolling forecasts
    print(f"\n  --- GARCH Forecasts ---")
    garch_fc = garch_rolling_forecasts(hist, train_window, forecast_horizon, step)

    print(f"\n  --- HAR-RV Forecasts ---")
    harv_fc = har_rv_rolling_forecasts(hist, train_window, forecast_horizon, step)

    if garch_fc.empty or harv_fc.empty:
        print(f"  SKIP: forecast generation failed")
        return None

    # 1A: Mincer-Zarnowitz for both
    print(f"\n  --- Mincer-Zarnowitz Regressions ---")
    mz_garch = mincer_zarnowitz(garch_fc, "GJR-GARCH")
    mz_harv = mincer_zarnowitz(harv_fc, "HAR-RV")

    print(f"  GARCH: α={mz_garch.get('alpha', 'N/A')}, β={mz_garch.get('beta', 'N/A')}, "
          f"R²={mz_garch.get('r_squared', 'N/A')}, diagnosis={mz_garch.get('diagnosis', 'N/A')}")
    print(f"  HAR-RV: α={mz_harv.get('alpha', 'N/A')}, β={mz_harv.get('beta', 'N/A')}, "
          f"R²={mz_harv.get('r_squared', 'N/A')}, diagnosis={mz_harv.get('diagnosis', 'N/A')}")

    # 1C: Diebold-Mariano
    print(f"\n  --- Diebold-Mariano Test ---")
    dm = diebold_mariano(garch_fc, harv_fc)
    print(f"  DM stat={dm.get('dm_statistic', 'N/A')}, p={dm.get('p_value', 'N/A')}, "
          f"winner={dm.get('winner', 'N/A')}")

    # 1D: Encompassing test
    print(f"\n  --- Encompassing Test ---")
    enc = encompassing_test(garch_fc, harv_fc)
    print(f"  Recommendation: {enc.get('recommendation', 'N/A')} "
          f"(GARCH weight={enc.get('garch_weight', 'N/A')}, HAR-RV weight={enc.get('harv_weight', 'N/A')})")

    # Also compute simple benchmark: 22-day rolling variance
    print(f"\n  --- Simple Benchmark (22-day rolling) ---")
    log_ret = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
    rolling_var = log_ret.rolling(22).var()

    return {
        "ticker": ticker,
        "n_days": len(hist),
        "mz_garch": mz_garch,
        "mz_harv": mz_harv,
        "diebold_mariano": dm,
        "encompassing": enc,
        "garch_forecasts": garch_fc,
        "harv_forecasts": harv_fc,
    }


def main():
    print(f"=== Forecast Evaluation Pipeline — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    print(f"Module 1: GARCH Forecast Evaluation\n")

    # Determine ticker list
    if "--full" in sys.argv:
        tickers = TEST_TICKERS_FULL
        args = [a for a in sys.argv[1:] if a != "--full"]
    elif len(sys.argv) > 1:
        tickers = [t.upper().strip() for t in sys.argv[1:]]
    else:
        tickers = TEST_TICKERS_DEFAULT

    print(f"Testing {len(tickers)} tickers: {', '.join(tickers[:10])}{'...' if len(tickers) > 10 else ''}")

    all_results = []
    for i, ticker in enumerate(tickers):
        print(f"\n[{i+1}/{len(tickers)}]", end="")
        result = evaluate_ticker(ticker)
        if result:
            all_results.append(result)

    # ============================================================
    # SUMMARY
    # ============================================================
    print(f"\n\n{'='*70}")
    print(f"SUMMARY — {len(all_results)} tickers evaluated")
    print(f"{'='*70}")

    if not all_results:
        print("No results to summarize.")
        return

    # Collect Mincer-Zarnowitz results
    print(f"\n--- Mincer-Zarnowitz: Forecast Unbiasedness ---")
    print(f"{'Ticker':<8} {'Model':<12} {'α':>10} {'β':>8} {'R²':>8} {'p(joint)':>10} {'Diagnosis':<20}")
    print("-" * 78)

    garch_r2s = []
    harv_r2s = []
    garch_diagnoses = []
    harv_diagnoses = []

    for r in all_results:
        mzg = r["mz_garch"]
        mzh = r["mz_harv"]
        if mzg.get("status") == "ok":
            print(f"{r['ticker']:<8} {'GARCH':<12} {mzg['alpha']:>10.6f} {mzg['beta']:>8.3f} "
                  f"{mzg['r_squared']:>8.3f} {mzg['p_joint']:>10.4f} {mzg['diagnosis']:<20}")
            garch_r2s.append(mzg["r_squared"])
            garch_diagnoses.append(mzg["diagnosis"])
        if mzh.get("status") == "ok":
            print(f"{r['ticker']:<8} {'HAR-RV':<12} {mzh['alpha']:>10.6f} {mzh['beta']:>8.3f} "
                  f"{mzh['r_squared']:>8.3f} {mzh['p_joint']:>10.4f} {mzh['diagnosis']:<20}")
            harv_r2s.append(mzh["r_squared"])
            harv_diagnoses.append(mzh["diagnosis"])

    print(f"\n--- Forecast Quality Summary ---")
    if garch_r2s:
        print(f"GARCH   avg R²: {np.mean(garch_r2s):.3f} (range {np.min(garch_r2s):.3f}–{np.max(garch_r2s):.3f})")
        for d in ["well_calibrated", "marginally_calibrated", "biased_high", "biased_low", "poor_tracking"]:
            count = garch_diagnoses.count(d)
            if count > 0:
                print(f"  {d}: {count}/{len(garch_diagnoses)}")
    if harv_r2s:
        print(f"HAR-RV  avg R²: {np.mean(harv_r2s):.3f} (range {np.min(harv_r2s):.3f}–{np.max(harv_r2s):.3f})")
        for d in ["well_calibrated", "marginally_calibrated", "biased_high", "biased_low", "poor_tracking"]:
            count = harv_diagnoses.count(d)
            if count > 0:
                print(f"  {d}: {count}/{len(harv_diagnoses)}")

    # Diebold-Mariano summary
    print(f"\n--- Diebold-Mariano: GARCH vs HAR-RV ---")
    dm_winners = {"GARCH": 0, "HAR-RV": 0, "no_significant_difference": 0}
    for r in all_results:
        dm = r["diebold_mariano"]
        if dm.get("status") == "ok":
            w = dm["winner"]
            # Normalize winner names
            if "GARCH" in str(w):
                dm_winners["GARCH"] += 1
            elif "HAR" in str(w):
                dm_winners["HAR-RV"] += 1
            else:
                dm_winners["no_significant_difference"] += 1

    for w, count in dm_winners.items():
        print(f"  {w}: {count} tickers")

    # Encompassing summary
    print(f"\n--- Encompassing Test: Optimal Forecast ---")
    enc_recs = {}
    for r in all_results:
        enc = r["encompassing"]
        if enc.get("status") == "ok":
            rec = enc["recommendation"]
            enc_recs[rec] = enc_recs.get(rec, 0) + 1

    for rec, count in sorted(enc_recs.items(), key=lambda x: -x[1]):
        print(f"  {rec}: {count} tickers")

    # Final verdict
    print(f"\n{'='*70}")
    print("VERDICT")
    print(f"{'='*70}")
    garch_better = dm_winners.get("GARCH", 0)
    harv_better = dm_winners.get("HAR-RV", 0)
    tied = dm_winners.get("no_significant_difference", 0)
    total = garch_better + harv_better + tied

    if total > 0:
        if harv_better > garch_better * 2:
            print("HAR-RV DOMINATES. Consider replacing GARCH with HAR-RV as primary forecast engine.")
        elif garch_better > harv_better * 2:
            print("GARCH DOMINATES. Current engine is well-chosen.")
        elif enc_recs.get("combine", 0) > total * 0.4:
            print("COMBINATION RECOMMENDED. Both models contribute — blend GARCH + HAR-RV.")
        else:
            print("MODELS ARE COMPARABLE. Either works; combination may offer marginal improvement.")

    avg_r2 = np.mean(garch_r2s) if garch_r2s else 0
    if avg_r2 < 0.05:
        print(f"\nWARNING: Average GARCH R² = {avg_r2:.3f}. Forecasts explain <5% of variance.")
        print("The VRP signal may be based on a forecast that's barely better than random.")
    elif avg_r2 < 0.15:
        print(f"\nCAUTION: Average GARCH R² = {avg_r2:.3f}. Moderate tracking — typical for daily equity vol.")
    else:
        print(f"\nGOOD: Average GARCH R² = {avg_r2:.3f}. Forecast tracks realized vol reasonably well.")


if __name__ == "__main__":
    main()
