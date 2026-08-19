/*
 * The reliability diagram.
 *
 * Verified against the live server on 2026-08-19 rather than transcribed from
 * docs/crons.md — which described chain 1 as disabled nine hours after it
 * started firing every fifteen minutes. What is deliberately NOT here: whether
 * any of it ran today. That claim rots within the hour, so it belongs to the
 * live widget below this component, not to prose.
 *
 * What IS here is the structural argument, which does not rot hourly: two
 * independent assessment chains running two different engines, and two
 * watchdogs on two providers neither chain controls.
 */

interface Lane {
  kind: 'assess' | 'watch'
  name: string
  provider: string
  schedule: string
  runs: string
  delivers: string
  /** Present only where delivery is currently broken. Named, never softened. */
  deliveryGap?: string
  death: string
}

const LANES: Lane[] = [
  {
    kind: 'assess',
    name: 'Chain 1 — server cron',
    provider: 'Hetzner',
    schedule: 'Every 15 min, 13:00–21:59 UTC, Mon–Fri',
    runs: 'Calls the app’s /api/cron/monitor, which assesses every open position with the TypeScript engine, then writes a heartbeat and reads it back to confirm it persisted',
    delivers: 'Discord, if the route itself errors',
    deliveryGap:
      'Position alerts from this chain go to Pushover, which has no credentials — an EMERGENCY raised here is written to the log and delivered nowhere. Chain 2 covers the same positions and does deliver; that is the only reason this is a gap and not an outage.',
    death: 'Its heartbeat stops, the health endpoint fails on staleness, and both watchdogs page.',
  },
  {
    kind: 'assess',
    name: 'Chain 2 — GitHub Actions',
    provider: 'GitHub',
    schedule: 'Every 15 min, 13:00–21:59 UTC, Mon–Fri',
    runs: 'position_monitor.py — a separate implementation of the same ladder, against the same positions, writing its own heartbeat',
    delivers: 'Discord (it refuses to run at all with no working channel)',
    death: 'Same heartbeat path, plus an if: failure() Discord post on the workflow itself.',
  },
  {
    kind: 'watch',
    name: 'Inner watchdog',
    provider: 'Hetzner',
    schedule: 'Every 30 min during market hours, plus 01:20 and 07:20 UTC',
    runs: 'Curls /api/cron/health and reads the verdict — it does not judge for itself',
    delivers: 'Discord on any non-200 or timeout',
    death: 'It alerts on its own failure. It cannot report that the box it runs on is gone — that is what the outer loop is for.',
  },
  {
    kind: 'watch',
    name: 'Outer watchdog',
    provider: 'Cloudflare',
    schedule: 'Every 30 min, always',
    runs: 'A Worker polling the same health endpoint from a third provider — one GitHub cannot disable and the server cannot take down with it',
    delivers: 'Discord on any non-200 or timeout',
    death: 'Nothing watches it. Accepted residual risk; the mitigation is a monthly trip-test, which is not yet scheduled.',
  },
]

const KIND_LABEL = {
  assess: 'Assesses positions',
  watch: 'Watches the watchers',
} as const

export function ReliabilityChains() {
  return (
    <div className="space-y-4">
      {(['assess', 'watch'] as const).map((kind) => (
        <div
          key={kind}
          className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden"
        >
          <div className="px-5 py-2.5 border-b bg-muted/30">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              {KIND_LABEL[kind]}
            </p>
          </div>
          {LANES.filter((l) => l.kind === kind).map((l) => (
            <div key={l.name} className="border-b last:border-b-0 px-5 py-4">
              <div className="flex items-baseline gap-2.5 flex-wrap">
                <p className="text-[13px] font-semibold text-foreground">{l.name}</p>
                <span className="inline-flex items-center rounded-4xl px-2 py-0.5 text-[10px] font-medium ring-1 ring-inset bg-muted text-muted-foreground ring-border">
                  {l.provider}
                </span>
                <span className="text-[11px] text-muted-foreground tabular-nums">{l.schedule}</span>
              </div>
              <p className="mt-1.5 text-[12px] text-muted-foreground leading-relaxed">{l.runs}</p>
              <p className="mt-1 text-[11px] text-muted-foreground/70 leading-relaxed">
                <span className="font-medium">Wakes you through:</span> {l.delivers}
              </p>
              <p className="mt-0.5 text-[11px] text-muted-foreground/70 leading-relaxed">
                <span className="font-medium">How you would know it died:</span> {l.death}
              </p>
              {l.deliveryGap && (
                <p className="mt-2 rounded-lg border border-amber-200 dark:border-amber-500/20 bg-amber-50/50 dark:bg-amber-500/5 px-3 py-2 text-[11px] text-amber-800/90 dark:text-amber-300/90 leading-relaxed">
                  {l.deliveryGap}
                </p>
              )}
            </div>
          ))}
        </div>
      ))}

      <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] px-5 py-4">
        <p className="text-[13px] font-semibold text-foreground">
          Why the duplication is the design, not waste
        </p>
        <p className="mt-1.5 text-[12px] text-muted-foreground leading-relaxed">
          Three providers &mdash; Hetzner, GitHub, Cloudflare &mdash; and no single one of them can
          silence the system. That matters because the failure that actually happened was not a
          crash: GitHub auto-disabled all seven scheduled workflows after sixty days of repo
          inactivity, and nothing errored, so nothing alerted. The second assessment chain exists
          for the same reason, and it has already earned it: on 19 August the GitHub scheduler ran
          the monitor once in fifty minutes while the server cron kept its fifteen-minute cadence
          throughout. Two chains, two engines, and a health check that alarms on the{' '}
          <em>absence</em> of a heartbeat rather than on an error.
        </p>
      </div>
    </div>
  )
}
