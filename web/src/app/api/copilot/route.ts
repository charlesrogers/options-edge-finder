import { supabase } from '@/lib/supabase'
import { isMarketOpen } from '@/lib/market-calendar'
import { computeFreshness, STALE_MINUTES } from '@/lib/freshness'

export const dynamic = 'force-dynamic'

/*
 * This route READS the verdicts the monitor stored. It does not compute any.
 *
 * It used to call assessPosition() from lib/copilot.ts — a TypeScript
 * reimplementation of position_monitor.py's alert rules — against prices it
 * fetched itself. That made two engines for one question: the phone alerted
 * from the Python, the screen rendered the TypeScript, and nothing forced them
 * to agree. A SAFE on the screen while the phone said CLOSE_NOW would have
 * looked like a working system.
 *
 * monitor_positions.py now persists every verdict to `position_assessments`
 * with the inputs it was computed from. One engine, one verdict.
 *
 * Two rules follow, and they are the whole point of the change:
 *   1. No re-derivation fallback. If the monitor has not assessed a position,
 *      this returns it WITHOUT a verdict rather than inventing one. Stale and
 *      honest beats fresh and divergent.
 *   2. Age travels with the verdict, so the UI can say how old it is and shout
 *      when it is too old to act on.
 *
 * The only arithmetic here is presentation over stored numbers (buyback cost
 * from the stored option ask, P&L against the trade's sold price). None of it
 * can change a level, a reason, or an action.
 */

interface AssessmentRow {
  trade_id: string | null
  ticker: string
  strike: number
  expiry: string
  contracts: number
  level: string
  reason: string | null
  action: string | null
  inputs: Record<string, unknown> | null
  assessed_at: string
  engine: string
  engine_version: string | null
  source: string
}

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

export async function GET() {
  const { data: trades, error } = await supabase
    .from('trades')
    .select('*')
    .eq('status', 'open')

  if (error) {
    return Response.json({ error: error.message }, { status: 500 })
  }

  const openTrades = trades ?? []
  if (openTrades.length === 0) {
    return Response.json({
      alerts: [],
      freshness: { latestAssessedAt: null, ageMinutes: null, stale: false, marketOpen: isMarketOpen(), staleThresholdMinutes: STALE_MINUTES },
    })
  }

  const tradeIds = openTrades.map((t) => t.id)

  // Newest first, then keep the first row seen per trade — one query, no N+1.
  const { data: rows, error: aErr } = await supabase
    .from('position_assessments')
    .select('*')
    .in('trade_id', tradeIds)
    .order('assessed_at', { ascending: false })

  if (aErr) {
    // A failed read is NOT an empty scorecard. Returning [] here would render
    // "all positions safe" out of a database error — the exact shape of the
    // outage this project already had once.
    return Response.json({ error: `assessment read failed: ${aErr.message}` }, { status: 500 })
  }

  const latest = new Map<string, AssessmentRow>()
  for (const r of (rows ?? []) as AssessmentRow[]) {
    if (r.trade_id && !latest.has(r.trade_id)) latest.set(r.trade_id, r)
  }

  const now = Date.now()
  const alerts = openTrades.map((trade) => {
    const a = latest.get(trade.id)

    if (!a) {
      // Never fabricate. The UI renders this as "not yet assessed".
      return {
        tradeId: trade.id,
        ticker: trade.ticker,
        strike: trade.strike,
        contracts: trade.contracts,
        expiry: trade.expiry,
        level: 'UNASSESSED' as const,
        reason: 'The monitor has not stored a verdict for this position yet.',
        action: 'Check the position monitor before acting on this row.',
        assessedAt: null,
        ageMinutes: null,
        dte: null,
        pctFromStrike: null,
        buybackCost: null,
        netPnl: null,
        premiumCapturedPct: null,
        daysToExDiv: null,
        daysToEarnings: null,
        engine: null,
        engineVersion: null,
        source: null,
      }
    }

    const inputs = a.inputs ?? {}
    const optionAsk = num(inputs.option_ask)
    const soldPrice = num(trade.sold_price)
    const contracts = a.contracts ?? trade.contracts ?? 1

    // Presentation arithmetic over stored values only.
    const buybackCost = optionAsk !== null ? optionAsk * 100 * contracts : null
    const netPnl =
      optionAsk !== null && soldPrice !== null
        ? (soldPrice - optionAsk) * 100 * contracts
        : null
    const premiumCapturedPct =
      optionAsk !== null && soldPrice !== null && soldPrice > 0
        ? ((soldPrice - optionAsk) / soldPrice) * 100
        : null

    const assessedAt = a.assessed_at
    const ageMinutes = Math.round((now - new Date(assessedAt).getTime()) / 60000)

    const exDiv = typeof inputs.ex_div_date === 'string' ? inputs.ex_div_date : null
    const earnings = typeof inputs.earnings_date === 'string' ? inputs.earnings_date : null
    const daysUntil = (d: string | null) =>
      d ? Math.ceil((new Date(d).getTime() - now) / 86400000) : null

    return {
      tradeId: trade.id,
      ticker: a.ticker,
      strike: a.strike,
      contracts,
      expiry: a.expiry,
      level: a.level,
      reason: a.reason ?? '',
      action: a.action ?? '',
      assessedAt,
      ageMinutes,
      dte: num(inputs.dte),
      pctFromStrike: num(inputs.pct_from_strike),
      buybackCost,
      netPnl,
      premiumCapturedPct,
      daysToExDiv: daysUntil(exDiv),
      daysToEarnings: daysUntil(earnings),
      engine: a.engine,
      engineVersion: a.engine_version,
      source: a.source,
    }
  })

  const levelOrder: Record<string, number> = {
    EMERGENCY: 0,
    CLOSE_NOW: 1,
    CLOSE_SOON: 2,
    WATCH: 3,
    SAFE: 4,
    // Unassessed sorts to the top, not the bottom: a position nobody has looked
    // at is a thing to deal with, not a quiet row at the end of the list.
    UNASSESSED: -1,
  }
  alerts.sort((a, b) => (levelOrder[a.level] ?? 5) - (levelOrder[b.level] ?? 5))

  // Staleness rule lives in lib/freshness.ts so it can be exercised against
  // fixtures — see scripts/check_freshness_fixture.mjs.
  const freshness = computeFreshness(alerts.map((a) => a.assessedAt), new Date(now), isMarketOpen())

  return Response.json({ alerts, freshness })
}
