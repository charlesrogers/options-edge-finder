import { NextResponse } from 'next/server'
import { getSupabase } from '@/lib/supabase'
import { assessPosition } from '@/lib/copilot'
import { parseTradeRow, tradeLabel, TradeRowError } from '@/lib/trade-row'
import { getStockPrice, getStockInfo, getOptionChain } from '@/lib/yf-proxy'

export const dynamic = 'force-dynamic'
export const maxDuration = 60

const CRON_SECRET = process.env.CRON_SECRET ?? ''
const PUSHOVER_TOKEN = process.env.PUSHOVER_TOKEN ?? ''
const PUSHOVER_USER = process.env.PUSHOVER_USER ?? ''

/**
 * Returns true only on confirmed delivery. Callers must treat false as a run
 * failure: an EMERGENCY that Pushover did not accept is an outage, not a detail.
 * This used to `return` silently when the credentials were unset — and they ARE
 * unset in this app's Coolify env, so every alert this route "sent" from the
 * server went nowhere while the route reported success.
 */
async function sendPushover(title: string, message: string, priority: number, sound: string): Promise<boolean> {
  if (!PUSHOVER_TOKEN || !PUSHOVER_USER) {
    console.error(`[monitor] PUSHOVER creds unset — "${title}" NOT DELIVERED`)
    return false
  }

  const body: Record<string, string | number> = {
    token: PUSHOVER_TOKEN, user: PUSHOVER_USER,
    title, message, priority, sound,
  }
  if (priority === 2) { body.retry = 30; body.expire = 300 }

  try {
    const resp = await fetch('https://api.pushover.net/1/messages.json', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams(Object.fromEntries(Object.entries(body).map(([k, v]) => [k, String(v)]))),
    })
    if (!resp.ok) {
      console.error(`[monitor] Pushover ${resp.status} — "${title}" NOT DELIVERED`)
      return false
    }
    return true
  } catch (e) {
    console.error(`[monitor] Pushover threw — "${title}" NOT DELIVERED: ${e}`)
    return false
  }
}

export async function GET(request: Request) {
  // Auth check. Never open-fail: an unset CRON_SECRET used to disable auth
  // entirely and expose this endpoint publicly.
  if (!CRON_SECRET) {
    return NextResponse.json({ error: 'CRON_SECRET unset — refusing to serve' }, { status: 500 })
  }
  const url = new URL(request.url)
  const secret = url.searchParams.get('secret') || request.headers.get('authorization')?.replace('Bearer ', '')
  if (secret !== CRON_SECRET) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  }

  let sb
  try { sb = getSupabase() } catch {
    return NextResponse.json({ error: 'no db' }, { status: 500 })
  }

  // Get open trades. A read failure must never render as "no open trades" —
  // that is an all-clear produced by a broken monitor.
  const { data: trades, error: tradesError } = await sb.from('trades').select('*').eq('status', 'open')
  if (tradesError) {
    return NextResponse.json(
      { error: `trades read failed: ${tradesError.message}`, alerts: 0 },
      { status: 500 },
    )
  }
  if (!trades?.length) {
    return NextResponse.json({ message: 'no open trades', alerts: 0 })
  }

  const alerts: { ticker: string; level: string; reason: string }[] = []
  // Alerts Pushover did not confirm. An undelivered EMERGENCY is an outage.
  const undelivered: string[] = []
  // Positions we could not evaluate. Their level is UNKNOWN, never SAFE.
  const unassessed: string[] = []

  for (const raw of trades) {
    // Field names come from trade-row.ts, the single description of what
    // `public.trades` actually contains. Reading `raw.expiration` inline is what
    // let this route spend months on columns that do not exist, producing
    // dte=NaN and permanently-false DTE rules with no error anywhere.
    let trade
    try {
      trade = parseTradeRow(raw)
    } catch (e) {
      const detail = e instanceof TradeRowError ? e.message : String(e)
      unassessed.push(detail)
      continue
    }
    const label = tradeLabel(trade)
    try {
      const spot = await getStockPrice(trade.ticker)
      if (!spot) {
        unassessed.push(`${label}: no price data`)
        continue
      }

      // Get option price
      let optAsk: number | null = null
      try {
        const chain = await getOptionChain(trade.ticker, trade.expiry)
        const match = chain.calls.find((c: { strike: number }) => c.strike === trade.strike)
        if (match) optAsk = ((match.bid || 0) + (match.ask || 0)) / 2 || match.lastPrice || null
      } catch { /* no chain */ }

      // Get ex-div. A FAILED LOOKUP IS NOT "NO DIVIDEND" — swallowing this error
      // leaves exDivDate null, which silently downgrades EMERGENCY to SAFE.
      let exDivDate: string | null = null
      try {
        const info = await getStockInfo(trade.ticker)
        if (info.exDividendDate) {
          exDivDate = new Date(info.exDividendDate * 1000).toISOString().split('T')[0]
        }
      } catch (e) {
        unassessed.push(`${label}: ex-div lookup failed (${e})`)
        continue
      }

      const alert = assessPosition({
        ticker: trade.ticker,
        strike: trade.strike,
        expiry: trade.expiry,
        soldPrice: trade.sold_price,
        contracts: trade.contracts,
        currentStock: spot,
        currentOptionAsk: optAsk,
        exDivDate: exDivDate,
        earningsDate: null,
      })

      if (alert.level === 'EMERGENCY') {
        if (!await sendPushover(
          `🚨 EMERGENCY: ${trade.ticker} $${trade.strike} Call`,
          `${alert.reason}\n\n${alert.action}`,
          2, 'siren'
        )) undelivered.push(`EMERGENCY ${label}`)
        alerts.push({ ticker: trade.ticker, level: 'EMERGENCY', reason: alert.reason })
      } else if (alert.level === 'CLOSE_NOW') {
        if (!await sendPushover(
          `🔴 CLOSE NOW: ${trade.ticker} $${trade.strike} Call`,
          `${alert.reason}\n\n${alert.action}`,
          1, 'persistent'
        )) undelivered.push(`CLOSE_NOW ${label}`)
        alerts.push({ ticker: trade.ticker, level: 'CLOSE_NOW', reason: alert.reason })
      } else if (alert.level === 'CLOSE_SOON') {
        if (!await sendPushover(
          `🟠 Close Soon: ${trade.ticker} $${trade.strike} Call`,
          `${alert.reason}\n\n${alert.action}`,
          0, 'pushover'
        )) undelivered.push(`CLOSE_SOON ${label}`)
        alerts.push({ ticker: trade.ticker, level: 'CLOSE_SOON', reason: alert.reason })
      }
    } catch (e) {
      unassessed.push(`${label}: ${e}`)
    }
  }

  // A run that could not assess every position — or could not deliver an alert
  // it did produce — is a failed run, not a quiet one.
  if (unassessed.length > 0 || undelivered.length > 0) {
    await sendPushover(
      `⚠️ Monitor DEGRADED — ${unassessed.length} position(s) unchecked`,
      `${unassessed.length} of ${trades.length} positions could not be assessed. ` +
        `Their alert level is UNKNOWN, not safe.\n\n${unassessed.slice(0, 6).map(u => `• ${u}`).join('\n')}`,
      1, 'persistent',
    )
    return NextResponse.json({
      message: `Checked ${trades.length - unassessed.length}/${trades.length} positions`,
      alerts: alerts.length,
      details: alerts,
      unassessed,
      undelivered,
    }, { status: 500 })
  }

  return NextResponse.json({
    message: `Checked ${trades.length} positions`,
    alerts: alerts.length,
    details: alerts,
    unassessed: [],
    undelivered: [],
  })
}
