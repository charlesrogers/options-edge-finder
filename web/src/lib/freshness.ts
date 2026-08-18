/**
 * How old a stored verdict may be before the page must refuse to stand behind it.
 *
 * The monitor is scheduled every 15 minutes during market hours. 20 gives one
 * missed run of slack — GitHub's scheduler runs late routinely — while still
 * being short enough that a genuinely dead monitor is caught inside one
 * coffee break rather than one afternoon.
 */
export const STALE_MINUTES = 20

export interface Freshness {
  latestAssessedAt: string | null
  ageMinutes: number | null
  stale: boolean
  marketOpen: boolean
  staleThresholdMinutes: number
}

/**
 * Decide whether the stored verdicts are too old to act on.
 *
 * Pure so it can be exercised against fixtures — the staleness banner is the
 * part of this page that only appears when something is broken, which is
 * exactly the kind of code that ships untested and turns out to be inverted.
 *
 * Two rules:
 *   - Staleness is only an alarm while the market is open. Overnight every
 *     verdict is hours old by design; a banner that cries wolf every evening is
 *     a banner nobody reads on the morning it matters.
 *   - No verdicts at all, during market hours, is stale — not fresh. An empty
 *     set must never read as "nothing to worry about".
 */
/*
 * marketOpen is passed in rather than imported, deliberately: it keeps this
 * module dependency-free so the fixture below can execute it directly, and it
 * makes "is the market open" a caller's fact rather than a hidden clock read.
 */
export function computeFreshness(
  assessedAtStamps: (string | null)[],
  now: Date,
  marketOpen: boolean
): Freshness {
  const stamps = assessedAtStamps.filter((s): s is string => Boolean(s)).sort()
  const latestAssessedAt = stamps.length > 0 ? stamps[stamps.length - 1] : null
  const ageMinutes =
    latestAssessedAt !== null
      ? Math.round((now.getTime() - new Date(latestAssessedAt).getTime()) / 60000)
      : null

  return {
    latestAssessedAt,
    ageMinutes,
    stale: marketOpen && (ageMinutes === null || ageMinutes > STALE_MINUTES),
    marketOpen,
    staleThresholdMinutes: STALE_MINUTES,
  }
}
