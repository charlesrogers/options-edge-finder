'use client'

import { useEffect, useState, useCallback } from 'react'
import { cn } from '@/lib/utils'
import type { PositionAlert, AlertLevel } from '@/lib/copilot'
import { LogTradeDialog } from './log-trade-dialog'

type AlertWithId = PositionAlert & { tradeId?: number }

/* ── Alert-level visual system ── */

const LEVEL_ACCENT: Record<AlertLevel, string> = {
  SAFE: 'bg-emerald-500',
  WATCH: 'bg-amber-500',
  CLOSE_SOON: 'bg-orange-500',
  CLOSE_NOW: 'bg-red-500',
  EMERGENCY: 'bg-red-500 animate-pulse',
}

const LEVEL_BADGE: Record<AlertLevel, string> = {
  SAFE: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 ring-emerald-600/20',
  WATCH: 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 ring-amber-600/20',
  CLOSE_SOON: 'bg-orange-50 dark:bg-orange-500/10 text-orange-700 dark:text-orange-400 ring-orange-600/20',
  CLOSE_NOW: 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 ring-red-600/20',
  EMERGENCY: 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 ring-red-600/20 animate-pulse',
}

const LEVEL_LABEL: Record<AlertLevel, string> = {
  SAFE: 'Safe',
  WATCH: 'Watch',
  CLOSE_SOON: 'Close Soon',
  CLOSE_NOW: 'Close Now',
  EMERGENCY: 'Emergency',
}

const LEVEL_ALERT_STYLE: Record<AlertLevel, { border: string; bg: string; title: string; detail: string }> = {
  SAFE: {
    border: 'border-emerald-200 dark:border-emerald-500/20',
    bg: 'bg-emerald-50/50 dark:bg-emerald-500/5',
    title: 'text-emerald-800 dark:text-emerald-300',
    detail: 'text-emerald-700 dark:text-emerald-400',
  },
  WATCH: {
    border: 'border-amber-200 dark:border-amber-500/20',
    bg: 'bg-amber-50/50 dark:bg-amber-500/5',
    title: 'text-amber-800 dark:text-amber-300',
    detail: 'text-amber-700 dark:text-amber-400',
  },
  CLOSE_SOON: {
    border: 'border-orange-200 dark:border-orange-500/20',
    bg: 'bg-orange-50/50 dark:bg-orange-500/5',
    title: 'text-orange-800 dark:text-orange-300',
    detail: 'text-orange-700 dark:text-orange-400',
  },
  CLOSE_NOW: {
    border: 'border-red-200 dark:border-red-500/20',
    bg: 'bg-red-50/50 dark:bg-red-500/5',
    title: 'text-red-800 dark:text-red-300',
    detail: 'text-red-700 dark:text-red-400',
  },
  EMERGENCY: {
    border: 'border-red-300 dark:border-red-500/30',
    bg: 'bg-red-50/70 dark:bg-red-500/10',
    title: 'text-red-800 dark:text-red-300',
    detail: 'text-red-700 dark:text-red-400',
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

  /* ── Loading skeleton ── */
  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="flex rounded-xl border bg-card overflow-hidden">
            <div className="w-1 flex-shrink-0 bg-muted animate-pulse" />
            <div className="flex-1 px-5 pt-4 pb-4 space-y-3">
              <div className="flex items-center gap-3">
                <div className="h-5 w-32 rounded-md bg-muted animate-pulse" />
                <div className="h-5 w-14 rounded-md bg-muted animate-pulse" />
              </div>
              <div className="grid grid-cols-4 gap-4">
                {[1, 2, 3, 4].map((j) => (
                  <div key={j} className="space-y-1.5">
                    <div className="h-7 w-12 rounded bg-muted animate-pulse" />
                    <div className="h-3 w-16 rounded bg-muted/60 animate-pulse" />
                  </div>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>
    )
  }

  /* ── Error state ── */
  if (error) {
    return (
      <div className="rounded-xl border bg-card py-12 text-center shadow-sm shadow-black/[0.04]">
        <div className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-red-50 dark:bg-red-500/10 mb-3">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-red-500">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
        </div>
        <p className="text-[14px] font-medium text-foreground">Something went wrong</p>
        <p className="text-[12px] text-muted-foreground mt-1">{error}</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <p className="text-[12px] text-muted-foreground">
          {alerts.length} open position{alerts.length !== 1 ? 's' : ''}
        </p>
        <LogTradeDialog onSuccess={fetchAlerts} />
      </div>

      {/* Empty state */}
      {alerts.length === 0 ? (
        <div className="rounded-xl border bg-card text-center py-16 shadow-sm shadow-black/[0.04]">
          <div className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-muted mb-4">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-muted-foreground">
              <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
            </svg>
          </div>
          <p className="text-[15px] font-semibold text-foreground">No open positions</p>
          <p className="text-[13px] text-muted-foreground mt-1">
            Log a trade to start getting copilot alerts.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {alerts.map((alert, idx) => (
            <PositionCard key={idx} alert={alert} onClose={fetchAlerts} />
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Position Card ── */

function PositionCard({ alert, onClose }: { alert: AlertWithId; onClose: () => void }) {
  const isUrgent = alert.level === 'CLOSE_NOW' || alert.level === 'EMERGENCY'
  const isWarn = alert.level === 'WATCH' || alert.level === 'CLOSE_SOON'
  const alertStyle = LEVEL_ALERT_STYLE[alert.level]

  return (
    <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden hover:shadow-md hover:shadow-black/[0.06] transition-shadow flex">
      {/* Left accent bar */}
      <div className={cn('w-1 flex-shrink-0', LEVEL_ACCENT[alert.level])} />

      <div className="flex-1 min-w-0">
        {/* Header */}
        <div className="px-5 pt-4 pb-3 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <h3 className="text-[15px] font-semibold text-foreground truncate">
              {alert.ticker} ${alert.strike} Call
            </h3>
            <span className={cn(
              'inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-semibold ring-1 ring-inset flex-shrink-0',
              LEVEL_BADGE[alert.level]
            )}>
              {LEVEL_LABEL[alert.level]}
            </span>
          </div>
          {alert.dte <= 7 && (
            <span className="text-[11px] font-semibold text-red-600 dark:text-red-400 tabular-nums flex-shrink-0">
              {alert.dte}d left
            </span>
          )}
        </div>

        {/* Metrics grid */}
        <div className="px-5 pb-3">
          <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
            <MetricCell
              label="DTE"
              value={`${alert.dte}`}
              accent={alert.dte <= 5 ? 'text-red-600 dark:text-red-400' : undefined}
            />
            <MetricCell
              label="% from Strike"
              value={`${alert.pctFromStrike >= 0 ? '+' : ''}${alert.pctFromStrike.toFixed(1)}%`}
              accent={alert.pctFromStrike < 0 ? 'text-red-600 dark:text-red-400' : alert.pctFromStrike < 2 ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'}
            />
            <MetricCell
              label="Premium Captured"
              value={`${alert.premiumCapturedPct.toFixed(0)}%`}
            />
            <MetricCell
              label="P(assignment)"
              value={`${(alert.pAssignment * 100).toFixed(0)}%`}
              accent={alert.pAssignment > 0.5 ? 'text-red-600 dark:text-red-400' : undefined}
            />
          </div>

          {/* Premium captured progress bar */}
          <div className="h-1 rounded-full bg-muted overflow-hidden mt-3">
            <div
              className="h-full rounded-full bg-emerald-500 transition-all"
              style={{ width: `${Math.min(100, alert.premiumCapturedPct)}%` }}
            />
          </div>
        </div>

        {/* Buyback + P&L row */}
        {(alert.buybackCost !== null || alert.netPnl !== null) && (
          <div className="px-5 pb-3 flex items-center gap-5 text-[12px]">
            {alert.buybackCost !== null && (
              <span className="text-muted-foreground">
                Buyback cost:{' '}
                <span className="font-semibold text-foreground tabular-nums">
                  ${alert.buybackCost.toFixed(2)}
                </span>
              </span>
            )}
            {alert.netPnl !== null && (
              <span className="text-muted-foreground">
                Net P&L:{' '}
                <span className={cn(
                  'font-semibold tabular-nums',
                  alert.netPnl >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'
                )}>
                  {alert.netPnl >= 0 ? '+' : ''}${alert.netPnl.toFixed(0)}
                </span>
              </span>
            )}
            {alert.daysToExDiv !== null && alert.daysToExDiv <= 14 && (
              <span className="text-amber-600 dark:text-amber-400 font-medium">
                Ex-div in {alert.daysToExDiv}d
              </span>
            )}
            {alert.daysToEarnings !== null && alert.daysToEarnings <= 14 && (
              <span className="text-amber-600 dark:text-amber-400 font-medium">
                Earnings in {alert.daysToEarnings}d
              </span>
            )}
          </div>
        )}

        {/* Alert message — WATCH / CLOSE_SOON */}
        {isWarn && (
          <div className="px-5 pb-4">
            <div className={cn(
              'rounded-lg border px-4 py-3 flex items-start gap-2.5',
              alertStyle.border, alertStyle.bg
            )}>
              <span className={cn('h-2 w-2 rounded-full mt-1.5 flex-shrink-0', LEVEL_ACCENT[alert.level])} />
              <div>
                <p className={cn('text-[13px] font-semibold leading-snug', alertStyle.title)}>
                  {alert.reason}
                </p>
                <p className={cn('text-[12px] mt-0.5 leading-relaxed', alertStyle.detail)}>
                  {alert.action}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Alert message — CLOSE_NOW / EMERGENCY with full-width red banner */}
        {isUrgent && (
          <div className={cn(
            'px-5 py-3 flex items-start gap-3 border-t',
            alert.level === 'EMERGENCY'
              ? 'bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/20'
              : 'bg-red-50/60 dark:bg-red-500/5 border-red-100 dark:border-red-500/15'
          )}>
            <span className={cn('h-2 w-2 rounded-full mt-1.5 flex-shrink-0', LEVEL_ACCENT[alert.level])} />
            <div className="flex-1 min-w-0">
              <p className={cn('text-[13px] font-semibold leading-snug', alertStyle.title)}>
                {alert.reason}
              </p>
              <p className={cn('text-[12px] mt-0.5 leading-relaxed', alertStyle.detail)}>
                {alert.action}
              </p>
            </div>
            <button
              onClick={async () => {
                if (!alert.tradeId) return
                await fetch(`/api/positions/${alert.tradeId}`, {
                  method: 'PATCH',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ closePrice: alert.buybackCost ?? 0 }),
                })
                onClose()
              }}
              className="flex-shrink-0 inline-flex items-center px-3 py-1.5 rounded-lg text-[12px] font-semibold bg-red-600 text-white hover:bg-red-700 transition-colors active:translate-y-px"
            >
              Mark Closed
            </button>
          </div>
        )}

        {/* SAFE level: subtle inline message */}
        {alert.level === 'SAFE' && (
          <div className="px-5 pb-4">
            <p className="text-[12px] text-emerald-700 dark:text-emerald-400">
              {alert.action}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Metric Cell ── */

function MetricCell({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div>
      <div className={cn('text-2xl font-semibold tracking-tight tabular-nums', accent ?? 'text-foreground')}>
        {value}
      </div>
      <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground mt-0.5">
        {label}
      </div>
    </div>
  )
}
