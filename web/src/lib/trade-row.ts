/**
 * The one place that knows what a row of Supabase `public.trades` looks like.
 *
 * Why this file exists (2026-08-18): the alerting paths and the UI path had
 * drifted onto two different sets of column names. `public.trades` is
 *
 *     id, ticker, strike, expiry, sold_price, close_price, contracts,
 *     status, opened_at, closed_at, created_at
 *
 * `api/copilot/route.ts` (the screen) read `expiry`/`sold_price` and was right.
 * `api/cron/monitor/route.ts` (the phone) read `expiration`/`premium_received` —
 * columns this table has never had. TypeScript could not catch it because the
 * Supabase client hands back `any`. The result was `dte = NaN`, which makes every
 * DTE-gated rule evaluate false forever: silent under-alerting, no error anywhere.
 *
 * Rule: a required field that is absent throws. It never defaults.
 */

import type { TradeRow } from '@/lib/supabase'

export type { TradeRow }

export class TradeRowError extends Error {}

const REQUIRED = ['ticker', 'strike', 'expiry', 'sold_price', 'contracts'] as const

export function parseTradeRow(row: Record<string, unknown>): TradeRow {
  if (!row || typeof row !== 'object') {
    throw new TradeRowError(`expected a trades row object, got ${typeof row}`)
  }

  const id = String(row.id ?? '?')
  const missing = REQUIRED.filter(c => row[c] === undefined || row[c] === null)
  if (missing.length > 0) {
    throw new TradeRowError(
      `trades row ${id} is missing required column(s): ${missing.join(', ')}. ` +
        `Present: ${Object.keys(row).sort().join(', ')}. ` +
        'This is a schema mismatch, not an empty position — refusing to assess it.',
    )
  }

  const strike = Number(row.strike)
  const soldPrice = Number(row.sold_price)
  const contracts = Number(row.contracts)
  if (!Number.isFinite(strike) || !Number.isFinite(soldPrice) || !Number.isFinite(contracts)) {
    throw new TradeRowError(
      `trades row ${id} has unusable numerics: strike=${row.strike}, ` +
        `sold_price=${row.sold_price}, contracts=${row.contracts}`,
    )
  }

  const expiry = String(row.expiry).slice(0, 10)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(expiry)) {
    throw new TradeRowError(
      `trades row ${id} has expiry ${JSON.stringify(row.expiry)}, not an ISO YYYY-MM-DD date`,
    )
  }

  return {
    ...(row as unknown as TradeRow),
    id,
    ticker: String(row.ticker).toUpperCase(),
    strike,
    expiry,
    sold_price: soldPrice,
    contracts,
    status: (row.status ?? 'open') as TradeRow['status'],
  }
}

export function tradeLabel(t: TradeRow): string {
  return `${t.ticker} $${t.strike} exp ${t.expiry}`
}
