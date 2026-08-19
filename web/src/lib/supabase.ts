import { createClient, type SupabaseClient } from '@supabase/supabase-js'

/*
 * The server's database client. Service-role, server-only, no exceptions.
 *
 * This used to be the PUBLIC anon key, injected as NEXT_PUBLIC_* build args and
 * therefore baked into the image and shipped to browsers. With RLS off (verified
 * `relrowsecurity = f` on all six tables on 2026-08-19) that key could INSERT a
 * fake trade, DELETE a real one, and write heartbeats — demonstrated: anon
 * INSERT into `trades` returned 201, anon DELETE returned 204.
 *
 * Two changes close that, and they only work together:
 *   1. RLS is enabled on the six tables with no policies granted to `anon`, so
 *      the public key can do nothing at all (migrations/004_rls_six_tables.sql).
 *   2. Server code authenticates as `service_role`, which has BYPASSRLS on this
 *      instance and so is unaffected.
 *
 * SUPABASE_SERVICE_ROLE_KEY is deliberately NOT prefixed NEXT_PUBLIC_ and is
 * deliberately NOT a Docker build arg — build args are baked into image layers
 * and readable by anyone who pulls the image. It arrives as a Coolify runtime
 * env var and never leaves the server.
 *
 * Nothing in the browser needs Supabase: the only two client components that
 * mention it (`sell-recommendations.tsx`, `trade-history.tsx`) import row TYPES,
 * which are erased at compile time. All data flows through the API routes, which
 * are themselves behind the session middleware.
 */

let _supabase: SupabaseClient | null = null

export function getSupabase(): SupabaseClient {
  /*
   * A hard stop if this ever gets imported into a client component. Without it
   * the failure mode is silent and awful: the key resolves to undefined in the
   * browser, the createClient throw gets swallowed by an error boundary, and the
   * page renders an empty-but-healthy-looking view — the exact shape of the
   * four-month outage this codebase already survived.
   */
  if (typeof window !== 'undefined') {
    throw new Error('getSupabase() is server-only — never import it into a client component')
  }
  if (_supabase) return _supabase

  const url = process.env.SUPABASE_URL
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY
  if (!url || !key) {
    // Fail closed and name the missing variable. A silent fallback to the anon
    // key here would quietly undo the whole point of this change.
    const missing = [
      !url ? 'SUPABASE_URL' : null,
      !key ? 'SUPABASE_SERVICE_ROLE_KEY' : null,
    ].filter(Boolean).join(', ')
    throw new Error(`Missing ${missing} — refusing to start a database client`)
  }

  _supabase = createClient(url, key, {
    // Service-role is a machine identity: no user session to persist, nothing to
    // refresh, and no reason to keep auth state between requests.
    auth: { persistSession: false, autoRefreshToken: false },
  })
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
  id: string                // uuid — gen_random_uuid(), not an integer
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
  id: string                // uuid
  ticker: string
  shares: number
  cost_basis: number | null
  updated_at: string
}
