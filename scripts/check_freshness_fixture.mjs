#!/usr/bin/env node --experimental-strip-types
/**
 * Fixture check for the /positions staleness banner (web-overhaul-spec §7.5).
 *
 * The banner only appears when something is broken, which is exactly the kind of
 * code that ships untested and turns out to be inverted. The spec offered two
 * ways to demonstrate it: pause the live monitor, or use a fixture. Pausing a
 * safety-critical monitor to test a banner is a bad trade, so: fixture.
 *
 * Run:  node --experimental-strip-types scripts/check_freshness_fixture.mjs
 */

import { computeFreshness, STALE_MINUTES } from '../web/src/lib/freshness.ts'

const NOW = new Date('2026-08-18T15:00:00Z') // 11:00 ET, mid-session
const minutesAgo = (m) => new Date(NOW.getTime() - m * 60_000).toISOString()

const CASES = [
  {
    name: 'fresh verdict during market hours -> no banner',
    stamps: [minutesAgo(3)],
    marketOpen: true,
    expect: { stale: false, ageMinutes: 3 },
  },
  {
    name: 'exactly at the threshold -> still not stale (> not >=)',
    stamps: [minutesAgo(STALE_MINUTES)],
    marketOpen: true,
    expect: { stale: false, ageMinutes: STALE_MINUTES },
  },
  {
    name: 'one minute past the threshold -> BANNER',
    stamps: [minutesAgo(STALE_MINUTES + 1)],
    marketOpen: true,
    expect: { stale: true, ageMinutes: STALE_MINUTES + 1 },
  },
  {
    name: 'monitor dead for two hours during the session -> BANNER',
    stamps: [minutesAgo(120)],
    marketOpen: true,
    expect: { stale: true, ageMinutes: 120 },
  },
  {
    name: 'the same two-hour-old verdict after the close -> no banner',
    stamps: [minutesAgo(120)],
    marketOpen: false,
    expect: { stale: false, ageMinutes: 120 },
  },
  {
    name: 'NO verdicts at all during market hours -> BANNER (never reads as calm)',
    stamps: [],
    marketOpen: true,
    expect: { stale: true, ageMinutes: null },
  },
  {
    name: 'no verdicts, market closed -> no banner',
    stamps: [],
    marketOpen: false,
    expect: { stale: false, ageMinutes: null },
  },
  {
    name: 'newest of several stamps wins, not the first in the array',
    stamps: [minutesAgo(90), minutesAgo(4), minutesAgo(45)],
    marketOpen: true,
    expect: { stale: false, ageMinutes: 4 },
  },
  {
    name: 'unassessed positions (null stamps) do not count as fresh',
    stamps: [null, null, minutesAgo(35)],
    marketOpen: true,
    expect: { stale: true, ageMinutes: 35 },
  },
]

let failed = 0
console.log(`Staleness threshold: ${STALE_MINUTES} minutes\n`)

for (const c of CASES) {
  const got = computeFreshness(c.stamps, NOW, c.marketOpen)
  const ok =
    got.stale === c.expect.stale && got.ageMinutes === c.expect.ageMinutes
  console.log(
    `  [${ok ? 'OK  ' : 'FAIL'}] ${c.name}\n` +
      `         stale=${got.stale} age=${got.ageMinutes} ` +
      `(expected stale=${c.expect.stale} age=${c.expect.ageMinutes})`
  )
  if (!ok) failed++
}

console.log()
if (failed > 0) {
  console.error(`FAILED — ${failed} of ${CASES.length} cases`)
  process.exit(1)
}
console.log(`PASS — ${CASES.length}/${CASES.length} staleness cases behave as specified.`)
