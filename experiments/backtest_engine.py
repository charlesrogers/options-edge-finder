"""
Portfolio Backtest Engine — The ONE correct backtest for all experiments.

Fixes every methodological flaw from Experiments 001-003:
1. Portfolio-level daily P&L (not individual trade averages)
2. Concurrent position tracking with limits
3. Real option prices from Databento
4. Proper exit priority (DTE floor > take-profit > stale > expiry)
5. Calendar-day holdout with 50+ test days
6. Bootstrap on daily portfolio returns

Per tasks/lessons.md:
- Never use arbitrary trade skip intervals
- Never silently skip None repricing
- Sharpe > 3.0 is a red flag
- Model concurrent positions as portfolio
"""

import os
import sys
import re
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
import databento as db


# ============================================================
# DATA TYPES
# ============================================================

@dataclass
class Position:
    """A single open option position (one spread or one CSP)."""
    ticker: str
    entry_date: pd.Timestamp
    sell_symbol: str
    buy_symbol: Optional[str]  # None for CSP
    sell_strike: float
    buy_strike: float  # 0 for CSP
    entry_credit: float  # per-share, after slippage
    raw_credit: float  # per-share, before slippage
    expiration: datetime
    dte_at_entry: int
    mode: str  # "spread" or "csp"

    # Tracking
    last_known_sell_price: float = 0
    last_known_buy_price: float = 0
    days_since_reprice: int = 0


@dataclass
class ClosedTrade:
    """A completed trade with P&L."""
    ticker: str
    mode: str
    entry_date: str
    exit_date: str
    exit_reason: str
    raw_credit: float  # per contract (x100)
    pnl: float  # per contract (x100)
    days_held: int
    sell_strike: float
    buy_strike: float


# ============================================================
# OPTION DATA HELPERS
# ============================================================

def load_option_data(ticker):
    """Load Databento option OHLCV for a ticker."""
    raw_dir = os.path.join(os.path.dirname(__file__), '..', 'data', 'databento', 'raw')
    if not os.path.exists(raw_dir):
        raw_dir = os.path.join(os.path.dirname(__file__), 'data', 'databento', 'raw')

    files = sorted([f for f in os.listdir(raw_dir)
                     if f.startswith(f'{ticker}_ohlcv') and f.endswith('.dbn.zst')])
    if not files:
        return pd.DataFrame()

    dfs = []
    for f in files:
        data = db.DBNStore.from_file(os.path.join(raw_dir, f))
        dfs.append(data.to_df())

    combined = pd.concat(dfs).sort_index()
    # Drop exact duplicates only (keep all contracts per date)
    combined = combined.reset_index().drop_duplicates().set_index('ts_event')
    return combined


def load_stock_data(ticker, period="2y"):
    """Load stock OHLCV."""
    import yfinance as yf
    hist = yf.download(ticker, period=period, progress=False)
    if isinstance(hist.columns, pd.MultiIndex):
        hist.columns = hist.columns.get_level_values(0)
    return hist


def parse_option_symbol(sym):
    """Parse OCC option symbol → (expiration, strike) or (None, None)."""
    m = re.search(r'(\d{6})P(\d{8})', str(sym).strip())
    if m:
        try:
            exp = datetime.strptime('20' + m.group(1), '%Y%m%d')
            strike = float(m.group(2)) / 1000
            return exp, strike
        except Exception:
            pass
    return None, None


def get_puts_on_date(option_df, date):
    """Get all puts available on a date, aggregated across exchanges."""
    date_ts = pd.Timestamp(date).normalize()
    if option_df.index.tz is not None:
        date_ts = date_ts.tz_localize(option_df.index.tz)

    day_data = option_df[option_df.index.normalize() == date_ts]
    if day_data.empty:
        return pd.DataFrame()

    # Aggregate across exchanges
    agg = day_data.groupby('symbol').agg({'close': 'mean', 'volume': 'sum'}).reset_index()

    # Filter to puts
    puts = agg[agg['symbol'].str.match(r'.*\d{6}P\d+', na=False)].copy()
    if puts.empty:
        return pd.DataFrame()

    # Parse strike and expiry
    parsed = puts['symbol'].apply(
        lambda s: pd.Series(parse_option_symbol(s), index=['expiration', 'strike'])
    )
    puts = pd.concat([puts, parsed], axis=1).dropna(subset=['expiration', 'strike'])
    return puts


def find_spread_legs(puts_df, spot, sell_otm_pct=0.05, buy_otm_pct=0.10,
                      min_dte=15, max_dte=45, trade_date=None):
    """Find sell and buy put legs from available puts."""
    if puts_df.empty:
        return None

    df = puts_df.copy()
    if trade_date:
        df['dte'] = (df['expiration'] - pd.Timestamp(trade_date)).dt.days
        df = df[(df['dte'] >= min_dte) & (df['dte'] <= max_dte)]

    if df.empty:
        return None

    # Nearest monthly expiry ~25 DTE
    df['dte_dist'] = abs(df['dte'] - 25)
    best_exp = df.loc[df['dte_dist'].idxmin(), 'expiration']
    exp_df = df[df['expiration'] == best_exp].copy()

    # Sell leg
    sell_target = spot * (1 - sell_otm_pct)
    exp_df['sell_dist'] = abs(exp_df['strike'] - sell_target)
    sell_row = exp_df.loc[exp_df['sell_dist'].idxmin()]

    # Buy leg
    buy_target = spot * (1 - buy_otm_pct)
    buy_cands = exp_df[exp_df['strike'] < sell_row['strike']].copy()
    if buy_cands.empty:
        return None
    buy_cands['buy_dist'] = abs(buy_cands['strike'] - buy_target)
    buy_row = buy_cands.loc[buy_cands['buy_dist'].idxmin()]

    credit = float(sell_row['close'] - buy_row['close'])
    if credit <= 0:
        return None

    return {
        "sell_symbol": str(sell_row['symbol']),
        "buy_symbol": str(buy_row['symbol']),
        "sell_strike": float(sell_row['strike']),
        "buy_strike": float(buy_row['strike']),
        "sell_price": float(sell_row['close']),
        "buy_price": float(buy_row['close']),
        "credit": credit,
        "expiration": best_exp,
        "dte": int(sell_row['dte']),
    }


def reprice_option(option_df, date, symbol):
    """Get option close price on a date. Returns (price, found)."""
    date_ts = pd.Timestamp(date).normalize()
    if option_df.index.tz is not None:
        date_ts = date_ts.tz_localize(option_df.index.tz)
    day = option_df[option_df.index.normalize() == date_ts]
    if day.empty:
        return None, False
    match = day[day['symbol'] == symbol]
    if match.empty:
        return None, False
    return float(match['close'].mean()), True


# ============================================================
# SIGNAL GENERATION
# ============================================================

def compute_daily_signals(stock_hist, window=20, iv_rv_ratio=1.2):
    """Compute GREEN/YELLOW/RED for each trading day."""
    close = stock_hist["Close"].values
    log_ret = np.log(close[1:] / close[:-1])
    rv = pd.Series(log_ret).rolling(window).std().values * np.sqrt(252) * 100
    iv_proxy = rv * iv_rv_ratio
    iv_q30 = np.nanpercentile(iv_proxy, 30)

    results = []
    dates = stock_hist.index[1:]
    for i in range(len(rv)):
        if np.isnan(rv[i]) or np.isnan(iv_proxy[i]):
            results.append(("SKIP", 0))
            continue
        vrp = iv_proxy[i] - rv[i]
        if vrp > 2 and iv_proxy[i] > iv_q30:
            results.append(("GREEN", vrp))
        elif vrp > 0:
            results.append(("YELLOW", vrp))
        else:
            results.append(("RED", vrp))

    return pd.DataFrame({
        "close": close[1:len(results) + 1],
        "signal": [r[0] for r in results],
        "vrp": [r[1] for r in results],
    }, index=dates[:len(results)])


# ============================================================
# PORTFOLIO BACKTEST ENGINE
# ============================================================

class PortfolioBacktest:
    def __init__(self,
                 mode="spread",
                 max_positions_per_ticker=3,
                 max_total_positions=10,
                 slippage_pct=0.05,
                 take_profit_pct=0.25,
                 dte_floor=5,
                 sell_otm_pct=0.05,
                 buy_otm_pct=0.10,
                 min_vrp=2.0,
                 starting_capital=100000):
        self.mode = mode
        self.max_per_ticker = max_positions_per_ticker
        self.max_total = max_total_positions
        self.slippage = slippage_pct
        self.tp_pct = take_profit_pct
        self.dte_floor = dte_floor
        self.sell_otm = sell_otm_pct
        self.buy_otm = buy_otm_pct
        self.min_vrp = min_vrp
        self.capital = starting_capital

        # State
        self.positions: list[Position] = []
        self.closed_trades: list[ClosedTrade] = []
        self.daily_pnl: list[tuple] = []  # (date, pnl, n_positions)
        self.reprice_stats = {"found": 0, "missing": 0}
        self.skipped_at_limit = 0

    def run(self, tickers, option_data_map, stock_data_map):
        """
        Run portfolio backtest across all tickers, day by day.

        Args:
            tickers: list of ticker symbols
            option_data_map: {ticker: DataFrame from Databento}
            stock_data_map: {ticker: DataFrame from Yahoo}
        """
        # Compute signals for all tickers
        signals_map = {}
        for ticker in tickers:
            if ticker in stock_data_map and not stock_data_map[ticker].empty:
                signals_map[ticker] = compute_daily_signals(stock_data_map[ticker])

        # Get all trading days (union across tickers)
        all_dates = set()
        for sig_df in signals_map.values():
            all_dates.update(sig_df.index)
        all_dates = sorted(all_dates)

        prev_portfolio_value = 0.0  # Track previous day's total unrealized

        for date in all_dates:
            if date.weekday() >= 5:
                continue

            realized_today = 0.0

            # 1. Reprice and check exits on all open positions
            positions_to_close = []
            for i, pos in enumerate(self.positions):
                dte_remaining = (pos.expiration - date).days

                # DTE floor FIRST (priority per lessons.md)
                if self.dte_floor > 0 and dte_remaining <= self.dte_floor:
                    pnl = self._close_position(pos, date, option_data_map, "dte_floor")
                    positions_to_close.append((i, pnl, "dte_floor", date))
                    continue

                # Reprice
                sell_p, sell_found = reprice_option(
                    option_data_map.get(pos.ticker, pd.DataFrame()), date, pos.sell_symbol
                )
                if sell_found:
                    pos.last_known_sell_price = sell_p
                    self.reprice_stats["found"] += 1
                    pos.days_since_reprice = 0
                else:
                    self.reprice_stats["missing"] += 1
                    pos.days_since_reprice += 1
                    sell_p = pos.last_known_sell_price

                buy_p = 0
                if pos.mode == "spread" and pos.buy_symbol:
                    bp, bf = reprice_option(
                        option_data_map.get(pos.ticker, pd.DataFrame()), date, pos.buy_symbol
                    )
                    if bf:
                        pos.last_known_buy_price = bp
                        buy_p = bp
                    else:
                        buy_p = pos.last_known_buy_price

                current_value = sell_p - buy_p if pos.mode == "spread" else sell_p

                # Stale data exit
                if pos.days_since_reprice >= 5:
                    pnl = self._calc_pnl(pos, current_value)
                    positions_to_close.append((i, pnl, "stale_data_exit", date))
                    continue

                # Take profit
                tp_threshold = pos.raw_credit * (1 - self.tp_pct)
                if self.tp_pct < 1.0 and current_value <= tp_threshold:
                    pnl = self._calc_pnl(pos, current_value)
                    positions_to_close.append((i, pnl, "take_profit", date))
                    continue

            # Close positions (reverse order to preserve indices)
            for close_info in sorted(positions_to_close, key=lambda x: x[0], reverse=True):
                idx = close_info[0]
                pos = self.positions[idx]
                pnl = close_info[1]
                reason = close_info[2]
                exit_date = close_info[3]

                self.closed_trades.append(ClosedTrade(
                    ticker=pos.ticker, mode=pos.mode,
                    entry_date=str(pos.entry_date)[:10],
                    exit_date=str(exit_date)[:10],
                    exit_reason=reason,
                    raw_credit=round(pos.raw_credit * 100, 2),
                    pnl=round(pnl, 2),
                    days_held=(exit_date - pos.entry_date).days,
                    sell_strike=pos.sell_strike,
                    buy_strike=pos.buy_strike,
                ))
                realized_today += pnl
                self.positions.pop(idx)

            # 2. Check signals and open new positions
            for ticker in tickers:
                if ticker not in signals_map or ticker not in option_data_map:
                    continue

                sig_df = signals_map[ticker]
                if date not in sig_df.index:
                    continue

                row = sig_df.loc[date]
                if row['signal'] != 'GREEN' or row['vrp'] < self.min_vrp:
                    continue

                # Position limits
                ticker_positions = sum(1 for p in self.positions if p.ticker == ticker)
                if ticker_positions >= self.max_per_ticker:
                    self.skipped_at_limit += 1
                    continue
                if len(self.positions) >= self.max_total:
                    self.skipped_at_limit += 1
                    continue

                # Find spread
                opt_df = option_data_map[ticker]
                puts = get_puts_on_date(opt_df, date)
                if puts.empty:
                    continue

                legs = find_spread_legs(puts, row['close'], self.sell_otm, self.buy_otm,
                                         trade_date=date)
                if legs is None:
                    continue

                raw_credit = legs['credit'] if self.mode == "spread" else legs['sell_price']
                adj_credit = raw_credit * (1 - self.slippage)

                pos = Position(
                    ticker=ticker,
                    entry_date=date,
                    sell_symbol=legs['sell_symbol'],
                    buy_symbol=legs['buy_symbol'] if self.mode == "spread" else None,
                    sell_strike=legs['sell_strike'],
                    buy_strike=legs['buy_strike'] if self.mode == "spread" else 0,
                    entry_credit=adj_credit,
                    raw_credit=raw_credit,
                    expiration=legs['expiration'],
                    dte_at_entry=legs['dte'],
                    mode=self.mode,
                    last_known_sell_price=legs['sell_price'],
                    last_known_buy_price=legs.get('buy_price', 0),
                )
                self.positions.append(pos)

            # FIX: Compute daily P&L as CHANGE in portfolio value, not level
            # Portfolio value = sum of (entry_credit - current_spread_value) for all open positions
            today_portfolio_value = 0.0
            for pos in self.positions:
                cv = pos.last_known_sell_price - pos.last_known_buy_price if pos.mode == "spread" else pos.last_known_sell_price
                today_portfolio_value += (pos.entry_credit - cv) * 100

            # Daily P&L = change in unrealized + realized closings today
            daily_change = (today_portfolio_value - prev_portfolio_value) + realized_today
            prev_portfolio_value = today_portfolio_value

            self.daily_pnl.append((date, daily_change, len(self.positions)))

        # Close remaining positions at end
        for pos in self.positions:
            pnl = self._calc_pnl(pos, pos.last_known_sell_price - pos.last_known_buy_price)
            self.closed_trades.append(ClosedTrade(
                ticker=pos.ticker, mode=pos.mode,
                entry_date=str(pos.entry_date)[:10],
                exit_date=str(all_dates[-1])[:10],
                exit_reason="end_of_data",
                raw_credit=round(pos.raw_credit * 100, 2),
                pnl=round(pnl, 2),
                days_held=(all_dates[-1] - pos.entry_date).days,
                sell_strike=pos.sell_strike,
                buy_strike=pos.buy_strike,
            ))
        self.positions = []

    def _close_position(self, pos, date, option_data_map, reason):
        """Close a position, return realized P&L."""
        current_sell = pos.last_known_sell_price
        current_buy = pos.last_known_buy_price
        current_value = current_sell - current_buy if pos.mode == "spread" else current_sell
        return self._calc_pnl(pos, current_value)

    def _calc_pnl(self, pos, current_value):
        """Calculate P&L for closing a position."""
        close_cost = current_value * (1 + self.slippage)
        return (pos.entry_credit - close_cost) * 100

    def get_portfolio_metrics(self):
        """Compute portfolio-level metrics from daily P&L."""
        if not self.daily_pnl:
            return {"error": "No daily P&L data"}

        dates = [d[0] for d in self.daily_pnl]
        pnls = np.array([d[1] for d in self.daily_pnl])
        n_pos = [d[2] for d in self.daily_pnl]

        # Daily returns as fraction of capital
        daily_returns = pnls / self.capital

        # Annualized Sharpe on daily returns
        sharpe = 0
        if daily_returns.std() > 0:
            sharpe = daily_returns.mean() / daily_returns.std() * np.sqrt(252)

        # Sortino
        downside = daily_returns[daily_returns < 0]
        down_std = downside.std() if len(downside) > 1 else daily_returns.std()
        sortino = daily_returns.mean() / down_std * np.sqrt(252) if down_std > 0 else 0

        # Cumulative P&L and drawdown
        cum_pnl = np.cumsum(pnls)
        peak = np.maximum.accumulate(cum_pnl)
        drawdown = cum_pnl - peak
        max_dd = drawdown.min()
        max_dd_pct = max_dd / self.capital * 100

        # Trade-level stats
        trade_pnls = [t.pnl for t in self.closed_trades]
        n_trades = len(trade_pnls)
        win_rate = sum(1 for p in trade_pnls if p > 0) / n_trades * 100 if n_trades > 0 else 0

        # Repricing quality
        total_reprice = self.reprice_stats["found"] + self.reprice_stats["missing"]
        miss_pct = self.reprice_stats["missing"] / total_reprice * 100 if total_reprice > 0 else 0

        return {
            "n_days": len(pnls),
            "n_trades": n_trades,
            "total_pnl": round(float(cum_pnl[-1]), 2),
            "daily_sharpe": round(float(sharpe), 3),
            "daily_sortino": round(float(sortino), 3),
            "max_dd": round(float(max_dd), 2),
            "max_dd_pct": round(float(max_dd_pct), 2),
            "avg_positions": round(float(np.mean(n_pos)), 1),
            "max_positions": int(max(n_pos)),
            "win_rate": round(win_rate, 1),
            "avg_trade_pnl": round(float(np.mean(trade_pnls)), 2) if trade_pnls else 0,
            "skipped_at_limit": self.skipped_at_limit,
            "reprice_missing_pct": round(miss_pct, 1),
            "exit_reasons": pd.Series([t.exit_reason for t in self.closed_trades]).value_counts().to_dict(),
        }

    def holdout_validate(self, split_pct=0.8):
        """Time-based holdout on daily portfolio returns."""
        if not self.daily_pnl:
            return {"error": "No data"}

        pnls = np.array([d[1] for d in self.daily_pnl])
        daily_returns = pnls / self.capital

        split = int(len(daily_returns) * split_pct)
        train = daily_returns[:split]
        test = daily_returns[split:]

        if len(test) < 50:
            return {"error": f"Only {len(test)} test days (need 50+)"}

        train_sharpe = train.mean() / train.std() * np.sqrt(252) if train.std() > 0 else 0
        test_sharpe = test.mean() / test.std() * np.sqrt(252) if test.std() > 0 else 0
        ratio = test_sharpe / train_sharpe if train_sharpe != 0 else 0

        return {
            "train_days": len(train),
            "test_days": len(test),
            "train_sharpe": round(float(train_sharpe), 3),
            "test_sharpe": round(float(test_sharpe), 3),
            "ratio": round(float(ratio), 3),
            "train_total_pnl": round(float(train.sum() * self.capital), 2),
            "test_total_pnl": round(float(test.sum() * self.capital), 2),
            "passed": ratio > 0.5 and test.mean() > 0,
        }

    def bootstrap(self, n_boot=1000):
        """Bootstrap on daily portfolio returns."""
        if not self.daily_pnl:
            return {"error": "No data"}

        pnls = np.array([d[1] for d in self.daily_pnl])
        daily_returns = pnls / self.capital
        np.random.seed(42)

        boot_sharpes = []
        boot_total_returns = []
        for _ in range(n_boot):
            sample = np.random.choice(daily_returns, size=len(daily_returns), replace=True)
            if sample.std() > 0:
                boot_sharpes.append(sample.mean() / sample.std() * np.sqrt(252))
            boot_total_returns.append(sample.sum())

        return {
            "sharpe_ci_lower": round(float(np.percentile(boot_sharpes, 2.5)), 3) if boot_sharpes else 0,
            "sharpe_ci_upper": round(float(np.percentile(boot_sharpes, 97.5)), 3) if boot_sharpes else 0,
            "return_ci_lower": round(float(np.percentile(boot_total_returns, 2.5) * self.capital), 2),
            "return_ci_upper": round(float(np.percentile(boot_total_returns, 97.5) * self.capital), 2),
            "prob_negative_return": round(float(np.mean([r < 0 for r in boot_total_returns]) * 100), 1),
            "prob_sharpe_below_zero": round(float(np.mean([s < 0 for s in boot_sharpes]) * 100), 1) if boot_sharpes else 100,
        }
