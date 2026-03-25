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
          const data = await res.json()
          setTrades(data)
        }
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  return (
    <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-5 py-4 flex items-center justify-between text-left hover:bg-accent/50 transition-colors"
      >
        <span className="text-[14px] font-semibold">Trade History</span>
        <span className="text-[12px] text-muted-foreground">
          {expanded ? 'Collapse' : 'Expand'}
        </span>
      </button>

      {expanded && (
        <div className="px-5 pb-4">
          {loading ? (
            <p className="text-[12px] text-muted-foreground">Loading...</p>
          ) : trades.length === 0 ? (
            <p className="text-[12px] text-muted-foreground">No trades yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="border-b text-left">
                    <th className="pb-2 pr-4 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                      Ticker
                    </th>
                    <th className="pb-2 pr-4 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                      Strike
                    </th>
                    <th className="pb-2 pr-4 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                      Expiry
                    </th>
                    <th className="pb-2 pr-4 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                      Premium
                    </th>
                    <th className="pb-2 pr-4 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                      Contracts
                    </th>
                    <th className="pb-2 pr-4 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                      Status
                    </th>
                    <th className="pb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                      P&L
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((t) => {
                    const pnl =
                      t.status === 'closed' && t.close_price !== null
                        ? (t.sold_price - t.close_price) * t.contracts * 100
                        : null
                    return (
                      <tr key={t.id} className="border-b last:border-0">
                        <td className="py-2 pr-4 font-medium">{t.ticker}</td>
                        <td className="py-2 pr-4">${t.strike}</td>
                        <td className="py-2 pr-4">{t.expiry}</td>
                        <td className="py-2 pr-4">
                          ${t.sold_price.toFixed(2)}
                        </td>
                        <td className="py-2 pr-4">{t.contracts}</td>
                        <td className="py-2 pr-4">
                          <span
                            className={cn(
                              'text-[11px] font-medium',
                              t.status === 'open'
                                ? 'text-emerald-600'
                                : 'text-muted-foreground'
                            )}
                          >
                            {t.status}
                          </span>
                        </td>
                        <td className="py-2">
                          {pnl !== null ? (
                            <span
                              className={cn(
                                'font-medium',
                                pnl >= 0
                                  ? 'text-emerald-600'
                                  : 'text-red-600'
                              )}
                            >
                              {pnl >= 0 ? '+' : ''}${pnl.toFixed(0)}
                            </span>
                          ) : (
                            <span className="text-muted-foreground">--</span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
