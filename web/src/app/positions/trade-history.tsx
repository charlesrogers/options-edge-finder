'use client'

import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import type { TradeRow } from '@/lib/supabase'

export function TradeHistory() {
  const [trades, setTrades] = useState<TradeRow[]>([])
  const [expanded, setExpanded] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch('/api/positions')
        if (res.ok) {
          setTrades(await res.json())
        }
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  return (
    <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
      {/* Collapsible header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-5 py-4 flex items-center justify-between text-left hover:bg-accent/40 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <span className="text-[14px] font-semibold text-foreground">Trade History</span>
          {!loading && trades.length > 0 && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold ring-1 ring-inset bg-gray-50 dark:bg-gray-500/10 text-gray-600 dark:text-gray-400 ring-gray-500/20">
              {trades.length}
            </span>
          )}
        </div>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={cn(
            'text-muted-foreground transition-transform',
            expanded && 'rotate-180'
          )}
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      {expanded && (
        <div className="border-t">
          {loading ? (
            <div className="px-5 py-6 text-center">
              <p className="text-[12px] text-muted-foreground">Loading trades...</p>
            </div>
          ) : trades.length === 0 ? (
            <div className="px-5 py-8 text-center">
              <div className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-muted mb-3">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-muted-foreground">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" />
                  <path d="M14 2v6h6" />
                </svg>
              </div>
              <p className="text-[13px] font-medium text-foreground">No trades yet</p>
              <p className="text-[12px] text-muted-foreground mt-0.5">Trades will appear here once you log them.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              {/* Grid header */}
              <div className="grid grid-cols-[1fr_80px_100px_80px_60px_70px_80px] gap-2 px-5 py-2.5 bg-muted/30 border-b">
                {['Ticker', 'Strike', 'Expiry', 'Premium', 'Qty', 'Status', 'P&L'].map((h) => (
                  <div key={h} className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    {h}
                  </div>
                ))}
              </div>

              {/* Data rows */}
              {trades.map((t) => {
                const pnl =
                  t.status === 'closed' && t.close_price !== null
                    ? (t.sold_price - t.close_price) * t.contracts * 100
                    : null
                return (
                  <div
                    key={t.id}
                    className="grid grid-cols-[1fr_80px_100px_80px_60px_70px_80px] gap-2 px-5 py-2.5 border-b last:border-0 hover:bg-accent/30 transition-colors items-center"
                  >
                    <div className="text-[13px] font-semibold text-foreground">{t.ticker}</div>
                    <div className="text-[12px] tabular-nums text-foreground">${t.strike}</div>
                    <div className="text-[12px] tabular-nums text-muted-foreground">{t.expiry}</div>
                    <div className="text-[12px] tabular-nums text-foreground">${t.sold_price.toFixed(2)}</div>
                    <div className="text-[12px] tabular-nums text-muted-foreground">{t.contracts}</div>
                    <div>
                      <span className={cn(
                        'inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-semibold ring-1 ring-inset',
                        t.status === 'open'
                          ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 ring-emerald-600/20'
                          : 'bg-gray-50 dark:bg-gray-500/10 text-gray-600 dark:text-gray-400 ring-gray-500/20'
                      )}>
                        {t.status}
                      </span>
                    </div>
                    <div className="text-[12px] font-semibold tabular-nums">
                      {pnl !== null ? (
                        <span className={pnl >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}>
                          {pnl >= 0 ? '+' : ''}${pnl.toFixed(0)}
                        </span>
                      ) : (
                        <span className="text-muted-foreground/50">--</span>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
