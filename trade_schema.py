"""
The one place that knows what a row of Supabase `public.trades` looks like.

Why this file exists (2026-08-18): the alerting paths and the UI path had drifted
onto two different sets of column names. `public.trades` is:

    id, ticker, strike, expiry, sold_price, close_price, contracts,
    status, opened_at, closed_at, created_at

`api/copilot/route.ts` (the screen) read `expiry` / `sold_price` and was right.
`monitor_positions.py` and `api/cron/monitor/route.ts` (both alert paths) read
`expiration` / `premium_received` — columns that have never existed on this table.
They inherited those names from the local SQLite schema in db.py. Because the
table was empty, nothing failed and nothing was noticed.

The bug was not the wrong names. The bug was `trade.get("expiration", "")` — a
default that turned a missing column into a plausible-looking value. So the rule
here is: **a required field that is absent raises. It never defaults.** A monitor
that cannot identify a position must say so, not assess a fabricated one.
"""

REQUIRED = ("ticker", "strike", "expiry", "sold_price", "contracts")


class TradeRowError(ValueError):
    """A trades row that cannot be trusted to describe a real position."""


class Position:
    """A validated open position, in the field names assess_position() expects."""

    __slots__ = ("id", "ticker", "strike", "expiry", "sold_price", "contracts", "status")

    def __init__(self, id, ticker, strike, expiry, sold_price, contracts, status):
        self.id = id
        self.ticker = ticker
        self.strike = strike
        self.expiry = expiry
        self.sold_price = sold_price
        self.contracts = contracts
        self.status = status

    @property
    def label(self):
        return f"{self.ticker} ${self.strike} exp {self.expiry}"

    def __repr__(self):
        return f"<Position {self.label} x{self.contracts} @ ${self.sold_price}>"


def parse_trade_row(row):
    """Validate one Supabase `trades` row. Raises TradeRowError rather than
    guessing — see the module docstring."""
    if not isinstance(row, dict):
        raise TradeRowError(f"expected a row dict, got {type(row).__name__}")

    missing = [c for c in REQUIRED if row.get(c) is None]
    if missing:
        raise TradeRowError(
            f"trades row {row.get('id', '?')} is missing required column(s): "
            f"{', '.join(missing)}. Present: {', '.join(sorted(row))}. "
            "This is a schema mismatch, not an empty position — refusing to assess it."
        )

    try:
        strike = float(row["strike"])
        sold_price = float(row["sold_price"])
        contracts = int(row["contracts"])
    except (TypeError, ValueError) as e:
        raise TradeRowError(f"trades row {row.get('id', '?')} has unusable numerics: {e}") from e

    expiry = str(row["expiry"])[:10]
    if len(expiry) != 10 or expiry[4] != "-" or expiry[7] != "-":
        raise TradeRowError(
            f"trades row {row.get('id', '?')} has expiry {row['expiry']!r}, "
            "which is not an ISO YYYY-MM-DD date"
        )

    return Position(
        id=row.get("id"),
        ticker=str(row["ticker"]).upper(),
        strike=strike,
        expiry=expiry,
        sold_price=sold_price,
        contracts=contracts,
        status=row.get("status", "open"),
    )
