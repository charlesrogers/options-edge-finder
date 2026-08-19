-- 004 — Row Level Security on this app's six tables.
--
-- WHY
-- ---
-- Verified on 2026-08-19, before this migration, against the live instance:
--
--   relrowsecurity = f   on all six tables
--   pg_policies      = 0 rows for all six tables
--   anon SELECT      -> 200 on all six
--   anon INSERT into public.trades              -> 201  (row created)
--   anon DELETE from public.trades              -> 204  (row removed)
--   anon DELETE from public.monitor_heartbeats  -> 204
--
-- The anon key is public by design — it was shipped as a NEXT_PUBLIC_* build arg
-- and is readable by anyone. So "anyone on the internet can insert a fake trade,
-- delete a real one, or blind the position monitor by writing heartbeats" was a
-- literal statement of fact, not a hypothetical.
--
-- HOW
-- ---
-- RLS with no policies is deny-all. There is nothing to write here beyond
-- enabling it, because:
--
--   * `service_role` has rolbypassrls = t on this instance (verified), so every
--     legitimate consumer — the web app's API routes, the GitHub Actions crons,
--     the position monitor — is unaffected the moment it authenticates with the
--     service key instead of the anon key.
--   * NOTHING reads these tables client-side. The only two browser components
--     that mention Supabase import row TYPES, which vanish at compile time. So
--     there is no legitimate anon access to preserve, and no anon-read policy
--     needs to exist. A policy that is not needed is an attack surface that is
--     not needed.
--
-- The REVOKE lines are NOT decorative. Verified before running this: `anon` and
-- `authenticated` currently hold DELETE, INSERT, REFERENCES, SELECT, TRIGGER,
-- TRUNCATE and UPDATE on all six tables. RLS is what actually denies them, but
-- leaving those grants in place means a single later permissive policy re-opens
-- write access. `PUBLIC` is included because privileges granted to PUBLIC are
-- not removed by revoking from anon.
--
-- Two RLS bypass routes were checked and are clear for these six tables:
--   * views / materialised views built on them — none exist (pg_depend/pg_rewrite
--     scan returned 0 rows). A view runs as its owner and does NOT apply the base
--     table's RLS, so this had to be confirmed rather than assumed.
--   * SECURITY DEFINER functions touching them — six such functions exist in
--     `public`, and none references any of these tables. They belong to other
--     apps on this shared instance.
--
-- WHAT THIS DOES NOT COVER — deliberate, and a real residual risk
-- --------------------------------------------------------------
-- The session executing this was scoped to exactly these six tables. This app
-- also reads and writes at least: basket_results, deployment_stages,
-- iv_snapshots, overrides, pass_rate_history, predictions, signal_graveyard,
-- vol_surface_snapshots. Those still carry full anon grants, and
-- migrations/001_signal_graveyard.sql:48 grants signal_graveyard to anon
-- explicitly. The public anon key can therefore still write them.
--
-- That matters: `predictions`, `iv_snapshots` and `overrides` feed the
-- recommendation engine, so this is an INTEGRITY exposure on trade inputs, not
-- just a confidentiality one. It is recorded here rather than fixed because
-- widening the blast radius past the named six was explicitly out of scope for
-- this session. It needs its own scoped pass.
--
-- BLAST RADIUS
-- ------------
-- This Supabase instance is shared by every app on the box: 87 other tables in
-- `public` besides these six. Every statement below names its table explicitly.
-- There is no loop, no wildcard, and no `FOR ALL TABLES`. Verified beforehand
-- that all six names are unique across schemas and owned by `postgres`.
--
-- Row counts immediately before this ran, so a later reader can prove nothing
-- was destroyed: trades=0, portfolio_holdings=7, paper_trades=452,
-- option_chain_snapshots=139177, position_assessments=0, monitor_heartbeats=15.
--
-- ORDER OF OPERATIONS — this matters
-- ----------------------------------
-- Do NOT run this until every consumer holds the service-role key:
--   * Coolify   : SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY on the app
--   * GitHub    : secret SUPABASE_SERVICE_ROLE_KEY (all 16 workflows read it)
--   * Hetzner   : /etc/options-copilot.env  SUPABASE_KEY
--   * Streamlit : st.secrets SUPABASE_KEY, if that app is still running
-- Running this first turns every cron red at once.

BEGIN;

ALTER TABLE public.trades                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.portfolio_holdings     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.paper_trades           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.option_chain_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.position_assessments   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.monitor_heartbeats     ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.trades                 FROM anon, authenticated, PUBLIC;
REVOKE ALL ON public.portfolio_holdings     FROM anon, authenticated, PUBLIC;
REVOKE ALL ON public.paper_trades           FROM anon, authenticated, PUBLIC;
REVOKE ALL ON public.option_chain_snapshots FROM anon, authenticated, PUBLIC;
REVOKE ALL ON public.position_assessments   FROM anon, authenticated, PUBLIC;
REVOKE ALL ON public.monitor_heartbeats     FROM anon, authenticated, PUBLIC;

COMMIT;
