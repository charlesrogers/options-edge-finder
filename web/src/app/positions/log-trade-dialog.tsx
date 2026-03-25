'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'

const inputClass =
  'mt-1 block h-9 w-full rounded-lg border border-input bg-background px-3 text-[13px] font-medium outline-none transition-all focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 placeholder:text-muted-foreground/50'

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
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mr-1.5">
          <path d="M12 5v14M5 12h14" />
        </svg>
        Log Trade
      </Button>
    )
  }

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
        onClick={() => setOpen(false)}
      />

      {/* Dialog */}
      <div className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]">
        <div className="w-full max-w-lg rounded-xl border bg-card shadow-lg shadow-black/[0.08] overflow-hidden transition-all">
          {/* Header */}
          <div className="px-6 pt-5 pb-4 border-b">
            <h3 className="text-[15px] font-semibold text-foreground">Log a New Trade</h3>
            <p className="text-[12px] text-muted-foreground mt-0.5">
              Enter the details of the covered call you sold.
            </p>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="px-6 py-5">
            <div className="grid grid-cols-2 gap-4">
              <label className="block">
                <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Ticker
                </span>
                <input
                  required
                  autoFocus
                  value={ticker}
                  onChange={(e) => setTicker(e.target.value)}
                  placeholder="AAPL"
                  className={inputClass}
                />
              </label>
              <label className="block">
                <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Strike Price
                </span>
                <input
                  required
                  type="number"
                  step="0.01"
                  value={strike}
                  onChange={(e) => setStrike(e.target.value)}
                  placeholder="260.00"
                  className={inputClass}
                />
              </label>
              <label className="block">
                <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Expiration Date
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
                  Premium Received
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
              <label className="block col-span-2 sm:col-span-1">
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
            </div>

            {/* Actions */}
            <div className="flex items-center justify-end gap-2 mt-6 pt-4 border-t">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="active:translate-y-px"
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                size="sm"
                disabled={submitting}
                className="active:translate-y-px"
              >
                {submitting ? 'Saving...' : 'Save Trade'}
              </Button>
            </div>
          </form>
        </div>
      </div>
    </>
  )
}
