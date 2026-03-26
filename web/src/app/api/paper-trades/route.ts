import { NextResponse } from 'next/server'
import { getSupabase } from '@/lib/supabase'

export const dynamic = 'force-dynamic'

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
    const { data: allTrades } = await sb.from('paper_trades').select('*').order('recommended_at', { ascending: false })
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

    const stats = {
      total: trades.length,
      scored: scored.length,
      winners: winners.length,
      losers: losers.length,
      win_rate: scored.length > 0 ? Math.round(winners.length / scored.length * 1000) / 10 : 0,
      avg_pnl: scored.length > 0 ? Math.round(totalPnl / scored.length * 100) / 100 : 0,
      total_pnl: Math.round(totalPnl * 100) / 100,
      since: trades.length > 0 ? trades[trades.length - 1].recommended_at : null,
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
