'use client'

import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import { TICKER_STRATEGIES, TIER_CONFIG, DEFAULT_IV_THRESHOLD, type TickerStrategy } from '@/lib/strategies'
import type { HoldingRow } from '@/lib/supabase'

/* ── Tier visual system (ring-inset badges like Jebbix grade badges) ── */

/*
 * Every class string below is a full literal. Do NOT build them by
 * interpolation (`bg-${color}-50`) — Tailwind's JIT scans source text, so a
 * constructed class is purged and the badge silently renders unstyled.
 *
 * Unknown tiers fall back rather than crash: ticker_strategies.py may add a
 * tier before the web knows about it, and a missing badge must never take the
 * page down.
 */
const TIER_FALLBACK_BADGE =
  'bg-gray-50 dark:bg-gray-500/10 text-gray-700 dark:text-gray-400 ring-gray-600/20'

const TIER_BADGE: Record<string, string> = {
  best: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 ring-emerald-600/20',
  strong: 'bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-400 ring-blue-600/20',
  good: 'bg-violet-50 dark:bg-violet-500/10 text-violet-700 dark:text-violet-400 ring-violet-600/20',
  conservative: 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 ring-amber-600/20',
  skip: 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 ring-red-600/20',
  // Probation is deliberately not Untested: untested means nobody looked,
  // probation means we looked with a weaker instrument.
  probation: 'bg-orange-50 dark:bg-orange-500/10 text-orange-700 dark:text-orange-400 ring-orange-600/20',
  untested: 'bg-gray-50 dark:bg-gray-500/10 text-gray-700 dark:text-gray-400 ring-gray-600/20',
}

const TIER_ACCENT: Record<string, string> = {
  best: 'bg-emerald-500',
  strong: 'bg-blue-500',
  good: 'bg-violet-500',
  conservative: 'bg-amber-500',
  skip: 'bg-red-500',
  probation: 'bg-orange-500',
  untested: 'bg-gray-400',
}

const TIER_VALUE_COLOR: Record<string, string> = {
  best: 'text-emerald-600 dark:text-emerald-400',
  strong: 'text-blue-600 dark:text-blue-400',
  good: 'text-violet-600 dark:text-violet-400',
  conservative: 'text-amber-600 dark:text-amber-400',
  skip: 'text-red-600 dark:text-red-400',
  probation: 'text-orange-600 dark:text-orange-400',
  untested: 'text-gray-500',
}

/** '$141', '-$88' — negative money reads as -$88, not $-88. */
function money(n: number): string {
  return `${n < 0 ? '-' : ''}$${Math.abs(n).toLocaleString()}`
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

  /*
   * Partition on the `skip` flag from the source of truth, not on tier.
   * AMZN and MSFT are skips that were reaching the recommendation list: AMZN
   * was live at 5% OTM after failing Exp 021 at the more conservative 15%, and
   * MSFT was absent from the table entirely, so it inherited the unknown-ticker
   * default — also 5% OTM, also more aggressive than the setting it failed.
   *
   * A ticker with no entry at all is likewise not recommendable: an unknown
   * ticker has no validated setting, and rendering it in the active list is how
   * MSFT came to be presented with no warning.
   */
  const skipped = paired.filter((p) => !p.strategy || p.strategy.skip)
  const active = paired.filter((p) => p.strategy && !p.strategy.skip)

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
            IV-rank entry gate
          </p>
          <p className="text-[12px] text-amber-700/80 dark:text-amber-400/70 mt-0.5">
            Per-ticker trial (Exp 023): DIS &ge; 75 validated on holdout; other tickers keep the
            default &ge; {DEFAULT_IV_THRESHOLD}. The gate failed its trial on TMUS and is retained
            pending a loosening experiment. Each ticker&rsquo;s own threshold is shown on its card;
            the gate is enforced by the paper-trade logger.
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
                    <div className="px-5 py-3 space-y-1.5">
                      <div className="flex items-center gap-2.5">
                        <span className="text-[13px] font-semibold text-muted-foreground">
                          {holding.ticker}
                        </span>
                        <span
                          className={cn(
                            'inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold ring-1 ring-inset',
                            strategy ? TIER_BADGE.skip : TIER_FALLBACK_BADGE
                          )}
                        >
                          {strategy ? 'Skip' : 'Not in research set'}
                        </span>
                      </div>
                      {/*
                        The note carries the reason and it is the whole point of
                        the row — never truncate it. AMZN's reads "Exp 021
                        failed AMZN at 15% OTM (22.9% test loss rate vs a 10%
                        gate) and it was live at a more aggressive 5%".
                      */}
                      <p className="text-[11px] text-muted-foreground/70 leading-relaxed">
                        {strategy?.note ??
                          'No validated setting for this ticker. Not recommended for covered calls until it has been tested on real option prices.'}
                      </p>
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

  /*
   * Owning 10,000 shares does not mean 100 contracts can be sold. KKR's
   * 15%-OTM / 20-45 DTE strike trades a MEDIAN of 3 contracts a day (Exp 021):
   * an uncapped position would be 33x the median daily volume of that strike —
   * the position IS the market. 100 was the number a human would have traded
   * on, so the cap and its reason have to be on the card, not in a footnote.
   */
  const uncappedContracts = Math.floor(shares / 100)
  const cap = strategy?.maxContracts ?? null
  const contracts = cap !== null ? Math.min(uncappedContracts, cap) : uncappedContracts
  const isCapped = cap !== null && uncappedContracts > cap

  const otmPctDisplay = strategy?.otmPct ? `${(strategy.otmPct * 100).toFixed(0)}%` : '--'
  const dteDisplay = strategy?.minDte && strategy?.maxDte ? `${strategy.minDte}-${strategy.maxDte}` : '--'
  const winRateNum = strategy?.expectedWinRate ?? 0
  const ivThreshold = strategy?.ivThreshold ?? DEFAULT_IV_THRESHOLD
  const hasRange = strategy?.pnlRangeLow !== null && strategy?.pnlRangeLow !== undefined
    && strategy?.pnlRangeHigh !== null && strategy?.pnlRangeHigh !== undefined

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
            {shares.toLocaleString()} shares &middot;{' '}
            <span className={cn('font-semibold', isCapped && 'text-orange-600 dark:text-orange-400')}>
              {contracts} contract{contracts !== 1 ? 's' : ''}
            </span>
          </span>
        </div>

        {/* Liquidity cap — stated where the size decision is made, not below the fold */}
        {isCapped && (
          <div className="mx-5 mb-3 rounded-lg border border-orange-200 dark:border-orange-500/20 bg-orange-50/60 dark:bg-orange-500/5 px-4 py-3">
            <p className="text-[12px] font-semibold text-orange-800 dark:text-orange-300">
              Capped at {cap} contract{cap !== 1 ? 's' : ''} &mdash; {uncappedContracts} would fit your{' '}
              {shares.toLocaleString()} shares
            </p>
            <p className="text-[11px] text-orange-700/80 dark:text-orange-400/70 mt-0.5 leading-relaxed">
              {strategy?.maxContractsReason}
            </p>
          </div>
        )}

        {/* Metrics grid */}
        <div className="px-5 pb-3">
          <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
            {/*
              The point estimate never renders alone. Exp 022 measured half-year
              retention swinging -77.9% -> +92.8% on identical rules, so the
              annual figure describes the start date as much as the strategy.
            */}
            {strategy?.expectedPnl !== undefined && strategy.expectedPnl !== null && (
              <MetricCell
                label="Expected P&L / yr per contract"
                value={money(strategy.expectedPnl)}
                accent={TIER_VALUE_COLOR[tier]}
                sub={
                  hasRange
                    ? `range ${money(strategy.pnlRangeLow!)}..${money(strategy.pnlRangeHigh!)}`
                    : strategy.realFillPnl !== null
                      ? `${money(strategy.realFillPnl)} on real fills only`
                      : undefined
                }
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
            <MetricCell
              label="IV Rank Gate"
              value={`≥ ${ivThreshold}`}
              sub={ivThreshold !== DEFAULT_IV_THRESHOLD ? 'per-ticker (Exp 023)' : undefined}
            />
            <MetricCell label="DTE Range" value={dteDisplay} />
          </div>
          {/*
            Per-contract x contract count, using the LIQUIDITY-CAPPED count —
            KKR's $316/contract reads as the third-best ticker until the 7-contract
            cap multiplies it down to ~$2.2K/yr. The at-size number is the one a
            holder of these shares would actually earn, so it renders wherever the
            per-contract number does. Real-fill basis shown when Exp 022 measured it.
          */}
          {strategy?.expectedPnl !== undefined && strategy.expectedPnl !== null && contracts > 0 && (
            <p className="mt-2 text-[12px] text-muted-foreground tabular-nums">
              &asymp; <span className="font-semibold text-foreground">{money(strategy.expectedPnl * contracts)}/yr</span>
              {' '}at your {contracts} contract{contracts !== 1 ? 's' : ''}
              {isCapped ? ' (liquidity-capped)' : ''}
              {strategy.realFillPnl !== null && strategy.realFillPnl !== strategy.expectedPnl && (
                <span className="text-orange-700/90 dark:text-orange-400/80">
                  {' '}&middot; real-fill basis &asymp; {money(strategy.realFillPnl * contracts)}/yr
                </span>
              )}
            </p>
          )}

          {/*
            Where the headline number and the real-fill number disagree, both go
            on the card. TMUS returns $151/yr on the simulator and -$81/yr
            counting only exits that were actual Databento prints; KKR is
            $316 vs -$88. Showing the first without the second is the difference
            between a strategy that makes money and one that does not.
          */}
          {strategy?.realFillPnl !== undefined && strategy?.realFillPnl !== null && hasRange && (
            <div className="mt-3 rounded-lg border border-red-200 dark:border-red-500/20 bg-red-50/50 dark:bg-red-500/5 px-4 py-2.5">
              <p className="text-[11px] text-red-800 dark:text-red-300 leading-relaxed">
                <span className="font-semibold">
                  {money(strategy.realFillPnl)}/yr on real-fill exits only
                </span>
                {strategy.repricingCoverage !== null && (
                  <> &mdash; only {strategy.repricingCoverage}% of exits repriced against a real
                  quote; the headline figure is substantially carried-forward prices.</>
                )}
              </p>
            </div>
          )}

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
                {winRateNum}% of simulated cycles ended profitable — premium kept exceeded any buyback cost. A losing cycle means the copilot's buyback cost more than the premium collected (that is the insurance working, not a portfolio loss — stock P&L is not included in these figures).
              </p>
            </div>
          )}

          {/*
            Probation is not Untested. Untested means nobody looked; probation
            means we looked with a weaker instrument, and the card has to say
            which instrument, because "Good" is what these three used to show.
          */}
          {tier === 'probation' && (
            <div className="mt-3 rounded-lg border border-orange-200 dark:border-orange-500/20 bg-orange-50/60 dark:bg-orange-500/5 px-4 py-2.5">
              <p className="text-[11px] text-orange-800 dark:text-orange-300 leading-relaxed">
                <span className="font-semibold">On probation:</span>{' '}
                {strategy?.repricingCoverage !== null && strategy?.repricingCoverage !== undefined
                  ? `only ${strategy.repricingCoverage}% of simulated exits repriced against a real
                     quote, below the 70% floor fixed before the run (Exp 022). The parameters are
                     unchanged — the evidence behind them is weaker than the badge used to imply.`
                  : `validated on stock closes only (Exp 014). This ticker has never been tested on
                     real option prices, so the numbers above describe the stock, not the options
                     you would actually sell.`}
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

function MetricCell({
  label,
  value,
  accent,
  sub,
}: {
  label: string
  value: string
  accent?: string
  /** Spread or qualifier shown under the label — a point estimate never stands alone. */
  sub?: string
}) {
  return (
    <div>
      <div className={cn('text-2xl font-semibold tracking-tight tabular-nums', accent ?? 'text-foreground')}>
        {value}
      </div>
      <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground mt-0.5">
        {label}
      </div>
      {sub && (
        <div className="text-[10px] text-muted-foreground/70 tabular-nums mt-0.5">{sub}</div>
      )}
    </div>
  )
}
