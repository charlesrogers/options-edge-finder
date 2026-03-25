'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { TICKER_STRATEGIES, TIER_CONFIG, type TickerStrategy } from '@/lib/strategies'
import type { HoldingRow } from '@/lib/supabase'

const TIER_BADGE_COLORS: Record<string, string> = {
  best: 'bg-emerald-500/10 text-emerald-700',
  strong: 'bg-blue-500/10 text-blue-700',
  good: 'bg-violet-500/10 text-violet-700',
  conservative: 'bg-amber-500/10 text-amber-700',
  skip: 'bg-red-500/10 text-red-700',
  untested: 'bg-gray-500/10 text-gray-700',
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
      <Card className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
        <CardContent className="py-3">
          <p className="text-[12px] text-muted-foreground">
            {eligible.length} ticker{eligible.length !== 1 ? 's' : ''} with 100+
            shares
            {ineligible.length > 0 && (
              <span>
                {' '}
                ({ineligible.length} below 100 shares)
              </span>
            )}
          </p>
        </CardContent>
      </Card>

      {eligible.length === 0 ? (
        <Card className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
          <CardContent className="py-12 text-center">
            <p className="text-[13px] text-muted-foreground">
              No holdings with 100+ shares found. Add holdings to get
              recommendations.
            </p>
          </CardContent>
        </Card>
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
                  <Card
                    key={holding.ticker}
                    className="rounded-xl border bg-card/50 shadow-sm shadow-black/[0.04] overflow-hidden opacity-60"
                  >
                    <CardContent className="flex items-center justify-between py-3">
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
                    </CardContent>
                  </Card>
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
    <Card className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden hover:shadow-md hover:shadow-black/[0.06] transition-shadow">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle className="text-[15px] font-semibold">
              {ticker}
            </CardTitle>
            <Badge className={cn('text-[10px]', badgeColor)}>
              {tierConfig?.label ?? 'Untested'}
            </Badge>
          </div>
          <span className="text-[11px] text-muted-foreground">
            {shares} shares ({maxContracts} contract{maxContracts !== 1 ? 's' : ''})
          </span>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* Strategy params */}
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
          <Metric label="OTM Target" value={otmPctDisplay} />
          <Metric label="DTE Range" value={dteDisplay} />
          {strategy?.expectedPnl !== undefined && strategy.expectedPnl !== null && (
            <Metric
              label="Expected P&L"
              value={`$${strategy.expectedPnl.toLocaleString()}`}
            />
          )}
          {strategy?.expectedWinRate !== undefined &&
            strategy.expectedWinRate !== null && (
              <Metric
                label="Win Rate"
                value={`${strategy.expectedWinRate}%`}
              />
            )}
        </div>

        {/* What happens */}
        {strategy?.otmPct && (
          <div className="rounded-lg bg-muted/50 p-3">
            <p className="text-[12px] text-muted-foreground">
              <span className="font-medium text-foreground">What happens:</span>{' '}
              Sell a call {otmPctDisplay} above current price, {dteDisplay} days
              out. Collect premium. If the stock stays below the strike, you keep
              the shares and the premium.
            </p>
          </div>
        )}

        {/* Strategy note */}
        <p className="text-[11px] text-muted-foreground">{strategy?.note}</p>
      </CardContent>
    </Card>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="text-[13px] font-medium">{value}</p>
    </div>
  )
}
