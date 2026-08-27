"""
Tests for the dead-man's switch (spec A3 Layer 0) and notification ownership.

The fault this defends against is not an error — it is silence. Nothing failed
during the 4.5-month outage; things simply stopped happening, and every alarm we
had was watching for explicit failures. A heartbeat inverts that: the monitor
must positively assert "I ran" on a known cadence, and the health check alarms on
the absence of that assertion.

Two consequences that these tests pin down:
  1. The heartbeat must be written on the FAILURE path too. A crashed monitor
     that writes nothing is indistinguishable from a cron that never fired.
  2. A run that could not persist its verdicts must fail. A UI reading stored
     assessments keeps showing the last good verdict when persistence quietly
     breaks, which is worse than showing nothing.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import monitor_positions
from monitor_positions import MonitorError


@pytest.fixture
def wired(monkeypatch):
    # Pin the wall clock OUTSIDE the 15:00-16:59 ET daily-summary window
    # (monitor_positions.py:672). main() reads datetime.now(tz=ET) directly, so
    # without this every test in this file grows an extra pushover when CI
    # happens to run between 3 and 5 PM ET — which is exactly how these tests
    # first failed, on a YAML-only PR at 15:00:05 ET on 2026-08-27.
    from datetime import datetime as _real_dt

    class _PinnedDatetime(_real_dt):
        @classmethod
        def now(cls, tz=None):
            return _real_dt(2026, 8, 27, 14, 0, tzinfo=monitor_positions.ET)

    monkeypatch.setattr(monitor_positions, "datetime", _PinnedDatetime)
    monkeypatch.setattr(monitor_positions, "SUPABASE_URL", "https://db.example.com")
    monkeypatch.setattr(monitor_positions, "SUPABASE_KEY", "key")
    monkeypatch.setattr(monitor_positions, "PUSHOVER_TOKEN", "t")
    monkeypatch.setattr(monitor_positions, "PUSHOVER_USER", "u")
    monkeypatch.setattr(monitor_positions, "DRY_RUN", False)
    monkeypatch.setattr(monitor_positions, "ROLE", "primary")
    monkeypatch.setattr(monitor_positions, "SOURCE", "pytest")

    monkeypatch.setattr(monitor_positions, "get_open_trades", lambda: [{
        "id": "8f14e45f-0000-4000-8000-000000000001",
        "ticker": "AAPL", "strike": 250, "expiry": "2026-09-18",
        "sold_price": 3.50, "contracts": 10, "status": "open",
    }])

    import pandas as pd
    monkeypatch.setattr(monitor_positions.yf_proxy, "get_stock_history",
                        lambda *a, **k: pd.DataFrame({"Close": [255.0]}))
    monkeypatch.setattr(monitor_positions.yf_proxy, "get_option_chain",
                        lambda *a, **k: None)
    monkeypatch.setattr(monitor_positions.yf_proxy, "get_stock_info",
                        lambda *a, **k: {})
    monkeypatch.setattr(monitor_positions, "store_assessment",
                        lambda *a, **k: {"id": "stub"})

    sent = []
    monkeypatch.setattr(monitor_positions, "send_pushover",
                        lambda **kw: (sent.append(kw), True)[1])
    return sent


@pytest.fixture
def beats(monkeypatch):
    written = []
    monkeypatch.setattr(monitor_positions, "write_heartbeat",
                        lambda **kw: (written.append(kw), {"id": "stub"})[1])
    return written


# ── the heartbeat exists at all ──────────────────────────────────────────────

def test_successful_run_writes_an_ok_heartbeat(wired, beats):
    monitor_positions.main()
    assert len(beats) == 1
    assert beats[0]["ok"] is True
    assert beats[0]["checked"] == 1


def test_run_with_no_open_positions_still_writes_a_heartbeat(wired, beats, monkeypatch):
    """Zero positions is a healthy state, not an excuse to skip the heartbeat.
    If an empty portfolio produced no heartbeat, the dead-man's switch would
    alarm every time Dad closed his last position."""
    monkeypatch.setattr(monitor_positions, "get_open_trades", lambda: [])
    monitor_positions.main()
    assert len(beats) == 1
    assert beats[0]["ok"] is True
    assert beats[0]["checked"] == 0


def test_failed_run_writes_a_not_ok_heartbeat_and_still_raises(wired, beats, monkeypatch):
    """The crucial one. A crash must leave a trace saying the run happened and
    was untrustworthy — otherwise it looks exactly like a cron that never fired,
    and the operator cannot tell the two apart."""
    def _boom(*a, **k):
        raise RuntimeError("yahoo exploded")
    monkeypatch.setattr(monitor_positions.yf_proxy, "get_stock_info", _boom)

    with pytest.raises(MonitorError):
        monitor_positions.main()

    assert len(beats) == 1
    assert beats[0]["ok"] is False
    assert beats[0]["unassessed_n"] == 1


def test_credential_failure_still_writes_a_heartbeat(wired, beats, monkeypatch):
    monkeypatch.setattr(monitor_positions, "PUSHOVER_TOKEN", "")
    with pytest.raises(MonitorError):
        monitor_positions.main()
    assert len(beats) == 1 and beats[0]["ok"] is False


def test_heartbeat_write_failure_fails_the_run(wired, monkeypatch):
    """No heartbeat means the health check will alarm. The run must be loud about
    why, rather than exiting 0 and leaving the operator to guess."""
    def _boom(**kw):
        raise MonitorError("heartbeat insert returned 401")
    monkeypatch.setattr(monitor_positions, "write_heartbeat", _boom)
    with pytest.raises(MonitorError, match="heartbeat"):
        monitor_positions.main()


# ── stored verdicts ──────────────────────────────────────────────────────────

def test_verdict_persistence_failure_fails_the_run(wired, beats, monkeypatch):
    def _boom(*a, **k):
        raise MonitorError("position_assessments insert returned no row")
    monkeypatch.setattr(monitor_positions, "store_assessment", _boom)
    with pytest.raises(MonitorError, match="not persisted"):
        monitor_positions.main()
    assert beats[0]["ok"] is False


def test_unassessed_position_stores_an_unassessed_verdict(wired, beats, monkeypatch):
    """Without this the UI keeps rendering the last good verdict for a position
    the monitor can no longer evaluate — a stale SAFE shown with confidence."""
    stored = []
    monkeypatch.setattr(monitor_positions, "store_assessment",
                        lambda *a, **k: (stored.append(k.get("level")), {"id": "s"})[1])
    def _boom(*a, **k):
        raise RuntimeError("no data")
    monkeypatch.setattr(monitor_positions.yf_proxy, "get_stock_info", _boom)

    with pytest.raises(MonitorError):
        monitor_positions.main()
    assert "UNASSESSED" in stored


# ── notification ownership: exactly one path buzzes the phone ────────────────

def test_fallback_stays_silent_while_primary_is_alive(wired, beats, monkeypatch):
    monkeypatch.setattr(monitor_positions, "ROLE", "fallback")
    monkeypatch.setattr(monitor_positions, "primary_is_alive", lambda: True)
    monitor_positions.main()
    assert wired == [], "fallback notified while the primary was healthy — Dad gets every alert twice"


def test_fallback_takes_over_when_primary_is_silent(wired, beats, monkeypatch):
    monkeypatch.setattr(monitor_positions, "ROLE", "fallback")
    monkeypatch.setattr(monitor_positions, "primary_is_alive", lambda: False)
    monitor_positions.main()
    assert len(wired) == 1, "primary was down and the fallback did not take over"
    assert "CLOSE NOW" in wired[0]["title"]


def test_fallback_takes_over_when_it_cannot_read_the_heartbeat(wired, beats, monkeypatch):
    """Any doubt resolves toward alerting. A duplicate push is an annoyance; a
    missing one is the event this tool exists to prevent."""
    def _boom(role="primary"):
        raise MonitorError("heartbeat read returned 401")
    monkeypatch.setattr(monitor_positions, "latest_heartbeat", _boom)
    monkeypatch.setattr(monitor_positions, "ROLE", "fallback")
    monitor_positions.main()
    assert len(wired) == 1, "unreadable heartbeat was treated as a healthy primary"


def test_fallback_takes_over_when_primary_heartbeat_says_not_ok(wired, beats, monkeypatch):
    monkeypatch.setattr(monitor_positions, "ROLE", "fallback")
    monkeypatch.setattr(monitor_positions, "latest_heartbeat",
                        lambda role="primary": {"ran_at": "2099-01-01T00:00:00+00:00", "ok": False})
    monitor_positions.main()
    assert len(wired) == 1, "a failing primary was treated as healthy"


def test_stale_primary_heartbeat_triggers_takeover(wired, beats, monkeypatch):
    monkeypatch.setattr(monitor_positions, "ROLE", "fallback")
    monkeypatch.setattr(monitor_positions, "latest_heartbeat",
                        lambda role="primary": {"ran_at": "2026-01-01T00:00:00+00:00", "ok": True})
    monitor_positions.main()
    assert len(wired) == 1, "a months-old heartbeat was treated as alive"


def test_suppressed_alerts_are_recorded_not_discarded(wired, beats, monkeypatch):
    """A quiet fallback run must still be auditable — you need to be able to ask
    'what would it have sent?' after the fact."""
    monkeypatch.setattr(monitor_positions, "ROLE", "fallback")
    monkeypatch.setattr(monitor_positions, "primary_is_alive", lambda: True)
    monitor_positions.main()
    assert beats[0]["detail"]["alerts_suppressed"], "suppressed alerts vanished from the record"


def test_daily_summary_fires_inside_its_window(wired, beats, monkeypatch):
    """The clock-pinning in the `wired` fixture must not quietly bury the
    summary feature: repin INSIDE the window and assert the summary sends.
    This is the red-baseline for the fixture's pin — remove the pin and the
    other tests in this file fail between 15:00 and 16:59 ET."""
    from datetime import datetime as _real_dt

    class _InWindow(_real_dt):
        @classmethod
        def now(cls, tz=None):
            return _real_dt(2026, 8, 27, 15, 30, tzinfo=monitor_positions.ET)

    monkeypatch.setattr(monitor_positions, "datetime", _InWindow)
    monitor_positions.main()
    assert any("Summary" in kw.get("title", "") for kw in wired), \
        "no daily summary inside the 15:00-16:59 ET window"
