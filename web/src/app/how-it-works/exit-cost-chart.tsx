'use client'

import { useState } from 'react'

/*
 * Exp 006's Monte Carlo tail table, as the comparison it actually is.
 *
 * Form: a dumbbell. Two measures on ONE scale (dollars per share), four ordered
 * positions, and the quantity the reader is meant to walk away with is the
 * DISTANCE between the two dots — which is the mark a dumbbell draws and a
 * paired bar chart makes you compute. Grouped bars were the obvious choice and
 * the wrong one: they encode two lengths from a shared baseline and leave the
 * gap implicit.
 *
 * Colour: two categorical slots from the house chart tokens (chart-1, chart-4),
 * validated in both modes with the dataviz skill (worst adjacent pair ΔE 23.8
 * protan / 36.1 normal in light, 25.1 / 34.4 in dark — well clear of the
 * floors). Legend always present; the gap is direct-labelled; the endpoint
 * values live in the hover readout and in the table view below, so no number is
 * gated behind a hover.
 */

/** Exp 006, 480,000 simulated paths, 14 DTE. Dollars per share. */
const ROWS = [
  { position: '3% OTM', closeNow: 3.75, waitP99: 34.44 },
  { position: '1% OTM', closeNow: 5.87, waitP99: 40.51 },
  { position: 'At the money', closeNow: 7.17, waitP99: 43.54 },
  { position: '1% ITM', closeNow: 8.62, waitP99: 46.58 },
]

const AXIS_MAX = 50
const TICKS = [0, 10, 20, 30, 40, 50]

const usd = (n: number) => `$${n.toFixed(2)}`
const at = (v: number) => `${(v / AXIS_MAX) * 100}%`

export function ExitCostChart({ sharesPerTicker }: { sharesPerTicker: number }) {
  const [hover, setHover] = useState<number | null>(null)

  /* The smallest gap in the table, not the largest — the rhetorical point is
     that even the position that looks safest carries this. Derived, so it can
     never drift from the share count stated at the top of the page. */
  const smallestGap = Math.min(...ROWS.map((r) => r.waitP99 - r.closeNow))
  const atSize = Math.round(smallestGap * sharesPerTicker)

  return (
    <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
      <div className="px-5 pt-4 pb-3 border-b">
        <p className="text-[14px] font-semibold text-foreground">
          What the buyback costs now, against what it can cost if you wait
        </p>
        <p className="text-[12px] text-muted-foreground mt-0.5 leading-relaxed">
          Dollars per share, 14 days to expiry. 480,000 simulated paths (Experiment 006). The
          median case favours closing by $8&ndash;21/share; this is the 99th percentile, where it
          stops being a preference.
        </p>
      </div>

      {/* Legend — identity never rests on colour alone. */}
      <div className="px-5 pt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5">
        <span className="inline-flex items-center gap-2 text-[11px] text-muted-foreground">
          <span
            className="h-2.5 w-2.5 rounded-full ring-2 ring-card"
            style={{ background: 'var(--chart-1)' }}
          />
          Cost to close now
        </span>
        <span className="inline-flex items-center gap-2 text-[11px] text-muted-foreground">
          <span
            className="h-2.5 w-2.5 rounded-full ring-2 ring-card"
            style={{ background: 'var(--chart-4)' }}
          />
          Worst case if you wait (99th percentile)
        </span>
      </div>

      <div className="px-5 pt-4 pb-2">
        <div className="grid gap-y-1" style={{ gridTemplateColumns: 'minmax(88px,auto) 1fr' }}>
          {ROWS.map((r, i) => {
            const gap = r.waitP99 - r.closeNow
            const active = hover === i
            return (
              <div key={r.position} className="contents">
                <div className="pr-3 self-center text-[12px] font-medium text-foreground text-right">
                  {r.position}
                </div>
                <div
                  className="relative h-11"
                  tabIndex={0}
                  role="img"
                  aria-label={`${r.position}: closing now costs ${usd(r.closeNow)} per share, waiting costs up to ${usd(r.waitP99)} at the 99th percentile, a gap of ${usd(gap)}`}
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover(null)}
                  onFocus={() => setHover(i)}
                  onBlur={() => setHover(null)}
                >
                  {/* Gridlines: hairline, solid, recessive. */}
                  {TICKS.map((t) => (
                    <div
                      key={t}
                      className="absolute top-0 bottom-0 w-px bg-border"
                      style={{ left: at(t) }}
                    />
                  ))}

                  {/* The connector IS the finding. */}
                  <div
                    className="absolute top-1/2 -translate-y-1/2 h-[2px] rounded-full"
                    style={{
                      left: at(r.closeNow),
                      width: at(gap),
                      background: 'var(--chart-4)',
                      opacity: active ? 1 : 0.45,
                    }}
                  />

                  <div
                    className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-card"
                    style={{ left: at(r.closeNow), background: 'var(--chart-1)' }}
                  />
                  <div
                    className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-card"
                    style={{ left: at(r.waitP99), background: 'var(--chart-4)' }}
                  />

                  {/*
                    Direct label: the gap only — never a number on every point.
                    Centred over the connector rather than hung off the right
                    dot, which pushed the last row's label off the card at
                    93% of the axis. A label that does not fit is not a label.
                  */}
                  <span
                    className="absolute top-0 -translate-x-1/2 text-[11px] font-semibold text-foreground tabular-nums whitespace-nowrap"
                    style={{ left: at((r.closeNow + r.waitP99) / 2) }}
                  >
                    {usd(gap)} more
                  </span>

                  {active && (
                    <div
                      className="pointer-events-none absolute z-20 -translate-x-1/2 bottom-full mb-1 rounded-lg border bg-card px-3 py-2 shadow-md shadow-black/[0.08]"
                      style={{ left: at((r.closeNow + r.waitP99) / 2) }}
                    >
                      <p className="text-[12px] font-semibold text-foreground whitespace-nowrap">
                        {r.position}, 14 DTE
                      </p>
                      <p className="text-[12px] text-muted-foreground whitespace-nowrap tabular-nums">
                        close now {usd(r.closeNow)} &middot; wait (p99) {usd(r.waitP99)}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )
          })}

          {/* Axis */}
          <div />
          <div className="relative h-5 mt-1">
            {TICKS.map((t) => (
              <span
                key={t}
                className="absolute top-0 -translate-x-1/2 text-[10px] text-muted-foreground tabular-nums"
                style={{ left: at(t) }}
              >
                ${t}
              </span>
            ))}
          </div>
        </div>
      </div>

      <details className="px-5 pb-3 group">
        <summary className="cursor-pointer text-[11px] text-muted-foreground hover:text-foreground list-none marker:hidden">
          <span className="underline decoration-dotted underline-offset-4">
            Table view &mdash; the same four rows as numbers
          </span>
        </summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-[12px] tabular-nums">
            <thead>
              <tr className="text-[11px] text-muted-foreground">
                <th className="text-left font-semibold py-1">Position (14 DTE)</th>
                <th className="text-right font-semibold py-1">Close now</th>
                <th className="text-right font-semibold py-1">Wait (99th pctl)</th>
                <th className="text-right font-semibold py-1">Difference</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((r) => (
                <tr key={r.position} className="border-t">
                  <td className="py-1.5 text-foreground">{r.position}</td>
                  <td className="py-1.5 text-right text-foreground">{usd(r.closeNow)}</td>
                  <td className="py-1.5 text-right text-foreground">{usd(r.waitP99)}</td>
                  <td className="py-1.5 text-right font-semibold text-foreground">
                    {usd(r.waitP99 - r.closeNow)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <div className="px-5 py-3 border-t bg-muted/20">
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          At {sharesPerTicker.toLocaleString()} shares, the <em>smallest</em>{' '}
          gap in this chart
          &mdash; the 3% out-of-the-money row, the one that looks safe &mdash; is{' '}
          <span className="font-medium text-foreground tabular-nums">
            ${atSize.toLocaleString()}
          </span>
          . You are not buying back to make money on the buyback. You are buying out of the tail.
          (Experiment 006 states this figure at 8,000 shares, the size of the MSFT position it was
          written about; this page states everything at the {sharesPerTicker.toLocaleString()}
          -share book it models throughout, and derives the dollars rather than quoting them.)
        </p>
      </div>
    </div>
  )
}
