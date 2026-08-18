"""
Tests for the monitor's FAILURE policy — not its alert thresholds.

These cover the class of bug that let the tool sleep for 4.5 months with every
signal green: a lookup fails, the failure is swallowed, and the monitor reports
an all-clear it has no basis for. Each test below asserts that a broken input
produces a LOUD failure rather than a quiet SAFE.

Threshold behaviour lives in test_position_monitor.py and is untouched here.
"""

import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import monitor_positions
from monitor_positions import MonitorError, epoch_to_date, preflight, get_open_trades


# ============================================================
# Ex-dividend timezone handling (FACT-10)
# ============================================================

# Yahoo reports ex-dividend dates as a UTC-midnight epoch.
EX_DIV_EPOCH = datetime(2026, 8, 20, 0, 0, tzinfo=timezone.utc).timestamp()


@pytest.mark.parametrize("tz", ["UTC", "America/New_York", "America/Los_Angeles", "Asia/Tokyo"])
def test_ex_div_date_is_host_timezone_independent(tz, monkeypatch):
    """The rendered date must not depend on where the job runs.

    The old naive datetime.fromtimestamp() rendered 2026-08-20T00:00Z as
    2026-08-19 on any US-timezone host — a one-day shift against a three-day
    EMERGENCY window. Moving this job from a UTC GitHub runner to the Hetzner
    box could have introduced exactly that.
    """
    import time
    if not hasattr(time, "tzset"):
        pytest.skip("tzset unavailable on this platform")

    monkeypatch.setenv("TZ", tz)
    time.tzset()
    try:
        # Guard against a vacuous test: confirm the process timezone really moved,
        # otherwise this would pass against the naive implementation too.
        naive = datetime.fromtimestamp(EX_DIV_EPOCH).strftime("%Y-%m-%d")
        if tz in ("America/New_York", "America/Los_Angeles"):
            assert naive == "2026-08-19", "TZ did not take effect — test would be vacuous"

        assert epoch_to_date(EX_DIV_EPOCH) == "2026-08-20"
    finally:
        monkeypatch.undo()
        time.tzset()


def test_naive_conversion_would_have_shifted_the_date():
    """Documents the bug being fixed, so a regression is unmistakable."""
    import time
    if not hasattr(time, "tzset"):
        pytest.skip("tzset unavailable on this platform")

    old_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "America/New_York"
        time.tzset()
        naive = datetime.fromtimestamp(EX_DIV_EPOCH).strftime("%Y-%m-%d")
        assert naive == "2026-08-19"          # the bug
        assert epoch_to_date(EX_DIV_EPOCH) == "2026-08-20"   # the fix
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()


# ============================================================
# Preflight — refuse to run blind
# ============================================================

def test_preflight_fails_without_pushover_credentials(monkeypatch):
    """A rotated Pushover token must not silently mute every EMERGENCY.

    The old code printed '[NO PUSHOVER]' and exited 0.
    """
    monkeypatch.setattr(monitor_positions, "SUPABASE_URL", "https://db.example.com")
    monkeypatch.setattr(monitor_positions, "SUPABASE_KEY", "key")
    monkeypatch.setattr(monitor_positions, "PUSHOVER_TOKEN", "")
    monkeypatch.setattr(monitor_positions, "PUSHOVER_USER", "")
    monkeypatch.setattr(monitor_positions, "DRY_RUN", False)

    with pytest.raises(MonitorError, match="PUSHOVER_TOKEN"):
        preflight()


def test_preflight_fails_without_supabase_credentials(monkeypatch):
    monkeypatch.setattr(monitor_positions, "SUPABASE_URL", "")
    monkeypatch.setattr(monitor_positions, "SUPABASE_KEY", "")
    monkeypatch.setattr(monitor_positions, "PUSHOVER_TOKEN", "t")
    monkeypatch.setattr(monitor_positions, "PUSHOVER_USER", "u")
    monkeypatch.setattr(monitor_positions, "DRY_RUN", False)

    with pytest.raises(MonitorError, match="SUPABASE_URL"):
        preflight()


# ============================================================
# Trades read — an error is never "no open trades"
# ============================================================

class _Resp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else []
        self.text = text

    def json(self):
        return self._payload


def test_trades_read_error_raises_instead_of_reporting_empty(monkeypatch):
    monkeypatch.setattr(monitor_positions, "SUPABASE_URL", "https://db.example.com")
    monkeypatch.setattr(monitor_positions, "SUPABASE_KEY", "stale-key")
    monkeypatch.setattr(monitor_positions.requests, "get",
                        lambda *a, **k: _Resp(401, text="Unauthorized"))

    # This is the exact 2026-03 failure: a stale key returning 401.
    with pytest.raises(MonitorError, match="401"):
        get_open_trades()


def test_trades_read_exception_raises(monkeypatch):
    monkeypatch.setattr(monitor_positions, "SUPABASE_URL", "https://db.example.com")
    monkeypatch.setattr(monitor_positions, "SUPABASE_KEY", "key")

    def _boom(*a, **k):
        raise ConnectionError("network down")
    monkeypatch.setattr(monitor_positions.requests, "get", _boom)

    with pytest.raises(MonitorError, match="trades read failed"):
        get_open_trades()


def test_genuinely_empty_trades_is_not_an_error(monkeypatch):
    monkeypatch.setattr(monitor_positions, "SUPABASE_URL", "https://db.example.com")
    monkeypatch.setattr(monitor_positions, "SUPABASE_KEY", "key")
    monkeypatch.setattr(monitor_positions.requests, "get", lambda *a, **k: _Resp(200, []))

    assert get_open_trades() == []


# ============================================================
# main() — an unassessable position fails the run
# ============================================================

@pytest.fixture
def wired(monkeypatch):
    """Credentials present, one open position, alerts captured not sent."""
    monkeypatch.setattr(monitor_positions, "SUPABASE_URL", "https://db.example.com")
    monkeypatch.setattr(monitor_positions, "SUPABASE_KEY", "key")
    monkeypatch.setattr(monitor_positions, "PUSHOVER_TOKEN", "t")
    monkeypatch.setattr(monitor_positions, "PUSHOVER_USER", "u")
    monkeypatch.setattr(monitor_positions, "DRY_RUN", False)

    # The exact column names public.trades returns. This fixture used to carry
    # `expiration`/`premium_received` — the local-SQLite spelling — which meant
    # the failure tests below passed for the wrong reason once row validation
    # landed: every position was rejected as unreadable before the behaviour
    # under test was ever reached.
    monkeypatch.setattr(monitor_positions, "get_open_trades", lambda: [{
        "id": "8f14e45f-0000-4000-8000-000000000001",
        "ticker": "AAPL", "strike": 250, "expiry": "2026-09-18",
        "sold_price": 3.50, "contracts": 10, "status": "open",
    }])

    sent = []
    monkeypatch.setattr(monitor_positions, "send_pushover",
                        lambda **kw: (sent.append(kw), True)[1])

    import pandas as pd
    monkeypatch.setattr(monitor_positions.yf_proxy, "get_stock_history",
                        lambda *a, **k: pd.DataFrame({"Close": [255.0]}))
    monkeypatch.setattr(monitor_positions.yf_proxy, "get_option_chain",
                        lambda *a, **k: None)
    return sent


def test_ex_div_lookup_failure_fails_the_run(wired, monkeypatch):
    """THE $400K TEST.

    If the ex-dividend lookup raises, we cannot rule out an imminent ex-div.
    The old code caught the exception, left ex_div_date=None, and assess_position
    returned a calm level for a position that may have been an EMERGENCY.
    """
    def _boom(*a, **k):
        raise TimeoutError("yahoo timeout")
    monkeypatch.setattr(monitor_positions.yf_proxy, "get_stock_info", _boom)

    with pytest.raises(MonitorError, match="unassessed"):
        monitor_positions.main()

    titles = " ".join(k.get("title", "") for k in wired)
    assert "DEGRADED" in titles, "operator must be told the position went unchecked"


def test_missing_price_data_fails_the_run(wired, monkeypatch):
    import pandas as pd
    monkeypatch.setattr(monitor_positions.yf_proxy, "get_stock_history",
                        lambda *a, **k: pd.DataFrame({"Close": []}))
    monkeypatch.setattr(monitor_positions.yf_proxy, "get_stock_info", lambda *a, **k: {})

    with pytest.raises(MonitorError, match="unassessed"):
        monitor_positions.main()


def test_non_dividend_payer_is_not_a_failure(wired, monkeypatch):
    """A successful lookup with no exDividendDate field is legitimate.

    The distinction between 'lookup failed' and 'pays no dividend' is the whole
    point — collapsing them either hides EMERGENCIES or cries wolf on every
    non-payer.
    """
    monkeypatch.setattr(monitor_positions.yf_proxy, "get_stock_info", lambda *a, **k: {})

    monitor_positions.main()   # must not raise

    titles = " ".join(k.get("title", "") for k in wired)
    assert "DEGRADED" not in titles


def test_undelivered_alert_fails_the_run(wired, monkeypatch):
    """An EMERGENCY that Pushover rejected is an outage, not a success."""
    monkeypatch.setattr(monitor_positions.yf_proxy, "get_stock_info",
                        lambda *a, **k: {"exDividendDate": EX_DIV_EPOCH})
    monkeypatch.setattr(monitor_positions, "send_pushover", lambda **kw: False)

    with pytest.raises(MonitorError, match="undelivered"):
        monitor_positions.main()


# ============================================================
# db.py — the silent SQLite fallback (FACT-7)
# ============================================================

def test_require_supabase_refuses_sqlite_fallback(monkeypatch):
    """In a container, a write to local.db is a write into the void."""
    import db

    monkeypatch.setenv("REQUIRE_SUPABASE", "1")
    with pytest.raises(db.SupabaseUnavailable, match="local SQLite"):
        db._get_sqlite()


def test_require_supabase_refuses_missing_client(monkeypatch):
    import db

    monkeypatch.setenv("REQUIRE_SUPABASE", "1")
    monkeypatch.setattr(db, "SUPABASE_URL", "")
    monkeypatch.setattr(db, "SUPABASE_KEY", "")
    monkeypatch.setattr(db, "_supabase_client", None)
    monkeypatch.setattr(db, "_read_secret", lambda k: "")

    with pytest.raises(db.SupabaseUnavailable, match="SUPABASE_URL"):
        db._get_supabase()


def test_sqlite_fallback_still_works_for_local_dev(monkeypatch):
    """The fallback is a dev convenience — it must survive when not headless."""
    import db

    monkeypatch.delenv("REQUIRE_SUPABASE", raising=False)
    conn = db._get_sqlite()
    assert conn is not None
    conn.close()


# ============================================================
# Schema drift between the alert path and the table (FACT-11)
# ============================================================

def test_legacy_column_names_do_not_produce_a_verdict(wired, monkeypatch):
    """A row in the old SQLite spelling must be UNREADABLE, not assessable.

    Before 2026-08-18 this file read `trade.get("expiration", "")` and
    `trade.get("premium_received", 0)` against a table whose columns are `expiry`
    and `sold_price`. The defaults on those .get() calls are the whole bug: they
    turned a missing column into a plausible value instead of an error.
    """
    monkeypatch.setattr(monitor_positions, "get_open_trades", lambda: [{
        "id": "legacy-row",
        "ticker": "AAPL", "strike": 250, "expiration": "2026-09-18",
        "premium_received": 3.50, "contracts": 10, "status": "open",
    }])
    monkeypatch.setattr(monitor_positions.yf_proxy, "get_stock_info", lambda *a, **k: {})

    with pytest.raises(MonitorError) as e:
        monitor_positions.main()
    assert "unassessed" in str(e.value)


def test_operator_is_told_which_columns_are_missing(wired, monkeypatch, capsys):
    """The failure has to name the columns, or the next person debugs it blind."""
    monkeypatch.setattr(monitor_positions, "get_open_trades", lambda: [{
        "id": "legacy-row", "ticker": "AAPL", "strike": 250,
        "expiration": "2026-09-18", "premium_received": 3.50, "contracts": 10,
    }])
    monkeypatch.setattr(monitor_positions.yf_proxy, "get_stock_info", lambda *a, **k: {})

    with pytest.raises(MonitorError):
        monitor_positions.main()
    out = capsys.readouterr().out
    assert "expiry" in out and "sold_price" in out


def test_a_real_supabase_row_is_assessed_normally(wired, monkeypatch):
    """The positive half: the shape public.trades actually returns produces a
    verdict, with no unassessed positions and no failure."""
    monkeypatch.setattr(monitor_positions.yf_proxy, "get_stock_info", lambda *a, **k: {})
    monitor_positions.main()   # must not raise


def test_partial_row_is_rejected_rather_than_half_assessed(wired, monkeypatch):
    """sold_price NULL means we cannot compute premium captured. Assessing it as
    0 would understate every profit-taking rule; the row is unreadable instead."""
    monkeypatch.setattr(monitor_positions, "get_open_trades", lambda: [{
        "id": "partial", "ticker": "AAPL", "strike": 250,
        "expiry": "2026-09-18", "sold_price": None, "contracts": 10,
    }])
    monkeypatch.setattr(monitor_positions.yf_proxy, "get_stock_info", lambda *a, **k: {})
    with pytest.raises(MonitorError):
        monitor_positions.main()
