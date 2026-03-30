import { NextResponse } from 'next/server'
import { getSupabase } from '@/lib/supabase'
import { assessPosition } from '@/lib/copilot'
import { getStockPrice, getStockInfo, getOptionChain } from '@/lib/yf-proxy'

export const dynamic = 'force-dynamic'
export const maxDuration = 60

const CRON_SECRET = process.env.CRON_SECRET ?? ''
const PUSHOVER_TOKEN = process.env.PUSHOVER_TOKEN ?? ''
const PUSHOVER_USER = process.env.PUSHOVER_USER ?? ''

async function sendPushover(title: string, message: string, priority: number, sound: string) {
  if (!PUSHOVER_TOKEN || !PUSHOVER_USER) return

  const body: Record<string, string | number> = {
    token: PUSHOVER_TOKEN, user: PUSHOVER_USER,
    title, message, priority, sound,
  }
  if (priority === 2) { body.retry = 30; body.expire = 300 }

  await fetch('https://api.pushover.net/1/messages.json', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams(Object.fromEntries(Object.entries(body).map(([k, v]) => [k, String(v)]))),
  })
}

export async function GET(request: Request) {
  // Auth check
  const url = new URL(request.url)
  const secret = url.searchParams.get('secret') || request.headers.get('authorization')?.replace('Bearer ', '')
  if (CRON_SECRET && secret !== CRON_SECRET) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  }

  let sb
  try { sb = getSupabase() } catch {
    return NextResponse.json({ error: 'no db' }, { status: 500 })
  }

  // Get open trades
  const { data: trades } = await sb.from('trades').select('*').eq('status', 'open')
  if (!trades?.length) {
    return NextResponse.json({ message: 'no open trades', alerts: 0 })
  }

  const alerts: { ticker: string; level: string; reason: string }[] = []

  for (const trade of trades) {
    try {
      const spot = await getStockPrice(trade.ticker)
      if (!spot) continue

      // Get option price
      let optAsk: number | null = null
      try {
        const chain = await getOptionChain(trade.ticker, trade.expiration)
        const match = chain.calls.find((c: { strike: number }) => c.strike === trade.strike)
        if (match) optAsk = ((match.bid || 0) + (match.ask || 0)) / 2 || match.lastPrice || null
      } catch { /* no chain */ }

      // Get ex-div
      let exDivDate: string | null = null
      try {
        const info = await getStockInfo(trade.ticker)
        if (info.exDividendDate) {
          exDivDate = new Date(info.exDividendDate * 1000).toISOString().split('T')[0]
        }
      } catch { /* no info */ }

      const alert = assessPosition({
        ticker: trade.ticker,
        strike: trade.strike,
        expiry: trade.expiration,
        soldPrice: trade.premium_received,
        contracts: trade.contracts,
        currentStock: spot,
        currentOptionAsk: optAsk,
        exDivDate: exDivDate,
        earningsDate: null,
      })

      if (alert.level === 'EMERGENCY') {
        await sendPushover(
          `🚨 EMERGENCY: ${trade.ticker} $${trade.strike} Call`,
          `${alert.reason}\n\n${alert.action}`,
          2, 'siren'
        )
        alerts.push({ ticker: trade.ticker, level: 'EMERGENCY', reason: alert.reason })
      } else if (alert.level === 'CLOSE_NOW') {
        await sendPushover(
          `🔴 CLOSE NOW: ${trade.ticker} $${trade.strike} Call`,
          `${alert.reason}\n\n${alert.action}`,
          1, 'persistent'
        )
        alerts.push({ ticker: trade.ticker, level: 'CLOSE_NOW', reason: alert.reason })
      } else if (alert.level === 'CLOSE_SOON') {
        await sendPushover(
          `🟠 Close Soon: ${trade.ticker} $${trade.strike} Call`,
          `${alert.reason}\n\n${alert.action}`,
          0, 'pushover'
        )
        alerts.push({ ticker: trade.ticker, level: 'CLOSE_SOON', reason: alert.reason })
      }
    } catch { /* skip failed ticker */ }
  }

  return NextResponse.json({
    message: `Checked ${trades.length} positions`,
    alerts: alerts.length,
    details: alerts,
  })
}
