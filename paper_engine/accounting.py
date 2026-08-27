"""P&L, commissions and spread. Option leg only, and every cost is a visible line.

Accounting conventions, stated once so no report has to guess:

  * `pnl_per_share = premium_collected - buyback_cost`, times 100 per contract.
    Option leg ONLY — the stock is excluded. A covered call's stock leg swamps
    the option leg and mixing them is how a 191% "loss" got published
    (tasks/lessons.md 2026-03-24).
  * Sell-to-open fills at the **bid**. Buy-to-close fills at the **ask**. Never
    mid, never last. This bias runs in exactly one direction and it is the safe
    one: a strategy that survives these fills would do better in reality, and a
    strategy that dies under them is genuinely dead.
  * Commissions are their own field and are never folded into P&L.
  * Spread cost is reported against a MID fill, because that is the only
    baseline that answers "what did the market's spread actually charge us".
    Half the spread on each side is the cost of crossing it.
  * Portfolio totals are tallied as value CHANGE per day, never as level.
"""
from . import config


def sell_fill_price(quote):
    """What a sell-to-open actually gets: the bid."""
    return quote.bid if quote.bid_usable else None


def buy_fill_price(quote):
    """What a buy-to-close actually pays: the ask."""
    return quote.ask if quote.ask_usable else None


def commission(contracts, sides=1):
    """Per-contract, per-side. Labelled an assumption, not a measurement."""
    return round(config.COMMISSION_PER_CONTRACT_PER_SIDE * contracts * sides, 4)


def spread_of(quote):
    return quote.spread


def spread_pct_of(quote, premium_per_share):
    """Spread as a percentage of the premium collected.

    On KKR's 15%-OTM strike this was 267% on 2026-08-20 — the round trip costs
    2.7x the credit. Expressing it against the premium rather than against the
    mid is what makes that legible at a glance.
    """
    s = quote.spread
    if s is None or not premium_per_share:
        return None
    return round(s / premium_per_share * 100, 1)


def spread_cost_usd(entry_spread, exit_spread, contracts):
    """What crossing the spread cost, versus filling both legs at mid.

    Half a spread each way. `None` on either side contributes nothing rather
    than silently becoming zero-as-a-fact: a settlement has no spread because
    nobody traded, which is different from a spread we failed to observe.
    """
    total = 0.0
    for s in (entry_spread, exit_spread):
        if s is not None:
            total += s / 2.0
    return round(total * 100 * contracts, 2)


def cycle_pnl(*, premium_per_share, buyback_per_share, contracts,
              entry_commission, exit_commission):
    """Close out one cycle. Returns the full accounting, every line visible."""
    pnl_ps = round(premium_per_share - buyback_per_share, 6)
    gross = round(pnl_ps * 100 * contracts, 2)
    commissions = round((entry_commission or 0) + (exit_commission or 0), 2)
    return {
        "premium_per_share": round(premium_per_share, 6),
        "buyback_per_share": round(buyback_per_share, 6),
        "pnl_per_share": pnl_ps,
        "gross_pnl": gross,
        "commissions_total": commissions,
        "net_pnl": round(gross - commissions, 2),
    }


def retention(kept_usd, collected_usd):
    """Retention with both halves attached, and the inversion flagged.

    A ratio whose numerator can go negative does not behave like a percentage,
    and reporting it alone inverts the reader's intuition (tasks/lessons.md
    2026-08-16). Numerator and denominator travel with it, always.
    """
    if not collected_usd:
        return {"pct": None, "kept_usd": kept_usd, "collected_usd": collected_usd,
                "numerator_negative": (kept_usd or 0) < 0,
                "note": "no premium collected — retention is undefined, not 0%"}
    return {
        "pct": round(kept_usd / collected_usd * 100, 1),
        "kept_usd": round(kept_usd, 2),
        "collected_usd": round(collected_usd, 2),
        "numerator_negative": kept_usd < 0,
    }


def defined_risk_ceiling(premium_per_share, buyback_per_share, contracts):
    """Sanity bound: a covered call's option leg cannot lose more than the
    buyback exceeds the premium. Asserted in tests as a guard against an
    accounting sign error turning a loss into a gain or vice versa."""
    return round((buyback_per_share - premium_per_share) * 100 * contracts, 2)
