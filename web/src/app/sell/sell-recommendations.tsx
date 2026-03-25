'use client'

import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { TICKER_STRATEGIES, TIER_CONFIG, type TickerStrategy } from '@/lib/strategies'
import type { HoldingRow } from '@/lib/supabase'

const TIER_BADGE_COLORS: Record<string, string> = {
  best: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
  strong: 'bg-blue-500/10 text-blue-700 dark:text-blue-400',
  good: 'bg-violet-500/10 text-violet-700 dark:text-violet-400',
  conservative: 'bg-amber-500/10 text-amber-700 dark:text-amber-400',
  skip: 'bg-red-500/10 text-red-700 dark:text-red-400',
  untested: 'bg-gray-500/10 text-gray-700 dark:text-gray-400',
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

  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-28 animate-pulse rounded-xl border bg-muted/30"
          />
        ))}
      </div>
    )
  }

  // Filter to holdings with >= 100 shares
  const eligible = holdings.filter((h) => h.shares >= 100)
  const ineligible = holdings.filter((h) => h.shares < 100)

  // Pair with strategies and sort by expected P&L desc
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
      {/* Holdings summary */}
      <div className="rounded-lg border px-4 py-3 flex items-start gap-2 border-blue-200 dark:border-blue-500/20">
        <span className="h-2 w-2 rounded-full bg-blue-500 mt-1.5 flex-shrink-0" />
        <div>
          <p className="text-[13px] font-semibold text-blue-800 dark:text-blue-300">
            {eligible.length} ticker{eligible.length !== 1 ? 's' : ''} with 100+
            shares
          </p>
          {ineligible.length > 0 && (
            <p className="text-[12px] text-blue-700 dark:text-blue-400 mt-0.5">
              {ineligible.length} holding{ineligible.length !== 1 ? 's' : ''} below 100 shares (not eligible)
            </p>
          )}
        </div>
      </div>

      {eligible.length === 0 ? (
        <div className="rounded-xl border bg-card text-center py-16 shadow-sm shadow-black/[0.04]">
          <div className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-muted mb-3">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="text-muted-foreground"
            >
              <path d="M16 20V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
              <rect width="20" height="14" x="2" y="6" rx="2" />
            </svg>
          </div>
          <p className="text-[15px] font-medium">No eligible holdings</p>
          <p className="text-[13px] text-muted-foreground mt-1">
            Add holdings with 100+ shares to get recommendations.
          </p>
        </div>
      ) : (
        <>
          {/* Active recommendations */}
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
                Skipped Tickers
              </h2>
              <div className="space-y-2">
                {skipped.map(({ holding, strategy }) => (
                  <div
                    key={holding.ticker}
                    className="rounded-xl border bg-card/50 shadow-sm shadow-black/[0.04] overflow-hidden opacity-60 px-5 py-3 flex items-center justify-between"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-medium">
                        {holding.ticker}
                      </span>
                      <Badge
                        className={cn('text-[10px]', TIER_BADGE_COLORS.skip)}
                      >
                        Skip
                      </Badge>
                    </div>
                    <span className="text-[11px] text-muted-foreground">
                      {strategy?.note ?? 'Not recommended for covered calls.'}
                    </span>
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
  const badgeColor = TIER_BADGE_COLORS[tier] ?? TIER_BADGE_COLORS.untested

  const maxContracts = Math.floor(shares / 100)
  const otmPctDisplay = strategy?.otmPct
    ? `${(strategy.otmPct * 100).toFixed(0)}%`
    : '?'
  const dteDisplay =
    strategy?.minDte && strategy?.maxDte
      ? `${strategy.minDte}-${strategy.maxDte}`
      : '?'

  return (
    <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden hover:shadow-md hover:shadow-black/[0.06] transition-shadow">
      {/* Header */}
      <div className="px-5 pt-4 pb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[15px] font-semibold">{ticker}</span>
          <Badge className={cn('text-[10px]', badgeColor)}>
            {tierConfig?.label ?? 'Untested'}
          </Badge>
        </div>
        <span className="text-[11px] text-muted-foreground">
          {shares} shares ({maxContracts} contract
          {maxContracts !== 1 ? 's' : ''})
        </span>
      </div>

      {/* Content */}
      <div className="px-5 pb-4 space-y-3">
        {/* Strategy params */}
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
          <Metric label="OTM Target" value={otmPctDisplay} />
          <Metric label="DTE Range" value={dteDisplay} />
          {strategy?.expectedPnl !== undefined &&
            strategy.expectedPnl !== null && (
              <Metric
                label="Expected P&L"
                value={`$${strategy.expectedPnl.toLocaleString()}`}
              />
            )}
          {strategy?.expectedWinRate !== undefined &&
            strategy.expectedWinRate !== null && (
              <Metric label="Win Rate" value={`${strategy.expectedWinRate}%`} />
            )}
        </div>

        {/* What happens */}
        {strategy?.otmPct && (
          <div className="rounded-lg bg-muted/50 px-4 py-3">
            <p className="text-[12px] text-muted-foreground">
              <span className="font-medium text-foreground">
                What happens:
              </span>{' '}
              Sell a call {otmPctDisplay} above current price, {dteDisplay} days
              out. Collect premium. If the stock stays below the strike, you keep
              the shares and the premium.
            </p>
          </div>
        )}

        {/* Strategy note */}
        {strategy?.note && (
          <p className="text-[11px] text-muted-foreground">{strategy.note}</p>
        )}
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="text-[13px] font-medium mt-0.5">{value}</p>
    </div>
  )
}
