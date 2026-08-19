import {
  ASSIGNMENT_PROBABILITY,
  ASSIGNMENT_TABLE_N,
  DTE_BUCKETS,
  MONEYNESS_BANDS,
} from '@/lib/assignment-table'

/*
 * CHECKPOINT 1 renders this as a plain data table on purpose.
 *
 * The spec asks for an interactive heatmap, and that lands at checkpoint 2
 * after the dataviz skill is loaded. Shipping a hand-tinted grid now would be
 * a chart built without the colour discipline, and the structure Charles is
 * being asked to approve is the CONTENT — which cell exists, what the axes
 * are, which cells the alert ladder points at. That is all legible here.
 *
 * The numbers come from web/src/lib/assignment-table.ts, generated from
 * position_monitor.py. The page and the alert engine cannot disagree.
 */

/** The cells the ladder's thresholds actually key off, called out in prose below. */
const ANCHORS: Record<string, string> = {
  '3-5% OTM|3-7': 'CLOSE SOON fires here',
  '0-1% ITM|0-3': 'CLOSE NOW fires here',
}

function pct(p: number): string {
  return `${(p * 100).toFixed(1)}%`
}

export function AssignmentTable() {
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
        <div className="min-w-[560px]">
          {/* Header row */}
          <div
            className="grid border-b bg-muted/40"
            style={{ gridTemplateColumns: `minmax(110px,1.4fr) repeat(${DTE_BUCKETS.length}, 1fr)` }}
          >
            <div className="px-4 py-2 text-[11px] font-semibold text-muted-foreground">
              Distance from strike
            </div>
            {DTE_BUCKETS.map((d) => (
              <div
                key={d.label}
                className="px-3 py-2 text-[11px] font-semibold text-muted-foreground text-right"
              >
                {d.label} DTE
              </div>
            ))}
          </div>

          {/* Data rows */}
          {MONEYNESS_BANDS.map((band, i) => {
            const prev = MONEYNESS_BANDS[i - 1]
            const crossesStrike = prev && !prev.itm && band.itm
            const row = ASSIGNMENT_PROBABILITY[band.label] ?? {}
            return (
              <div
                key={band.label}
                className={
                  'grid border-b last:border-b-0 ' +
                  (crossesStrike ? 'border-t-2 border-t-red-500/40 ' : '') +
                  (band.itm ? 'bg-red-50/40 dark:bg-red-500/5' : '')
                }
                style={{ gridTemplateColumns: `minmax(110px,1.4fr) repeat(${DTE_BUCKETS.length}, 1fr)` }}
              >
                <div className="px-4 py-2 text-[12px] font-medium text-foreground">
                  {band.label}
                </div>
                {DTE_BUCKETS.map((d) => {
                  const p = row[d.label]
                  const anchor = ANCHORS[`${band.label}|${d.label}`]
                  return (
                    <div
                      key={d.label}
                      className="px-3 py-2 text-right tabular-nums"
                      title={anchor}
                    >
                      {p === undefined ? (
                        <span className="text-[12px] text-muted-foreground/40">&mdash;</span>
                      ) : (
                        <span
                          className={
                            'text-[12px] ' +
                            (anchor
                              ? 'font-semibold text-foreground underline decoration-dotted decoration-amber-500 underline-offset-4'
                              : p >= 0.5
                                ? 'font-medium text-red-600 dark:text-red-400'
                                : 'text-foreground')
                          }
                        >
                          {pct(p)}
                        </span>
                      )}
                    </div>
                  )
                })}
              </div>
            )
          })}
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
