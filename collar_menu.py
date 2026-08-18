"""
collar_menu.py — Zero-cost collar menu generator (Phase 2, Part D).

Prices per-ticker collar menus off live Yahoo chains via yf_proxy and prints a
markdown table per ticker. This is a CONVERSATION AID, not a monitor and not a
recommendation engine: it prices the menu, it does not pick a row.

Why this exists (tasks/phase2-onboarding-runbook.md, Part D):
    concentrated, low-basis, $10M+ positions + multi-year-high forward rates +
    elevated vol on big names = zero-cost collars at historically attractive
    terms. Our job is to price the menu, not to advise.

What it does, per ticker:
  * Picks the listed expiry nearest ~3 months and ~12 months out.
  * For put floors at 10% / 15% / 20% OTM, finds the call strike that would make
    the collar zero-cost (linear interpolation between listed strikes), then
    reports the nearest ACTUALLY LISTED strike and its ACTUAL net credit/debit.
    Exact zero does not exist on a listed chain and this script never pretends
    it does.
  * Reports max loss %, max gain % and R:R with the net cost rolled into the
    basis (the Moontower formulation), plus the implied vol of each leg.
  * Reports bid/ask per leg, the width, and what the width costs to cross at
    100-lot size — at his size the width IS the cost.

Usage:
    python3 collar_menu.py                          # all held tickers -> stdout
    python3 collar_menu.py --tickers AAPL TMUS
    python3 collar_menu.py --out results/collar_menu.md
    python3 collar_menu.py --json results/collar_menu.json
    python3 collar_menu.py --verify AAPL            # hand-check worksheet

Run it during regular trading hours. Outside RTH Yahoo returns bid=ask=0 on most
contracts and its own impliedVolatility field collapses to powers of two (0.25,
0.125, 0.0625, ...) — solver garbage. The script detects this and says so
loudly rather than printing a menu of fiction.
"""

import argparse
import json
import math
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# yf_proxy pulls in `requests`, which the pure-math half of this module does not
# need. Import it lazily so the economics can be unit-tested (and CI's slim
# dependency set can import this file) without a network stack.
yf_proxy = None


def _yf():
    global yf_proxy
    if yf_proxy is None:
        import yf_proxy as _mod
        yf_proxy = _mod
    return yf_proxy


try:
    from py_vollib.black_scholes_merton.implied_volatility import (
        implied_volatility as _bsm_iv,
    )
    HAVE_VOLLIB = True
except Exception:  # pragma: no cover - py_vollib is in requirements.txt
    HAVE_VOLLIB = False


# ============================================================
# CONFIG
# ============================================================

# Dad's holdings. Same list as daily_chain_capture.CAPTURE_TICKERS; duplicated
# here rather than imported so this script pulls in no db/analytics deps.
HELD_TICKERS = ["AAPL", "TMUS", "KKR", "DIS", "TXN", "GOOGL", "AMZN"]

# Put floors to price, as fraction OTM below spot. From the Part D spec.
PUT_FLOORS = [0.10, 0.15, 0.20]

# Tenors: (label, target days to expiry). "~3 months and ~12 months" per spec.
TENORS = [("~3 month", 91), ("~12 month", 365)]

CONTRACT_MULTIPLIER = 100          # shares per option contract
DEFAULT_SHARES = 10_000            # Part A: 10,000 shares/ticker
DEFAULT_RATE = 0.045               # risk-free rate for the IV solve; matches
                                   # sabr.py's existing r=0.045 default.

# --- Quote-quality flag thresholds ---
# ARBITRARY STARTING VALUES, not derived from any study. They exist only to draw
# the eye to legs worth arguing about; tune them once we've watched a few
# sessions of real quotes. Every underlying number in the table is reported raw
# so a flag never hides the actual figure.
WIDE_PCT_OF_MID = 0.20             # spread wider than 20% of mid -> "wide"
ABSURD_PCT_OF_MID = 0.50           # wider than 50% of mid -> "absurd"
STALE_DAYS = 3                     # last trade older than 3 calendar days
MIN_OI = 100                       # open interest below this -> "thin"

# Fraction of legs that must be two-sided quoted before we trust the run.
QUOTE_HEALTH_FLOOR = 0.60

TAX_CAVEAT = (
    "he discusses it with his tax person (collars on low-basis stock have "
    "tax/straddle-rule implications that are explicitly out of our lane — say "
    "so on the page)"
)


# ============================================================
# SMALL HELPERS
# ============================================================

def _f(x):
    """Coerce to float, mapping None/NaN/blank to None."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def _parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _pct(x, digits=1):
    return "—" if x is None else f"{x * 100:.{digits}f}%"


def _money(x, digits=2):
    if x is None:
        return "—"
    return f"-${abs(x):,.{digits}f}" if x < 0 else f"${x:,.{digits}f}"


def _signed_money(x, digits=2):
    """Net cost: positive = debit (you pay), negative = credit (you receive)."""
    if x is None:
        return "—"
    if x < 0:
        return f"${abs(x):,.{digits}f} cr"
    return f"${x:,.{digits}f} db"


# ============================================================
# LEG QUOTES
# ============================================================

class Leg:
    """One option leg with its quote, its quality flags, and a solved IV."""

    def __init__(self, row, kind, spot, T, r, q, asof):
        self.kind = kind                                  # 'c' or 'p'
        self.symbol = row.get("contractSymbol")
        self.strike = _f(row.get("strike"))
        self.bid = _f(row.get("bid"))
        self.ask = _f(row.get("ask"))
        self.last = _f(row.get("lastPrice"))
        self.volume = _f(row.get("volume")) or 0
        self.oi = _f(row.get("openInterest")) or 0
        self.yahoo_iv = _f(row.get("impliedVolatility"))
        self.last_trade = _parse_dt(row.get("lastTradeDate"))

        bid = self.bid or 0.0
        ask = self.ask or 0.0
        self.quoted = bid > 0 and ask > 0 and ask >= bid
        if self.quoted:
            self.mid = (bid + ask) / 2.0
            self.width = ask - bid
            self.price_source = "mid"
        else:
            # No two-sided market. Fall back to last trade so the row can still
            # be sketched, but the row is stamped INDICATIVE and must not be
            # read as a tradeable price.
            self.mid = self.last if (self.last or 0) > 0 else None
            self.width = None
            self.price_source = "last"

        self.flags = self._quality_flags(asof)
        self.iv = self._solve_iv(spot, T, r, q)

    def _quality_flags(self, asof):
        flags = []
        if (self.bid or 0) <= 0:
            flags.append("no-bid")
        if (self.ask or 0) <= 0:
            flags.append("no-ask")
        if self.quoted and self.mid:
            ratio = self.width / self.mid
            if ratio > ABSURD_PCT_OF_MID:
                flags.append(f"absurd-width {ratio * 100:.0f}%")
            elif ratio > WIDE_PCT_OF_MID:
                flags.append(f"wide {ratio * 100:.0f}%")
        if self.oi < MIN_OI:
            flags.append(f"thin OI {self.oi:.0f}")
        if self.last_trade and asof:
            age = (asof - self.last_trade).days
            if age > STALE_DAYS:
                flags.append(f"stale {age}d")
        return flags

    def _solve_iv(self, spot, T, r, q):
        """
        Implied vol solved from OUR price (the mid), not read off Yahoo.

        Yahoo's impliedVolatility field on this proxy is unusable outside RTH —
        it collapses to exact powers of two (0.25, 0.125, 0.0625, 0.03125 ...),
        which is a bisection solver hitting its floor on a zero-priced quote.
        Solving from the same mid the table quotes also keeps the IV column
        internally consistent with the net cost column.
        """
        if not self.mid or self.mid <= 0 or not spot or T <= 0:
            return None
        intrinsic = (spot - self.strike) if self.kind == "c" else (self.strike - spot)
        if self.mid <= max(intrinsic, 0.0) + 1e-9:
            return None  # at/below intrinsic — no solvable vol
        if HAVE_VOLLIB:
            try:
                return float(_bsm_iv(self.mid, spot, self.strike, T, r, q, self.kind))
            except Exception:
                pass
        return _bisect_iv(self.mid, spot, self.strike, T, r, q, self.kind)

    def cross_cost(self, contracts):
        """Dollars to cross this leg's spread at `contracts` contracts."""
        if self.width is None:
            return None
        return self.width * CONTRACT_MULTIPLIER * contracts

    def to_dict(self):
        return {
            "kind": self.kind,
            "symbol": self.symbol,
            "strike": self.strike,
            "bid": self.bid,
            "ask": self.ask,
            "mid": self.mid,
            "last": self.last,
            "width": self.width,
            "price_source": self.price_source,
            "iv_solved": self.iv,
            "iv_yahoo": self.yahoo_iv,
            "open_interest": self.oi,
            "volume": self.volume,
            "last_trade": self.last_trade.isoformat() if self.last_trade else None,
            "flags": self.flags,
        }


def _norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bsm_price(flag, S, K, T, r, sigma, q):
    if sigma <= 0 or T <= 0:
        fwd = S * math.exp(-q * T) - K * math.exp(-r * T)
        return max(fwd, 0.0) if flag == "c" else max(-fwd, 0.0)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if flag == "c":
        return S * math.exp(-q * T) * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * math.exp(-q * T) * _norm_cdf(-d1)


def _bisect_iv(price, S, K, T, r, q, flag, lo=1e-4, hi=5.0):
    """Fallback IV solver for when py_vollib is unavailable or refuses."""
    if _bsm_price(flag, S, K, T, r, hi, q) < price:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if _bsm_price(flag, S, K, T, r, mid, q) < price:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-6:
            break
    return (lo + hi) / 2.0


# ============================================================
# CHAIN LOADING
# ============================================================

def pick_expiries(ticker, expirations, today, targets):
    """
    For each target DTE, return the listed expiry closest to it.

    Some listed expiries 500 on the proxy, so callers must be able to fall back;
    this returns a ranked candidate list per target rather than a single date.
    """
    dated = []
    for e in expirations:
        try:
            d = datetime.strptime(e, "%Y-%m-%d").date()
        except ValueError:
            continue
        dte = (d - today).days
        if dte > 0:
            dated.append((e, dte))
    out = []
    for label, target in targets:
        ranked = sorted(dated, key=lambda x: abs(x[1] - target))
        out.append((label, target, ranked))
    return out


def load_chain(ticker, expiration):
    """Fetch one chain; return None if the proxy fails or hands back nothing."""
    try:
        chain = _yf().get_option_chain(ticker, expiration)
    except Exception as exc:
        print(f"  [warn] {ticker} {expiration}: {exc}")
        return None
    if chain.calls.empty and chain.puts.empty:
        return None
    return chain


# ============================================================
# COLLAR CONSTRUCTION
# ============================================================

def _rows(df):
    return df.to_dict("records") if df is not None and not df.empty else []


def nearest_strike_leg(legs, target_strike, require_price=True):
    """
    Nearest listed strike to `target_strike`.

    Prefers strikes that actually carry a price — on a sparse chain the literally
    nearest strike is often an unquoted stub, and reporting "no price" while a
    tradeable strike sits one tick away would be a false negative. Falls back to
    the nearest listed strike of any kind so the row can still name the contract
    and be stamped unpriceable.
    """
    candidates = [l for l in legs if l.strike is not None]
    if not candidates:
        return None
    if require_price:
        priced = [l for l in candidates if l.mid and l.mid > 0]
        if priced:
            candidates = priced
    return min(candidates, key=lambda l: abs(l.strike - target_strike))


def interpolate_zero_cost_strike(call_legs, put_premium):
    """
    Find the call strike whose premium equals the put premium.

    Walks OTM call strikes low->high looking for the first adjacent pair that
    brackets `put_premium`, then interpolates linearly in strike. Returns
    (K_star, status) where status is one of:
        'ok'            — bracketed and interpolated
        'below_chain'   — even the lowest OTM call is too cheap to pay for the
                          put; no zero-cost collar exists without selling an ITM
                          call (heavy put skew)
        'above_chain'   — the put is cheaper than the highest listed call, so
                          zero-cost sits beyond the listed strikes
        'unpriceable'   — not enough priced legs to say anything
    """
    priced = [l for l in call_legs if l.mid and l.mid > 0]
    priced.sort(key=lambda l: l.strike)
    if len(priced) < 2:
        return None, "unpriceable"
    if priced[0].mid < put_premium:
        return None, "below_chain"
    for a, b in zip(priced, priced[1:]):
        if a.mid >= put_premium >= b.mid:
            span = a.mid - b.mid
            if span <= 0:
                return a.strike, "ok"
            frac = (a.mid - put_premium) / span
            return a.strike + frac * (b.strike - a.strike), "ok"
    return None, "above_chain"


def build_collar_row(floor, spot, put_leg, call_leg, k_star, status, contracts):
    """
    Economics with the net cost rolled into the basis (Moontower formulation).

    net    = put paid - call received, per share. Positive = debit.
    basis  = spot + net   (what this hedged year actually costs you per share)
    max loss = (put strike - basis) / basis
    max gain = (call strike - basis) / basis
    R:R      = max gain / |max loss|

    Dividends received over the tenor sit on top of both numbers and are not
    included here; the per-ticker footnote states the yield.
    """
    row = {
        "floor_target_pct": floor,
        "status": status,
        "spot": spot,
        "contracts": contracts,
        "put": put_leg.to_dict() if put_leg else None,
        "call": call_leg.to_dict() if call_leg else None,
        "zero_cost_call_strike_interp": k_star,
    }
    if put_leg is None or call_leg is None or not put_leg.mid or not call_leg.mid:
        row["priceable"] = False
        return row

    net = put_leg.mid - call_leg.mid
    # Worst realistic fill: pay the ask on the put, hit the bid on the call.
    if put_leg.quoted and call_leg.quoted:
        net_cross = put_leg.ask - call_leg.bid
    else:
        net_cross = None
    basis = spot + net

    row.update({
        "priceable": True,
        "put_strike": put_leg.strike,
        "call_strike": call_leg.strike,
        "put_otm_pct": (spot - put_leg.strike) / spot,
        "call_otm_pct": (call_leg.strike - spot) / spot,
        "net_per_share": net,
        "net_per_share_cross": net_cross,
        "net_total": net * CONTRACT_MULTIPLIER * contracts,
        "net_total_cross": (None if net_cross is None
                            else net_cross * CONTRACT_MULTIPLIER * contracts),
        "effective_basis": basis,
        "max_loss_pct": (put_leg.strike - basis) / basis,
        "max_gain_pct": (call_leg.strike - basis) / basis,
        "put_iv": put_leg.iv,
        "call_iv": call_leg.iv,
        "indicative": not (put_leg.quoted and call_leg.quoted),
    })
    ml, mg = row["max_loss_pct"], row["max_gain_pct"]
    row["risk_reward"] = (mg / abs(ml)) if ml and ml < 0 else None
    return row


def build_ticker_menu(ticker, rate, contracts, shares, today=None):
    """Price the full menu for one ticker. Returns a dict (JSON-serializable)."""
    today = today or date.today()
    asof = datetime.now(timezone.utc)
    print(f"\n=== {ticker} ===")

    info = _yf().get_stock_info(ticker)
    div_yield = _f(info.get("dividendYield")) or 0.0
    if div_yield > 1:                       # tolerate a percent-formatted feed
        div_yield /= 100.0

    expirations = _yf().get_expirations(ticker)
    if not expirations:
        return {"ticker": ticker, "error": "no expirations returned by proxy"}

    out = {
        "ticker": ticker,
        "name": info.get("shortName") or info.get("longName"),
        "dividend_yield": div_yield,
        "ex_dividend_date": info.get("exDividendDate"),
        "earnings_date": (info.get("earningsDate") or [None])[0],
        "risk_free_rate": rate,
        "contracts": contracts,
        "shares": shares,
        "asof_utc": asof.isoformat(),
        "tenors": [],
    }

    for label, target, ranked in pick_expiries(ticker, expirations, today, TENORS):
        chain, expiration, dte = None, None, None
        for cand, cand_dte in ranked[:4]:      # tolerate proxy 500s on an expiry
            chain = load_chain(ticker, cand)
            if chain is not None:
                expiration, dte = cand, cand_dte
                break
        if chain is None:
            out["tenors"].append({
                "label": label, "target_dte": target,
                "error": "no loadable expiry near this tenor",
            })
            continue

        spot = _f(chain.underlying_price) or _f(info.get("regularMarketPrice"))
        if not spot:
            out["tenors"].append({
                "label": label, "expiration": expiration,
                "error": "no underlying price",
            })
            continue

        T = max(dte, 1) / 365.0
        call_legs = [Leg(r, "c", spot, T, rate, div_yield, asof)
                     for r in _rows(chain.calls)]
        put_legs = [Leg(r, "p", spot, T, rate, div_yield, asof)
                    for r in _rows(chain.puts)]
        otm_calls = [l for l in call_legs if l.strike and l.strike > spot]

        tenor = {
            "label": label, "target_dte": target, "expiration": expiration,
            "dte": dte, "spot": spot,
            "quote_health": _quote_health(call_legs + put_legs),
            "rows": [],
        }

        for floor in PUT_FLOORS:
            target_put = spot * (1 - floor)
            put_leg = nearest_strike_leg(put_legs, target_put)
            if put_leg is None or not put_leg.mid:
                tenor["rows"].append({
                    "floor_target_pct": floor, "priceable": False,
                    "status": "no_put_price",
                    "put": put_leg.to_dict() if put_leg else None,
                })
                continue
            k_star, status = interpolate_zero_cost_strike(otm_calls, put_leg.mid)
            if status == "ok":
                call_leg = nearest_strike_leg(otm_calls, k_star)
            elif status == "below_chain":
                priced = [l for l in otm_calls if l.mid and l.mid > 0]
                call_leg = min(priced, key=lambda l: l.strike) if priced else None
            elif status == "above_chain":
                call_leg = max((l for l in otm_calls if l.mid), key=lambda l: l.strike, default=None)
            else:
                call_leg = None
            tenor["rows"].append(
                build_collar_row(floor, spot, put_leg, call_leg, k_star, status, contracts)
            )

        out["tenors"].append(tenor)
    return out


def _quote_health(legs):
    if not legs:
        return {"legs": 0, "quoted": 0, "quoted_frac": 0.0}
    quoted = sum(1 for l in legs if l.quoted)
    return {"legs": len(legs), "quoted": quoted, "quoted_frac": quoted / len(legs)}


# ============================================================
# MARKDOWN RENDERING
# ============================================================

STATUS_NOTE = {
    "below_chain": (
        "no zero-cost collar exists at this floor without selling an ITM call — "
        "the put costs more than any OTM call brings in (put skew). Row below "
        "shows the lowest listed OTM call, i.e. the closest you can get."
    ),
    "above_chain": (
        "zero-cost sits beyond the highest listed call strike — the put is "
        "cheaper than every listed call. Row below shows the highest priced "
        "listed strike."
    ),
    "unpriceable": "not enough priced call strikes to interpolate.",
    "no_put_price": "no usable price on the put leg at this floor.",
}


def render_ticker(menu):
    L = []
    t = menu["ticker"]
    if menu.get("error"):
        return [f"## {t}", "", f"**Could not price:** {menu['error']}", ""]

    name = menu.get("name") or ""
    L.append(f"## {t} — {name}" if name else f"## {t}")
    L.append("")
    div = menu.get("dividend_yield") or 0.0
    L.append(
        f"Dividend yield {_pct(div, 2)} · ex-div date on file "
        f"{menu.get('ex_dividend_date') or '—'} (Yahoo reports the most recent one, "
        f"not always the next) · next earnings {menu.get('earnings_date') or '—'} · "
        f"sized at {menu['contracts']} contracts ({menu['shares']:,} shares)"
    )
    L.append("")

    for tenor in menu["tenors"]:
        L.append(f"### {tenor['label']} tenor")
        L.append("")
        if tenor.get("error"):
            L.append(f"*{tenor['error']}*")
            L.append("")
            continue

        qh = tenor["quote_health"]
        L.append(
            f"Expiry **{tenor['expiration']}** ({tenor['dte']} DTE, target "
            f"{tenor['target_dte']}) · spot **${tenor['spot']:,.2f}** · "
            f"two-sided quotes on {qh['quoted']}/{qh['legs']} chain legs "
            f"({qh['quoted_frac'] * 100:.0f}%)"
        )
        L.append("")
        if qh["quoted_frac"] < QUOTE_HEALTH_FLOOR:
            L.append(
                "> ⚠️ **Quotes are mostly dead on this chain.** Prices below fall "
                "back to last trade and are INDICATIVE ONLY — do not read them as "
                "tradeable. Re-run during regular trading hours."
            )
            L.append("")

        # --- Table 1: the menu ---
        L.append(
            "| Floor | Put strike | Call cap | Zero-cost K* (interp) | Net / share | "
            "Net @ size | Max loss | Max gain | R:R | Put IV | Call IV |"
        )
        L.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for r in tenor["rows"]:
            floor_lbl = f"{r['floor_target_pct'] * 100:.0f}% OTM"
            if not r.get("priceable"):
                L.append("| " + floor_lbl + " |" + " — |" * 10)
                continue
            ks = r.get("zero_cost_call_strike_interp")
            rr = r.get("risk_reward")
            cells = [
                floor_lbl,
                f"${r['put_strike']:,.2f} ({_pct(r['put_otm_pct'], 1)} OTM)",
                f"${r['call_strike']:,.2f} ({_pct(r['call_otm_pct'], 1)} OTM)",
                f"${ks:,.2f}" if ks else "—",
                _signed_money(r["net_per_share"]) + (" ⚠️" if r.get("indicative") else ""),
                _signed_money(r["net_total"], 0),
                _pct(r["max_loss_pct"]),
                _pct(r["max_gain_pct"]),
                f"{rr:.2f}×" if rr else "—",
                _pct(r["put_iv"], 1),
                _pct(r["call_iv"], 1),
            ]
            L.append("| " + " | ".join(cells) + " |")
        L.append("")

        # --- The one-line R:R framing, per row ---
        for r in tenor["rows"]:
            floor_lbl = f"{r['floor_target_pct'] * 100:.0f}% floor"
            note = STATUS_NOTE.get(r.get("status"))
            if not r.get("priceable"):
                L.append(f"- **{floor_lbl}** — {note or 'not priceable.'}")
                continue
            L.append(
                f"- **{floor_lbl}** — risking {_pct(abs(r['max_loss_pct']))} to make "
                f"{_pct(r['max_gain_pct'])}"
                + (f", {_signed_money(r['net_total'], 0)} to put on at "
                   f"{r['contracts']} contracts." if r['net_total'] else ".")
                + (f" {note}" if note else "")
            )
        L.append("")

        # --- Table 2: execution reality ---
        L.append("**Execution reality** — at this size the width is the cost.")
        L.append("")
        L.append(
            "| Floor | Leg | Contract | Bid | Ask | Mid | Width | Width % of mid | "
            "Cost to cross @ size | OI | Vol | Flags |"
        )
        L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for r in tenor["rows"]:
            floor_lbl = f"{r['floor_target_pct'] * 100:.0f}%"
            for kind, key in (("Put (buy)", "put"), ("Call (sell)", "call")):
                leg = r.get(key)
                if not leg:
                    L.append(f"| {floor_lbl} | {kind} | — | — | — | — | — | — | — | — | — | — |")
                    continue
                w = leg["width"]
                mid = leg["mid"]
                wpct = _pct(w / mid, 0) if (w is not None and mid) else "—"
                cross = (None if w is None
                         else w * CONTRACT_MULTIPLIER * r.get("contracts", 0))
                src = "" if leg["price_source"] == "mid" else " *(last)*"
                L.append(
                    f"| {floor_lbl} | {kind} | `{leg['symbol']}` "
                    f"| {_money(leg['bid'])} | {_money(leg['ask'])} "
                    f"| {_money(mid)}{src} | {_money(w)} | {wpct} "
                    f"| {_money(cross, 0)} | {leg['open_interest']:,.0f} "
                    f"| {leg['volume']:,.0f} "
                    f"| {', '.join(leg['flags']) if leg['flags'] else '—'} |"
                )
        L.append("")
    return L


def render_document(menus, args):
    now = datetime.now(timezone.utc)
    L = [
        "# Collar menu",
        "",
        f"Generated {now.strftime('%Y-%m-%d %H:%M UTC')} from live Yahoo chains via "
        f"`yf_proxy`. Risk-free rate {args.rate * 100:.2f}%, sized at "
        f"{args.contracts} contracts ({args.shares:,} shares) per ticker.",
        "",
        "**This is a menu with prices. It is not a recommendation.** No row here is "
        "picked, ranked, or endorsed — the point is to see what the market is "
        "actually charging for downside protection at each floor, so the "
        "conversation happens against real numbers.",
        "",
        "> **Tax caveat — out of our lane.** Per the Phase 2 spec: "
        f"{TAX_CAVEAT}. Nothing on this page accounts for tax. Do not act on any "
        "row until the tax person has signed off on it.",
        "",
        "**How to read it**",
        "",
        "- **Net / share** — put mid minus call mid. `db` = debit (you pay), "
        "`cr` = credit (you receive). Exact zero-cost does not exist on a listed "
        "chain; the *Zero-cost K\\** column is where zero would sit if strikes were "
        "continuous, and the *Call cap* column is the nearest strike you can "
        "actually trade, with its actual net cost.",
        "- **Max loss / max gain / R:R** — net cost rolled into the basis. "
        "Effective basis = spot + net; max loss = (put strike − basis) / basis; "
        "max gain = (call strike − basis) / basis. Dividends received over the "
        "tenor sit on top of both and are not included — each ticker's yield is "
        "stated in its header.",
        "- **IV** — solved from the mid quoted in the same row (Black-Scholes-Merton, "
        "continuous dividend yield), not read off Yahoo's `impliedVolatility` field, "
        "which returns solver garbage outside trading hours.",
        "- **Flags** — `no-bid` / `no-ask` mean there is no two-sided market on that "
        "leg. `wide` / `absurd-width` / `thin OI` / `stale` are drawn against "
        "arbitrary starting thresholds "
        f"(width > {WIDE_PCT_OF_MID * 100:.0f}% and > {ABSURD_PCT_OF_MID * 100:.0f}% "
        f"of mid, OI < {MIN_OI}, last trade > {STALE_DAYS}d ago) — they are eye-catchers "
        "to tune, not derived limits. The raw bid, ask and width are always shown so "
        "the flag never hides the number.",
        "- **⚠️ on a net cost** means at least one leg had no two-sided quote and the "
        "price fell back to last trade. Indicative only.",
        "",
        "---",
        "",
    ]
    for m in menus:
        L += render_ticker(m)
        L.append("---")
        L.append("")
    return "\n".join(L)


# ============================================================
# VERIFY MODE
# ============================================================

def render_verify(menu):
    """
    Hand-check worksheet: raw leg quotes plus the arithmetic spelled out, so two
    rows can be spot-checked against broker-quoted prices without trusting any
    of this code.
    """
    L = [f"HAND-CHECK WORKSHEET — {menu['ticker']}", "=" * 60, ""]
    if menu.get("error"):
        L.append(menu["error"])
        return "\n".join(L)
    for tenor in menu["tenors"]:
        if tenor.get("error"):
            continue
        L.append(f"{tenor['label']}  expiry {tenor['expiration']}  "
                 f"DTE {tenor['dte']}  spot {tenor['spot']:.2f}")
        L.append("")
        for r in tenor["rows"]:
            L.append(f"  --- {r['floor_target_pct'] * 100:.0f}% floor ---")
            if not r.get("priceable"):
                L.append(f"      not priceable ({r.get('status')})")
                L.append("")
                continue
            p, c = r["put"], r["call"]
            L.append(f"      BUY  PUT  {p['symbol']}  K={p['strike']}  "
                     f"bid={p['bid']} ask={p['ask']} -> mid={p['mid']:.4f}")
            L.append(f"      SELL CALL {c['symbol']}  K={c['strike']}  "
                     f"bid={c['bid']} ask={c['ask']} -> mid={c['mid']:.4f}")
            L.append(f"      net/share      = {p['mid']:.4f} - {c['mid']:.4f} "
                     f"= {r['net_per_share']:+.4f}")
            L.append(f"      basis          = {r['spot']:.4f} + ({r['net_per_share']:+.4f}) "
                     f"= {r['effective_basis']:.4f}")
            L.append(f"      max loss       = ({p['strike']:.2f} - {r['effective_basis']:.4f}) "
                     f"/ {r['effective_basis']:.4f} = {r['max_loss_pct'] * 100:+.2f}%")
            L.append(f"      max gain       = ({c['strike']:.2f} - {r['effective_basis']:.4f}) "
                     f"/ {r['effective_basis']:.4f} = {r['max_gain_pct'] * 100:+.2f}%")
            if r.get("risk_reward"):
                L.append(f"      R:R            = {r['max_gain_pct'] * 100:.2f} / "
                         f"{abs(r['max_loss_pct']) * 100:.2f} = {r['risk_reward']:.4f}x")
            L.append(f"      net @ {r['contracts']} contracts = {r['net_per_share']:+.4f} "
                     f"x {CONTRACT_MULTIPLIER} x {r['contracts']} = "
                     f"{r['net_total']:+,.2f}")
            L.append(f"      put IV (solved from mid)  = "
                     f"{('%.4f' % r['put_iv']) if r['put_iv'] else 'n/a'}   "
                     f"(Yahoo said {p['iv_yahoo']})")
            L.append(f"      call IV (solved from mid) = "
                     f"{('%.4f' % r['call_iv']) if r['call_iv'] else 'n/a'}   "
                     f"(Yahoo said {c['iv_yahoo']})")
            L.append("")
            L.append("      To spot-check: pull these two contract symbols in the "
                     "broker and compare bid/ask.")
            L.append("")
    return "\n".join(L)


# ============================================================
# MAIN
# ============================================================

def main():
    ap = argparse.ArgumentParser(
        description="Zero-cost collar menu generator (conversation aid, not a monitor)."
    )
    ap.add_argument("--tickers", nargs="+", default=HELD_TICKERS,
                    help=f"Tickers to price (default: {' '.join(HELD_TICKERS)})")
    ap.add_argument("--shares", type=int, default=DEFAULT_SHARES,
                    help="Shares held per ticker; sets the contract count.")
    ap.add_argument("--rate", type=float, default=DEFAULT_RATE,
                    help="Risk-free rate used for the IV solve.")
    ap.add_argument("--out", help="Write the markdown document to this path.")
    ap.add_argument("--json", dest="json_out",
                    help="Write the raw priced menu to this JSON path.")
    ap.add_argument("--verify", metavar="TICKER",
                    help="Print a hand-check worksheet for one ticker and exit.")
    args = ap.parse_args()

    args.contracts = args.shares // CONTRACT_MULTIPLIER
    if args.contracts < 1:
        print(f"--shares {args.shares} is under one contract ({CONTRACT_MULTIPLIER} "
              f"shares). Nothing to price.")
        return 1

    if args.verify:
        menu = build_ticker_menu(args.verify.upper(), args.rate,
                                 args.contracts, args.shares)
        print()
        print(render_verify(menu))
        return 0

    tickers = [t.upper() for t in args.tickers]
    print(f"Pricing collar menus for {len(tickers)} tickers at {args.contracts} "
          f"contracts each: {', '.join(tickers)}")

    menus = []
    for i, t in enumerate(tickers, 1):
        print(f"\n[{i}/{len(tickers)}] {t}")
        try:
            menus.append(build_ticker_menu(t, args.rate, args.contracts, args.shares))
        except Exception as exc:
            print(f"  [error] {t}: {exc}")
            menus.append({"ticker": t, "error": str(exc)})

    doc = render_document(menus, args)

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as fh:
            fh.write(doc)
        print(f"\nWrote markdown -> {os.path.abspath(args.out)}")
    else:
        print()
        print(doc)

    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
        with open(args.json_out, "w") as fh:
            json.dump(menus, fh, indent=2, default=str)
        print(f"Wrote JSON     -> {os.path.abspath(args.json_out)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
