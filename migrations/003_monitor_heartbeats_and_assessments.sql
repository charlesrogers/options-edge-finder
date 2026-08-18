-- 003 — the two tables the dead-man's switch needs (2026-08-18)
--
-- The failure mode this whole spec exists to defeat is SILENCE. Every alert we
-- have alerts on an explicit failure, which is exactly the class of fault that
-- did NOT happen during the 4.5-month outage: nothing failed, things simply
-- stopped happening. You cannot detect that by watching for errors. You detect
-- it by requiring a positive signal at a known cadence and alarming on its
-- absence.
--
-- monitor_heartbeats is that signal. Every monitor run writes one row whether or
-- not it found anything, and the health check fails when the newest row is older
-- than one monitor interval during market hours.
--
-- position_assessments is the stored-verdict store (spec A1). The web reads
-- these rather than re-deriving a verdict in TypeScript, so the number on the
-- screen and the number in the push notification are the same number, computed
-- once, with an "as of" timestamp attached.

CREATE TABLE IF NOT EXISTS public.monitor_heartbeats (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ran_at                timestamptz NOT NULL DEFAULT now(),

  -- Which copy of the monitor produced this. Two run: the Hetzner cron
  -- (primary, owns notifications) and GitHub Actions (fallback). Recording the
  -- role is what lets the fallback stay quiet while the primary is healthy
  -- instead of double-buzzing Dad's phone for the same event.
  source                text NOT NULL,            -- 'hetzner-cron' | 'github-actions'
  role                  text NOT NULL,            -- 'primary' | 'fallback'
  engine                text NOT NULL,            -- 'position_monitor.py'
  engine_version        text,

  positions_checked     integer NOT NULL DEFAULT 0,
  positions_unassessed  integer NOT NULL DEFAULT 0,
  alerts_fired          integer NOT NULL DEFAULT 0,
  alerts_undelivered    integer NOT NULL DEFAULT 0,

  -- A heartbeat that says "I ran" is not enough; it must say whether what it
  -- ran on was fresh. ok=false means the run completed but its output cannot be
  -- trusted, which the health check treats exactly like no heartbeat at all.
  ok                    boolean NOT NULL,
  detail                jsonb
);

CREATE INDEX IF NOT EXISTS monitor_heartbeats_ran_at_idx
  ON public.monitor_heartbeats (ran_at DESC);
CREATE INDEX IF NOT EXISTS monitor_heartbeats_role_ran_at_idx
  ON public.monitor_heartbeats (role, ran_at DESC);


CREATE TABLE IF NOT EXISTS public.position_assessments (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assessed_at     timestamptz NOT NULL DEFAULT now(),

  trade_id        uuid REFERENCES public.trades(id) ON DELETE CASCADE,
  ticker          text NOT NULL,
  strike          numeric NOT NULL,
  expiry          date NOT NULL,
  contracts       integer NOT NULL,

  level           text NOT NULL,   -- SAFE | WATCH | CLOSE_SOON | CLOSE_NOW | EMERGENCY | UNASSESSED
  reason          text,
  action          text,

  -- Every input the verdict was computed from. Without these a stored verdict
  -- is unauditable after the fact: you cannot tell a correct SAFE from a SAFE
  -- produced by a stale quote.
  inputs          jsonb,

  engine          text NOT NULL,
  engine_version  text,
  source          text NOT NULL
);

CREATE INDEX IF NOT EXISTS position_assessments_trade_assessed_idx
  ON public.position_assessments (trade_id, assessed_at DESC);
CREATE INDEX IF NOT EXISTS position_assessments_assessed_at_idx
  ON public.position_assessments (assessed_at DESC);
