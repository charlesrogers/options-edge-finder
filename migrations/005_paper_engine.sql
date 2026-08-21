-- 005 — Paper-trading engine: forward validation with pre-registered arms.
--
-- STATUS: NOT YET APPLIED. Update this line to `STATUS: APPLIED <date>` after
-- running it, and only after the read-back at the bottom returns the expected
-- row. A migration file that says APPLIED without a verified read-back is the
-- same class of claim as a write helper returning the attempted count
-- (tasks/lessons.md 2026-08-15).
--
-- Apply with:
--   ssh root@95.216.205.160 \
--     "docker exec -i supabase-db psql -U postgres -d postgres" \
--     < migrations/005_paper_engine.sql
--
-- Idempotent: every statement is CREATE ... IF NOT EXISTS / ADD COLUMN IF NOT
-- EXISTS, so re-running is a no-op.
--
--
-- WHY NEW TABLES AND NOT `paper_trades`
-- -------------------------------------
-- `results/013_paper_trade_audit.md`: 444 of the existing tracker's 452 scored
-- rows are synthetic Black-Scholes backfill, and they were published as a track
-- record. The two populations must be **unjoinable by construction**, not by a
-- WHERE clause that someone eventually forgets. Nothing here references
-- `paper_trades`, and nothing ever should.
--
--
-- WHAT THE FOUR TABLES ARE FOR
-- ----------------------------
--   paper_engine_entry_evals — one row per (ticker, trading day). The record of
--       a decision *considered*, including the ones no arm took. Contract
--       selection runs before the gates, so a day where arm A was blocked by
--       the IV gate and arm C entered still has its contract and its quotes.
--       Without that row, "is the IV gate worth anything" is unanswerable.
--   paper_engine_quotes — the decision-moment market. Keyed by
--       (contract_symbol, tick_ts) because a quote captured at 19:50 UTC cannot
--       price a decision made at 14:22.
--   paper_engine_trades — the ledger. One row per (arm, ticker, cycle_seq),
--       carrying BOTH the alert-time quote and the fill-time quote for entry
--       and exit. That pair is the auditable receipt: it is what lets someone
--       check that we sold at the bid, bought back at the ask, and waited the
--       fifteen minutes we said we waited.
--   paper_engine_events — append-only log with a deterministic dedup key, which
--       is what makes re-runs safe and makes a kill switch alert once on the
--       transition instead of once per tick for hours (tasks/lessons.md
--       2026-08-19).
--
-- All timestamps are timestamptz. Never a bare DATE for anything compared to a
-- time — a midnight-UTC DATE parse produced a weekend false alarm
-- (tasks/lessons.md 2026-08-18). The `trading_day` DATE columns exist only for
-- grouping and are always derived from the ET calendar, never compared to a
-- timestamp.

BEGIN;

-- ============================================================
-- 1. Entry evaluations — one per ticker per trading day
-- ============================================================
CREATE TABLE IF NOT EXISTS public.paper_engine_entry_evals (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tick_ts             timestamptz NOT NULL,
  trading_day         date        NOT NULL,
  ticker              text        NOT NULL,

  -- 'ok' | 'proxy_failed' | 'empty_chain' | 'no_expiry_in_band' | 'no_strike'
  -- 'proxy_failed' and 'empty_chain' are deliberately separate values:
  -- yf_proxy._get returns {} on RequestException, so the engine has to probe
  -- for the difference and record which one it actually saw.
  chain_status        text        NOT NULL,
  spot                numeric,
  spot_usable         boolean     NOT NULL DEFAULT false,

  contract_symbol     text,
  strike              numeric,
  expiry              date,
  dte                 integer,
  bid                 numeric,
  ask                 numeric,
  last                numeric,
  volume              numeric,
  open_interest       numeric,
  implied_volatility  numeric,

  iv_rank             numeric,
  iv_threshold        numeric,
  iv_rank_source      text,

  -- The §5.2 liquidity floor, evaluated once and shared by every arm: a quote
  -- missing for one arm is missing for all.
  liquidity_ok        boolean     NOT NULL DEFAULT false,
  liquidity_reason    text,

  -- {"A": {"gate_passed": bool, "reason": str, "entered": bool}, "B": ..., ...}
  arm_results         jsonb       NOT NULL DEFAULT '{}'::jsonb,

  engine_commit_sha   text,
  engine_version      text,
  created_at          timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT paper_engine_entry_evals_day_ticker_key UNIQUE (ticker, trading_day)
);

CREATE INDEX IF NOT EXISTS paper_engine_entry_evals_day_idx
  ON public.paper_engine_entry_evals (trading_day DESC, ticker);


-- ============================================================
-- 2. Quotes — the decision-moment market
-- ============================================================
CREATE TABLE IF NOT EXISTS public.paper_engine_quotes (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  contract_symbol     text        NOT NULL,
  tick_ts             timestamptz NOT NULL,
  trading_day         date        NOT NULL,
  ticker              text        NOT NULL,

  bid                 numeric,
  ask                 numeric,
  last                numeric,
  volume              numeric,
  open_interest       numeric,
  implied_volatility  numeric,
  spot                numeric,

  bid_usable          boolean     NOT NULL DEFAULT false,
  ask_usable          boolean     NOT NULL DEFAULT false,
  spot_usable         boolean     NOT NULL DEFAULT false,

  -- 'ok' | 'proxy_failed' | 'empty_chain' | 'contract_missing' | 'unusable'
  source_status       text        NOT NULL,

  -- A carried-forward quote. `stale_from_tick_ts` names the tick it was
  -- actually observed at, so a stale fill can always be traced to the last
  -- real print behind it.
  stale               boolean     NOT NULL DEFAULT false,
  stale_from_tick_ts  timestamptz,

  engine_commit_sha   text,
  engine_version      text,
  created_at          timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT paper_engine_quotes_symbol_tick_key UNIQUE (contract_symbol, tick_ts)
);

CREATE INDEX IF NOT EXISTS paper_engine_quotes_tick_idx
  ON public.paper_engine_quotes (tick_ts DESC);
CREATE INDEX IF NOT EXISTS paper_engine_quotes_symbol_tick_idx
  ON public.paper_engine_quotes (contract_symbol, tick_ts DESC);
CREATE INDEX IF NOT EXISTS paper_engine_quotes_day_ticker_idx
  ON public.paper_engine_quotes (trading_day DESC, ticker);


-- ============================================================
-- 3. Trades — the auditable ledger
-- ============================================================
CREATE TABLE IF NOT EXISTS public.paper_engine_trades (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),

  arm                 text        NOT NULL,   -- 'A' | 'B' | 'C' | 'D'
  ticker              text        NOT NULL,
  cycle_seq           integer     NOT NULL,
  -- 'pending_entry' | 'open' | 'pending_exit' | 'closed' | 'abandoned'
  status              text        NOT NULL,

  contract_symbol     text        NOT NULL,
  strike              numeric     NOT NULL,
  expiry              date        NOT NULL,
  dte_at_entry        integer,
  contracts           integer     NOT NULL,

  -- ---- entry: the decision, then the fill fifteen minutes later ----
  entry_decision_ts   timestamptz NOT NULL,
  entry_decision_bid  numeric,
  entry_decision_ask  numeric,
  entry_decision_spot numeric,
  entry_fill_ts       timestamptz,
  entry_fill_bid      numeric,
  entry_fill_ask      numeric,
  entry_fill_spot     numeric,
  -- Sell-to-open fills at the BID. Never mid, never last.
  entry_fill_price    numeric,
  entry_spread        numeric,
  entry_spread_pct    numeric,
  entry_latency_min   numeric,
  entry_overnight_gap boolean     NOT NULL DEFAULT false,
  entry_quote_stale   boolean     NOT NULL DEFAULT false,
  entry_commission    numeric     NOT NULL DEFAULT 0,

  -- ---- exit ----
  exit_decision_ts    timestamptz,
  exit_decision_bid   numeric,
  exit_decision_ask   numeric,
  exit_decision_spot  numeric,
  exit_fill_ts        timestamptz,
  exit_fill_bid       numeric,
  exit_fill_ask       numeric,
  exit_fill_spot      numeric,
  -- Buy-to-close fills at the ASK; a settlement is priced off the stock.
  exit_fill_price     numeric,
  exit_spread         numeric,
  exit_spread_pct     numeric,
  exit_latency_min    numeric,
  exit_overnight_gap  boolean     NOT NULL DEFAULT false,
  exit_quote_stale    boolean     NOT NULL DEFAULT false,
  exit_commission     numeric     NOT NULL DEFAULT 0,

  exit_kind           text,       -- cc_core.Decision.kind
  exit_clause         text,       -- position_monitor clause id that fired
  exit_verdict        text,       -- alert level at exit
  exit_priced_from    text,       -- 'option_quote' | 'intrinsic' | 'zero'

  -- CLOSE_SOON's clock, persisted so a restart mid-position cannot reset it.
  close_soon_armed_on date,

  -- ---- assignment (always modeled — a paper position cannot be assigned) ----
  assigned            boolean     NOT NULL DEFAULT false,
  assignment_type     text        NOT NULL DEFAULT '',
  assignment_modeled  boolean     NOT NULL DEFAULT true,
  assignment_inputs   jsonb,

  -- ---- accounting: option leg only, stock excluded ----
  premium_per_share   numeric,
  buyback_per_share   numeric,
  pnl_per_share       numeric,
  gross_pnl           numeric,    -- (premium - buyback) * 100 * contracts
  commissions_total   numeric     NOT NULL DEFAULT 0,
  spread_cost_total   numeric     NOT NULL DEFAULT 0,
  net_pnl             numeric,    -- gross_pnl - commissions_total
  -- False when the exit was filled at a carried-forward quote. Every reported
  -- number is reported twice — all fills and real-fill subset — and if the two
  -- disagree in sign, the real-fill number is the result
  -- (tasks/lessons.md 2026-08-17, verbatim).
  real_fill           boolean     NOT NULL DEFAULT true,

  engine_commit_sha   text,
  engine_version      text,
  opened_at           timestamptz NOT NULL DEFAULT now(),
  closed_at           timestamptz,
  updated_at          timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT paper_engine_trades_arm_ticker_cycle_key UNIQUE (arm, ticker, cycle_seq)
);

CREATE INDEX IF NOT EXISTS paper_engine_trades_open_idx
  ON public.paper_engine_trades (status, arm, ticker);
CREATE INDEX IF NOT EXISTS paper_engine_trades_closed_idx
  ON public.paper_engine_trades (closed_at DESC);


-- ============================================================
-- 4. Events — append-only, deterministically keyed
-- ============================================================
CREATE TABLE IF NOT EXISTS public.paper_engine_events (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_ts            timestamptz NOT NULL DEFAULT now(),
  trading_day         date,

  -- 'entry_pending' | 'entry_filled' | 'exit_pending' | 'exit_filled'
  -- | 'modeled_assignment' | 'kill_state_change' | 'integrity_pause'
  -- | 'stale_streak' | 'startup_gate_fail' | 'schema_contract_fail'
  -- | 'proxy_failure' | 'alert_sent'
  kind                text        NOT NULL,
  severity            text        NOT NULL DEFAULT 'info',  -- info | warning | critical

  arm                 text,
  ticker              text,
  cycle_seq           integer,

  -- Deterministic. Two things depend on it: a crash between "decided" and
  -- "filled" cannot double-fill on the next run, and a kill switch that stays
  -- TRIGGERED alerts once on the transition rather than once per tick.
  dedup_key           text        NOT NULL,

  payload             jsonb       NOT NULL DEFAULT '{}'::jsonb,
  engine_commit_sha   text,
  engine_version      text,

  CONSTRAINT paper_engine_events_dedup_key UNIQUE (dedup_key)
);

CREATE INDEX IF NOT EXISTS paper_engine_events_ts_idx
  ON public.paper_engine_events (event_ts DESC);
CREATE INDEX IF NOT EXISTS paper_engine_events_kind_ts_idx
  ON public.paper_engine_events (kind, event_ts DESC);


-- ============================================================
-- 5. signal_graveyard gains a typed home for pre-registration thresholds
-- ============================================================
-- `signal_registry.pre_register()` accepts `pass_thresholds` and then folds it
-- into the free-text `hypothesis` string, because migration 001 gave the table
-- no column for it. The paper engine's startup gate has to compare the
-- committed PREREGISTRATION.md's SHA-256 against what was registered, and
-- regex-scraping a hash out of prose is not a contract. This gives it a typed
-- column. Additive and nullable — every existing row keeps working.
ALTER TABLE public.signal_graveyard
  ADD COLUMN IF NOT EXISTS pass_thresholds jsonb;


-- ============================================================
-- 6. RLS — deny-all, service-role only (same posture as migration 004)
-- ============================================================
-- The anon key is public by design (it ships as a NEXT_PUBLIC_* build arg), and
-- arm-level P&L at Dad's size is effectively a holdings disclosure. RLS with no
-- policies is deny-all; `service_role` has rolbypassrls on this instance, so
-- the engine and the web app's server-side routes keep working and nobody else
-- can read a row.
ALTER TABLE public.paper_engine_entry_evals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.paper_engine_quotes      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.paper_engine_trades      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.paper_engine_events      ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.paper_engine_entry_evals FROM anon, authenticated, PUBLIC;
REVOKE ALL ON public.paper_engine_quotes      FROM anon, authenticated, PUBLIC;
REVOKE ALL ON public.paper_engine_trades      FROM anon, authenticated, PUBLIC;
REVOKE ALL ON public.paper_engine_events      FROM anon, authenticated, PUBLIC;

GRANT ALL ON public.paper_engine_entry_evals TO service_role;
GRANT ALL ON public.paper_engine_quotes      TO service_role;
GRANT ALL ON public.paper_engine_trades      TO service_role;
GRANT ALL ON public.paper_engine_events      TO service_role;

COMMIT;

-- PostgREST caches the schema. Without this the tables exist in Postgres and
-- stay invisible to every client until the container restarts.
NOTIFY pgrst, 'reload schema';

-- ============================================================
-- READ-BACK VERIFICATION — run this, paste the output into the PR, and only
-- then change STATUS at the top of this file.
-- ============================================================
--   select table_name, count(*) as columns
--     from information_schema.columns
--    where table_schema = 'public'
--      and table_name like 'paper_engine_%'
--    group by table_name order by table_name;
--   -- expect 4 rows: events, entry_evals, quotes, trades
--
--   select relname, relrowsecurity from pg_class
--    where relname like 'paper_engine_%';
--   -- expect relrowsecurity = t on all four
--
--   select column_name from information_schema.columns
--    where table_name = 'signal_graveyard' and column_name = 'pass_thresholds';
--   -- expect 1 row
