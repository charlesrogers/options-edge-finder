"""
Guards the contract between `public.trades` and the two things that read it.

Background (2026-08-18): the alerting paths read `expiration` and
`premium_received`; the table has `expiry` and `sold_price`. The table was empty,
so nothing failed. `test_live_supabase_columns_exist` is the test that would have
caught it on day one — it asks PostgREST for exactly the columns the monitor
needs and lets the database answer. PostgREST rejects an unknown column even when
the table has zero rows, so this works before the first real position is ever
logged.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trade_schema import REQUIRED, TradeRowError, parse_trade_row


def _row(**over):
    row = {
        "id": "1ce9a2f4-0000-4000-8000-000000000000",
        "ticker": "aapl",
        "strike": 230.0,
        "expiry": "2026-08-21",
        "sold_price": 3.10,
        "contracts": 100,
        "status": "open",
    }
    row.update(over)
    return row


def test_parses_a_real_supabase_row():
    pos = parse_trade_row(_row())
    assert pos.ticker == "AAPL"          # normalised
    assert pos.expiry == "2026-08-21"
    assert pos.sold_price == 3.10
    assert pos.contracts == 100
    assert pos.label == "AAPL $230.0 exp 2026-08-21"


def test_legacy_sqlite_column_names_are_rejected_not_defaulted():
    """The exact shape the monitor used to assume. The point of the test is that
    this raises rather than yielding expiry='' / sold_price=0."""
    legacy = {
        "id": "legacy",
        "ticker": "AAPL",
        "strike": 230.0,
        "expiration": "2026-08-21",
        "premium_received": 3.10,
        "contracts": 100,
    }
    with pytest.raises(TradeRowError) as e:
        parse_trade_row(legacy)
    assert "expiry" in str(e.value) and "sold_price" in str(e.value)


@pytest.mark.parametrize("col", REQUIRED)
def test_every_required_column_missing_raises(col):
    with pytest.raises(TradeRowError):
        parse_trade_row(_row(**{col: None}))


@pytest.mark.parametrize("bad", ["", "08/21/2026", "2026-8-21", "next friday"])
def test_non_iso_expiry_raises(bad):
    with pytest.raises(TradeRowError):
        parse_trade_row(_row(expiry=bad))


def test_unusable_numerics_raise():
    with pytest.raises(TradeRowError):
        parse_trade_row(_row(strike="not-a-number"))


def test_required_set_is_frozen():
    """If you change this, you are changing what the monitor needs to assess a
    position. Update the DB, both readers, and the golden cases together."""
    assert set(REQUIRED) == {"ticker", "strike", "expiry", "sold_price", "contracts"}


@pytest.mark.skipif(
    not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY")),
    reason="needs Supabase credentials; runs in CI",
)
def test_live_supabase_columns_exist():
    """Ask the live database whether the monitor's columns exist. PostgREST
    answers 400/42703 for an unknown column even on an empty table, so this is a
    real contract check that does not need a real position to exist."""
    import requests

    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_KEY"]
    select = ",".join(("id", *REQUIRED, "status"))
    resp = requests.get(
        f"{url}/rest/v1/trades?select={select}&limit=1",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=20,
    )
    assert resp.status_code == 200, (
        f"public.trades does not expose the columns the monitor reads "
        f"({select}): HTTP {resp.status_code} {resp.text[:300]}"
    )


@pytest.mark.skipif(
    not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY")),
    reason="needs Supabase credentials; runs in CI",
)
def test_live_supabase_rejects_the_legacy_column_names():
    """The other half: prove the old names really are absent, so this test file
    fails loudly if someone 'fixes' the drift by re-adding them on one side only."""
    import requests

    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_KEY"]
    resp = requests.get(
        f"{url}/rest/v1/trades?select=expiration,premium_received&limit=1",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=20,
    )
    assert resp.status_code != 200, (
        "public.trades now has expiration/premium_received columns. Two column "
        "sets for the same fact is how the phone and the screen drifted apart. "
        "Pick one and update trade_schema.REQUIRED, trade-row.ts, and db.add_trade."
    )
