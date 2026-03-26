'use client'

import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import { TIER_CONFIG } from '@/lib/strategies'

/* ── Types ── */

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
  ticker: string; tier: string; total: number; scored: number
  winners: number; losers: number; win_rate: number; avg_pnl: number
}

interface Stats {
  total: number; scored: number; winners: number; losers: number
  win_rate: number; avg_pnl: number; total_pnl: number; since: string | null
}

/* ── Status helpers ── */

type TradeStatus = 'won' | 'lost' | 'pending'

function getStatus(t: PaperTrade): TradeStatus {
  if (!t.scored) return 'pending'
  return (t.pnl_pct ?? 0) > 0 ? 'won' : 'lost'
}

const STATUS_PILL: Record<TradeStatus, string> = {
  won: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 ring-emerald-600/20',
  lost: 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 ring-red-600/20',
  pending: 'bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-400 ring-blue-600/20',
}

const STATUS_CARD_BG: Record<TradeStatus, string> = {
  won: 'border-emerald-200 dark:border-emerald-500/20 bg-emerald-50/30 dark:bg-emerald-500/5',
  lost: 'border-red-200 dark:border-red-500/20 bg-red-50/30 dark:bg-red-500/5',
  pending: 'border-border bg-card',
}

const TIER_BADGE: Record<string, string> = {
  best: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 ring-emerald-600/20',
  strong: 'bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-400 ring-blue-600/20',
  good: 'bg-violet-50 dark:bg-violet-500/10 text-violet-700 dark:text-violet-400 ring-violet-600/20',
  conservative: 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 ring-amber-600/20',
  untested: 'bg-gray-50 dark:bg-gray-500/10 text-gray-600 dark:text-gray-400 ring-gray-500/20',
}


/* ── Main ── */

export function PaperTradeList() {
  const [data, setData] = useState<{ stats: Stats; byTicker: TickerBreakdown[]; trades: PaperTrade[] } | null>(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | TradeStatus>('all')
  const [sortKey, setSortKey] = useState<'biggest_loss' | 'biggest_win' | 'newest'>('newest')
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())

  useEffect(() => {
    fetch('/api/paper-trades?detail=true')
      .then(r => r.ok ? r.json() : null)
      .then(setData)
      .catch(() => null)
      .finally(() => setLoading(false))
  }, [])

  function toggle(id: number) {
    setExpandedIds(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  /* ── Skeleton ── */
  if (loading) {
    return (
      <div className="space-y-6">
        <div className="h-7 w-64 bg-muted animate-pulse rounded-md" />
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {[1,2,3,4,5].map(i => <div key={i} className="h-24 bg-muted animate-pulse rounded-xl" />)}
        </div>
        <div className="space-y-2">
          {[1,2,3,4,5].map(i => <div key={i} className="h-16 bg-muted animate-pulse rounded-xl" />)}
        </div>
      </div>
    )
  }

  if (!data?.stats) return null

  const { stats, byTicker, trades } = data

  // Count per status
  const counts = {
    all: trades.length,
    won: trades.filter(t => getStatus(t) === 'won').length,
    lost: trades.filter(t => getStatus(t) === 'lost').length,
    pending: trades.filter(t => getStatus(t) === 'pending').length,
  }

  // Filter + sort
  let filtered = filter === 'all' ? [...trades] : trades.filter(t => getStatus(t) === filter)
  if (sortKey === 'biggest_loss') filtered.sort((a, b) => (a.pnl_pct ?? 999) - (b.pnl_pct ?? 999))
  if (sortKey === 'biggest_win') filtered.sort((a, b) => (b.pnl_pct ?? -999) - (a.pnl_pct ?? -999))
  if (sortKey === 'newest') filtered.sort((a, b) => b.recommended_at.localeCompare(a.recommended_at))

  // Auto-detect patterns (losses concentrated in specific tickers/tiers)
  const patterns: { label: string; losses: number; total: number; lossRate: number; avgLossRate: number; delta: number }[] = []
  const avgLossRate = stats.scored > 0 ? stats.losers / stats.scored : 0

  for (const bt of byTicker ?? []) {
    if (bt.scored >= 5 && bt.losers > 0) {
      const lossRate = bt.losers / bt.scored
      if (lossRate > avgLossRate + 0.05) {
        patterns.push({
          label: `${bt.ticker} (${TIER_CONFIG[bt.tier as keyof typeof TIER_CONFIG]?.label ?? bt.tier})`,
          losses: bt.losers, total: bt.scored, lossRate, avgLossRate, delta: lossRate - avgLossRate,
        })
      }
    }
  }
  patterns.sort((a, b) => b.delta - a.delta)

  return (
    <div className="space-y-6">
      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Paper Trade Analysis</h1>
          <p className="text-[13px] text-muted-foreground mt-1">
            {stats.scored} scored / {stats.total} tracked · {stats.win_rate}% win rate
            {stats.since && ` · Since ${new Date(stats.since).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })}`}
          </p>
        </div>
        {/* Sort */}
        <select value={sortKey} onChange={e => setSortKey(e.target.value as typeof sortKey)}
          className="h-8 rounded-lg border border-input bg-background px-2.5 text-[12px] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50">
          <option value="newest">Newest first</option>
          <option value="biggest_loss">Biggest loss</option>
          <option value="biggest_win">Biggest win</option>
        </select>
      </div>

      {/* ── Scoreboard (5-column like bettybot) ── */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 p-4 rounded-xl border bg-card shadow-sm shadow-black/[0.04]">
        <div>
          <div className="text-[11px] text-muted-foreground uppercase tracking-wider">Record</div>
          <div className="text-[20px] font-bold text-foreground">{stats.win_rate}%</div>
          <div className="text-[11px] text-muted-foreground flex gap-1.5">
            <span className="text-emerald-600">{stats.winners}W</span>
            <span className="text-red-600">{stats.losers}L</span>
            <span className="text-muted-foreground">{stats.total - stats.scored}P</span>
          </div>
        </div>
        <div>
          <div className="text-[11px] text-muted-foreground uppercase tracking-wider">Avg P&L</div>
          <div className={cn('text-[20px] font-bold', stats.avg_pnl >= 0 ? 'text-emerald-600' : 'text-red-600')}>
            {stats.avg_pnl >= 0 ? '+' : ''}{stats.avg_pnl.toFixed(1)}%
          </div>
          <div className="text-[11px] text-muted-foreground">per trade</div>
        </div>
        <div>
          <div className="text-[11px] text-muted-foreground uppercase tracking-wider">Total Scored</div>
          <div className="text-[20px] font-bold text-foreground">{stats.scored}</div>
          <div className="text-[11px] text-muted-foreground">of {stats.total} tracked</div>
        </div>
        <div>
          <div className="text-[11px] text-muted-foreground uppercase tracking-wider">Losses</div>
          <div className="text-[20px] font-bold text-red-600">{stats.losers}</div>
          <div className="text-[11px] text-muted-foreground">{(avgLossRate * 100).toFixed(0)}% loss rate</div>
        </div>
        <div>
          <div className="text-[11px] text-muted-foreground uppercase tracking-wider">Pending</div>
          <div className="text-[20px] font-bold text-foreground">{stats.total - stats.scored}</div>
          <div className="text-[11px] text-muted-foreground">awaiting expiry</div>
        </div>
      </div>

      {/* ── Pattern badges (like bettybot losses page) ── */}
      {patterns.length > 0 && (
        <div>
          <h2 className="text-[14px] font-semibold mb-2">Patterns Found</h2>
          <div className="flex flex-wrap gap-2">
            {patterns.map((p, i) => (
              <div key={i} className="px-3 py-2 rounded-lg bg-red-50 dark:bg-red-500/5 border border-red-200 dark:border-red-500/15 text-[12px]">
                <span className="font-medium text-foreground">{p.label}</span>
                <span className="text-muted-foreground">: {p.losses}L / {p.total} total ({(p.lossRate * 100).toFixed(0)}% loss rate vs {(p.avgLossRate * 100).toFixed(0)}% avg)</span>
                <span className="text-red-600 ml-1">+{(p.delta * 100).toFixed(0)}pp</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Pill filter tabs (like bettybot) ── */}
      <div className="flex gap-1.5">
        {(['all', 'won', 'lost', 'pending'] as const).map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className={cn(
              'px-3 py-1.5 text-[12px] rounded-full font-medium transition-colors',
              filter === f
                ? 'bg-primary text-primary-foreground'
                : 'bg-secondary text-muted-foreground hover:text-foreground'
            )}>
            {f.charAt(0).toUpperCase() + f.slice(1)} <span className="opacity-50">{counts[f]}</span>
          </button>
        ))}
      </div>

      {/* ── Per-ticker breakdown (collapsible) ── */}
      {byTicker && byTicker.length > 0 && (
        <details className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
          <summary className="px-5 py-3 cursor-pointer text-[13px] font-semibold text-foreground hover:bg-accent/50 transition-colors">
            Per-Ticker Breakdown
          </summary>
          <div className="px-5 pb-4 border-t">
            <div className="grid grid-cols-[1fr_50px_50px_50px_60px_70px] gap-3 py-2 text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
              <div>Ticker</div><div>Scored</div><div>Win%</div><div>Losses</div><div>Avg P&L</div><div>Tier</div>
            </div>
            {byTicker.map(t => (
              <div key={t.ticker} className="grid grid-cols-[1fr_50px_50px_50px_60px_70px] gap-3 py-2 items-center text-[12px] border-t hover:bg-accent/30 transition-colors">
                <div className="font-semibold text-foreground">{t.ticker}</div>
                <div className="tabular-nums text-muted-foreground">{t.scored}</div>
                <div className={cn('tabular-nums font-medium', t.win_rate >= 80 ? 'text-emerald-600' : t.win_rate >= 60 ? 'text-foreground' : 'text-red-600')}>{t.win_rate}%</div>
                <div className="tabular-nums text-red-600">{t.losers}</div>
                <div className={cn('tabular-nums font-medium', t.avg_pnl >= 0 ? 'text-emerald-600' : 'text-red-600')}>{t.avg_pnl >= 0 ? '+' : ''}{t.avg_pnl.toFixed(0)}%</div>
                <span className={cn('inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold ring-1 ring-inset', TIER_BADGE[t.tier] ?? TIER_BADGE.untested)}>
                  {TIER_CONFIG[t.tier as keyof typeof TIER_CONFIG]?.label ?? t.tier}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}

      {/* ── Trade list ── */}
      <div className="space-y-1.5">
        {filtered.map(trade => {
          const status = getStatus(trade)
          const isExpanded = expandedIds.has(trade.id)
          const params = trade.strategy_params ? JSON.parse(trade.strategy_params) : {}
          const isBackfilled = params.backfilled === true

          return (
            <div key={trade.id} className={cn('rounded-xl border overflow-hidden transition-shadow', STATUS_CARD_BG[status], isExpanded && 'shadow-md shadow-black/[0.06]')}>
              {/* Compact row — always visible */}
              <button onClick={() => toggle(trade.id)} className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-accent/20 transition-colors">
                {/* Status pill */}
                <span className={cn('text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ring-1 ring-inset shrink-0', STATUS_PILL[status])}>
                  {status}
                </span>

                {/* Center: ticker + details */}
                <div className="flex-1 min-w-0">
                  <div className="text-[13px] font-medium text-foreground truncate">
                    {trade.ticker} ${trade.strike} Call @ ${trade.premium_at_rec.toFixed(2)}
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    {trade.otm_pct.toFixed(1)}% OTM · {trade.dte} DTE
                    {isBackfilled && ' · backfilled'}
                    {trade.expiration && ` · exp ${trade.expiration}`}
                  </div>
                </div>

                {/* Right: P&L + date */}
                <div className="text-right shrink-0">
                  {trade.scored && trade.pnl_pct !== null ? (
                    <div className={cn('text-[13px] font-bold tabular-nums', status === 'won' ? 'text-emerald-600' : 'text-red-600')}>
                      {trade.pnl_pct > 0 ? '+' : ''}{trade.pnl_pct.toFixed(0)}%
                    </div>
                  ) : (
                    <div className="text-[13px] text-muted-foreground">—</div>
                  )}
                  <div className="text-[10px] text-muted-foreground">
                    {new Date(trade.recommended_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                  </div>
                </div>
              </button>

              {/* Expanded detail */}
              {isExpanded && (
                <div className="px-4 pb-4 border-t space-y-3 pt-3">
                  {/* Diagnosis bullets */}
                  <ul className="space-y-0.5">
                    {status === 'won' && (
                      <>
                        <li className="text-[12px] text-muted-foreground flex items-start gap-1.5">
                          <span className="text-emerald-600 mt-0.5 shrink-0">+</span>
                          <span>Option expired worthless — kept full ${trade.premium_at_rec.toFixed(2)}/share premium</span>
                        </li>
                        <li className="text-[12px] text-muted-foreground flex items-start gap-1.5">
                          <span className="text-emerald-600 mt-0.5 shrink-0">+</span>
                          <span>Strike ${trade.strike} was {trade.otm_pct.toFixed(1)}% above stock price at entry</span>
                        </li>
                      </>
                    )}
                    {status === 'lost' && (
                      <>
                        <li className="text-[12px] text-muted-foreground flex items-start gap-1.5">
                          <span className="text-red-600 mt-0.5 shrink-0">-</span>
                          <span>Stock rallied through ${trade.strike} strike — expired in-the-money</span>
                        </li>
                        <li className="text-[12px] text-muted-foreground flex items-start gap-1.5">
                          <span className="text-red-600 mt-0.5 shrink-0">-</span>
                          <span>The copilot would have flagged CLOSE_NOW before expiry, limiting this loss</span>
                        </li>
                        {trade.otm_pct < 4 && (
                          <li className="text-[12px] text-muted-foreground flex items-start gap-1.5">
                            <span className="text-red-600 mt-0.5 shrink-0">-</span>
                            <span>Only {trade.otm_pct.toFixed(1)}% OTM at entry — close strikes have higher assignment risk</span>
                          </li>
                        )}
                      </>
                    )}
                    {status === 'pending' && (
                      <li className="text-[12px] text-muted-foreground flex items-start gap-1.5">
                        <span className="text-blue-600 mt-0.5 shrink-0">i</span>
                        <span>Expires {trade.expiration} — scoring after 30 days from recommendation</span>
                      </li>
                    )}
                  </ul>

                  {/* Strategy context */}
                  <div>
                    <div className="text-[11px] text-muted-foreground uppercase tracking-wider mb-1">Strategy</div>
                    <div className="text-[12px] text-muted-foreground space-y-0.5">
                      <div>Target OTM: <span className="font-medium text-foreground">{params.target_otm ? `${(params.target_otm * 100).toFixed(0)}%` : '—'}</span> · Actual: <span className="font-medium text-foreground">{trade.otm_pct.toFixed(1)}%</span></div>
                      {params.expected_pnl && <div>Expected annual P&L: <span className="font-medium text-foreground">${params.expected_pnl.toLocaleString()}/contract</span></div>}
                      <div>Tier: <span className={cn('inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold ring-1 ring-inset ml-0.5', TIER_BADGE[trade.tier] ?? TIER_BADGE.untested)}>
                        {TIER_CONFIG[trade.tier as keyof typeof TIER_CONFIG]?.label ?? trade.tier}
                      </span></div>
                    </div>
                  </div>

                  {/* Execution */}
                  <div>
                    <div className="text-[11px] text-muted-foreground uppercase tracking-wider mb-1">Execution</div>
                    <div className="text-[12px] text-muted-foreground space-y-0.5">
                      <div>Premium: <span className="font-medium text-foreground">${trade.premium_at_rec.toFixed(2)}/share</span> · DTE: <span className="font-medium text-foreground">{trade.dte}</span></div>
                      <div>Pricing: <span className="font-medium text-foreground">{params.pricing ?? 'Real market prices'}</span></div>
                      {isBackfilled && <div className="text-amber-600 dark:text-amber-400">Backfilled — BSM-estimated premium, not real market price</div>}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {filtered.length === 0 && (
        <div className="rounded-xl border bg-card text-center py-12 shadow-sm shadow-black/[0.04]">
          <p className="text-[14px] font-medium text-foreground">No trades match this filter</p>
          <p className="text-[12px] text-muted-foreground mt-1">Try selecting a different filter above.</p>
        </div>
      )}
    </div>
  )
}
