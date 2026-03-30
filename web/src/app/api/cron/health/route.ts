import { NextResponse } from 'next/server'
import { getSupabase } from '@/lib/supabase'

export const dynamic = 'force-dynamic'

const CRON_SECRET = process.env.CRON_SECRET ?? ''
const DISCORD_WEBHOOK = 'https://discord.com/api/webhooks/1486969921542946887/SAD4fP0-JaPrGmnEs_W2WIZmiRMQt1T2kQSbgnNenTTjnRq0YcqNkkLsKdvyPJ5pAA6y'

interface Check {
  name: string
  status: 'ok' | 'warn' | 'fail'
  detail: string
}

async function sendDiscordAlert(checks: Check[]) {
  const failures = checks.filter(c => c.status === 'fail')
  const warnings = checks.filter(c => c.status === 'warn')

  if (failures.length === 0 && warnings.length === 0) return

  const emoji = failures.length > 0 ? '🚨' : '⚠️'
  const title = failures.length > 0
    ? `${emoji} Options Copilot: ${failures.length} system failure(s)`
    : `${emoji} Options Copilot: ${warnings.length} warning(s)`

  const fields = checks
    .filter(c => c.status !== 'ok')
    .map(c => ({
      name: `${c.status === 'fail' ? '❌' : '⚠️'} ${c.name}`,
      value: c.detail,
      inline: false,
    }))

  await fetch(DISCORD_WEBHOOK, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      embeds: [{
        title,
        color: failures.length > 0 ? 0xff0000 : 0xffaa00,
        fields,
        timestamp: new Date().toISOString(),
        footer: { text: 'options.imprevista.com' },
      }],
    }),
  })
}

export async function GET(request: Request) {
  const url = new URL(request.url)
  const secret = url.searchParams.get('secret') || request.headers.get('authorization')?.replace('Bearer ', '')
  if (CRON_SECRET && secret !== CRON_SECRET) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  }

  const checks: Check[] = []

  // 1. Supabase connection
  try {
    const sb = getSupabase()
    const { count } = await sb.from('paper_trades').select('id', { count: 'exact' })
    if (count !== null && count > 0) {
      checks.push({ name: 'Supabase', status: 'ok', detail: `Connected, ${count} paper trades` })
    } else {
      checks.push({ name: 'Supabase', status: 'warn', detail: 'Connected but 0 paper trades' })
    }
  } catch (e) {
    checks.push({ name: 'Supabase', status: 'fail', detail: `Connection failed: ${e}` })
  }

  // 2. Chain capture freshness — last capture should be within 2 days
  try {
    const sb = getSupabase()
    const { data } = await sb.from('option_chain_snapshots').select('date').order('date', { ascending: false }).limit(1)
    if (data?.[0]) {
      const lastDate = new Date(data[0].date)
      const ageHours = (Date.now() - lastDate.getTime()) / (1000 * 60 * 60)
      if (ageHours > 48) {
        checks.push({ name: 'Chain Capture', status: 'fail', detail: `Last capture ${Math.round(ageHours)}h ago (should be <48h). Data collection may be broken.` })
      } else {
        checks.push({ name: 'Chain Capture', status: 'ok', detail: `Last capture ${Math.round(ageHours)}h ago` })
      }
    } else {
      checks.push({ name: 'Chain Capture', status: 'warn', detail: 'No chain data found' })
    }
  } catch {
    checks.push({ name: 'Chain Capture', status: 'warn', detail: 'Could not check chain freshness' })
  }

  // 3. Paper trade logger freshness — should run daily on weekdays
  try {
    const sb = getSupabase()
    const { data } = await sb.from('paper_trades').select('recommended_at').order('recommended_at', { ascending: false }).limit(1)
    if (data?.[0]) {
      const lastDate = new Date(data[0].recommended_at)
      const ageDays = (Date.now() - lastDate.getTime()) / (1000 * 60 * 60 * 24)
      if (ageDays > 3) {
        checks.push({ name: 'Paper Trade Logger', status: 'warn', detail: `Last paper trade ${Math.round(ageDays)} days ago. Logger may not be running.` })
      } else {
        checks.push({ name: 'Paper Trade Logger', status: 'ok', detail: `Last paper trade ${Math.round(ageDays)} day(s) ago` })
      }
    }
  } catch {
    checks.push({ name: 'Paper Trade Logger', status: 'warn', detail: 'Could not check paper trade freshness' })
  }

  // 4. YF Proxy health
  try {
    const resp = await fetch('https://yfinance-proxy.charlesrogers.workers.dev/health', { signal: AbortSignal.timeout(5000) })
    if (resp.ok) {
      checks.push({ name: 'YF Proxy', status: 'ok', detail: 'Cloudflare Worker responding' })
    } else {
      checks.push({ name: 'YF Proxy', status: 'fail', detail: `HTTP ${resp.status}. All market data fetches will fail.` })
    }
  } catch {
    checks.push({ name: 'YF Proxy', status: 'fail', detail: 'YF proxy unreachable. All market data fetches will fail.' })
  }

  // Send Discord alert if any failures/warnings
  try {
    await sendDiscordAlert(checks)
  } catch { /* don't fail health check because Discord is down */ }

  const overallStatus = checks.some(c => c.status === 'fail') ? 'fail'
    : checks.some(c => c.status === 'warn') ? 'warn' : 'ok'

  return NextResponse.json({ status: overallStatus, checks })
}
