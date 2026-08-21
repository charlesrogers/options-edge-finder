"""Decision-moment market data: capture, contract selection, and the liquidity floor.

The rule this module exists to enforce: **a quote captured at 19:50 UTC cannot
price a decision made at 14:22.** The daily chain-capture cron is not a
substitute and this engine never reads it for pricing. Every quote here is
fetched at the tick that used it.

Three failure modes are handled explicitly rather than by omission:

  * `yf_proxy._get` swallows `RequestException` and returns `{}`, so a dead
    proxy and an empty chain are the same value. Probed 2026-08-20 and confirmed.
    Every fetch here returns a `status` that distinguishes them.
  * A quote that arrives as NaN passes an `is None` guard and lands in
    arithmetic as a silent NaN (tasks/lessons.md 2026-08-16). Everything goes
    through `cc_core.is_usable_number`.
  * A missing quote on an open position is carried forward, marked `stale`, and
    counted. Nothing is ever silently skipped.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import cc_core
import yf_proxy

from . import config

# Chain fetch outcomes. 'proxy_failed' and 'empty_chain' are separate values on
# purpose — see the module docstring.
OK = "ok"
PROXY_FAILED = "proxy_failed"
EMPTY_CHAIN = "empty_chain"
NO_EXPIRY_IN_BAND = "no_expiry_in_band"
NO_STRIKE = "no_strike"
CONTRACT_MISSING = "contract_missing"


@dataclass
class Quote:
    """One contract's market at one instant."""
    contract_symbol: str
    ticker: str
    tick_ts: datetime
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    volume: Optional[float] = None
    open_interest: Optional[float] = None
    implied_volatility: Optional[float] = None
    spot: Optional[float] = None
    source_status: str = OK
    stale: bool = False
    stale_from_tick_ts: Optional[datetime] = None

    @property
    def bid_usable(self):
        return cc_core.is_usable_number(self.bid)

    @property
    def ask_usable(self):
        return cc_core.is_usable_number(self.ask)

    @property
    def spot_usable(self):
        return cc_core.is_usable_number(self.spot)

    @property
    def spread(self):
        if self.bid_usable and self.ask_usable:
            return round(self.ask - self.bid, 4)
        return None

    @property
    def crossed(self):
        """A market where the bid exceeds the ask is not a market."""
        return self.bid_usable and self.ask_usable and self.bid > self.ask

    def as_row(self, trading_day):
        return {
            "contract_symbol": self.contract_symbol,
            "tick_ts": self.tick_ts.isoformat(),
            "trading_day": trading_day,
            "ticker": self.ticker,
            "bid": self.bid, "ask": self.ask, "last": self.last,
            "volume": self.volume, "open_interest": self.open_interest,
            "implied_volatility": self.implied_volatility, "spot": self.spot,
            "bid_usable": self.bid_usable, "ask_usable": self.ask_usable,
            "spot_usable": self.spot_usable,
            "source_status": self.source_status,
            "stale": self.stale,
            "stale_from_tick_ts": (self.stale_from_tick_ts.isoformat()
                                   if self.stale_from_tick_ts else None),
        }


@dataclass
class ChainFetch:
    """The result of asking the proxy for one ticker's chain."""
    ticker: str
    status: str
    tick_ts: datetime
    spot: Optional[float] = None
    expiry: Optional[str] = None
    dte: Optional[int] = None
    calls: object = None
    detail: str = ""
    quotes: dict = field(default_factory=dict)   # contract_symbol -> Quote

    @property
    def ok(self):
        return self.status == OK


def _f(value):
    """Coerce to float, or None. Never returns NaN."""
    return float(value) if cc_core.is_usable_number(value, allow_zero=True) else None


def probe_expirations(ticker):
    """Ask for expirations and say WHY the answer was empty if it was."""
    data = yf_proxy._get(f"/stock/{ticker}/options")
    if not data:
        # {} is what a RequestException produces. It is also, in principle,
        # what a genuinely empty response would produce — but the proxy always
        # returns an `expirations` key on success, so an absent key means the
        # request itself did not complete.
        return [], PROXY_FAILED
    exps = data.get("expirations", [])
    if not exps:
        return [], EMPTY_CHAIN
    return exps, OK


def pick_expiry(expirations, as_of_date, min_dte, max_dte, target_dte=30):
    """Nearest expiry to `target_dte` inside the band — cc_sim.find_call's rule.

    Reimplementing this differently from the simulator would mean the forward
    engine and the backtest sell different contracts, which would quietly
    invalidate every comparison between them.
    """
    banded = []
    for e in expirations:
        try:
            dte = (datetime.strptime(e, "%Y-%m-%d").date() - as_of_date).days
        except (ValueError, TypeError):
            continue
        if min_dte <= dte <= max_dte:
            banded.append((abs(dte - target_dte), dte, e))
    if not banded:
        return None, None
    _, dte, expiry = sorted(banded)[0]
    return expiry, dte


def pick_strike(calls, spot, otm_pct):
    """Strike nearest `spot * (1 + otm_pct)` — cc_sim.find_call's rule."""
    if calls is None or calls.empty:
        return None
    target = spot * (1 + otm_pct)
    usable = calls[calls["strike"].apply(lambda s: cc_core.is_usable_number(s))]
    if usable.empty:
        return None
    return usable.iloc[(usable["strike"].astype(float) - target).abs().argmin()]


def fetch_chain(ticker, tick_ts, otm_pct, min_dte, max_dte, target_dte=30):
    """Capture the decision-moment market for one ticker.

    Contract selection runs here, BEFORE any gate is evaluated, so a day where
    arm A is blocked by the IV gate and arm C enters still has its contract and
    its quotes on record. Without that, "is the IV gate worth anything" is
    unanswerable after the fact.
    """
    out = ChainFetch(ticker=ticker, status=OK, tick_ts=tick_ts)

    exps, status = probe_expirations(ticker)
    if status != OK:
        out.status = status
        out.detail = f"expirations lookup returned {status}"
        return out

    expiry, dte = pick_expiry(exps, tick_ts.date(), min_dte, max_dte, target_dte)
    if expiry is None:
        out.status = NO_EXPIRY_IN_BAND
        out.detail = f"no expiry in DTE band {min_dte}-{max_dte}; had {len(exps)}"
        return out
    out.expiry, out.dte = expiry, dte

    data = yf_proxy._get(f"/stock/{ticker}/options/{expiry}")
    if not data:
        out.status = PROXY_FAILED
        out.detail = "chain fetch returned {} — request did not complete"
        return out

    spot = _f(data.get("underlyingPrice"))
    out.spot = spot
    calls_data = data.get("calls", [])
    if not calls_data:
        out.status = EMPTY_CHAIN
        out.detail = f"chain for {expiry} has no calls"
        return out

    import pandas as pd
    calls = pd.DataFrame(calls_data)
    out.calls = calls

    if spot is None:
        out.status = NO_STRIKE
        out.detail = "no usable underlying price — cannot select a strike"
        return out

    row = pick_strike(calls, spot, otm_pct)
    if row is None:
        out.status = NO_STRIKE
        out.detail = "no usable strike in chain"
        return out

    out.quotes[str(row.get("contractSymbol"))] = Quote(
        contract_symbol=str(row.get("contractSymbol")),
        ticker=ticker, tick_ts=tick_ts,
        bid=_f(row.get("bid")), ask=_f(row.get("ask")),
        last=_f(row.get("lastPrice")), volume=_f(row.get("volume")),
        open_interest=_f(row.get("openInterest")),
        implied_volatility=_f(row.get("impliedVolatility")),
        spot=spot, source_status=OK)
    out.status = OK
    return out


def quote_for_contract(ticker, contract_symbol, expiry, tick_ts):
    """Fetch one already-chosen contract's current market.

    Used for open positions, whose contract was fixed at entry. A contract that
    has vanished from the chain is `contract_missing` — distinct from an empty
    chain and from a proxy failure, because it means something different: the
    position is real and its market is gone.
    """
    data = yf_proxy._get(f"/stock/{ticker}/options/{expiry}")
    if not data:
        return Quote(contract_symbol=contract_symbol, ticker=ticker,
                     tick_ts=tick_ts, source_status=PROXY_FAILED)
    calls_data = data.get("calls", [])
    if not calls_data:
        return Quote(contract_symbol=contract_symbol, ticker=ticker,
                     tick_ts=tick_ts, source_status=EMPTY_CHAIN,
                     spot=_f(data.get("underlyingPrice")))
    spot = _f(data.get("underlyingPrice"))
    for row in calls_data:
        if str(row.get("contractSymbol")) == contract_symbol:
            return Quote(
                contract_symbol=contract_symbol, ticker=ticker, tick_ts=tick_ts,
                bid=_f(row.get("bid")), ask=_f(row.get("ask")),
                last=_f(row.get("lastPrice")), volume=_f(row.get("volume")),
                open_interest=_f(row.get("openInterest")),
                implied_volatility=_f(row.get("impliedVolatility")),
                spot=spot, source_status=OK)
    return Quote(contract_symbol=contract_symbol, ticker=ticker, tick_ts=tick_ts,
                 spot=spot, source_status=CONTRACT_MISSING)


def carry_forward(previous: Quote, tick_ts):
    """Reuse the last observed quote, marked and traceable.

    A carried-forward quote is not data. It is a placeholder that keeps the
    position evaluable, and every number computed from it is reported in the
    all-fill column only. `stale_from_tick_ts` preserves the trail back to the
    last real print.
    """
    q = Quote(contract_symbol=previous.contract_symbol, ticker=previous.ticker,
              tick_ts=tick_ts, bid=previous.bid, ask=previous.ask,
              last=previous.last, volume=previous.volume,
              open_interest=previous.open_interest,
              implied_volatility=previous.implied_volatility,
              spot=previous.spot, source_status=previous.source_status,
              stale=True)
    q.stale_from_tick_ts = previous.stale_from_tick_ts or previous.tick_ts
    return q


# ------------------------------------------------------------ liquidity floor --

def liquidity_check(quote: Quote):
    """The §5.2 entry floor, evaluated once and shared by every arm.

    This is realism, not caution. Dad cannot sell at a zero bid. KKR's 15%-OTM
    strike trades a median of 3 contracts a day (Exp 021), and on 2026-08-20 its
    market was 0.15 / 0.55 — a round trip costing 2.7x the credit collected.
    An engine that filled that at mid would report a strategy nobody could run.

    Returns (ok: bool, reason: str). The reason is always specific; "no" is not
    an acceptable answer to record.
    """
    if quote.source_status == PROXY_FAILED:
        return False, "proxy_failed"
    if quote.source_status == EMPTY_CHAIN:
        return False, "empty_chain"
    if quote.source_status == CONTRACT_MISSING:
        return False, "contract_missing"
    if not quote.bid_usable:
        return False, "no_bid"
    if not quote.ask_usable:
        return False, "no_ask"
    if quote.crossed:
        return False, "crossed"
    if quote.bid < config.MIN_ENTRY_BID:
        return False, f"bid_below_floor({quote.bid}<{config.MIN_ENTRY_BID})"
    return True, "ok"


# ----------------------------------------------------------------- IV rank ----

def iv_rank_for(ticker, current_iv):
    """IV rank the way the PRODUCTION Sell surface computes it.

    Arm A is "the product as shipped", so it must gate on the number the
    product actually shows: `db.get_real_iv_rank` from recorded ATM-IV history
    when there are >= 20 days of it, else the realized-vol proxy
    (`analytics.get_iv_rank_percentile`). That is the branch structure in
    streamlit_app.py:143-153, reused rather than reimplemented.

    KNOWN PARITY GAP, recorded rather than papered over: `cc_sim.compute_iv_rank`
    uses a THIRD definition (Exp 009's ATM call price as a percentage of spot).
    So the reference table's IV gate and this engine's IV gate are not the same
    function. That does not affect arm A vs arm C — both arms use this
    function, so the paired A-C difference is internally valid — but it does
    mean the forward IV-gate result is not directly comparable to the
    backtest's. Stated in PREREGISTRATION.md, not fixed here: adding a fourth
    definition would make it worse.

    Returns (rank, source, detail).
    """
    if not cc_core.is_usable_number(current_iv):
        return None, "unavailable", "no usable current IV"
    try:
        import db
        real_rank, _pctl, days = db.get_real_iv_rank(ticker, current_iv)
        if real_rank is not None and days >= 20:
            return float(real_rank), "real_iv", f"{days}d recorded IV history"
    except Exception as e:
        # A failed lookup is not a rank of zero and is not silence.
        return None, "error", f"get_real_iv_rank failed: {str(e)[:160]}"

    try:
        import analytics
        hist = yf_proxy.get_stock_history(ticker, period="1y")
        if hist is None or hist.empty:
            return None, "unavailable", "no stock history for the RV proxy"
        rank, _ = analytics.get_iv_rank_percentile(hist, current_iv)
        if rank is None:
            return None, "unavailable", "RV proxy returned no rank"
        return float(rank), "rv_proxy", "realized-vol proxy (<20d recorded IV)"
    except Exception as e:
        return None, "error", f"rv proxy failed: {str(e)[:160]}"
