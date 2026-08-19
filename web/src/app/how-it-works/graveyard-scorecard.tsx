'use client'

import { useEffect, useState } from 'react'

/*
 * "Most of what we tested did not work, and we can show you every failure."
 *
 * That sentence is only worth saying if the number behind it is the live one.
 * Read from /api/graveyard, which selects straight out of signal_graveyard —
 * the table register_hypotheses.py writes to before any test is run. A
 * hardcoded "9 failed" would be the fossil bug wearing a humble face.
 *
 * The scorecard is allowed to embarrass us. If `deployed` is zero, it renders
 * zero. If a status appears that this code does not recognise, it renders as
 * `other` and says so rather than being folded into a bucket that flatters.
 */

interface Signal {
  id: string
  name: string | null
  tier: number | null
  status: string
  outcome: 'failed' | 'deployed' | 'untested' | 'other'
  layerReached: number | null
  testedDate: string | null
}

interface Summary {
  generatedAt: string
  registered: number
  tested: number
  failed: number
  deployed: number
  untested: number
  other: number
  signals: Signal[]
  error?: string
}

const OUTCOME_STYLE: Record<Signal['outcome'], string> = {
  failed: 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 ring-red-600/20',
  deployed:
    'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 ring-emerald-600/20',
  untested: 'bg-gray-50 dark:bg-gray-500/10 text-gray-700 dark:text-gray-400 ring-gray-600/20',
  other: 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 ring-amber-600/20',
}

export function GraveyardScorecard() {
  const [data, setData] = useState<Summary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    fetch('/api/graveyard', { cache: 'no-store' })
      .then(async (r) => {
        const body = await r.json()
        if (!r.ok) throw new Error(body?.error ?? `HTTP ${r.status}`)
        return body as Summary
      })
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)))
    return () => {
      alive = false
    }
  }, [])

  if (error) {
    return (
      <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] px-5 py-4">
        <p className="text-[13px] font-semibold text-red-600 dark:text-red-400">
          The graveyard table did not answer
        </p>
        <p className="mt-1 text-[12px] text-muted-foreground leading-relaxed">
          {error}. The count is deliberately not hardcoded, so when the table is unreadable this
          card has nothing to show — which is the correct behaviour, not a bug to paper over.
        </p>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] px-5 py-4">
        {/*
          The endpoint is named in the FIRST render, not only in the loaded
          footnote, so it is present in the server HTML — which is what
          scripts/verify_production_claims.py can actually see, and what a
          reader with the page source open can check for themselves.
        */}
        <p className="text-[12px] text-muted-foreground">
          Reading the graveyard from <code className="text-[11px]">/api/graveyard</code>…
        </p>
      </div>
    )
  }

  const stats = [
    { label: 'Pre-registered', value: data.registered, tone: 'text-foreground' },
    { label: 'Tested', value: data.tested, tone: 'text-foreground' },
    { label: 'Failed', value: data.failed, tone: 'text-red-600 dark:text-red-400' },
    { label: 'Deployed', value: data.deployed, tone: 'text-foreground' },
  ]

  return (
    <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
      <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-y sm:divide-y-0">
        {stats.map((s) => (
          <div key={s.label} className="px-5 py-4">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              {s.label}
            </p>
            <p className={`mt-1 text-3xl font-semibold tracking-tight tabular-nums ${s.tone}`}>
              {s.value}
            </p>
          </div>
        ))}
      </div>

      <div className="px-5 py-3 border-t bg-muted/20">
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Live from the <code className="text-[10px]">signal_graveyard</code> table via{' '}
          <code className="text-[10px]">/api/graveyard</code>, which you can read yourself, at{' '}
          <span className="tabular-nums">{data.generatedAt.replace('T', ' ').slice(0, 19)} UTC</span>
          . {data.untested > 0 && `${data.untested} more are registered and not yet tested. `}
          {data.other > 0 &&
            `${data.other} carry a status this page does not classify — shown below rather than folded into a bucket. `}
          {data.deployed === 0 &&
            'Nothing in this table has been deployed: every signal tested so far failed its own pre-registered threshold. The rules the tool ships with come from the covered-call work, not from these signals.'}
        </p>
      </div>

      <details className="px-5 py-3 border-t">
        <summary className="cursor-pointer text-[11px] text-muted-foreground hover:text-foreground list-none marker:hidden">
          <span className="underline decoration-dotted underline-offset-4">
            Every signal in the table, pass and fail
          </span>
        </summary>
        <div className="mt-3 space-y-1.5">
          {data.signals.map((s) => (
            <div key={s.id} className="flex items-baseline gap-2.5 flex-wrap">
              <span className="text-[12px] font-semibold text-foreground tabular-nums w-10">
                {s.id}
              </span>
              <span
                className={`inline-flex items-center rounded-4xl px-2 py-0.5 text-[10px] font-medium ring-1 ring-inset ${OUTCOME_STYLE[s.outcome]}`}
              >
                {s.outcome}
              </span>
              <span className="text-[12px] text-muted-foreground">{s.name ?? '—'}</span>
              {s.outcome === 'failed' && s.layerReached !== null && (
                <span className="text-[11px] text-muted-foreground/60">
                  died at layer {s.layerReached}
                </span>
              )}
            </div>
          ))}
        </div>
      </details>
    </div>
  )
}
