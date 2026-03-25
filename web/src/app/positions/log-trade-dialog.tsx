'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'

const inputClass =
  'mt-0.5 block h-8 w-full rounded-lg border border-input bg-background px-2.5 text-[13px] font-medium outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50'

export function LogTradeDialog({ onSuccess }: { onSuccess: () => void }) {
  const [open, setOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const [ticker, setTicker] = useState('')
  const [strike, setStrike] = useState('')
  const [expiry, setExpiry] = useState('')
  const [soldPrice, setSoldPrice] = useState('')
  const [contracts, setContracts] = useState('1')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    try {
      const res = await fetch('/api/positions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ticker: ticker.toUpperCase().trim(),
          strike: parseFloat(strike),
          expiry,
          soldPrice: parseFloat(soldPrice),
          contracts: parseInt(contracts, 10),
        }),
      })
      if (res.ok) {
        setOpen(false)
        setTicker('')
        setStrike('')
        setExpiry('')
        setSoldPrice('')
        setContracts('1')
        onSuccess()
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (!open) {
    return (
      <Button
        size="sm"
        className="active:translate-y-px"
        onClick={() => setOpen(true)}
      >
        Log Trade
      </Button>
    )
  }

  return (
    <div className="rounded-xl border bg-card px-5 pt-4 pb-4 shadow-sm shadow-black/[0.04]">
      <h3 className="mb-3 text-[14px] font-semibold">Log a New Trade</h3>
      <form
        onSubmit={handleSubmit}
        className="grid grid-cols-2 gap-3 sm:grid-cols-5"
      >
        <label className="block">
          <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Ticker
          </span>
          <input
            required
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="AAPL"
            className={inputClass}
          />
        </label>
        <label className="block">
          <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Strike
          </span>
          <input
            required
            type="number"
            step="0.01"
            value={strike}
            onChange={(e) => setStrike(e.target.value)}
            placeholder="260"
            className={inputClass}
          />
        </label>
        <label className="block">
          <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Expiry
          </span>
          <input
            required
            type="date"
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
            className={inputClass}
          />
        </label>
        <label className="block">
          <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Premium
          </span>
          <input
            required
            type="number"
            step="0.01"
            value={soldPrice}
            onChange={(e) => setSoldPrice(e.target.value)}
            placeholder="3.50"
            className={inputClass}
          />
        </label>
        <div className="flex items-end gap-2">
          <label className="block flex-1">
            <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Contracts
            </span>
            <input
              type="number"
              min="1"
              value={contracts}
              onChange={(e) => setContracts(e.target.value)}
              className={inputClass}
            />
          </label>
          <div className="flex gap-1">
            <Button
              type="submit"
              size="sm"
              disabled={submitting}
              className="active:translate-y-px"
            >
              {submitting ? 'Saving...' : 'Save'}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="active:translate-y-px"
              onClick={() => setOpen(false)}
            >
              Cancel
            </Button>
          </div>
        </div>
      </form>
    </div>
  )
}
