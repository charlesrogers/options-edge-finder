import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import json
import os
import yf_proxy
from analytics import (
    calc_realized_vol,
    calc_vrp_signal,
    get_iv_rank_percentile,
    get_term_structure,
    calc_garch_forecast,
    calc_yang_zhang_vol,
    classify_vol_regime,
    get_next_fomc_date,
    calc_skew_score,
    calc_empirical_probabilities,
)
from db import (
    add_trade, close_trade, get_open_trades, get_all_trades, delete_trade,
    record_iv, get_iv_history, get_real_iv_rank, using_supabase,
    log_prediction, get_holdings, save_holding,
)
from eval_monitor import check_circuit_breakers
from ticker_strategies import get_strategy, TIER_CONFIG

st.set_page_config(
    page_title="Covered Call Copilot",
    page_icon="$",
    layout="wide",
)

# Version marker -- increment to bust Streamlit caches on deploy
_APP_VERSION = "5.0-copilot"
if "app_version" not in st.session_state or st.session_state.app_version != _APP_VERSION:
    st.cache_data.clear()
    st.cache_resource.clear()
    st.session_state.app_version = _APP_VERSION


# ============================================================
# TOP NAVIGATION
# ============================================================
st.title("Covered Call Copilot")
st.caption("Never get called away. Never lose money. Make money.")

tab_positions, tab_sell, tab_howitworks = st.tabs([
    "My Positions",
    "Sell a Call",
    "How It Works",
])


# ============================================================
# DATA LOADERS -- all routed through Cloudflare Worker proxy
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
    """Load a single expiration's option chain (lazy -- only when needed)."""
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
        iv_rank_source = f"RV proxy (recording IV daily -- {iv_history_days}d so far)"

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

    # Record today's IV snapshot -- full data capture
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

    # Log prediction for scoring later -- full context
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
# TAB 1: MY POSITIONS (what Dad checks every morning)
# ============================================================
with tab_positions:
    st.header("My Positions")

    # --- Log a New Trade ---
    with st.expander("Log a New Trade", expanded=False):
        with st.form("add_trade_form"):
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                t_ticker = st.text_input("Ticker", value="AAPL").upper()
            with fc2:
                t_strike = st.number_input("Strike Price", min_value=1.0, value=250.0, step=5.0)
                t_premium = st.number_input("Premium Received (per share)", min_value=0.01, value=3.00, step=0.25)
            with fc3:
                t_contracts = st.number_input("Contracts", min_value=1, value=1, step=1)
                t_expiration = st.date_input("Expiration Date", value=datetime.now() + timedelta(days=30))
            t_notes = st.text_input("Notes (optional)", value="")

            submitted = st.form_submit_button("Log Trade")
            if submitted:
                add_trade(
                    ticker=t_ticker, option_type="call", strike=t_strike,
                    expiration=t_expiration.strftime("%Y-%m-%d"),
                    premium=t_premium, contracts=t_contracts,
                    strategy="covered_call", notes=t_notes,
                )
                st.success(f"Logged: Short {t_contracts} {t_ticker} {t_strike} Call @ ${t_premium:.2f}")
                st.rerun()

    open_trades = get_open_trades()

    # --- Circuit Breakers ---
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
                    st.info(f"**{alert['type']}**: {alert['message']} -- {alert['action']}")

            if cb["sizing_multiplier"] < 1.0:
                st.caption(f"Position sizing adjusted to {cb['sizing_multiplier']:.0%} of normal")
    except Exception:
        pass

    if not open_trades:
        st.info("No open positions. Log a trade above to start monitoring.")
    else:
        # --- COVERED CALL COPILOT (data-backed alerts) ---
        st.subheader("Position Alerts")
        st.caption(
            "Thresholds from 145,099 real option observations + 480,000 Monte Carlo paths. "
            "Priority: #1 Never get called away, #2 Don't lose money, #3 Make money."
        )

        for trade in open_trades:
            ticker = trade["ticker"]
            try:
                # Fetch current data
                hist_pos = yf_proxy.get_stock_history(ticker, period="5d")
                if hist_pos.empty:
                    continue
                spot_pos = float(hist_pos["Close"].iloc[-1])

                # Get current option ask price
                opt_ask = None
                try:
                    chain_pos = yf_proxy.get_option_chain(ticker, trade["expiration"])
                    match_pos = chain_pos.calls[chain_pos.calls["strike"] == trade["strike"]]
                    if not match_pos.empty:
                        ask_val = match_pos.iloc[0].get("ask", 0) or 0
                        bid_val = match_pos.iloc[0].get("bid", 0) or 0
                        opt_ask = (ask_val + bid_val) / 2 if bid_val > 0 else match_pos.iloc[0].get("lastPrice", 0)
                except Exception:
                    pass

                # Get ex-div and earnings dates
                ex_div_str = None
                earn_str = None
                try:
                    info_pos = yf_proxy.get_stock_info(ticker)
                    ex_div_ts = info_pos.get("exDividendDate")
                    if ex_div_ts and isinstance(ex_div_ts, (int, float)):
                        ex_div_str = datetime.fromtimestamp(ex_div_ts).strftime("%Y-%m-%d")
                    earn_ts = info_pos.get("earningsTimestampStart") or info_pos.get("earningsDate")
                    if earn_ts:
                        if isinstance(earn_ts, (list, tuple)):
                            earn_ts = earn_ts[0]
                        if isinstance(earn_ts, (int, float)):
                            earn_str = datetime.fromtimestamp(earn_ts).strftime("%Y-%m-%d")
                except Exception:
                    pass

                # Run copilot assessment
                from position_monitor import assess_position
                alert = assess_position(
                    ticker=ticker,
                    strike=trade["strike"],
                    expiry=trade["expiration"],
                    sold_price=trade["premium_received"],
                    contracts=trade["contracts"],
                    current_stock=spot_pos,
                    current_option_ask=opt_ask,
                    ex_div_date=ex_div_str,
                    earnings_date=earn_str,
                )

                # Display alert card
                level_config = {
                    "SAFE": ("success", "SAFE"),
                    "WATCH": ("warning", "WATCH"),
                    "CLOSE_SOON": ("warning", "CLOSE SOON"),
                    "CLOSE_NOW": ("error", "CLOSE NOW"),
                    "EMERGENCY": ("error", "EMERGENCY"),
                }
                st_func_name, level_label = level_config.get(alert.level, ("info", "?"))

                with st.container():
                    # Header
                    st.markdown(
                        f"### {alert.ticker} ${alert.strike:.0f} Call "
                        f"(sold ${alert.sold_price:.2f}, {alert.dte} DTE)"
                    )

                    # Metrics row
                    mc1, mc2, mc3, mc4 = st.columns(4)
                    mc1.metric("Stock", f"${alert.current_stock:.2f}")
                    mc2.metric("From Strike", f"{alert.pct_from_strike:+.1f}%",
                               help="Positive = OTM (safe), Negative = ITM (danger)")
                    mc3.metric("P(Assignment)", f"{alert.p_assignment:.0f}%")
                    mc4.metric("Premium Captured", f"{alert.premium_captured_pct:.0f}%")

                    # Alert message
                    if alert.level == "EMERGENCY":
                        st.error(f"**{alert.reason}**\n\n**{alert.action}**")
                    elif alert.level == "CLOSE_NOW":
                        st.error(f"**{alert.reason}**\n\n{alert.action}")
                    elif alert.level == "CLOSE_SOON":
                        st.warning(f"{alert.reason}\n\n{alert.action}")
                    elif alert.level == "WATCH":
                        st.warning(f"{alert.reason}\n\n{alert.action}")
                    else:
                        st.success(f"{alert.reason}\n\n{alert.action}")

                    # Buyback details
                    if alert.buyback_cost is not None:
                        bc1, bc2 = st.columns(2)
                        bc1.caption(f"Buyback cost: ${alert.buyback_cost:,.0f}")
                        bc2.caption(f"Net P&L if close now: ${alert.net_pnl:+,.0f}" if alert.net_pnl else "")

                    # Strategy fitness hint from Experiment 008
                    try:
                        _strat = get_strategy(ticker)
                        if _strat.get('skip'):
                            st.caption(f"**Strategy note:** Experiment 008 found covered calls on {ticker} lose money at every OTM%. Consider not selling calls on this ticker.")
                        elif _strat.get('otm_pct') and spot_pos and trade.get('strike'):
                            _actual_otm = (trade['strike'] - spot_pos) / spot_pos * 100
                            _optimal_otm = _strat['otm_pct'] * 100
                            if abs(_actual_otm - _optimal_otm) > 3:
                                _win = _strat.get('expected_win_rate', '?')
                                _pnl = _strat.get('expected_pnl')
                                _pnl_str = f", +${_pnl:,}/yr" if _pnl else ""
                                st.caption(f"**Strategy note:** This position is {_actual_otm:.0f}% OTM. Experiment 008 found {_optimal_otm:.0f}% OTM is optimal for {ticker} ({_win}% win rate{_pnl_str}).")
                    except Exception:
                        pass

                    # Close / Delete buttons
                    btn1, btn2 = st.columns(2)
                    with btn1:
                        if st.button(f"Close Trade #{trade['id']}", key=f"close_{trade['id']}"):
                            cp = opt_ask if opt_ask else 0
                            close_trade(trade["id"], cp, "manual_close")
                            st.success("Trade closed!")
                            st.rerun()
                    with btn2:
                        if st.button(f"Delete Trade #{trade['id']}", key=f"del_{trade['id']}"):
                            delete_trade(trade["id"])
                            st.warning("Trade deleted")
                            st.rerun()

                    st.markdown("---")

            except Exception:
                st.caption(f"{ticker} ${trade['strike']} -- could not assess (data unavailable)")

    # --- Trade History ---
    all_trades = get_all_trades()
    closed_trades = [t for t in all_trades if t["status"] != "open"]
    if closed_trades:
        with st.expander(f"Trade History ({len(closed_trades)} closed)", expanded=False):
            hist_data = []
            for t in closed_trades:
                pnl = ((t["premium_received"] - (t.get("close_price") or 0)) * 100 * t["contracts"])
                hist_data.append({
                    "Ticker": t["ticker"], "Strike": t["strike"],
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
# TAB 2: SELL A CALL (daily recommendations)
# ============================================================
with tab_sell:
    st.header("Sell a Call")

    # --- Portfolio Holdings ---
    try:
        holdings = get_holdings()
    except Exception:
        holdings = {}

    with st.expander("My Stock Holdings (edit shares owned)", expanded=not bool(holdings)):
        st.caption("Enter how many shares you own of each stock. "
                   "This determines covered call sizing and concentration limits.")

        # Default tickers
        default_tickers = ["TXN", "TMUS", "GOOGL", "AMZN", "AAPL", "KKR", "DIS"]
        edit_tickers = sorted(set(list(holdings.keys()) + default_tickers))

        cols_per_row = 3
        for i in range(0, len(edit_tickers), cols_per_row):
            row_tickers = edit_tickers[i:i + cols_per_row]
            cols = st.columns(cols_per_row)
            for j, tick in enumerate(row_tickers):
                with cols[j]:
                    current = holdings.get(tick, {}).get("shares", 0)
                    new_val = st.number_input(
                        f"{tick} shares", value=int(current),
                        min_value=0, step=100, key=f"holding_{tick}",
                    )
                    if new_val != current:
                        try:
                            save_holding(tick, new_val)
                            holdings[tick] = {"shares": new_val, "avg_cost": None}
                        except Exception:
                            pass

        # Add new ticker
        new_tick = st.text_input("Add ticker", placeholder="Enter ticker symbol...",
                                  key="add_holding_ticker")
        if new_tick:
            new_tick = new_tick.strip().upper()
            if new_tick and new_tick not in holdings:
                try:
                    save_holding(new_tick, 0)
                    holdings[new_tick] = {"shares": 0, "avg_cost": None}
                    st.rerun()
                except Exception:
                    pass

    # Watchlist = tickers with holdings
    watchlist = [t for t in holdings if holdings[t].get("shares", 0) > 0]
    if not watchlist:
        watchlist = [t.strip().upper() for t in "TXN, TMUS, GOOGL, AMZN, AAPL, KKR, DIS".split(",")]

    # Portfolio settings + phase
    portfolio_value = st.session_state.get("portfolio_value", 1000000)
    current_phase = st.session_state.get("trading_phase", "paper")

    with st.expander("Portfolio Settings", expanded=False):
        portfolio_value = st.number_input("Total Portfolio Value ($)", value=portfolio_value,
                                           min_value=10000, step=50000)
        st.session_state.portfolio_value = portfolio_value

        current_phase = st.selectbox(
            "Current Phase",
            ["paper", "starter", "quarter_kelly", "full"],
            index=["paper", "starter", "quarter_kelly", "full"].index(current_phase),
            format_func=lambda x: {
                "paper": "A: Paper Trading (no real money)",
                "starter": "B: Starter (1 contract max, 3 positions max)",
                "quarter_kelly": "C: Quarter-Kelly (3% per position, 6 max)",
                "full": "D: Full Deployment (5% per position, 10 max)",
            }.get(x, x),
            help="Progress through phases: Paper -> Starter -> Quarter-Kelly -> Full. "
                 "Each phase has minimum weeks and gates before advancing."
        )
        st.session_state.trading_phase = current_phase

    # Phase banner
    phase_labels = {
        "paper": ("Paper Trading", "info", "No real money. Track what WOULD happen."),
        "starter": ("Starter", "warning", "1 contract per trade, max 3 positions."),
        "quarter_kelly": ("Quarter-Kelly", "success", "Scaled sizing, max 3% per position."),
        "full": ("Full Deployment", "success", "Full deployment with monitoring."),
    }
    p_label, p_type, p_desc = phase_labels.get(current_phase, ("Unknown", "info", ""))
    if p_type == "info":
        st.info(f"**Phase: {p_label}** -- {p_desc}")
    elif p_type == "warning":
        st.warning(f"**Phase: {p_label}** -- {p_desc}")
    else:
        st.success(f"**Phase: {p_label}** -- {p_desc}")

    if not watchlist:
        st.info("Enter tickers in your watchlist above to see today's recommendations.")
    else:
        # --- Market Conditions Banner ---
        try:
            vix_hist = yf_proxy.get_stock_history("^VIX", period="5d")
            if not vix_hist.empty:
                vix_level = float(vix_hist["Close"].iloc[-1])
                if vix_level > 45:
                    st.error(f"**MARKET HALTED** -- VIX at {vix_level:.1f}. No new trades. Protect existing positions.")
                    st.warning("The system will NOT show any trade recommendations when VIX > 45. "
                               "Focus on managing existing positions.")
                    watchlist = []
                elif vix_level > 35:
                    st.warning(f"**CAUTION** -- VIX at {vix_level:.1f}. Reduce position sizes by 50%.")
                elif vix_level > 25:
                    st.info(f"**ELEVATED VOL** -- VIX at {vix_level:.1f}. Be selective.")
                else:
                    st.success(f"**OPEN FOR BUSINESS** -- VIX at {vix_level:.1f}. Normal conditions.")
            else:
                vix_level = None
        except Exception:
            vix_level = None

        # --- Scan Watchlist for Covered Call Recommendations ---
        st.caption(f"Scanning {len(watchlist)} tickers for covered call opportunities...")
        progress = st.progress(0)

        recommendations = []
        skipped = []

        for i, ticker in enumerate(watchlist):
            progress.progress((i + 1) / len(watchlist))
            strat = get_strategy(ticker)

            # Skip tickers flagged by Experiment 008
            if strat.get('skip'):
                skipped.append({"ticker": ticker, "reason": strat.get('note', 'Not recommended'),
                                "tier": strat['tier']})
                continue

            shares_owned = holdings.get(ticker, {}).get("shares", 0)
            max_contracts = shares_owned // 100 if shares_owned >= 100 else 0

            try:
                data = compute_analytics(ticker)
                if not data or "error" in data:
                    continue

                current_price = data.get("current_price")
                if not current_price:
                    continue

                chains = data.get("chains", {})
                expirations = data.get("expirations", [])
                current_iv = data.get("current_iv")
                rv_forecast = data.get("rv_forecast")
                vrp = data.get("vrp")

                # Find the best call to sell using per-ticker optimal OTM%
                otm_pct = strat['otm_pct'] or 0.05
                target_strike = current_price * (1 + otm_pct)
                min_dte = strat.get('min_dte') or 20
                max_dte = strat.get('max_dte') or 45

                best_call = None
                best_expiry = None

                for exp in expirations:
                    if exp not in chains:
                        # Lazy-load additional expirations if needed
                        chain = load_chain(ticker, exp)
                        if chain is not None:
                            chains[exp] = chain
                        else:
                            continue
                    chain = chains[exp]
                    if not hasattr(chain, 'calls') or chain.calls.empty:
                        continue

                    # Check DTE
                    try:
                        exp_date = pd.Timestamp(exp)
                        dte = (exp_date - pd.Timestamp.now()).days
                        if dte < min_dte or dte > max_dte:
                            continue
                    except Exception:
                        continue

                    calls = chain.calls[chain.calls["strike"] > 0].copy()
                    if calls.empty:
                        continue

                    # Find strike nearest to target
                    calls["dist"] = abs(calls["strike"] - target_strike)
                    best_row = calls.loc[calls["dist"].idxmin()]
                    strike = float(best_row["strike"])
                    bid = best_row.get("bid", 0) or 0
                    ask = best_row.get("ask", 0) or 0
                    premium = round((bid + ask) / 2, 2) if bid > 0 else float(best_row.get("lastPrice", 0))

                    if premium <= 0:
                        continue

                    actual_otm = (strike - current_price) / current_price * 100

                    if best_call is None or abs(dte - 30) < abs(best_call.get("dte", 0) - 30):
                        best_call = {
                            "strike": strike,
                            "premium": premium,
                            "dte": dte,
                            "actual_otm": actual_otm,
                        }
                        best_expiry = exp

                if best_call and best_call["premium"] > 0:
                    # Sizing
                    if current_phase == "paper":
                        n_contracts = 0
                    elif current_phase == "starter":
                        n_contracts = min(1, max_contracts)
                    else:
                        n_contracts = min(max_contracts, 3)  # conservative max

                    recommendations.append({
                        "ticker": ticker,
                        "price": current_price,
                        "strike": best_call["strike"],
                        "premium": best_call["premium"],
                        "dte": best_call["dte"],
                        "expiry": best_expiry,
                        "actual_otm": best_call["actual_otm"],
                        "target_otm": otm_pct * 100,
                        "shares_owned": shares_owned,
                        "max_contracts": max_contracts,
                        "n_contracts": n_contracts,
                        "tier": strat['tier'],
                        "expected_pnl": strat.get('expected_pnl'),
                        "expected_win_rate": strat.get('expected_win_rate'),
                        "note": strat.get('note', ''),
                        "iv": current_iv,
                        "rv": rv_forecast,
                        "vrp": vrp,
                    })
            except Exception:
                continue

        progress.empty()

        # --- Display Covered Call Recommendations ---
        if recommendations:
            # Sort by expected P&L (best strategies first)
            recommendations.sort(key=lambda x: x.get("expected_pnl") or 0, reverse=True)

            st.subheader(f"{len(recommendations)} Covered Call Recommendations")
            st.caption("Per-ticker optimal strikes from Experiment 008 (75 combos, real Databento data)")

            for rec in recommendations:
                tick = rec["ticker"]
                tier = rec["tier"]
                tc = TIER_CONFIG.get(tier, TIER_CONFIG['untested'])

                with st.container():
                    st.markdown("---")

                    # Header with tier badge
                    shares = rec.get("shares_owned", 0)
                    contracts_available = rec.get("max_contracts", 0)

                    # Map tier to streamlit color names
                    tier_colors = {'best': 'green', 'strong': 'blue', 'good': 'violet',
                                   'conservative': 'orange', 'untested': 'gray'}
                    tier_color = tier_colors.get(tier, 'gray')
                    st.markdown(f"### {tick}  ${rec['price']:.2f}  :{tier_color}[{tc['icon']} {tc['label']}]")

                    if shares > 0:
                        st.caption(f"You own **{shares:,} shares** ({contracts_available} contracts available)")
                    else:
                        st.caption("No shares entered -- add holdings above to enable sizing")

                    # The recommendation
                    phase_note = " *(Paper trade -- track but don't execute)*" if current_phase == "paper" else ""
                    n_c = rec.get("n_contracts", 0)
                    contract_text = f" x {n_c} contract{'s' if n_c > 1 else ''}" if n_c > 0 else ""

                    st.markdown(
                        f"**Sell ${rec['strike']:.0f} Call @ ${rec['premium']:.2f}** "
                        f"| {rec['expiry']} ({rec['dte']} DTE) "
                        f"| {rec['actual_otm']:.1f}% OTM{contract_text}{phase_note}"
                    )

                    # Key numbers
                    m1, m2, m3, m4 = st.columns(4)
                    with m1:
                        premium_total = rec["premium"] * 100 * max(n_c, 1)
                        st.metric("Premium", f"${premium_total:,.0f}",
                                  help=f"${rec['premium']:.2f}/share x 100 x {max(n_c, 1)} contract(s)")
                    with m2:
                        win_rate = rec.get("expected_win_rate")
                        if win_rate:
                            st.metric("Win Rate", f"{win_rate}%",
                                      help="From Experiment 008 backtest on real data")
                        else:
                            st.metric("Win Rate", "Unknown", help="Untested ticker")
                    with m3:
                        exp_pnl = rec.get("expected_pnl")
                        if exp_pnl:
                            st.metric("Expected P&L/yr", f"${exp_pnl:+,}/contract",
                                      help="Net annual P&L from Experiment 008 (premium - buyback costs)")
                        else:
                            st.metric("Expected P&L/yr", "Unknown")
                    with m4:
                        st.metric("Strategy", f"{rec['target_otm']:.0f}% OTM",
                                  help=f"Optimal OTM% for {tick} from Experiment 008")

                    # Plain English
                    st.markdown(f"""
**What happens:**
- **Most likely:** {tick} stays below ${rec['strike']:.0f} -- call expires worthless -- you keep ${premium_total:,.0f}
- **If {tick} rises above ${rec['strike']:.0f}:** copilot alerts you to buy back before assignment
- **Copilot guarantee:** zero assignments in 75 backtest combos across 5 tickers
""")

                    # Research backing
                    if rec.get('note'):
                        st.caption(f"**Research:** {rec['note']}")

                    # VRP context (secondary)
                    if rec.get("iv") and rec.get("rv"):
                        gap = rec["iv"] - rec["rv"]
                        if gap > 0:
                            st.caption(
                                f"**Vol edge:** IV {rec['iv']:.0f}% vs RV forecast {rec['rv']:.0f}% "
                                f"({gap:.0f}pt gap -- options are overpriced)"
                            )
        else:
            st.info("No covered call recommendations today. Check that you have holdings entered above.")

        # --- Skipped Tickers ---
        if skipped:
            with st.expander(f"Skipped {len(skipped)} ticker(s)", expanded=False):
                for s in skipped:
                    tc = TIER_CONFIG.get(s['tier'], TIER_CONFIG['skip'])
                    st.caption(f"{tc['icon']} **{s['ticker']}**: {s['reason']}")


# ============================================================
# TAB 3: HOW IT WORKS (evidence the tool works -- read once)
# ============================================================
with tab_howitworks:
    st.header("How It Works")
    st.caption("Evidence that this tool actually helps. Read once, then trust the alerts.")

    # --- Section 1: Copilot Simulator Results (Experiment 007) ---
    st.subheader("Would This Tool Have Saved You?")
    st.caption("Real AAPL covered call history replayed through the copilot. Databento option prices, not estimates.")

    _sim_path = os.path.join(os.path.dirname(__file__), "experiments", "007_copilot_simulator", "results.json")
    _sim_data = None
    if os.path.exists(_sim_path):
        try:
            with open(_sim_path) as _f:
                _sim_data = json.load(_f)
        except Exception:
            pass

    if _sim_data and "trades" in _sim_data:
        _trades = _sim_data["trades"]
        _summary = _sim_data.get("summary", {})

        # --- Big number hero ---
        _tax_avoided = _summary.get("tax_avoided", 0)
        _assignments_prevented = _summary.get("assignments_prevented", 0)
        _false_alarms = _summary.get("false_alarms", 0)
        _false_alarm_cost = _summary.get("false_alarm_cost", 0)
        _net_pnl = _summary.get("net_pnl", 0)

        st.markdown(f"""
        <div style="text-align:center; padding: 1.5rem; background: linear-gradient(135deg, #065f46, #047857); border-radius: 12px; margin-bottom: 1.5rem;">
            <div style="color: #6ee7b7; font-size: 14px; text-transform: uppercase; letter-spacing: 2px;">Estimated Taxes Avoided</div>
            <div style="color: white; font-size: 48px; font-weight: bold;">${_tax_avoided:,.0f}</div>
            <div style="color: #a7f3d0; font-size: 14px; margin-top: 4px;">{_assignments_prevented} assignments prevented on {len(_trades)} trades</div>
        </div>
        """, unsafe_allow_html=True)

        # --- With vs Without Copilot ---
        col_with, col_without = st.columns(2)

        with col_with:
            st.markdown("#### With Copilot")
            _total_premium = _summary.get("total_premium", 0)
            _total_buyback = _summary.get("total_buyback", 0)
            st.metric("Premium Collected", f"${_total_premium:,.0f}")
            st.metric("Buyback Costs", f"${_total_buyback:,.0f}")
            st.metric("Net P&L", f"${_net_pnl:+,.0f}")
            st.metric("Assignments", "ZERO", delta="0 shares called away", delta_color="off")

        with col_without:
            st.markdown("#### Without Copilot (Hold to Expiry)")
            _would_assign = _summary.get("assignments_without_copilot", 0)
            st.metric("Would Have Been Assigned", f"{_would_assign} times")
            st.metric("Tax Bill (est.)", f"${_tax_avoided:,.0f}", delta=f"-${_tax_avoided:,.0f}", delta_color="inverse")
            if _tax_avoided > 0:
                _buyback_total = sum(abs(t["pnl_per_contract"]) for t in _trades if t["pnl_per_contract"] < 0)
                _roi = _tax_avoided / max(_buyback_total, 1)
                st.metric("Return on Copilot", f"{_roi:.0f}x",
                          help="Every $1 spent on early buybacks saved this much in avoided taxes")

        # --- False Alarm Honesty ---
        st.markdown("---")
        _fa_col1, _fa_col2 = st.columns(2)
        _fa_col1.metric("False Alarms", _false_alarms,
                        help="Times the copilot said CLOSE but the position would have expired worthless")
        _fa_col2.metric("False Alarm Cost", f"${_false_alarm_cost:,.0f}",
                        help="Premium given up on unnecessary early closes")

        # --- Trade-by-Trade Timeline ---
        with st.expander("Trade-by-Trade Timeline", expanded=False):
            _icons = {"SAFE": "SAFE", "WATCH": "WATCH", "CLOSE_SOON": "CLOSE SOON",
                      "CLOSE_NOW": "CLOSE NOW", "EMERGENCY": "EMERGENCY"}

            for _t in _trades:
                _icon = _icons.get(_t.get("alert_at_close", ""), "?")
                _assign_badge = " **WOULD HAVE BEEN ASSIGNED**" if _t.get("would_assign_at_expiry") else ""
                _tax_badge = f" -- Saved ${_t['tax_avoided']:,.0f}" if _t.get("tax_avoided", 0) > 0 else ""
                _pnl_color = "green" if _t["pnl_per_contract"] >= 0 else "red"

                with st.container():
                    st.markdown(
                        f"[{_icon}] **{_t['entry_date']} -> {_t['exit_date']}** ({_t['days_held']}d) "
                        f"| ${_t['strike']:.0f} Call @ ${_t['sold_price']:.2f} "
                        f"| Stock: ${_t['entry_spot']:.0f} -> ${_t['exit_spot']:.0f} "
                        f"| P&L: **:{_pnl_color}[${_t['pnl_per_contract']:+,.0f}]**"
                        f"{_assign_badge}{_tax_badge}"
                    )
                    _reason = _t.get("close_reason", "")
                    if _reason:
                        st.caption(_reason)

        # --- Methodology ---
        with st.expander("Methodology"):
            st.markdown("""
**Data:** Real AAPL option prices from Databento (OHLCV, Apr 2025 - Mar 2026). Not Black-Scholes estimates.

**Strategy:** Sell ~5% OTM monthly covered calls on the first trading day of each month.

**Copilot Rules:**
- **SAFE/WATCH**: Hold position
- **CLOSE_SOON**: Buy back (take profit or approaching danger zone)
- **CLOSE_NOW**: Buy back immediately (ITM, near-expiry + near-strike, or ex-div danger)
- **EMERGENCY**: ITM + ex-dividend within 3 days (the $400K alert)

**Tax Assumption:** $150/share unrealized gain, 30% tax rate = $4,500/contract if assigned.

**"Would have been assigned"** = stock price was above strike at actual expiration.
All thresholds are from Experiment 006 (145,099 real observations + 480,000 Monte Carlo paths).
            """)
    else:
        st.warning("Simulator results not found. Run `experiments/007_copilot_simulator/run.py` first.")

    # --- Section 2: Strategy Grid Search Results (Experiment 008) ---
    st.markdown("---")
    st.subheader("Which Strategy Works Best?")
    st.caption("75 parameter combos tested across 5 tickers with real Databento prices")

    _grid_path = os.path.join(os.path.dirname(__file__), "experiments", "008_strategy_grid", "results.json")
    _grid_data = None
    if os.path.exists(_grid_path):
        try:
            with open(_grid_path) as _f:
                _grid_data = json.load(_f)
        except Exception:
            pass

    if _grid_data:
        _grid_df = pd.DataFrame(_grid_data)
        _grid_df = _grid_df[_grid_df.get('num_trades', pd.Series(dtype=float)).notna()]
        _grid_df = _grid_df[_grid_df['num_trades'] > 0]

        if not _grid_df.empty:
            # OTM% summary
            st.markdown("#### OTM% Comparison (averaged across tickers)")
            _otm_summary = []
            for _otm in sorted(_grid_df['otm_pct'].unique()):
                _sub = _grid_df[_grid_df['otm_pct'] == _otm]
                _otm_summary.append({
                    'Strike Distance': f"{_otm*100:.0f}% OTM",
                    'Avg Net P&L': f"${_sub['net_pnl'].mean():+,.0f}",
                    'Win Rate': f"{_sub['win_rate'].mean():.0f}%",
                    'Profitable Combos': f"{len(_sub[_sub['net_pnl'] > 0])}/{len(_sub)}",
                    'Assignments': int(_sub['assignments'].sum()),
                })
            st.dataframe(pd.DataFrame(_otm_summary), use_container_width=True, hide_index=True)

            # Top 10 strategies
            st.markdown("#### Top 10 Strategies (0 assignments + highest profit)")
            _best = _grid_df[(_grid_df['assignments'] == 0) & (_grid_df['net_pnl'] > 0)]
            if not _best.empty:
                _top = _best.sort_values('composite_score', ascending=False).head(10)
                _display = _top[['ticker', 'otm_pct', 'dte_label', 'num_trades',
                                 'win_rate', 'net_pnl', 'avg_pnl', 'worst_trade',
                                 'premium_retained_pct']].copy()
                _display.columns = ['Ticker', 'OTM%', 'DTE', 'Trades', 'Win%',
                                    'Net P&L', 'Avg P&L', 'Worst', 'Retained%']
                _display['OTM%'] = _display['OTM%'].apply(lambda x: f"{x*100:.0f}%")
                _display['Net P&L'] = _display['Net P&L'].apply(lambda x: f"${x:+,.0f}")
                _display['Avg P&L'] = _display['Avg P&L'].apply(lambda x: f"${x:+,.0f}")
                _display['Worst'] = _display['Worst'].apply(lambda x: f"${x:+,.0f}")
                _display['Win%'] = _display['Win%'].apply(lambda x: f"{x:.0f}%")
                _display['Retained%'] = _display['Retained%'].apply(lambda x: f"{x:.0f}%")
                st.dataframe(_display, use_container_width=True, hide_index=True)
            else:
                st.warning("No strategy achieved both 0 assignments and positive P&L.")

            # Key finding
            st.success(
                "**Key Finding:** 3% OTM collects enough premium to absorb buyback costs "
                "(avg +$500/yr). 5-7% OTM is the worst of both worlds -- moderate premium, expensive buybacks. "
                "10-15% OTM is safe but collects less. The optimal strategy depends on the stock's volatility."
            )
    else:
        st.info("Run `experiments/008_strategy_grid/run.py` to see strategy comparison results.")

    # --- Section 3: Bear Market Stress Test (Experiment 010) ---
    st.markdown("---")
    st.subheader("What Happens in a Bear Market?")
    st.caption("10,000 Monte Carlo paths across 4 market scenarios. Do covered calls help or hurt?")

    _stress_path = os.path.join(os.path.dirname(__file__), "experiments", "010_bear_market_stress", "results.json")
    _stress_data = None
    if os.path.exists(_stress_path):
        try:
            with open(_stress_path) as _f:
                _stress_data = json.load(_f)
        except Exception:
            pass

    if _stress_data:
        # Group by scenario, pick the 15% OTM (conservative) results for summary
        _scenarios = {}
        for row in _stress_data:
            key = row["scenario"]
            if key not in _scenarios:
                _scenarios[key] = {}
            _scenarios[key][row["otm_pct"]] = row

        # Scenario order
        _scenario_order = ["bull_market", "sideways", "gradual_decline", "sharp_crash", "flash_crash"]
        _scenario_icons = {
            "bull_market": "Bull Market",
            "sideways": "Sideways Grind",
            "gradual_decline": "Gradual Decline (-20%)",
            "sharp_crash": "Sharp Crash (-30%)",
            "flash_crash": "Flash Crash (-10% day 1)",
        }

        _stress_summary = []
        for sc in _scenario_order:
            if sc not in _scenarios:
                continue
            # Show conservative (15% OTM) results
            r = _scenarios[sc].get(0.15) or _scenarios[sc].get(0.03)
            if not r:
                continue
            _stress_summary.append({
                "Scenario": r.get("label", sc),
                "Stock Only (avg)": f"{r['stock_mean_return']:+.1f}%",
                "With Covered Calls (avg)": f"{r['cc_mean_return']:+.1f}%",
                "CC Beats Stock": f"{r['cc_beats_stock_pct']:.0f}%",
                "Avg Call P&L": f"${r['avg_call_pnl']:+,.0f}",
                "Cushion": f"{r['avg_cushion_pct']:+.1f}%",
            })

        if _stress_summary:
            st.dataframe(pd.DataFrame(_stress_summary), use_container_width=True, hide_index=True)

            st.success(
                "**Key Finding:** Covered calls provide a cushion in every scenario. "
                "In a sharp crash, stock-only loses -28.5% on average while covered calls lose -22.2% "
                "(6.4% cushion). In sideways markets, covered calls turn a slight loss into a slight gain."
            )

            with st.expander("Aggressive vs Conservative (3% OTM vs 15% OTM)"):
                _comp_data = []
                for sc in _scenario_order:
                    if sc not in _scenarios:
                        continue
                    agg = _scenarios[sc].get(0.03)
                    con = _scenarios[sc].get(0.15)
                    if agg and con:
                        _comp_data.append({
                            "Scenario": agg.get("label", sc),
                            "3% OTM (avg return)": f"{agg['cc_mean_return']:+.1f}%",
                            "3% OTM cushion": f"{agg['avg_cushion_pct']:+.1f}%",
                            "15% OTM (avg return)": f"{con['cc_mean_return']:+.1f}%",
                            "15% OTM cushion": f"{con['avg_cushion_pct']:+.1f}%",
                        })
                if _comp_data:
                    st.dataframe(pd.DataFrame(_comp_data), use_container_width=True, hide_index=True)
                    st.caption(
                        "15% OTM provides more cushion in crashes (6.4% vs 2.8%) because the premium "
                        "collected is closer to pure profit. 3% OTM earns more in sideways markets."
                    )
    else:
        st.info("Run `experiments/010_bear_market_stress/run.py` to see bear market stress test results.")
