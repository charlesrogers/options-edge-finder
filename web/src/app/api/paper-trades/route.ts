import { NextResponse } from 'next/server'
import { getSupabase } from '@/lib/supabase'

export const dynamic = 'force-dynamic'

/*
 * backfill_paper_trades.py seeded history by pricing synthetic trades with
 * Black-Scholes off stock history, flagging them strategy_params.backfilled.
 * As of the 2026-08-18 audit (results/013_paper_trade_audit.md) all 444 scored
 * rows are those synthetic trades and ZERO real-price recommendations have ever
 * been scored — so a blended win rate describes bsm_call(), not the strategy.
 * The split is computed here so no caller can accidentally publish the blend.
 */
type TradeRow = Record<string, unknown>

function isBackfilled(t: TradeRow): boolean {
  const raw = t.strategy_params
  if (!raw) return false
  try {
    const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw
    return Boolean((parsed as Record<string, unknown>)?.backfilled)
  } catch {
    return false
  }
}

function summarize(rows: TradeRow[]) {
  const scored = rows.filter((t) => t.scored)
  const winners = scored.filter((t) => ((t.pnl_pct as number) ?? 0) > 0)
  const totalPnl = scored.reduce((s, t) => s + ((t.pnl_pct as number) ?? 0), 0)
  return {
    total: rows.length,
    scored: scored.length,
    winners: winners.length,
    losers: scored.length - winners.length,
    // null, not 0 — an unscored set has no win rate, and 0% reads as "it loses".
    win_rate: scored.length > 0 ? Math.round((winners.length / scored.length) * 1000) / 10 : null,
    avg_pnl: scored.length > 0 ? Math.round((totalPnl / scored.length) * 100) / 100 : null,
  }
}

export async function GET(request: Request) {
  let sb
  try {
    sb = getSupabase()
  } catch {
    return NextResponse.json({ stats: { total: 0, scored: 0, winners: 0, losers: 0, win_rate: 0, avg_pnl: 0 }, trades: [] })
  }

  const url = new URL(request.url)
  const detail = url.searchParams.get('detail') === 'true'

  try {
    // Always get all scored trades for stats
    const { data: allTrades, error } = await sb.from('paper_trades').select('*').order('recommended_at', { ascending: false })
    // Never report an empty-but-healthy scorecard when the DB rejected the read —
    // this route returned all-zeros with HTTP 200 through a 4-month auth outage.
    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 })
    }
    const trades = allTrades ?? []

    const scored = trades.filter(t => t.scored)
    const winners = scored.filter(t => (t.pnl_pct ?? 0) > 0)
    const losers = scored.filter(t => (t.pnl_pct ?? 0) <= 0)
    const totalPnl = scored.reduce((s, t) => s + (t.pnl_pct ?? 0), 0)

    // Per-ticker breakdown
    const tickers = [...new Set(trades.map(t => t.ticker))]
    const byTicker = tickers.map(ticker => {
      const tickerTrades = trades.filter(t => t.ticker === ticker)
      const tickerScored = tickerTrades.filter(t => t.scored)
      const tickerWins = tickerScored.filter(t => (t.pnl_pct ?? 0) > 0)
      return {
        ticker,
        tier: tickerTrades[0]?.tier ?? 'untested',
        total: tickerTrades.length,
        scored: tickerScored.length,
        winners: tickerWins.length,
        losers: tickerScored.length - tickerWins.length,
        win_rate: tickerScored.length > 0 ? Math.round(tickerWins.length / tickerScored.length * 1000) / 10 : 0,
        avg_pnl: tickerScored.length > 0 ? Math.round(tickerScored.reduce((s, t) => s + (t.pnl_pct ?? 0), 0) / tickerScored.length * 100) / 100 : 0,
      }
    }).sort((a, b) => b.avg_pnl - a.avg_pnl)

    // Provenance split — the scorecard renders these, never the blend.
    const syntheticRows = trades.filter(isBackfilled)
    const liveRows = trades.filter((t) => !isBackfilled(t))
    const pendingLive = liveRows
      .filter((t) => !t.scored && t.expiration)
      .map((t) => t.expiration as string)
      .sort()

    const stats = {
      total: trades.length,
      scored: scored.length,
      winners: winners.length,
      losers: losers.length,
      win_rate: scored.length > 0 ? Math.round(winners.length / scored.length * 1000) / 10 : 0,
      avg_pnl: scored.length > 0 ? Math.round(totalPnl / scored.length * 100) / 100 : 0,
      total_pnl: Math.round(totalPnl * 100) / 100,
      since: trades.length > 0 ? trades[trades.length - 1].recommended_at : null,
      provenance: {
        synthetic: summarize(syntheticRows),
        live: summarize(liveRows),
        /** Earliest expiry among unscored real-price rows — when a real record can first exist. */
        first_live_outcome_due: pendingLive[0] ?? null,
      },
    }

    if (detail) {
      return NextResponse.json({ stats, byTicker, trades })
    }

    // Backward compat: return flat stats + recent for the scorecard
    return NextResponse.json({
      ...stats,
      recent: trades.slice(0, 10),
    })
  } catch {
    return NextResponse.json({ stats: { total: 0, scored: 0, winners: 0, losers: 0, win_rate: 0, avg_pnl: 0 }, trades: [] })
  }
}
