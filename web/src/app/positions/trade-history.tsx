'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
          // This returns open trades; for history we'd need a separate endpoint.
          // For now, show all trades from the same endpoint.
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
    <Card className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
      <CardHeader className="cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <CardTitle className="flex items-center justify-between text-[14px] font-semibold">
          <span>Trade History</span>
          <span className="text-[12px] text-muted-foreground">
            {expanded ? 'Collapse' : 'Expand'}
          </span>
        </CardTitle>
      </CardHeader>

      {expanded && (
        <CardContent>
          {loading ? (
            <p className="text-[12px] text-muted-foreground">Loading...</p>
          ) : trades.length === 0 ? (
            <p className="text-[12px] text-muted-foreground">No trades yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="border-b text-left text-[11px] text-muted-foreground">
                    <th className="pb-2 pr-4 font-medium">Ticker</th>
                    <th className="pb-2 pr-4 font-medium">Strike</th>
                    <th className="pb-2 pr-4 font-medium">Expiry</th>
                    <th className="pb-2 pr-4 font-medium">Premium</th>
                    <th className="pb-2 pr-4 font-medium">Contracts</th>
                    <th className="pb-2 pr-4 font-medium">Status</th>
                    <th className="pb-2 font-medium">P&L</th>
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
                        <td className="py-2 pr-4">${t.sold_price.toFixed(2)}</td>
                        <td className="py-2 pr-4">{t.contracts}</td>
                        <td className="py-2 pr-4">
                          <span
                            className={cn(
                              'text-[11px]',
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
                                pnl >= 0 ? 'text-emerald-600' : 'text-red-600'
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
        </CardContent>
      )}
    </Card>
  )
}
