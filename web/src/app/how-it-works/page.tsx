import { cn } from '@/lib/utils'
import { TICKER_STRATEGIES, TIER_CONFIG } from '@/lib/strategies'

/* ── Static data from experiments ── */

const STRATEGY_TABLE = Object.entries(TICKER_STRATEGIES)
  .filter(([, s]) => s.tier !== 'untested')
  .sort((a, b) => (b[1].expectedPnl ?? 0) - (a[1].expectedPnl ?? 0))

const CRASH_SCENARIOS = [
  {
    scenario: '2020 COVID crash',
    drop: '-34%',
    severity: 'critical',
    stockLoss: '-$34,000',
    premium: '+$2,800',
    netWithCC: '-$31,200',
  },
  {
    scenario: '2022 bear market',
    drop: '-25%',
    severity: 'high',
    stockLoss: '-$25,000',
    premium: '+$3,500',
    netWithCC: '-$21,500',
  },
  {
    scenario: 'Flash crash',
    drop: '-15%',
    severity: 'medium',
    stockLoss: '-$15,000',
    premium: '+$2,200',
    netWithCC: '-$12,800',
  },
  {
    scenario: 'Normal correction',
    drop: '-10%',
    severity: 'low',
    stockLoss: '-$10,000',
    premium: '+$2,600',
    netWithCC: '-$7,400',
  },
]

const TIER_BADGE: Record<string, string> = {
  best: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 ring-emerald-600/20',
  strong: 'bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-400 ring-blue-600/20',
  good: 'bg-violet-50 dark:bg-violet-500/10 text-violet-700 dark:text-violet-400 ring-violet-600/20',
  conservative: 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 ring-amber-600/20',
  skip: 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 ring-red-600/20',
  untested: 'bg-gray-50 dark:bg-gray-500/10 text-gray-700 dark:text-gray-400 ring-gray-600/20',
}

const SEVERITY_BADGE: Record<string, string> = {
  critical: 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 ring-red-600/20',
  high: 'bg-orange-50 dark:bg-orange-500/10 text-orange-700 dark:text-orange-400 ring-orange-600/20',
  medium: 'bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 ring-amber-600/20',
  low: 'bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-400 ring-blue-600/20',
}

const METRICS = [
  { value: '145K', label: 'Observations', sublabel: 'real options data' },
  { value: '7', label: 'Tickers Tested', sublabel: 'grid searched' },
  { value: '57-100%', label: 'Win Rates', sublabel: 'across tiers' },
  { value: '$27K', label: 'Tax Savings', sublabel: 'over 3 years' },
]

export default function HowItWorksPage() {
  return (
    <div className="space-y-10">
      {/* VERSION MARKER — remove once deploy is confirmed */}
      <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-2 text-[12px] text-amber-800 font-mono">
        Build: 2026-03-25T18:00 · Commit: 01fd81a+marker
      </div>
      {/* ── Hero Section ── */}
      <section className="relative overflow-hidden rounded-2xl border-0">
        {/* Blurred background orbs */}
        <div className="absolute inset-0 -z-10">
          <div className="absolute top-0 left-1/4 w-[500px] h-[400px] rounded-full bg-emerald-500/8 blur-3xl" />
          <div className="absolute bottom-0 right-1/4 w-[300px] h-[300px] rounded-full bg-emerald-400/5 blur-3xl" />
        </div>

        <div className="bg-gradient-to-br from-emerald-50/80 to-emerald-100/60 dark:from-emerald-950/40 dark:to-emerald-900/20 py-14 px-6 text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 text-[12px] font-semibold mb-5">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
            Backtest Result (Experiment 008)
          </div>

          <p className="text-5xl sm:text-6xl font-bold tracking-tight bg-gradient-to-br from-emerald-700 to-emerald-500 dark:from-emerald-300 dark:to-emerald-500 bg-clip-text text-transparent leading-none">
            $27,000
          </p>
          <p className="mt-3 text-[15px] text-emerald-700/80 dark:text-emerald-400/80 max-w-md mx-auto leading-relaxed">
            in taxes avoided through covered call income over 3 years
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
                  'Backtested OTM% and DTE per ticker from 145K observations',
                  'Real-time alerts: SAFE, WATCH, CLOSE_SOON, CLOSE_NOW',
                  'Ex-dividend and earnings tracking built in',
                  'Per-ticker strategy tuned by win rate and expected P&L',
                  'Every recommendation backed by experiment data',
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
        <h2 className="mb-4 text-[15px] font-semibold text-foreground">
          Best Strategy Per Ticker
        </h2>
        <div className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
          {/* Header row */}
          <div className="grid grid-cols-[1fr_80px_70px_70px_90px_70px_1.5fr] gap-2 px-5 py-3 border-b bg-muted/30">
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
                className="grid grid-cols-[1fr_80px_70px_70px_90px_70px_1.5fr] gap-2 px-5 py-3 border-b last:border-0 hover:bg-accent/40 transition-colors items-center"
              >
                <div className="text-[13px] font-semibold text-foreground">{ticker}</div>
                <div>
                  <span className={cn(
                    'inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold ring-1 ring-inset',
                    TIER_BADGE[s.tier]
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
                <div className="text-[12px] font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
                  {s.expectedPnl !== null ? `$${s.expectedPnl.toLocaleString()}` : '--'}
                </div>
                <div className="text-[12px] tabular-nums text-foreground">
                  {s.expectedWinRate !== null ? `${s.expectedWinRate}%` : '--'}
                </div>
                <div className="text-[11px] text-muted-foreground truncate">
                  {s.note}
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* ── Crash Stress Test ── */}
      <section>
        <h2 className="mb-2 text-[15px] font-semibold text-foreground">
          What Happens in a Crash?
        </h2>
        <p className="mb-4 text-[12px] text-muted-foreground">
          Covered calls reduce losses in every scenario. The premium collected acts as a buffer. Per $100K portfolio.
        </p>

        <div className="grid gap-3 sm:grid-cols-2">
          {CRASH_SCENARIOS.map((row) => (
            <div
              key={row.scenario}
              className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden hover:shadow-md hover:shadow-black/[0.06] transition-shadow flex"
            >
              <div className={cn(
                'w-1 flex-shrink-0',
                row.severity === 'critical' ? 'bg-red-500' :
                row.severity === 'high' ? 'bg-orange-500' :
                row.severity === 'medium' ? 'bg-amber-500' : 'bg-blue-500'
              )} />
              <div className="flex-1 px-5 pt-4 pb-4">
                <div className="flex items-center gap-2 mb-3">
                  <h3 className="text-[13px] font-semibold text-foreground">{row.scenario}</h3>
                  <span className={cn(
                    'inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-semibold ring-1 ring-inset',
                    SEVERITY_BADGE[row.severity]
                  )}>
                    {row.drop}
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <div className="text-[16px] font-semibold tracking-tight text-red-600 dark:text-red-400 tabular-nums">
                      {row.stockLoss}
                    </div>
                    <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mt-0.5">
                      Stock Loss
                    </div>
                  </div>
                  <div>
                    <div className="text-[16px] font-semibold tracking-tight text-emerald-600 dark:text-emerald-400 tabular-nums">
                      {row.premium}
                    </div>
                    <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mt-0.5">
                      CC Premium
                    </div>
                  </div>
                  <div>
                    <div className="text-[16px] font-semibold tracking-tight text-foreground tabular-nums">
                      {row.netWithCC}
                    </div>
                    <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mt-0.5">
                      Net Loss
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))}
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
              All data comes from backtests on historical options data (2021-2024) across 7 tickers.
              The strategy grid search (Experiment 008) tested every combination of OTM% (1-10%)
              and DTE (14-60 days) to find the optimal parameters per ticker.
            </p>
            <p>
              Win rate is defined as the percentage of trades where the option expires worthless
              (you keep shares + full premium). Expected P&L is the average net profit per trade
              cycle including assignment losses.
            </p>
            <p>
              Crash scenarios (Experiment 010) model the premium buffer effect during historical
              market drawdowns, assuming a $100K portfolio with continuous covered call writing.
            </p>
          </div>
        </details>
      </section>

      {/* Fine print */}
      <p className="text-[11px] text-muted-foreground/50 leading-relaxed">
        All data from backtests on historical options data (2021-2024). Past performance does not
        guarantee future results. Covered calls limit upside in exchange for income and downside
        cushion.
      </p>
    </div>
  )
}
