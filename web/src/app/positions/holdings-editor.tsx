'use client'

import { useEffect, useState, useCallback } from 'react'
import { cn } from '@/lib/utils'
import { TICKER_STRATEGIES, TIER_CONFIG } from '@/lib/strategies'

interface Holding {
  ticker: string
  shares: number
}

const DEFAULT_TICKERS = ['AAPL', 'TMUS', 'KKR', 'DIS', 'TXN', 'GOOGL', 'AMZN']

export function HoldingsEditor() {
  const [holdings, setHoldings] = useState<Holding[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(false)
  const [saving, setSaving] = useState<string | null>(null)

  // New holding form
  const [newTicker, setNewTicker] = useState('')
  const [newShares, setNewShares] = useState('')

  const fetchHoldings = useCallback(async () => {
    try {
      const res = await fetch('/api/holdings')
      if (res.ok) {
        const data = await res.json()
        if (Array.isArray(data)) {
          setHoldings(data.map((h: Record<string, unknown>) => ({ ticker: String(h.ticker), shares: Number(h.shares) || 0 })))
          // Auto-expand if no holdings
          if (data.length === 0) setExpanded(true)
        }
      }
    } catch {
      // Silently fail — holdings are optional
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchHoldings() }, [fetchHoldings])

  async function saveHolding(ticker: string, shares: number) {
    setSaving(ticker)
    try {
      await fetch('/api/holdings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker: ticker.toUpperCase(), shares }),
      })
      await fetchHoldings()
    } finally {
      setSaving(null)
    }
  }

  async function handleAddNew(e: React.FormEvent) {
    e.preventDefault()
    const ticker = newTicker.trim().toUpperCase()
    const shares = parseInt(newShares, 10)
    if (!ticker || isNaN(shares) || shares < 0) return
    await saveHolding(ticker, shares)
    setNewTicker('')
    setNewShares('')
  }

  const hasHoldings = holdings.some(h => h.shares > 0)
  const totalShares = holdings.reduce((s, h) => s + h.shares, 0)

  // Merge defaults with existing holdings
  const allTickers = Array.from(new Set([
    ...holdings.map(h => h.ticker),
    ...DEFAULT_TICKERS,
  ])).sort()

  const holdingsMap = Object.fromEntries(holdings.map(h => [h.ticker, h.shares]))

  return (
    <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
      {/* Header — always visible */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-5 py-4 flex items-center justify-between text-left hover:bg-accent/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <h2 className="text-[14px] font-semibold text-foreground">Stock Holdings</h2>
          {hasHoldings && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold ring-1 ring-inset bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 ring-emerald-600/20">
              {holdings.filter(h => h.shares > 0).length} stocks · {totalShares.toLocaleString()} shares
            </span>
          )}
          {!hasHoldings && !loading && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold ring-1 ring-inset bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 ring-amber-600/20">
              No holdings entered
            </span>
          )}
        </div>
        <svg
          className={cn('w-4 h-4 text-muted-foreground transition-transform', expanded && 'rotate-180')}
          viewBox="0 0 16 16"
          fill="none"
        >
          <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="px-5 pb-5 border-t">
          <p className="text-[12px] text-muted-foreground mt-3 mb-4">
            Enter how many shares you own of each stock. This determines covered call sizing and which tickers get recommendations.
          </p>

          {/* Holdings grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {allTickers.map(ticker => {
              const shares = holdingsMap[ticker] ?? 0
              const strategy = TICKER_STRATEGIES[ticker]
              const tier = strategy?.tier
              const tierConfig = tier ? TIER_CONFIG[tier] : null
              const isSaving = saving === ticker

              return (
                <div key={ticker} className="flex items-center gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 mb-1">
                      <span className="text-[13px] font-semibold text-foreground">{ticker}</span>
                      {tierConfig && (
                        <span className="text-[9px] text-muted-foreground">{tierConfig.icon}</span>
                      )}
                    </div>
                    <input
                      type="number"
                      min="0"
                      step="100"
                      value={shares || ''}
                      placeholder="0"
                      onChange={async (e) => {
                        const val = parseInt(e.target.value, 10) || 0
                        // Optimistic update
                        setHoldings(prev => {
                          const existing = prev.find(h => h.ticker === ticker)
                          if (existing) return prev.map(h => h.ticker === ticker ? { ...h, shares: val } : h)
                          return [...prev, { ticker, shares: val }]
                        })
                      }}
                      onBlur={(e) => {
                        const val = parseInt(e.target.value, 10) || 0
                        saveHolding(ticker, val)
                      }}
                      className={cn(
                        'w-full h-8 rounded-lg border border-input bg-background px-2.5 text-[13px] tabular-nums',
                        'placeholder:text-muted-foreground/50',
                        'focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50',
                        'disabled:opacity-50',
                        isSaving && 'opacity-60',
                      )}
                      disabled={isSaving}
                    />
                  </div>
                </div>
              )
            })}
          </div>

          {/* Add new ticker */}
          <form onSubmit={handleAddNew} className="flex items-end gap-2 mt-4 pt-4 border-t">
            <div className="flex-1">
              <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground mb-1 block">
                Add ticker
              </label>
              <input
                type="text"
                value={newTicker}
                onChange={(e) => setNewTicker(e.target.value.toUpperCase())}
                placeholder="MSFT"
                className="w-full h-8 rounded-lg border border-input bg-background px-2.5 text-[13px] placeholder:text-muted-foreground/50 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              />
            </div>
            <div className="w-24">
              <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground mb-1 block">
                Shares
              </label>
              <input
                type="number"
                min="0"
                step="100"
                value={newShares}
                onChange={(e) => setNewShares(e.target.value)}
                placeholder="100"
                className="w-full h-8 rounded-lg border border-input bg-background px-2.5 text-[13px] tabular-nums placeholder:text-muted-foreground/50 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              />
            </div>
            <button
              type="submit"
              disabled={!newTicker.trim() || !newShares}
              className="h-8 px-3 rounded-lg bg-primary text-primary-foreground text-[13px] font-medium hover:bg-primary/90 transition-colors active:translate-y-px disabled:opacity-50 disabled:pointer-events-none"
            >
              Add
            </button>
          </form>
        </div>
      )}
    </div>
  )
}
