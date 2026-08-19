'use client'

import { useEffect, useState } from 'react'

/*
 * The page proving the system is awake while you read it.
 *
 * Everything here comes from /api/status, which reads the same heartbeat table
 * the alerting reads and applies the same staleness rule (the constant lives in
 * lib/live-evidence.ts and /api/cron/health imports it too). Nothing on this
 * card is a constant typed into a component — that defect, a fossil pretending
 * to be live data, is the reason this whole page exists.
 *
 * The rule that makes it evidence rather than decoration: it must be capable of
 * saying the system is down. A widget that can only render green proves
 * nothing. Fetch failure renders as "cannot tell", never as healthy.
 */

interface Chain {
  role: string
  label: string
  source: string | null
  engine: string | null
  lastRunAt: string | null
  ageMinutes: number | null
  state: 'live' | 'stale' | 'failed' | 'never'
}

interface Status {
  generatedAt: string
  marketOpen: boolean
  staleAfterMinutes: number
  chains: Chain[]
  capture: { date: string | null; tradingDaysAgo: number | null }
  errors: string[]
}

const STATE_STYLE: Record<Chain['state'], { dot: string; text: string; word: string }> = {
  live: { dot: 'bg-emerald-500', text: 'text-emerald-600 dark:text-emerald-400', word: 'Running' },
  stale: { dot: 'bg-amber-500', text: 'text-amber-600 dark:text-amber-400', word: 'Stale' },
  failed: { dot: 'bg-red-500', text: 'text-red-600 dark:text-red-400', word: 'Last run failed' },
  never: { dot: 'bg-red-500', text: 'text-red-600 dark:text-red-400', word: 'No heartbeat ever' },
}

function age(minutes: number | null): string {
  if (minutes === null) return '—'
  if (minutes < 90) return `${minutes} min ago`
  const h = Math.round(minutes / 60)
  if (h < 36) return `${h} h ago`
  return `${Math.round(h / 24)} days ago`
}

export function LiveStatus() {
  const [status, setStatus] = useState<Status | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [fetchedAt, setFetchedAt] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const resp = await fetch('/api/status', { cache: 'no-store' })
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
        const data: Status = await resp.json()
        if (!alive) return
        setStatus(data)
        setError(null)
        setFetchedAt(new Date().toLocaleTimeString())
      } catch (e) {
        if (!alive) return
        // Keep the last good reading on screen but say plainly that it is the
        // last good reading. Silently showing a stale green card is the exact
        // failure this section is about.
        setError(e instanceof Error ? e.message : String(e))
      }
    }
    load()
    const t = setInterval(load, 60_000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  return (
    <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
      <div className="px-5 pt-4 pb-3 border-b flex items-start justify-between gap-4">
        <div>
          <p className="text-[14px] font-semibold text-foreground">Right now, as you read this</p>
          <p className="text-[12px] text-muted-foreground mt-0.5 leading-relaxed">
            Read from the monitor heartbeat table on load and every 60 seconds, through{' '}
            <code className="text-[11px]">/api/status</code> &mdash; the same table and the same
            staleness limit ({status?.staleAfterMinutes ?? 35} min during market hours) the
            alerting itself uses. Not a number typed into this page.
          </p>
        </div>
        {status && (
          <span className="hidden sm:inline-flex flex-shrink-0 items-center rounded-4xl px-2.5 py-0.5 text-[10px] font-medium ring-1 ring-inset bg-muted text-muted-foreground ring-border">
            Market {status.marketOpen ? 'open' : 'closed'}
          </span>
        )}
      </div>

      {!status && !error && (
        <div className="px-5 py-6 text-[12px] text-muted-foreground">Reading the heartbeat…</div>
      )}

      {!status && error && (
        <div className="px-5 py-6">
          <p className="text-[13px] font-semibold text-red-600 dark:text-red-400">
            Cannot tell — the status endpoint did not answer
          </p>
          <p className="mt-1 text-[12px] text-muted-foreground leading-relaxed">
            {error}. That is not the same as &ldquo;everything is fine&rdquo;, and this card will
            not pretend it is.
          </p>
        </div>
      )}

      {status && (
        <>
          {status.chains.map((c) => {
            const s = STATE_STYLE[c.state]
            return (
              <div key={c.role} className="border-b px-5 py-3.5">
                <div className="flex items-baseline gap-2.5 flex-wrap">
                  <span className={`h-2 w-2 rounded-full flex-shrink-0 ${s.dot}`} />
                  <span className="text-[13px] font-semibold text-foreground">{c.label}</span>
                  <span className={`text-[12px] font-medium ${s.text}`}>{s.word}</span>
                  <span className="text-[12px] text-muted-foreground tabular-nums">
                    last run {age(c.ageMinutes)}
                  </span>
                </div>
                <p className="mt-1 text-[11px] text-muted-foreground/70 leading-relaxed">
                  {c.engine ?? 'engine unknown'}
                  {c.source ? ` · scheduled by ${c.source}` : ''}
                  {c.lastRunAt ? ` · ${new Date(c.lastRunAt).toISOString().replace('T', ' ').slice(0, 19)} UTC` : ''}
                </p>
              </div>
            )
          })}

          <div className="border-b px-5 py-3.5">
            <div className="flex items-baseline gap-2.5 flex-wrap">
              <span
                className={`h-2 w-2 rounded-full flex-shrink-0 ${
                  status.capture.tradingDaysAgo !== null && status.capture.tradingDaysAgo <= 1
                    ? 'bg-emerald-500'
                    : 'bg-amber-500'
                }`}
              />
              <span className="text-[13px] font-semibold text-foreground">Option chain capture</span>
              <span className="text-[12px] text-muted-foreground tabular-nums">
                {status.capture.date
                  ? `${status.capture.date} · ${status.capture.tradingDaysAgo} trading day(s) ago`
                  : 'no capture found'}
              </span>
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground/70 leading-relaxed">
              Counted in trading days, not hours — a wall-clock rule turned this red every
              Saturday night and nobody read the channel after that.
            </p>
          </div>

          {status.errors.length > 0 && (
            <div className="border-b px-5 py-3 bg-red-50/50 dark:bg-red-500/5">
              {status.errors.map((e) => (
                <p key={e} className="text-[11px] text-red-700 dark:text-red-400 leading-relaxed">
                  {e}
                </p>
              ))}
            </div>
          )}

          <div className="px-5 py-2.5 bg-muted/20">
            <p className="text-[10px] text-muted-foreground/70 tabular-nums">
              Server generated {status.generatedAt.replace('T', ' ').slice(0, 19)} UTC
              {fetchedAt ? ` · fetched by this page at ${fetchedAt}` : ''}
              {error ? ` · last refresh failed (${error}) — figures above are the last good read` : ''}
            </p>
          </div>
        </>
      )}
    </div>
  )
}
