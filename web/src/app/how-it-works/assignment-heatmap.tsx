'use client'

import { useState } from 'react'
import {
  ASSIGNMENT_PROBABILITY,
  ASSIGNMENT_TABLE_N,
  DTE_BUCKETS,
  MONEYNESS_BANDS,
} from '@/lib/assignment-table'

/*
 * The table the alert engine reads, rendered as a heatmap.
 *
 * The numbers are generated from position_monitor.py into
 * web/src/lib/assignment-table.ts, so this page and the engine that fires the
 * alerts cannot disagree. tests/test_assignment_table_ts_drift.py fails CI if
 * they do.
 *
 * Colour: a sequential ramp — one hue, five steps, light to dark — because the
 * encoded quantity is magnitude. The steps are design tokens (--risk-1..5),
 * validated in both modes with the dataviz skill's ordinal checks; see the
 * comment beside them in globals.css. The five bands are plain linear
 * twentieths of probability, not tuned thresholds: any band edge that looked
 * meaningful would be inventing a finding the data does not contain.
 *
 * Every cell keeps its printed value. That is the point of the chart — the
 * reader is meant to find one cell and read it — and it doubles as the
 * contrast-relief channel the colour rules require.
 */

const BAND_COUNT = 5

/** Linear twentieths: 0-20, 20-40, 40-60, 60-80, 80-100. */
function bandOf(p: number): number {
  return Math.min(BAND_COUNT, Math.max(1, Math.ceil(p * BAND_COUNT) || 1))
}

/** The cells the ladder's own thresholds key off. Annotated, not recoloured. */
const ANCHORS: Record<string, string> = {
  '3-5% OTM|3-7': 'CLOSE SOON fires here',
  '0-1% ITM|0-3': 'CLOSE NOW fires here',
}

const pct = (p: number) => `${(p * 100).toFixed(1)}%`

interface Hover {
  band: string
  dte: string
  p: number
  anchor?: string
  x: number
  y: number
}

export function AssignmentHeatmap() {
  const [hover, setHover] = useState<Hover | null>(null)

  const cols = `minmax(104px,1.3fr) repeat(${DTE_BUCKETS.length}, minmax(56px,1fr))`

  /* offsetLeft/offsetTop are measured against the nearest positioned ancestor,
     which is the `relative` wrapper below — so the tooltip needs no scroll or
     viewport maths, and it travels correctly inside the horizontal scroller. */
  const show = (cell: HTMLElement, band: string, dte: string, p: number, anchor?: string) =>
    setHover({
      band,
      dte,
      p,
      anchor,
      x: cell.offsetLeft + cell.offsetWidth / 2,
      y: cell.offsetTop,
    })

  return (
    <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
      <div className="px-5 pt-4 pb-3 border-b">
        <p className="text-[14px] font-semibold text-foreground">
          Probability the call finishes in the money
        </p>
        <p className="text-[12px] text-muted-foreground mt-0.5 leading-relaxed">
          {ASSIGNMENT_TABLE_N.toLocaleString()}{' '}
          real Databento option observations, bucketed by
          distance from strike and days to expiry (Experiment 006). Rows above the divider are
          out of the money &mdash; the stock is below your strike. This is the table the alert
          engine reads; the page and the engine are generated from the same source.
        </p>
      </div>

      <div className="overflow-x-auto">
        <div className="min-w-[600px] relative px-5 pt-4 pb-1" onMouseLeave={() => setHover(null)}>
          {/* Header */}
          <div className="grid" style={{ gridTemplateColumns: cols }}>
            <div className="pb-2 pr-3 text-[11px] font-semibold text-muted-foreground self-end">
              Distance from strike
            </div>
            {DTE_BUCKETS.map((d) => (
              <div
                key={d.label}
                className="pb-2 px-1 text-[11px] font-semibold text-muted-foreground text-center"
              >
                {d.label}
                <span className="block text-[10px] font-normal text-muted-foreground/70">days</span>
              </div>
            ))}
          </div>

          {/* Cells — 2px surface gaps do the separating, never a stroke. */}
          {MONEYNESS_BANDS.map((band, i) => {
            const prev = MONEYNESS_BANDS[i - 1]
            const crossesStrike = Boolean(prev && !prev.itm && band.itm)
            const row = ASSIGNMENT_PROBABILITY[band.label] ?? {}
            return (
              <div key={band.label}>
                {crossesStrike && (
                  <div className="grid items-center py-1.5" style={{ gridTemplateColumns: cols }}>
                    <div className="pr-3 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground text-right">
                      strike
                    </div>
                    <div
                      className="h-px bg-foreground/25"
                      style={{ gridColumn: `2 / span ${DTE_BUCKETS.length}` }}
                    />
                  </div>
                )}
                <div className="grid" style={{ gridTemplateColumns: cols }}>
                  <div className="pr-3 py-1 text-[12px] font-medium text-foreground text-right self-center tabular-nums">
                    {band.label}
                  </div>
                  {DTE_BUCKETS.map((d) => {
                    const p = row[d.label]
                    const anchor = ANCHORS[`${band.label}|${d.label}`]
                    if (p === undefined) {
                      return (
                        <div key={d.label} className="p-[2px]">
                          <div className="h-8 rounded-[3px] border border-dashed border-border flex items-center justify-center text-[11px] text-muted-foreground/40">
                            &mdash;
                          </div>
                        </div>
                      )
                    }
                    const step = bandOf(p)
                    return (
                      <div key={d.label} className="p-[2px]">
                        <div
                          tabIndex={0}
                          role="img"
                          aria-label={`${band.label}, ${d.label} days to expiry: ${pct(p)} finish in the money${anchor ? `. ${anchor}` : ''}`}
                          className={
                            'h-8 rounded-[3px] flex items-center justify-center text-[12px] font-medium tabular-nums cursor-default ' +
                            'focus:outline-none focus-visible:ring-3 focus-visible:ring-ring/50 ' +
                            (anchor ? 'outline outline-2 outline-offset-[-3px] outline-foreground/70 ' : '')
                          }
                          style={{
                            background: `var(--risk-${step})`,
                            color: `var(--risk-${step}-fg)`,
                          }}
                          onMouseEnter={(e) => show(e.currentTarget, band.label, d.label, p, anchor)}
                          onFocus={(e) => show(e.currentTarget, band.label, d.label, p, anchor)}
                        >
                          {pct(p)}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })}

          {hover && (
            <div
              className="pointer-events-none absolute z-20 -translate-x-1/2 -translate-y-full rounded-lg border bg-card px-3 py-2 shadow-md shadow-black/[0.08]"
              style={{ left: hover.x, top: hover.y - 6 }}
            >
              <p className="text-[12px] font-semibold text-foreground whitespace-nowrap">
                {hover.band} &middot; {hover.dte} days to expiry
              </p>
              <p className="text-[12px] text-muted-foreground whitespace-nowrap">
                finishes in the money{' '}
                <span className="font-semibold text-foreground tabular-nums">{pct(hover.p)}</span>{' '}
                of the time
              </p>
              {hover.anchor && (
                <p className="mt-0.5 text-[11px] font-medium text-foreground whitespace-nowrap">
                  {hover.anchor}
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Legend — the ramp, its bands, and what the outlined cells mean. */}
      <div className="px-5 pt-2 pb-3 flex flex-wrap items-center gap-x-5 gap-y-2">
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-muted-foreground">0%</span>
          <div className="flex">
            {Array.from({ length: BAND_COUNT }, (_, k) => (
              <div
                key={k}
                className="h-3 w-8 first:rounded-l-[3px] last:rounded-r-[3px]"
                style={{ background: `var(--risk-${k + 1})` }}
                title={`${k * 20}–${(k + 1) * 20}%`}
              />
            ))}
          </div>
          <span className="text-[11px] text-muted-foreground">100%</span>
          <span className="text-[11px] text-muted-foreground/70">
            chance of finishing in the money
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-3 w-5 rounded-[3px] outline outline-2 outline-offset-[-2px] outline-foreground/70 bg-muted" />
          <span className="text-[11px] text-muted-foreground">
            the cell an alert level is set from
          </span>
        </div>
      </div>

      <div className="px-5 py-3 border-t bg-muted/20">
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Read one cell: a call 3&ndash;5% out of the money with 3&ndash;7 days left finishes in
          the money <span className="font-medium text-foreground">15.8%</span> of the time. That
          is one trade in six, on a position that looks safe. It is why{' '}
          <span className="font-medium text-foreground">CLOSE SOON</span>{' '}
          fires in the gamma zone
          rather than waiting for the stock to touch the strike. Once the stock is through the
          strike with days left, the probability never falls below 64% at any bucket &mdash;
          there is no &ldquo;wait for it to come back&rdquo; column in this table.
        </p>
      </div>
    </div>
  )
}
