"""
NYSE trading calendar for the Python side, reading the same generated session
list the web reads (web/src/lib/nyse-sessions.json).

Spec A6. Wall-clock thresholds are wrong for a market that is closed 104 days a
year plus holidays: the health check's ">48h since last chain capture" went red
every Saturday night and stayed red until Monday, with nothing wrong. An alert
channel survives about two false alarms.

The holiday list is not maintained here — scripts/generate_nyse_calendar.py
produces the JSON from `exchange_calendars`, and CI fails if it drifts. This
module only reads it, so both languages answer "is the market open" identically.
"""

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "web", "src", "lib", "nyse-sessions.json",
)

_data = None


class CalendarRangeError(RuntimeError):
    """A date outside the generated calendar.

    Raised rather than answered, because past the end of the file every answer
    would be silently wrong and "no sessions since X" is indistinguishable from
    a dead pipeline.
    """


def _load():
    global _data
    if _data is None:
        with open(_PATH) as f:
            _data = json.load(f)
        _data["_session_set"] = set(_data["sessions"])
    return _data


def et_date(at=None):
    at = at or datetime.now(tz=ET)
    return at.astimezone(ET).strftime("%Y-%m-%d")


def _assert_in_range(day):
    d = _load()
    if day < d["range"]["start"] or day > d["range"]["end"]:
        raise CalendarRangeError(
            f"{day} is outside the generated NYSE calendar "
            f"({d['range']['start']}..{d['range']['end']}). "
            "Run scripts/generate_nyse_calendar.py to extend it."
        )


def is_trading_day(day):
    _assert_in_range(day)
    return day in _load()["_session_set"]


def close_minutes_et(day):
    early = _load()["early_closes"].get(day)
    if early:
        h, m = early.split(":")
        return int(h) * 60 + int(m)
    return 16 * 60


_OPEN_MINUTES = 9 * 60 + 30


def is_market_open(at=None):
    at = (at or datetime.now(tz=ET)).astimezone(ET)
    day = at.strftime("%Y-%m-%d")
    if not is_trading_day(day):
        return False
    mins = at.hour * 60 + at.minute
    return _OPEN_MINUTES <= mins < close_minutes_et(day)


def trading_days_since(since, now=None):
    """Sessions that have CLOSED between two instants.

    A Friday-afternoon capture is zero sessions old all weekend and one session
    old after Monday's bell — which is what "stale" should have meant all along.
    """
    now = (now or datetime.now(tz=ET)).astimezone(ET)
    frm = since.astimezone(ET).strftime("%Y-%m-%d")
    to = now.strftime("%Y-%m-%d")
    _assert_in_range(frm)
    _assert_in_range(to)
    if frm > to:
        return 0

    d = _load()
    n = sum(1 for s in d["sessions"] if frm < s <= to)
    # Today counts only once it has closed, or this morning's check would call
    # data captured after yesterday's bell a day stale.
    if to in d["_session_set"] and to > frm and (now.hour * 60 + now.minute) < close_minutes_et(to):
        n -= 1
    return max(0, n)


def calendar_range():
    d = _load()
    return d["range"]["start"], d["range"]["end"]
