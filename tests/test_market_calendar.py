"""
Trading-calendar freshness (spec A6) — the anti-noise item.

FACT-5, demonstrated: chain capture runs `50 19 * * 1-5`, the health check failed
at >48h wall-clock, so every Saturday night the check went red and stayed red
until Monday. Run 31984884170 posted a 🚨 Discord embed at 01:25 on a Sunday with
nothing wrong. That matters beyond annoyance: A4's daily proof-of-life push only
works if its absence is noticeable, and an absence is not noticeable in a channel
people have learned to ignore.

The tests below use the exact weekend that produced that false alarm.
"""

import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import market_calendar as mc
from market_calendar import CalendarRangeError

ET = ZoneInfo("America/New_York")


# ── the weekend false alarm ──────────────────────────────────────────────────

FRIDAY_CAPTURE = datetime(2026, 8, 14, 15, 50, tzinfo=ET)   # 19:50 UTC, the real cron time


@pytest.mark.parametrize("label,when", [
    ("Friday evening",  datetime(2026, 8, 14, 18, 0, tzinfo=ET)),
    ("Saturday night",  datetime(2026, 8, 15, 21, 0, tzinfo=ET)),
    ("Sunday 01:25",    datetime(2026, 8, 16, 1, 25, tzinfo=ET)),   # the actual alarm time
    ("Monday premarket", datetime(2026, 8, 17, 8, 30, tzinfo=ET)),
])
def test_weekend_produces_no_staleness(label, when):
    """The whole weekend must read as zero trading days stale."""
    assert mc.trading_days_since(FRIDAY_CAPTURE, when) == 0, label


def test_wall_clock_would_have_cried_wolf():
    """Guards against a vacuous test: reproduce the arithmetic that actually fired.

    Two faults stacked to produce the 🚨 at 01:25 Sunday. option_chain_snapshots.date
    is a DATE column, so `new Date("2026-08-14")` is midnight UTC — nearly 20 hours
    before the 19:50 UTC capture it represents. That inflated age crossed the 48h
    wall-clock threshold at 01:25 Sunday even though only ~34 real hours had passed
    since the capture, and only ~5 hours of them were market hours.

    Both are fixed: the date is anchored to the close, and the threshold counts
    closed sessions instead of hours.
    """
    from datetime import timezone
    sunday_utc = datetime(2026, 8, 16, 1, 25, tzinfo=timezone.utc)
    date_column_as_midnight = datetime(2026, 8, 14, 0, 0, tzinfo=timezone.utc)

    naive_age_hours = (sunday_utc - date_column_as_midnight).total_seconds() / 3600
    assert naive_age_hours > 48, "the old >48h rule would not have fired — test is vacuous"
    assert round(naive_age_hours) == 49            # matches the run's "Last capture 49h ago"

    real_age_hours = (sunday_utc - FRIDAY_CAPTURE).total_seconds() / 3600
    assert real_age_hours < 48, "nothing was actually stale"

    # Anchored to the close, the Friday capture is zero sessions old all weekend.
    anchored = datetime(2026, 8, 14, 20, 0, tzinfo=timezone.utc)
    assert mc.trading_days_since(anchored, sunday_utc) == 0

    # And this is why the anchoring is not cosmetic: midnight UTC on the 14th is
    # 20:00 ET on the 13th, so the unanchored value lands a full session early.
    # It happens to stay under the >1 threshold, but it is off by one, and being
    # off by one is how a threshold gets "tuned" against the wrong number later.
    assert mc.trading_days_since(date_column_as_midnight, sunday_utc) == 1


def test_a_genuinely_missed_capture_is_still_caught():
    """The check must not have been softened into uselessness. A capture that
    missed Monday's session is one trading day stale by Monday's close."""
    monday_evening = datetime(2026, 8, 17, 18, 0, tzinfo=ET)
    assert mc.trading_days_since(FRIDAY_CAPTURE, monday_evening) == 1
    tuesday_evening = datetime(2026, 8, 18, 18, 0, tzinfo=ET)
    assert mc.trading_days_since(FRIDAY_CAPTURE, tuesday_evening) == 2


# ── holidays ─────────────────────────────────────────────────────────────────

def test_labor_day_weekend_is_quiet():
    """Three-day weekend: 76 wall-clock hours, zero trading days."""
    friday = datetime(2026, 9, 4, 15, 50, tzinfo=ET)
    monday_holiday = datetime(2026, 9, 7, 21, 0, tzinfo=ET)
    assert (monday_holiday - friday).total_seconds() / 3600 > 48
    assert mc.trading_days_since(friday, monday_holiday) == 0
    assert not mc.is_market_open(monday_holiday)


def test_thanksgiving_is_not_a_trading_day():
    assert not mc.is_trading_day("2026-11-26")
    assert mc.is_trading_day("2026-11-27")          # open, but a half day
    assert mc.close_minutes_et("2026-11-27") == 13 * 60


def test_christmas_and_july_fourth_observed():
    assert not mc.is_trading_day("2026-12-25")
    assert not mc.is_trading_day("2026-07-03")      # observed for July 4 (a Saturday)


def test_holidays_come_from_the_library_not_from_here():
    """The generated file must declare its provenance. A hand-maintained holiday
    list is the thing spec A6 forbids."""
    with open(os.path.join(os.path.dirname(__file__), '..',
                           'web', 'src', 'lib', 'nyse-sessions.json')) as f:
        data = json.load(f)
    assert data["generator"] == "exchange_calendars"
    assert data["exchange"] == "XNYS"
    assert len(data["sessions"]) > 1500


# ── market hours ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("when,expected", [
    (datetime(2026, 8, 17, 9, 29, tzinfo=ET), False),   # one minute before the bell
    (datetime(2026, 8, 17, 9, 30, tzinfo=ET), True),
    (datetime(2026, 8, 17, 15, 59, tzinfo=ET), True),
    (datetime(2026, 8, 17, 16, 0, tzinfo=ET), False),   # closed at the bell
    (datetime(2026, 8, 15, 12, 0, tzinfo=ET), False),   # Saturday
])
def test_market_open_boundaries(when, expected):
    assert mc.is_market_open(when) is expected


def test_half_day_closes_early():
    """1:00 PM ET on the day after Thanksgiving. A heartbeat check that thought
    the market was open until 16:00 would alarm for three hours every half day."""
    assert mc.is_market_open(datetime(2026, 11, 27, 12, 30, tzinfo=ET))
    assert not mc.is_market_open(datetime(2026, 11, 27, 13, 30, tzinfo=ET))


# ── running off the end of the generated file ────────────────────────────────

def test_dates_outside_the_generated_range_raise():
    """Past the last generated session every answer would be silently wrong, and
    'no sessions since X' is indistinguishable from a dead pipeline."""
    with pytest.raises(CalendarRangeError):
        mc.is_trading_day("2099-01-01")
    with pytest.raises(CalendarRangeError):
        mc.is_trading_day("2019-01-01")


def test_generated_calendar_has_headroom():
    """Fails a year before the file runs out, so nobody discovers it in an
    incident. Regenerate with scripts/generate_nyse_calendar.py."""
    from datetime import date
    _, end = mc.calendar_range()
    end_date = date.fromisoformat(end)
    days_left = (end_date - date.today()).days
    assert days_left > 365, (
        f"the generated NYSE calendar ends in {days_left} days ({end}). "
        "Run scripts/generate_nyse_calendar.py."
    )
