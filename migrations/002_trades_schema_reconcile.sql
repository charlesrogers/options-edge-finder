-- 002 — reconcile public.trades with the Python side (2026-08-18)
--
-- public.trades was created by the Next.js rebuild with
--   (ticker, strike, expiry, sold_price, close_price, contracts, status,
--    opened_at, closed_at, created_at)
-- while db.py (Streamlit) writes the older local-SQLite field set
--   (option_type, expiration, premium_received, strategy, notes, opened, close_reason).
--
-- The name collisions (expiration/expiry, premium_received/sold_price, opened/opened_at)
-- are handled by an explicit adapter in db.py — the DB keeps the web names, which
-- are the ones the alerting engine and the UI already agree on. The four columns
-- below have no equivalent at all, so inserting them 400'd and Streamlit's
-- "add trade" form has never successfully written to Supabase. They are added
-- rather than dropped because notes/strategy/close_reason are information the
-- operator typed and would otherwise be silently discarded.
--
-- Additive only. No column is renamed or removed, so nothing that reads the
-- table today can break.

ALTER TABLE public.trades
  ADD COLUMN IF NOT EXISTS option_type   text NOT NULL DEFAULT 'call',
  ADD COLUMN IF NOT EXISTS strategy      text NOT NULL DEFAULT 'covered_call',
  ADD COLUMN IF NOT EXISTS notes         text,
  ADD COLUMN IF NOT EXISTS close_reason  text;

-- The monitor reads WHERE status='open'. Cheap, and it makes the 15-minute
-- read a single index hit once real positions exist.
CREATE INDEX IF NOT EXISTS trades_status_idx ON public.trades (status);
