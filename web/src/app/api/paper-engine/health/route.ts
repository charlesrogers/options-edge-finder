import { NextResponse } from 'next/server'
import { getSupabase } from '@/lib/supabase'
import { computeFreshness } from '@/lib/freshness'
import { isMarketOpen } from '@/lib/market-calendar'

export const dynamic = 'force-dynamic'

/*
 * The paper engine's health surface.
 *
 * THIS ROUTE REPORTS. IT NEVER ALERTS.
 *
 * That separation is not stylistic. A health endpoint that alerted turned every
 * poller into an alerter, and one stale heartbeat produced an alert per minute
 * for hours (tasks/lessons.md 2026-08-19). Alerting lives exclusively in the
 * scheduled engine runs, deduped on state change. If you are ever tempted to
 * post to Discord from here, the answer is no.
 *
 * It also inherits the app's default-deny auth gate: /paper-engine and this
 * route are deliberately absent from PUBLIC_EXACT and PUBLIC_PREFIXES in
 * proxy.ts. Arm-level P&L at Dad's size is effectively a holdings disclosure.
 *
 * Every threshold rendered by the page is SERVED FROM HERE, read out of the
 * engine's own rows and out of the committed thresholds — never re-declared in
 * TypeScript. A TS mirror of a Python truth is production drift by definition
 * (tasks/lessons.md 2026-08-18, strategies.ts).
 */

type Row = Record<string, unknown>

const ARMS = ['A', 'B', 'C', 'D'] as const

function num(v: unknown): number | null {
  if (v === null || v === undefined) return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

/*
 * Retention, with both halves attached. A ratio whose numerator can go negative
 * does not behave like a percentage, and reporting the percentage alone inverts
 * the reader's intuition (tasks/lessons.md 2026-08-16).
 */
function retention(keptUsd: number, collectedUsd: number) {
  if (collectedUsd === 0) {
    return {
      pct: null,
      keptUsd,
      collectedUsd,
      numeratorNegative: keptUsd < 0,
      note: 'no premium collected — retention is undefined, not 0%',
    }
  }
  return {
    pct: Math.round((keptUsd / collectedUsd) * 1000) / 10,
    keptUsd: Math.round(keptUsd * 100) / 100,
    collectedUsd: Math.round(collectedUsd * 100) / 100,
    numeratorNegative: keptUsd < 0,
  }
}

function summarise(trades: Row[]) {
  const collected = trades.reduce(
    (a, t) => a + (num(t.premium_per_share) ?? 0) * 100 * (num(t.contracts) ?? 0),
    0
  )
  const net = trades.reduce((a, t) => a + (num(t.net_pnl) ?? 0), 0)
  const gross = trades.reduce((a, t) => a + (num(t.gross_pnl) ?? 0), 0)
  const pnls = trades.map((t) => num(t.net_pnl) ?? 0)
  return {
    cycles: trades.length,
    netPnl: Math.round(net * 100) / 100,
    grossPnl: Math.round(gross * 100) / 100,
    commissions:
      Math.round(trades.reduce((a, t) => a + (num(t.commissions_total) ?? 0), 0) * 100) / 100,
    spreadCost:
      Math.round(trades.reduce((a, t) => a + (num(t.spread_cost_total) ?? 0), 0) * 100) / 100,
    retention: retention(net, collected),
    worstCycle: pnls.length ? Math.round(Math.min(...pnls) * 100) / 100 : null,
    // Modelled, always. A paper position cannot actually be assigned.
    modeledAssignments: trades.filter((t) => t.assigned === true).length,
  }
}

export async function GET() {
  const generatedAt = new Date().toISOString()
  try {
    const sb = getSupabase()

    const [hb, trades, quotes, evals, events, killEvents] = await Promise.all([
      sb
        .from('monitor_heartbeats')
        .select('ran_at, ok, detail, engine_version')
        .eq('role', 'paper-engine')
        .order('ran_at', { ascending: false })
        .limit(20),
      sb
        .from('paper_engine_trades')
        .select(
          'arm, ticker, cycle_seq, status, contract_symbol, strike, expiry, contracts,' +
            'entry_decision_ts, entry_decision_bid, entry_decision_ask,' +
            'entry_fill_ts, entry_fill_bid, entry_fill_ask, entry_fill_price,' +
            'entry_spread, entry_latency_min, entry_overnight_gap, entry_quote_stale, entry_commission,' +
            'exit_decision_ts, exit_decision_bid, exit_decision_ask,' +
            'exit_fill_ts, exit_fill_bid, exit_fill_ask, exit_fill_price,' +
            'exit_spread, exit_latency_min, exit_overnight_gap, exit_quote_stale, exit_commission,' +
            'exit_kind, exit_clause, exit_verdict, exit_priced_from,' +
            'premium_per_share, buyback_per_share, gross_pnl, commissions_total,' +
            'spread_cost_total, net_pnl, real_fill, assigned, assignment_type,' +
            'assignment_modeled, assignment_inputs, engine_commit_sha, closed_at, opened_at'
        )
        .order('opened_at', { ascending: false })
        .limit(2000),
      sb
        .from('paper_engine_quotes')
        .select('ticker, trading_day, bid_usable, ask_usable, stale, source_status')
        .order('tick_ts', { ascending: false })
        .limit(5000),
      sb
        .from('paper_engine_entry_evals')
        .select('ticker, trading_day, chain_status, liquidity_ok, liquidity_reason, iv_rank, iv_threshold, arm_results')
        .order('trading_day', { ascending: false })
        .limit(500),
      sb
        .from('paper_engine_events')
        .select('event_ts, kind, severity, arm, ticker, cycle_seq, payload')
        .order('event_ts', { ascending: false })
        .limit(300),
      // Kill-switch state is queried DIRECTLY, never filtered out of the
      // shared event feed: kill transitions are rare by design, so a few busy
      // weeks of fill events would evict them from a limit(300) window and the
      // board would render "no kill-switch state" while a kill is TRIGGERED —
      // the opposite of the truth, on the one surface built to show it
      // (correctness review, 2026-08-21; same mechanism as
      // killswitch.last_states() on the Python side).
      sb
        .from('paper_engine_events')
        .select('event_ts, payload')
        .eq('kind', 'kill_state_change')
        .order('event_ts', { ascending: false })
        .limit(500),
    ])

    for (const r of [hb, trades, quotes, evals, events, killEvents]) {
      if (r.error) throw new Error(r.error.message)
    }

    // Cast through `unknown`: PostgREST's generated row types do not overlap
    // with an index-signature record, and these tables have no generated types
    // at all yet. The shape is asserted by the engine's own schema contract
    // check, which runs against the live database before every tick.
    const heartbeats = (hb.data ?? []) as unknown as Row[]
    const allTrades = (trades.data ?? []) as unknown as Row[]
    const allQuotes = (quotes.data ?? []) as unknown as Row[]
    const allEvals = (evals.data ?? []) as unknown as Row[]
    const allEvents = (events.data ?? []) as unknown as Row[]

    const marketOpen = isMarketOpen(new Date())
    const freshness = computeFreshness(
      heartbeats.map((h) => (h.ran_at as string) ?? null),
      new Date(),
      marketOpen
    )

    // ---------------------------------------------------------- band 1 -----
    const latest = heartbeats[0]
    const detail = (latest?.detail ?? {}) as Record<string, unknown>
    const tally = (detail.tally ?? {}) as Record<string, unknown>

    const byTicker: Record<string, { captured: number; usable: number; stale: number }> = {}
    for (const q of allQuotes) {
      const t = String(q.ticker)
      byTicker[t] ??= { captured: 0, usable: 0, stale: 0 }
      byTicker[t].captured += 1
      if ((q.bid_usable || q.ask_usable) && !q.stale) byTicker[t].usable += 1
      if (q.stale) byTicker[t].stale += 1
    }

    // Every rung of the ladder, with its lifetime fire count per arm. A clause
    // at zero across hundreds of observations is presumed unwired, not unlucky
    // (tasks/lessons.md 2026-08-16) — so zeros are RENDERED, not filtered out.
    const clauseFires: Record<string, Record<string, number>> = {}
    for (const t of allTrades) {
      const clause = t.exit_clause ? String(t.exit_clause) : null
      if (!clause) continue
      clauseFires[clause] ??= {}
      const arm = String(t.arm)
      clauseFires[clause][arm] = (clauseFires[clause][arm] ?? 0) + 1
    }
    const liveClauseCounts = (tally.clause_fires ?? {}) as Record<string, number>

    const integrity = {
      heartbeat: {
        ...freshness,
        lastOk: latest ? latest.ok === true : null,
        engineVersion: latest?.engine_version ?? null,
        engineCommitSha: (detail.engine_commit_sha as string) ?? null,
        marketClosedLastRun: detail.market_closed === true,
      },
      quoteCoverage: Object.fromEntries(
        Object.entries(byTicker).map(([t, c]) => [
          t,
          {
            captured: c.captured,
            usable: c.usable,
            stale: c.stale,
            pct: c.captured ? Math.round((c.usable / c.captured) * 1000) / 10 : null,
          },
        ])
      ),
      lastRunTally: tally,
      // The premium-captured trap: assess_position defaults
      // premium_captured_pct to 0 on a missing ask, which silently disables
      // TP-75 and TP-50. The forward-time twin of the DTE bug, so it has a
      // counter of its own rather than living inside a coverage percentage.
      assessedWithoutAsk: tally.assessed_without_ask ?? null,
      proxyFailures: tally.proxy_failures ?? null,
      emptyChains: tally.empty_chains ?? null,
      writes: detail.writes ?? null,
      clauseFires,
      liveClauseCounts,
      recentHeartbeats: heartbeats.slice(0, 10).map((h) => ({
        ranAt: h.ran_at,
        ok: h.ok,
      })),
    }

    // ---------------------------------------------------------- band 2 -----
    const closed = allTrades.filter((t) => t.status === 'closed')
    const strategy: Record<string, unknown> = {}
    for (const arm of ARMS) {
      const armTrades = closed.filter((t) => t.arm === arm)
      const tickers = [...new Set(armTrades.map((t) => String(t.ticker)))]
      strategy[arm] = {
        all: summarise(armTrades),
        // Reported twice, always. If the two disagree in sign, the real-fill
        // number is the result (tasks/lessons.md 2026-08-17, verbatim).
        realFill: summarise(armTrades.filter((t) => t.real_fill === true)),
        perTicker: Object.fromEntries(
          tickers.map((tk) => [
            tk,
            {
              all: summarise(armTrades.filter((t) => t.ticker === tk)),
              realFill: summarise(
                armTrades.filter((t) => t.ticker === tk && t.real_fill === true)
              ),
            },
          ])
        ),
      }
    }

    // Paired differences, matched on the SHARED ENTRY — (ticker, contract,
    // entry decision time) — which is identical across arms by construction.
    // cycle_seq is allocated per (arm, ticker) and desynchronizes as soon as
    // arms exit at different times (A TP-exits and re-enters while B holds),
    // so pairing on it would compare unrelated cycles from different market
    // paths exactly when the arms start behaving differently — the one moment
    // the pairing exists to measure (correctness review, 2026-08-21).
    function paired(a: string, b: string) {
      const key = (t: Row) => `${t.ticker}#${t.contract_symbol}#${t.entry_decision_ts}`
      const am = new Map(closed.filter((t) => t.arm === a).map((t) => [key(t), t]))
      const bm = new Map(closed.filter((t) => t.arm === b).map((t) => [key(t), t]))
      const deltas: { ticker: string; cycle: number; delta: number }[] = []
      for (const [k, at] of am) {
        const bt = bm.get(k)
        if (!bt) continue
        deltas.push({
          ticker: String(at.ticker),
          cycle: Number(at.cycle_seq),
          delta: (num(at.net_pnl) ?? 0) - (num(bt.net_pnl) ?? 0),
        })
      }
      const vals = deltas.map((d) => d.delta)
      const mean = vals.length ? vals.reduce((x, y) => x + y, 0) / vals.length : null
      return {
        n: vals.length,
        meanDelta: mean === null ? null : Math.round(mean * 100) / 100,
        perTicker: Object.fromEntries(
          [...new Set(deltas.map((d) => d.ticker))].map((tk) => {
            const v = deltas.filter((d) => d.ticker === tk).map((d) => d.delta)
            return [
              tk,
              {
                n: v.length,
                meanDelta:
                  Math.round((v.reduce((x, y) => x + y, 0) / v.length) * 100) / 100,
              },
            ]
          })
        ),
        // Never report A-B without both arms' assignment counts. Being called
        // away is the tax event the copilot exists to prevent and option-leg
        // P&L cannot see it.
        assignments: {
          [a]: closed.filter((t) => t.arm === a && t.assigned === true).length,
          [b]: closed.filter((t) => t.arm === b && t.assigned === true).length,
        },
      }
    }

    // ---------------------------------------------------------- band 3 -----
    const killChanges = (killEvents.data ?? []) as unknown as Row[]
    const currentKills: Record<string, unknown> = {}
    for (const e of killChanges) {
      const p = (e.payload ?? {}) as Record<string, unknown>
      const k = String(p.key ?? '')
      if (k && !(k in currentKills)) {
        currentKills[k] = { ...p, at: e.event_ts }
      }
    }

    return NextResponse.json(
      {
        generatedAt,
        reportOnly: true,
        integrity,
        strategy,
        paired: { AminusB: paired('A', 'B'), AminusD: paired('A', 'D') },
        entryEvals: allEvals.slice(0, 200),
        ledger: allTrades.slice(0, 500),
        events: allEvents.slice(0, 100),
        kills: currentKills,
      },
      { headers: { 'Cache-Control': 'no-store' } }
    )
  } catch (e) {
    /*
     * 503 with the reason, never an empty dashboard. "The engine has done
     * nothing" and "we cannot read the engine's tables" must never render as
     * the same screen — that equivalence is the entire failure this page exists
     * to make impossible.
     */
    return NextResponse.json(
      {
        generatedAt,
        error: `paper engine tables unreadable: ${e instanceof Error ? e.message : String(e)}`,
      },
      { status: 503, headers: { 'Cache-Control': 'no-store' } }
    )
  }
}
