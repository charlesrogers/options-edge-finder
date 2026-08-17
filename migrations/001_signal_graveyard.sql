-- signal_graveyard — the hypothesis pre-registration table.
--
-- Discovered missing 2026-08-16: db.register_hypothesis() targets
-- `signal_graveyard` on Supabase, but the table has never existed there.
-- Every pre-registration since H01 (2026-03-22) silently landed in the
-- gitignored local SQLite file instead, because db.py falls back without
-- saying so. Only H01-H04 survive, all still `untested`.
--
-- STATUS: APPLIED 2026-08-17. The table now exists on the self-hosted Supabase
-- and holds 13 rows (H01-H04 untested, H17-H20 from Week 2, H21-H24 from
-- Phase 3). Verified by read-back, not by write count. This file is kept
-- idempotent so re-running it is a no-op.
--
-- Apply with:
--   ssh root@95.216.205.160 \
--     "docker exec -i supabase-db psql -U postgres -d postgres" \
--     < migrations/001_signal_graveyard.sql
--
-- Note the fallback trap that hid this for five months: db.py silently writes
-- to a gitignored local SQLite when the `supabase` client is missing or the
-- creds are unset, and returns the same value either way. signal_registry
-- .backend() now prints the destination on every call. If it says `sqlite:...`,
-- the row did NOT reach this table.

CREATE TABLE IF NOT EXISTS signal_graveyard (
    signal_id           TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    tier                INTEGER,
    hypothesis          TEXT,
    pre_registered_date TEXT NOT NULL,
    tested_date         TEXT,
    status              TEXT NOT NULL DEFAULT 'untested',
    layer_reached       INTEGER NOT NULL DEFAULT 0,
    best_sharpe         DOUBLE PRECISION,
    best_clv            DOUBLE PRECISION,
    n_trades            INTEGER,
    failure_reason      TEXT,
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS signal_graveyard_status_idx
    ON signal_graveyard (status);

-- The graveyard is append-and-annotate. A row is never deleted: the Deflated
-- Sharpe denominator is the count of everything ever tested, including the
-- failures. Deleting a failed signal silently inflates every later result.
