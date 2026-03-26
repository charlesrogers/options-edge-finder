'use client'

import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'

interface PaperTradeStats {
  total: number
  scored: number
  winners: number
  losers: number
  win_rate: number
  avg_pnl: number
  total_pnl: number
  recent?: Array<{
    ticker: string
    strike: number
    premium_at_rec: number
    otm_pct: number
    dte: number
    tier: string
    recommended_at: string
    scored: boolean
    pnl_pct: number | null
    expired_worthless: boolean | null
  }>
}

export function PaperTradeScorecard() {
  const [stats, setStats] = useState<PaperTradeStats | null>(null)

  useEffect(() => {
    fetch('/api/paper-trades')
      .then(r => r.ok ? r.json() : null)
      .then(setStats)
      .catch(() => null)
  }, [])

  if (!stats || stats.total === 0) return null

  return (
    <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
      <div className="px-5 pt-4 pb-3">
        <div className="flex items-center justify-between">
          <h2 className="text-[14px] font-semibold text-foreground">Paper Trade Tracker</h2>
          <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold ring-1 ring-inset bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-400 ring-blue-600/20">
            {stats.total} tracked
          </span>
        </div>
        <p className="text-[12px] text-muted-foreground mt-0.5">
          Every recommendation logged and scored automatically. {stats.scored > 0 ? `${stats.scored} scored so far.` : 'Scoring begins after 30 days.'}
        </p>
      </div>

      {/* Stats row */}
      {stats.scored > 0 ? (
        <div className="px-5 pb-4">
          <div className="grid grid-cols-3 gap-4">
            <div>
              <div className={cn(
                'text-2xl font-semibold tracking-tight',
                stats.win_rate >= 60 ? 'text-emerald-600' : stats.win_rate >= 40 ? 'text-amber-600' : 'text-red-600'
              )}>
                {stats.win_rate}%
              </div>
              <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground mt-0.5">Win Rate</div>
            </div>
            <div>
              <div className={cn(
                'text-2xl font-semibold tracking-tight',
                stats.total_pnl >= 0 ? 'text-emerald-600' : 'text-red-600'
              )}>
                {stats.total_pnl >= 0 ? '+' : ''}{stats.total_pnl.toFixed(0)}%
              </div>
              <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground mt-0.5">Total P&L</div>
            </div>
            <div>
              <div className="text-2xl font-semibold tracking-tight text-foreground">
                {stats.winners}W / {stats.losers}L
              </div>
              <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground mt-0.5">Record</div>
            </div>
          </div>
        </div>
      ) : (
        <div className="px-5 pb-4">
          <div className="rounded-lg border border-blue-200 dark:border-blue-500/20 bg-blue-50/50 dark:bg-blue-500/5 px-4 py-3">
            <p className="text-[12px] text-blue-700 dark:text-blue-400">
              {stats.total} recommendation{stats.total !== 1 ? 's' : ''} tracked. Scoring begins 30 days after each recommendation.
            </p>
          </div>
        </div>
      )}

      {/* Recent paper trades */}
      {stats.recent && stats.recent.length > 0 && (
        <div className="px-5 pb-4 border-t pt-3">
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground mb-2">Recent Recommendations</p>
          <div className="space-y-1.5">
            {stats.recent.slice(0, 5).map((trade, i) => (
              <div key={i} className="flex items-center gap-3 text-[12px]">
                <span className="font-semibold text-foreground w-12">{trade.ticker}</span>
                <span className="text-muted-foreground">${trade.strike} Call @ ${trade.premium_at_rec.toFixed(2)}</span>
                <span className="text-muted-foreground ml-auto tabular-nums">{trade.recommended_at}</span>
                {trade.scored && trade.pnl_pct !== null && (
                  <span className={cn(
                    'inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold ring-1 ring-inset',
                    trade.pnl_pct > 0
                      ? 'bg-emerald-50 text-emerald-700 ring-emerald-600/20'
                      : 'bg-red-50 text-red-700 ring-red-600/20'
                  )}>
                    {trade.pnl_pct > 0 ? '+' : ''}{trade.pnl_pct.toFixed(0)}%
                  </span>
                )}
                {!trade.scored && (
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-muted text-muted-foreground">
                    pending
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
