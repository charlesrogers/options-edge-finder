'use client'

import { useEffect, useState, useCallback } from 'react'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { PositionAlert, AlertLevel } from '@/lib/copilot'
import { LogTradeDialog } from './log-trade-dialog'

type AlertWithId = PositionAlert & { tradeId?: number }

const LEVEL_STYLES: Record<AlertLevel, { border: string; badge: string; label: string }> = {
  SAFE: {
    border: 'border-l-4 border-l-emerald-500',
    badge: 'bg-emerald-500/10 text-emerald-700',
    label: 'Safe',
  },
  WATCH: {
    border: 'border-l-4 border-l-amber-500',
    badge: 'bg-amber-500/10 text-amber-700',
    label: 'Watch',
  },
  CLOSE_SOON: {
    border: 'border-l-4 border-l-orange-500',
    badge: 'bg-orange-500/10 text-orange-700',
    label: 'Close Soon',
  },
  CLOSE_NOW: {
    border: 'border-l-4 border-l-red-500',
    badge: 'bg-red-500/10 text-red-700',
    label: 'Close Now',
  },
  EMERGENCY: {
    border: 'border-l-4 border-l-red-600 animate-pulse',
    badge: 'bg-red-600/10 text-red-700',
    label: 'Emergency',
  },
}

export function PositionsList() {
  const [alerts, setAlerts] = useState<AlertWithId[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchAlerts = useCallback(async () => {
    try {
      setLoading(true)
      const res = await fetch('/api/copilot')
      if (!res.ok) throw new Error('Failed to fetch alerts')
      const data = await res.json()
      setAlerts(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAlerts()
  }, [fetchAlerts])

  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-32 animate-pulse rounded-xl border bg-muted/30"
          />
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-[13px] text-destructive">
          {error}
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-[12px] text-muted-foreground">
          {alerts.length} open position{alerts.length !== 1 ? 's' : ''}
        </p>
        <LogTradeDialog onSuccess={fetchAlerts} />
      </div>

      {alerts.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-[13px] text-muted-foreground">
              No open positions. Log a trade to get started.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {alerts.map((alert, idx) => {
            const style = LEVEL_STYLES[alert.level]
            return (
              <Card
                key={idx}
                className={cn(
                  'rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden',
                  style.border
                )}
              >
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-[15px] font-semibold">
                      {alert.ticker} ${alert.strike} Call
                    </CardTitle>
                    <Badge className={cn('text-[10px]', style.badge)}>
                      {style.label}
                    </Badge>
                  </div>
                </CardHeader>

                <CardContent className="space-y-3">
                  {/* Metrics row */}
                  <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
                    <Metric
                      label="DTE"
                      value={`${alert.dte}`}
                    />
                    <Metric
                      label="% from Strike"
                      value={`${alert.pctFromStrike >= 0 ? '+' : ''}${alert.pctFromStrike.toFixed(1)}%`}
                    />
                    <Metric
                      label="Premium Captured"
                      value={`${alert.premiumCapturedPct.toFixed(0)}%`}
                    />
                    <Metric
                      label="P(assignment)"
                      value={`${(alert.pAssignment * 100).toFixed(0)}%`}
                    />
                  </div>

                  {/* Buyback + P&L */}
                  {(alert.buybackCost !== null || alert.netPnl !== null) && (
                    <div className="flex gap-4 text-[12px]">
                      {alert.buybackCost !== null && (
                        <span className="text-muted-foreground">
                          Buyback: <span className="font-medium text-foreground">${alert.buybackCost.toFixed(2)}</span>
                        </span>
                      )}
                      {alert.netPnl !== null && (
                        <span className="text-muted-foreground">
                          Net P&L:{' '}
                          <span
                            className={cn(
                              'font-medium',
                              alert.netPnl >= 0
                                ? 'text-emerald-600'
                                : 'text-red-600'
                            )}
                          >
                            {alert.netPnl >= 0 ? '+' : ''}${alert.netPnl.toFixed(0)}
                          </span>
                        </span>
                      )}
                    </div>
                  )}

                  {/* Action banner for urgent alerts */}
                  {(alert.level === 'CLOSE_NOW' ||
                    alert.level === 'EMERGENCY') && (
                    <div className="rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900 p-3">
                      <p className="text-[12px] font-semibold text-red-700 dark:text-red-400">
                        {alert.reason}
                      </p>
                      <p className="mt-1 text-[11px] text-red-600 dark:text-red-500">
                        {alert.action}
                      </p>
                    </div>
                  )}

                  {/* Reason for non-urgent */}
                  {alert.level !== 'CLOSE_NOW' &&
                    alert.level !== 'EMERGENCY' &&
                    alert.level !== 'SAFE' && (
                      <p className="text-[11px] text-muted-foreground">
                        {alert.reason} — {alert.action}
                      </p>
                    )}

                  {/* Close button for urgent */}
                  {(alert.level === 'CLOSE_NOW' ||
                    alert.level === 'EMERGENCY') && (
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={async () => {
                        if (!alert.tradeId) return
                        await fetch(`/api/positions/${alert.tradeId}`, {
                          method: 'PATCH',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({
                            closePrice: alert.buybackCost ?? 0,
                          }),
                        })
                        fetchAlerts()
                      }}
                    >
                      Mark Closed
                    </Button>
                  )}
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </div>
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
