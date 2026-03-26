'use client'

import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import { TICKER_STRATEGIES, TIER_CONFIG, DEFAULT_IV_THRESHOLD, type TickerStrategy } from '@/lib/strategies'
import type { HoldingRow } from '@/lib/supabase'

/* ── Tier visual system (ring-inset badges like Jebbix grade badges) ── */

const TIER_BADGE: Record<string, string> = {
  best: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 ring-emerald-600/20',
  strong: 'bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-400 ring-blue-600/20',
  good: 'bg-violet-50 dark:bg-violet-500/10 text-violet-700 dark:text-violet-400 ring-violet-600/20',
  conservative: 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 ring-amber-600/20',
  skip: 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 ring-red-600/20',
  untested: 'bg-gray-50 dark:bg-gray-500/10 text-gray-700 dark:text-gray-400 ring-gray-600/20',
}

const TIER_ACCENT: Record<string, string> = {
  best: 'bg-emerald-500',
  strong: 'bg-blue-500',
  good: 'bg-violet-500',
  conservative: 'bg-amber-500',
  skip: 'bg-red-500',
  untested: 'bg-gray-400',
}

const TIER_VALUE_COLOR: Record<string, string> = {
  best: 'text-emerald-600 dark:text-emerald-400',
  strong: 'text-blue-600 dark:text-blue-400',
  good: 'text-violet-600 dark:text-violet-400',
  conservative: 'text-amber-600 dark:text-amber-400',
  skip: 'text-red-600 dark:text-red-400',
  untested: 'text-gray-500',
}

export function SellRecommendations() {
  const [holdings, setHoldings] = useState<HoldingRow[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch('/api/holdings')
        if (res.ok) {
          setHoldings(await res.json())
        }
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  /* ── Loading skeleton ── */
  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="rounded-xl border bg-card overflow-hidden">
            <div className="px-5 pt-4 pb-4 space-y-3">
              <div className="flex items-center gap-3">
                <div className="h-5 w-20 rounded-md bg-muted animate-pulse" />
                <div className="h-5 w-14 rounded-md bg-muted animate-pulse" />
              </div>
              <div className="grid grid-cols-4 gap-4">
                {[1, 2, 3, 4].map((j) => (
                  <div key={j} className="space-y-1.5">
                    <div className="h-7 w-16 rounded bg-muted animate-pulse" />
                    <div className="h-3 w-14 rounded bg-muted/60 animate-pulse" />
                  </div>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>
    )
  }

  const eligible = holdings.filter((h) => h.shares >= 100)
  const ineligible = holdings.filter((h) => h.shares < 100)

  const paired = eligible
    .map((h) => ({
      holding: h,
      strategy: TICKER_STRATEGIES[h.ticker] as TickerStrategy | undefined,
    }))
    .sort((a, b) => {
      const aPnl = a.strategy?.expectedPnl ?? -Infinity
      const bPnl = b.strategy?.expectedPnl ?? -Infinity
      return bPnl - aPnl
    })

  const skipped = paired.filter((p) => p.strategy?.tier === 'skip')
  const active = paired.filter((p) => p.strategy?.tier !== 'skip')

  return (
    <div className="space-y-6">
      {/* Holdings summary info bar */}
      <div className="rounded-lg border border-blue-200 dark:border-blue-500/20 bg-blue-50/50 dark:bg-blue-500/5 px-4 py-3 flex items-start gap-2.5">
        <span className="h-2 w-2 rounded-full bg-blue-500 mt-1.5 flex-shrink-0" />
        <div>
          <p className="text-[13px] font-semibold text-blue-800 dark:text-blue-300">
            {eligible.length} ticker{eligible.length !== 1 ? 's' : ''} with 100+ shares
          </p>
          {ineligible.length > 0 && (
            <p className="text-[12px] text-blue-700/80 dark:text-blue-400/70 mt-0.5">
              {ineligible.length} holding{ineligible.length !== 1 ? 's' : ''} below 100 shares (not eligible for covered calls)
            </p>
          )}
        </div>
      </div>

      {/* IV threshold notice */}
      <div className="rounded-lg border border-amber-200 dark:border-amber-500/20 bg-amber-50/50 dark:bg-amber-500/5 px-4 py-3 flex items-start gap-2.5">
        <span className="h-2 w-2 rounded-full bg-amber-500 mt-1.5 flex-shrink-0" />
        <div>
          <p className="text-[13px] font-semibold text-amber-800 dark:text-amber-300">
            IV-aware entry (Experiment 009: +204% P&L improvement)
          </p>
          <p className="text-[12px] text-amber-700/80 dark:text-amber-400/70 mt-0.5">
            Only sell when IV Rank &ge; {DEFAULT_IV_THRESHOLD}. Low IV months are automatically skipped by the paper trading tracker.
          </p>
        </div>
      </div>

      {/* Empty state */}
      {eligible.length === 0 ? (
        <div className="rounded-xl border bg-card text-center py-16 shadow-sm shadow-black/[0.04]">
          <div className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-muted mb-4">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-muted-foreground">
              <path d="M16 20V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
              <rect width="20" height="14" x="2" y="6" rx="2" />
            </svg>
          </div>
          <p className="text-[15px] font-semibold text-foreground">No eligible holdings</p>
          <p className="text-[13px] text-muted-foreground mt-1">
            Add holdings with 100+ shares to get recommendations.
          </p>
        </div>
      ) : (
        <>
          {/* Active recommendation cards */}
          <div className="space-y-3">
            {active.map(({ holding, strategy }) => (
              <TickerCard
                key={holding.ticker}
                ticker={holding.ticker}
                shares={holding.shares}
                strategy={strategy}
              />
            ))}
          </div>

          {/* Skipped tickers */}
          {skipped.length > 0 && (
            <div>
              <h2 className="mb-2 text-[14px] font-semibold text-muted-foreground">
                Not Recommended
              </h2>
              <div className="space-y-2">
                {skipped.map(({ holding, strategy }) => (
                  <div
                    key={holding.ticker}
                    className="rounded-xl border bg-card/50 shadow-sm shadow-black/[0.04] overflow-hidden"
                  >
                    <div className="px-5 py-3 flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2.5">
                        <span className="text-[13px] font-semibold text-muted-foreground">
                          {holding.ticker}
                        </span>
                        <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold ring-1 ring-inset bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 ring-red-600/20">
                          Skip
                        </span>
                      </div>
                      <span className="text-[11px] text-muted-foreground/70 truncate">
                        {strategy?.note ?? 'Not recommended for covered calls.'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

/* ── Ticker Recommendation Card ── */

function TickerCard({
  ticker,
  shares,
  strategy,
}: {
  ticker: string
  shares: number
  strategy: TickerStrategy | undefined
}) {
  const tier = strategy?.tier ?? 'untested'
  const tierConfig = TIER_CONFIG[tier]
  const maxContracts = Math.floor(shares / 100)
  const otmPctDisplay = strategy?.otmPct ? `${(strategy.otmPct * 100).toFixed(0)}%` : '--'
  const dteDisplay = strategy?.minDte && strategy?.maxDte ? `${strategy.minDte}-${strategy.maxDte}` : '--'
  const winRateNum = strategy?.expectedWinRate ?? 0

  return (
    <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden hover:shadow-md hover:shadow-black/[0.06] transition-shadow">
      <div className="min-w-0">
        {/* Header */}
        <div className="px-5 pt-4 pb-3 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <h3 className="text-[15px] font-semibold text-foreground">{ticker}</h3>
            <span className={cn(
              'inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-semibold ring-1 ring-inset',
              TIER_BADGE[tier]
            )}>
              {tierConfig?.label ?? 'Untested'}
            </span>
          </div>
          <span className="text-[12px] text-muted-foreground tabular-nums">
            {shares} shares &middot; {maxContracts} contract{maxContracts !== 1 ? 's' : ''}
          </span>
        </div>

        {/* Metrics grid */}
        <div className="px-5 pb-3">
          <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
            {strategy?.expectedPnl !== undefined && strategy.expectedPnl !== null && (
              <MetricCell
                label="Expected P&L"
                value={`$${strategy.expectedPnl.toLocaleString()}`}
                accent={TIER_VALUE_COLOR[tier]}
              />
            )}
            {strategy?.expectedWinRate !== undefined && strategy.expectedWinRate !== null && (
              <MetricCell
                label="Win Rate"
                value={`${strategy.expectedWinRate}%`}
                accent={strategy.expectedWinRate >= 70 ? 'text-emerald-600 dark:text-emerald-400' : undefined}
              />
            )}
            <MetricCell label="OTM Target" value={otmPctDisplay} />
            <MetricCell label="DTE Range" value={dteDisplay} />
          </div>

          {/* Win rate progress bar */}
          {winRateNum > 0 && (
            <div className="mt-3">
              <div className="h-1 rounded-full bg-muted overflow-hidden">
                <div
                  className={cn('h-full rounded-full transition-all', TIER_ACCENT[tier])}
                  style={{ width: `${Math.min(100, winRateNum)}%` }}
                />
              </div>
              <p className="text-[10px] text-muted-foreground/60 mt-1 tabular-nums">
                {winRateNum}% of trades expire worthless (you keep shares + premium)
              </p>
            </div>
          )}
        </div>

        {/* Strategy description */}
        {strategy?.otmPct && (
          <div className="mx-5 mb-3 rounded-lg bg-muted/40 dark:bg-muted/20 px-4 py-3">
            <p className="text-[12px] text-muted-foreground leading-relaxed">
              <span className="font-semibold text-foreground">Sell</span> a call{' '}
              <span className="font-semibold text-foreground">{otmPctDisplay} OTM</span>,{' '}
              <span className="font-semibold text-foreground">{dteDisplay} DTE</span>.{' '}
              Collect premium. If the stock stays below the strike, you keep shares and premium.
            </p>
          </div>
        )}

        {/* Strategy note */}
        {strategy?.note && (
          <div className="px-5 pb-4">
            <p className="text-[11px] text-muted-foreground/70">{strategy.note}</p>
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Metric Cell ── */

function MetricCell({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div>
      <div className={cn('text-2xl font-semibold tracking-tight tabular-nums', accent ?? 'text-foreground')}>
        {value}
      </div>
      <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground mt-0.5">
        {label}
      </div>
    </div>
  )
}
