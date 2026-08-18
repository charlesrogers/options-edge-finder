"""
Phase 3 additions on top of experiments/cc_sim.py.

cc_sim is the engine (real Databento prices, real ex-div dates, correct `as_of`
clock, one independent cohort per trading day). It is deliberately not modified
here — Phase 3 only needs two things it does not provide:

1. **An entry gate for the H22 backwardation guard**, in cc_sim's gate shape.
2. **A daily equity curve**, because H23 is scored on "return per unit of worst
   drawdown" and that is undefined on a bare trade list.

Assignment convention, inherited from cc_sim and stated because it matters for
the equity curve: an assignment is settled as "pay the intrinsic value, keep the
shares", which is economically identical to being called away and repurchasing
at the same close. Return and drawdown are therefore unaffected by assignment
*accounting*; the tax event is what makes assignment catastrophic in production,
and assignments are counted and reported separately rather than priced in.
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import cc_sim

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_cache')


# ============================================================
# H22 GUARD — as a cc_sim entry gate
# ============================================================

def load_vix_term_structure(start='2019-01-01', end='2026-08-16'):
    """Daily ^VIX and ^VIX3M closes. Free CBOE data, cached to parquet."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f'vix_term_{start}_{end}.parquet')
    if os.path.exists(path):
        return pd.read_parquet(path)

    import yfinance as yf
    df = yf.download(['^VIX', '^VIX3M'], start=start, end=end,
                     progress=False, auto_adjust=False)['Close'].dropna()
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    df = df.rename(columns={'^VIX': 'VIX', '^VIX3M': 'VIX3M'})
    df.to_parquet(path)
    return df


def load_long_stock(ticker, start='2019-01-01', end='2026-08-16'):
    """
    Daily closes over an explicit long window, cached.

    cc_sim.load_stock() asks the proxy for period='5y', which is right for the
    option-data window but starts in 2021-08 — too late to score a full 2021
    calendar year. The calm control needs whole years, so it loads its own.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f'{ticker}_stock_{start}_{end}.parquet')
    if os.path.exists(path):
        s = pd.read_parquet(path)['Close']
    else:
        import yfinance as yf
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if df.empty:
            raise RuntimeError(f'No stock history for {ticker} {start}..{end}')
        df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
        df.to_parquet(path)
        s = df['Close']
    return s[~s.index.duplicated(keep='last')].sort_index()


def blocked_entry_stats(baseline_trades, arm_trades, contracts=1):
    """
    What did the gate actually throw away?

    A gate never changes a trade it allows, so a paired per-entry comparison is
    identically zero and says nothing. The question that matters is whether the
    entries it removed were good ones: report the count and the mean/median P&L
    of the baseline trades the arm no longer takes.
    """
    kept = {t.entry_date for t in arm_trades}
    blocked = [t for t in baseline_trades if t.entry_date not in kept]
    if not blocked:
        return {'n_blocked': 0}
    pnl = np.array([t.pnl_per_share for t in blocked]) * 100 * contracts
    return {
        'n_blocked': len(blocked),
        'blocked_mean_pnl': round(float(pnl.mean()), 2),
        'blocked_median_pnl': round(float(np.median(pnl)), 2),
        'blocked_total_pnl': round(float(pnl.sum()), 2),
        'blocked_winners': int((pnl > 0).sum()),
        'blocked_losers': int((pnl < 0).sum()),
    }


def backwardation_gate(vix_df, drawdown_pct=0.15, high_lookback=60,
                       use_backwardation=True, use_drawdown=True):
    """
    H22's guard, in cc_sim's gate shape: gate(chain, date, spot) -> (allow, why).

    Blocks a NEW entry when VIX > VIX3M (term structure in backwardation) or the
    stock trades more than `drawdown_pct` below its trailing `high_lookback`-day
    high. Both numbers are ARBITRARY STARTING VALUES from the spec.

    Only data at or before `date` is ever read — a gate that peeks would make
    the walk-forward split meaningless.
    """
    back = (vix_df['VIX'] > vix_df['VIX3M'])
    highs = {}

    def gate(chain, date, spot):
        if use_backwardation:
            prior = back.loc[:date]
            if len(prior) and bool(prior.iloc[-1]):
                return False, 'backwardation'
        if use_drawdown:
            key = id(chain)
            if key not in highs:
                highs[key] = chain.stock.rolling(high_lookback, min_periods=10).max()
            h = highs[key].loc[:date]
            c = chain.stock.loc[:date]
            if len(h) and len(c) and pd.notna(h.iloc[-1]):
                if float(c.iloc[-1]) < float(h.iloc[-1]) * (1 - drawdown_pct):
                    return False, 'drawdown'
        return True, ''

    legs = []
    if use_backwardation:
        legs.append('back')
    if use_drawdown:
        legs.append(f'dd{int(drawdown_pct * 100)}')
    gate.label = 'guard_' + '_'.join(legs) if legs else 'guard_none'
    return gate


def and_gates(*gates):
    """Allow an entry only if every gate allows it. Reports the first blocker."""
    def gate(chain, date, spot):
        for g in gates:
            ok, why = g(chain, date, spot)
            if not ok:
                return False, why
        return True, ''
    gate.label = '+'.join(getattr(g, 'label', '?') for g in gates)
    return gate


def gate_entry_dates(chain, gate):
    """Every option day the gate would allow an entry on. Used by the controls."""
    out = []
    for date in chain.option_days:
        spot = chain.spot(date)
        if spot is None:
            continue
        ok, _ = gate(chain, date, spot)
        if ok:
            out.append(date)
    return out


# ============================================================
# SEQUENTIAL CHAINS — one real portfolio path out of the cohort set
# ============================================================

def sequential_chain(trades, start_idx=0):
    """
    Turn cc_sim's independent-cohort trade list into ONE portfolio path.

    cc_sim opens a cohort on every eligible day; a real account holding 100
    shares can only have one call open at a time. Starting from the
    `start_idx`-th entry date, take that trade, then the next trade whose entry
    is on or after the previous exit, and so on.

    `start_idx` is the stagger: the same rules starting a fortnight later are a
    different path, and with ~12 trades a year the difference between paths is
    larger than the difference between the configurations under test.
    """
    ordered = sorted(trades, key=lambda t: t.entry_date)
    if start_idx >= len(ordered):
        return []
    chain, i = [], start_idx
    while i < len(ordered):
        t = ordered[i]
        chain.append(t)
        j = i + 1
        while j < len(ordered) and ordered[j].entry_date < t.exit_date:
            j += 1
        i = j
    return chain


# ============================================================
# EQUITY CURVE
# ============================================================

def equity_curve(chain_data, trade_chain, shares, contracts,
                 start_date=None, end_date=None):
    """
    Daily portfolio value = stock mark-to-market + the call overlay.

    overlay(t) = contracts x 100 x (realised P&L to date + unrealised on the
    open position). Changing the overwrite ratio scales `contracts` and nothing
    else — the stock leg is identical across ratios, which is exactly what
    partial overwriting does and is why the ratio can only move the curve by the
    size of the overlay.

    Missing daily prices carry the last known price forward, as in cc_sim, and
    are counted by the caller via cc_sim's diagnostics.
    """
    days = chain_data.option_days
    if start_date is not None:
        days = [d for d in days if d >= pd.Timestamp(start_date)]
    if end_date is not None:
        days = [d for d in days if d <= pd.Timestamp(end_date)]

    by_entry = {}
    for t in trade_chain:
        by_entry.setdefault(t.entry_date, []).append(t)

    realised = 0.0
    open_trade = None
    last_px = 0.0
    values, index = [], []

    for date in days:
        spot = chain_data.spot(date)
        if spot is None:
            continue
        key = str(date)[:10]

        if open_trade is None and key in by_entry:
            open_trade = by_entry[key][0]
            last_px = open_trade.premium

        unrealised = 0.0
        if open_trade is not None:
            px = chain_data.price.get((open_trade.symbol, date))
            if px is not None:
                last_px = float(px)
            if key >= open_trade.exit_date:
                realised += open_trade.pnl_per_share
                open_trade = None
            else:
                unrealised = open_trade.premium - last_px

        values.append(spot * shares + (realised + unrealised) * 100.0 * contracts)
        index.append(date)

    return pd.Series(values, index=pd.DatetimeIndex(index))


def drawdown_pct(equity):
    """Worst peak-to-trough decline of an equity curve, as a positive percent."""
    if len(equity) == 0:
        return 0.0
    peak = equity.cummax()
    return float(((equity - peak) / peak).min() * -100.0)


def curve_stats(equity, trade_chain, shares, contracts):
    """Return/drawdown plus the income and friction numbers H23 reports."""
    if len(equity) < 2:
        return None
    start, end = float(equity.iloc[0]), float(equity.iloc[-1])
    ret = (end - start) / start * 100.0
    dd = drawdown_pct(equity)
    gross = sum(t.premium for t in trade_chain) * 100 * contracts
    buyback = sum(t.buyback for t in trade_chain) * 100 * contracts
    net = sum(t.pnl_per_share for t in trade_chain) * 100 * contracts
    return {
        'contracts': contracts,
        'total_return_pct': round(ret, 4),
        'max_drawdown_pct': round(dd, 4),
        'return_over_drawdown': round(ret / dd, 4) if dd > 0 else None,
        'net_income': round(net, 2),
        'gross_premium': round(gross, 2),
        'buyback_cost': round(buyback, 2),
        'retention_pct': round(net / gross * 100, 2) if gross else None,
        'n_trades': len(trade_chain),
        'assignments': sum(1 for t in trade_chain if t.assigned),
        'worst_trade': round(min((t.pnl_per_share for t in trade_chain), default=0)
                             * 100 * contracts, 2),
        'loss_rate_pct': round(sum(1 for t in trade_chain if t.pnl_per_share < 0)
                               / len(trade_chain) * 100, 1) if trade_chain else None,
    }


def median_of(rows, key):
    vals = [r[key] for r in rows if r and r.get(key) is not None]
    return round(float(np.median(vals)), 4) if vals else None
