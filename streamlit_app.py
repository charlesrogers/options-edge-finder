import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import time
import plotly.graph_objects as go
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
)
from db import add_trade, close_trade, get_open_trades, get_all_trades, delete_trade
from db import record_iv, get_iv_history, get_real_iv_rank, using_supabase

st.set_page_config(
    page_title="Options Edge Finder",
    page_icon="$",
    layout="wide",
)

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

tab_dashboard, tab_analyzer, tab_positions = st.tabs([
    "Dashboard",
    "Trade Analyzer",
    "My Positions",
])

# Ticker input at the top (compact)
ticker_input = st.text_input(
    "Tickers (comma-separated)",
    value="AAPL",
    label_visibility="collapsed",
    placeholder="Enter tickers: AAPL, MSFT, GOOGL",
)
tickers = [t.strip().upper() for t in ticker_input.split(",") if t.strip()]


# ============================================================
# DATA LOADERS
# ============================================================
def _yf_retry(func, retries=3, delay=2):
    """Retry a yfinance call with backoff to handle rate limits."""
    for attempt in range(retries):
        try:
            return func()
        except Exception as e:
            if attempt < retries - 1 and ("RateLimit" in type(e).__name__ or "429" in str(e)):
                time.sleep(delay * (attempt + 1))
            else:
                raise
    return None


@st.cache_data(ttl=600)
def load_stock_data(ticker, period="1y"):
    stock = yf.Ticker(ticker)
    hist = _yf_retry(lambda: stock.history(period=period))
    if hist is None or hist.empty:
        return pd.DataFrame(), {}
    # info call is separate and often rate-limited — make it optional
    time.sleep(1)  # delay to avoid back-to-back rate limits
    try:
        info = _yf_retry(lambda: stock.info, retries=2, delay=5)
        if info is None:
            info = {}
    except Exception:
        info = {}
    return hist, info


@st.cache_data(ttl=600)
def load_expirations(ticker):
    """Get all available expiration dates for a ticker."""
    try:
        stock = yf.Ticker(ticker)
        expirations = _yf_retry(lambda: stock.options, retries=2)
        return list(expirations) if expirations else []
    except Exception:
        return []


@st.cache_resource(ttl=300)
def load_chain(ticker, expiration):
    """Load a single expiration's option chain (lazy — only when needed)."""
    stock = yf.Ticker(ticker)
    try:
        return _yf_retry(lambda: stock.option_chain(expiration), retries=2)
    except Exception:
        return None


def load_options_data(ticker):
    """Load first 2 expirations for dashboard/term structure. Returns chains dict + all expiration list."""
    expirations = load_expirations(ticker)
    if not expirations:
        return None, []
    chains = {}
    for exp in expirations[:2]:  # only first 2 to reduce API calls
        time.sleep(0.5)  # small delay to avoid rate limits
        chain = load_chain(ticker, exp)
        if chain is not None:
            chains[exp] = chain
    return chains, expirations


@st.cache_data(ttl=900)
def load_vix_data():
    vix_hist = pd.DataFrame()
    for period in ["1y", "6mo", "3mo"]:
        try:
            df = yf.download("^VIX", period=period, progress=False)
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                vix_hist = df
                break
        except Exception:
            continue
    if vix_hist.empty:
        for period in ["6mo", "3mo", "1mo"]:
            try:
                vix_hist = yf.Ticker("^VIX").history(period=period)
                if not vix_hist.empty:
                    break
            except Exception:
                continue

    vix3m_hist = None
    try:
        df3m = yf.download("^VIX3M", period="1y", progress=False)
        if not df3m.empty:
            if isinstance(df3m.columns, pd.MultiIndex):
                df3m.columns = df3m.columns.get_level_values(0)
            vix3m_hist = df3m
    except Exception:
        pass
    if vix3m_hist is None:
        try:
            vix3m_hist = yf.Ticker("^VIX3M").history(period="6mo")
        except Exception:
            pass
    return vix_hist, vix3m_hist


def compute_analytics(ticker):
    """Load and compute all analytics for a ticker. Returns a dict."""
    hist, info = load_stock_data(ticker)
    chains, expirations = load_options_data(ticker)
    if hist.empty:
        return None

    current_price = hist["Close"].iloc[-1]
    company_name = info.get("shortName", ticker)
    rv_10 = calc_realized_vol(hist, window=10)
    rv_20 = calc_realized_vol(hist, window=20)
    rv_30 = calc_realized_vol(hist, window=30)

    current_iv = None
    if chains and expirations:
        first_exp = expirations[0]
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
        forecast_method = "GARCH(1,1)"
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

    vrp = (current_iv - rv_forecast) if current_iv else None
    signal, signal_color, signal_reason = calc_vrp_signal(vrp, iv_rank, term_label)

    # Record today's IV snapshot (builds history over time)
    if current_iv is not None:
        try:
            first_exp = expirations[0] if expirations else ""
            record_iv(ticker, current_iv, current_price, first_exp, rv_20, term_label)
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

    return {
        "hist": hist, "info": info, "chains": chains, "expirations": expirations,
        "current_price": current_price, "company_name": company_name,
        "rv_10": rv_10, "rv_20": rv_20, "rv_30": rv_30, "yz_20": yz_20,
        "garch_vol": garch_vol, "garch_info": garch_info,
        "rv_forecast": rv_forecast, "forecast_method": forecast_method,
        "current_iv": current_iv, "iv_rank": iv_rank, "iv_pctl": iv_pctl,
        "iv_rank_source": iv_rank_source, "iv_history_days": iv_history_days,
        "term_struct": term_struct, "term_label": term_label,
        "vrp": vrp, "signal": signal, "signal_color": signal_color, "signal_reason": signal_reason,
        "earnings_date": earnings_date, "earnings_days": earnings_days,
        "empirical": empirical,
    }


# ============================================================
# TAB: DASHBOARD
# ============================================================
with tab_dashboard:
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

        # --- Signal banner ---
        if signal == "GREEN":
            st.success(f"**SELL OPTIONS** — {signal_reason}")
        elif signal == "YELLOW":
            st.warning(f"**MARGINAL** — {signal_reason}")
        else:
            st.error(f"**DON'T SELL** — {signal_reason}")

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
                st.caption(
                    f"GARCH persistence: {garch_info['persistence']:.3f} "
                    f"({'High — vol shocks last long' if garch_info['persistence'] > 0.95 else 'Moderate — vol mean-reverts reasonably fast'}) | "
                    f"Long-run vol: {garch_info.get('long_run_vol', 0):.1f}%"
                )

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
        with st.expander("Historical Backtest: How reliable is this signal?", expanded=False):
            bt = backtest_vrp_strategy(hist, window=20, holding_period=20)
            bt_summary = summarize_backtest(bt)
            if bt_summary:
                st.markdown(
                    "We looked at every day in the past year where conditions were similar to today, "
                    "and checked what would have happened if you sold options then."
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
                            lambda r: score_trade(r, current_iv, rv_forecast, iv_rank, term_label), axis=1
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
                                current_price, best["strike"], strike_iv, dte, "call", premium
                            )
                            if prob_loss is not None:
                                avg_win = premium * 100
                                avg_loss = abs(float(np.mean([
                                    max(0, current_price * 1.1 - best["strike"]) - premium,
                                    max(0, current_price * 1.15 - best["strike"]) - premium,
                                ]))) * 100
                                kelly_frac = calc_kelly_size(1 - prob_loss, avg_win, max(avg_loss, 1))
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
                                st.metric("Kelly Size",
                                           f"{kelly_frac*100:.1f}% of capital" if kelly_frac > 0 else "No edge",
                                           help=TIPS["kelly"])
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
                            lambda r: score_trade(r, current_iv, rv_forecast, iv_rank, term_label), axis=1
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
                                current_price, best["strike"], strike_iv_p, dte, "put", premium
                            )
                            if prob_loss_p is not None:
                                avg_win_p = premium * 100
                                avg_loss_p = abs(float(np.mean([
                                    max(0, best["strike"] - current_price * 0.9) - premium,
                                    max(0, best["strike"] - current_price * 0.85) - premium,
                                ]))) * 100
                                kelly_frac_p = calc_kelly_size(1 - prob_loss_p, avg_win_p, max(avg_loss_p, 1))
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

    if not open_trades:
        st.info("No open positions. Log a trade above or use the Trade Analyzer to find opportunities.")
    else:
        for trade in open_trades:
            ticker = trade["ticker"]
            with st.spinner(f"Checking {ticker} {trade['strike']} {trade['option_type']}..."):
                try:
                    stock = yf.Ticker(ticker)
                    hist = stock.history(period="1y")
                    spot = hist["Close"].iloc[-1]

                    current_option_price = None
                    current_delta = None
                    try:
                        if trade["option_type"] == "call":
                            chain = stock.option_chain(trade["expiration"]).calls
                        else:
                            chain = stock.option_chain(trade["expiration"]).puts
                        match = chain[chain["strike"] == trade["strike"]]
                        if not match.empty:
                            row = match.iloc[0]
                            mid = (row["bid"] + row["ask"]) / 2 if row["bid"] > 0 else row["lastPrice"]
                            current_option_price = mid
                            dte_now = max((datetime.strptime(trade["expiration"], "%Y-%m-%d") - datetime.now()).days, 1)
                            iv_now = row.get("impliedVolatility", 0.3)
                            from py_vollib.black_scholes.greeks.analytical import delta as bs_delta_fn
                            flag = "c" if trade["option_type"] == "call" else "p"
                            t_years = max(dte_now / 365.0, 1/365)
                            current_delta = bs_delta_fn(flag, spot, trade["strike"], t_years, 0.045, iv_now)
                    except Exception:
                        pass

                    rv_20 = calc_realized_vol(hist, window=20)
                    current_iv = None
                    try:
                        exps = stock.options
                        if exps:
                            first_chain = stock.option_chain(exps[0]).calls
                            first_chain_c = first_chain.copy()
                            first_chain_c["dist"] = abs(first_chain_c["strike"] - spot)
                            atm = first_chain_c.loc[first_chain_c["dist"].idxmin()]
                            current_iv = atm["impliedVolatility"] * 100
                    except Exception:
                        pass

                    try:
                        exps = stock.options
                        chains_for_ts = {}
                        for exp in list(exps)[:4]:
                            chains_for_ts[exp] = stock.option_chain(exp)
                        _, term_label_pos = get_term_structure(chains_for_ts, list(exps)[:4], spot)
                    except Exception:
                        term_label_pos = "N/A"

                    signals, metrics = generate_exit_signals(
                        trade, spot, current_option_price, current_iv, rv_20, term_label_pos, current_delta
                    )
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


# ============================================================
# FOOTER
# ============================================================
st.divider()
st.caption(
    "Based on concepts from 'Retail Options Trading' by Sinclair & Mack (2024). "
    "This tool does NOT auto-trade. Not financial advice. "
    "Hover over any metric for an explanation."
)
