import { NextResponse } from 'next/server'
import { getSupabase } from '@/lib/supabase'
import { isMarketOpen, tradingDaysSince } from '@/lib/market-calendar'
import {
  HEARTBEAT_STALE_MINUTES,
  assertPublicSafe,
  cached,
  summarizeHeartbeats,
  type ChainStatus,
  type HeartbeatRow,
} from '@/lib/live-evidence'

export const dynamic = 'force-dynamic'

/*
 * The read-only projection of "is this thing awake", for the page to render.
 *
 * /api/cron/health is the alarm: it judges seven subsystems and POSTs to
 * Discord, and it is gated on CRON_SECRET. This is not that. It answers one
 * question for the reader of /how-it-works — when did each monitoring chain
 * last run — and it answers it WITHOUT the ops secret, because a liveness
 * claim only the operator can verify is not evidence.
 *
 * It carries no gate of its own: it inherits whatever the app's middleware
 * applies to the page that reads it, so a reader who can load /how-it-works can
 * always load this, and one who cannot, cannot. That is the intended coupling —
 * the widget must never be visible to a stricter or looser audience than the
 * argument it supports.
 *
 * What it must never become: a second copy of the health endpoint's judgement.
 * It imports HEARTBEAT_STALE_MINUTES and the state machine from
 * lib/live-evidence.ts, which /api/cron/health imports too. If the alarm's
 * definition of "alive" changes, this changes with it or neither does.
 *
 * Disclosure surface, deliberately narrow, so it is safe at either setting:
 * timestamps, ages, and which scheduler wrote them. No positions, no strikes,
 * no P&L, no detail strings. Everything here is already visible in the public
 * repo's workflow files.
 */

/** chain1 = Hetzner cron -> copilot.ts. primary = GitHub Actions -> position_monitor.py. */
const ROLES = ['chain1', 'primary'] as const

const CHAIN_LABEL: Record<string, string> = {
  chain1: 'Chain 1 — server cron',
  primary: 'Chain 2 — GitHub Actions',
}

export async function GET() {
  const payload = await cached('status', build)
  // Checked on the way out, on every request including cache hits — the guard
  // must not be skippable by the path a change is most likely to take.
  assertPublicSafe(payload)
  return NextResponse.json(payload, { headers: { 'Cache-Control': 'no-store' } })
}

async function build() {
  const now = new Date()
  const marketOpen = isMarketOpen(now)

  let chains: ChainStatus[]
  let capture: { date: string | null; tradingDaysAgo: number | null } = {
    date: null,
    tradingDaysAgo: null,
  }
  const errors: string[] = []

  try {
    const sb = getSupabase()
    // 60 rows covers well over a day of both chains at 15-minute cadence, so
    // the "chain 2 has not run since yesterday" case is still visible here
    // rather than being cut off by the limit and read as "never".
    // Filter to the monitor's own roles: the paper engine writes ~26 rows/day
    // to this table under role 'paper-engine' and would evict the monitor's
    // rows from this window, shrinking the visible history it exists to show.
    const { data, error } = await sb
      .from('monitor_heartbeats')
      .select('ran_at, ok, source, role, engine')
      .in('role', [...ROLES, 'fallback'])
      .order('ran_at', { ascending: false })
      .limit(60)
    if (error) throw new Error(error.message)
    chains = summarizeHeartbeats((data ?? []) as HeartbeatRow[], [...ROLES], {
      now,
      marketOpen,
      tradingDaysSince,
    })
  } catch (e) {
    // A read that fails is not "no news". It is reported as an error and the
    // widget renders it as such — never as a quiet absence of chains.
    errors.push(`monitor_heartbeats unreadable: ${e instanceof Error ? e.message : String(e)}`)
    chains = []
  }

  try {
    const sb = getSupabase()
    const { data, error } = await sb
      .from('option_chain_snapshots')
      .select('date')
      .order('date', { ascending: false })
      .limit(1)
    if (error) throw new Error(error.message)
    if (data?.[0]) {
      const date = String(data[0].date).slice(0, 10)
      // Anchored to the close so a same-day capture is not counted a session old.
      capture = { date, tradingDaysAgo: tradingDaysSince(new Date(`${date}T20:00:00Z`), now) }
    }
  } catch (e) {
    errors.push(`option_chain_snapshots unreadable: ${e instanceof Error ? e.message : String(e)}`)
  }

  return {
    generatedAt: now.toISOString(),
    marketOpen,
    staleAfterMinutes: HEARTBEAT_STALE_MINUTES,
    chains: chains.map((c) => ({ ...c, label: CHAIN_LABEL[c.role] ?? c.role })),
    capture,
    errors,
  }
}
