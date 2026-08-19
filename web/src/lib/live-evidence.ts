/**
 * The facts /how-it-works publishes about itself, as data rather than prose.
 *
 * Two sections of that page make claims that rot: "the monitor is running" and
 * "most of what we tested failed". Both were prose in checkpoint 1, and prose
 * about infrastructure was wrong twice inside two days — the crontab doc still
 * described a monitor line as disabled nine hours after it started firing every
 * fifteen minutes. Prose has no failure mode that anyone notices.
 *
 * So the page reads these from the same tables the alerting reads, through
 * /api/status and /api/graveyard, and renders whatever is actually there —
 * including "stale" and including a count that disagrees with the sales pitch.
 *
 * Everything here is pure and dependency-free (the clock and the calendar are
 * passed in) so scripts/check_live_evidence_fixture.mjs can execute it directly.
 * The states that matter are the broken ones, which never occur in a browser
 * you happen to be looking at.
 */

/**
 * How stale a heartbeat may get during market hours before it is an outage.
 *
 * One monitor cycle is 15 minutes; two missed cycles is real, not scheduler
 * jitter. /api/cron/health imports this same constant — the widget and the
 * alarm must not be able to disagree about what "alive" means.
 */
export const HEARTBEAT_STALE_MINUTES = 35

/* ── Monitor heartbeats ─────────────────────────────────────────────────── */

export interface HeartbeatRow {
  ran_at: string
  ok: boolean | null
  source: string | null
  role: string | null
  /** Which implementation ran: copilot.ts via the route, or position_monitor.py. */
  engine: string | null
}

export type ChainState = 'live' | 'stale' | 'failed' | 'never'

export interface ChainStatus {
  /** `role` as written by the writer: chain1 (server cron) or chain2 (GH Actions). */
  role: string
  /** Which scheduler wrote it — hetzner-cron, github-actions. */
  source: string | null
  /** Which engine it ran. The two chains run different code on purpose. */
  engine: string | null
  lastRunAt: string | null
  ageMinutes: number | null
  state: ChainState
}

export interface HeartbeatDeps {
  now: Date
  marketOpen: boolean
  /** Injected so this module stays dependency-free; see market-calendar.ts. */
  tradingDaysSince: (since: Date, now: Date) => number
}

/**
 * Latest heartbeat per role, with an honest state for each.
 *
 * Deliberately NOT collapsed to a single "is it alive" boolean. The two chains
 * run different engines against the same positions, and the interesting failure
 * is one of them dying while the other keeps the aggregate green — which is
 * exactly what happened on 2026-08-19, when GitHub ran once all morning while
 * the server cron fired every fifteen minutes.
 */
export function summarizeHeartbeats(
  rows: HeartbeatRow[],
  roles: string[],
  deps: HeartbeatDeps
): ChainStatus[] {
  return roles.map((role) => {
    const latest = rows
      .filter((r) => (r.role ?? '') === role)
      .sort((a, b) => b.ran_at.localeCompare(a.ran_at))[0]

    if (!latest) {
      return {
        role,
        source: null,
        engine: null,
        lastRunAt: null,
        ageMinutes: null,
        state: 'never' as const,
      }
    }

    const ranAt = new Date(latest.ran_at)
    const ageMinutes = Math.round((deps.now.getTime() - ranAt.getTime()) / 60_000)

    // Order matters: a run that FAILED is not rescued by being recent.
    let state: ChainState
    if (latest.ok === false) {
      state = 'failed'
    } else if (deps.marketOpen && ageMinutes > HEARTBEAT_STALE_MINUTES) {
      state = 'stale'
    } else if (!deps.marketOpen && deps.tradingDaysSince(ranAt, deps.now) > 1) {
      // Overnight and weekends: age in minutes is meaningless by design, so the
      // question is whether a whole trading session went by without a run.
      state = 'stale'
    } else {
      state = 'live'
    }

    return {
      role,
      source: latest.source,
      engine: latest.engine,
      lastRunAt: latest.ran_at,
      ageMinutes,
      state,
    }
  })
}

/* ── The hypothesis graveyard ───────────────────────────────────────────── */

export interface GraveyardRow {
  signal_id: string
  name: string | null
  tier: number | null
  status: string
  layer_reached: number | null
  tested_date: string | null
}

export type SignalOutcome = 'failed' | 'deployed' | 'untested' | 'other'

export interface GraveyardSignal {
  id: string
  name: string | null
  tier: number | null
  status: string
  outcome: SignalOutcome
  layerReached: number | null
  testedDate: string | null
}

export interface GraveyardSummary {
  registered: number
  tested: number
  failed: number
  deployed: number
  untested: number
  /** Statuses this code does not recognise. Never folded into another bucket. */
  other: number
  signals: GraveyardSignal[]
}

function outcomeOf(status: string): SignalOutcome {
  if (status === 'untested') return 'untested'
  if (status.startsWith('failed')) return 'failed'
  if (status === 'deployed') return 'deployed'
  // An unrecognised status must not quietly become a pass or disappear from the
  // count. The page renders `other` when it is non-zero and says so.
  return 'other'
}

export function summarizeGraveyard(rows: GraveyardRow[]): GraveyardSummary {
  const signals: GraveyardSignal[] = rows
    .map((r) => ({
      id: r.signal_id,
      name: r.name,
      tier: r.tier,
      status: r.status,
      outcome: outcomeOf(r.status),
      layerReached: r.layer_reached,
      testedDate: r.tested_date,
    }))
    .sort((a, b) => a.id.localeCompare(b.id, undefined, { numeric: true }))

  const count = (o: SignalOutcome) => signals.filter((s) => s.outcome === o).length
  const untested = count('untested')

  return {
    registered: signals.length,
    tested: signals.length - untested,
    failed: count('failed'),
    deployed: count('deployed'),
    untested,
    other: count('other'),
    signals,
  }
}
