import { NextResponse } from 'next/server'
import { getSupabase } from '@/lib/supabase'

export async function GET() {
  const sb = getSupabase()
  if (!sb) {
    return NextResponse.json({ total: 0, scored: 0, winners: 0, losers: 0, win_rate: 0, avg_pnl: 0, total_pnl: 0, recent: [] })
  }

  try {
    // Get aggregate stats
    const { data: scored } = await sb.from('paper_trades').select('*').eq('scored', true)
    const { count: total } = await sb.from('paper_trades').select('id', { count: 'exact' })

    const scoredTrades = scored ?? []
    const winners = scoredTrades.filter(t => (t.pnl_pct ?? 0) > 0)
    const totalPnl = scoredTrades.reduce((s, t) => s + (t.pnl_pct ?? 0), 0)

    // Get recent paper trades (last 10)
    const { data: recent } = await sb
      .from('paper_trades')
      .select('*')
      .order('recommended_at', { ascending: false })
      .limit(10)

    return NextResponse.json({
      total: total ?? 0,
      scored: scoredTrades.length,
      winners: winners.length,
      losers: scoredTrades.length - winners.length,
      win_rate: scoredTrades.length > 0 ? Math.round(winners.length / scoredTrades.length * 1000) / 10 : 0,
      avg_pnl: scoredTrades.length > 0 ? Math.round(totalPnl / scoredTrades.length * 100) / 100 : 0,
      total_pnl: Math.round(totalPnl * 100) / 100,
      recent: recent ?? [],
    })
  } catch {
    return NextResponse.json({ total: 0, scored: 0, winners: 0, losers: 0, win_rate: 0, avg_pnl: 0, total_pnl: 0, recent: [] })
  }
}
