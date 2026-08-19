import { NextResponse } from 'next/server'
import { getSupabase } from '@/lib/supabase'
import { calendarRange, isMarketOpen, tradingDaysSince } from '@/lib/market-calendar'
import { timingSafeEqual } from '@/lib/auth'
import { HEARTBEAT_STALE_MINUTES } from '@/lib/live-evidence'

export const dynamic = 'force-dynamic'

const CRON_SECRET = process.env.CRON_SECRET ?? ''
// Webhook URLs are secrets — this repo is public, so it must never be inlined here.

// HEARTBEAT_STALE_MINUTES lives in lib/live-evidence.ts because /api/status and
// the /how-it-works widget publish the same judgement to the reader. A second
// copy here would let the page call a monitor "live" that this endpoint is
// already paging about.

interface Check {
  name: string
  status: 'ok' | 'warn' | 'fail'
  detail: string
}


export async function GET(request: Request) {
  // Never open-fail: `CRON_SECRET && ...` meant an unset env var silently
  // disabled auth and exposed this endpoint publicly.
  if (!CRON_SECRET) {
    return NextResponse.json({ error: 'CRON_SECRET unset — refusing to serve' }, { status: 500 })
  }
  /*
   * Bearer header ONLY. The `?secret=` form used to be accepted here, which put
   * the secret into Traefik access logs, container logs, browser history and the
   * Referer of any outbound link — a credential that leaks by being used. No
   * consumer used it (verified across the GitHub workflows, the Hetzner cron
   * scripts, the Uptime Kuma monitor and the Cloudflare worker: all send the
   * header), so removing it costs nothing.
   *
   * Constant-time compare, so the secret cannot be recovered a byte at a time.
   */
  const secret = request.headers.get('authorization')?.replace('Bearer ', '') ?? ''
  if (!timingSafeEqual(secret, CRON_SECRET)) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  }

  const checks: Check[] = []
  const now = new Date()
  const marketOpen = isMarketOpen(now)

  // 1. Supabase connection
  try {
    const sb = getSupabase()
    const { count, error } = await sb.from('paper_trades').select('id', { count: 'exact', head: true })
    if (error) throw new Error(error.message)
    if (count !== null && count > 0) {
      checks.push({ name: 'Supabase', status: 'ok', detail: `Connected, ${count} paper trades` })
    } else {
      checks.push({ name: 'Supabase', status: 'warn', detail: 'Connected but 0 paper trades' })
    }
  } catch (e) {
    checks.push({ name: 'Supabase', status: 'fail', detail: `Connection failed: ${e}` })
  }

  // 2. THE DEAD-MAN'S SWITCH.
  //
  // Every other check here watches for something going wrong. This one watches
  // for nothing happening, which is the fault that actually occurred: for 4.5
  // months nothing errored, the jobs simply stopped, and no error-shaped alarm
  // could see it. The monitor writes a heartbeat every run; its ABSENCE is the
  // alarm. A read failure here is also a fail — "I could not check" must never
  // render as "the monitor is fine".
  try {
    const sb = getSupabase()
    const { data, error } = await sb
      .from('monitor_heartbeats')
      .select('ran_at, ok, source, role, positions_checked, positions_unassessed')
      .order('ran_at', { ascending: false })
      .limit(1)
    if (error) throw new Error(error.message)

    if (!data?.[0]) {
      checks.push({
        name: 'Monitor Heartbeat',
        status: 'fail',
        detail: 'No monitor heartbeat has ever been recorded. The position monitor is not running.',
      })
    } else {
      const hb = data[0]
      const ageMin = (now.getTime() - new Date(hb.ran_at).getTime()) / 60000
      const stamp = `${hb.source}/${hb.role}, ${Math.round(ageMin)} min ago`

      if (!hb.ok) {
        checks.push({
          name: 'Monitor Heartbeat',
          status: 'fail',
          detail: `Last monitor run FAILED (${stamp}). ${hb.positions_unassessed} position(s) unassessed — their alert level is UNKNOWN, not safe.`,
        })
      } else if (marketOpen && ageMin > HEARTBEAT_STALE_MINUTES) {
        checks.push({
          name: 'Monitor Heartbeat',
          status: 'fail',
          detail: `Market is open and the last monitor run was ${Math.round(ageMin)} min ago (limit ${HEARTBEAT_STALE_MINUTES}). Positions are unmonitored right now.`,
        })
      } else if (!marketOpen && tradingDaysSince(new Date(hb.ran_at), now) > 1) {
        checks.push({
          name: 'Monitor Heartbeat',
          status: 'fail',
          detail: `No monitor run in over a trading day (last: ${stamp}).`,
        })
      } else {
        checks.push({
          name: 'Monitor Heartbeat',
          status: 'ok',
          detail: `${stamp}, ${hb.positions_checked} position(s) checked${marketOpen ? '' : ' (market closed)'}`,
        })
      }
    }
  } catch (e) {
    checks.push({
      name: 'Monitor Heartbeat',
      status: 'fail',
      detail: `Could not read heartbeats — treating as no heartbeat: ${e}`,
    })
  }

  // 3. Chain capture freshness, in TRADING days.
  //
  // This was ">48h wall clock" against a job that runs Mon–Fri, so it went red
  // every Saturday night and stayed red until Monday with nothing wrong
  // (run 31984884170 posted a 🚨 embed at 01:25 on a Sunday). Two false alarms
  // and nobody reads the channel.
  try {
    const sb = getSupabase()
    const { data, error } = await sb
      .from('option_chain_snapshots')
      .select('date')
      .order('date', { ascending: false })
      .limit(1)
    if (error) throw new Error(error.message)

    if (data?.[0]) {
      // The column is a date; anchor it to the close so a same-day capture is
      // not counted as a session old.
      const lastCapture = new Date(`${String(data[0].date).slice(0, 10)}T20:00:00Z`)
      const staleDays = tradingDaysSince(lastCapture, now)
      if (staleDays > 1) {
        checks.push({
          name: 'Chain Capture',
          status: 'fail',
          detail: `Last capture was ${staleDays} trading days ago (${String(data[0].date).slice(0, 10)}). Data collection is broken.`,
        })
      } else {
        checks.push({
          name: 'Chain Capture',
          status: 'ok',
          detail: `Last capture ${String(data[0].date).slice(0, 10)} (${staleDays} trading day(s) ago)`,
        })
      }
    } else {
      checks.push({ name: 'Chain Capture', status: 'fail', detail: 'No chain data found at all' })
    }
  } catch (e) {
    // A read that fails is a failure. "Could not check" used to be a warn, which
    // is the same shape of bug as reporting all-clear on an unreadable table.
    checks.push({ name: 'Chain Capture', status: 'fail', detail: `Could not check chain freshness: ${e}` })
  }

  // 4. Paper trade logger freshness, also in trading days.
  try {
    const sb = getSupabase()
    const { data, error } = await sb
      .from('paper_trades')
      .select('recommended_at')
      .order('recommended_at', { ascending: false })
      .limit(1)
    if (error) throw new Error(error.message)

    if (data?.[0]) {
      const staleDays = tradingDaysSince(new Date(data[0].recommended_at), now)
      if (staleDays > 2) {
        checks.push({
          name: 'Paper Trade Logger',
          status: 'warn',
          detail: `Last paper trade ${staleDays} trading days ago. Logger may not be running.`,
        })
      } else {
        checks.push({
          name: 'Paper Trade Logger',
          status: 'ok',
          detail: `Last paper trade ${staleDays} trading day(s) ago`,
        })
      }
    } else {
      checks.push({ name: 'Paper Trade Logger', status: 'warn', detail: 'No paper trades found' })
    }
  } catch (e) {
    checks.push({ name: 'Paper Trade Logger', status: 'warn', detail: `Could not check paper trade freshness: ${e}` })
  }

  // 5. YF Proxy health
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

  // 6. The calendar this endpoint's own answers depend on. Past its last
  //    generated session every freshness number silently becomes wrong.
  try {
    const { end } = calendarRange
    const daysLeft = Math.round((new Date(`${end}T00:00:00Z`).getTime() - now.getTime()) / 86400000)
    if (daysLeft < 0) {
      checks.push({ name: 'Market Calendar', status: 'fail', detail: `Generated NYSE calendar ended ${end}. Freshness checks are unreliable.` })
    } else if (daysLeft < 90) {
      checks.push({ name: 'Market Calendar', status: 'warn', detail: `Generated NYSE calendar ends ${end} (${daysLeft} days). Regenerate it.` })
    } else {
      checks.push({ name: 'Market Calendar', status: 'ok', detail: `NYSE sessions through ${end}` })
    }
  } catch (e) {
    checks.push({ name: 'Market Calendar', status: 'fail', detail: `${e}` })
  }

  // THIS ROUTE DOES NOT ALERT. It reports; its callers alert.
  //
  // It used to post to Discord on every failing evaluation. Uptime Kuma polls
  // this endpoint every 60 seconds, so one stale heartbeat produced one Discord
  // message PER MINUTE for hours (2026-08-19 incident) — alarm spam that trains
  // humans to mute the channel, which is the failure mode this system exists to
  // prevent. Alerting belongs to the three callers with sane semantics: the
  // Hetzner watchdog (30-min cadence), the Cloudflare worker (30-min, off-box),
  // and Kuma (state-change only). The 503 status below is the entire contract.

  const overallStatus = checks.some(c => c.status === 'fail') ? 'fail'
    : checks.some(c => c.status === 'warn') ? 'warn' : 'ok'

  // THE STATUS CODE IS THE POINT.
  //
  // This route returned 200 with {"status":"fail"} in the body. The server's
  // health cron guards with `curl -sf`, which reacts only to the status code, so
  // it could not detect a failing health check — it would have run green through
  // the entire outage. Returning 503 is what lets the outer checkers be dumb
  // enough to be reliable: curl, an exit code, no body parsing, nothing to rot.
  const httpStatus = overallStatus === 'fail' ? 503 : 200

  return NextResponse.json(
    {
      status: overallStatus,
      marketOpen,
      checkedAt: now.toISOString(),
      checks,
    },
    { status: httpStatus },
  )
}
