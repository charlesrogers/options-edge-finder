import { NextResponse } from 'next/server'
import { getSupabase } from '@/lib/supabase'
import {
  assertPublicSafe,
  cached,
  summarizeGraveyard,
  type GraveyardRow,
} from '@/lib/live-evidence'

export const dynamic = 'force-dynamic'

/*
 * The scorecard behind "most of what we tested did not work".
 *
 * Read live on purpose: the claim is only worth anything if the reader can
 * check it against the table rather than against a number someone typed into a
 * component — which is the failure this whole page is a response to. Every row
 * here is already in the public repo (register_hypotheses.py,
 * register_h21_h24.py, results/*.md), so the response is safe whether the app
 * gates it or not; like /api/status it carries no gate of its own and inherits
 * the page's.
 *
 * `failure_reason` and `hypothesis` are NOT selected. They are paragraphs, the
 * page renders a scorecard, and the smaller the response the less there is to
 * go stale in a cache.
 */
export async function GET() {
  try {
    const payload = await cached('graveyard', async () => {
      const sb = getSupabase()
      const { data, error } = await sb
        .from('signal_graveyard')
        .select('signal_id, name, tier, status, layer_reached, tested_date')
      if (error) throw new Error(error.message)
      return { generatedAt: new Date().toISOString(), ...summarizeGraveyard((data ?? []) as GraveyardRow[]) }
    })
    // Checked on the way out, on every request including cache hits.
    assertPublicSafe(payload)
    return NextResponse.json(payload, { headers: { 'Cache-Control': 'no-store' } })
  } catch (e) {
    // 503, not an empty scorecard. "0 failures" and "could not read the table"
    // must never render as the same thing on a page about honest reporting.
    return NextResponse.json(
      {
        generatedAt: new Date().toISOString(),
        error: `signal_graveyard unreadable: ${e instanceof Error ? e.message : String(e)}`,
      },
      { status: 503, headers: { 'Cache-Control': 'no-store' } }
    )
  }
}
