import { cn } from '@/lib/utils'
import { TICKER_STRATEGIES, TIER_CONFIG } from '@/lib/strategies'

/* ── Static data from experiments ── */

/*
 * Every configured ticker is listed, skips included and sorted last. Hiding the
 * skips is how AMZN and MSFT stayed invisible while still being recommendable
 * elsewhere in the app; the ones we will not trade are part of the honest table.
 */
const STRATEGY_TABLE = Object.entries(TICKER_STRATEGIES).sort((a, b) => {
  if (a[1].skip !== b[1].skip) return a[1].skip ? 1 : -1
  return (b[1].expectedPnl ?? 0) - (a[1].expectedPnl ?? 0)
})

/*
 * The crash table that used to live here is gone, not restated.
 *
 * It showed four scenarios labelled "2020 COVID crash" and "2022 bear market"
 * with dollar figures per $100K portfolio. Two independent problems:
 *
 *   1. Those scenarios were never historical. Experiment 010 is 10,000 Monte
 *      Carlo paths per scenario with Black-Scholes pricing — a simulation of a
 *      -30% shock, not a replay of 2020. Labelling it with a year presented a
 *      model as a memory.
 *   2. Experiment 010 is inside the DTE-bug blast radius. Its run.py imports
 *      assess_position from position_monitor (line 23), the code path that
 *      measured DTE against datetime.now(), so every observation was evaluated
 *      at DTE=0. Exp 012's supersede note puts it plainly: the bug "invalidated
 *      every backtest from Exp 007 to Exp 014, this one included."
 *
 * On top of both, the dollar figures shown ($34,000 / $2,800 / $31,200) appear
 * nowhere in Exp 010, which reported percentages on a 1-contract position. They
 * had no source at all.
 *
 * Re-running the stress test on cc_sim.py would give us a real answer. Until
 * then the honest content is the absence of one.
 */

/* Full literal class strings — a constructed class is purged by Tailwind's JIT. */
const TIER_FALLBACK_BADGE =
  'bg-gray-50 dark:bg-gray-500/10 text-gray-700 dark:text-gray-400 ring-gray-600/20'

const TIER_BADGE: Record<string, string> = {
  best: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 ring-emerald-600/20',
  strong: 'bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-400 ring-blue-600/20',
  good: 'bg-violet-50 dark:bg-violet-500/10 text-violet-700 dark:text-violet-400 ring-violet-600/20',
  conservative: 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 ring-amber-600/20',
  skip: 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 ring-red-600/20',
  probation: 'bg-orange-50 dark:bg-orange-500/10 text-orange-700 dark:text-orange-400 ring-orange-600/20',
  untested: 'bg-gray-50 dark:bg-gray-500/10 text-gray-700 dark:text-gray-400 ring-gray-600/20',
}

/*
 * Derived from the generated strategy table so these cards cannot drift from
 * it the way the whole page just did. The "$27K tax savings" card that used to
 * sit here is removed: it traced to Exp 007 (not Exp 008, as the page claimed),
 * and Exp 007 is inside the DTE-bug blast radius that invalidated Exps 007-014.
 */
const LIVE = Object.values(TICKER_STRATEGIES).filter((s) => !s.skip)

/** Measured on real Databento chains by Exp 022 — it carries a chain range or a coverage figure. */
const ON_REAL_PRICES = Object.values(TICKER_STRATEGIES).filter(
  (s) => !s.skip && (s.pnlRangeLow !== null || s.repricingCoverage !== null)
)

/*
 * Win-rate range is quoted over the real-price tickers only. GOOGL's 94% was
 * measured on stock closes (Exp 014) and would silently widen a range captioned
 * "Exp 022" with a number Exp 022 never produced.
 */
const WIN_RATES = ON_REAL_PRICES.map((s) => s.expectedWinRate).filter(
  (w): w is number => w !== null
)

const METRICS = [
  {
    value: '145,099',
    label: 'Observations',
    sublabel: 'assignment-probability table (Exp 006)',
  },
  {
    value: `${Object.keys(TICKER_STRATEGIES).length}`,
    label: 'Tickers Configured',
    sublabel: `${LIVE.length} recommendable, ${Object.keys(TICKER_STRATEGIES).length - LIVE.length} skipped`,
  },
  {
    value: `${Math.min(...WIN_RATES)}-${Math.max(...WIN_RATES)}%`,
    label: 'Win Rates',
    sublabel: 'simulated, hold-to-expiry (Exp 022)',
  },
  {
    value: `${ON_REAL_PRICES.length}`,
    label: 'On Real Option Prices',
    sublabel: 'the rest are stock-close only',
  },
]

export default function HowItWorksPage() {
  return (
    <div className="max-w-7xl mx-auto px-6 py-8 space-y-10">
      {/* ── Hero Section ── */}
      <section className="relative overflow-hidden rounded-2xl border-0">
        {/*
          This hero used to read "$27,000 in taxes avoided — Backtest Result
          (Experiment 008)". The figure is from Exp 007, not 008, and Exp 007 is
          one of the backtests the DTE bug invalidated. It is withdrawn rather
          than restated: there is no corrected tax figure, because the
          experiment that produced it has not been re-run on a working engine.
        */}
        <div className="absolute inset-0 -z-10">
          <div className="absolute top-0 left-1/4 w-[500px] h-[400px] rounded-full bg-amber-500/8 blur-3xl" />
          <div className="absolute bottom-0 right-1/4 w-[300px] h-[300px] rounded-full bg-amber-400/5 blur-3xl" />
        </div>

        <div className="bg-gradient-to-br from-amber-50/80 to-amber-100/60 dark:from-amber-950/40 dark:to-amber-900/20 py-14 px-6 text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-amber-500/10 text-amber-700 dark:text-amber-400 text-[12px] font-semibold mb-5">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500" />
            Numbers corrected 2026-08-18 (Experiment 022)
          </div>

          <p className="text-5xl sm:text-6xl font-bold tracking-tight text-amber-800 dark:text-amber-300 leading-none">
            ~4&times; too high
          </p>
          <p className="mt-3 text-[15px] text-amber-800/80 dark:text-amber-300/80 max-w-xl mx-auto leading-relaxed">
            Every backtest from Experiment 007 to 014 measured days-to-expiry against the wall
            clock, so each observation was scored as if it expired that day. Re-run on the fixed
            engine, the annual income this product was publishing is roughly four times what it
            actually measures on real fills. The figures below are the corrected ones.
          </p>
        </div>
      </section>

      {/* ── Metric Cards ── */}
      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {METRICS.map((m) => (
          <div
            key={m.label}
            className="rounded-xl border bg-card px-5 pt-4 pb-3 shadow-sm shadow-black/[0.04] hover:shadow-md hover:shadow-black/[0.06] transition-shadow"
          >
            <p className="text-2xl font-semibold tracking-tight text-foreground">{m.value}</p>
            <p className="text-[12px] font-medium text-foreground mt-0.5">{m.label}</p>
            <p className="text-[10px] text-muted-foreground/60">{m.sublabel}</p>
          </div>
        ))}
      </section>

      {/* ── With vs Without ── */}
      <section>
        <h2 className="mb-4 text-[15px] font-semibold text-foreground">
          With vs Without Copilot
        </h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {/* Without */}
          <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden flex">
            <div className="w-1 flex-shrink-0 bg-red-500" />
            <div className="flex-1 px-5 pt-4 pb-4">
              <p className="text-[14px] font-semibold text-red-600 dark:text-red-400 mb-3">
                Without Copilot
              </p>
              <div className="space-y-2.5">
                {[
                  'Pick random strikes based on gut feel',
                  'No idea when to close -- hold until expiry',
                  'Miss ex-dividend dates, get assigned unexpectedly',
                  'Same strategy for every stock regardless of volatility',
                  'No data on what actually works',
                ].map((text, i) => (
                  <div key={i} className="flex items-start gap-2.5">
                    <span className="h-1.5 w-1.5 rounded-full bg-red-400 mt-1.5 flex-shrink-0" />
                    <p className="text-[12px] text-muted-foreground leading-relaxed">{text}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* With */}
          <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden flex">
            <div className="w-1 flex-shrink-0 bg-emerald-500" />
            <div className="flex-1 px-5 pt-4 pb-4">
              <p className="text-[14px] font-semibold text-emerald-600 dark:text-emerald-400 mb-3">
                With Copilot
              </p>
              <div className="space-y-2.5">
                {[
                  // Attribution corrected: the 145,099 observations are Exp 006's
                  // assignment-probability table, not the source of the OTM%/DTE
                  // settings. Those come from Exp 014 (stock closes, walk-forward)
                  // and were re-measured on real chains by Exp 022.
                  'OTM% and DTE per ticker from walk-forward validation (Exp 014), re-measured on real option chains (Exp 022)',
                  'Real-time alerts: SAFE, WATCH, CLOSE_SOON, CLOSE_NOW',
                  'Ex-dividend and earnings tracking built in',
                  'Position size capped by measured option liquidity, not just by shares owned',
                  'Tickers without real option data are marked, not quietly recommended',
                ].map((text, i) => (
                  <div key={i} className="flex items-start gap-2.5">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 mt-1.5 flex-shrink-0" />
                    <p className="text-[12px] text-muted-foreground leading-relaxed">{text}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Strategy Table (custom grid, not HTML table) ── */}
      <section>
        <h2 className="mb-1 text-[15px] font-semibold text-foreground">
          Strategy Per Ticker
        </h2>
        <p className="mb-4 text-[12px] text-muted-foreground leading-relaxed">
          Expected P&amp;L is a simulated annual figure per contract, shown with the range across
          staggered start dates &mdash; and, where they disagree, the figure counting only exits
          that were real quoted prints. Half-year retention on identical rules swung from
          &minus;77.9% to +92.8%, so the point estimate describes the start date as much as the
          strategy.
        </p>
        <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
          {/* Header row */}
          <div className="grid grid-cols-[80px_100px_60px_70px_130px_70px_1.5fr] gap-2 px-5 py-3 border-b bg-muted/30">
            {['Ticker', 'Tier', 'OTM %', 'DTE', 'Expected P&L', 'Win Rate', 'Note'].map((h) => (
              <div key={h} className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                {h}
              </div>
            ))}
          </div>

          {/* Data rows */}
          {STRATEGY_TABLE.map(([ticker, s]) => {
            const tierCfg = TIER_CONFIG[s.tier]
            return (
              <div
                key={ticker}
                className="grid grid-cols-[80px_100px_60px_70px_130px_70px_1.5fr] gap-2 px-5 py-3 border-b last:border-0 hover:bg-accent/40 transition-colors items-center"
              >
                <div className="text-[13px] font-semibold text-foreground">{ticker}</div>
                <div>
                  <span className={cn(
                    'inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold ring-1 ring-inset',
                    TIER_BADGE[s.tier] ?? TIER_FALLBACK_BADGE
                  )}>
                    {tierCfg?.label ?? s.tier}
                  </span>
                </div>
                <div className="text-[12px] tabular-nums text-foreground">
                  {s.otmPct ? `${(s.otmPct * 100).toFixed(0)}%` : '--'}
                </div>
                <div className="text-[12px] tabular-nums text-foreground">
                  {s.minDte && s.maxDte ? `${s.minDte}-${s.maxDte}` : '--'}
                </div>
                {/*
                  The point estimate never renders alone: the chain range or the
                  real-fill figure goes directly under it. On DIS the point is
                  $267 and the range is $51..$590 — the spread is the finding.
                */}
                <div>
                  <div className={cn(
                    'text-[12px] font-semibold tabular-nums',
                    s.skip ? 'text-muted-foreground' : 'text-emerald-600 dark:text-emerald-400'
                  )}>
                    {s.expectedPnl !== null ? `$${s.expectedPnl.toLocaleString()}` : '--'}
                  </div>
                  {s.pnlRangeLow !== null && s.pnlRangeHigh !== null && (
                    <div className="text-[10px] text-muted-foreground/70 tabular-nums">
                      {s.pnlRangeLow < 0 ? '-' : ''}${Math.abs(s.pnlRangeLow).toLocaleString()}..
                      {s.pnlRangeHigh < 0 ? '-' : ''}${Math.abs(s.pnlRangeHigh).toLocaleString()}
                    </div>
                  )}
                  {s.realFillPnl !== null && (
                    <div className="text-[10px] text-red-600/80 dark:text-red-400/80 tabular-nums">
                      {s.realFillPnl < 0 ? '-' : ''}${Math.abs(s.realFillPnl).toLocaleString()} real fills
                    </div>
                  )}
                </div>
                <div className="text-[12px] tabular-nums text-foreground">
                  {s.expectedWinRate !== null ? `${s.expectedWinRate}%` : '--'}
                </div>
                {/* Not truncated — the note is where the caveat lives. */}
                <div className="text-[11px] text-muted-foreground leading-relaxed">
                  {s.note}
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* ── Crash stress test: withdrawn ── */}
      <section>
        <h2 className="mb-2 text-[15px] font-semibold text-foreground">
          What Happens in a Crash?
        </h2>
        <div className="rounded-xl border border-amber-200 dark:border-amber-500/20 bg-amber-50/50 dark:bg-amber-500/5 px-5 py-4">
          <p className="text-[13px] font-semibold text-amber-800 dark:text-amber-300">
            We do not currently have a defensible answer.
          </p>
          <div className="mt-2 space-y-2 text-[12px] text-amber-800/80 dark:text-amber-300/80 leading-relaxed">
            <p>
              This section used to show four crash scenarios &mdash; labelled &ldquo;2020 COVID
              crash&rdquo; and &ldquo;2022 bear market&rdquo; &mdash; with the loss, the premium
              collected and the net damage per $100K. All of it has been removed.
            </p>
            <p>
              Those were never historical replays. Experiment 010 is 10,000 Monte Carlo paths per
              scenario with Black-Scholes pricing, so attaching a year to a row presented a model
              as a memory. It is also inside the bug described above: its code imports the
              copilot&rsquo;s <code className="text-[11px]">assess_position</code>, the path that
              measured days-to-expiry against the wall clock. The dollar figures shown did not
              appear in Experiment 010 at all.
            </p>
            <p>
              What survives is narrower and worth stating plainly: covered calls collect premium,
              premium offsets some of a drawdown, and it cannot offset much of a large one. How
              much, on this strategy, is an open question until the stress test is re-run on the
              corrected engine.
            </p>
          </div>
        </div>
      </section>

      {/* ── Methodology (collapsible) ── */}
      <section>
        <details className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden group">
          <summary className="px-5 py-4 flex items-center justify-between cursor-pointer hover:bg-accent/40 transition-colors">
            <span className="text-[14px] font-semibold text-foreground">Methodology</span>
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-muted-foreground transition-transform group-open:rotate-180">
              <path d="m6 9 6 6 6-6" />
            </svg>
          </summary>
          <div className="px-5 pb-5 border-t pt-4 space-y-3 text-[12px] text-muted-foreground leading-relaxed">
            <p>
              <span className="font-medium text-foreground">What was wrong.</span> Every backtest
              from Experiment 007 through 014 computed days-to-expiry against{' '}
              <code className="text-[11px]">datetime.now()</code>, so each historical observation
              was evaluated as though it expired that day. The strategy grid search that used to
              headline this page (Experiment 008) is one of them. Those results are kept as the
              record of what was believed, not cited as evidence.
            </p>
            <p>
              <span className="font-medium text-foreground">What replaced it.</span> Experiment 022
              re-derived every published per-ticker figure on a corrected engine
              (<code className="text-[11px]">cc_sim.py</code>: real as-of dates, real ex-dividend
              dates, one cohort per trading day) against real Databento option prices, reporting
              the median of 25 staggered chains. Three of four tickers fell outside their
              pre-registered tolerance. The strike distances themselves rest on Experiment 014,
              which was independently verified to be outside the bug&rsquo;s blast radius.
            </p>
            <p>
              <span className="font-medium text-foreground">Repricing coverage.</span> A simulated
              exit is only as good as the quote behind it. Where no real print existed the engine
              carried the last price forward, so each ticker also carries the share of exits that
              repriced against a real quote &mdash; 97% for AAPL, 56% for TMUS, 36% for KKR.
              Restricted to real prints, TMUS and KKR are loss-making. Both are on probation for
              exactly that reason.
            </p>
            <p>
              <span className="font-medium text-foreground">Win rate</span> is the share of
              simulated cycles that ended profitable &mdash; premium kept exceeded any buyback
              cost &mdash; under the production copilot policy (Exp 022 ran the copilot's own
              exits, early buybacks included). A losing cycle means the buyback cost more than
              the premium collected; stock P&amp;L is not part of these figures.
            </p>
          </div>
        </details>
      </section>

      {/* Fine print */}
      <p className="text-[11px] text-muted-foreground/50 leading-relaxed">
        Every figure on this page is simulated on historical option prices, not a trading record:
        no real-price recommendation from this product has been scored yet. Covered calls limit
        upside in exchange for income and a partial downside cushion, and they lose money on
        individual trades &mdash; 9% of AAPL&rsquo;s simulated trades lost, the worst by $971. Past
        performance, simulated or otherwise, does not guarantee future results.
      </p>
    </div>
  )
}
