-- Signal graveyard — hypothesis pre-registration + verdict tracking.
--
-- db.py / signal_registry.py have referenced public.signal_graveyard since March 2026,
-- but the table was never created in the self-hosted Supabase. Every pre_register() /
-- mark_result() call against Supabase failed with PGRST205 ("table not found in schema
-- cache"), so the research-discipline audit trail existed only in a local SQLite file
-- (local.db, 4 rows, never updated since 2026-03-26). This migration creates it for real.
--
-- Column set matches the SQLite DDL in db.py so both backends behave identically.
--
-- Apply:
--   ssh root@95.216.205.160 "docker exec -i supabase-db psql -U postgres -d postgres" \
--     < migrations/001_signal_graveyard.sql

CREATE TABLE IF NOT EXISTS public.signal_graveyard (
    signal_id            TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    tier                 INTEGER,
    hypothesis           TEXT,
    pre_registered_date  TEXT NOT NULL,
    tested_date          TEXT,
    status               TEXT DEFAULT 'untested',
    layer_reached        INTEGER DEFAULT 0,
    best_sharpe          DOUBLE PRECISION,
    best_clv             DOUBLE PRECISION,
    n_trades             INTEGER,
    failure_reason       TEXT,
    notes                TEXT
);

GRANT ALL ON public.signal_graveyard TO anon, authenticated, service_role;

-- PostgREST caches the schema; without this the table stays invisible to the client.
NOTIFY pgrst, 'reload schema';
