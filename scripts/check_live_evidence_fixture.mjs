#!/usr/bin/env node --experimental-strip-types
/**
 * Fixture check for the /how-it-works live evidence widgets.
 *
 * Both widgets only tell the truth in states you cannot produce by looking at
 * them: a chain that has gone stale, a chain that ran and FAILED, a graveyard
 * row with a status nobody anticipated. A widget that renders "live" for all of
 * those is worse than no widget, because the page's whole argument is that it
 * reports its own failures. So the states are exercised against fixtures.
 *
 * Run:  node --experimental-strip-types scripts/check_live_evidence_fixture.mjs
 */

import {
  HEARTBEAT_STALE_MINUTES,
  summarizeHeartbeats,
  summarizeGraveyard,
} from '../web/src/lib/live-evidence.ts'

const NOW = new Date('2026-08-19T15:00:00Z') // 11:00 ET, mid-session
const minutesAgo = (m) => new Date(NOW.getTime() - m * 60_000).toISOString()

/* A stub calendar: the real one is exercised by tests/test_market_calendar.py.
   What matters here is that the overnight branch consults it at all. */
const tradingDaysSince = (since, now) =>
  Math.floor((now.getTime() - since.getTime()) / (24 * 3600 * 1000))

const hb = (role, ageMin, ok = true) => ({
  ran_at: minutesAgo(ageMin),
  ok,
  source: role === 'chain1' ? 'hetzner-cron' : 'github-actions',
  role,
  engine: role === 'chain1' ? 'copilot.ts via /api/cron/monitor' : 'position_monitor.py',
})

const HEARTBEAT_CASES = [
  {
    name: 'both chains recent during market hours -> both live',
    rows: [hb('chain1', 5), hb('primary', 9)],
    marketOpen: true,
    expect: { chain1: 'live', primary: 'live' },
  },
  {
    name: 'one chain drifts past the stale limit -> only that chain goes stale',
    // The real 2026-08-19 shape: the server cron kept 15-minute cadence while
    // GitHub's scheduler ran once in fifty minutes. An aggregate "is it alive"
    // would have read green through this.
    rows: [hb('chain1', 5), hb('primary', HEARTBEAT_STALE_MINUTES + 1)],
    marketOpen: true,
    expect: { chain1: 'live', primary: 'stale' },
  },
  {
    name: 'exactly at the limit is not yet stale',
    rows: [hb('chain1', HEARTBEAT_STALE_MINUTES), hb('primary', 1)],
    marketOpen: true,
    expect: { chain1: 'live', primary: 'live' },
  },
  {
    name: 'a run that FAILED is not rescued by being recent',
    rows: [hb('chain1', 1, false), hb('primary', 1)],
    marketOpen: true,
    expect: { chain1: 'failed', primary: 'live' },
  },
  {
    name: 'overnight: hours old is by design, not an alarm',
    rows: [hb('chain1', 600), hb('primary', 620)],
    marketOpen: false,
    expect: { chain1: 'live', primary: 'live' },
  },
  {
    name: 'overnight: a whole trading session missed is still stale',
    rows: [hb('chain1', 60 * 24 * 3), hb('primary', 60 * 24 * 3)],
    marketOpen: false,
    expect: { chain1: 'stale', primary: 'stale' },
  },
  {
    name: 'a chain that has never written a heartbeat reads never, not live',
    rows: [hb('chain1', 5)],
    marketOpen: true,
    expect: { chain1: 'live', primary: 'never' },
  },
  {
    name: 'no heartbeats at all -> nothing reads live',
    rows: [],
    marketOpen: true,
    expect: { chain1: 'never', primary: 'never' },
  },
  {
    name: 'the newest row wins even when the table comes back unsorted',
    rows: [hb('chain1', 400), hb('chain1', 3), hb('primary', 4)],
    marketOpen: true,
    expect: { chain1: 'live', primary: 'live' },
  },
]

const GRAVEYARD_CASES = [
  {
    name: 'the live shape as of 2026-08-19: 13 registered, 9 tested, 9 failed, 0 deployed',
    rows: [
      ...['H01', 'H02', 'H03', 'H04'].map((id) => ({ signal_id: id, status: 'untested' })),
      { signal_id: 'H17', status: 'failed_layer_2' },
      { signal_id: 'H18', status: 'failed_layer_2' },
      { signal_id: 'H19', status: 'failed_layer_2' },
      { signal_id: 'H20', status: 'failed_layer_0' },
      { signal_id: 'H21', status: 'failed_layer_0' },
      { signal_id: 'H22', status: 'failed_layer_0' },
      { signal_id: 'H22a', status: 'failed_layer_3' },
      { signal_id: 'H23', status: 'failed_layer_4' },
      { signal_id: 'H24', status: 'failed_layer_2' },
    ],
    expect: { registered: 13, tested: 9, failed: 9, deployed: 0, untested: 4, other: 0 },
  },
  {
    name: 'a deployed signal counts as tested and deployed, never as failed',
    rows: [
      { signal_id: 'H01', status: 'deployed' },
      { signal_id: 'H02', status: 'failed_layer_1' },
    ],
    expect: { registered: 2, tested: 2, failed: 1, deployed: 1, untested: 0, other: 0 },
  },
  {
    name: 'an unrecognised status lands in `other`, never silently in a pass bucket',
    rows: [
      { signal_id: 'H01', status: 'marginal' },
      { signal_id: 'H02', status: 'untested' },
    ],
    expect: { registered: 2, tested: 1, failed: 0, deployed: 0, untested: 1, other: 1 },
  },
  {
    name: 'an empty table reports zero registered, not a missing scorecard',
    rows: [],
    expect: { registered: 0, tested: 0, failed: 0, deployed: 0, untested: 0, other: 0 },
  },
]

let failures = 0

console.log('HEARTBEATS')
for (const c of HEARTBEAT_CASES) {
  const got = summarizeHeartbeats(c.rows, ['chain1', 'primary'], {
    now: NOW,
    marketOpen: c.marketOpen,
    tradingDaysSince,
  })
  const actual = Object.fromEntries(got.map((g) => [g.role, g.state]))
  const ok = Object.entries(c.expect).every(([role, state]) => actual[role] === state)
  console.log(`  [${ok ? 'OK  ' : 'FAIL'}] ${c.name}`)
  if (!ok) {
    failures++
    console.log(`         expected ${JSON.stringify(c.expect)}`)
    console.log(`         got      ${JSON.stringify(actual)}`)
  }
}

console.log('\nGRAVEYARD')
for (const c of GRAVEYARD_CASES) {
  const rows = c.rows.map((r) => ({
    name: null,
    tier: null,
    layer_reached: null,
    tested_date: null,
    ...r,
  }))
  const got = summarizeGraveyard(rows)
  const bad = Object.entries(c.expect).filter(([k, v]) => got[k] !== v)
  console.log(`  [${bad.length ? 'FAIL' : 'OK  '}] ${c.name}`)
  if (bad.length) {
    failures++
    for (const [k, v] of bad) console.log(`         ${k}: expected ${v}, got ${got[k]}`)
  }
}

/* The buckets must partition the table. A signal that falls out of every count
   is exactly how "0 deployed" would quietly become a lie. */
console.log('\nPARTITION')
for (const c of GRAVEYARD_CASES) {
  const rows = c.rows.map((r) => ({
    name: null,
    tier: null,
    layer_reached: null,
    tested_date: null,
    ...r,
  }))
  const g = summarizeGraveyard(rows)
  const ok =
    g.failed + g.deployed + g.other + g.untested === g.registered &&
    g.tested + g.untested === g.registered
  console.log(`  [${ok ? 'OK  ' : 'FAIL'}] buckets partition the table — ${c.name}`)
  if (!ok) failures++
}

console.log()
if (failures) {
  console.log(`FAILED — ${failures} case(s)`)
  process.exit(1)
}
console.log('PASS — every live-evidence state behaves as specified')
