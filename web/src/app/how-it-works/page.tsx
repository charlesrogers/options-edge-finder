import { TICKER_STRATEGIES, TIER_CONFIG, DEFAULT_IV_THRESHOLD } from '@/lib/strategies'
import { ASSIGNMENT_TABLE_N } from '@/lib/assignment-table'
import { AssignmentTable } from './assignment-table'

/*
 * ── What this page is ──────────────────────────────────────────────────────
 *
 * The reader is a 30-year Goldman/CS/DB veteran with 10,000 shares per ticker
 * who once lost ~$400K to a missed ex-dividend assignment. He does not need
 * covered calls explained. He needs a reason to trust software with that
 * failure mode. So the page is an evidence trail, not a pitch: methodology,
 * data sources, outputs, and the failures we found in our own work.
 *
 * Rules that bind every number below:
 *   - No number without lineage. Every figure names its experiment.
 *   - No point estimate without its spread. Exp 022 measured half-year
 *     retention swinging -77.9% -> +92.8% on identical rules; an annual point
 *     estimate reports a regime as much as a strategy.
 *   - Nothing is hardcoded that could be derived. Constants pretending to be
 *     live data are the exact bug (strategies.ts, frozen March 2026) that this
 *     product's whole correction programme exists to kill.
 *
 * ── Checkpoint status ──────────────────────────────────────────────────────
 * CHECKPOINT 1 (this pass): content and information architecture, static.
 * CHECKPOINT 2: the assignment heatmap, the close-now chart, the reliability
 *   diagram, the LIVE status widget and the LIVE graveyard counts. Every
 *   placeholder for those is marked `CHECKPOINT 2` inline and renders an
 *   honest "not wired yet" state rather than a plausible fake.
 * CHECKPOINT 3: polish.
 */

const ALL = Object.entries(TICKER_STRATEGIES)
const LIVE = ALL.filter(([, s]) => !s.skip)
const SKIPPED = ALL.filter(([, s]) => s.skip)

/** Measured on real Databento chains by Exp 022 — carries a chain range or a coverage figure. */
const ON_REAL_PRICES = LIVE.filter(
  ([, s]) => s.pnlRangeLow !== null || s.repricingCoverage !== null
)

/*
 * The portfolio figure is DERIVED here, never typed in.
 *
 * Charles's father holds ~10,000 shares per ticker. Contracts are capped by
 * measured option liquidity (Exp 021), so KKR contributes 7 contracts, not
 * 100 — and the cap is applied to the MONEY, not only to the displayed count.
 * The runbook's older "~$70-85K/yr" predates Exp 022 and is not reproducible
 * from the corrected table; this is what the corrected table actually sums to.
 */
const SHARES_PER_TICKER = 10000

function contractsFor(maxContracts: number | null): number {
  const uncapped = Math.floor(SHARES_PER_TICKER / 100)
  return maxContracts === null ? uncapped : Math.min(uncapped, maxContracts)
}

const AT_SIZE_SIMULATED = LIVE.reduce(
  (sum, [, s]) => sum + (s.expectedPnl ?? 0) * contractsFor(s.maxContracts),
  0
)

/*
 * Same sum, but where Exp 022 could separate exits that were real quoted
 * prints from exits carried forward, the real-print figure is used. TMUS and
 * KKR go negative on that basis. This number is the honest one.
 */
const AT_SIZE_REAL_FILL = LIVE.reduce(
  (sum, [, s]) => sum + (s.realFillPnl ?? s.expectedPnl ?? 0) * contractsFor(s.maxContracts),
  0
)

const NO_PNL_MEASURED = LIVE.filter(([, s]) => s.expectedPnl === null)

const usd = (n: number) =>
  `${n < 0 ? '-' : ''}$${Math.abs(Math.round(n)).toLocaleString()}`

/* Full literal class strings — a constructed class is purged by Tailwind's JIT. */
const TIER_BADGE: Record<string, string> = {
  best: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 ring-emerald-600/20',
  strong: 'bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-400 ring-blue-600/20',
  good: 'bg-violet-50 dark:bg-violet-500/10 text-violet-700 dark:text-violet-400 ring-violet-600/20',
  conservative: 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 ring-amber-600/20',
  skip: 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 ring-red-600/20',
  probation: 'bg-orange-50 dark:bg-orange-500/10 text-orange-700 dark:text-orange-400 ring-orange-600/20',
  untested: 'bg-gray-50 dark:bg-gray-500/10 text-gray-700 dark:text-gray-400 ring-gray-600/20',
}
const TIER_FALLBACK_BADGE =
  'bg-gray-50 dark:bg-gray-500/10 text-gray-700 dark:text-gray-400 ring-gray-600/20'

/*
 * The ladder, transcribed from position_monitor.assess_position() in priority
 * order. CHECKPOINT 2 should consider generating this the way the probability
 * table is generated — the trigger conditions are executable code and this is
 * a second copy of them. Flagged, not silently accepted.
 */
const LADDER = [
  {
    level: 'EMERGENCY',
    dot: 'bg-red-600',
    text: 'text-red-700 dark:text-red-400',
    trigger: 'In the money AND ex-dividend within 3 days',
    evidence: 'Early exercise is close to certain — the dividend is worth more than the remaining time value',
    action: 'Buy back immediately. This is the $400K scenario.',
  },
  {
    level: 'CLOSE NOW',
    dot: 'bg-red-500',
    text: 'text-red-600 dark:text-red-400',
    trigger: 'In the money by any amount · or within 1% with ex-div in 5 days · or under 3 DTE and within 3% · or within 2% with earnings in 2 days',
    evidence: 'Every in-the-money cell of the table above is 64-99%',
    action: 'Buy back today.',
  },
  {
    level: 'CLOSE SOON',
    dot: 'bg-amber-500',
    text: 'text-amber-600 dark:text-amber-400',
    trigger: 'Within 2% of strike with 7+ DTE · or within 3% under 7 DTE (the gamma zone) · or 75% of premium already captured · or ex-div in 3-5 days and within 5%',
    evidence: '3-5% out with 3-7 days left still finishes in the money 15.8% of the time',
    action: 'Close this week. Take the profit while it is still a profit.',
  },
  {
    level: 'WATCH',
    dot: 'bg-blue-500',
    text: 'text-blue-600 dark:text-blue-400',
    trigger: '2-5% from strike with 7+ DTE · or ex-div in 5-10 days and within 5% · or half the premium captured and within 5%',
    evidence: 'Those buckets run 33-57% — a third to over half of them finish in the money',
    action: 'Check daily. No action yet.',
  },
  {
    level: 'SAFE',
    dot: 'bg-emerald-500',
    text: 'text-emerald-600 dark:text-emerald-400',
    trigger: 'Everything else',
    evidence: 'Above 10% out with under 30 days: 0.0-2.3%',
    action: 'Do nothing.',
  },
]

/* Exp 006, Monte Carlo tail table at 14 DTE (480,000 paths). Per share. */
const TAIL_RISK = [
  { position: '3% OTM', closeNow: 3.75, waitP99: 34.44 },
  { position: '1% OTM', closeNow: 5.87, waitP99: 40.51 },
  { position: 'At the money', closeNow: 7.17, waitP99: 43.54 },
  { position: '1% ITM', closeNow: 8.62, waitP99: 46.58 },
]

export default function HowItWorksPage() {
  return (
    <div className="max-w-7xl mx-auto px-6 py-8 space-y-12">

      {/* ═══ 1. The $400K sentence ═══ */}
      <section className="rounded-2xl border bg-card overflow-hidden">
        <div className="px-6 sm:px-10 py-10 max-w-3xl">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            What this is for
          </p>
          <h1 className="mt-3 text-[26px] sm:text-[32px] font-bold tracking-tight text-foreground leading-[1.15]">
            An in-the-money covered call held through an ex-dividend date gets exercised early.
            On 10,000 low-basis shares that is not a bad trade &mdash; it is a six-figure tax
            event you did not choose the year of.
          </h1>
          <p className="mt-5 text-[14px] text-muted-foreground leading-relaxed">
            It happened once, on MSFT, and it cost about $400,000. This tool exists for that one
            failure mode. Everything else on this page &mdash; the strike rules, the income
            figures, the reliability plumbing &mdash; is downstream of making that event
            impossible to miss.
          </p>
          <p className="mt-4 text-[14px] text-muted-foreground leading-relaxed">
            You have sold covered calls for thirty years. The tool does not change the strategy
            and does not claim to pick better strikes than you would. It watches the positions
            every fifteen minutes, and it knows the ex-dividend calendar.
          </p>
        </div>
      </section>

      {/* ═══ 2. The alert ladder, on the real data ═══ */}
      <section className="space-y-4">
        <div>
          <h2 className="text-[20px] font-bold tracking-tight text-foreground">
            The alert ladder, and the table underneath it
          </h2>
          <p className="mt-1.5 text-[13px] text-muted-foreground leading-relaxed max-w-3xl">
            Five levels. Each one exists because of a cell in a table built from{' '}
            {ASSIGNMENT_TABLE_N.toLocaleString()} real option observations, not because a round
            number looked prudent.
          </p>
        </div>

        <AssignmentTable />

        <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
          {LADDER.map((l) => (
            <div key={l.level} className="border-b last:border-b-0 px-5 py-3.5">
              <div className="flex items-baseline gap-2.5">
                <span className={`h-2 w-2 rounded-full flex-shrink-0 ${l.dot}`} />
                <span className={`text-[13px] font-semibold tracking-tight ${l.text}`}>
                  {l.level}
                </span>
                <span className="text-[12px] text-foreground/80">{l.action}</span>
              </div>
              <div className="mt-1.5 ml-[18px] space-y-1">
                <p className="text-[12px] text-muted-foreground leading-relaxed">
                  <span className="font-medium text-foreground/70">Fires when:</span> {l.trigger}
                </p>
                <p className="text-[11px] text-muted-foreground/70 leading-relaxed">
                  {l.evidence}
                </p>
              </div>
            </div>
          ))}
        </div>
        <p className="text-[11px] text-muted-foreground/60 leading-relaxed">
          Transcribed from <code className="text-[10px]">position_monitor.assess_position()</code>,
          evaluated in the order shown &mdash; the first level that matches wins.
        </p>
      </section>

      {/* ═══ 3. Exit discipline ═══ */}
      <section className="space-y-4">
        <div>
          <h2 className="text-[20px] font-bold tracking-tight text-foreground">
            Why we buy back early, and why that is not the obvious answer
          </h2>
          <p className="mt-1.5 text-[13px] text-muted-foreground leading-relaxed max-w-3xl">
            The instinct on a call moving against you is to wait &mdash; the stock may come back,
            and the remaining time value is yours if it does. Across the same{' '}
            {ASSIGNMENT_TABLE_N.toLocaleString()} observations, waiting costs more at every
            moneyness level and every DTE. There is no bucket where patience wins.
          </p>
        </div>

        <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
          <div className="px-5 pt-4 pb-3 border-b">
            <p className="text-[14px] font-semibold text-foreground">
              The tail is the argument
            </p>
            <p className="text-[12px] text-muted-foreground mt-0.5 leading-relaxed">
              Buyback cost per share at 14 days to expiry: closing now, versus the 99th
              percentile of waiting. 480,000 simulated paths (Experiment 006). The averages
              favour closing by $8&ndash;21/share; the tail is where it stops being a preference.
            </p>
          </div>
          <div className="grid grid-cols-4 border-b bg-muted/40">
            {['Position', 'Close now', 'Wait (99th pctl)', 'Difference'].map((h, i) => (
              <div
                key={h}
                className={`px-4 py-2 text-[11px] font-semibold text-muted-foreground ${i === 0 ? '' : 'text-right'}`}
              >
                {h}
              </div>
            ))}
          </div>
          {TAIL_RISK.map((r) => (
            <div key={r.position} className="grid grid-cols-4 border-b last:border-b-0">
              <div className="px-4 py-2.5 text-[12px] font-medium text-foreground">
                {r.position}
              </div>
              <div className="px-4 py-2.5 text-[12px] text-right tabular-nums text-foreground">
                ${r.closeNow.toFixed(2)}
              </div>
              <div className="px-4 py-2.5 text-[12px] text-right tabular-nums text-foreground">
                ${r.waitP99.toFixed(2)}
              </div>
              <div className="px-4 py-2.5 text-[12px] text-right tabular-nums font-semibold text-red-600 dark:text-red-400">
                ${(r.waitP99 - r.closeNow).toFixed(2)}
              </div>
            </div>
          ))}
          <div className="px-5 py-3 border-t bg-muted/20">
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              At 8,000 shares, a $30/share tail is $240,000. You are not buying back to make
              money on the buyback. You are buying out of the tail.
            </p>
          </div>
        </div>

        {/* CHECKPOINT 2: this table becomes a chart (dataviz skill first). */}

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] px-5 py-4">
            <p className="text-[13px] font-semibold text-foreground">Rule: never hold to expiry</p>
            <p className="mt-1.5 text-[12px] text-muted-foreground leading-relaxed">
              Expiry is the one moment you have no options left. Every alert level above resolves
              to closing the position before then, and the income figures on this page are
              measured under that policy &mdash; the copilot&rsquo;s own exits, early buybacks
              included &mdash; not under holding to expiry.
            </p>
          </div>
          <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] px-5 py-4">
            <p className="text-[13px] font-semibold text-foreground">Rule: no stop losses</p>
            <p className="mt-1.5 text-[12px] text-muted-foreground leading-relaxed">
              A short call&rsquo;s price spikes exactly when the stock moves toward the strike, so
              a price-triggered stop buys back at the worst available print and then whipsaws. The
              copilot triggers on the <span className="font-medium text-foreground">position</span>{' '}
              &mdash; distance to strike, days left, ex-dividend proximity &mdash; not on the
              option&rsquo;s price.
            </p>
          </div>
        </div>

        <div className="rounded-xl border border-amber-200 dark:border-amber-500/20 bg-amber-50/50 dark:bg-amber-500/5 px-5 py-4">
          <p className="text-[13px] font-semibold text-amber-800 dark:text-amber-300">
            How we know the exit rule and not the strategy that produced it
          </p>
          <div className="mt-2 space-y-2 text-[12px] text-amber-800/80 dark:text-amber-300/80 leading-relaxed">
            <p>
              This programme did not start with covered calls. Experiment 001 tested bull put
              spreads and found that taking profit at 25% of max dramatically beat holding to
              expiry &mdash; the exit discipline was the whole edge. That result was computed on
              simulated option prices.
            </p>
            <p>
              Experiment 002 re-ran it on real option prices with real bid-ask friction. The win
              rate held up at 78.9% and the strategy still lost{' '}
              <span className="font-medium">$27.87 per trade</span>, with a 100% probability of
              ruin. We stopped trading put spreads that day.
            </p>
            <p>
              What survived the re-test is the narrow part: exit timing dominates, and simulated
              fills flatter every strategy that touches them. Both lessons are why the covered
              call numbers below are split by whether the exit was a real quoted print.
            </p>
          </div>
        </div>
      </section>

      {/* ═══ 4. The entry rules ═══ */}
      <section className="space-y-4">
        <div>
          <h2 className="text-[20px] font-bold tracking-tight text-foreground">
            The entry rules
          </h2>
          <p className="mt-1.5 text-[13px] text-muted-foreground leading-relaxed max-w-3xl">
            Strike distance and expiry window per ticker, walk-forward validated on the first 67%
            of history and tested on the last 33% (Experiment 014), then re-measured on real
            option chains (Experiment 022). Rendered from the same generated file{' '}
            <code className="text-[11px]">/sell</code> reads, so the two pages cannot disagree.
          </p>
        </div>

        <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
          <div className="overflow-x-auto">
            <div className="min-w-[720px]">
              <div
                className="grid border-b bg-muted/40"
                style={{ gridTemplateColumns: '80px 90px 90px 110px 130px 1fr' }}
              >
                {['Ticker', 'Strike', 'Expiry', 'IV gate', 'Expected P&L', 'Status'].map((h) => (
                  <div key={h} className="px-4 py-2 text-[11px] font-semibold text-muted-foreground">
                    {h}
                  </div>
                ))}
              </div>
              {[...LIVE, ...SKIPPED].map(([ticker, s]) => {
                const cfg = TIER_CONFIG[s.tier]
                return (
                  <div
                    key={ticker}
                    className="grid border-b last:border-b-0 items-start"
                    style={{ gridTemplateColumns: '80px 90px 90px 110px 130px 1fr' }}
                  >
                    <div className="px-4 py-3 text-[13px] font-semibold text-foreground">
                      {ticker}
                    </div>
                    <div className="px-4 py-3 text-[12px] tabular-nums text-foreground">
                      {s.otmPct === null ? '—' : `${(s.otmPct * 100).toFixed(0)}% OTM`}
                    </div>
                    <div className="px-4 py-3 text-[12px] tabular-nums text-muted-foreground">
                      {s.minDte === null ? '—' : `${s.minDte}-${s.maxDte}d`}
                    </div>
                    <div className="px-4 py-3 text-[12px] tabular-nums text-muted-foreground">
                      {s.skip ? '—' : `IV rank ≥ ${s.ivThreshold}`}
                    </div>
                    <div className="px-4 py-3">
                      {s.expectedPnl === null ? (
                        <span className="text-[12px] text-muted-foreground/60">not measured</span>
                      ) : (
                        <>
                          <span className="text-[13px] font-semibold tabular-nums text-foreground">
                            {usd(s.expectedPnl)}
                          </span>
                          <span className="text-[10px] text-muted-foreground">/yr/contract</span>
                          {s.pnlRangeLow !== null && (
                            <div className="text-[10px] text-muted-foreground/70 tabular-nums">
                              range {usd(s.pnlRangeLow)}..{usd(s.pnlRangeHigh ?? 0)}
                            </div>
                          )}
                          {s.realFillPnl !== null && s.realFillPnl !== s.expectedPnl && (
                            <div className="text-[10px] text-red-600 dark:text-red-400 tabular-nums">
                              {usd(s.realFillPnl)}/yr real fills only
                            </div>
                          )}
                        </>
                      )}
                    </div>
                    <div className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded-4xl px-2 py-0.5 text-[10px] font-medium ring-1 ring-inset ${
                          TIER_BADGE[s.tier] ?? TIER_FALLBACK_BADGE
                        }`}
                      >
                        {cfg?.label ?? s.tier}
                      </span>
                      {s.maxContracts !== null && (
                        <p className="mt-1 text-[10px] font-medium text-amber-700 dark:text-amber-400">
                          Capped at {s.maxContracts} contracts — {s.maxContractsReason}
                        </p>
                      )}
                      <p className="mt-1 text-[11px] text-muted-foreground leading-relaxed">
                        {s.note}
                      </p>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] px-5 py-4">
            <p className="text-[13px] font-semibold text-foreground">
              The IV gate, and the one optimisation that survived
            </p>
            <p className="mt-1.5 text-[12px] text-muted-foreground leading-relaxed">
              Calls are only sold when the ticker&rsquo;s IV rank is at or above{' '}
              {DEFAULT_IV_THRESHOLD}. Experiment 023 put that rule on trial per ticker on holdout
              data. It beat no gate for AAPL, DIS and KKR; DIS earned its own threshold of 75 and
              is the only ticker that moved. On TMUS the gate{' '}
              <span className="font-medium text-foreground">failed</span> &mdash; it blocks 109
              entries averaging +$48 and keeps the losers &mdash; and it stays live there only
              because loosening a restriction needs its own experiment. It is the first
              pre-registered clause in this programme to pass anything.
            </p>
          </div>
          <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] px-5 py-4">
            <p className="text-[13px] font-semibold text-foreground">What we do not do</p>
            <ul className="mt-1.5 space-y-1.5">
              {[
                'Predict direction. Every predictor tested came out at zero weight (H10); the base rates are near a coin flip. Nothing on this site forecasts the stock.',
                'Use leverage, or sell anything naked. Calls are written only against shares you already hold.',
                'Sell through earnings or an ex-dividend date. Both are calendar bans, not judgement calls.',
                'Size by shares alone. Contracts are capped by measured option liquidity.',
              ].map((t) => (
                <li key={t} className="flex items-start gap-2">
                  <span className="h-1 w-1 rounded-full bg-muted-foreground/50 mt-1.5 flex-shrink-0" />
                  <span className="text-[12px] text-muted-foreground leading-relaxed">{t}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* ═══ 5. The process is the edge ═══ */}
      <section className="space-y-4">
        <div>
          <h2 className="text-[20px] font-bold tracking-tight text-foreground">
            The process is the edge
          </h2>
          <p className="mt-1.5 text-[13px] text-muted-foreground leading-relaxed max-w-3xl">
            There is no analytical edge here and we are not going to claim one. What we have is
            method: hypotheses registered with immutable pass/fail thresholds before the code that
            tests them exists, walk-forward holdouts, and a graveyard that keeps the failures.
            Most of what we tested did not work, and we can show you every failure.
          </p>
        </div>

        {/* CHECKPOINT 2: live counts from signal_graveyard via the API. */}
        <div className="rounded-xl border border-dashed bg-muted/20 px-5 py-4">
          <p className="text-[12px] font-semibold text-muted-foreground">
            CHECKPOINT 2 — graveyard scorecard
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground/70 leading-relaxed">
            N hypotheses registered · M failed · K deployed, read live from{' '}
            <code className="text-[10px]">signal_graveyard</code>. Deliberately left blank rather
            than filled with a plausible constant: a hardcoded count that looks live is the
            precise defect this page is about.
          </p>
        </div>

        <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
          <div className="px-5 pt-4 pb-3 border-b">
            <p className="text-[14px] font-semibold text-foreground">
              Two bugs we found in our own engine, and what they did to our numbers
            </p>
            <p className="text-[12px] text-muted-foreground mt-0.5 leading-relaxed">
              Both were found by us, in our own work, after the numbers had been published on this
              site. Both moved every published figure down.
            </p>
          </div>
          <div className="px-5 py-4 border-b">
            <p className="text-[13px] font-semibold text-foreground">
              The clock bug &mdash; invalidated seven of our own experiments
            </p>
            <p className="mt-1.5 text-[12px] text-muted-foreground leading-relaxed">
              Every backtest from Experiment 007 through 014 computed days-to-expiry against the
              wall clock instead of the simulated date, so each historical observation was scored
              as though it expired that day. Experiment 012&rsquo;s supersede note states it
              plainly: it invalidated every backtest in that range. The strategy grid search that
              used to headline this page is one of them. Those results are kept as the record of
              what was believed, not cited as evidence.
            </p>
          </div>
          <div className="px-5 py-4 border-b">
            <p className="text-[13px] font-semibold text-foreground">
              The fabricated IV rank
            </p>
            <p className="mt-1.5 text-[12px] text-muted-foreground leading-relaxed">
              The simulator returned a hardcoded IV rank of 50.0 whenever it had fewer than ten
              days of history &mdash; which is to say, on every ticker&rsquo;s first nine days.
              The entry gate was therefore being evaluated against a number the engine invented.
            </p>
          </div>
          <div className="px-5 py-4 bg-muted/20">
            <p className="text-[13px] font-semibold text-foreground">
              What that did to one published number
            </p>
            <p className="mt-1.5 text-[12px] text-muted-foreground leading-relaxed">
              AAPL&rsquo;s expected annual P&amp;L per contract went{' '}
              <span className="font-medium text-foreground tabular-nums">$351</span> (broken clock){' '}
              &rarr; <span className="font-medium text-foreground tabular-nums">$299</span>{' '}
              (fabricated IV rank) &rarr;{' '}
              <span className="font-medium text-foreground tabular-nums">$141</span>, with a named
              cause at every step. Three of the four re-measured tickers fell outside their
              pre-registered tolerance. Every correction this programme has made has moved a
              published number down, which is the process working &mdash; and is also the best
              available guide to how much weight to put on any single figure here.
            </p>
          </div>
        </div>
      </section>

      {/* ═══ 6. Reliability ═══ */}
      <section className="space-y-4">
        <div>
          <h2 className="text-[20px] font-bold tracking-tight text-foreground">
            Silence must be impossible
          </h2>
          <p className="mt-1.5 text-[13px] text-muted-foreground leading-relaxed max-w-3xl">
            An alerting tool that dies quietly is worse than no tool, because you stop watching
            the positions yourself. This has already happened here: all seven scheduled jobs were
            switched off for four and a half months while every dashboard stayed green. The
            architecture below is the response to that, and it is stated with its gaps.
          </p>
        </div>

        <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
          {[
            {
              layer: 'Layer 1 — the monitor',
              what: 'GitHub Actions runs the Python assessment engine every 15 minutes through market hours, sends the Pushover alert, and writes a heartbeat.',
              fail: 'If it stops, the heartbeat goes stale and the health endpoint returns 503.',
              state: 'live' as const,
            },
            {
              layer: 'Layer 2 — the inner watchdog',
              what: 'A cron on a Hetzner server polls the health endpoint every 30 minutes during market hours and twice overnight, and pages Discord and Pushover on a bad response or a timeout.',
              fail: 'It alerts on its own failure. Different provider from layer 1, so a GitHub outage cannot silence both.',
              state: 'live' as const,
            },
            {
              layer: 'Layer 3 — the outer watchdog',
              what: 'A Cloudflare Worker polls the same endpoint every 30 minutes from a third provider, one that GitHub cannot disable.',
              fail: 'Nothing watches the watcher — this is accepted residual risk, covered by a monthly fire drill.',
              state: 'not-deployed' as const,
            },
          ].map((l) => (
            <div key={l.layer} className="border-b last:border-b-0 px-5 py-4">
              <div className="flex items-center gap-2">
                <p className="text-[13px] font-semibold text-foreground">{l.layer}</p>
                {l.state === 'not-deployed' && (
                  <span className="inline-flex items-center rounded-4xl px-2 py-0.5 text-[10px] font-medium ring-1 ring-inset bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 ring-amber-600/20">
                    Not deployed yet
                  </span>
                )}
              </div>
              <p className="mt-1.5 text-[12px] text-muted-foreground leading-relaxed">{l.what}</p>
              <p className="mt-1 text-[11px] text-muted-foreground/70 leading-relaxed">
                <span className="font-medium">How you would know it died:</span> {l.fail}
              </p>
            </div>
          ))}
        </div>

        <div className="rounded-xl border border-amber-200 dark:border-amber-500/20 bg-amber-50/50 dark:bg-amber-500/5 px-5 py-4">
          <p className="text-[13px] font-semibold text-amber-800 dark:text-amber-300">
            Stated plainly: two of the three layers are not fully in place
          </p>
          <div className="mt-2 space-y-2 text-[12px] text-amber-800/80 dark:text-amber-300/80 leading-relaxed">
            <p>
              The Cloudflare outer loop is written but not deployed &mdash; it needs a login and
              three secrets. And a server-side 15-minute monitor line was found to have never once
              executed: it guarded on a Docker-network hostname that cannot resolve from the host,
              so the shell short-circuited every run for months. An auditor reading the crontab
              saw monitoring coverage that did not exist, which is worse than seeing none.
            </p>
            <p>
              It is commented out rather than quietly repaired, because the route it called has no
              Pushover credential and would have delivered nothing.
            </p>
          </div>
        </div>

        {/* CHECKPOINT 2: live heartbeat/capture-age widget. */}
        <div className="rounded-xl border border-dashed bg-muted/20 px-5 py-4">
          <p className="text-[12px] font-semibold text-muted-foreground">
            CHECKPOINT 2 — live status widget
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground/70 leading-relaxed">
            Monitor heartbeat age, last chain-capture age, health state, with timestamps — the
            page proving the system is awake as you read it. Blocked on one design question:{' '}
            <code className="text-[10px]">/api/cron/health</code> requires a bearer token today,
            so this needs a public read-only projection of the heartbeat rather than exposing the
            authenticated route. Flagged for the security session.
          </p>
        </div>
      </section>

      {/* ═══ 7. Honest expectations ═══ */}
      <section className="space-y-4">
        <div>
          <h2 className="text-[20px] font-bold tracking-tight text-foreground">
            What this actually earns
          </h2>
          <p className="mt-1.5 text-[13px] text-muted-foreground leading-relaxed max-w-3xl">
            A yield overlay of well under one percent, bought at the price of your upside above
            the strike. Anyone quoting covered-call income of 5&ndash;10% is selling the 3&ndash;5%
            out-of-the-money strikes that the table at the top of this page shows to be the worst
            zone on the board.
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] px-5 py-4">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Simulated exits
            </p>
            <p className="mt-1 text-3xl font-semibold tracking-tight text-foreground tabular-nums">
              {usd(AT_SIZE_SIMULATED)}
              <span className="text-[13px] font-normal text-muted-foreground">/yr</span>
            </p>
            <p className="mt-1.5 text-[11px] text-muted-foreground leading-relaxed">
              Summed across the {LIVE.length} recommendable tickers at{' '}
              {SHARES_PER_TICKER.toLocaleString()} shares each, with the liquidity cap applied to
              the money and not only to the contract count. Experiment 022.
            </p>
          </div>
          <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] px-5 py-4">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Counting only real quoted exits
            </p>
            <p className="mt-1 text-3xl font-semibold tracking-tight text-foreground tabular-nums">
              {usd(AT_SIZE_REAL_FILL)}
              <span className="text-[13px] font-normal text-muted-foreground">/yr</span>
            </p>
            <p className="mt-1.5 text-[11px] text-muted-foreground leading-relaxed">
              The same sum where Exp 022 could separate exits that repriced against a real print
              from exits carried forward. TMUS and KKR turn negative on that basis, which is why
              both are on probation.
            </p>
          </div>
        </div>

        <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] px-5 py-4">
          <p className="text-[13px] font-semibold text-foreground">
            Why both numbers are ranges wearing a point estimate&rsquo;s clothes
          </p>
          <div className="mt-2 space-y-2 text-[12px] text-muted-foreground leading-relaxed">
            <p>
              Experiment 022 ran the identical rules over staggered half-year windows. DIS
              returned <span className="font-medium text-foreground tabular-nums">&minus;77.9%</span>{' '}
              in one half and{' '}
              <span className="font-medium text-foreground tabular-nums">+92.8%</span>{' '}
              in another
              &mdash; a 171 point spread on the same strategy. An annual figure measures the
              regime it was drawn from at least as much as it measures the rules, which is why
              every per-ticker number in the table above carries its chain range.
            </p>
            {NO_PNL_MEASURED.length > 0 && (
              <p>
                {NO_PNL_MEASURED.map(([t]) => t).join(', ')}{' '}
                contributes nothing to either total:
                validated on stock closes only, with no real option history yet, so there is no
                P&amp;L figure to add rather than a zero.
              </p>
            )}
            <p>
              {ON_REAL_PRICES.length} of {LIVE.length} recommendable tickers have been measured on
              real option chains at all. The rest are stock-close validation, which tells you the
              strike distance is defensible and tells you nothing about what the option would have
              filled at.
            </p>
          </div>
        </div>

        <div className="rounded-xl border border-amber-200 dark:border-amber-500/20 bg-amber-50/50 dark:bg-amber-500/5 px-5 py-4">
          <p className="text-[13px] font-semibold text-amber-800 dark:text-amber-300">
            What happens in a crash: we do not have a defensible answer
          </p>
          <div className="mt-2 space-y-2 text-[12px] text-amber-800/80 dark:text-amber-300/80 leading-relaxed">
            <p>
              Four crash scenarios used to sit here, labelled &ldquo;2020 COVID crash&rdquo; and
              &ldquo;2022 bear market&rdquo;, with dollar figures per $100K. All of it is
              withdrawn. They were never historical replays &mdash; Experiment 010 is 10,000 Monte
              Carlo paths per scenario with Black-Scholes pricing, so attaching a year to a row
              presented a model as a memory. It is also inside the clock bug&rsquo;s blast radius,
              and the dollar figures shown appeared nowhere in the experiment at all.
            </p>
            <p>
              What survives is narrower: a covered call collects premium, premium offsets part of
              a drawdown, and it cannot offset much of a large one. Selling the call does not
              increase your downside &mdash; you keep the premium whatever the stock does &mdash;
              but it does not protect you either. How much cushion this specific strategy provides
              is an open question until the stress test is re-run on the corrected engine.
            </p>
          </div>
        </div>
      </section>

      {/* ═══ 8. The daily workflow ═══ */}
      <section className="space-y-4">
        <div>
          <h2 className="text-[20px] font-bold tracking-tight text-foreground">
            What running it looks like
          </h2>
          <p className="mt-1.5 text-[13px] text-muted-foreground leading-relaxed max-w-3xl">
            Two minutes in the morning. The phone does the rest.
          </p>
        </div>
        <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
          {[
            {
              when: 'Morning, ~2 minutes',
              what: 'Open the app. Any position that needs attention is at the top with the level and the reason. If nothing is flagged, close the tab.',
            },
            {
              when: 'During the day',
              what: 'Nothing, unless the phone buzzes. Alerts fire at CLOSE SOON and above; an EMERGENCY repeats every 30 seconds until you acknowledge it.',
            },
            {
              when: 'When an alert fires',
              what: 'The alert names the position, the trigger, and the action. You place the buyback in WellsTrade yourself — there is no trading API and the tool never touches your account.',
            },
            {
              when: 'Every day, without fail',
              what: 'A proof-of-life push arrives whether or not anything happened. If it does not arrive, assume the tool is dead and check the positions yourself. That is the contract.',
            },
          ].map((r) => (
            <div key={r.when} className="border-b last:border-b-0 px-5 py-3.5 sm:flex sm:gap-6">
              <p className="text-[12px] font-semibold text-foreground sm:w-48 sm:flex-shrink-0">
                {r.when}
              </p>
              <p className="mt-1 sm:mt-0 text-[12px] text-muted-foreground leading-relaxed">
                {r.what}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ═══ Methodology ═══ */}
      <section>
        <details className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden group">
          <summary className="px-5 py-4 flex items-center justify-between cursor-pointer hover:bg-accent/40 transition-colors">
            <span className="text-[14px] font-semibold text-foreground">
              Methodology &mdash; how each number on this page was produced
            </span>
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-muted-foreground transition-transform group-open:rotate-180">
              <path d="m6 9 6 6 6-6" />
            </svg>
          </summary>
          <div className="px-5 pb-5 border-t pt-4 space-y-3 text-[12px] text-muted-foreground leading-relaxed">
            <p>
              <span className="font-medium text-foreground">The assignment table.</span>{' '}
              Experiment 006, {ASSIGNMENT_TABLE_N.toLocaleString()} real Databento observations
              bucketed by moneyness and days to expiry. It was independently checked and is one of
              the two artefacts the clock bug did not touch. The page and the alert engine read
              the same generated file.
            </p>
            <p>
              <span className="font-medium text-foreground">The strike rules.</span> Experiment
              014, walk-forward: trained on the first 67% of history, tested on the last 33%,
              verified to be outside the bug&rsquo;s blast radius. When 3% out proved too
              aggressive for TMUS, that test caught it and the strike moved to 15%.
            </p>
            <p>
              <span className="font-medium text-foreground">The income figures.</span> Experiment
              022 re-derived every published per-ticker figure on a corrected engine
              (<code className="text-[11px]">cc_sim.py</code>: real as-of dates, real ex-dividend
              dates, one cohort per trading day) against real Databento option prices, reporting
              the median of 25 staggered chains.
            </p>
            <p>
              <span className="font-medium text-foreground">Repricing coverage.</span> A simulated
              exit is only as good as the quote behind it. Where no real print existed the engine
              carried the last price forward, so each ticker carries the share of exits that
              repriced against a real quote &mdash; 97% for AAPL, 56% for TMUS, 36% for KKR.
              Restricted to real prints, TMUS and KKR are loss-making. Both are on probation for
              exactly that reason.
            </p>
            <p>
              <span className="font-medium text-foreground">Win rate</span>{' '}
              is the share of
              simulated cycles that ended profitable &mdash; premium kept exceeded any buyback
              cost &mdash; under the production copilot policy, with early buybacks included. A
              losing cycle means the buyback cost more than the premium collected; stock P&amp;L
              is not part of these figures.
            </p>
            <p>
              <span className="font-medium text-foreground">Pre-registration</span> with immutable
              pass/fail thresholds began at Experiment 021. The earlier experiments were not
              pre-registered, and several did not survive re-examination.
            </p>
          </div>
        </details>
      </section>

      {/* Fine print */}
      <p className="text-[11px] text-muted-foreground/50 leading-relaxed">
        Every figure on this page is simulated on historical option prices, not a trading record:
        no real-price recommendation from this product has been scored yet, and the first real
        outcomes are due 2026-09-18. Covered calls limit upside in exchange for income and a
        partial downside cushion, and they lose money on individual trades &mdash; 9% of
        AAPL&rsquo;s simulated trades lost, the worst by $971. Past performance, simulated or
        otherwise, does not guarantee future results.
      </p>
    </div>
  )
}
