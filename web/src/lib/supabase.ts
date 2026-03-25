import { createClient, type SupabaseClient } from '@supabase/supabase-js'

let _supabase: SupabaseClient | null = null

export function getSupabase(): SupabaseClient {
  if (_supabase) return _supabase
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL
  const key = process.env.NEXT_PUBLIC_SUPABASE_KEY
  if (!url || !key) {
    throw new Error('Missing NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_KEY')
  }
  _supabase = createClient(url, key)
  return _supabase
}

/** Convenience alias — calls getSupabase() lazily */
export const supabase = new Proxy({} as SupabaseClient, {
  get(_target, prop) {
    return (getSupabase() as unknown as Record<string | symbol, unknown>)[prop]
  },
})

/* ── Row types matching the Supabase tables ── */

export interface TradeRow {
  id: number
  ticker: string
  strike: number
  expiry: string            // YYYY-MM-DD
  sold_price: number        // premium per share
  contracts: number
  opened_at: string         // ISO timestamp
  closed_at: string | null
  close_price: number | null
  status: 'open' | 'closed'
}

export interface HoldingRow {
  id: number
  ticker: string
  shares: number
  cost_basis: number | null
  updated_at: string
}
