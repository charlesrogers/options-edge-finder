'use client'

import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'

interface ProvenanceSummary {
  total: number
  scored: number
  winners: number
  losers: number
  win_rate: number | null
  avg_pnl: number | null
}

interface PaperTradeStats {
  total: number
  scored: number
  winners: number
  losers: number
  win_rate: number
  avg_pnl: number
  total_pnl: number
  provenance?: {
    synthetic: ProvenanceSummary
    live: ProvenanceSummary
    first_live_outcome_due: string | null
  }
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

  /*
   * If the API predates the provenance split there is no way to tell synthetic
   * rows from real ones, and the blended figure is exactly the number the audit
   * disqualified. Render "audit pending" rather than falling back to it —
   * unaudited stats may not display bare (spec 5.2).
   */
  const live = stats.provenance?.live
  const synthetic = stats.provenance?.synthetic
  const provenanceKnown = Boolean(stats.provenance)

  if (!provenanceKnown) {
    return (
      <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
        <div className="px-5 pt-4 pb-4">
          <a href="/paper-trades" className="text-[14px] font-semibold text-foreground hover:text-primary transition-colors">
            Paper Trade Tracker
          </a>
          <div className="mt-2 rounded-lg border border-amber-200 dark:border-amber-500/20 bg-amber-50/60 dark:bg-amber-500/5 px-4 py-3">
            <p className="text-[12px] font-semibold text-amber-800 dark:text-amber-300">Audit pending</p>
            <p className="text-[11px] text-amber-700/80 dark:text-amber-400/70 mt-1 leading-relaxed">
              {stats.total} recommendations tracked. Statistics are withheld until synthetic
              backfill rows can be separated from real-price ones.
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
      <div className="px-5 pt-4 pb-3">
        <div className="flex items-center justify-between">
          <a href="/paper-trades" className="text-[14px] font-semibold text-foreground hover:text-primary transition-colors">Paper Trade Tracker</a>
          <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold ring-1 ring-inset bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-400 ring-blue-600/20">
            {stats.total} tracked
          </span>
        </div>
        {/*
          Methodology on the face of the card, not in a tooltip (spec 5.1). The
          scorer measures hold-to-expiry outcomes; the copilot buys back early,
          which is the entire point of the copilot. This card can therefore never
          be the strategy's record, even once real trades are scored.
        */}
        <p className="text-[12px] text-muted-foreground mt-0.5 leading-relaxed">
          Hold-to-expiry outcomes of logged recommendations &mdash; <span className="font-medium">not</span> the
          copilot strategy, which buys back early.
        </p>
      </div>

      {/*
        Provenance gate. Until a real-price recommendation has been scored, no
        win rate on this card is the strategy's. As of the 2026-08-18 audit all
        444 scored rows are Black-Scholes backfill and zero live-chain rows have
        reached expiry (results/013_paper_trade_audit.md).
      */}
      {live && live.scored > 0 ? (
        <div className="px-5 pb-4">
          <div className="grid grid-cols-3 gap-4">
            <div>
              <div className={cn(
                'text-2xl font-semibold tracking-tight',
                (live.win_rate ?? 0) >= 60 ? 'text-emerald-600' : (live.win_rate ?? 0) >= 40 ? 'text-amber-600' : 'text-red-600'
              )}>
                {live.win_rate}%
              </div>
              <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground mt-0.5">Win Rate</div>
              <div className="text-[10px] text-muted-foreground/70 mt-0.5">real prices, hold-to-expiry</div>
            </div>
            <div>
              <div className={cn(
                'text-2xl font-semibold tracking-tight',
                (live.avg_pnl ?? 0) >= 0 ? 'text-emerald-600' : 'text-red-600'
              )}>
                {(live.avg_pnl ?? 0) >= 0 ? '+' : ''}{(live.avg_pnl ?? 0).toFixed(1)}%
              </div>
              <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground mt-0.5">Avg P&L / Trade</div>
            </div>
            <div>
              <div className="text-2xl font-semibold tracking-tight text-foreground">
                {live.winners}W / {live.losers}L
              </div>
              <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground mt-0.5">Record</div>
            </div>
          </div>
        </div>
      ) : (
        <div className="px-5 pb-4 space-y-2">
          <div className="rounded-lg border border-amber-200 dark:border-amber-500/20 bg-amber-50/60 dark:bg-amber-500/5 px-4 py-3">
            <p className="text-[12px] font-semibold text-amber-800 dark:text-amber-300">
              No real-price recommendation has been scored yet
            </p>
            <p className="text-[11px] text-amber-700/80 dark:text-amber-400/70 mt-1 leading-relaxed">
              {live ? `${live.total} recommendation${live.total !== 1 ? 's' : ''} logged off live option chains, none yet at expiry` : 'No live-chain recommendations logged'}
              {stats.provenance?.first_live_outcome_due
                ? `. First outcomes due ${stats.provenance.first_live_outcome_due}.`
                : '.'}
            </p>
          </div>
          {synthetic && synthetic.scored > 0 && (
            <div className="rounded-lg border bg-muted/30 px-4 py-3">
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                <span className="font-medium text-foreground">
                  {synthetic.scored} scored trades ({synthetic.win_rate}% expired worthless,{' '}
                  {(synthetic.avg_pnl ?? 0) >= 0 ? '+' : ''}{synthetic.avg_pnl}% avg)
                </span>{' '}
                are synthetic: priced with Black-Scholes off stock history by the backfill
                script, not quotes anyone could have traded. They describe the pricing model,
                not the strategy, and are shown here only so the count is not mistaken for a
                track record.
              </p>
            </div>
          )}
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
