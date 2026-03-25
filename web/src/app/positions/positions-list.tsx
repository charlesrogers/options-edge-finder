'use client'

import { useEffect, useState, useCallback } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { PositionAlert, AlertLevel } from '@/lib/copilot'
import { LogTradeDialog } from './log-trade-dialog'

type AlertWithId = PositionAlert & { tradeId?: number }

const LEVEL_STYLES: Record<
  AlertLevel,
  {
    dot: string
    border: string
    badge: string
    label: string
    alertBorder: string
    alertBg: string
    titleColor: string
    detailColor: string
  }
> = {
  SAFE: {
    dot: 'bg-emerald-500',
    border: 'border-emerald-200 dark:border-emerald-500/20',
    badge: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
    label: 'Safe',
    alertBorder: 'border-emerald-200 dark:border-emerald-500/20',
    alertBg: '',
    titleColor: 'text-emerald-800 dark:text-emerald-300',
    detailColor: 'text-emerald-700 dark:text-emerald-400',
  },
  WATCH: {
    dot: 'bg-amber-500',
    border: 'border-amber-200 dark:border-amber-500/20',
    badge: 'bg-amber-500/10 text-amber-700 dark:text-amber-400',
    label: 'Watch',
    alertBorder: 'border-amber-200 dark:border-amber-500/20',
    alertBg: '',
    titleColor: 'text-amber-800 dark:text-amber-300',
    detailColor: 'text-amber-700 dark:text-amber-400',
  },
  CLOSE_SOON: {
    dot: 'bg-amber-500',
    border: 'border-amber-200 dark:border-amber-500/20',
    badge: 'bg-orange-500/10 text-orange-700 dark:text-orange-400',
    label: 'Close Soon',
    alertBorder: 'border-amber-200 dark:border-amber-500/20',
    alertBg: '',
    titleColor: 'text-amber-800 dark:text-amber-300',
    detailColor: 'text-amber-700 dark:text-amber-400',
  },
  CLOSE_NOW: {
    dot: 'bg-red-500',
    border: 'border-red-200 dark:border-red-500/20',
    badge: 'bg-red-500/10 text-red-700 dark:text-red-400',
    label: 'Close Now',
    alertBorder: 'border-red-200 dark:border-red-500/20',
    alertBg: '',
    titleColor: 'text-red-800 dark:text-red-300',
    detailColor: 'text-red-700 dark:text-red-400',
  },
  EMERGENCY: {
    dot: 'bg-red-500 animate-pulse',
    border: 'border-red-200 dark:border-red-500/20',
    badge: 'bg-red-600/10 text-red-700 dark:text-red-400',
    label: 'Emergency',
    alertBorder: 'border-red-200 dark:border-red-500/20',
    alertBg: '',
    titleColor: 'text-red-800 dark:text-red-300',
    detailColor: 'text-red-700 dark:text-red-400',
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
      <div className="rounded-xl border bg-card py-8 text-center shadow-sm shadow-black/[0.04]">
        <p className="text-[13px] text-destructive">{error}</p>
      </div>
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
        <div className="rounded-xl border bg-card text-center py-16 shadow-sm shadow-black/[0.04]">
          <div className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-muted mb-3">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="text-muted-foreground"
            >
              <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
            </svg>
          </div>
          <p className="text-[15px] font-medium">No open positions</p>
          <p className="text-[13px] text-muted-foreground mt-1">
            Log a trade to get started.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {alerts.map((alert, idx) => {
            const style = LEVEL_STYLES[alert.level]
            return (
              <div
                key={idx}
                className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden hover:shadow-md hover:shadow-black/[0.06] transition-shadow"
              >
                {/* Header */}
                <div className="px-5 pt-4 pb-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-[15px] font-semibold">
                      {alert.ticker} ${alert.strike} Call
                    </span>
                    <Badge className={cn('text-[10px]', style.badge)}>
                      {style.label}
                    </Badge>
                  </div>
                  {alert.dte <= 7 && (
                    <span className="text-[11px] font-medium text-red-600 dark:text-red-400">
                      {alert.dte} DTE
                    </span>
                  )}
                </div>

                {/* Content */}
                <div className="px-5 pb-4 space-y-3">
                  {/* Metrics row */}
                  <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
                    <Metric label="DTE" value={`${alert.dte}`} />
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
                          Buyback:{' '}
                          <span className="font-medium text-foreground">
                            ${alert.buybackCost.toFixed(2)}
                          </span>
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

                  {/* Status alert pattern for urgent alerts */}
                  {(alert.level === 'CLOSE_NOW' ||
                    alert.level === 'EMERGENCY') && (
                    <div
                      className={cn(
                        'rounded-lg border px-4 py-3 flex items-start gap-2',
                        style.alertBorder
                      )}
                    >
                      <span
                        className={cn(
                          'h-2 w-2 rounded-full mt-1.5 flex-shrink-0',
                          style.dot
                        )}
                      />
                      <div>
                        <p
                          className={cn(
                            'text-[13px] font-semibold',
                            style.titleColor
                          )}
                        >
                          {alert.reason}
                        </p>
                        <p
                          className={cn(
                            'text-[12px] mt-0.5',
                            style.detailColor
                          )}
                        >
                          {alert.action}
                        </p>
                      </div>
                    </div>
                  )}

                  {/* Status alert for WATCH / CLOSE_SOON */}
                  {(alert.level === 'WATCH' ||
                    alert.level === 'CLOSE_SOON') && (
                    <div
                      className={cn(
                        'rounded-lg border px-4 py-3 flex items-start gap-2',
                        style.alertBorder
                      )}
                    >
                      <span
                        className={cn(
                          'h-2 w-2 rounded-full mt-1.5 flex-shrink-0',
                          style.dot
                        )}
                      />
                      <div>
                        <p
                          className={cn(
                            'text-[13px] font-semibold',
                            style.titleColor
                          )}
                        >
                          {alert.reason}
                        </p>
                        <p className="text-[12px] text-muted-foreground mt-0.5">
                          {alert.action}
                        </p>
                      </div>
                    </div>
                  )}

                  {/* Close button for urgent */}
                  {(alert.level === 'CLOSE_NOW' ||
                    alert.level === 'EMERGENCY') && (
                    <Button
                      variant="destructive"
                      size="sm"
                      className="active:translate-y-px"
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
                </div>
              </div>
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
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="text-[13px] font-medium mt-0.5">{value}</p>
    </div>
  )
}
