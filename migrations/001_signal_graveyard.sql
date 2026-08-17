-- signal_graveyard — the hypothesis pre-registration table.
--
-- Discovered missing 2026-08-16: db.register_hypothesis() targets
-- `signal_graveyard` on Supabase, but the table has never existed there.
-- Every pre-registration since H01 (2026-03-22) silently landed in the
-- gitignored local SQLite file instead, because db.py falls back without
-- saying so. Only H01-H04 survive, all still `untested`.
--
-- Apply with:
--   ssh root@95.216.205.160 \
--     "docker exec -i supabase-db psql -U postgres -d postgres" \
--     < migrations/001_signal_graveyard.sql
--
-- Then backfill from local.db (H01-H04, H17-H20) — see
-- register_hypotheses.py.

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
