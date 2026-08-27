"""The shared decision core: one definition of what a verdict makes a trader do.

This module exists because we are still paying down engine #2 (`copilot.ts`) and
`tasks/lessons.md` (2026-08-16, "Built a second simulator") is explicit that the
next duplicated decision rule is the next silent divergence. Two callers need
these semantics:

  * `experiments/cc_sim.py` — the historical cohort simulator, which prices the
    exit at that day's Databento close.
  * `paper_engine/` — the forward engine, which prices the exit at the real ask
    fifteen minutes after the decision.

They differ in *pricing*, which is the entire point of the paper engine. They
must not differ in *deciding*. So the decision is here, once, and both import it.

`decide()` is a pure function of (context, config, policy, arming state). It
returns what to do and the new arming state; it never prices a fill for the
caller that does not want its price. Everything it returns about money is
labelled with where the number came from (`priced_from`), so a caller that
substitutes its own fill cannot accidentally inherit the simulator's.

Ordering is load-bearing and is the ordering `run_cohort` has always used:

  1. expiry settlement (a position past its expiry cannot be traded)
  2. the copilot's verdict
  3. CLOSE_NOW  -> close
  4. CLOSE_SOON -> arm, and close once `close_soon_days` have elapsed
  5. rational early exercise into a dividend — checked *after* the policy,
     because the alert fires in the morning and exercise is decided at the
     close of the day before the ex-date (Natenberg Ch. 12)

CLOSE_SOON's clock is measured in **calendar** days, not trading days. That is
not an accident and not a bug: the number comes from the alert's own wording
("Close this week"), and `cc_sim` has always computed it as a calendar delta.
The paper-engine spec §3 says "trading days"; the code is the authority and the
discrepancy is recorded in `tasks/paper-engine-s0-verification.md`.
"""

from dataclasses import dataclass
from typing import Optional

HOLD, CLOSE_SOON, CLOSE_NOW = 'HOLD', 'CLOSE_SOON', 'CLOSE_NOW'

# What produced `settle_price`. A caller that supplies its own fill (the paper
# engine) re-prices only OPTION_QUOTE decisions — an assignment settles at
# intrinsic and an expiry-worthless settles at zero no matter who is asking.
OPTION_QUOTE = 'option_quote'
INTRINSIC = 'intrinsic'
ZERO = 'zero'
NONE = 'none'


@dataclass
class Decision:
    """What the copilot's verdict means, before anyone has priced it."""
    kind: str                 # expiry_assigned | expiry_worthless | policy_close_now
                              # | policy_close_soon | early_exercise | hold
    verdict: str              # the alert level (or policy label) that produced it
    closes: bool
    assigned: bool
    assignment_type: str      # '' | 'early_exdiv' | 'expiry'
    settle_price: Optional[float]   # per share, as the SIMULATOR would book it
    priced_from: str

    @property
    def needs_market_fill(self):
        """True when closing this position requires actually buying it back.

        Assignments and worthless expiries do not: nobody trades, the leg just
        settles. Only these decisions cost a spread and a commission.
        """
        return self.closes and self.priced_from == OPTION_QUOTE


HOLD_DECISION_KIND = 'hold'


def _hold(verdict):
    return Decision(kind=HOLD_DECISION_KIND, verdict=verdict, closes=False,
                    assigned=False, assignment_type='', settle_price=None,
                    priced_from=NONE)


def decide(ctx, cfg, policy, armed_on=None):
    """Decide what happens to one open position on one observation.

    Args:
        ctx: a `cc_sim.DayContext` (or anything with the same attributes:
            date, spot, strike, option_price, sold_price, dte, days_to_exdiv,
            dividend, is_itm, intrinsic, extrinsic).
        cfg: merged config dict — reads `slippage`, `close_soon_days`,
            `close_soon_sticky`.
        policy: callable(ctx) -> (action, verdict).
        armed_on: the date CLOSE_SOON first fired for this position, or None.
            The paper engine persists this between runs; the simulator keeps it
            in a local. Either way the state lives outside this function, which
            is what makes the engine safe to restart mid-position.

    Returns:
        (Decision, new_armed_on)
    """
    # 1. Expiry settlement. Past expiry there is no position left to trade, so
    #    this precedes the policy — a copilot verdict on an expired contract is
    #    meaningless and must never be able to book a buyback.
    if ctx.dte <= 0:
        if ctx.spot > ctx.strike:
            return Decision(kind='expiry_assigned', verdict='EXPIRY', closes=True,
                            assigned=True, assignment_type='expiry',
                            settle_price=ctx.spot - ctx.strike,
                            priced_from=INTRINSIC), armed_on
        return Decision(kind='expiry_worthless', verdict='EXPIRY', closes=True,
                        assigned=False, assignment_type='',
                        settle_price=0.0, priced_from=ZERO), armed_on

    # 2. The copilot gets to act.
    action, verdict = policy(ctx)

    # 3. CLOSE_NOW / EMERGENCY — close at the next opportunity.
    if action == CLOSE_NOW:
        return Decision(kind='policy_close_now', verdict=verdict, closes=True,
                        assigned=False, assignment_type='',
                        settle_price=ctx.option_price * (1 + cfg['slippage']),
                        priced_from=OPTION_QUOTE), armed_on

    # 4. CLOSE_SOON — arm, then close once the clock runs out. Sticky by
    #    default: the live app does not un-say "close this week" when the alert
    #    drops back to WATCH the next day.
    if action == CLOSE_SOON:
        if armed_on is None:
            armed_on = ctx.date
        if (ctx.date - armed_on).days >= cfg['close_soon_days']:
            return Decision(kind='policy_close_soon', verdict=verdict, closes=True,
                            assigned=False, assignment_type='',
                            settle_price=ctx.option_price * (1 + cfg['slippage']),
                            priced_from=OPTION_QUOTE), armed_on
    elif not cfg['close_soon_sticky']:
        armed_on = None

    # 5. Rational early exercise into the dividend (Natenberg Ch. 12). Deliberately
    #    after the policy: the holder decides at the close of the day before the
    #    ex-date, by which time the copilot has already had its chance to act.
    if (ctx.days_to_exdiv is not None and ctx.days_to_exdiv <= 1
            and ctx.is_itm and ctx.dividend is not None
            and ctx.extrinsic < ctx.dividend):
        return Decision(kind='early_exercise', verdict=verdict, closes=True,
                        assigned=True, assignment_type='early_exdiv',
                        settle_price=ctx.intrinsic, priced_from=INTRINSIC), armed_on

    return _hold(verdict), armed_on


def assignment_is_approaching(ctx, within_days=3):
    """Did this observation come near the early-assignment branch?

    Exp 015 reported "0 assignments" from a run in which the assignment state
    was never reachable, and read it as the constraint being satisfied
    (tasks/lessons.md 2026-08-16, "hard constraint satisfied by construction").
    Counting approaches is what lets a zero be reported honestly as
    "non-binding — the state was never reached" instead of as a pass.
    """
    return bool(ctx.is_itm and ctx.days_to_exdiv is not None
                and ctx.days_to_exdiv <= within_days)


def is_usable_number(value, allow_zero=False):
    """True only for a real, finite, non-negative number.

    Promoted from `position_monitor._is_usable_number` so the engine, the
    simulator and the monitor share one definition (spec §5.5). Rejects None,
    NaN, inf, non-numerics, bools and — unless `allow_zero` — zero.

    `is None` is not a missing-data check: a NaN dividend yield sails straight
    through a None-guard and lands in arithmetic as a silent NaN
    (tasks/lessons.md 2026-08-16).
    """
    if value is None or isinstance(value, bool):
        return False
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    if v != v or v in (float('inf'), float('-inf')):
        return False
    if v < 0:
        return False
    return True if allow_zero else v > 0


def is_usable_date(value):
    """True only for something that parses to a real calendar date.

    The date twin of `is_usable_number`. An externally-sourced date that is
    None, NaN, an empty string, or a malformed stub must be rejected loudly
    rather than silently becoming "no dividend ahead" — which is how the
    EMERGENCY rule spent six experiments unable to fire.
    """
    if value is None or isinstance(value, bool):
        return False
    # pandas NaT and float('nan') are both self-unequal.
    if value != value:
        return False
    if isinstance(value, str):
        if not value.strip():
            return False
        from datetime import datetime as _dt
        try:
            _dt.strptime(value[:10], '%Y-%m-%d')
            return True
        except ValueError:
            return False
    return hasattr(value, 'year') and hasattr(value, 'month') and hasattr(value, 'day')


def parse_market_date(value):
    """Normalize an externally-sourced date to 'YYYY-MM-DD', or None.

    Accepts the THREE shapes Yahoo has actually served: a UTC-midnight epoch
    (int/float seconds), an ISO 'YYYY-MM-DD' string, and a date/datetime.
    Anything else — NaN, empty, malformed — returns None.

    Why this exists: the deployed Cloudflare worker returns
    `exDividendDate: calendarEvents.exDividendDate?.fmt` — a STRING — while
    both the live monitor and the paper engine guarded with
    `isinstance(ts, (int, float))`. A string date therefore parsed to None on
    every lookup, which made the EMERGENCY clause and every ex-div rule
    silently unreachable against the live proxy: the DTE-bug shape
    (tasks/lessons.md 2026-08-16) on the $400K alert path. Probed live
    2026-08-21: AAPL /info returned exDividendDate '2026-08-10' (str) and
    earningsDate as a list of strings.

    Epochs are interpreted as UTC — a naive fromtimestamp() renders them in the
    host's local timezone and shifts the date back a day on any US box, a
    one-day error against a three-day EMERGENCY window.
    """
    from datetime import datetime as _dt, timezone as _tz
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value != value or value in (float('inf'), float('-inf')) or value <= 0:
            return None
        try:
            return _dt.fromtimestamp(value, tz=_tz.utc).strftime('%Y-%m-%d')
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        s = value.strip()[:10]
        try:
            _dt.strptime(s, '%Y-%m-%d')
            return s
        except ValueError:
            return None
    if hasattr(value, 'year') and hasattr(value, 'month') and hasattr(value, 'day'):
        return f'{value.year:04d}-{value.month:02d}-{value.day:02d}'
    return None


def upcoming_market_date(value, as_of):
    """`parse_market_date`, then None unless the date is `as_of` or later.

    Yahoo's calendarEvents serves the MOST RECENT ex-dividend date, which is in
    the PAST for most of each payment cycle (probed 2026-08-21: AAPL served
    '2026-08-10' eleven days after it). Downstream, position_monitor computes
    `max(0, (ex_div - today).days)`, so a past date clamps to days_to_exdiv=0
    and an ITM covered call on any dividend payer fires a false EMERGENCY every
    15 minutes until Yahoo rolls the date. A past event date carries no forward
    risk; it must parse to None, in the same place the shape is normalized.

    `as_of` is a date, datetime, or 'YYYY-MM-DD' string. Today (== as_of) is
    kept — conservative on the ex-date itself.
    """
    s = parse_market_date(value)
    if s is None:
        return None
    a = parse_market_date(as_of)
    if a is None:
        return None
    return s if s >= a else None
