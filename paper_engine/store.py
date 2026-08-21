"""Persistence. Every write is read back; nothing reports a count it did not confirm.

The shape of this module is set by two incidents:

  * 2026-08-15 — write helpers returned `len(attempted)`, so a four-month outage
    reported healthy row counts the whole way through. Here, `Prefer:
    return=representation` makes PostgREST echo the stored row and an empty echo
    raises. A confirmed count is the only count this module will produce.
  * 2026-08-18 — a schema/data-contract mismatch surfaced only after the first
    write. `schema_contract_check()` selects the exact expected column list from
    every table before the engine makes a single decision; PostgREST rejects an
    unknown column even against an empty table, so this is a real check.

The SQLite fallback in `db.py` does not exist here at all. There is no local
mode: no credentials means no run.
"""
import json
import os
from datetime import datetime, timezone

import requests

from . import config

TIMEOUT = 20


class StoreError(RuntimeError):
    """Any persistence failure. Always fatal — the engine exits rather than
    trading against a database it cannot read or write."""


def _creds():
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY") or ""
    if not url or not key:
        raise StoreError(
            "SUPABASE_URL / SUPABASE_KEY are not set. This engine has no local "
            "fallback on purpose: a paper trade written to an ephemeral SQLite "
            "file in a container is a trade that never happened, reported as a "
            "success (tasks/lessons.md 2026-08-15)."
        )
    return url, key


def _headers(extra=None):
    _, key = _creds()
    h = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def _url(table):
    base, _ = _creds()
    return f"{base}/rest/v1/{table}"


def _stamp(row):
    """Engine lineage on every row. A result whose engine SHA is unknown cannot
    be reproduced or trusted (tasks/lessons.md 2026-08-17)."""
    row.setdefault("engine_commit_sha", config.engine_commit_sha())
    row.setdefault("engine_version", config.ENGINE_VERSION)
    return row


def insert(table, row, verify=True):
    """Insert one row and confirm the database returned it."""
    resp = requests.post(_url(table), headers=_headers({"Prefer": "return=representation"}),
                         json=_stamp(dict(row)), timeout=TIMEOUT)
    if resp.status_code not in (200, 201):
        raise StoreError(f"{table} insert -> {resp.status_code}: {resp.text[:400]}")
    if not verify:
        return None
    data = resp.json()
    if not data:
        raise StoreError(f"{table} insert returned no row — the write did not persist")
    return data[0]


def upsert(table, row, on_conflict, verify=True):
    """Insert or update on a unique key, and confirm the stored row came back.

    Used for quotes and entry evaluations, whose unique keys make a re-run of
    the same tick a no-op instead of a duplicate.
    """
    resp = requests.post(
        f"{_url(table)}?on_conflict={on_conflict}",
        headers=_headers({"Prefer": "return=representation,resolution=merge-duplicates"}),
        json=_stamp(dict(row)), timeout=TIMEOUT)
    if resp.status_code not in (200, 201):
        raise StoreError(f"{table} upsert -> {resp.status_code}: {resp.text[:400]}")
    if not verify:
        return None
    data = resp.json()
    if not data:
        raise StoreError(f"{table} upsert returned no row — the write did not persist")
    return data[0]


def insert_event(row):
    """Append an event, tolerating the deterministic-key collision by design.

    Returns 'inserted' or 'duplicate'. A duplicate is not an error: it is the
    mechanism. A crash between "decided to trade" and "recorded the fill" leaves
    the pending event already written, so the next run finds it and continues
    rather than double-filling. It is also what makes a kill switch alert once
    on the transition instead of once per tick for hours
    (tasks/lessons.md 2026-08-19).
    """
    resp = requests.post(
        f"{_url(config.TABLES['events'])}?on_conflict=dedup_key",
        headers=_headers({"Prefer": "return=representation,resolution=ignore-duplicates"}),
        json=_stamp(dict(row)), timeout=TIMEOUT)
    if resp.status_code not in (200, 201):
        raise StoreError(f"events insert -> {resp.status_code}: {resp.text[:400]}")
    return "inserted" if resp.json() else "duplicate"


def update(table, patch, **filters):
    """Patch rows matching `filters` (eq semantics) and return what came back."""
    query = "&".join(f"{k}=eq.{v}" for k, v in filters.items())
    if not query:
        raise StoreError("refusing an unfiltered update")
    patch = dict(patch)
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()
    resp = requests.patch(f"{_url(table)}?{query}",
                          headers=_headers({"Prefer": "return=representation"}),
                          json=patch, timeout=TIMEOUT)
    if resp.status_code not in (200, 204):
        raise StoreError(f"{table} update -> {resp.status_code}: {resp.text[:400]}")
    return resp.json() if resp.content else []


def select(table, query="", expect_ok=True):
    """GET rows. A read failure raises — "I could not check" must never be
    reported as "there is nothing there"."""
    resp = requests.get(f"{_url(table)}?{query}" if query else _url(table),
                        headers=_headers(), timeout=TIMEOUT)
    if expect_ok and resp.status_code != 200:
        raise StoreError(f"{table} select -> {resp.status_code}: {resp.text[:400]}")
    return resp


def select_rows(table, query=""):
    return select(table, query).json()


# ------------------------------------------------------------------ contract --

def schema_contract_check():
    """Select the exact expected column list from every table, before trading.

    Returns a dict of table -> 'ok'. Raises StoreError naming the first table
    that disagrees. Runs in the workflow, where credentials exist — not in
    credential-less CI, where it would be a check that cannot fail.
    """
    result = {}
    for table, columns in config.SCHEMA_CONTRACT.items():
        resp = select(table, f"select={','.join(columns)}&limit=1", expect_ok=False)
        if resp.status_code != 200:
            raise StoreError(
                f"schema contract FAILED for {table}: {resp.status_code} "
                f"{resp.text[:300]}\nExpected columns: {', '.join(columns)}"
            )
        result[table] = "ok"
    return result


# ----------------------------------------------------------------- graveyard --

def graveyard_rows(signal_ids):
    """Read the pre-registration rows back from Supabase.

    Deliberately a direct REST read rather than `db.py`: db.py falls back to a
    gitignored local SQLite file without saying so, and the whole point of the
    startup gate is that a pre-registration living on someone's laptop must not
    be able to satisfy it.
    """
    ids = ",".join(signal_ids)
    rows = select_rows(
        "signal_graveyard",
        f"signal_id=in.({ids})&select=signal_id,name,status,hypothesis,pass_thresholds,pre_registered_date")
    return {r["signal_id"]: r for r in rows}


# ----------------------------------------------------------------- heartbeat --

def write_heartbeat(*, ok, detail, positions_checked=0, alerts_fired=0):
    """Write this run's heartbeat, including on failure paths.

    A heartbeat is the positive signal a dead-man's switch watches, so it has to
    be written by runs that failed too — otherwise "the engine is broken" and
    "the engine is fine and quiet" look identical. `ok=false` means the run
    completed but its output cannot be trusted.
    """
    return insert("monitor_heartbeats", {
        "source": config.HEARTBEAT_SOURCE,
        "role": config.HEARTBEAT_ROLE,
        "engine": f"{config.ENGINE_NAME}.py",
        "engine_version": config.ENGINE_VERSION,
        "positions_checked": positions_checked,
        "positions_unassessed": detail.get("positions_unassessed", 0),
        "alerts_fired": alerts_fired,
        "alerts_undelivered": detail.get("alerts_undelivered", 0),
        "ok": bool(ok),
        "detail": detail,
    })


# ------------------------------------------------------------------- tallies --

class ConfirmedCounter:
    """Counts only what the database echoed back.

    `attempted` and `confirmed` are separate fields because conflating them is
    precisely the bug: a run that attempts 40 writes and confirms 0 must exit 1,
    not print "40 rows".
    """

    def __init__(self):
        self.attempted = 0
        self.confirmed = 0
        self.failures = []

    def record(self, fn, *args, **kwargs):
        self.attempted += 1
        try:
            out = fn(*args, **kwargs)
        except StoreError as e:
            self.failures.append(str(e)[:300])
            return None
        self.confirmed += 1
        return out

    @property
    def silently_empty(self):
        """Attempted work, confirmed nothing. The shape of a silent outage."""
        return self.attempted > 0 and self.confirmed == 0

    def as_dict(self):
        return {"attempted": self.attempted, "confirmed": self.confirmed,
                "failures": self.failures[:10],
                "failure_count": len(self.failures)}

    def __str__(self):
        return f"{self.confirmed}/{self.attempted} writes confirmed"


def json_safe(obj):
    """Round-trip through JSON so a NaN can never reach Supabase as a literal."""
    def _clean(o):
        if isinstance(o, dict):
            return {k: _clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_clean(v) for v in o]
        if isinstance(o, float) and (o != o or o in (float("inf"), float("-inf"))):
            return None
        return o
    return json.loads(json.dumps(_clean(obj), default=str))
