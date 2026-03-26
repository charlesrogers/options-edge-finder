'use client'

import { useEffect, useState, useCallback } from 'react'
import { cn } from '@/lib/utils'
import type { PositionAlert, AlertLevel } from '@/lib/copilot'
import { LogTradeDialog } from './log-trade-dialog'

type AlertWithId = PositionAlert & { tradeId?: number }

/* ── Colors by alert level (matches Jebbix priority system) ── */

const ACCENT: Record<AlertLevel, string> = {
  SAFE: 'bg-emerald-500',
  WATCH: 'bg-amber-500',
  CLOSE_SOON: 'bg-orange-500',
  CLOSE_NOW: 'bg-red-500',
  EMERGENCY: 'bg-red-500 animate-pulse',
}

const BADGE: Record<AlertLevel, string> = {
  SAFE: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 ring-emerald-600/20',
  WATCH: 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 ring-amber-600/20',
  CLOSE_SOON: 'bg-orange-50 dark:bg-orange-500/10 text-orange-700 dark:text-orange-400 ring-orange-600/20',
  CLOSE_NOW: 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 ring-red-600/20',
  EMERGENCY: 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 ring-red-600/20',
}

const LABEL: Record<AlertLevel, string> = {
  SAFE: 'Safe', WATCH: 'Watch', CLOSE_SOON: 'Close Soon',
  CLOSE_NOW: 'Close Now', EMERGENCY: 'Emergency',
}

const ALERT_BG: Record<AlertLevel, { border: string; bg: string; dot: string; title: string; body: string }> = {
  SAFE:       { border: 'border-emerald-200', bg: 'bg-emerald-50', dot: 'bg-emerald-500', title: 'text-emerald-900', body: 'text-emerald-800' },
  WATCH:      { border: 'border-amber-200',   bg: 'bg-amber-50',   dot: 'bg-amber-500',   title: 'text-amber-900',   body: 'text-amber-800' },
  CLOSE_SOON: { border: 'border-orange-200',  bg: 'bg-orange-50',  dot: 'bg-orange-500',  title: 'text-orange-900',  body: 'text-orange-800' },
  CLOSE_NOW:  { border: 'border-red-200',     bg: 'bg-red-50',     dot: 'bg-red-500',     title: 'text-red-900',     body: 'text-red-800' },
  EMERGENCY:  { border: 'border-red-300',     bg: 'bg-red-50',     dot: 'bg-red-500',     title: 'text-red-900',     body: 'text-red-800' },
}


/* ── Build dynamic headline (like Jebbix's buildHeadline) ── */

function buildHeadline(alerts: AlertWithId[]): { title: string; subtitle: string; accent: 'green' | 'red' | 'default' } {
  if (alerts.length === 0) {
    return { title: 'No open positions', subtitle: 'Log a trade to start getting copilot alerts.', accent: 'default' }
  }

  const emergency = alerts.filter(a => a.level === 'EMERGENCY')
  const closeNow = alerts.filter(a => a.level === 'CLOSE_NOW')
  const closeSoon = alerts.filter(a => a.level === 'CLOSE_SOON')
  const safe = alerts.filter(a => a.level === 'SAFE')

  if (emergency.length > 0) {
    return {
      title: `${emergency.length} position${emergency.length > 1 ? 's need' : ' needs'} immediate action`,
      subtitle: `${emergency[0].ticker} $${emergency[0].strike} Call is ITM near ex-dividend. Buy back NOW to avoid assignment.`,
      accent: 'red',
    }
  }

  if (closeNow.length > 0) {
    return {
      title: `${closeNow.length} position${closeNow.length > 1 ? 's' : ''} at risk — close today`,
      subtitle: `${closeNow[0].ticker} $${closeNow[0].strike} Call is ${closeNow[0].pctFromStrike < 0 ? 'in the money' : `${closeNow[0].pctFromStrike.toFixed(1)}% from strike`}. Assignment probability: ${(closeNow[0].pAssignment * 100).toFixed(0)}%.`,
      accent: 'red',
    }
  }

  if (closeSoon.length > 0) {
    return {
      title: `${closeSoon.length} position${closeSoon.length > 1 ? 's' : ''} to close this week`,
      subtitle: `${closeSoon[0].ticker} $${closeSoon[0].strike} Call — ${closeSoon[0].reason}`,
      accent: 'default',
    }
  }

  if (safe.length === alerts.length) {
    return {
      title: 'All positions are safe — nothing to do today',
      subtitle: `${alerts.length} open position${alerts.length > 1 ? 's' : ''}, all well outside their strikes. Keep holding.`,
      accent: 'green',
    }
  }

  return {
    title: `${alerts.length} open positions`,
    subtitle: `${safe.length} safe, ${alerts.length - safe.length} need attention.`,
    accent: 'default',
  }
}


/* ── Stat Card (matches Jebbix StatCard exactly) ── */

function StatCard({ label, value, insight, accent }: {
  label: string; value: string; insight: string; accent?: 'green' | 'red' | 'default'
}) {
  const valueColor = accent === 'green' ? 'text-emerald-600' : accent === 'red' ? 'text-red-600' : 'text-foreground'
  return (
    <div className="rounded-xl border bg-card p-5 shadow-sm shadow-black/[0.04]">
      <p className="text-[12px] font-medium text-muted-foreground uppercase tracking-wider">{label}</p>
      <div className="flex items-center gap-2 mt-1">
        <p className={cn('text-2xl font-semibold tracking-tight', valueColor)}>{value}</p>
      </div>
      <p className="text-[12px] text-muted-foreground mt-1.5 leading-relaxed">{insight}</p>
    </div>
  )
}


/* ── Main Component ── */

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

  useEffect(() => { fetchAlerts() }, [fetchAlerts])

  /* ── Skeleton (matches Jebbix SkeletonDashboard) ── */
  if (loading) {
    return (
      <div className="space-y-6">
        <div className="space-y-2">
          <div className="h-7 w-96 bg-muted animate-pulse rounded-md" />
          <div className="h-4 w-full max-w-lg bg-muted animate-pulse rounded-md" />
        </div>
        <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
          {[1, 2, 3, 4].map(i => <div key={i} className="h-28 bg-muted animate-pulse rounded-xl" />)}
        </div>
        <div className="space-y-3">
          {[1, 2, 3].map(i => <div key={i} className="h-40 bg-muted animate-pulse rounded-xl" />)}
        </div>
      </div>
    )
  }

  /* ── Error ── */
  if (error) {
    return (
      <div className="rounded-xl border bg-card p-8 text-center shadow-sm">
        <div className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10 mb-4">
          <span className="text-destructive text-lg">!</span>
        </div>
        <p className="text-[15px] font-medium mb-1">Something went wrong</p>
        <p className="text-[13px] text-muted-foreground mb-4">{error}</p>
        <button
          onClick={fetchAlerts}
          className="inline-flex items-center px-4 py-2 rounded-lg bg-primary text-primary-foreground text-[13px] font-medium hover:bg-primary/90 transition-colors active:translate-y-px"
        >
          Retry
        </button>
      </div>
    )
  }

  const headline = buildHeadline(alerts)
  const urgent = alerts.filter(a => a.level === 'CLOSE_NOW' || a.level === 'EMERGENCY')
  const safe = alerts.filter(a => a.level === 'SAFE')
  const totalPnl = alerts.reduce((s, a) => s + (a.netPnl ?? 0), 0)
  const avgCapture = alerts.length > 0 ? alerts.reduce((s, a) => s + a.premiumCapturedPct, 0) / alerts.length : 0

  return (
    <div className="space-y-6">
      {/* ── Dynamic headline (like Jebbix) ── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{headline.title}</h1>
          <p className="text-[13px] text-muted-foreground mt-1 max-w-2xl leading-relaxed">
            {headline.subtitle}
          </p>
        </div>
        <LogTradeDialog onSuccess={fetchAlerts} />
      </div>

      {/* ── Stat cards row (like Jebbix's GPA / Missing / Forecast / Actions) ── */}
      {alerts.length > 0 && (
        <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Open Positions"
            value={`${alerts.length}`}
            insight={`${safe.length} safe, ${alerts.length - safe.length} need attention`}
            accent={urgent.length > 0 ? 'red' : 'green'}
          />
          <StatCard
            label="Urgent"
            value={`${urgent.length}`}
            insight={urgent.length === 0 ? 'No positions need immediate action' : `${urgent[0].ticker} is ${urgent[0].pctFromStrike < 0 ? 'ITM' : 'near strike'}`}
            accent={urgent.length > 0 ? 'red' : 'green'}
          />
          <StatCard
            label="Avg Captured"
            value={`${avgCapture.toFixed(0)}%`}
            insight={avgCapture >= 75 ? 'Consider taking profit on mature positions' : 'Positions still have time value to decay'}
          />
          <StatCard
            label="Net P&L"
            value={`${totalPnl >= 0 ? '+' : ''}$${totalPnl.toFixed(0)}`}
            insight="If all positions closed now at current prices"
            accent={totalPnl >= 0 ? 'green' : 'red'}
          />
        </div>
      )}

      {/* ── Alert feed (like Jebbix AlertFeed — urgent first) ── */}
      {urgent.length > 0 && (
        <div>
          <h2 className="text-[14px] font-semibold mb-2">Alerts</h2>
          <div className="space-y-2">
            {urgent.map((alert, idx) => (
              <AlertCard key={idx} alert={alert} onClose={fetchAlerts} />
            ))}
          </div>
        </div>
      )}

      {/* ── Position cards ── */}
      {alerts.length === 0 ? (
        <div className="rounded-xl border bg-card text-center py-16 shadow-sm shadow-black/[0.04]">
          <div className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-muted mb-4">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-muted-foreground">
              <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
            </svg>
          </div>
          <p className="text-[15px] font-semibold text-foreground">No open positions</p>
          <p className="text-[13px] text-muted-foreground mt-1">Log a trade to start getting copilot alerts.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {alerts
            .filter(a => a.level !== 'CLOSE_NOW' && a.level !== 'EMERGENCY')
            .map((alert, idx) => (
              <PositionCard key={idx} alert={alert} onClose={fetchAlerts} />
            ))}
        </div>
      )}
    </div>
  )
}


/* ── Alert Card (urgent — like Jebbix AlertFeed items) ── */

function AlertCard({ alert, onClose }: { alert: AlertWithId; onClose: () => void }) {
  const s = ALERT_BG[alert.level]
  return (
    <div className={cn('flex items-start gap-3 px-4 py-3 rounded-xl border', s.border, s.bg)}>
      <span className="h-5 w-5 rounded-full bg-white/60 flex items-center justify-center flex-shrink-0 mt-0.5">
        <span className={cn('h-2 w-2 rounded-full', s.dot, alert.level === 'EMERGENCY' && 'animate-pulse')} />
      </span>
      <div className="flex-1 min-w-0">
        <p className={cn('text-[13px] font-medium', s.title)}>
          {alert.ticker} ${alert.strike} Call — {alert.reason}
        </p>
        <p className={cn('text-[12px] mt-0.5', s.body)}>
          {alert.action}
        </p>
        <div className="flex items-center gap-4 mt-1.5">
          <span className="text-[11px] text-muted-foreground">
            {alert.dte} DTE · {alert.pctFromStrike >= 0 ? '+' : ''}{alert.pctFromStrike.toFixed(1)}% from strike · P(assign): {(alert.pAssignment * 100).toFixed(0)}%
          </span>
        </div>
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
  )
}


/* ── Position Card (non-urgent — like Jebbix CourseCard) ── */

function PositionCard({ alert, onClose }: { alert: AlertWithId; onClose: () => void }) {
  return (
    <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden hover:shadow-md hover:shadow-black/[0.06] transition-shadow">
      <div className="min-w-0">
        {/* Header — ticker + badge (like CourseCard name + letter badge) */}
        <div className="px-5 pt-4 pb-3">
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-[13px] font-semibold text-foreground leading-snug">
              {alert.ticker} ${alert.strike} Call
            </h3>
            <span className={cn(
              'inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-semibold ring-1 ring-inset flex-shrink-0',
              BADGE[alert.level]
            )}>
              {LABEL[alert.level]}
            </span>
          </div>

          {/* Large metric + secondary info (like CourseCard grade display) */}
          <div className="flex items-center gap-2 mt-2">
            <span className={cn(
              'text-2xl font-semibold tracking-tight',
              alert.pctFromStrike < 0 ? 'text-red-600' : alert.pctFromStrike < 3 ? 'text-amber-600' : 'text-emerald-600'
            )}>
              {alert.pctFromStrike >= 0 ? '+' : ''}{alert.pctFromStrike.toFixed(1)}%
            </span>
            <span className="text-[12px] text-muted-foreground">from strike</span>
            {alert.dte <= 7 && (
              <span className="text-[12px] font-medium text-red-600">{alert.dte}d left</span>
            )}
          </div>

          {/* Forecast-like insight */}
          <p className="text-[12px] text-muted-foreground mt-1.5">
            {alert.premiumCapturedPct.toFixed(0)}% premium captured · P(assignment): {(alert.pAssignment * 100).toFixed(0)}%
            {alert.netPnl !== null && (
              <> · Net P&L: <span className={cn('font-medium', alert.netPnl >= 0 ? 'text-emerald-600' : 'text-red-600')}>
                {alert.netPnl >= 0 ? '+' : ''}${alert.netPnl.toFixed(0)}
              </span></>
            )}
          </p>

          {/* Ex-div / earnings warning (like CourseCard missing alert) */}
          {alert.daysToExDiv !== null && alert.daysToExDiv <= 14 && (
            <div className="flex items-center gap-1.5 mt-2.5 px-2.5 py-1.5 rounded-lg bg-amber-50 dark:bg-amber-500/10 border border-amber-100 dark:border-amber-500/15">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-500 flex-shrink-0" />
              <span className="text-[12px] font-medium text-amber-700 dark:text-amber-400">
                Ex-dividend in {alert.daysToExDiv} days
              </span>
            </div>
          )}
          {alert.daysToEarnings !== null && alert.daysToEarnings <= 14 && (
            <div className="flex items-center gap-1.5 mt-2 px-2.5 py-1.5 rounded-lg bg-blue-50 dark:bg-blue-500/10 border border-blue-100 dark:border-blue-500/15">
              <span className="h-1.5 w-1.5 rounded-full bg-blue-500 flex-shrink-0" />
              <span className="text-[12px] font-medium text-blue-700 dark:text-blue-400">
                Earnings in {alert.daysToEarnings} days
              </span>
            </div>
          )}
        </div>

        {/* Category bars (like CourseCard category progress) */}
        <div className="px-5 pb-4 space-y-2">
          <div>
            <div className="flex justify-between items-center mb-1">
              <span className="text-[11px] text-muted-foreground">Premium captured</span>
              <span className="text-[11px] font-medium tabular-nums">{alert.premiumCapturedPct.toFixed(0)}%</span>
            </div>
            <div className="h-1 rounded-full bg-muted overflow-hidden">
              <div
                className="h-full rounded-full bg-emerald-500 transition-all"
                style={{ width: `${Math.min(100, alert.premiumCapturedPct)}%`, opacity: 0.7 }}
              />
            </div>
          </div>
          <div>
            <div className="flex justify-between items-center mb-1">
              <span className="text-[11px] text-muted-foreground">Time elapsed</span>
              <span className="text-[11px] font-medium tabular-nums">{alert.dte} DTE</span>
            </div>
            <div className="h-1 rounded-full bg-muted overflow-hidden">
              <div
                className="h-full rounded-full bg-blue-500 transition-all"
                style={{ width: `${Math.max(0, Math.min(100, 100 - (alert.dte / 45 * 100)))}%`, opacity: 0.7 }}
              />
            </div>
          </div>
        </div>

        {/* Copilot action (like CourseCard forecast) */}
        {alert.level !== 'SAFE' && (
          <div className="px-5 pb-4">
            <p className="text-[12px] text-muted-foreground">
              <span className="font-medium text-foreground">Copilot:</span> {alert.action}
            </p>
          </div>
        )}
        {alert.level === 'SAFE' && (
          <div className="px-5 pb-4">
            <p className="text-[12px] text-emerald-700 dark:text-emerald-400">{alert.action}</p>
          </div>
        )}
      </div>
    </div>
  )
}
