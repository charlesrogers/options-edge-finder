'use client'

import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import { TIER_CONFIG } from '@/lib/strategies'

interface PaperTrade {
  id: number
  ticker: string
  strike: number
  premium_at_rec: number
  otm_pct: number
  dte: number
  expiration: string
  tier: string
  recommended_at: string
  scored: boolean
  pnl_pct: number | null
  expired_worthless: boolean | null
  outcome_price: number | null
  strategy_params: string | null
}

interface TickerBreakdown {
  ticker: string
  tier: string
  total: number
  scored: number
  winners: number
  losers: number
  win_rate: number
  avg_pnl: number
}

interface Stats {
  total: number
  scored: number
  winners: number
  losers: number
  win_rate: number
  avg_pnl: number
  total_pnl: number
  since: string | null
}

const TIER_BADGE: Record<string, string> = {
  best: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 ring-emerald-600/20',
  strong: 'bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-400 ring-blue-600/20',
  good: 'bg-violet-50 dark:bg-violet-500/10 text-violet-700 dark:text-violet-400 ring-violet-600/20',
  conservative: 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 ring-amber-600/20',
  skip: 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 ring-red-600/20',
  untested: 'bg-gray-50 dark:bg-gray-500/10 text-gray-700 dark:text-gray-400 ring-gray-600/20',
}

type SortKey = 'biggest_loss' | 'biggest_win' | 'newest' | 'oldest'
type ResultFilter = 'all' | 'wins' | 'losses' | 'pending'

export function PaperTradeList() {
  const [data, setData] = useState<{ stats: Stats; byTicker: TickerBreakdown[]; trades: PaperTrade[] } | null>(null)
  const [loading, setLoading] = useState(true)

  // Filters
  const [tickerFilter, setTickerFilter] = useState<string>('all')
  const [tierFilter, setTierFilter] = useState<string>('all')
  const [resultFilter, setResultFilter] = useState<ResultFilter>('all')
  const [sortKey, setSortKey] = useState<SortKey>('biggest_loss')
  const [expandedId, setExpandedId] = useState<number | null>(null)

  useEffect(() => {
    fetch('/api/paper-trades?detail=true')
      .then(r => r.ok ? r.json() : null)
      .then(setData)
      .catch(() => null)
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="h-7 w-80 bg-muted animate-pulse rounded-md" />
        <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
          {[1, 2, 3, 4].map(i => <div key={i} className="h-28 bg-muted animate-pulse rounded-xl" />)}
        </div>
        <div className="space-y-3">
          {[1, 2, 3, 4, 5].map(i => <div key={i} className="h-20 bg-muted animate-pulse rounded-xl" />)}
        </div>
      </div>
    )
  }

  if (!data || !data.stats) return null

  const { stats, byTicker, trades } = data

  // Apply filters
  let filtered = [...trades]
  if (tickerFilter !== 'all') filtered = filtered.filter(t => t.ticker === tickerFilter)
  if (tierFilter !== 'all') filtered = filtered.filter(t => t.tier === tierFilter)
  if (resultFilter === 'wins') filtered = filtered.filter(t => t.scored && (t.pnl_pct ?? 0) > 0)
  if (resultFilter === 'losses') filtered = filtered.filter(t => t.scored && (t.pnl_pct ?? 0) <= 0)
  if (resultFilter === 'pending') filtered = filtered.filter(t => !t.scored)

  // Sort
  if (sortKey === 'biggest_loss') filtered.sort((a, b) => (a.pnl_pct ?? 999) - (b.pnl_pct ?? 999))
  if (sortKey === 'biggest_win') filtered.sort((a, b) => (b.pnl_pct ?? -999) - (a.pnl_pct ?? -999))
  if (sortKey === 'newest') filtered.sort((a, b) => b.recommended_at.localeCompare(a.recommended_at))
  if (sortKey === 'oldest') filtered.sort((a, b) => a.recommended_at.localeCompare(b.recommended_at))

  const tickers = [...new Set(trades.map(t => t.ticker))].sort()
  const tiers = [...new Set(trades.map(t => t.tier))].sort()
  const losses = filtered.filter(t => t.scored && (t.pnl_pct ?? 0) <= 0)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Paper Trade Analysis</h1>
        <p className="text-[13px] text-muted-foreground mt-1">
          {stats.scored} scored / {stats.total} tracked · {stats.win_rate}% win rate
          {stats.since && ` · Since ${stats.since}`}
        </p>
      </div>

      {/* Stat cards */}
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        <StatCard label="Win Rate" value={`${stats.win_rate}%`} accent={stats.win_rate >= 60 ? 'green' : 'red'}
          insight={`${stats.winners}W / ${stats.losers}L`} />
        <StatCard label="Avg P&L" value={`${stats.avg_pnl >= 0 ? '+' : ''}${stats.avg_pnl.toFixed(0)}%`}
          accent={stats.avg_pnl >= 0 ? 'green' : 'red'} insight="Per trade average" />
        <StatCard label="Scored" value={`${stats.scored}`} insight={`of ${stats.total} tracked`} />
        <StatCard label="Pending" value={`${stats.total - stats.scored}`} insight="Awaiting 30-day scoring" />
      </div>

      {/* Per-ticker breakdown */}
      {byTicker && byTicker.length > 0 && (
        <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
          <div className="px-5 pt-4 pb-2">
            <h2 className="text-[14px] font-semibold text-foreground">Per-Ticker Breakdown</h2>
          </div>
          <div className="px-5 pb-4">
            <div className="grid grid-cols-[1fr_60px_50px_50px_60px_70px] gap-3 px-0 py-2 text-[11px] font-medium text-muted-foreground uppercase tracking-wider border-b">
              <div>Ticker</div><div>Trades</div><div>Win%</div><div>Losses</div><div>Avg P&L</div><div>Tier</div>
            </div>
            {byTicker.map(t => (
              <div key={t.ticker} className="grid grid-cols-[1fr_60px_50px_50px_60px_70px] gap-3 px-0 py-2.5 items-center text-[12px] border-b last:border-0 hover:bg-muted/30 transition-colors">
                <div className="font-semibold text-foreground">{t.ticker}</div>
                <div className="tabular-nums text-muted-foreground">{t.scored}</div>
                <div className={cn('tabular-nums font-medium', t.win_rate >= 80 ? 'text-emerald-600' : t.win_rate >= 60 ? 'text-foreground' : 'text-red-600')}>
                  {t.win_rate}%
                </div>
                <div className="tabular-nums text-red-600">{t.losers}</div>
                <div className={cn('tabular-nums font-medium', t.avg_pnl >= 0 ? 'text-emerald-600' : 'text-red-600')}>
                  {t.avg_pnl >= 0 ? '+' : ''}{t.avg_pnl.toFixed(0)}%
                </div>
                <div>
                  <span className={cn('inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold ring-1 ring-inset', TIER_BADGE[t.tier] ?? TIER_BADGE.untested)}>
                    {TIER_CONFIG[t.tier as keyof typeof TIER_CONFIG]?.label ?? t.tier}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <select value={tickerFilter} onChange={e => setTickerFilter(e.target.value)}
          className="h-8 rounded-lg border border-input bg-background px-2.5 text-[13px] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50">
          <option value="all">All tickers</option>
          {tickers.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={tierFilter} onChange={e => setTierFilter(e.target.value)}
          className="h-8 rounded-lg border border-input bg-background px-2.5 text-[13px] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50">
          <option value="all">All tiers</option>
          {tiers.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={resultFilter} onChange={e => setResultFilter(e.target.value as ResultFilter)}
          className="h-8 rounded-lg border border-input bg-background px-2.5 text-[13px] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50">
          <option value="all">All results</option>
          <option value="wins">Winners only</option>
          <option value="losses">Losses only</option>
          <option value="pending">Pending</option>
        </select>
        <select value={sortKey} onChange={e => setSortKey(e.target.value as SortKey)}
          className="h-8 rounded-lg border border-input bg-background px-2.5 text-[13px] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50">
          <option value="biggest_loss">Sort: Biggest loss</option>
          <option value="biggest_win">Sort: Biggest win</option>
          <option value="newest">Sort: Newest</option>
          <option value="oldest">Sort: Oldest</option>
        </select>
        <span className="text-[12px] text-muted-foreground ml-auto">
          {filtered.length} trades shown
        </span>
      </div>

      {/* Trade cards */}
      <div className="space-y-2">
        {filtered.map(trade => (
          <TradeCard key={trade.id} trade={trade} expanded={expandedId === trade.id}
            onToggle={() => setExpandedId(expandedId === trade.id ? null : trade.id)} />
        ))}
      </div>
    </div>
  )
}

function StatCard({ label, value, insight, accent }: { label: string; value: string; insight: string; accent?: 'green' | 'red' }) {
  const color = accent === 'green' ? 'text-emerald-600' : accent === 'red' ? 'text-red-600' : 'text-foreground'
  return (
    <div className="rounded-xl border bg-card p-5 shadow-sm shadow-black/[0.04]">
      <p className="text-[12px] font-medium text-muted-foreground uppercase tracking-wider">{label}</p>
      <p className={cn('text-2xl font-semibold tracking-tight mt-1', color)}>{value}</p>
      <p className="text-[12px] text-muted-foreground mt-1">{insight}</p>
    </div>
  )
}

function TradeCard({ trade, expanded, onToggle }: { trade: PaperTrade; expanded: boolean; onToggle: () => void }) {
  const isWin = trade.scored && (trade.pnl_pct ?? 0) > 0
  const isLoss = trade.scored && (trade.pnl_pct ?? 0) <= 0
  const isPending = !trade.scored
  const tierConfig = TIER_CONFIG[trade.tier as keyof typeof TIER_CONFIG]

  const params = trade.strategy_params ? JSON.parse(trade.strategy_params) : {}
  const isBackfilled = params.backfilled === true

  const resultBadge = isWin
    ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 ring-emerald-600/20'
    : isLoss
      ? 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 ring-red-600/20'
      : 'bg-gray-50 dark:bg-gray-500/10 text-gray-600 dark:text-gray-400 ring-gray-600/20'

  const resultLabel = isWin ? 'WIN' : isLoss ? 'LOSS' : 'PENDING'
  const outcome = trade.expired_worthless ? 'Expired OTM (kept full premium)' : trade.scored ? 'Expired ITM (stock above strike)' : 'Awaiting expiration'

  return (
    <div className={cn(
      'rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden transition-shadow',
      expanded && 'shadow-md shadow-black/[0.06]'
    )}>
      <button onClick={onToggle} className="w-full px-5 py-3.5 flex items-center gap-4 text-left hover:bg-accent/30 transition-colors">
        {/* Ticker + date */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-semibold text-foreground">{trade.ticker}</span>
            <span className="text-[11px] text-muted-foreground">{trade.recommended_at}</span>
            {isBackfilled && <span className="text-[10px] text-muted-foreground/60">backfilled</span>}
          </div>
          <p className="text-[12px] text-muted-foreground mt-0.5">
            ${trade.strike} Call @ ${trade.premium_at_rec.toFixed(2)} ({trade.otm_pct.toFixed(1)}% OTM, {trade.dte} DTE)
          </p>
        </div>

        {/* Result badge */}
        <span className={cn('inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-semibold ring-1 ring-inset flex-shrink-0', resultBadge)}>
          {resultLabel}
        </span>

        {/* P&L */}
        {trade.scored && trade.pnl_pct !== null && (
          <span className={cn('text-[15px] font-semibold tabular-nums flex-shrink-0', isWin ? 'text-emerald-600' : 'text-red-600')}>
            {trade.pnl_pct > 0 ? '+' : ''}{trade.pnl_pct.toFixed(0)}%
          </span>
        )}

        {/* Chevron */}
        <svg className={cn('w-4 h-4 text-muted-foreground transition-transform flex-shrink-0', expanded && 'rotate-180')} viewBox="0 0 16 16" fill="none">
          <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {/* Expanded details */}
      {expanded && (
        <div className="px-5 pb-4 border-t space-y-3 pt-3">
          {/* Metrics */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div>
              <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">OTM %</p>
              <p className="text-[13px] font-semibold tabular-nums">{trade.otm_pct.toFixed(1)}%</p>
            </div>
            <div>
              <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">DTE</p>
              <p className="text-[13px] font-semibold tabular-nums">{trade.dte}</p>
            </div>
            <div>
              <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Tier</p>
              <span className={cn('inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold ring-1 ring-inset', TIER_BADGE[trade.tier] ?? TIER_BADGE.untested)}>
                {tierConfig?.label ?? trade.tier}
              </span>
            </div>
            <div>
              <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Premium</p>
              <p className="text-[13px] font-semibold tabular-nums">${trade.premium_at_rec.toFixed(2)}/sh</p>
            </div>
          </div>

          {/* Outcome */}
          <div className={cn(
            'rounded-lg border px-4 py-3 flex items-start gap-2.5',
            isWin ? 'border-emerald-200 bg-emerald-50' : isLoss ? 'border-red-200 bg-red-50' : 'border-gray-200 bg-gray-50'
          )}>
            <span className={cn('h-2 w-2 rounded-full mt-1.5 flex-shrink-0', isWin ? 'bg-emerald-500' : isLoss ? 'bg-red-500' : 'bg-gray-400')} />
            <div>
              <p className={cn('text-[13px] font-medium', isWin ? 'text-emerald-900' : isLoss ? 'text-red-900' : 'text-gray-800')}>
                {outcome}
              </p>
              {trade.scored && trade.pnl_pct !== null && (
                <p className={cn('text-[12px] mt-0.5', isWin ? 'text-emerald-800' : 'text-red-800')}>
                  P&L: {trade.pnl_pct > 0 ? '+' : ''}{trade.pnl_pct.toFixed(1)}% of premium
                  {trade.expired_worthless && ' — option expired worthless, kept full $' + trade.premium_at_rec.toFixed(2) + '/share'}
                </p>
              )}
              {isLoss && (
                <p className="text-[11px] text-muted-foreground mt-1 italic">
                  The copilot would have flagged CLOSE_NOW before expiry, limiting this loss.
                </p>
              )}
            </div>
          </div>

          {/* Strategy params */}
          <div className="text-[11px] text-muted-foreground space-y-0.5">
            <p>Strategy: {params.target_otm ? `${(params.target_otm * 100).toFixed(0)}% OTM target` : 'default'}</p>
            {params.expected_pnl && <p>Expected annual P&L: ${params.expected_pnl.toLocaleString()}/contract</p>}
            <p>Pricing: {params.pricing ?? 'Real market prices'}</p>
            <p>Expiration: {trade.expiration}</p>
          </div>
        </div>
      )}
    </div>
  )
}
