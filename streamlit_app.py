import streamlit as st
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yf_proxy
import traceback
from analytics import (
    calc_realized_vol,
    calc_vrp_signal,
    calc_greeks_for_chain,
    get_iv_rank_percentile,
    get_term_structure,
    expected_move,
    score_trade,
    calc_prob_of_loss,
    calc_kelly_size,
    calc_edge_confidence,
    run_monte_carlo,
    stress_test_trade,
    generate_exit_signals,
    get_action_playbook,
    backtest_vrp_strategy,
    summarize_backtest,
    explain_signal_plain_english,
    calc_garch_forecast,
    calc_empirical_probabilities,
    build_vol_surface,
    calc_portfolio_correlation,
    calc_yang_zhang_vol,
    classify_vol_regime,
    get_next_fomc_date,
    calc_skew_score,
)
from db import add_trade, close_trade, get_open_trades, get_all_trades, delete_trade
from db import record_iv, get_iv_history, get_real_iv_rank, using_supabase
from db import log_prediction, score_pending_predictions, get_prediction_scorecard
from db import get_pending_predictions_count, get_all_predictions
from eval_risk import run_all_risk_metrics
from eval_backtest import walk_forward_backtest, iv_multiplier_sensitivity
from eval_signals import run_all_signal_validation
from eval_portfolio import (crisis_correlation_analysis, portfolio_vega_stress,
                            portfolio_theta_risk, historical_stress_test)
from eval_monitor import cusum_edge_detection, check_circuit_breakers
from basket_test import (CORE_BASKET, QUICK_BASKET, FULL_BASKET,
                         test_ticker, _compute_aggregate, load_all_results)

st.set_page_config(
    page_title="Options Edge Finder",
    page_icon="$",
    layout="wide",
)

# Version marker — increment to bust Streamlit caches on deploy
_APP_VERSION = "4.2-basket-ui"
if "app_version" not in st.session_state or st.session_state.app_version != _APP_VERSION:
    st.cache_data.clear()
    st.cache_resource.clear()
    st.session_state.app_version = _APP_VERSION

# ============================================================
# TOOLTIP DEFINITIONS — hover help for every metric
# ============================================================
TIPS = {
    "iv": (
        "Implied Volatility (IV) is the market's forecast of how much the stock will move. "
        "Higher IV = options cost more = you collect more premium when selling. "
        "Think of it as the 'price of insurance.' IV of 30% means the market expects "
        "~1.9% daily moves (30/16)."
    ),
    "rv": (
        "Realized Volatility is how much the stock has ACTUALLY been moving over the past 20 trading days. "
        "This is the reality check against IV. If IV is 30% but the stock only moved at 20%, "
        "the options were overpriced by 10 points — that's your edge."
    ),
    "vrp": (
        "Variance Risk Premium = IV minus Realized Vol. This is THE key number. "
        "Positive VRP means options are overpriced (good for sellers). "
        "Negative VRP means options are underpriced (bad for sellers). "
        "Historically, VRP is positive ~82% of the time for indices. "
        "Think of it as: 'Am I getting paid enough to sell this insurance?' "
        "CAVEAT: True VRP = IV minus FUTURE realized vol (unknowable). We use backward-looking RV "
        "as a rough forecast. This works when vol is stable but fails around regime changes, "
        "earnings, and market shocks. Treat as directional signal, not precise measurement."
    ),
    "iv_rank": (
        "IV Rank shows where current IV sits in its 52-week range (0-100%). "
        "IV Rank of 80% = IV is near its yearly high = big premiums. "
        "IV Rank of 12% = IV is near its yearly low = tiny premiums. "
        "Generally, sell options when IV Rank > 30%. Below that, you're selling cheap insurance. "
        "CAVEAT: We approximate this using historical realized vol as a proxy for historical IV "
        "(yfinance doesn't provide historical IV). The real IV Rank could be significantly different."
    ),
    "iv_pctl": (
        "IV Percentile = what % of days in the past year had IV below today's level. "
        "Percentile of 90% means IV was lower than today on 90% of days = high premium environment. "
        "CAVEAT: Same limitation as IV Rank — we use realized vol as a proxy, not actual historical IV."
    ),
    "term_structure": (
        "Term Structure compares short-term vs long-term option prices. "
        "CONTANGO (normal): Long-term > short-term. Safe to sell. "
        "BACKWARDATION (danger): Short-term > long-term. The market is panicking. "
        "NEVER sell options during backwardation — it means traders expect something bad to happen soon."
    ),
    "daily_move": (
        "The 'Rule of 16': Divide annualized IV by 16 to get expected daily move. "
        "This is the market's best guess at how much the stock moves in a single day. "
        "If the stock rarely moves more than this, short option sellers profit."
    ),
    "weekly_move": (
        "Expected weekly move = daily move x sqrt(5). "
        "This is what the market thinks a full trading week of movement looks like. "
        "Your short strike should ideally be outside this range."
    ),
    "edge_score": (
        "Edge Score (1-10) combines VRP, IV rank, term structure, and liquidity "
        "into a single number. 8+ = strong edge. 5-7 = moderate. Below 5 = weak or no edge. "
        "This is your quick read on whether a specific strike is worth selling."
    ),
    "prob_profit": (
        "Probability of Profit: chance this trade makes money at expiration, based on "
        "the log-normal distribution implied by IV. 80%+ is good for premium sellers. "
        "CAVEAT: Assumes log-normal distribution. Real stocks have fat tails — "
        "big moves happen 3-10x more often than this model predicts. "
        "Treat this as optimistic. The real probability of profit is somewhat lower."
    ),
    "prob_assign": (
        "Probability of Assignment: chance the option expires in-the-money and you get assigned. "
        "For covered calls, assignment = selling your shares at the strike (may be fine). "
        "For cash-secured puts, assignment = buying shares at the strike (may be fine if you want them)."
    ),
    "kelly": (
        "Kelly Criterion: optimal fraction of capital to risk on this trade. "
        "We use 25% Kelly (conservative) because full Kelly is too aggressive. "
        "If Kelly says 0%, there's no statistical edge — don't trade. "
        "Example: Kelly 5% on a $100k account = risk $5k max. "
        "CAVEAT: Kelly is extremely sensitive to input estimates. Our win/loss estimates are rough. "
        "Use this as a ceiling, not a target. When in doubt, go smaller."
    ),
    "confidence": (
        "Confidence Grade: structural edge checklist scored 0-100. "
        "A (80+) = strong structural reasons to trade. "
        "B (60-79) = solid but not perfect. "
        "C (40-59) = marginal, maybe skip. "
        "D/F (<40) = no real edge, don't trade. "
        "Based on VRP, IV rank, liquidity, term structure, DTE, and probability."
    ),
    "delta": (
        "Delta: how much the option price changes per $1 move in the stock. "
        "Delta 0.30 call = 30% chance of expiring ITM, option gains $0.30 per $1 stock move. "
        "For covered calls, sell 0.20-0.30 delta (70-80% chance of keeping shares). "
        "Delta also approximates probability of assignment."
    ),
    "theta": (
        "Theta: how much value the option loses per day (time decay). "
        "As a seller, theta is your friend — it's the daily 'rent' you collect. "
        "Theta accelerates near expiration. Optimal selling window: 30-45 DTE."
    ),
    "vega": (
        "Vega: how much the option price changes per 1% move in IV. "
        "As a seller, rising IV hurts you (option gets more expensive to buy back). "
        "Falling IV helps you (option gets cheaper). "
        "High vega = more exposure to volatility changes."
    ),
    "gamma": (
        "Gamma: how fast delta changes. High gamma near expiration means small stock moves "
        "create wild swings in your P&L. This is why short options near expiry are dangerous. "
        "Gamma risk is the #1 reason to close positions early."
    ),
    "vix": (
        "VIX: the market's 'fear gauge.' Measures expected S&P 500 volatility over 30 days. "
        "VIX < 15 = calm. 15-20 = normal. 20-30 = elevated. 30+ = fear/panic. "
        "High VIX = high premiums = potentially good for sellers, BUT check term structure first."
    ),
    "mc_ev": (
        "Expected Value: average P&L across 10,000 simulated outcomes. "
        "Positive EV = the math favors you on average. But averages can be misleading — "
        "check the 5th percentile to see how bad it can get."
    ),
    "mc_5pct": (
        "5th Percentile: the P&L at the bad end of outcomes. "
        "In 95% of simulations, you did better than this number. "
        "This is your 'how bad can it realistically get?' number. "
        "If this loss would ruin your sleep, reduce position size."
    ),
    "skew": (
        "Skew measures the asymmetry of your P&L distribution. "
        "Negative skew (common for short options) = small frequent wins, rare large losses. "
        "This is the fundamental tradeoff of selling options. "
        "Skew below -1.0 means tail risk is significant."
    ),
    "eff_buy": (
        "Effective Buy Price = Strike - Premium. This is what you'd actually pay per share "
        "if assigned on a cash-secured put. Compare this to the current price — "
        "the difference is your 'discount' for buying via put selling."
    ),
    "backtest_win": (
        "Historical win rate when the VRP signal was this color. "
        "IMPORTANT CAVEAT: This backtest uses realized vol as a proxy for both IV and RV, "
        "which makes it partially circular. Treat as a rough sanity check, not rigorous evidence. "
        "A real backtest would require historical IV data we don't have."
    ),
}


# ============================================================
# TOP NAVIGATION
# ============================================================
st.title("Options Edge Finder")
st.caption("Know when to sell. Know when to fold.")

tab_guide, tab_dashboard, tab_analyzer, tab_positions, tab_scorecard, tab_basket = st.tabs([
    "Getting Started",
    "Dashboard",
    "Trade Analyzer",
    "My Positions",
    "Scorecard",
    "Basket Test",
])

# Ticker input — persistent across tabs via session state
if "ticker_input" not in st.session_state:
    st.session_state.ticker_input = ""

ticker_input = st.text_input(
    "Tickers (comma-separated)",
    value=st.session_state.ticker_input,
    label_visibility="collapsed",
    placeholder="Enter tickers: AAPL, MSFT, GOOGL ...",
    key="ticker_box",
)
st.session_state.ticker_input = ticker_input
tickers = [t.strip().upper() for t in ticker_input.split(",") if t.strip()]


# ============================================================
# DATA LOADERS — all routed through Cloudflare Worker proxy
# ============================================================
@st.cache_data(ttl=600)
def load_stock_data(ticker, period="1y"):
    hist = yf_proxy.get_stock_history(ticker, period=period)
    if hist.empty:
        return pd.DataFrame(), {}
    info = yf_proxy.get_stock_info(ticker)
    return hist, info


@st.cache_data(ttl=600)
def load_expirations(ticker):
    """Get all available expiration dates for a ticker."""
    return yf_proxy.get_expirations(ticker)


@st.cache_data(ttl=300)
def load_chain(ticker, expiration):
    """Load a single expiration's option chain (lazy — only when needed)."""
    chain = yf_proxy.get_option_chain(ticker, expiration)
    if chain.calls.empty and chain.puts.empty:
        return None
    return chain


def load_options_data(ticker):
    """Load first 2 expirations for dashboard/term structure. Returns chains dict + all expiration list."""
    expirations = load_expirations(ticker)
    if not expirations:
        return None, []
    chains = {}
    for exp in expirations[:2]:
        chain = load_chain(ticker, exp)
        if chain is not None:
            chains[exp] = chain
    return chains, expirations


@st.cache_data(ttl=900)
def load_vix_data():
    vix_hist = yf_proxy.get_stock_history("^VIX", period="6mo")
    vix3m_hist = yf_proxy.get_stock_history("^VIX3M", period="6mo")
    return vix_hist, vix3m_hist if not vix3m_hist.empty else None


def compute_analytics(ticker):
    """Load and compute all analytics for a ticker. Returns a dict."""
    hist, info = load_stock_data(ticker)
    chains, expirations = load_options_data(ticker)
    print(f"[compute_analytics] {ticker}: hist={len(hist)} rows, chains={len(chains) if chains else 0}, expirations={len(expirations)}")
    if hist.empty:
        return None

    current_price = hist["Close"].iloc[-1]
    company_name = info.get("shortName", ticker)
    rv_10 = calc_realized_vol(hist, window=10)
    rv_20 = calc_realized_vol(hist, window=20)
    rv_30 = calc_realized_vol(hist, window=30)

    current_iv = None
    if chains:
        first_exp = list(chains.keys())[0]
        calls = chains[first_exp].calls
        if not calls.empty and "impliedVolatility" in calls.columns:
            calls_sorted = calls.copy()
            calls_sorted["dist"] = abs(calls_sorted["strike"] - current_price)
            atm_row = calls_sorted.loc[calls_sorted["dist"].idxmin()]
            current_iv = atm_row["impliedVolatility"] * 100

    # Yang-Zhang estimator (better than close-to-close)
    yz_20 = calc_yang_zhang_vol(hist, window=20)

    # GARCH forecast (forward-looking)
    garch_vol, garch_info = calc_garch_forecast(hist, horizon=20)

    # Best available vol forecast: GARCH > Yang-Zhang > Close-to-Close
    if garch_vol is not None and garch_vol > 0:
        rv_forecast = garch_vol
        forecast_method = "GJR-GARCH"
    elif yz_20 > 0:
        rv_forecast = yz_20
        forecast_method = "Yang-Zhang"
    else:
        rv_forecast = rv_20
        forecast_method = "Close-to-Close"

    # IV Rank: use real recorded history if available, fallback to RV proxy
    iv_rank_proxy, iv_pctl_proxy = get_iv_rank_percentile(hist, current_iv)
    real_iv_rank, real_iv_pctl, iv_history_days = get_real_iv_rank(ticker, current_iv) if current_iv else (None, None, 0)

    if real_iv_rank is not None and iv_history_days >= 20:
        iv_rank = real_iv_rank
        iv_pctl = real_iv_pctl
        iv_rank_source = f"Real IV ({iv_history_days}d history)"
    else:
        iv_rank = iv_rank_proxy
        iv_pctl = iv_pctl_proxy
        iv_rank_source = f"RV proxy (recording IV daily — {iv_history_days}d so far)"

    term_struct, term_label = get_term_structure(chains, expirations, current_price)

    # Regime detection (needs VIX data)
    rv_60 = calc_realized_vol(hist, window=60) if len(hist) >= 60 else None
    regime = "normal"
    regime_info = {}
    try:
        vix_df = yf_proxy.get_stock_history("^VIX", period="5d")
        vix3m_df = yf_proxy.get_stock_history("^VIX3M", period="5d")
        vix_level = float(vix_df["Close"].iloc[-1]) if not vix_df.empty else None
        vix_ratio = None
        if not vix_df.empty and not vix3m_df.empty:
            vix_ratio = float(vix_df["Close"].iloc[-1] / vix3m_df["Close"].iloc[-1])
        regime, regime_info = classify_vol_regime(vix_level, vix_ratio, rv_20, rv_60)
    except Exception:
        pass

    vrp = (current_iv - rv_forecast) if current_iv else None
    signal, signal_color, signal_reason = calc_vrp_signal(vrp, iv_rank, term_label, regime=regime)

    # Skew scoring from front-month chain
    skew_value, skew_penalty, skew_details = None, 0, {}
    if chains:
        first_exp = list(chains.keys())[0]
        try:
            dte_front = max((datetime.strptime(first_exp, "%Y-%m-%d") - datetime.now()).days, 1)
            skew_value, skew_penalty, skew_details = calc_skew_score(
                chains[first_exp].calls, chains[first_exp].puts, current_price, dte_front
            )
        except Exception:
            pass

    # Empirical tail probabilities
    empirical = calc_empirical_probabilities(hist, move_pct=0.05, holding_days=20)

    # Earnings check
    earnings_date = None
    earnings_days = None
    try:
        cal = info.get("earningsTimestampStart") or info.get("earningsDate")
        if cal:
            if isinstance(cal, (list, tuple)):
                cal = cal[0]
            if isinstance(cal, (int, float)):
                earnings_date = datetime.fromtimestamp(cal)
            else:
                earnings_date = pd.Timestamp(cal).to_pydatetime()
            earnings_days = (earnings_date - datetime.now()).days
    except Exception:
        pass

    # FOMC check
    fomc_date, fomc_days = get_next_fomc_date()

    # Record today's IV snapshot — full data capture
    db_status = []
    if current_iv is not None:
        try:
            first_exp = expirations[0] if expirations else ""
            p25 = skew_details.get("put_25d_iv")
            c25 = skew_details.get("call_25d_iv")
            record_iv(ticker, current_iv, current_price, first_exp, rv_20, term_label,
                      put_25d_iv=p25, call_25d_iv=c25,
                      rv_10=rv_10, rv_30=rv_30, rv_60=rv_60, yz_20=yz_20,
                      garch_vol=garch_vol, iv_rank=iv_rank, iv_pctl=iv_pctl,
                      vrp=vrp, signal=signal, regime=regime, skew=skew_value,
                      fomc_days=fomc_days,
                      earnings_days=earnings_days)
            db_status.append(f"IV snapshot saved ({'Supabase' if using_supabase() else 'local SQLite'})")
        except Exception as e:
            db_status.append(f"IV snapshot FAILED: {e}")

    # Log prediction for scoring later — full context
    try:
        log_prediction(
            ticker=ticker, signal=signal, spot_price=current_price,
            atm_iv=current_iv, rv_forecast=rv_forecast, vrp=vrp,
            iv_rank=iv_rank, term_label=term_label, regime=regime,
            skew=skew_value, garch_vol=garch_vol, forecast_method=forecast_method,
            rv_20=rv_20, iv_pctl=iv_pctl, skew_penalty=skew_penalty,
            signal_reason=signal_reason, earnings_days=earnings_days,
            fomc_days=fomc_days,
        )
        db_status.append(f"Prediction logged ({'Supabase' if using_supabase() else 'local SQLite'})")
    except Exception as e:
        db_status.append(f"Prediction log FAILED: {e}")

    return {
        "hist": hist, "info": info, "chains": chains, "expirations": expirations,
        "current_price": current_price, "company_name": company_name,
        "rv_10": rv_10, "rv_20": rv_20, "rv_30": rv_30, "rv_60": rv_60, "yz_20": yz_20,
        "garch_vol": garch_vol, "garch_info": garch_info,
        "rv_forecast": rv_forecast, "forecast_method": forecast_method,
        "current_iv": current_iv, "iv_rank": iv_rank, "iv_pctl": iv_pctl,
        "iv_rank_source": iv_rank_source, "iv_history_days": iv_history_days,
        "term_struct": term_struct, "term_label": term_label,
        "vrp": vrp, "signal": signal, "signal_color": signal_color, "signal_reason": signal_reason,
        "earnings_date": earnings_date, "earnings_days": earnings_days,
        "fomc_date": fomc_date, "fomc_days": fomc_days,
        "regime": regime, "regime_info": regime_info,
        "skew_value": skew_value, "skew_penalty": skew_penalty, "skew_details": skew_details,
        "empirical": empirical,
        "db_status": db_status,
    }


# ============================================================
# TAB: GETTING STARTED
# ============================================================
with tab_guide:
    st.header("How to Use This Tool")
    st.markdown("""
**Enter your tickers in the box above** (comma-separated, e.g. `AAPL, MSFT, GOOGL`) then switch to the Dashboard or Trade Analyzer tab.

---

### The 3 Tabs

| Tab | What it does |
|---|---|
| **Dashboard** | Shows whether conditions favor selling options right now. Green = sell, Yellow = be cautious, Red = don't sell. |
| **Trade Analyzer** | Pick a specific expiration and strike to see full risk breakdown, Monte Carlo simulation, and stress test before you trade. |
| **My Positions** | Track your open trades, get exit signals (MUST SELL / WARNING), and log your trade history. |

---

### The Core Idea

When you sell options (covered calls, cash-secured puts), you collect premium. The question is: **is the premium worth the risk?**

This tool answers that by measuring the **Variance Risk Premium (VRP)** — the gap between what the market *expects* (implied volatility) and what actually *happens* (realized volatility). When IV is much higher than RV, options are "overpriced" and selling has an edge.

---

### Quick Workflow

1. **Check the Dashboard signal** — Green means IV is elevated relative to RV, options are likely overpriced
2. **Go to Trade Analyzer** — Pick an expiration (30-45 DTE is the sweet spot), look at the edge checklist and Monte Carlo
3. **Log your trade in My Positions** — Get automatic exit signals when conditions change

---
""")

    st.header("Where This Tool Is Strong")
    st.markdown("""
- **GJR-GARCH volatility forecasting** — Asymmetric GARCH models the leverage effect (bad news spikes vol more than good news calms it). Better than symmetric GARCH(1,1) for equities.
- **Student's t-distribution probabilities** — Probability of Profit uses fat-tailed distribution fitted to actual returns, not log-normal. More realistic crash probability estimates.
- **Volatility regime detection** — Classifies market as crash/high_vol/normal/low_vol using VIX level, term structure, and RV acceleration. Automatically adjusts signals per regime.
- **De-biased backtesting** — Uses IV = RV x 1.2 to remove circular bias, includes transaction costs ($0.65 + slippage).
- **Skew-aware scoring** — Measures 25-delta put/call skew and penalizes trades when the market is pricing tail risk.
- **FOMC calendar** — Warns before Fed meetings, flags expirations that span FOMC dates.
- **Portfolio beta-weighting** — Shows SPY beta per holding and warns when portfolio beta exceeds thresholds.
- **Exit discipline** — 7 automatic triggers (take profit, DTE, delta blowout, VRP flip, etc.) help prevent "one bad trade" scenarios.
- **Transparency** — Every metric has a tooltip, and the "What to Trust" section is brutally honest about limitations.
""")

    st.header("Where This Tool Is Weak")
    st.markdown("""
These are real limitations you need to understand. **Ignoring them will cost you money.**
""")

    weak_col1, weak_col2 = st.columns(2)
    with weak_col1:
        st.subheader("Data Quality")
        st.markdown("""
**IV Rank is estimated until you build history.**
We record real IV daily (ATM + 25-delta put/call). Until you have 90+ days of recordings,
IV Rank uses realized vol as a proxy (can be off by 20+ points). After 90 days, it uses real data.
For faster real IV data, consider ThetaData ($50/mo) or Polygon.io ($200/mo).

**Options data is delayed.**
We pull from Yahoo Finance via a caching proxy. Data may be 5-15 minutes behind real-time.
Never use this for intraday timing — it's for daily/weekly decision-making only.

**Earnings dates may be missing.**
The earnings calendar comes from Yahoo Finance and is sometimes incomplete or wrong.
Always verify earnings dates independently before selling options near them.
""")

        st.subheader("Model Limitations")
        st.markdown("""
**Probability of Profit uses Student's t (fat tails) but is still approximate.**
We fit a Student's t-distribution to actual historical returns, which captures fat tails better
than log-normal. But it's still based on ~1 year of history and assumes stationarity.

**GJR-GARCH captures leverage effect but not regime changes.**
GJR-GARCH models how bad news increases vol more than good news (leverage effect).
But it still assumes mean-reversion and can't predict sudden regime shifts.
The regime classifier adds a layer of protection, but it's rule-based, not predictive.

**Greeks assume Black-Scholes.**
The Greeks use Black-Scholes with per-strike IV (not flat IV). This incorporates skew
automatically but still assumes continuous trading and no jumps.
""")

    with weak_col2:
        st.subheader("Backtesting")
        st.markdown("""
**The backtest is de-biased but still limited.**
We estimate IV as RV x 1.2 (since IV historically exceeds RV by ~15-25% for equities).
This removes the worst circular bias, but the ratio varies by ticker and regime.
Treat results as directionally useful, not precise.

**One year of data isn't enough.**
The backtest uses ~250 trading days. A real backtest needs 5-10 years across multiple
market regimes (2008 crash, 2018 Volmageddon, 2020 COVID, 2022 bear). For SPY/QQQ,
you can extend to 20 years of underlying returns as a partial stress test.

**Transaction costs are now included but approximate.**
We model $0.65 commission + $0.025 slippage per contract per leg. Real slippage varies
by liquidity — illiquid names with wide spreads cost much more. The backtest doesn't model
bid-ask spread variation.
""")

        st.subheader("What's Not Covered")
        st.markdown("""
**Correlation risk is basic.**
The tool now shows SPY beta per holding and portfolio-level beta, plus pairwise correlation.
But it doesn't model joint tail risk or portfolio VaR. A correlated crash scenario
is the #1 way premium sellers blow up.

**Dealer positioning / gamma exposure.**
Market makers' hedging flows can amplify or dampen moves. Tools like SpotGamma ($50/mo)
track this — we don't. Best proxy: VIX term structure (which we show).

**Skew is measured but not deeply modeled.**
We now calculate 25-delta put/call skew and penalize trade scores when skew is steep.
But we don't use SABR or SVI vol surface parameterization for strike-level adjustments.

**Macro events are partially covered.**
FOMC dates are hardcoded and flagged. But CPI, jobs reports, geopolitical events,
and sector rotation are not modeled. Always check an economic calendar independently.
""")

    st.divider()
    st.markdown("""
    ### Bottom Line

    This tool is **good for disciplined premium sellers** who want a systematic framework
    for deciding *when* and *whether* to sell options. It's **not a replacement for**
    professional platforms like TastyTrade, Moontower.ai, or Bloomberg.

    The biggest edge it gives you isn't the analytics — it's **exit discipline**.
    Most retail option sellers lose money because they hold losers too long or
    sell into bad conditions. The signal system and exit triggers help prevent that.

    *Based on 'Retail Options Trading' by Sinclair & Mack (2024).*
    """)


# ============================================================
# TAB: DASHBOARD
# ============================================================
with tab_dashboard:
    if not tickers:
        st.info("Enter one or more tickers in the box above to get started. Example: `AAPL, MSFT, GOOGL`")
    for ticker in tickers:
        try:
            with st.spinner(f"Loading {ticker}..."):
                data = compute_analytics(ticker)
        except Exception as e:
            err_name = type(e).__name__
            if "RateLimit" in err_name:
                st.error(f"Yahoo Finance rate limit hit for {ticker}. Please wait 30 seconds and refresh.")
            else:
                st.error(f"Error loading {ticker}: {err_name} — {e}")
            continue

        if data is None:
            st.error(f"No data for {ticker}")
            continue

        current_price = data["current_price"]
        current_iv = data["current_iv"]
        rv_20 = data["rv_20"]
        vrp = data["vrp"]
        iv_rank = data["iv_rank"]
        iv_pctl = data["iv_pctl"]
        term_label = data["term_label"]
        signal = data["signal"]
        signal_reason = data["signal_reason"]
        hist = data["hist"]

        st.header(f"{data['company_name']} ({ticker}) — ${current_price:.2f}")

        # --- Earnings warning (BEFORE signal) ---
        earnings_days = data.get("earnings_days")
        earnings_date = data.get("earnings_date")
        if earnings_days is not None and 0 <= earnings_days <= 14:
            st.error(
                f"**EARNINGS IN {earnings_days} DAYS** ({earnings_date.strftime('%b %d')}). "
                f"Do NOT sell options through earnings. The elevated IV you see is likely "
                f"fair pricing of the earnings move, not free premium. "
                f"If you have open positions expiring after earnings, close them first."
            )
        elif earnings_days is not None and 14 < earnings_days <= 30:
            st.warning(
                f"**Earnings on {earnings_date.strftime('%b %d')}** ({earnings_days} days). "
                f"Be cautious selling options that expire after this date."
            )

        # --- FOMC warning ---
        fomc_days = data.get("fomc_days")
        fomc_date = data.get("fomc_date")
        if fomc_days is not None and 0 <= fomc_days <= 3:
            st.error(
                f"**FOMC DECISION IN {fomc_days} DAYS** ({fomc_date.strftime('%b %d')}). "
                f"IV may be elevated due to rate uncertainty. Premium could be fairly priced, not free edge. "
                f"Avoid selling short-dated options through FOMC."
            )
        elif fomc_days is not None and 3 < fomc_days <= 14:
            st.info(
                f"**FOMC meeting on {fomc_date.strftime('%b %d')}** ({fomc_days} days). "
                f"Factor this into expirations — avoid selling through FOMC unless intentional."
            )

        # --- Regime badge ---
        regime = data.get("regime", "normal")
        regime_info = data.get("regime_info", {})
        if regime == "crash":
            st.error(f"**REGIME: CRASH** — {regime_info.get('reason', '')}. Halt all new option writing.")
        elif regime == "high_vol":
            st.warning(f"**REGIME: HIGH VOL** — {regime_info.get('reason', '')}. Use wider strikes, smaller size.")
        elif regime == "low_vol":
            st.info(f"**REGIME: LOW VOL** — {regime_info.get('reason', '')}. Premiums are thin.")

        # --- Signal banner ---
        if signal == "GREEN":
            st.success(f"**SELL OPTIONS** — {signal_reason}")
        elif signal == "YELLOW":
            st.warning(f"**MARGINAL** — {signal_reason}")
        else:
            st.error(f"**DON'T SELL** — {signal_reason}")

        # --- DB storage status ---
        db_status = data.get("db_status", [])
        if db_status:
            status_text = " | ".join(db_status)
            if any("FAILED" in s for s in db_status):
                st.error(f"Database: {status_text}")
            else:
                st.caption(f"Data recorded: {status_text}")

        # --- Plain English explanation ---
        explanation = explain_signal_plain_english(
            signal, vrp, iv_rank, term_label, current_iv, rv_20, current_price
        )
        with st.expander("What does this mean? (plain English)", expanded=signal == "RED"):
            st.markdown(explanation)

        # --- Data reliability ---
        with st.expander("What to trust / What to question", expanded=False):
            st.markdown("""
**Trust these** (direct from market data):
- Implied Volatility — real-time from options chain
- Term Structure — directly observed from option prices across expirations
- Greeks (delta, theta, vega, gamma) — calculated from Black-Scholes with market IV
- Expected Move — simple math from IV (Rule of 16)

**Directionally useful but imprecise**:
- VRP — uses backward-looking realized vol as forecast for future vol. Works when vol is stable, fails around regime changes
- Realized Volatility — accurate measurement of past, but past ≠ future

**Take with a grain of salt** (approximations):
- IV Rank / IV Percentile — uses historical realized vol as proxy for historical IV (we don't have real historical IV data). Could be off by 20+ points
- Probability of Profit — assumes log-normal distribution; real tails are fatter. Your actual P(loss) is higher than shown
- Kelly Size — extremely sensitive to input estimates which are rough. Use as a ceiling, not a target
- Confidence Score — point values are heuristic, not empirically calibrated
- Historical Backtest — partially circular (uses RV as proxy for both IV and RV). Treat as rough sanity check only

**Not covered (blind spots)**:
- Correlation risk (if you sell options on multiple stocks, a market crash hits all of them)
- Dealer positioning / gamma exposure
- Skew dynamics (OTM puts are priced differently than our model assumes)
- Event risk beyond earnings (Fed meetings, product launches, lawsuits)
""")

        # --- Metrics row with tooltips ---
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        with col1:
            st.metric("Implied Vol", f"{current_iv:.1f}%" if current_iv else "N/A",
                       help=TIPS["iv"])
        with col2:
            forecast_method = data.get("forecast_method", "C2C")
            st.metric(f"Vol Forecast ({forecast_method})", f"{data['rv_forecast']:.1f}%",
                       help=f"Best available vol forecast using {forecast_method}. "
                            f"Close-to-Close: {rv_20:.1f}% | Yang-Zhang: {data.get('yz_20', 0):.1f}% | "
                            f"GARCH: {data.get('garch_vol', 0):.1f}%" if data.get('garch_vol') else
                            f"Best available vol forecast. GARCH unavailable (need 100+ days data).")
        with col3:
            st.metric("VRP", f"{vrp:+.1f} pts" if vrp else "N/A",
                       delta=f"{'Edge exists' if vrp and vrp > 2 else 'Thin/No edge'}" if vrp else None,
                       delta_color="normal" if vrp and vrp > 2 else "inverse",
                       help=TIPS["vrp"])
        with col4:
            iv_src = data.get("iv_rank_source", "")
            st.metric("IV Rank", f"{iv_rank:.0f}%" if iv_rank else "N/A",
                       help=TIPS["iv_rank"] + f"\n\nSource: {iv_src}")
        with col5:
            st.metric("IV Percentile", f"{iv_pctl:.0f}%" if iv_pctl else "N/A",
                       help=TIPS["iv_pctl"] + f"\n\nSource: {iv_src}")
        with col6:
            st.metric("Term Structure", term_label, help=TIPS["term_structure"])

        # --- Expected moves ---
        if current_iv:
            daily_move, weekly_move = expected_move(current_price, current_iv)
            mcol1, mcol2, mcol3 = st.columns(3)
            with mcol1:
                st.metric("Expected Daily Move", f"${daily_move:.2f}", help=TIPS["daily_move"])
            with mcol2:
                st.metric("Expected Weekly Move", f"${weekly_move:.2f}", help=TIPS["weekly_move"])
            with mcol3:
                pct_move = (daily_move / current_price) * 100
                st.metric("Daily Move %", f"{pct_move:.2f}%",
                           help="Daily expected move as a percentage of the stock price.")

        # --- Vol Forecast Comparison ---
        with st.expander("Volatility Forecasts (3 methods compared)", expanded=False):
            vc1, vc2, vc3, vc4 = st.columns(4)
            with vc1:
                st.metric("Close-to-Close (20d)", f"{rv_20:.1f}%",
                           help="Simplest method. Standard deviation of daily log returns, annualized. "
                                "Only uses closing prices. Misses intraday moves.")
            with vc2:
                st.metric("Yang-Zhang (20d)", f"{data.get('yz_20', 0):.1f}%",
                           help="Best simple estimator. Combines overnight gaps + intraday range + close-to-close. "
                                "More accurate than C2C, especially for stocks with big intraday swings.")
            with vc3:
                gv = data.get("garch_vol")
                st.metric("GARCH Forecast", f"{gv:.1f}%" if gv else "N/A",
                           help="Statistical model that accounts for vol clustering (high vol tends to follow high vol) "
                                "and mean reversion. This is a FORWARD-LOOKING forecast, not backward-looking. "
                                "The closest thing we have to predicting future vol.")
            with vc4:
                st.metric("Current IV", f"{current_iv:.1f}%" if current_iv else "N/A",
                           help="What the market thinks vol will be. Compare to our forecasts — "
                                "if IV >> all forecasts, options are overpriced (good for sellers).")

            garch_info = data.get("garch_info", {})
            if garch_info and "persistence" in garch_info:
                gamma = garch_info.get("gamma", 0)
                leverage_str = ""
                if gamma and gamma > 0:
                    lev_ratio = garch_info.get("leverage_ratio")
                    if lev_ratio:
                        leverage_str = f" | Leverage effect: {lev_ratio:.1f}x (downside vol {lev_ratio:.1f}x worse than upside)"
                st.caption(
                    f"GJR-GARCH persistence: {garch_info['persistence']:.3f} "
                    f"({'High — vol shocks last long' if garch_info['persistence'] > 0.95 else 'Moderate — vol mean-reverts reasonably fast'}) | "
                    f"Long-run vol: {garch_info.get('long_run_vol', 0):.1f}%"
                    f"{leverage_str}"
                )

        # --- Skew Info ---
        skew_val = data.get("skew_value")
        skew_det = data.get("skew_details", {})
        if skew_val is not None:
            with st.expander("Put/Call Skew", expanded=False):
                sk_cols = st.columns(3)
                with sk_cols[0]:
                    st.metric("25d Put IV", f"{skew_det.get('put_25d_iv', 0):.1f}%",
                              help="Implied vol of ~25-delta put. Higher than ATM = market pricing crash risk.")
                with sk_cols[1]:
                    st.metric("ATM IV", f"{skew_det.get('atm_iv', 0):.1f}%")
                with sk_cols[2]:
                    st.metric("25d Call IV", f"{skew_det.get('call_25d_iv', 0):.1f}%")
                skew_label = "Normal" if skew_val < 5 else ("Elevated" if skew_val < 10 else "Extreme")
                st.metric("Skew (Put - Call)", f"{skew_val:.1f} pts ({skew_label})",
                          help="Positive = puts are more expensive than calls. "
                               ">10 = extreme skew, market pricing significant tail risk. "
                               "Penalizes put selling in trade scoring.")
                if skew_val > 10:
                    st.warning("Extreme skew — the market is pricing high tail risk. Be very cautious selling puts.")
                elif skew_val > 5:
                    st.info("Elevated skew — OTM puts are pricing in more risk than usual.")

        # --- Empirical Tails (Real Distribution) ---
        empirical = data.get("empirical")
        if empirical:
            with st.expander("Real Tail Risk (actual historical moves, not log-normal)", expanded=False):
                st.markdown(
                    f"Based on **{empirical['n_observations']}** rolling 20-day periods. "
                    f"This stock's returns have **skew {empirical['skew']:.2f}** and "
                    f"**excess kurtosis {empirical['kurtosis']:.2f}**"
                    + (f" — **fatter tails than normal** (log-normal underestimates risk by "
                       f"~{empirical.get('tail_ratio_5pct', 1):.1f}x for 5% moves)."
                       if empirical['kurtosis'] > 1 else " — close to normal distribution.")
                )

                tc1, tc2, tc3, tc4 = st.columns(4)
                with tc1:
                    st.metric("Prob down >5%", f"{empirical['prob_down_5pct']*100:.1f}%",
                               help="How often the stock actually dropped 5%+ in a 20-day window. "
                                    "Compare to log-normal estimate to see if tails are fatter than models assume.")
                with tc2:
                    st.metric("Prob down >10%", f"{empirical['prob_down_10pct']*100:.1f}%",
                               help="A 10% drop in 20 days. This is where short put sellers start to really hurt.")
                with tc3:
                    st.metric("Prob down >15%", f"{empirical['prob_down_15pct']*100:.1f}%",
                               help="Tail event territory. If this number is >3%, think carefully about position sizing.")
                with tc4:
                    st.metric("Worst 5th pctl", f"{empirical['pct_5']:.1f}%",
                               help="In the worst 5% of 20-day periods, the stock moved at least this much. "
                                    "This is a more honest downside estimate than log-normal.")

                # Show how wrong log-normal is
                if empirical.get("tail_ratio_5pct", 1) > 1.3:
                    st.warning(
                        f"**Log-normal underestimates 5% downside moves by {empirical['tail_ratio_5pct']:.1f}x.** "
                        f"The probability numbers in our Monte Carlo and Prob of Profit are optimistic. "
                        f"Mentally adjust downward."
                    )

        # --- Historical Backtest ---
        bt_skewness = None  # used by Kelly sizing
        with st.expander("Historical Backtest: How reliable is this signal?", expanded=False):
            bt = backtest_vrp_strategy(hist, window=20, holding_period=20)
            bt_summary = summarize_backtest(bt)
            if bt is not None and not bt.empty and "pnl_pct" in bt.columns:
                bt_skewness = float(bt["pnl_pct"].skew())
            if bt_summary:
                st.markdown(
                    "We looked at every day in the past year where conditions were similar to today, "
                    "and checked what would have happened if you sold options then. "
                    "**De-biased**: IV estimated at RV x 1.2 (removes circular bias). "
                    "**Includes costs**: $0.65 commission + $0.025 slippage per contract."
                )
                for sig_name, stats in bt_summary.items():
                    color = {"GREEN": "green", "YELLOW": "orange", "RED": "red"}[sig_name]
                    st.markdown(f"**When signal was {sig_name}** ({stats['count']} occurrences):")
                    bc1, bc2, bc3, bc4 = st.columns(4)
                    with bc1:
                        st.metric("Win Rate", f"{stats['win_rate']:.0f}%",
                                   help=TIPS["backtest_win"])
                    with bc2:
                        st.metric("Avg VRP", f"{stats['avg_vrp']:+.1f} pts")
                    with bc3:
                        st.metric("Avg P&L", f"{stats['avg_pnl_pct']:+.1f}%")
                    with bc4:
                        st.metric("Worst Loss", f"{stats['worst_loss_pct']:+.1f}%")

                # Current signal callout
                if signal in bt_summary:
                    s = bt_summary[signal]
                    st.info(
                        f"**Today's signal is {signal}.** Historically, selling options on {ticker} "
                        f"in similar conditions won {s['win_rate']:.0f}% of the time "
                        f"with an average return of {s['avg_pnl_pct']:+.1f}%. "
                        f"Worst case was {s['worst_loss_pct']:+.1f}%."
                    )
            else:
                st.info("Not enough historical data to run backtest.")

        # --- Walk-Forward Backtest (Module 4) ---
        with st.expander("Walk-Forward Backtest: Out-of-Sample Validation", expanded=False):
            st.caption(
                "The standard backtest above is one-pass (in-sample). This splits history into "
                "rolling train/test windows to measure TRUE out-of-sample performance. "
                "If OOS results are much worse than in-sample, the strategy is overfit."
            )
            if len(hist) >= 1100:  # need ~4+ years
                try:
                    with st.spinner("Running walk-forward backtest (this takes a moment)..."):
                        wf = walk_forward_backtest(hist, train_days=756, test_days=126, step_days=63)

                    if wf.get("error"):
                        st.warning(f"Walk-forward: {wf['error']}")
                    else:
                        oos = wf["oos_summary"]
                        is_ = wf["is_summary"]

                        st.markdown(f"**{oos['n_windows']} walk-forward windows evaluated**")

                        wc1, wc2, wc3, wc4 = st.columns(4)
                        with wc1:
                            st.metric("OOS Win Rate", f"{oos['avg_win_rate']:.1f}%",
                                      help="Average win rate across all out-of-sample windows")
                        with wc2:
                            st.metric("OOS Avg P&L", f"{oos['avg_pnl_pct']:+.3f}%",
                                      help="Average P&L per trade across OOS windows")
                        with wc3:
                            st.metric("OOS Sharpe", f"{oos['avg_sharpe']:.3f}",
                                      help="Average Sharpe ratio across OOS windows")
                        with wc4:
                            of = wf["overfit_ratio"]
                            st.metric("Overfit Ratio", f"{of:.2f}x",
                                      help="In-sample P&L / OOS P&L. >2x = likely overfit")

                        # IS vs OOS comparison
                        st.markdown("**In-Sample vs Out-of-Sample:**")
                        comp_df = pd.DataFrame([
                            {"Metric": "Avg P&L %", "In-Sample": f"{is_['avg_pnl_pct']:+.3f}%",
                             "Out-of-Sample": f"{oos['avg_pnl_pct']:+.3f}%"},
                            {"Metric": "Win Rate", "In-Sample": f"{is_['avg_win_rate']:.1f}%",
                             "Out-of-Sample": f"{oos['avg_win_rate']:.1f}%"},
                            {"Metric": "Sharpe", "In-Sample": f"{is_['avg_sharpe']:.3f}",
                             "Out-of-Sample": f"{oos['avg_sharpe']:.3f}"},
                        ])
                        st.dataframe(comp_df, use_container_width=True, hide_index=True)

                        if of > 2:
                            st.error(f"Overfit ratio {of:.1f}x — in-sample results are misleading. "
                                     f"Do NOT trust the standard backtest numbers.")
                        elif of > 1.3:
                            st.warning(f"Overfit ratio {of:.1f}x — some degradation OOS. "
                                       f"Real results will likely be worse than backtest suggests.")
                        elif oos["avg_pnl_pct"] > 0:
                            st.success(f"Strategy holds up out-of-sample (overfit ratio {of:.1f}x). "
                                       f"OOS P&L is positive.")
                        else:
                            st.error(f"OOS P&L is negative ({oos['avg_pnl_pct']:+.3f}%). "
                                     f"Strategy does not work on unseen data.")

                        # Window-by-window chart
                        if wf.get("window_details"):
                            wd = pd.DataFrame(wf["window_details"])
                            fig_wf = go.Figure()
                            fig_wf.add_trace(go.Bar(
                                x=wd["test_start"], y=wd["oos_avg_pnl"],
                                name="OOS Avg P&L",
                                marker_color=["green" if p > 0 else "red" for p in wd["oos_avg_pnl"]],
                            ))
                            fig_wf.add_hline(y=0, line_dash="dash", line_color="gray")
                            fig_wf.update_layout(
                                title="Out-of-Sample P&L by Window",
                                yaxis_title="Avg P&L %", xaxis_title="Test Window Start",
                                height=300,
                            )
                            st.plotly_chart(fig_wf, use_container_width=True)

                except Exception as e:
                    st.warning(f"Walk-forward failed: {e}")
            else:
                st.info(f"Need ~4+ years of data for walk-forward ({len(hist)} rows available, need ~1100). "
                        f"Try a ticker with longer history.")

        # --- Volatility chart ---
        with st.expander("Volatility History", expanded=False):
            vol_fig = go.Figure()
            rv_10_series = hist["Close"].pct_change().rolling(10).std() * np.sqrt(252) * 100
            rv_20_series = hist["Close"].pct_change().rolling(20).std() * np.sqrt(252) * 100
            rv_30_series = hist["Close"].pct_change().rolling(30).std() * np.sqrt(252) * 100
            vol_fig.add_trace(go.Scatter(x=rv_10_series.index, y=rv_10_series, name="RV 10d", line=dict(width=1)))
            vol_fig.add_trace(go.Scatter(x=rv_20_series.index, y=rv_20_series, name="RV 20d", line=dict(width=2)))
            vol_fig.add_trace(go.Scatter(x=rv_30_series.index, y=rv_30_series, name="RV 30d", line=dict(width=1)))
            if current_iv:
                vol_fig.add_hline(y=current_iv, line_dash="dash", line_color="red",
                                  annotation_text=f"Current IV: {current_iv:.1f}%")
            vol_fig.update_layout(
                title=f"{ticker} Realized Volatility vs Current IV",
                yaxis_title="Annualized Volatility (%)", height=400, margin=dict(t=40, b=20),
            )
            st.plotly_chart(vol_fig, use_container_width=True)

        # --- VIX Context ---
        with st.expander("Market Context (VIX)", expanded=False):
            try:
                vix_hist, vix3m_hist = load_vix_data()
            except Exception:
                vix_hist, vix3m_hist = pd.DataFrame(), None
            if vix_hist is None or vix_hist.empty:
                st.warning("VIX data unavailable — Yahoo Finance may be throttling index data. Try refreshing.")
            else:
                current_vix = vix_hist["Close"].iloc[-1]
                vix_mean = vix_hist["Close"].mean()
                vcol1, vcol2, vcol3, vcol4 = st.columns(4)
                with vcol1:
                    st.metric("VIX", f"{current_vix:.1f}", help=TIPS["vix"])
                with vcol2:
                    st.metric("Period Mean", f"{vix_mean:.1f}",
                               help="Average VIX over available history. Long-term average is ~20.")
                with vcol3:
                    st.metric("Period Low", f"{vix_hist['Close'].min():.1f}")
                with vcol4:
                    st.metric("Period High", f"{vix_hist['Close'].max():.1f}")

                vix_fig = go.Figure()
                vix_fig.add_trace(go.Scatter(
                    x=vix_hist.index, y=vix_hist["Close"],
                    name="VIX", line=dict(color="orange", width=2)
                ))
                vix_fig.add_hline(y=20, line_dash="dash", line_color="gray",
                                  annotation_text="Long-term avg (~20)")
                vix_fig.update_layout(title="VIX", yaxis_title="VIX Level",
                                      height=300, margin=dict(t=40, b=20))
                st.plotly_chart(vix_fig, use_container_width=True)

                if vix3m_hist is not None and not vix3m_hist.empty:
                    current_vix3m = vix3m_hist["Close"].iloc[-1]
                    ratio = current_vix / current_vix3m
                    ts_label = "Contango" if ratio < 0.95 else ("Backwardation" if ratio > 1.05 else "Flat")
                    st.metric("VIX/VIX3M Ratio", f"{ratio:.3f} ({ts_label})",
                               help="VIX / VIX3M ratio. Below 0.95 = contango (calm). "
                                    "Above 1.05 = backwardation (fear). "
                                    "This is the single best indicator of whether it's safe to sell options.")

        st.divider()

    # --- Portfolio Correlation (outside ticker loop, shows if multiple tickers) ---
    if len(tickers) >= 2:
        with st.expander("Portfolio Correlation Risk", expanded=False):
            st.markdown(
                "If you sell options on multiple stocks, a market-wide move hits all of them. "
                "High correlation = less diversification = more portfolio risk."
            )
            with st.spinner("Computing correlations..."):
                corr_data = calc_portfolio_correlation(tickers)
            if corr_data:
                st.metric("Avg Pairwise Correlation", f"{corr_data['avg_pairwise_corr']:.2f}",
                           help="Average correlation between your holdings. "
                                "Above 0.6 = highly correlated (a market drop hits everything). "
                                "Below 0.3 = well diversified.")
                st.metric("Diversification Ratio", f"{corr_data['diversification_ratio']:.2f}",
                           help="Higher = more diversification benefit. "
                                "1.0 = no diversification (stocks move together). "
                                "2.0+ = good diversification.")

                # Correlation heatmap
                corr_fig = go.Figure(data=go.Heatmap(
                    z=corr_data["correlation_matrix"].values,
                    x=corr_data["correlation_matrix"].columns,
                    y=corr_data["correlation_matrix"].index,
                    colorscale="RdYlGn_r",
                    zmin=-1, zmax=1,
                    text=corr_data["correlation_matrix"].round(2).values,
                    texttemplate="%{text}",
                ))
                corr_fig.update_layout(title="Return Correlations (1 Year)", height=400)
                st.plotly_chart(corr_fig, use_container_width=True)

                # Beta-weighting
                betas = corr_data.get("betas", {})
                portfolio_beta = corr_data.get("portfolio_beta")
                if betas:
                    st.subheader("SPY Beta")
                    beta_cols = st.columns(len(betas) + 1)
                    for i, (t, b) in enumerate(betas.items()):
                        with beta_cols[i]:
                            st.metric(t, f"{b:.2f}",
                                      help="Beta to SPY. 1.0 = moves with market. >1.2 = amplifies market moves.")
                    if portfolio_beta is not None:
                        with beta_cols[-1]:
                            st.metric("Portfolio", f"{portfolio_beta:.2f}",
                                      help="Equal-weighted portfolio beta. >1.5 = very concentrated directional risk.")
                        if portfolio_beta > 1.5:
                            st.error(
                                f"**Portfolio beta is {portfolio_beta:.2f}** — very concentrated market exposure. "
                                f"A 5% S&P drop could mean a ~{portfolio_beta * 5:.0f}% portfolio hit. "
                                f"Consider reducing total short-put exposure or hedging."
                            )
                        elif portfolio_beta > 1.2:
                            st.warning(
                                f"**Portfolio beta is {portfolio_beta:.2f}** — above-average market sensitivity. "
                                f"Be aware of concentrated directional risk."
                            )

                if corr_data["avg_pairwise_corr"] > 0.6:
                    st.warning(
                        f"**Your holdings are highly correlated ({corr_data['avg_pairwise_corr']:.2f}).** "
                        f"If you sell options on all of them, a market drop triggers losses on every position simultaneously. "
                        f"Consider reducing total short option exposure or adding uncorrelated positions."
                    )


# ============================================================
# TAB: TRADE ANALYZER
# ============================================================
with tab_analyzer:
    st.header("Trade Analyzer")
    st.caption("Pick a ticker and expiration to analyze specific trades with full risk breakdown.")

    if not tickers:
        st.info("Enter a ticker above to start analyzing trades.")
    else:
        # Use first ticker or let user pick
        analyze_ticker = st.selectbox("Analyze", tickers, key="analyzer_ticker")

        try:
            with st.spinner(f"Loading {analyze_ticker}..."):
                data = compute_analytics(analyze_ticker)
        except Exception as e:
            err_name = type(e).__name__
            if "RateLimit" in err_name:
                st.error(f"Yahoo Finance rate limit hit. Please wait 30-60 seconds and refresh the page.")
            else:
                st.error(f"Error loading {analyze_ticker}: {err_name} — {e}")
            data = None

        if data is None:
            st.error(f"No data for {analyze_ticker}")
        elif not data["chains"] or not data["expirations"]:
            st.warning(
                f"No options data loaded for {analyze_ticker}. This usually means Yahoo Finance is rate-limiting requests. "
                f"Wait 30-60 seconds and refresh. The Dashboard tab may still work since its data is cached."
            )
        else:
            current_price = data["current_price"]
            current_iv = data["current_iv"]
            rv_forecast = data["rv_forecast"]
            iv_rank = data["iv_rank"]
            term_label = data["term_label"]
            vrp = data["vrp"]
            chains = data["chains"]
            expirations = data["expirations"]

            # Earnings warning in analyzer
            earnings_days_az = data.get("earnings_days")
            earnings_date_az = data.get("earnings_date")
            if earnings_days_az is not None and 0 <= earnings_days_az <= 14:
                st.error(
                    f"**EARNINGS IN {earnings_days_az} DAYS** ({earnings_date_az.strftime('%b %d')}). "
                    f"Do NOT sell options through earnings unless you understand the implied move is likely fair. "
                    f"Any expiration after earnings has earnings risk baked into the premium."
                )

            # Signal context at top
            signal = data["signal"]
            if signal == "GREEN":
                st.success(f"**{analyze_ticker} conditions favor selling** — VRP: {vrp:+.1f}, IV Rank: {iv_rank:.0f}%, Term: {term_label}")
            elif signal == "YELLOW":
                st.warning(f"**{analyze_ticker} conditions are marginal** — VRP: {vrp:+.1f}, IV Rank: {iv_rank:.0f}%, Term: {term_label}")
            else:
                vrp_str = f"{vrp:+.1f}" if vrp is not None else "N/A"
                ivr_str = f"{iv_rank:.0f}%" if iv_rank is not None else "N/A"
                st.error(f"**{analyze_ticker} conditions are unfavorable** — VRP: {vrp_str}, IV Rank: {ivr_str}, Term: {term_label}")
                explanation = explain_signal_plain_english(
                    signal, vrp, iv_rank, term_label, current_iv, data["rv_20"], current_price
                )
                st.markdown(explanation)

            def fmt_exp(x):
                try:
                    days = (datetime.strptime(x, "%Y-%m-%d") - datetime.now()).days
                    label = f"{x} ({days}d)"
                    # Flag if this expiration spans earnings
                    if earnings_days_az is not None and earnings_date_az is not None:
                        exp_dt = datetime.strptime(x, "%Y-%m-%d")
                        if exp_dt > earnings_date_az and earnings_days_az >= 0:
                            label += " ⚠ SPANS EARNINGS"
                    # Flag if expiration spans FOMC
                    fomc_d, fomc_dy = data.get("fomc_date"), data.get("fomc_days")
                    if fomc_d is not None and fomc_dy is not None and fomc_dy >= 0:
                        exp_dt = datetime.strptime(x, "%Y-%m-%d")
                        if exp_dt > fomc_d:
                            label += " ⚠ SPANS FOMC"
                    return label
                except Exception:
                    return x

            # Default to ~30-45 DTE (optimal theta decay window)
            default_idx = 0
            for i, exp in enumerate(expirations):
                try:
                    days = (datetime.strptime(exp, "%Y-%m-%d") - datetime.now()).days
                    if days >= 28:
                        default_idx = i
                        break
                except Exception:
                    pass

            exp_choice = st.selectbox(
                "Expiration",
                expirations,
                index=default_idx,
                format_func=fmt_exp,
                key="az_exp",
                help="30-45 DTE is the sweet spot for selling options — theta decay accelerates while gamma risk is still manageable.",
            )
            try:
                dte = max((datetime.strptime(exp_choice, "%Y-%m-%d") - datetime.now()).days, 1)
            except Exception:
                dte = 30

            # Load the selected chain on demand
            with st.spinner(f"Loading {exp_choice} chain..."):
                selected_chain = load_chain(analyze_ticker, exp_choice)
            if selected_chain is None:
                st.error(f"Could not load options chain for {exp_choice}")
            else:

              # Vol Surface
              with st.expander("Volatility Smile / Skew", expanded=False):
                  vol_surf = build_vol_surface(selected_chain.calls, selected_chain.puts, current_price, dte)
                  if vol_surf:
                      skew_fig = go.Figure()
                      calls_data = vol_surf["data"][vol_surf["data"]["type"] == "call"]
                      puts_data = vol_surf["data"][vol_surf["data"]["type"] == "put"]
                      skew_fig.add_trace(go.Scatter(
                          x=calls_data["strike"], y=calls_data["iv"],
                          mode="markers+lines", name="Calls", marker=dict(color="green"),
                      ))
                      skew_fig.add_trace(go.Scatter(
                          x=puts_data["strike"], y=puts_data["iv"],
                          mode="markers+lines", name="Puts", marker=dict(color="red"),
                      ))
                      skew_fig.add_vline(x=current_price, line_dash="dash", line_color="gray",
                                          annotation_text=f"Stock: ${current_price:.0f}")
                      skew_fig.update_layout(
                          title=f"IV Smile — {exp_choice} ({dte}d)",
                          xaxis_title="Strike", yaxis_title="Implied Volatility (%)",
                          height=350, margin=dict(t=40, b=20),
                      )
                      st.plotly_chart(skew_fig, use_container_width=True)

                      sc1, sc2, sc3 = st.columns(3)
                      with sc1:
                          st.metric("ATM IV", f"{vol_surf['atm_iv']:.1f}%",
                                     help="At-the-money implied volatility. The baseline.")
                      with sc2:
                          st.metric("Put Skew", f"{vol_surf['put_skew']:+.1f} pts",
                                     help="How much more OTM puts cost vs ATM. Positive = puts are expensive "
                                          "(normal — people buy puts for protection). "
                                          "Bigger skew = more premium in OTM puts = potential edge for put sellers, "
                                          "BUT also reflects real tail risk.")
                      with sc3:
                          st.metric("Call Skew", f"{vol_surf['call_skew']:+.1f} pts",
                                     help="How much more/less OTM calls cost vs ATM. Usually negative or flat. "
                                          "Positive call skew can appear before earnings or takeover speculation.")

                      if vol_surf["put_skew"] > 5:
                          st.info(
                              f"**Large put skew ({vol_surf['put_skew']:+.1f} pts).** "
                              f"OTM puts are significantly more expensive than ATM options. "
                              f"This means put sellers collect extra 'skew premium' on top of VRP — "
                              f"a potential double edge. But the skew exists because real crash risk is priced in."
                          )

              tab_calls, tab_puts = st.tabs(["Covered Calls", "Cash-Secured Puts"])

              # ----- CALLS -----
              with tab_calls:
                st.markdown(
                    "**Selling covered calls**: You own shares and sell someone the right to buy them at a higher price. "
                    "You collect premium upfront. Upside is capped at the strike price."
                )
                calls_df = selected_chain.calls.copy()
                if not calls_df.empty:
                    calls_df = calc_greeks_for_chain(calls_df, current_price, dte, "call")
                    calls_df = calls_df[
                        (calls_df["strike"] >= current_price * 0.9) &
                        (calls_df["strike"] <= current_price * 1.2)
                    ].copy()

                    if not calls_df.empty:
                        calls_df["edge_score"] = calls_df.apply(
                            lambda r: score_trade(r, current_iv, rv_forecast, iv_rank, term_label, skew_penalty=data.get("skew_penalty", 0)), axis=1
                        )

                        display_cols = [
                            "strike", "lastPrice", "bid", "ask", "impliedVolatility",
                            "calc_delta", "calc_theta", "calc_vega", "calc_gamma",
                            "volume", "openInterest", "edge_score"
                        ]
                        display_cols = [c for c in display_cols if c in calls_df.columns]
                        show_df = calls_df[display_cols].copy()
                        show_df.columns = [
                            c.replace("calc_", "").replace("impliedVolatility", "IV")
                            .replace("lastPrice", "last").replace("openInterest", "OI")
                            .replace("edge_score", "EDGE")
                            for c in show_df.columns
                        ]
                        if "IV" in show_df.columns:
                            show_df["IV"] = (show_df["IV"] * 100).round(1)

                        st.markdown(
                            "**Column guide**: "
                            "**strike** = price at which shares get called away | "
                            "**bid/ask** = what you can sell/buy for | "
                            "**IV** = implied volatility at this strike | "
                            "**delta** = prob of assignment & price sensitivity | "
                            "**theta** = daily decay (your daily income) | "
                            "**vega** = sensitivity to IV changes | "
                            "**EDGE** = composite score (1-10, higher = more edge)"
                        )

                        st.dataframe(
                            show_df.style.format({
                                "strike": "{:.0f}", "last": "{:.2f}", "bid": "{:.2f}",
                                "ask": "{:.2f}", "IV": "{:.1f}", "delta": "{:.3f}",
                                "theta": "{:.4f}", "vega": "{:.4f}", "gamma": "{:.5f}",
                            }).background_gradient(subset=["EDGE"], cmap="RdYlGn", vmin=1, vmax=10),
                            use_container_width=True, hide_index=True,
                        )

                        # Recommendation
                        otm_calls = calls_df[calls_df["calc_delta"].between(0.15, 0.35)]
                        if not otm_calls.empty:
                            best = otm_calls.loc[otm_calls["edge_score"].idxmax()]
                            premium = best["bid"] if best["bid"] > 0 else best["lastPrice"]
                            max_gain = premium + (best["strike"] - current_price)
                            strike_iv = best["impliedVolatility"] * 100

                            st.info(
                                f"**Recommended**: Sell the **${best['strike']:.0f} call** "
                                f"(delta {best['calc_delta']:.2f}, IV {strike_iv:.1f}%) "
                                f"for ~${premium:.2f} premium. "
                                f"Max gain: ${max_gain:.2f}/share. "
                                f"Edge score: {best['edge_score']:.0f}/10"
                            )

                            # === FULL RISK ANALYSIS ===
                            prob_loss, prob_assign, prob_cat = calc_prob_of_loss(
                                current_price, best["strike"], strike_iv, dte, "call", premium,
                                hist=data["hist"]
                            )
                            if prob_loss is not None:
                                avg_win = premium * 100
                                avg_loss = abs(float(np.mean([
                                    max(0, current_price * 1.1 - best["strike"]) - premium,
                                    max(0, current_price * 1.15 - best["strike"]) - premium,
                                ]))) * 100
                                kelly_frac = calc_kelly_size(
                                    1 - prob_loss, avg_win, max(avg_loss, 1),
                                    skewness=bt_skewness,
                                )
                            else:
                                kelly_frac = 0

                            conf_score, conf_checks = calc_edge_confidence(
                                vrp, iv_rank, term_label, prob_loss,
                                best.get("volume", 0), best.get("openInterest", 0), dte
                            )

                            st.subheader("Risk & Confidence")
                            rc1, rc2, rc3, rc4 = st.columns(4)
                            with rc1:
                                st.metric("Prob of Profit",
                                           f"{(1-prob_loss)*100:.1f}%" if prob_loss is not None else "N/A",
                                           help=TIPS["prob_profit"])
                            with rc2:
                                st.metric("Prob of Assignment",
                                           f"{prob_assign*100:.1f}%" if prob_assign is not None else "N/A",
                                           help=TIPS["prob_assign"])
                            with rc3:
                                kelly_help = TIPS["kelly"]
                                if bt_skewness is not None:
                                    kelly_help += f" Adjusted for P&L skew ({bt_skewness:.2f})."
                                st.metric("Kelly Size",
                                           f"{kelly_frac*100:.1f}% of capital" if kelly_frac > 0 else "No edge",
                                           help=kelly_help)
                            with rc4:
                                grade = "A" if conf_score >= 80 else "B" if conf_score >= 60 else "C" if conf_score >= 40 else "D" if conf_score >= 25 else "F"
                                st.metric("Confidence", f"{grade} ({conf_score}/100)",
                                           help=TIPS["confidence"])

                            # Edge checklist
                            with st.expander("Edge Checklist — Why or why not?", expanded=True):
                                for check_name, (pts, desc) in conf_checks.items():
                                    if pts >= 10:
                                        st.markdown(f"  :white_check_mark: **{check_name}** ({pts}pts): {desc}")
                                    elif pts >= 5:
                                        st.markdown(f"  :warning: **{check_name}** ({pts}pts): {desc}")
                                    else:
                                        st.markdown(f"  :x: **{check_name}** ({pts}pts): {desc}")

                            # Monte Carlo
                            mc = run_monte_carlo(current_price, strike_iv, dte, best["strike"], premium, "call")
                            if mc:
                                st.subheader("Simulated Outcomes (10,000 scenarios)")
                                mc1, mc2, mc3, mc4 = st.columns(4)
                                with mc1:
                                    st.metric("Expected P&L", f"${mc['expected_value']:+,.0f}",
                                               help=TIPS["mc_ev"])
                                with mc2:
                                    st.metric("Prob of Profit", f"{mc['prob_profit']*100:.1f}%")
                                with mc3:
                                    st.metric("5th Pctl (worst realistic)", f"${mc['pct_5']:+,.0f}",
                                               help=TIPS["mc_5pct"])
                                with mc4:
                                    st.metric("95th Pctl (best realistic)", f"${mc['pct_95']:+,.0f}")

                                pnl_fig = go.Figure()
                                pnl_fig.add_trace(go.Histogram(x=mc["pnl"], nbinsx=80, name="P&L"))
                                pnl_fig.add_vline(x=0, line_dash="dash", line_color="white")
                                pnl_fig.update_layout(
                                    title="P&L Distribution at Expiration (per contract)",
                                    xaxis_title="P&L ($)", yaxis_title="Frequency",
                                    height=300, margin=dict(t=40, b=20), showlegend=False,
                                )
                                st.plotly_chart(pnl_fig, use_container_width=True)
                                st.caption(
                                    f"Skew: {mc['skew']:.2f} | Kurtosis: {mc['kurtosis']:.2f} — "
                                    + ("Negative skew = small wins often, rare big losses (normal for selling options)"
                                       if mc['skew'] < -0.5 else "Distribution shape is relatively symmetric"),
                                    help=TIPS["skew"],
                                )

                            # Stress test
                            with st.expander("Stress Test: P&L under combined shocks"):
                                st.markdown(
                                    "This table shows your P&L if the stock moves **and** implied volatility changes simultaneously. "
                                    "Red = you lose money. Green = you make money. "
                                    "The column headers show IV change in vol points. "
                                    "Evaluated at the midpoint of the trade's life."
                                )
                                stress_df = stress_test_trade(current_price, best["strike"], premium, strike_iv, dte, "call")
                                st.dataframe(
                                    stress_df.set_index("Stock Move").style.format("${:+,.0f}")
                                    .background_gradient(cmap="RdYlGn", axis=None),
                                    use_container_width=True,
                                )

            # ----- PUTS -----
            with tab_puts:
                st.markdown(
                    "**Selling cash-secured puts**: You agree to buy shares at the strike price if the stock drops. "
                    "You collect premium upfront. If assigned, your cost basis = strike - premium (a discount)."
                )
                puts_df = selected_chain.puts.copy()
                if not puts_df.empty:
                    puts_df = calc_greeks_for_chain(puts_df, current_price, dte, "put")
                    puts_df = puts_df[
                        (puts_df["strike"] >= current_price * 0.8) &
                        (puts_df["strike"] <= current_price * 1.05)
                    ].copy()

                    if not puts_df.empty:
                        puts_df["edge_score"] = puts_df.apply(
                            lambda r: score_trade(r, current_iv, rv_forecast, iv_rank, term_label, skew_penalty=data.get("skew_penalty", 0)), axis=1
                        )
                        puts_df["eff_buy_price"] = puts_df["strike"] - puts_df.apply(
                            lambda r: r["bid"] if r["bid"] > 0 else r["lastPrice"], axis=1
                        )

                        display_cols = [
                            "strike", "lastPrice", "bid", "ask", "impliedVolatility",
                            "calc_delta", "calc_theta", "calc_vega",
                            "eff_buy_price", "volume", "openInterest", "edge_score"
                        ]
                        display_cols = [c for c in display_cols if c in puts_df.columns]
                        show_df = puts_df[display_cols].copy()
                        show_df.columns = [
                            c.replace("calc_", "").replace("impliedVolatility", "IV")
                            .replace("lastPrice", "last").replace("openInterest", "OI")
                            .replace("edge_score", "EDGE").replace("eff_buy_price", "eff_buy")
                            for c in show_df.columns
                        ]
                        if "IV" in show_df.columns:
                            show_df["IV"] = (show_df["IV"] * 100).round(1)

                        st.markdown(
                            "**Column guide**: "
                            "**strike** = price at which you buy shares if assigned | "
                            "**eff_buy** = effective purchase price (strike - premium) | "
                            "**delta** = negative = prob of assignment | "
                            "**EDGE** = composite score (1-10)"
                        )

                        st.dataframe(
                            show_df.style.format({
                                "strike": "{:.0f}", "last": "{:.2f}", "bid": "{:.2f}",
                                "ask": "{:.2f}", "IV": "{:.1f}", "delta": "{:.3f}",
                                "theta": "{:.4f}", "vega": "{:.4f}", "eff_buy": "{:.2f}",
                            }).background_gradient(subset=["EDGE"], cmap="RdYlGn", vmin=1, vmax=10),
                            use_container_width=True, hide_index=True,
                        )

                        otm_puts = puts_df[puts_df["calc_delta"].between(-0.35, -0.15)]
                        if not otm_puts.empty:
                            best = otm_puts.loc[otm_puts["edge_score"].idxmax()]
                            premium = best["bid"] if best["bid"] > 0 else best["lastPrice"]
                            eff_price = best["strike"] - premium
                            discount = ((current_price - eff_price) / current_price) * 100
                            strike_iv_p = best["impliedVolatility"] * 100

                            st.info(
                                f"**Recommended**: Sell the **${best['strike']:.0f} put** "
                                f"(delta {best['calc_delta']:.2f}, IV {strike_iv_p:.1f}%) "
                                f"for ~${premium:.2f} premium. "
                                f"Effective buy price: ${eff_price:.2f} ({discount:.1f}% discount). "
                                f"Edge score: {best['edge_score']:.0f}/10"
                            )

                            prob_loss_p, prob_assign_p, prob_cat_p = calc_prob_of_loss(
                                current_price, best["strike"], strike_iv_p, dte, "put", premium,
                                hist=data["hist"]
                            )
                            if prob_loss_p is not None:
                                avg_win_p = premium * 100
                                avg_loss_p = abs(float(np.mean([
                                    max(0, best["strike"] - current_price * 0.9) - premium,
                                    max(0, best["strike"] - current_price * 0.85) - premium,
                                ]))) * 100
                                kelly_frac_p = calc_kelly_size(
                                    1 - prob_loss_p, avg_win_p, max(avg_loss_p, 1),
                                    skewness=bt_skewness,
                                )
                            else:
                                kelly_frac_p = 0

                            conf_score_p, conf_checks_p = calc_edge_confidence(
                                vrp, iv_rank, term_label, prob_loss_p,
                                best.get("volume", 0), best.get("openInterest", 0), dte
                            )

                            st.subheader("Risk & Confidence")
                            rc1, rc2, rc3, rc4 = st.columns(4)
                            with rc1:
                                st.metric("Prob of Profit",
                                           f"{(1-prob_loss_p)*100:.1f}%" if prob_loss_p is not None else "N/A",
                                           help=TIPS["prob_profit"])
                            with rc2:
                                st.metric("Prob of Assignment",
                                           f"{prob_assign_p*100:.1f}%" if prob_assign_p is not None else "N/A",
                                           help=TIPS["prob_assign"])
                            with rc3:
                                st.metric("Kelly Size",
                                           f"{kelly_frac_p*100:.1f}% of capital" if kelly_frac_p > 0 else "No edge",
                                           help=TIPS["kelly"])
                            with rc4:
                                grade_p = "A" if conf_score_p >= 80 else "B" if conf_score_p >= 60 else "C" if conf_score_p >= 40 else "D" if conf_score_p >= 25 else "F"
                                st.metric("Confidence", f"{grade_p} ({conf_score_p}/100)",
                                           help=TIPS["confidence"])

                            with st.expander("Edge Checklist — Why or why not?", expanded=True):
                                for check_name, (pts, desc) in conf_checks_p.items():
                                    if pts >= 10:
                                        st.markdown(f"  :white_check_mark: **{check_name}** ({pts}pts): {desc}")
                                    elif pts >= 5:
                                        st.markdown(f"  :warning: **{check_name}** ({pts}pts): {desc}")
                                    else:
                                        st.markdown(f"  :x: **{check_name}** ({pts}pts): {desc}")

                            mc_p = run_monte_carlo(current_price, strike_iv_p, dte, best["strike"], premium, "put")
                            if mc_p:
                                st.subheader("Simulated Outcomes (10,000 scenarios)")
                                mc1, mc2, mc3, mc4 = st.columns(4)
                                with mc1:
                                    st.metric("Expected P&L", f"${mc_p['expected_value']:+,.0f}",
                                               help=TIPS["mc_ev"])
                                with mc2:
                                    st.metric("Prob of Profit", f"{mc_p['prob_profit']*100:.1f}%")
                                with mc3:
                                    st.metric("5th Pctl (worst realistic)", f"${mc_p['pct_5']:+,.0f}",
                                               help=TIPS["mc_5pct"])
                                with mc4:
                                    st.metric("95th Pctl (best realistic)", f"${mc_p['pct_95']:+,.0f}")

                                pnl_fig_p = go.Figure()
                                pnl_fig_p.add_trace(go.Histogram(x=mc_p["pnl"], nbinsx=80))
                                pnl_fig_p.add_vline(x=0, line_dash="dash", line_color="white")
                                pnl_fig_p.update_layout(
                                    title="P&L Distribution at Expiration",
                                    xaxis_title="P&L ($)", yaxis_title="Frequency",
                                    height=300, margin=dict(t=40, b=20), showlegend=False,
                                )
                                st.plotly_chart(pnl_fig_p, use_container_width=True)
                                st.caption(
                                    f"Skew: {mc_p['skew']:.2f} | Kurtosis: {mc_p['kurtosis']:.2f}",
                                    help=TIPS["skew"],
                                )

                            with st.expander("Stress Test: P&L under combined shocks"):
                                st.markdown(
                                    "P&L if stock moves AND IV changes simultaneously. "
                                    "Evaluated at midpoint of trade life."
                                )
                                stress_df_p = stress_test_trade(current_price, best["strike"], premium, strike_iv_p, dte, "put")
                                st.dataframe(
                                    stress_df_p.set_index("Stock Move").style.format("${:+,.0f}")
                                    .background_gradient(cmap="RdYlGn", axis=None),
                                    use_container_width=True,
                                )


# ============================================================
# TAB: MY POSITIONS
# ============================================================
with tab_positions:
    st.header("My Positions")

    with st.expander("Log a New Trade", expanded=False):
        with st.form("add_trade_form"):
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                t_ticker = st.text_input("Ticker", value="AAPL").upper()
                t_type = st.selectbox("Type", ["call", "put"])
                t_strategy = st.selectbox("Strategy", ["covered_call", "cash_secured_put"])
            with fc2:
                t_strike = st.number_input("Strike Price", min_value=1.0, value=250.0, step=5.0)
                t_premium = st.number_input("Premium Received (per share)", min_value=0.01, value=3.00, step=0.25)
                t_contracts = st.number_input("Contracts", min_value=1, value=1, step=1)
            with fc3:
                t_expiration = st.date_input("Expiration Date", value=datetime.now() + timedelta(days=30))
                t_notes = st.text_input("Notes (optional)", value="")

            submitted = st.form_submit_button("Log Trade")
            if submitted:
                add_trade(
                    ticker=t_ticker, option_type=t_type, strike=t_strike,
                    expiration=t_expiration.strftime("%Y-%m-%d"),
                    premium=t_premium, contracts=t_contracts,
                    strategy=t_strategy, notes=t_notes,
                )
                st.success(f"Logged: Short {t_contracts} {t_ticker} {t_strike} {t_type} @ ${t_premium:.2f}")
                st.rerun()

    open_trades = get_open_trades()

    # --- Circuit Breakers (Module 8C) ---
    try:
        vix_cb = None
        try:
            vix_data_cb = yf_proxy.get_stock_history("^VIX", period="5d")
            if not vix_data_cb.empty:
                vix_cb = float(vix_data_cb["Close"].iloc[-1])
        except Exception:
            pass

        fomc_date_cb, fomc_days_cb = get_next_fomc_date()

        open_tickers_cb = list(set(t.get("ticker", "") for t in open_trades)) if open_trades else []

        cb = check_circuit_breakers(
            vix_level=vix_cb,
            fomc_days=fomc_days_cb,
            open_tickers=open_tickers_cb,
        )

        if cb["n_alerts"] > 0:
            for alert in cb["alerts"]:
                if alert["severity"] == "CRITICAL":
                    st.error(f"**{alert['type']} CIRCUIT BREAKER**: {alert['message']}\n\n"
                             f"**Action:** {alert['action']}")
                elif alert["severity"] == "HIGH":
                    st.warning(f"**{alert['type']} CIRCUIT BREAKER**: {alert['message']}\n\n"
                               f"**Action:** {alert['action']}")
                elif alert["severity"] == "MODERATE":
                    st.info(f"**{alert['type']}**: {alert['message']} — {alert['action']}")

            if cb["sizing_multiplier"] < 1.0:
                st.caption(f"Position sizing adjusted to {cb['sizing_multiplier']:.0%} of normal")
    except Exception:
        pass

    if not open_trades:
        st.info("No open positions. Log a trade above or use the Trade Analyzer to find opportunities.")
    else:
        for trade in open_trades:
            ticker = trade["ticker"]
            with st.spinner(f"Checking {ticker} {trade['strike']} {trade['option_type']}..."):
                try:
                    hist = yf_proxy.get_stock_history(ticker, period="1y")
                    if hist.empty:
                        raise ValueError(f"No history data for {ticker}")
                    spot = hist["Close"].iloc[-1]

                    current_option_price = None
                    current_delta = None
                    try:
                        trade_chain = yf_proxy.get_option_chain(ticker, trade["expiration"])
                        if trade["option_type"] == "call":
                            chain = trade_chain.calls
                        else:
                            chain = trade_chain.puts
                        match = chain[chain["strike"] == trade["strike"]]
                        if not match.empty:
                            row = match.iloc[0]
                            bid = row.get("bid", 0) or 0
                            ask = row.get("ask", 0) or 0
                            mid = (bid + ask) / 2 if bid > 0 else row.get("lastPrice", 0)
                            current_option_price = mid
                            dte_now = max((datetime.strptime(trade["expiration"], "%Y-%m-%d") - datetime.now()).days, 1)
                            iv_now = row.get("impliedVolatility", 0.3)
                            try:
                                from py_vollib.black_scholes.greeks.analytical import delta as bs_delta_fn
                                flag = "c" if trade["option_type"] == "call" else "p"
                                t_years = max(dte_now / 365.0, 1/365)
                                current_delta = bs_delta_fn(flag, spot, trade["strike"], t_years, 0.045, iv_now)
                            except Exception:
                                pass
                    except Exception:
                        pass

                    rv_20 = calc_realized_vol(hist, window=20)
                    current_iv = None
                    term_label_pos = "N/A"
                    try:
                        exps = yf_proxy.get_expirations(ticker)
                        if exps:
                            first_chain = yf_proxy.get_option_chain(ticker, exps[0])
                            if not first_chain.calls.empty:
                                fc = first_chain.calls.copy()
                                fc["dist"] = abs(fc["strike"] - spot)
                                atm = fc.loc[fc["dist"].idxmin()]
                                current_iv = atm["impliedVolatility"] * 100
                            # Term structure from first 2 expirations
                            chains_for_ts = {exps[0]: first_chain}
                            if len(exps) > 1:
                                second = yf_proxy.get_option_chain(ticker, exps[1])
                                if not second.calls.empty:
                                    chains_for_ts[exps[1]] = second
                            _, term_label_pos = get_term_structure(chains_for_ts, exps[:2], spot)
                    except Exception:
                        pass

                    signals, metrics = generate_exit_signals(
                        trade, spot, current_option_price, current_iv, rv_20, term_label_pos, current_delta
                    )

                    # Add regime and FOMC signals
                    try:
                        regime_pos = classify_vol_regime(
                            vix_level=None, rv20=rv_20,
                            rv60=calc_realized_vol(hist, window=60) if len(hist) >= 60 else None
                        )
                        if regime_pos[0] == "crash":
                            signals.insert(0, ("MUST_SELL", "Crash Regime",
                                "Volatility regime classified as CRASH. Close all short premium positions.",
                                "Close this position immediately."))
                        elif regime_pos[0] == "high_vol":
                            signals.append(("WARNING", "High Vol Regime",
                                f"Volatility regime is elevated ({regime_pos[1].get('reason', '')}).",
                                "Consider reducing size or closing if trade is not well in profit."))
                    except Exception:
                        pass

                    try:
                        fomc_d, fomc_dy = get_next_fomc_date()
                        if fomc_dy is not None:
                            dte_trade = (datetime.strptime(trade["expiration"], "%Y-%m-%d") - datetime.now()).days
                            if fomc_dy <= 3 and dte_trade > 0 and fomc_d and datetime.strptime(trade["expiration"], "%Y-%m-%d") > fomc_d:
                                signals.append(("WARNING", "FOMC Imminent",
                                    f"FOMC decision in {fomc_dy} days and your option expires after it.",
                                    "Consider closing before FOMC if you're near breakeven."))
                    except Exception:
                        pass
                except Exception as e:
                    signals = [("INFO", "Data Error", f"Could not load data: {e}", "Check manually")]
                    metrics = {"dte": 0, "pnl_per_share": None, "pnl_total": None, "pct_of_max": None, "current_delta": None}
                    spot = 0
                    current_option_price = None
                    term_label_pos = "N/A"

            has_must_sell = any(s[0] == "MUST_SELL" for s in signals)
            has_warning = any(s[0] == "WARNING" for s in signals)
            dte_display = metrics.get("dte", "?")
            pnl_display = f"${metrics['pnl_total']:+,.0f}" if metrics.get("pnl_total") is not None else "N/A"
            pct_display = f"{metrics['pct_of_max']:.0f}%" if metrics.get("pct_of_max") is not None else "N/A"

            if has_must_sell:
                st.error(f"**MUST SELL: {ticker} ${trade['strike']:.0f} {trade['option_type'].upper()}** — {dte_display} DTE | P&L: {pnl_display} | {pct_display} of max profit")
            elif has_warning:
                st.warning(f"**{ticker} ${trade['strike']:.0f} {trade['option_type'].upper()}** — {dte_display} DTE | P&L: {pnl_display} | {pct_display} of max profit")
            else:
                st.success(f"**{ticker} ${trade['strike']:.0f} {trade['option_type'].upper()}** — {dte_display} DTE | P&L: {pnl_display} | {pct_display} of max profit")

            with st.expander(f"Details & Action Plan", expanded=has_must_sell):
                d1, d2, d3, d4, d5 = st.columns(5)
                with d1:
                    st.metric("Stock Price", f"${spot:.2f}" if spot else "N/A")
                with d2:
                    st.metric("Option Price", f"${current_option_price:.2f}" if current_option_price else "N/A",
                               help="Current mid price of the option. Compare to your premium received to see P&L.")
                with d3:
                    st.metric("Premium Collected", f"${trade['premium_received']:.2f}",
                               help="What you received when you sold this option. This is your max profit.")
                with d4:
                    st.metric("Current Delta", f"{current_delta:.3f}" if current_delta else "N/A",
                               help=TIPS["delta"])
                with d5:
                    st.metric("Contracts", trade["contracts"])

                st.markdown("### Exit Signals")
                for sev, name, msg, action in signals:
                    if sev == "MUST_SELL":
                        st.error(f"**{name}**: {msg}\n\n**Action: {action}**")
                    elif sev == "WARNING":
                        st.warning(f"**{name}**: {msg}\n\n**Action: {action}**")
                    else:
                        st.info(f"**{name}**: {msg}\n\n**Action: {action}**")

                st.markdown("### What To Do In Every Scenario")
                dte_val = metrics.get("dte", 30)
                pct_val = metrics.get("pct_of_max", 0)
                playbook = get_action_playbook(trade, spot, trade["strike"], dte_val, trade["option_type"], pct_val)
                for scenario, action, reasoning in playbook:
                    st.markdown(f"**If {scenario}:** {action}")
                    st.caption(reasoning)

                bc1, bc2 = st.columns(2)
                with bc1:
                    if st.button(f"Close Trade #{trade['id']}", key=f"close_{trade['id']}"):
                        cp = current_option_price if current_option_price else 0
                        close_trade(trade["id"], cp, "manual_close")
                        st.success("Trade closed!")
                        st.rerun()
                with bc2:
                    if st.button(f"Delete Trade #{trade['id']}", key=f"del_{trade['id']}"):
                        delete_trade(trade["id"])
                        st.warning("Trade deleted")
                        st.rerun()

    # Trade History
    all_trades = get_all_trades()
    closed_trades = [t for t in all_trades if t["status"] != "open"]
    if closed_trades:
        with st.expander(f"Trade History ({len(closed_trades)} closed)", expanded=False):
            hist_data = []
            for t in closed_trades:
                pnl = ((t["premium_received"] - (t.get("close_price") or 0)) * 100 * t["contracts"])
                hist_data.append({
                    "Ticker": t["ticker"], "Type": t["option_type"], "Strike": t["strike"],
                    "Premium": f"${t['premium_received']:.2f}",
                    "Close": f"${t.get('close_price', 0):.2f}" if t.get("close_price") else "Expired",
                    "P&L": f"${pnl:+,.0f}",
                    "Reason": t.get("close_reason", ""),
                    "Opened": t["opened"][:10],
                    "Closed": (t.get("closed_at") or "")[:10],
                })
            st.dataframe(pd.DataFrame(hist_data), use_container_width=True, hide_index=True)
            total_pnl = sum(
                (t["premium_received"] - (t.get("close_price") or 0)) * 100 * t["contracts"]
                for t in closed_trades
            )
            win_count = sum(1 for t in closed_trades if t["premium_received"] > (t.get("close_price") or 0))
            st.metric("Total Realized P&L", f"${total_pnl:+,.0f}")
            st.metric("Win Rate", f"{win_count}/{len(closed_trades)} ({win_count/len(closed_trades)*100:.0f}%)")

    # --- Portfolio Risk Analysis (Module 6) ---
    if open_trades:
        st.divider()
        st.subheader("Portfolio Risk Analysis")

        port_tickers = list(set(t.get("ticker", "") for t in open_trades if t.get("ticker")))

        # Portfolio value input
        portfolio_val = st.number_input(
            "Portfolio Value ($)", min_value=1000, value=100000, step=5000,
            help="Enter total portfolio value for risk calculations as % of portfolio",
            key="portfolio_value_input",
        )

        # --- Capital Deployment Tracking (Module 7B) ---
        deployed_capital = 0
        for t in open_trades:
            try:
                strike = float(t.get("strike", 0))
                contracts = int(t.get("contracts", 1))
                opt_type = t.get("option_type", "call")
                strategy = t.get("strategy", "")

                if "put" in opt_type or "put" in strategy:
                    # Cash-secured put: margin = strike * 100 * contracts
                    margin = strike * 100 * contracts
                else:
                    # Covered call: margin = stock value (already held)
                    spot = float(t.get("spot_at_open", 0) or strike)
                    margin = spot * 100 * contracts
                deployed_capital += margin
            except Exception:
                continue

        deployment_pct = deployed_capital / portfolio_val * 100 if portfolio_val > 0 else 0
        cash_reserve_pct = 100 - deployment_pct

        dc1, dc2, dc3, dc4 = st.columns(4)
        with dc1:
            st.metric("Capital Deployed", f"${deployed_capital:,.0f}",
                      help="Estimated margin/capital tied up in open positions")
        with dc2:
            st.metric("Deployment %", f"{deployment_pct:.0f}%",
                      help="% of portfolio committed to open positions")
        with dc3:
            color = "normal" if cash_reserve_pct >= 35 else "inverse"
            st.metric("Cash Reserve", f"{cash_reserve_pct:.0f}%",
                      help="Uninvested capital. Target: 35-50% normal, 60-75% high vol")
        with dc4:
            st.metric("Positions", len(open_trades))

        # Deployment warnings based on regime targets
        if cash_reserve_pct < 25:
            st.error(
                f"Cash reserve {cash_reserve_pct:.0f}% is DANGEROUSLY LOW. "
                f"Target: >35% in normal markets, >60% in high vol. "
                f"Close some positions or add capital before opening new trades."
            )
        elif cash_reserve_pct < 35:
            st.warning(
                f"Cash reserve {cash_reserve_pct:.0f}% is below the 35% target for normal markets. "
                f"Avoid opening new positions until some close."
            )
        else:
            st.caption(
                f"Deployment targets: Normal regime 50-65% deployed, "
                f"High vol 25-40%, Crisis 0%. Current: {deployment_pct:.0f}% deployed."
            )

        pr_tab1, pr_tab2, pr_tab3 = st.tabs([
            "Vega Stress & Greeks", "Stress Scenarios", "Correlation Analysis"
        ])

        with pr_tab1:
            try:
                vs = portfolio_vega_stress(open_trades, portfolio_val)
                tr = portfolio_theta_risk(open_trades)

                if not vs.get("error"):
                    st.markdown("**Vega Stress Test** — What happens if volatility spikes?")
                    vc1, vc2, vc3 = st.columns(3)
                    with vc1:
                        st.metric("VIX +5", f"${vs['stress_5pt_loss']:+,.0f}",
                                  help="Estimated loss from a 5-point VIX increase")
                    with vc2:
                        st.metric("VIX +10", f"${vs['stress_10pt_loss']:+,.0f}",
                                  help="Estimated loss from a 10-point VIX spike")
                    with vc3:
                        st.metric("VIX +20", f"${vs['stress_20pt_loss']:+,.0f}",
                                  help="Estimated loss from a 20-point VIX spike (Volmageddon-scale)")

                    if vs.get("stress_10pt_pct") is not None:
                        if vs["passes_5pct_test"]:
                            st.success(f"VIX +10 = {vs['stress_10pt_pct']:+.1f}% of portfolio. Within 5% limit.")
                        else:
                            st.error(f"VIX +10 = {vs['stress_10pt_pct']:+.1f}% of portfolio. "
                                     f"EXCEEDS 5% limit — reduce positions or add hedges.")

                if not tr.get("error"):
                    st.markdown("**Portfolio Greeks**")
                    gc1, gc2, gc3, gc4 = st.columns(4)
                    with gc1:
                        st.metric("Daily Theta", f"${tr['portfolio_theta_daily']:+.2f}",
                                  help="Daily time decay income (positive = seller earns)")
                    with gc2:
                        st.metric("Portfolio Vega", f"{tr['portfolio_vega']:.2f}",
                                  help="Sensitivity to 1% IV change (negative = short vol)")
                    with gc3:
                        if tr.get("theta_vega_ratio"):
                            st.metric("Theta/Vega", f"{tr['theta_vega_ratio']:.1f} days",
                                      help="Days of theta to offset a 1-point IV rise")
                    with gc4:
                        if tr.get("breakeven_daily_move"):
                            st.metric("Breakeven Move", f"${tr['breakeven_daily_move']:.2f}",
                                      help="Daily stock move that wipes out one day of theta")

            except Exception as e:
                st.warning(f"Could not compute portfolio Greeks: {e}")

        with pr_tab2:
            try:
                stress = historical_stress_test(open_trades, portfolio_val)
                if not isinstance(stress, dict) or stress.get("error"):
                    st.warning(f"Stress test: {stress.get('error', 'failed')}")
                else:
                    for name, s in stress.items():
                        if not isinstance(s, dict) or "combined_loss" not in s:
                            continue
                        st.markdown(f"**{name}** — {s['description']}")
                        sc1, sc2, sc3 = st.columns(3)
                        with sc1:
                            st.metric("SPY Move", f"{s['spy_drop_pct']:+.0f}%")
                        with sc2:
                            st.metric("VIX Level", f"{s['vix_level']} (+{s['vix_change']})")
                        with sc3:
                            st.metric("Est. Loss", f"${s['combined_loss']:+,.0f}")

                        if s.get("loss_pct") is not None:
                            if s["surviving"]:
                                st.info(f"Portfolio impact: {s['loss_pct']:+.1f}% — survivable")
                            else:
                                st.error(f"Portfolio impact: {s['loss_pct']:+.1f}% — CRITICAL (>25% loss)")
                        st.markdown("---")

            except Exception as e:
                st.warning(f"Stress test failed: {e}")

        with pr_tab3:
            if len(port_tickers) >= 2:
                try:
                    with st.spinner("Computing correlations..."):
                        cc = crisis_correlation_analysis(port_tickers)

                    if cc.get("error"):
                        st.warning(f"Correlation analysis: {cc['error']}")
                    else:
                        cc1, cc2, cc3 = st.columns(3)
                        with cc1:
                            st.metric("Avg Normal Corr", f"{cc['avg_normal_corr']:.3f}",
                                      help="Average pairwise correlation in normal markets")
                        with cc2:
                            if cc.get("avg_crisis_corr") is not None:
                                st.metric("Avg Crisis Corr", f"{cc['avg_crisis_corr']:.3f}",
                                          help="Correlation on days SPY drops >1%")
                        with cc3:
                            st.metric("Effective Bets", f"{cc['n_eff_normal']:.1f} / {cc['n_available']}",
                                      help="How many truly independent positions you have")

                        if cc.get("diversification_illusion") and cc["diversification_illusion"] > 3:
                            st.warning(
                                f"Diversification illusion: {cc['diversification_illusion']:.0f}x — "
                                f"you think you have {cc['n_available']} bets but really have "
                                f"{cc['n_eff_normal']:.1f}. In a crisis, it drops to "
                                f"{cc.get('n_eff_crisis', '?')}."
                            )

                        if cc["high_corr_pairs"]:
                            st.markdown("**Highly correlated pairs (|r| > 0.7):**")
                            pair_data = [{"Pair": p["pair"],
                                         "Normal": f"{p['normal_corr']:.3f}",
                                         "Crisis": f"{p['crisis_corr']:.3f}" if p.get("crisis_corr") else "N/A"}
                                        for p in cc["high_corr_pairs"][:8]]
                            st.dataframe(pd.DataFrame(pair_data), use_container_width=True, hide_index=True)

                except Exception as e:
                    st.warning(f"Correlation analysis failed: {e}")
            else:
                st.info("Need 2+ different tickers in open positions for correlation analysis.")


# ============================================================
# TAB: SCORECARD
# ============================================================
with tab_scorecard:
    st.header("Prediction Scorecard")
    st.caption(
        "Every time you load a ticker, the tool logs its signal (GREEN/YELLOW/RED) along with all inputs. "
        "After 20 trading days, it checks what actually happened and scores whether the prediction was correct. "
        "This is the only honest way to know if the tool works."
    )

    # Score any pending predictions
    try:
        pending = get_pending_predictions_count()
        if pending > 0:
            with st.spinner(f"Scoring {pending} pending predictions..."):
                scored = score_pending_predictions()
            if scored > 0:
                st.success(f"Scored {scored} predictions that have matured.")
    except Exception as e:
        st.warning(f"Could not score predictions: {e}")

    # Show scorecard
    scorecard = get_prediction_scorecard()

    if scorecard is None:
        st.info(
            "No scored predictions yet. The tool logs a prediction every time you load a ticker. "
            "After 20 trading days, it automatically checks the outcome. "
            "Come back in a few weeks to see how accurate the signals are."
        )

        # Show pending
        try:
            all_preds = get_all_predictions()
            if not all_preds.empty:
                pending_df = all_preds[all_preds["scored"] == 0]
                st.metric("Predictions Logged (Pending)", len(pending_df))
                if not pending_df.empty:
                    st.dataframe(
                        pending_df[["date", "ticker", "signal", "spot_price", "vrp", "regime"]].head(20),
                        use_container_width=True,
                    )
        except Exception:
            pass
    else:
        # Trade Recommendations summary
        st.subheader("Trade Recommendations")
        rc1, rc2, rc3, rc4 = st.columns(4)
        with rc1:
            st.metric("Tickers Analyzed", scorecard.get("total_signals_generated", scorecard["total_predictions"]),
                      help="Total signals generated across all tickers and days")
        with rc2:
            st.metric("Trades Recommended", scorecard.get("total_recommended", "—"),
                      help="GREEN signals = 'sell premium here'")
        with rc3:
            st.metric("Cautioned / Avoided",
                      f"{scorecard.get('total_cautioned', 0)} / {scorecard.get('total_avoided', 0)}",
                      help="YELLOW = proceed with caution, RED = don't sell")
        with rc4:
            rec_rate = scorecard.get("recommendation_rate", 0)
            st.metric("Recommendation Rate", f"{rec_rate:.0f}%",
                      help="% of analyzed tickers that got a GREEN signal. "
                           "Lower = more selective. 30-50% is healthy.")

        # Overall accuracy
        st.subheader("Accuracy (Scored Predictions)")
        oc1, oc2, oc3, oc4 = st.columns(4)
        with oc1:
            st.metric("Total Scored", scorecard["total_predictions"])
        with oc2:
            st.metric("Seller Won", scorecard["total_correct"])
        with oc3:
            acc = scorecard["overall_accuracy"]
            st.metric("Accuracy", f"{acc:.1f}%",
                      help="% of times the actual move was smaller than the expected move (IV-implied). "
                           ">60% = tool has edge. >70% = strong. <50% = broken.")
        with oc4:
            baseline = scorecard.get("baseline_accuracy", acc)
            st.metric("Baseline (Always Sell)", f"{baseline:.1f}%",
                      help="Win rate if you ignored signals and always sold. "
                           "The model adds value only if GREEN > baseline > RED.")

        if acc >= 65:
            st.success(f"Overall accuracy {acc:.1f}% — signals have predictive value.")
        elif acc >= 50:
            st.info(f"Accuracy {acc:.1f}% — slightly better than random. Need more data.")
        else:
            st.error(f"Accuracy {acc:.1f}% — below 50%. Do NOT rely on these signals.")

        # --- P&L Summary (the REAL measure) ---
        pnl_summary = scorecard.get("pnl_summary")
        if pnl_summary:
            st.subheader("P&L Analysis — Does Winning Actually Make Money?")
            st.caption(
                "Win rate can lie ($1 wins / $10 losses = 85% win rate but negative expected value). "
                "P&L shows the actual dollar impact. Negative skewness = rare big losses."
            )
            p1, p2, p3, p4 = st.columns(4)
            with p1:
                avg = pnl_summary["avg_pnl_pct"]
                st.metric("Avg P&L per Trade", f"{avg:+.2f}%",
                          help="Average profit/loss per prediction as % of stock price")
            with p2:
                st.metric("Win/Loss Ratio",
                          f"{pnl_summary['win_loss_ratio']:.2f}x" if pnl_summary.get("win_loss_ratio") else "N/A",
                          help="Average win size / average loss size. >1 = wins are bigger than losses.")
            with p3:
                st.metric("Skewness", f"{pnl_summary['skewness']:.2f}",
                          help="Negative = fat left tail (rare big losses). "
                               "Short premium typically shows -2 to -3. Closer to 0 is better.")
            with p4:
                st.metric("Worst Single Trade", f"{pnl_summary['worst_pnl_pct']:+.2f}%",
                          help="Worst single prediction P&L. This is your tail risk.")

            # The critical test
            if avg > 0 and pnl_summary["skewness"] > -2:
                st.success(f"Positive avg P&L ({avg:+.2f}%) with manageable skew ({pnl_summary['skewness']:.1f}). Strategy is working.")
            elif avg > 0:
                st.warning(f"Positive avg P&L ({avg:+.2f}%) but high negative skew ({pnl_summary['skewness']:.1f}). "
                           f"Wins are real but tail risk is significant.")
            else:
                st.error(f"NEGATIVE avg P&L ({avg:+.2f}%). Despite a {acc:.0f}% win rate, "
                         f"losses are larger than wins. The strategy is losing money.")

        # --- Realized VRP Analysis (the PRIMARY edge metric) ---
        rvrp_summary = scorecard.get("rvrp_summary")
        if rvrp_summary:
            st.subheader("Realized VRP — Do We Have Real Edge?")
            st.caption(
                "Realized VRP = (IV at entry - Realized Vol) / IV at entry. "
                "Measures whether we sell IV that proves overpriced. "
                "Positive = real edge. Lower variance than P&L — "
                "the most reliable signal of profitability (Sinclair & Mack, 2024)."
            )
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                avg_rvrp = rvrp_summary["avg_rvrp"]
                st.metric("Avg Realized VRP", f"{avg_rvrp:.1%}",
                          help="(IV_entry - RV_holding) / IV_entry. Positive = sold overpriced vol.")
            with c2:
                st.metric("Median Realized VRP", f"{rvrp_summary['median_rvrp']:.1%}")
            with c3:
                st.metric("% Positive", f"{rvrp_summary['pct_positive_rvrp']:.0f}%",
                          help="Percentage of trades where IV exceeded realized vol. "
                               "Sinclair benchmark: 82% for SPY.")
            with c4:
                st.metric("Observations", f"{rvrp_summary['count']}")

            if avg_rvrp > 0.02:
                st.success(f"Strong positive Realized VRP ({avg_rvrp:.1%}). "
                           "You are consistently selling overpriced volatility.")
            elif avg_rvrp > 0:
                st.info(f"Positive Realized VRP ({avg_rvrp:.1%}). Edge exists but thin. "
                        "Monitor for decay.")
            else:
                st.error(f"Negative Realized VRP ({avg_rvrp:.1%}). "
                         "You are selling UNDERPRICED volatility. Reassess strategy.")

            # Realized VRP by signal type
            rvrp_by_sig = scorecard.get("rvrp_by_signal", {})
            if rvrp_by_sig:
                st.markdown("**Realized VRP by Signal Type**")
                sig_cols = st.columns(len(rvrp_by_sig))
                for i, (sig, data) in enumerate(rvrp_by_sig.items()):
                    color_map = {"GREEN": "green", "YELLOW": "orange", "RED": "red"}
                    with sig_cols[i]:
                        st.metric(
                            f":{color_map.get(sig, 'gray')}[{sig}] Avg RVRP",
                            f"{data['avg_rvrp']:.1%}",
                            help=f"{data['pct_positive']:.0f}% positive, n={data['count']}"
                        )
                # Check monotonic ordering (H03)
                green_rvrp = rvrp_by_sig.get("GREEN", {}).get("avg_rvrp")
                red_rvrp = rvrp_by_sig.get("RED", {}).get("avg_rvrp")
                if green_rvrp is not None and red_rvrp is not None:
                    spread = green_rvrp - red_rvrp
                    if spread > 0.015:
                        st.success(f"Signal discrimination working: GREEN exceeds RED by {spread:.1%}.")
                    elif spread > 0:
                        st.info(f"Weak signal discrimination: GREEN exceeds RED by only {spread:.1%}.")
                    else:
                        st.error("Signal discrimination BROKEN: RED Realized VRP >= GREEN. "
                                 "Traffic light ordering is not monotonic.")

        # --- Tail Risk Metrics (Module 3) ---
        if pnl_summary:
            with st.expander("Tail Risk Metrics — How Bad Can It Get?", expanded=False):
                st.caption(
                    "Risk metrics beyond simple win rate. These measure tail behavior, "
                    "drawdown severity, and asymmetric market exposure."
                )
                try:
                    all_preds_for_risk = get_all_predictions()
                    scored_preds = all_preds_for_risk[all_preds_for_risk["scored"] == 1] if not all_preds_for_risk.empty else pd.DataFrame()
                    if not scored_preds.empty and "pnl_pct" in scored_preds.columns and scored_preds["pnl_pct"].notna().any():
                        risk = run_all_risk_metrics(scored_preds)

                        # CVaR
                        cvar_data = risk.get("cvar", {}).get("overall")
                        if cvar_data:
                            rc1, rc2, rc3 = st.columns(3)
                            with rc1:
                                st.metric("VaR (95%)", f"{cvar_data['var_95']:+.2f}%",
                                          help="Value at Risk: 95% of trades do better than this")
                            with rc2:
                                st.metric("CVaR (95%)", f"{cvar_data['cvar_95']:+.2f}%",
                                          help="Expected loss in the worst 5% of trades")
                            with rc3:
                                tr = cvar_data['tail_risk_ratio']
                                st.metric("Tail Risk Ratio", f"{tr:.1f}x",
                                          help="CVaR / avg premium. >1 = worst trades wipe out avg premium")

                            if tr > 3:
                                st.error(f"Tail risk ratio {tr:.1f}x — worst trades are devastating relative to premiums collected.")
                            elif tr > 1.5:
                                st.warning(f"Tail risk ratio {tr:.1f}x — moderate tail risk. Size positions accordingly.")

                            # CVaR by signal
                            cvar_sigs = {k: v for k, v in risk.get("cvar", {}).items() if k != "overall" and v is not None}
                            if cvar_sigs:
                                st.markdown("**CVaR by Signal:**")
                                cs_cols = st.columns(len(cvar_sigs))
                                for i, (sig, cv) in enumerate(cvar_sigs.items()):
                                    with cs_cols[i]:
                                        st.metric(f"{sig} CVaR", f"{cv['cvar_95']:+.2f}%")

                        # Omega + Sortino + Calmar
                        omega = risk.get("omega")
                        sortino = risk.get("sortino")
                        calmar = risk.get("calmar")

                        ratio_cols = st.columns(4)
                        with ratio_cols[0]:
                            if omega:
                                st.metric("Omega Ratio", f"{omega['omega_breakeven']:.2f}",
                                          help="Sum of gains / sum of losses. >1 = positive expected value")
                        with ratio_cols[1]:
                            if omega:
                                st.metric("Omega (risk-free)", f"{omega['omega_risk_free']:.2f}",
                                          help=f">1 means strategy beats risk-free rate ({omega['rf_threshold_pct']:.2f}% per trade)")
                        with ratio_cols[2]:
                            if sortino and sortino.get("sortino_annualized") is not None:
                                st.metric("Sortino (ann.)", f"{sortino['sortino_annualized']:.2f}",
                                          help="Risk-adjusted return using downside deviation only. >1 = good, >2 = excellent")
                        with ratio_cols[3]:
                            if calmar and calmar.get("calmar_ratio") is not None:
                                st.metric("Calmar Ratio", f"{calmar['calmar_ratio']:.2f}",
                                          help="Annual return / max drawdown. >1 = return exceeds worst drawdown")

                        # Max Drawdown detail
                        dd = risk.get("max_drawdown")
                        if dd and dd["max_drawdown_pct"] != 0:
                            st.markdown(f"**Max Drawdown:** {dd['max_drawdown_pct']:+.2f}% "
                                        f"({dd['n_trades_in_drawdown']} trades, "
                                        f"{'recovered' if dd.get('recovered') else 'NOT recovered'})")

                        # Conditional Beta
                        cb = risk.get("conditional_beta")
                        if cb and not cb.get("error") and cb.get("up_beta") is not None:
                            st.markdown("**Market Exposure Asymmetry:**")
                            b1, b2, b3 = st.columns(3)
                            with b1:
                                st.metric("Up-Beta", f"{cb['up_beta']:.3f}",
                                          help="Sensitivity when SPY goes up. Low = limited upside capture")
                            with b2:
                                st.metric("Down-Beta", f"{cb['down_beta']:.3f}",
                                          help="Sensitivity when SPY goes down. High = large losses in selloffs")
                            with b3:
                                if cb.get("asymmetry_ratio") is not None:
                                    st.metric("Asymmetry", f"{cb['asymmetry_ratio']:.1f}x",
                                              help="Down-beta / up-beta. >1 = lose more in drops than gain in rallies (typical for short premium)")

                    else:
                        st.info("Not enough scored predictions with P&L data for risk metrics.")
                except Exception as e:
                    st.warning(f"Could not compute risk metrics: {e}")

        # --- Signal Validation (Module 5) ---
        if pnl_summary:
            with st.expander("Signal Validation — Are the Signals Real?", expanded=False):
                st.caption(
                    "Statistical tests on whether each signal component (VRP, IV rank, regime, skew) "
                    "actually predicts P&L, or is just noise."
                )
                try:
                    all_preds_for_sig = get_all_predictions()
                    scored_for_sig = all_preds_for_sig[all_preds_for_sig["scored"] == 1] if not all_preds_for_sig.empty else pd.DataFrame()
                    if not scored_for_sig.empty and "pnl_pct" in scored_for_sig.columns and scored_for_sig["pnl_pct"].notna().sum() >= 30:
                        sig_val = run_all_signal_validation(scored_for_sig)

                        # 5A: Fama-MacBeth coefficients
                        fm = sig_val.get("fama_macbeth", {})
                        if not fm.get("error") and fm.get("coefficients"):
                            st.markdown("**Signal Predictive Power** (pooled OLS with Newey-West SE)")
                            st.caption(f"R² = {fm['r_squared']:.4f} | n = {fm['n_obs']}")
                            coeff_rows = []
                            for name, c in fm["coefficients"].items():
                                if name == "intercept":
                                    continue
                                coeff_rows.append({
                                    "Signal": name,
                                    "Beta": f"{c['beta']:.4f}",
                                    "t-stat": f"{c['t_stat']:.2f}",
                                    "p-value": f"{c['p_value']:.4f}",
                                    "Significant": "Yes " + c["stars"] if c["significant"] else "No",
                                })
                            st.dataframe(pd.DataFrame(coeff_rows), use_container_width=True, hide_index=True)

                            vrp_c = fm["coefficients"].get("vrp")
                            if vrp_c and vrp_c["significant"] and vrp_c["beta"] > 0:
                                st.success("VRP has significant positive predictive power — core thesis holds.")
                            elif vrp_c and not vrp_c["significant"]:
                                st.error(f"VRP is NOT significant (p={vrp_c['p_value']:.3f}). "
                                         f"Core edge thesis is weak with current data.")
                        elif fm.get("error"):
                            st.info(f"Signal regression: {fm['error']}")

                        # 5B: VIF
                        mc = sig_val.get("multicollinearity", {})
                        if not mc.get("error") and mc.get("vif"):
                            st.markdown("**Multicollinearity (VIF)**")
                            vif_rows = [{"Signal": f, "VIF": f"{v['vif']:.2f}", "Status": v["concern"].upper()}
                                        for f, v in mc["vif"].items()]
                            st.dataframe(pd.DataFrame(vif_rows), use_container_width=True, hide_index=True)
                            severe = [f for f, v in mc["vif"].items() if v["concern"] == "severe"]
                            if severe:
                                st.warning(f"Severe multicollinearity: {', '.join(severe)}. "
                                           f"These signals are redundant — consider dropping one.")

                        # 5C: Regime filter
                        rf = sig_val.get("regime_filter", {})
                        if not rf.get("error"):
                            st.markdown("**Regime Filter Test**")
                            rc1, rc2, rc3 = st.columns(3)
                            a = rf["strategy_a"]
                            b = rf["strategy_b"]
                            with rc1:
                                st.metric("Filtered GREEN", f"{a['avg_pnl_pct']:+.3f}%" if a["avg_pnl_pct"] is not None else "N/A",
                                          help=f"{a['n_trades']} trades")
                            with rc2:
                                st.metric("All GREEN", f"{b['avg_pnl_pct']:+.3f}%" if b["avg_pnl_pct"] is not None else "N/A",
                                          help=f"{b['n_trades']} trades")
                            with rc3:
                                st.metric("Random Skip", f"{rf['strategy_c']['avg_pnl_pct']:+.3f}%",
                                          help=f"Average of 100 random subsamples")

                            if rf.get("regime_adds_value") is True:
                                st.success("Regime filter adds significant value over random skipping.")
                            elif rf.get("regime_adds_value") is False:
                                st.warning("Regime filter does NOT beat random skipping — "
                                           "it may just be reducing sample size without adding information.")

                        # 5D: Deflated Sharpe
                        er = sig_val.get("exit_rule", {})
                        if not er.get("error"):
                            st.markdown("**Deflated Sharpe Ratio** (multiple-testing correction)")
                            dc1, dc2 = st.columns(2)
                            with dc1:
                                st.metric("Observed Sharpe", f"{er['observed_sharpe']:.4f}")
                            with dc2:
                                st.metric("Expected Max (null)", f"{er['expected_max_sharpe_null']:.4f}",
                                          help=f"Expected best Sharpe from {er['n_trials_assumed']} random trials")
                            if er["passes_dsr"]:
                                st.success("Passes Deflated Sharpe test — performance likely genuine.")
                            else:
                                st.warning("Fails Deflated Sharpe — performance may be from overfitting "
                                           "exit rules across multiple parameter choices.")

                    else:
                        st.info("Need 30+ scored predictions with P&L data for signal validation.")
                except Exception as e:
                    st.warning(f"Signal validation failed: {e}")

        # --- Signal Separation (the most important test) ---
        st.subheader("Signal Separation — Does GREEN Beat RED?")
        st.caption("This is THE test. If GREEN doesn't beat RED, the signals are useless.")

        by_signal = scorecard.get("by_signal", {})
        if by_signal:
            sig_cols = st.columns(len(by_signal))
            for i, (sig, stats) in enumerate(by_signal.items()):
                with sig_cols[i]:
                    st.markdown(f"**{sig}** ({stats['count']} predictions)")
                    st.metric("Accuracy", f"{stats['accuracy']:.1f}%")
                    if stats.get("avg_pnl_pct") is not None:
                        st.metric("Avg P&L", f"{stats['avg_pnl_pct']:+.2f}%",
                                  help="Average P&L per prediction as % of stock price")
                        st.metric("Total P&L", f"{stats['total_pnl_pct']:+.2f}%")
                    st.metric("Avg Stock Return", f"{stats['avg_return']:+.1f}%")
                    if stats.get("avg_vrp") is not None:
                        st.metric("Avg VRP at Signal", f"{stats['avg_vrp']:+.1f}")
                    if stats.get("skewness") is not None:
                        st.metric("P&L Skew", f"{stats['skewness']:.2f}",
                                  help="Negative = fat left tail (big losses)")
                    st.metric("Worst Return", f"{stats['worst_return']:+.1f}%")

            # Signal separation test — P&L based (more reliable than accuracy)
            green_pnl = by_signal.get("GREEN", {}).get("avg_pnl_pct")
            red_pnl = by_signal.get("RED", {}).get("avg_pnl_pct")
            if green_pnl is not None and red_pnl is not None:
                pnl_spread = green_pnl - red_pnl
                if pnl_spread > 0.5:
                    st.success(
                        f"GREEN avg P&L ({green_pnl:+.2f}%) vs RED ({red_pnl:+.2f}%) = "
                        f"**{pnl_spread:+.2f}pp spread**. GREEN makes more money. Signals work."
                    )
                elif pnl_spread > 0:
                    st.info(
                        f"GREEN avg P&L ({green_pnl:+.2f}%) vs RED ({red_pnl:+.2f}%) = "
                        f"**{pnl_spread:+.2f}pp spread**. Slight edge — need more data."
                    )
                else:
                    st.error(
                        f"RED avg P&L ({red_pnl:+.2f}%) beats GREEN ({green_pnl:+.2f}%). "
                        f"Signals are NOT adding value by P&L."
                    )

            green_acc = by_signal.get("GREEN", {}).get("accuracy", 0)
            yellow_acc = by_signal.get("YELLOW", {}).get("accuracy", 0)
            red_acc = by_signal.get("RED", {}).get("accuracy", 0)
            if green_acc > 0 and red_acc > 0:
                spread = green_acc - red_acc
                if spread > 15:
                    st.success(
                        f"GREEN ({green_acc:.0f}%) vs RED ({red_acc:.0f}%) = **{spread:+.0f}pp spread**. "
                        f"Strong signal differentiation. Follow the signals."
                    )
                elif spread > 5:
                    st.info(
                        f"GREEN ({green_acc:.0f}%) vs RED ({red_acc:.0f}%) = **{spread:+.0f}pp spread**. "
                        f"Directionally correct but needs more data for confidence."
                    )
                elif spread > 0:
                    st.warning(
                        f"GREEN ({green_acc:.0f}%) vs RED ({red_acc:.0f}%) = **{spread:+.0f}pp spread**. "
                        f"Barely separating — signals may not be reliable yet."
                    )
                else:
                    st.error(
                        f"RED ({red_acc:.0f}%) outperforms GREEN ({green_acc:.0f}%). "
                        f"Signals are INVERTED — do NOT trade on them."
                    )

        # --- VRP as Predictor ---
        vrp_analysis = scorecard.get("vrp_analysis")
        if vrp_analysis:
            st.subheader("VRP as Predictor — Does Higher VRP = Better Outcomes?")
            st.caption("VRP (IV - RV forecast) is the core edge metric. High VRP should mean sellers win more.")
            v1, v2 = st.columns(2)
            with v1:
                if vrp_analysis.get("high_vrp_accuracy") is not None:
                    st.metric(f"VRP >= 5 ({vrp_analysis['high_vrp_count']} predictions)",
                              f"{vrp_analysis['high_vrp_accuracy']:.1f}%")
                else:
                    st.metric("VRP >= 5", "Not enough data")
            with v2:
                if vrp_analysis.get("low_vrp_accuracy") is not None:
                    st.metric(f"VRP < 5 ({vrp_analysis['low_vrp_count']} predictions)",
                              f"{vrp_analysis['low_vrp_accuracy']:.1f}%")
                else:
                    st.metric("VRP < 5", "Not enough data")

            if (vrp_analysis.get("high_vrp_accuracy") is not None and
                    vrp_analysis.get("low_vrp_accuracy") is not None):
                vrp_spread = vrp_analysis["high_vrp_accuracy"] - vrp_analysis["low_vrp_accuracy"]
                if vrp_spread > 10:
                    st.success(f"High VRP outperforms by {vrp_spread:.0f}pp — VRP is a valid predictor.")
                elif vrp_spread > 0:
                    st.info(f"High VRP slightly better by {vrp_spread:.0f}pp — directionally correct.")
                else:
                    st.warning(f"High VRP underperforms by {abs(vrp_spread):.0f}pp — VRP may not be predictive here.")

        # --- Cumulative P&L Curve ---
        cum_pnl = scorecard.get("cumulative_pnl", [])
        if len(cum_pnl) >= 5:
            st.subheader("Cumulative P&L — Equity Curve")
            st.caption(
                "Running total of estimated P&L (% of stock price) across all scored predictions. "
                "A rising curve = the strategy is making money over time."
            )
            cum_df = pd.DataFrame(cum_pnl)
            fig_cum = go.Figure()
            fig_cum.add_trace(go.Scatter(
                x=cum_df["date"], y=cum_df["cum_pnl_pct"],
                mode="lines", name="Cumulative P&L",
                line=dict(color="green", width=2),
                fill="tozeroy",
                fillcolor="rgba(0,200,0,0.1)",
            ))
            fig_cum.add_hline(y=0, line_dash="dash", line_color="red")
            fig_cum.update_layout(
                yaxis_title="Cumulative P&L (%)", xaxis_title="Date",
                height=350,
            )
            st.plotly_chart(fig_cum, use_container_width=True)

            # Max drawdown
            cum_series = pd.Series([p["cum_pnl_pct"] for p in cum_pnl])
            running_max = cum_series.cummax()
            drawdown = cum_series - running_max
            max_dd = drawdown.min()
            if max_dd < -1:
                st.warning(f"Max drawdown: {max_dd:.2f}pp — watch for sustained losses.")
            elif max_dd < 0:
                st.info(f"Max drawdown: {max_dd:.2f}pp — within normal range.")

        # --- Rolling Accuracy + P&L (is the model improving?) ---
        rolling = scorecard.get("rolling_accuracy", [])
        if len(rolling) >= 5:
            st.subheader("Performance Over Time — Is the Model Improving?")
            st.caption("30-prediction rolling window. Upward trend = model is learning. Flat = stable. Down = degrading.")
            roll_df = pd.DataFrame(rolling)

            # Dual-axis chart: accuracy + rolling P&L
            has_rolling_pnl = "avg_pnl_pct" in roll_df.columns and roll_df["avg_pnl_pct"].notna().any()

            if has_rolling_pnl:
                fig_roll = make_subplots(specs=[[{"secondary_y": True}]])
            else:
                fig_roll = go.Figure()

            acc_trace = go.Scatter(
                x=roll_df["end_date"], y=roll_df["accuracy"],
                mode="lines+markers", name="Rolling Accuracy",
                line=dict(color="blue", width=2),
            )
            if has_rolling_pnl:
                fig_roll.add_trace(acc_trace, secondary_y=False)
            else:
                fig_roll.add_trace(acc_trace)

            if has_rolling_pnl:
                fig_roll.add_trace(go.Scatter(
                    x=roll_df["end_date"], y=roll_df["avg_pnl_pct"],
                    mode="lines", name="Rolling Avg P&L (%)",
                    line=dict(color="orange", width=2, dash="dot"),
                ), secondary_y=True)

            fig_roll.add_hline(y=50, line_dash="dash", line_color="red",
                              annotation_text="Random (50%)")
            fig_roll.add_hline(y=acc, line_dash="dash", line_color="green",
                              annotation_text=f"Overall ({acc:.0f}%)")

            layout_kwargs = dict(
                yaxis_title="Accuracy %", xaxis_title="Date",
                yaxis_range=[0, 100], height=350,
            )
            if has_rolling_pnl:
                fig_roll.update_yaxes(title_text="Accuracy %", secondary_y=False)
                fig_roll.update_yaxes(title_text="Avg P&L %", secondary_y=True)
                fig_roll.update_layout(xaxis_title="Date", height=350)
            else:
                fig_roll.update_layout(**layout_kwargs)
            st.plotly_chart(fig_roll, use_container_width=True)

            # Trend detection
            if len(rolling) >= 10:
                first_half = np.mean([r["accuracy"] for r in rolling[:len(rolling)//2]])
                second_half = np.mean([r["accuracy"] for r in rolling[len(rolling)//2:]])
                trend = second_half - first_half
                if trend > 5:
                    st.success(f"Accuracy trending UP (+{trend:.1f}pp). Model is improving.")
                elif trend < -5:
                    st.warning(f"Accuracy trending DOWN ({trend:+.1f}pp). Model may be degrading.")
                else:
                    st.info(f"Accuracy stable ({trend:+.1f}pp change). Consistent performance.")

        # --- CUSUM Edge Erosion (Module 8A) ---
        if pnl_summary:
            try:
                all_preds_cusum = get_all_predictions()
                scored_cusum = all_preds_cusum[all_preds_cusum["scored"] == 1] if not all_preds_cusum.empty else pd.DataFrame()
                if not scored_cusum.empty and "pnl_pct" in scored_cusum.columns and scored_cusum["pnl_pct"].notna().sum() >= 20:
                    pnl_for_cusum = scored_cusum["pnl_pct"].dropna()
                    dates_for_cusum = scored_cusum.loc[pnl_for_cusum.index, "date"] if "date" in scored_cusum.columns else None
                    cusum = cusum_edge_detection(pnl_for_cusum, dates_for_cusum)

                    if not cusum.get("error") and cusum.get("chart_data"):
                        st.subheader("Edge Erosion Monitor (CUSUM)")
                        st.caption(
                            "CUSUM detects if the strategy's edge is degrading over time. "
                            "Rising line = performance slipping. If it crosses the red threshold, "
                            "the edge may be gone."
                        )

                        cd = pd.DataFrame(cusum["chart_data"])
                        fig_cusum = go.Figure()
                        x_vals = cd["date"] if "date" in cd.columns else cd["idx"]
                        fig_cusum.add_trace(go.Scatter(
                            x=x_vals, y=cd["cusum"],
                            mode="lines", name="CUSUM",
                            line=dict(color="blue", width=2),
                        ))
                        fig_cusum.add_hline(
                            y=cusum["threshold"], line_dash="dash", line_color="red",
                            annotation_text=f"Alert threshold ({cusum['threshold']})",
                        )
                        fig_cusum.update_layout(
                            yaxis_title="CUSUM Value", xaxis_title="Trade #" if "date" not in cd.columns else "Date",
                            height=300,
                        )
                        st.plotly_chart(fig_cusum, use_container_width=True)

                        if cusum["alert"]:
                            st.error(
                                f"CUSUM crossed alert threshold at trade #{cusum['alert_trade_idx']}. "
                                f"Edge may have eroded — investigate before opening new positions."
                            )
                        else:
                            st.success(f"CUSUM at {cusum['current_cusum']:.2f} (threshold {cusum['threshold']:.0f}). "
                                       f"No edge erosion detected.")

                        if cusum.get("ir_trend") is not None:
                            if cusum["ir_trend"] < -0.2:
                                st.warning(f"Information ratio declining: "
                                           f"{cusum['early_ir']:.3f} → {cusum['recent_ir']:.3f}")
            except Exception:
                pass

        # By regime
        by_regime = scorecard.get("by_regime", {})
        if by_regime:
            st.subheader("Accuracy by Regime")
            reg_cols = st.columns(len(by_regime))
            for i, (reg, stats) in enumerate(by_regime.items()):
                with reg_cols[i]:
                    st.markdown(f"**{reg}** ({stats['count']})")
                    st.metric("Accuracy", f"{stats['accuracy']:.1f}%")
                    st.metric("Avg Return", f"{stats['avg_return']:+.1f}%")

        # By ticker
        by_ticker = scorecard.get("by_ticker", {})
        if by_ticker:
            st.subheader("Accuracy by Ticker")
            st.caption("Sorted by prediction count. Tickers with few predictions are unreliable.")
            ticker_df = pd.DataFrame([
                {"Ticker": t, "Count": s["count"],
                 "Accuracy": f"{s['accuracy']:.1f}%",
                 "Avg Return": f"{s['avg_return']:+.1f}%"}
                for t, s in sorted(by_ticker.items(), key=lambda x: x[1]["count"], reverse=True)
            ])
            st.dataframe(ticker_df, use_container_width=True, hide_index=True)

        # Recent predictions detail
        st.subheader("Recent Scored Predictions")
        recent = scorecard.get("recent", [])
        if recent:
            rdf = pd.DataFrame(recent)
            display_cols = ["date", "ticker", "signal", "regime", "spot_price",
                           "vrp", "outcome_return", "pnl_pct", "seller_won"]
            display_cols = [c for c in display_cols if c in rdf.columns]
            rdf_display = rdf[display_cols].copy()
            if "outcome_return" in rdf_display.columns:
                rdf_display["outcome_return"] = rdf_display["outcome_return"].apply(
                    lambda x: f"{x:+.1f}%" if pd.notna(x) else "N/A"
                )
            if "pnl_pct" in rdf_display.columns:
                rdf_display["pnl_pct"] = rdf_display["pnl_pct"].apply(
                    lambda x: f"{x:+.2f}%" if pd.notna(x) else "N/A"
                )
            if "seller_won" in rdf_display.columns:
                rdf_display["seller_won"] = rdf_display["seller_won"].map({1: "Yes", 0: "No"})
            if "vrp" in rdf_display.columns:
                rdf_display["vrp"] = rdf_display["vrp"].apply(
                    lambda x: f"{x:+.1f}" if pd.notna(x) else "N/A"
                )
            st.dataframe(rdf_display, use_container_width=True, hide_index=True)

    # Show all pending predictions
    try:
        all_preds = get_all_predictions()
        if not all_preds.empty:
            pending_df = all_preds[all_preds["scored"] == 0]
            if not pending_df.empty:
                with st.expander(f"Pending Predictions ({len(pending_df)} awaiting outcome)", expanded=False):
                    st.caption("These predictions have been logged but not enough time has passed to score them.")
                    display_cols = ["date", "ticker", "signal", "regime", "spot_price", "vrp", "holding_days"]
                    display_cols = [c for c in display_cols if c in pending_df.columns]
                    st.dataframe(pending_df[display_cols].head(50), use_container_width=True, hide_index=True)
    except Exception:
        pass

    # --- Signal Graveyard & Hypothesis Tracker ---
    try:
        from db import get_graveyard
        graveyard_df = get_graveyard()
        if not graveyard_df.empty:
            with st.expander(f"Signal Graveyard ({len(graveyard_df)} hypotheses)", expanded=False):
                st.caption(
                    "Every hypothesis is pre-registered before testing. The graveyard tracks "
                    "all ideas (pass + fail) for Deflated Sharpe Ratio correction. "
                    "More failed signals = MORE confidence in surviving signals."
                )

                # Color-coded status
                def style_status(val):
                    colors = {
                        "untested": "color: gray",
                        "testing": "color: dodgerblue",
                        "passed": "color: green; font-weight: bold",
                    }
                    for key in colors:
                        if key in str(val).lower():
                            return colors[key]
                    if "failed" in str(val).lower():
                        return "color: red"
                    return ""

                display_cols = ["signal_id", "name", "tier", "status", "layer_reached"]
                if "best_rvrp" in graveyard_df.columns:
                    display_cols.append("best_rvrp")
                if "n_trades" in graveyard_df.columns:
                    display_cols.append("n_trades")
                available = [c for c in display_cols if c in graveyard_df.columns]

                styled = graveyard_df[available].style.applymap(
                    style_status, subset=["status"]
                ) if "status" in available else graveyard_df[available]
                st.dataframe(styled, use_container_width=True, hide_index=True)

                # Summary stats
                total = len(graveyard_df)
                tested = len(graveyard_df[graveyard_df["status"] != "untested"]) if "status" in graveyard_df.columns else 0
                passed = len(graveyard_df[graveyard_df["status"].str.contains("passed", na=False)]) if "status" in graveyard_df.columns else 0
                failed = len(graveyard_df[graveyard_df["status"].str.contains("failed", na=False)]) if "status" in graveyard_df.columns else 0

                g1, g2, g3, g4 = st.columns(4)
                g1.metric("Registered", total)
                g2.metric("Tested", tested)
                g3.metric("Passed", passed)
                g4.metric("Failed", failed, help="Failed signals are GOOD — they prove the gate works "
                          "and improve Deflated Sharpe correction for surviving signals.")
    except Exception:
        pass


# ============================================================
# TAB: BASKET TEST
# ============================================================
with tab_basket:
    st.header("Basket Performance Test")
    st.caption(
        "Run the full evaluation pipeline across a basket of tickers to test whether the strategy works "
        "at scale. Computes one-pass backtest, walk-forward OOS validation, GREEN-only P&L, and risk metrics."
    )

    # Basket selection
    basket_choice = st.selectbox(
        "Select basket",
        ["Quick (5 tickers)", "Core (20 tickers)", "Full (50 tickers)", "Custom"],
        index=0,
        help="Quick: ~2 min, Core: ~8 min, Full: ~20 min",
    )

    if basket_choice == "Custom":
        custom_input = st.text_input(
            "Enter tickers (comma-separated)",
            value="SPY, QQQ, AAPL, MSFT, NVDA, TSLA",
        )
        selected_basket = [t.strip().upper() for t in custom_input.split(",") if t.strip()]
    elif "Quick" in basket_choice:
        selected_basket = QUICK_BASKET
    elif "Full" in basket_choice:
        selected_basket = FULL_BASKET
    else:
        selected_basket = CORE_BASKET

    st.caption(f"**{len(selected_basket)} tickers:** {', '.join(selected_basket[:20])}"
               + (f" ... +{len(selected_basket)-20} more" if len(selected_basket) > 20 else ""))

    # Run button
    if st.button("Run Basket Test", type="primary"):
        import yfinance as yf
        from basket_test import save_results, save_to_supabase

        progress = st.progress(0, text="Starting...")
        ticker_results = {}
        status_area = st.empty()

        for i, ticker in enumerate(selected_basket):
            progress.progress(
                (i) / len(selected_basket),
                text=f"Testing {ticker} ({i+1}/{len(selected_basket)})..."
            )
            try:
                hist = yf.download(ticker, period="6y", progress=False)
                if isinstance(hist.columns, pd.MultiIndex):
                    hist.columns = hist.columns.get_level_values(0)

                if hist.empty or len(hist) < 252:
                    ticker_results[ticker] = {"error": f"Insufficient data ({len(hist)} rows)"}
                    continue

                result = test_ticker(ticker, hist)
                ticker_results[ticker] = result

            except Exception as e:
                ticker_results[ticker] = {"error": str(e)}

        progress.progress(1.0, text="Complete!")

        # Build full results
        from datetime import datetime as _dt
        results = {
            "run_date": _dt.now().strftime("%Y-%m-%d %H:%M"),
            "n_tickers": len(selected_basket),
            "period": "6y",
            "holding_period": 20,
            "tickers": ticker_results,
        }
        results["aggregate"] = _compute_aggregate(ticker_results)

        # Save
        try:
            save_results(results)
            save_to_supabase(results)
        except Exception:
            pass

        # Store in session state for display
        st.session_state["basket_results"] = results

    # Display results
    results = st.session_state.get("basket_results")
    if results:
        agg = results.get("aggregate", {})
        n_ok = agg.get("n_successful", 0)
        n_oos = agg.get("n_with_oos", 0)

        st.subheader(f"Results — {results['run_date']}")
        st.caption(f"{results['n_tickers']} tickers requested, {n_ok} successful, {n_oos} with walk-forward")

        # ── Aggregate metrics ──
        op = agg.get("one_pass", {})
        gr = agg.get("green_only", {})
        wf = agg.get("walk_forward", {})

        if op:
            st.markdown("### Overall (One-Pass Backtest)")
            a1, a2, a3, a4 = st.columns(4)
            with a1:
                st.metric("Avg Win Rate", f"{op['avg_win_rate']:.1f}%")
            with a2:
                st.metric("Avg P&L / Trade", f"{op['avg_pnl']:+.4f}%")
            with a3:
                st.metric("Avg Sharpe", f"{op['avg_sharpe']:.3f}")
            with a4:
                st.metric("% Tickers Profitable", f"{op['pct_profitable']:.0f}%")

        if gr:
            st.markdown("### GREEN-Only (What You'd Actually Trade)")
            g1, g2, g3 = st.columns(3)
            with g1:
                st.metric("Avg Win Rate", f"{gr['avg_win_rate']:.1f}%")
            with g2:
                st.metric("Avg P&L / Trade", f"{gr['avg_pnl']:+.4f}%")
            with g3:
                st.metric("% Tickers Profitable", f"{gr['pct_profitable']:.0f}%")

            if op and gr["avg_pnl"] > op["avg_pnl"]:
                st.success(f"GREEN signals outperform overall by "
                           f"{gr['avg_pnl'] - op['avg_pnl']:+.4f}pp — signals add value.")
            elif op:
                st.warning("GREEN signals don't outperform overall — signals may need tuning.")

        if wf:
            st.markdown("### Walk-Forward (Out-of-Sample)")
            w1, w2, w3, w4 = st.columns(4)
            with w1:
                st.metric("OOS Win Rate", f"{wf['avg_win_rate']:.1f}%")
            with w2:
                st.metric("OOS Avg P&L", f"{wf['avg_pnl']:+.4f}%")
            with w3:
                st.metric("% OOS Profitable", f"{wf['pct_profitable_oos']:.0f}%")
            with w4:
                st.metric("Avg Overfit Ratio", f"{wf['avg_overfit_ratio']:.2f}x",
                          help=">2x means in-sample results are misleading")

            if wf["avg_pnl"] > 0 and wf["avg_overfit_ratio"] < 2:
                st.success("Strategy holds up out-of-sample with low overfit. Robust.")
            elif wf["avg_pnl"] > 0:
                st.info("Positive OOS but elevated overfit ratio — real results may be weaker.")
            else:
                st.error("Negative OOS P&L — strategy does not work on unseen data.")

        surv = agg.get("survivorship_adjusted")
        if surv:
            st.markdown("### Survivorship Bias Adjustment")
            s1, s2, s3 = st.columns(3)
            with s1:
                st.metric("Raw Annual Return", f"{surv['raw_annual_return_pct']:+.2f}%")
            with s2:
                st.metric("Adjusted (-150bps/yr)", f"{surv['adjusted_annual_return_pct']:+.2f}%")
            with s3:
                st.metric("Still Profitable?", "YES" if surv["still_profitable"] else "NO")

        # ── Per-ticker table ──
        st.markdown("### Per-Ticker Results")
        table_rows = []
        for ticker, r in sorted(results["tickers"].items()):
            if isinstance(r, dict) and r.get("error"):
                table_rows.append({
                    "Ticker": ticker, "Win%": "ERR", "Avg P&L": str(r["error"])[:30],
                    "Sharpe": "", "GREEN P&L": "", "OOS P&L": "", "Overfit": "",
                })
                continue

            op_t = r.get("one_pass", {})
            gr_t = r.get("green_only", {})
            wf_t = r.get("walk_forward", {})

            table_rows.append({
                "Ticker": ticker,
                "Win%": f"{op_t['overall_win_rate']:.0f}%" if not op_t.get("error") else "N/A",
                "Avg P&L": f"{op_t['overall_avg_pnl']:+.3f}%" if not op_t.get("error") else "N/A",
                "Sharpe": f"{op_t['overall_sharpe']:.3f}" if not op_t.get("error") else "N/A",
                "GREEN P&L": f"{gr_t['avg_pnl']:+.3f}%" if gr_t and not gr_t.get("error") else "N/A",
                "OOS P&L": f"{wf_t['oos_avg_pnl']:+.3f}%" if not wf_t.get("error") else "N/A",
                "Overfit": f"{wf_t['overfit_ratio']:.2f}x" if not wf_t.get("error") else "N/A",
            })

        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

        # ── Charts ──
        valid_tickers = {t: r for t, r in results["tickers"].items()
                         if isinstance(r, dict) and not r.get("error")
                         and not r.get("one_pass", {}).get("error")}

        if valid_tickers:
            # P&L comparison chart
            st.markdown("### P&L Comparison")
            chart_data = []
            for t, r in sorted(valid_tickers.items()):
                op_t = r["one_pass"]
                gr_t = r.get("green_only", {})
                chart_data.append({
                    "Ticker": t,
                    "Overall": op_t["overall_avg_pnl"],
                    "GREEN": gr_t.get("avg_pnl", 0) if gr_t else 0,
                })

            cdf = pd.DataFrame(chart_data)
            fig_pnl = go.Figure()
            fig_pnl.add_trace(go.Bar(x=cdf["Ticker"], y=cdf["Overall"], name="Overall",
                                     marker_color="steelblue"))
            fig_pnl.add_trace(go.Bar(x=cdf["Ticker"], y=cdf["GREEN"], name="GREEN Only",
                                     marker_color="green"))
            fig_pnl.add_hline(y=0, line_dash="dash", line_color="red")
            fig_pnl.update_layout(barmode="group", yaxis_title="Avg P&L %",
                                  height=400, margin=dict(t=30))
            st.plotly_chart(fig_pnl, use_container_width=True)

            # OOS vs IS comparison
            oos_tickers = {t: r for t, r in valid_tickers.items()
                           if not r.get("walk_forward", {}).get("error")}
            if oos_tickers:
                st.markdown("### In-Sample vs Out-of-Sample")
                oos_data = []
                for t, r in sorted(oos_tickers.items()):
                    wf_t = r["walk_forward"]
                    op_t = r["one_pass"]
                    oos_data.append({
                        "Ticker": t,
                        "In-Sample": op_t["overall_avg_pnl"],
                        "Out-of-Sample": wf_t["oos_avg_pnl"],
                    })

                odf = pd.DataFrame(oos_data)
                fig_oos = go.Figure()
                fig_oos.add_trace(go.Bar(x=odf["Ticker"], y=odf["In-Sample"],
                                         name="In-Sample", marker_color="lightblue"))
                fig_oos.add_trace(go.Bar(x=odf["Ticker"], y=odf["Out-of-Sample"],
                                         name="Out-of-Sample", marker_color="navy"))
                fig_oos.add_hline(y=0, line_dash="dash", line_color="red")
                fig_oos.update_layout(barmode="group", yaxis_title="Avg P&L %",
                                      height=400, margin=dict(t=30))
                st.plotly_chart(fig_oos, use_container_width=True)

    # ── Historical runs ──
    history = load_all_results()
    if history:
        with st.expander(f"Historical Runs ({len(history)} saved)", expanded=False):
            hist_rows = []
            for h in history:
                ha = h.get("aggregate", {})
                hop = ha.get("one_pass", {})
                hgr = ha.get("green_only", {})
                hwf = ha.get("walk_forward", {})
                hist_rows.append({
                    "Date": h.get("run_date", "?"),
                    "Tickers": h.get("n_tickers", "?"),
                    "Avg P&L": f"{hop.get('avg_pnl', 0):+.4f}%" if hop else "N/A",
                    "GREEN P&L": f"{hgr.get('avg_pnl', 0):+.4f}%" if hgr else "N/A",
                    "OOS P&L": f"{hwf.get('avg_pnl', 0):+.4f}%" if hwf else "N/A",
                    "Overfit": f"{hwf.get('avg_overfit_ratio', 0):.2f}x" if hwf else "N/A",
                })
            st.dataframe(pd.DataFrame(hist_rows), use_container_width=True, hide_index=True)

            # Trend chart if enough history
            if len(history) >= 2:
                trend_data = []
                for h in history:
                    ha = h.get("aggregate", {})
                    hop = ha.get("one_pass", {})
                    hgr = ha.get("green_only", {})
                    if hop:
                        trend_data.append({
                            "date": h.get("run_date", ""),
                            "overall": hop.get("avg_pnl", 0),
                            "green": hgr.get("avg_pnl", 0) if hgr else 0,
                        })
                if trend_data:
                    tdf = pd.DataFrame(trend_data)
                    fig_trend = go.Figure()
                    fig_trend.add_trace(go.Scatter(
                        x=tdf["date"], y=tdf["overall"],
                        mode="lines+markers", name="Overall P&L",
                    ))
                    fig_trend.add_trace(go.Scatter(
                        x=tdf["date"], y=tdf["green"],
                        mode="lines+markers", name="GREEN P&L",
                    ))
                    fig_trend.add_hline(y=0, line_dash="dash", line_color="red")
                    fig_trend.update_layout(
                        title="Basket Performance Over Time",
                        yaxis_title="Avg P&L %", height=350,
                    )
                    st.plotly_chart(fig_trend, use_container_width=True)


# ============================================================
# FOOTER
# ============================================================
st.divider()
st.caption(
    "Based on concepts from 'Retail Options Trading' by Sinclair & Mack (2024). "
    "This tool does NOT auto-trade. Not financial advice. "
    "Hover over any metric for an explanation."
)

# Diagnostics (temporary — remove once working)
with st.expander("Debug Info", expanded=False):
    st.text(f"App version: {_APP_VERSION}")
    st.text(f"Proxy URL: {yf_proxy.PROXY_URL}")
    try:
        import requests as _req
        r = _req.get(f"{yf_proxy.PROXY_URL}/health", timeout=5)
        st.text(f"Proxy health: {r.status_code} — {r.text[:100]}")
    except Exception as _e:
        st.text(f"Proxy health: FAILED — {_e}")
    try:
        test_exps = yf_proxy.get_expirations("AAPL")
        st.text(f"AAPL expirations: {len(test_exps)} — {test_exps[:3]}")
    except Exception as _e:
        st.text(f"AAPL expirations: FAILED — {_e}")
