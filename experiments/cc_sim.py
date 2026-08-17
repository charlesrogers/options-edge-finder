"""
Covered-call cohort simulator — shared engine for Experiments 015-018.

Why this exists instead of reusing experiments/007_copilot_simulator/run.py:

1. **DTE was always 0.** `assess_position()` measured DTE against the wall
   clock, so every historical observation in Exp 007-013 evaluated at 0 DTE.
   Every DTE-conditional alert rule was unreachable. Fixed by passing `as_of`
   (commit 8040440); this engine always passes it.

2. **Ex-dividend was always None.** Exp 007-013 passed `ex_div_date=None`, so
   the EMERGENCY rule and both ex-div CLOSE rules never fired in any backtest.
   This engine loads real historical ex-div dates and amounts.

3. **Assignment was inferred, not simulated.** Exp 008/009 counted an
   assignment as "finished ITM at expiry and the copilot did not fire" — which
   credits the copilot for closes it made for unrelated reasons and cannot see
   early exercise at all. This engine carries positions forward and assigns
   them: early (rational exercise into a dividend, Natenberg Ch. 12) or at
   expiry.

4. **Entry was chained on an arbitrary 25-day interval**, which subsamples the
   entry calendar — the survivorship bias documented in tasks/lessons.md
   (2026-03-23, "40 trades from 336 GREEN days"). This engine evaluates every
   trading day as an independent cohort. Overlapping cohorts are NOT
   independent observations; policy comparisons here are paired (identical
   entry set, identical price paths) and must be read that way.

Real Databento OPRA prices only. No BSM anywhere in the P&L path.

Conventions, stated so results are comparable:
  - CLOSE_NOW / EMERGENCY  -> close at today's close.
  - CLOSE_SOON             -> close within `close_soon_days` calendar days.
                              Default 5, taken from the alert's own wording
                              ("Close this week"), not invented here. Applied
                              identically to every policy arm.
  - Slippage defaults to 0, matching the Exp 007-009 convention so baselines
    are comparable. Runners report a slippage sensitivity separately.
  - A missing daily price carries the last known price forward and is counted.
    Nothing is ever silently skipped (tasks/lessons.md 2026-03-23).
"""

import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd

from position_monitor import assess_position, lookup_itm_probability

RAW_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'databento', 'raw')
CACHE_DIR = os.path.join(os.path.dirname(__file__), '_cache')

# Tickers with enough Databento option history to backtest on real prices.
# Measured 2026-08-16 — see experiments/015_probability_buybacks/README.md.
USABLE_TICKERS = ['AAPL', 'DIS', 'TMUS', 'KKR', 'TXN']
UNUSABLE_TICKERS = {
    'GOOGL': 'only 5 trading days of Databento option data (2026-03-16..20)',
    'AMZN': 'no Databento option data was ever purchased',
}


# ============================================================
# DATA
# ============================================================

@dataclass
class ChainData:
    """Everything one ticker's simulation needs, loaded once."""
    ticker: str
    by_date: dict            # date (Timestamp, naive, normalised) -> DataFrame[symbol, strike, exp, close]
    price: dict              # (symbol, date) -> close
    option_days: list        # sorted list of dates with option data
    stock: pd.Series         # Close indexed by naive normalised date
    dividends: list          # [(date, amount)] sorted
    iv_rank: dict            # 'YYYY-MM-DD' -> percentile 0-100
    trend: pd.DataFrame = None   # trend features indexed by date (Exp 016)

    spot_gaps: list = field(default_factory=list)   # dates with no same-day close

    def spot(self, date):
        """Stock close on `date`. None if that day has no close.

        This used to fall back to the NEXT available trading day, which every
        caller consumes at decision time — strike selection, the daily policy
        evaluation, expiry settlement, the IV-rank ATM normalisation. That turns
        a data gap into look-ahead. Verified never to have fired on the
        committed caches (0 of 1,757 option days across the 5 tickers are
        missing a same-day close), so no published result depended on it, but
        a gap must surface as missing data rather than as tomorrow's price.
        """
        if date in self.stock.index:
            return float(self.stock.loc[date])
        self.spot_gaps.append(date)
        return None

    def next_exdiv(self, date):
        """Next ex-dividend (date, amount) on or after `date`, or (None, None)."""
        for d, amt in self.dividends:
            if d >= date:
                return d, amt
        return None, None


def _cache_path(name):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, name)


def load_calls(ticker):
    """Parse Databento OHLCV into a tidy call table. Cached to parquet."""
    cache = _cache_path(f'{ticker}_calls.parquet')
    if os.path.exists(cache):
        return pd.read_parquet(cache)

    import databento as db
    files = sorted(f for f in os.listdir(RAW_DIR)
                   if f.startswith(f'{ticker}_ohlcv') and f.endswith('.dbn.zst'))
    if not files:
        raise FileNotFoundError(f'No Databento OHLCV for {ticker} in {RAW_DIR}')

    print(f'    [{ticker}] parsing {len(files)} Databento file(s)...', flush=True)
    frames = [db.DBNStore.from_file(os.path.join(RAW_DIR, f)).to_df() for f in files]
    raw = pd.concat(frames)
    raw = raw.reset_index().drop_duplicates()

    raw['symbol'] = raw['symbol'].astype(str)
    # Parse once per distinct symbol, not once per row (millions of rows).
    uniq = pd.DataFrame({'symbol': raw['symbol'].unique()})
    ext = uniq['symbol'].str.extract(r'(\d{6})C(\d{8})\s*$')
    uniq['expiration'] = pd.to_datetime('20' + ext[0], format='%Y%m%d', errors='coerce')
    uniq['strike'] = pd.to_numeric(ext[1], errors='coerce') / 1000.0
    uniq = uniq.dropna(subset=['expiration', 'strike'])

    calls = raw.merge(uniq, on='symbol', how='inner')
    calls['date'] = pd.to_datetime(calls['ts_event']).dt.tz_localize(None).dt.normalize()
    calls = (calls.groupby(['date', 'symbol', 'strike', 'expiration'], as_index=False)
                  .agg(close=('close', 'mean'), volume=('volume', 'sum')))
    calls = calls[calls['close'] > 0]

    calls.to_parquet(cache, index=False)
    print(f'    [{ticker}] {len(calls):,} call-days cached', flush=True)
    return calls


def load_dividends(ticker):
    """Historical ex-dividend dates and amounts. Cached to JSON."""
    cache = _cache_path(f'{ticker}_dividends.json')
    if os.path.exists(cache):
        with open(cache) as f:
            return [(pd.Timestamp(d), float(a)) for d, a in json.load(f)]

    import yfinance as yf
    series = yf.Ticker(ticker).dividends
    rows = [(str(d)[:10], float(a)) for d, a in series.items()]
    with open(cache, 'w') as f:
        json.dump(rows, f, indent=1)
    return [(pd.Timestamp(d), a) for d, a in rows]


def load_stock(ticker, period='5y'):
    """Daily stock closes via the Cloudflare Worker proxy. Cached to parquet."""
    cache = _cache_path(f'{ticker}_stock.parquet')
    if os.path.exists(cache):
        df = pd.read_parquet(cache)
    else:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        import yf_proxy
        df = yf_proxy.get_stock_history(ticker, period=period)
        if df.empty:
            raise RuntimeError(f'No stock history for {ticker}')
        df.to_parquet(cache)
    s = df['Close'].copy()
    s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
    return s[~s.index.duplicated(keep='last')].sort_index()


def compute_iv_rank(calls, stock):
    """IV rank exactly as Experiment 009 defined it, so the production entry
    gate is reproduced rather than reinvented: ATM call price as a percentage
    of spot, ranked against its own trailing 60 observations.

    This is a *proxy*, not an implied vol. It is what production uses, so it is
    what the backtest must use.
    """
    proxy = {}
    skipped = {'no_spot': 0, 'no_dte_band': 0}
    for date, day in calls.groupby('date'):
        # Same-day close only — no next-day fallback, which would be look-ahead.
        spot = float(stock.loc[date]) if date in stock.index else None
        if not spot:
            skipped['no_spot'] += 1
            continue
        dte = (day['expiration'] - date).dt.days
        band = day[(dte >= 20) & (dte <= 45)]
        if band.empty:
            skipped['no_dte_band'] += 1
            continue
        atm = band.iloc[(band['strike'] - spot).abs().argmin()]
        proxy[date] = float(atm['close']) / spot * 100

    series = pd.Series(proxy).sort_index()
    ranks = {}
    for i, (date, val) in enumerate(series.items()):
        window = series.iloc[max(0, i - 60):i + 1]
        if len(window) < 10:
            # Not enough history to rank. This used to return a hardcoded 50.0,
            # which passes the `>= 50` production gate — so the first ~10 days of
            # every ticker entered unconditionally on a fabricated rank, and
            # were counted as if the gate had approved them. Return None instead
            # and let the gate report it as missing data.
            ranks[str(date)[:10]] = None
            continue
        ranks[str(date)[:10]] = (window < val).sum() / len(window) * 100

    if any(skipped.values()):
        print(f'    [iv_rank] {skipped["no_spot"]} days without a same-day stock '
              f'close, {skipped["no_dte_band"]} without a 20-45 DTE contract '
              f'— no rank computed for those days', flush=True)
    return ranks


def compute_trend_features(stock):
    """Momentum / persistence features for the H18 trend gate.

    Every value at date d uses only closes up to and including d. The
    autocorrelation percentile is an EXPANDING rank, not a full-sample rank —
    a full-sample rank would leak the future into the gate and make any
    walk-forward split meaningless.
    """
    close = stock.astype(float)
    rets = close.pct_change()
    ac = rets.rolling(252).apply(lambda w: pd.Series(w).autocorr(lag=1), raw=True)
    return pd.DataFrame({
        'r20': close / close.shift(20) - 1,
        'r60': close / close.shift(60) - 1,
        'autocorr252': ac,
        'autocorr_pct': ac.expanding(min_periods=60).rank(pct=True) * 100,
    })


def load_ticker(ticker, verbose=True):
    """Load everything for one ticker. Expensive; call once, reuse."""
    if ticker in UNUSABLE_TICKERS:
        raise ValueError(f'{ticker} is not backtestable: {UNUSABLE_TICKERS[ticker]}')
    if verbose:
        print(f'  Loading {ticker}...', flush=True)

    calls = load_calls(ticker)
    stock = load_stock(ticker)
    divs = sorted(load_dividends(ticker))

    by_date = {d: g for d, g in calls.groupby('date')}
    price = calls.set_index(['symbol', 'date'])['close'].to_dict()
    option_days = sorted(by_date)
    iv_rank = compute_iv_rank(calls, stock)

    if verbose:
        print(f'    {ticker}: {len(option_days)} option days '
              f'{str(option_days[0])[:10]} -> {str(option_days[-1])[:10]}, '
              f'{len(price):,} priced call-days, '
              f'{len([d for d, _ in divs if option_days[0] <= d <= option_days[-1]])} '
              f'ex-div dates in window', flush=True)

    return ChainData(ticker=ticker, by_date=by_date, price=price,
                     option_days=option_days, stock=stock, dividends=divs,
                     iv_rank=iv_rank, trend=compute_trend_features(stock))


# ============================================================
# ENTRY
# ============================================================

def find_call(chain, date, spot, otm_pct, min_dte, max_dte, target_dte=30):
    """Pick the call to sell: nearest expiry to `target_dte` inside the DTE
    band, then the strike nearest `spot * (1 + otm_pct)`."""
    day = chain.by_date.get(date)
    if day is None or day.empty:
        return None
    dte = (day['expiration'] - date).dt.days
    band = day[(dte >= min_dte) & (dte <= max_dte)].copy()
    if band.empty:
        return None
    band['dte'] = (band['expiration'] - date).dt.days
    best_exp = band.loc[(band['dte'] - target_dte).abs().idxmin(), 'expiration']
    exp_calls = band[band['expiration'] == best_exp]
    target = spot * (1 + otm_pct)
    row = exp_calls.loc[(exp_calls['strike'] - target).abs().idxmin()]
    return {
        'symbol': str(row['symbol']),
        'strike': float(row['strike']),
        'price': float(row['close']),
        'expiration': row['expiration'],
        'dte': int(row['dte']),
    }


# ============================================================
# EXIT POLICIES
# ============================================================

@dataclass
class DayContext:
    """What a policy sees on one day of one open position."""
    ticker: str
    date: pd.Timestamp
    spot: float
    strike: float
    option_price: float
    sold_price: float
    dte: int
    days_to_exdiv: int      # None when no dividend ahead
    dividend: float         # amount of that dividend, None when no dividend ahead
    expiration: pd.Timestamp
    price_is_stale: bool

    @property
    def pct_from_strike(self):
        return (self.strike - self.spot) / self.spot * 100

    @property
    def is_itm(self):
        return self.spot > self.strike

    @property
    def intrinsic(self):
        return max(0.0, self.spot - self.strike)

    @property
    def extrinsic(self):
        return max(0.0, self.option_price - self.intrinsic)


HOLD, CLOSE_SOON, CLOSE_NOW = 'HOLD', 'CLOSE_SOON', 'CLOSE_NOW'


def baseline_policy(ctx):
    """The current production copilot, evaluated correctly.

    Same rules as the live app, but with a real `as_of` and a real ex-dividend
    date — which no previous backtest supplied.
    """
    alert = assess_position(
        ticker=ctx.ticker, strike=ctx.strike, expiry=ctx.expiration,
        sold_price=ctx.sold_price, contracts=1, current_stock=ctx.spot,
        current_option_ask=ctx.option_price,
        ex_div_date=(ctx.date + timedelta(days=ctx.days_to_exdiv)
                     if ctx.days_to_exdiv is not None else None),
        earnings_date=None,
        as_of=ctx.date,
    )
    if alert.level in ('CLOSE_NOW', 'EMERGENCY'):
        return CLOSE_NOW, alert.level
    if alert.level == 'CLOSE_SOON':
        return CLOSE_SOON, alert.level
    return HOLD, alert.level


def make_probability_policy(close_soon_p, close_now_p):
    """Exit on empirical P(assignment) instead of on distance to strike.

    EMERGENCY is deliberately untouched — it is the ex-dividend catastrophe
    rule and is out of scope for H17 (that is H19, shadow mode only).
    """
    def policy(ctx):
        if ctx.is_itm and ctx.days_to_exdiv is not None and ctx.days_to_exdiv <= 3:
            return CLOSE_NOW, 'EMERGENCY'
        p = lookup_itm_probability(ctx.pct_from_strike, ctx.dte)
        if p > close_now_p:
            return CLOSE_NOW, f'P={p:.0%}>CN'
        if p > close_soon_p:
            return CLOSE_SOON, f'P={p:.0%}>CS'
        return HOLD, f'P={p:.0%}'
    policy.label = f'prob_cs{int(close_soon_p*100)}_cn{int(close_now_p*100)}'
    return policy


# ============================================================
# ONE COHORT
# ============================================================

@dataclass
class Trade:
    ticker: str
    entry_date: str
    exit_date: str
    symbol: str
    strike: float
    expiration: str
    dte_at_entry: int
    entry_spot: float
    exit_spot: float
    premium: float          # per share, gross
    buyback: float          # per share, cost to close (0 if expired worthless)
    pnl_per_share: float
    exit_reason: str
    assigned: bool
    assignment_type: str    # '', 'early_exdiv', 'expiry'
    days_held: int
    missing_price_days: int
    priced_days: int
    verdict_at_exit: str
    # True when the buyback was filled at a carried-forward price because the
    # contract did not trade on the exit date. The exit fill is the single
    # number that sets P&L, so a stale one means this trade's P&L is synthetic.
    # Counting missing days across the position is not enough — the exit day is
    # the one that matters.
    exit_price_is_stale: bool = False
    n_rolls: int = 0


def run_cohort(chain, entry_date, cfg, policy):
    """Open one position on `entry_date` and carry it to its exit.

    Returns (Trade, reason_if_no_trade).
    """
    cfg = {**DEFAULT_CFG, **cfg}   # callable directly, not only via run()
    spot = chain.spot(entry_date)
    if spot is None:
        return None, 'no_spot'

    call = find_call(chain, entry_date, spot, cfg['otm_pct'],
                     cfg['min_dte'], cfg['max_dte'])
    if call is None:
        return None, 'no_call'
    if call['price'] <= 0:
        return None, 'no_premium'
    # An entry whose expiry falls outside the option-data window can never be
    # settled. Counting it would silently mix truncated trades into the P&L.
    if call['expiration'] > chain.option_days[-1]:
        return None, 'expiry_beyond_data'

    symbol = call['symbol']
    strike = call['strike']
    expiration = call['expiration']
    premium = call['price']

    last_price = premium
    missing = 0
    priced = 0
    close_soon_armed_on = None

    days = [d for d in chain.option_days if entry_date < d <= expiration]

    def settle(date, buyback, reason, assigned, atype, verdict, exit_spot,
               fill_is_stale=False):
        return Trade(
            ticker=chain.ticker, entry_date=str(entry_date)[:10],
            exit_date=str(date)[:10], symbol=symbol, strike=strike,
            expiration=str(expiration)[:10], dte_at_entry=call['dte'],
            entry_spot=round(spot, 2), exit_spot=round(exit_spot, 2),
            premium=round(premium, 4), buyback=round(buyback, 4),
            pnl_per_share=round(premium - buyback, 4), exit_reason=reason,
            assigned=assigned, assignment_type=atype,
            days_held=(date - entry_date).days,
            missing_price_days=missing, priced_days=priced,
            verdict_at_exit=verdict, exit_price_is_stale=fill_is_stale,
        )

    unpriced_stock_days = 0
    for date in days:
        day_spot = chain.spot(date)
        if day_spot is None:
            # No stock close: the position cannot be evaluated OR settled today.
            # Counted, never silent (tasks/lessons.md 2026-03-23).
            unpriced_stock_days += 1
            continue

        px = chain.price.get((symbol, date))
        if px is None:
            missing += 1
            stale = True
            px = last_price
        else:
            priced += 1
            stale = False
            last_price = px

        dte = (expiration - date).days
        exdiv_date, div_amt = chain.next_exdiv(date)
        # A dividend after this call expires cannot cause it to be exercised.
        if exdiv_date is not None and exdiv_date > expiration:
            exdiv_date, div_amt = None, None
        days_to_exdiv = (exdiv_date - date).days if exdiv_date is not None else None

        ctx = DayContext(
            ticker=chain.ticker, date=date, spot=day_spot, strike=strike,
            option_price=px, sold_price=premium, dte=dte,
            days_to_exdiv=days_to_exdiv, dividend=div_amt,
            expiration=expiration, price_is_stale=stale,
        )

        # --- expiry settlement ---
        if dte <= 0:
            if day_spot > strike:
                return settle(date, day_spot - strike, 'expiry_assigned',
                              True, 'expiry', 'EXPIRY', day_spot), None
            return settle(date, 0.0, 'expiry_worthless', False, '',
                          'EXPIRY', day_spot), None

        # --- the copilot gets to act first ---
        action, verdict = policy(ctx)

        if action == CLOSE_NOW:
            return settle(date, px * (1 + cfg['slippage']), 'policy_close_now',
                          False, '', verdict, day_spot, fill_is_stale=stale), None

        if action == CLOSE_SOON:
            if close_soon_armed_on is None:
                close_soon_armed_on = date
            if (date - close_soon_armed_on).days >= cfg['close_soon_days']:
                return settle(date, px * (1 + cfg['slippage']),
                              'policy_close_soon', False, '', verdict, day_spot,
                              fill_is_stale=stale), None
        elif not cfg['close_soon_sticky']:
            close_soon_armed_on = None

        # --- rational early exercise into the dividend (Natenberg Ch. 12) ---
        # Checked after the policy, because the alert fires in the morning and
        # exercise is decided at the close of the day before the ex-date.
        if (days_to_exdiv is not None and days_to_exdiv <= 1
                and ctx.is_itm and div_amt is not None
                and ctx.extrinsic < div_amt):
            return settle(date, ctx.intrinsic, 'early_exercise', True,
                          'early_exdiv', verdict, day_spot), None

    # Ran out of option data before expiry.
    final_date = days[-1] if days else entry_date
    final_spot = chain.spot(final_date) or spot
    return settle(final_date, last_price * (1 + cfg['slippage']),
                  'data_ended', False, '', 'NO_DATA', final_spot,
                  fill_is_stale=True), None


# ============================================================
# ENTRY GATES
# ============================================================

def iv_rank_gate(min_rank=50):
    """Production entry rule from Experiment 009."""
    def gate(chain, date, spot):
        rank = chain.iv_rank.get(str(date)[:10])
        if rank is None:
            return False, 'no_iv_rank'
        return (rank >= min_rank), f'iv_rank={rank:.0f}'
    gate.label = f'iv{min_rank}'
    return gate


def no_gate():
    def gate(chain, date, spot):
        return True, ''
    gate.label = 'none'
    return gate


def trend_blocks(chain, entry_date, feature, threshold):
    """Would the H18 trend gate suppress an entry on `entry_date`?

    Returns (blocked, value). Missing feature data does NOT block — a gate that
    silently suppresses entries because a rolling window has not filled yet
    would look like a working filter while being a data artefact.
    """
    date = pd.Timestamp(entry_date)
    if chain.trend is None or date not in chain.trend.index:
        return False, None
    val = chain.trend.at[date, feature]
    if pd.isna(val):
        return False, None
    return bool(val > threshold), float(val)


# ============================================================
# RUN
# ============================================================

DEFAULT_CFG = {
    'otm_pct': 0.05,
    'min_dte': 20,
    'max_dte': 45,
    'slippage': 0.0,
    'close_soon_days': 5,
    # Once CLOSE_SOON fires, the instruction ("Close this week") stands even if
    # the alert drops back to WATCH the next day — the live app does not un-say
    # it. With sticky=False the clock resets on any non-CLOSE_SOON day, which
    # lets an oscillating position never close on that channel, and does so
    # asymmetrically between arms (the two policies oscillate on different
    # days), so the paired design would not cancel it out.
    'close_soon_sticky': True,
}


def run(chain, cfg, policy, gate=None, progress_every=50, label=''):
    """Run every trading day as an independent cohort.

    Returns (trades, diagnostics).
    """
    cfg = {**DEFAULT_CFG, **cfg}
    gate = gate or no_gate()

    trades = []
    skipped = {}
    n = 0
    for date in chain.option_days:
        n += 1
        if progress_every and n % progress_every == 0:
            print(f'      [{label or chain.ticker}] day {n}/{len(chain.option_days)} '
                  f'({str(date)[:10]}) — {len(trades)} entries', flush=True)

        spot = chain.spot(date)
        if spot is None:
            skipped['no_spot'] = skipped.get('no_spot', 0) + 1
            continue

        ok, why = gate(chain, date, spot)
        if not ok:
            # "the gate rejected this day" and "the gate had no data for this
            # day" are different facts and must not share a counter.
            key = 'gate_no_data' if why in ('no_iv_rank', 'no_trend_data') else 'gate'
            skipped[key] = skipped.get(key, 0) + 1
            continue

        trade, reason = run_cohort(chain, date, cfg, policy)
        if trade is None:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        trades.append(trade)

    diagnostics = {
        'candidate_days': len(chain.option_days),
        'entries': len(trades),
        'skipped': skipped,
        'missing_price_days': sum(t.missing_price_days for t in trades),
        'priced_days': sum(t.priced_days for t in trades),
        # Trades that never saw a single real quote after entry: their whole
        # life was the carried-forward entry price. Reported, never hidden.
        'never_repriced_trades': sum(1 for t in trades if t.priced_days == 0),
        'data_ended_trades': sum(1 for t in trades if t.exit_reason == 'data_ended'),
        'stale_exit_fills': sum(1 for t in trades if t.exit_price_is_stale),
        'stock_price_gaps': len(chain.spot_gaps),
    }
    total_days = diagnostics['missing_price_days'] + diagnostics['priced_days']
    diagnostics['missing_price_pct'] = round(
        diagnostics['missing_price_days'] / total_days * 100, 1) if total_days else 0.0
    return trades, diagnostics


# ============================================================
# SCORING
# ============================================================

def score(trades):
    """Tri-fold scorecard: assignments (hard constraint), net P&L, retention."""
    if not trades:
        return {'n_trades': 0, 'gross_premium': 0.0, 'total_buyback': 0.0,
                'net_pnl': 0.0, 'retention_pct': 0.0, 'assignments': 0,
                'early_assignments': 0, 'expiry_assignments': 0,
                'win_rate': 0.0, 'loss_rate': 0.0, 'worst_trade': 0.0,
                'avg_pnl': 0.0, 'avg_days_held': 0.0, 'buyback_count': 0,
                'held_to_expiry': 0, 'policy_exits': 0, 'stale_fill_exits': 0,
                'stale_fill_pct': 0.0, 'pnl_from_stale_fills': 0.0,
                'pnl_from_real_fills': 0.0}

    gross = sum(t.premium for t in trades) * 100
    buyback = sum(t.buyback for t in trades) * 100
    net = sum(t.pnl_per_share for t in trades) * 100
    wins = sum(1 for t in trades if t.pnl_per_share > 0)
    losses = sum(1 for t in trades if t.pnl_per_share < 0)
    early = sum(1 for t in trades if t.assignment_type == 'early_exdiv')
    expiry = sum(1 for t in trades if t.assignment_type == 'expiry')
    bought_back = sum(1 for t in trades if t.exit_reason.startswith('policy_'))
    expired = sum(1 for t in trades if t.exit_reason.startswith('expiry'))

    # How much of this P&L is real? A policy exit filled at a carried-forward
    # price is a synthetic number. Reported next to the headline so retention
    # can never be quoted without its data quality.
    policy_exits = [t for t in trades if t.exit_reason.startswith('policy_')]
    stale_exits = [t for t in policy_exits if t.exit_price_is_stale]
    real_exits = [t for t in policy_exits if not t.exit_price_is_stale]

    return {
        'n_trades': len(trades),
        'gross_premium': round(gross, 2),
        'total_buyback': round(buyback, 2),
        'net_pnl': round(net, 2),
        'retention_pct': round(net / gross * 100, 1) if gross > 0 else 0.0,
        'policy_exits': len(policy_exits),
        'stale_fill_exits': len(stale_exits),
        'stale_fill_pct': round(len(stale_exits) / len(policy_exits) * 100, 1)
                          if policy_exits else 0.0,
        'pnl_from_stale_fills': round(sum(t.pnl_per_share for t in stale_exits) * 100, 2),
        'pnl_from_real_fills': round(sum(t.pnl_per_share for t in real_exits) * 100, 2),
        'assignments': early + expiry,
        'early_assignments': early,
        'expiry_assignments': expiry,
        'win_rate': round(wins / len(trades) * 100, 1),
        'loss_rate': round(losses / len(trades) * 100, 1),
        'worst_trade': round(min(t.pnl_per_share for t in trades) * 100, 2),
        'avg_pnl': round(net / len(trades), 2),
        'avg_days_held': round(float(np.mean([t.days_held for t in trades])), 1),
        'buyback_count': bought_back,
        'held_to_expiry': expired,
    }


def walk_forward_split(trades, train_frac=0.67):
    """Split by ENTRY date, first `train_frac` train / remainder test.

    Splitting on entry date (not exit date) is what keeps the test period free
    of positions that were opened using train-period information.
    """
    if not trades:
        return [], [], None
    dates = sorted({t.entry_date for t in trades})
    cut = dates[int(len(dates) * train_frac)] if len(dates) > 1 else dates[0]
    train = [t for t in trades if t.entry_date < cut]
    test = [t for t in trades if t.entry_date >= cut]
    return train, test, cut


def paired_difference(a_trades, b_trades):
    """Per-entry P&L difference between two policies over identical entries.

    Cohorts overlap, so trade counts overstate independence. Two policies do
    see the *same* entries though, so the difference is paired: report its mean,
    its sign counts and a t-statistic on the paired deltas, and treat the
    t-statistic as indicative only (overlapping windows are autocorrelated).
    """
    a = {t.entry_date: t for t in a_trades}
    b = {t.entry_date: t for t in b_trades}
    shared = sorted(set(a) & set(b))
    if not shared:
        return {'n_paired': 0}
    deltas = np.array([b[d].pnl_per_share - a[d].pnl_per_share for d in shared]) * 100
    sd = deltas.std(ddof=1) if len(deltas) > 1 else 0.0
    return {
        'n_paired': len(shared),
        'mean_delta': round(float(deltas.mean()), 2),
        'median_delta': round(float(np.median(deltas)), 2),
        'better': int((deltas > 0).sum()),
        'worse': int((deltas < 0).sum()),
        'same': int((deltas == 0).sum()),
        't_stat_indicative': round(float(deltas.mean() / (sd / np.sqrt(len(deltas)))), 2)
                             if sd > 0 else 0.0,
    }


def trades_to_records(trades):
    return [asdict(t) for t in trades]
