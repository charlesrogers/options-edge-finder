import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { TICKER_STRATEGIES, TIER_CONFIG } from '@/lib/strategies'

/* ── Static data from experiments ── */

const STRATEGY_TABLE = Object.entries(TICKER_STRATEGIES)
  .filter(([, s]) => s.tier !== 'untested')
  .sort((a, b) => (b[1].expectedPnl ?? 0) - (a[1].expectedPnl ?? 0))

const CRASH_SCENARIOS = [
  { scenario: '2020 COVID crash (-34%)', callLoss: '$0', stockLoss: '-$34,000', netWithCC: '-$31,200', premium: '$2,800' },
  { scenario: '2022 bear market (-25%)', callLoss: '$0', stockLoss: '-$25,000', netWithCC: '-$21,500', premium: '$3,500' },
  { scenario: 'Flash crash (-15%)', callLoss: '$0', stockLoss: '-$15,000', netWithCC: '-$12,800', premium: '$2,200' },
  { scenario: 'Normal correction (-10%)', callLoss: '$0', stockLoss: '-$10,000', netWithCC: '-$7,400', premium: '$2,600' },
]

const TIER_BADGE_COLORS: Record<string, string> = {
  best: 'bg-emerald-500/10 text-emerald-700',
  strong: 'bg-blue-500/10 text-blue-700',
  good: 'bg-violet-500/10 text-violet-700',
  conservative: 'bg-amber-500/10 text-amber-700',
  skip: 'bg-red-500/10 text-red-700',
  untested: 'bg-gray-500/10 text-gray-700',
}

export default function HowItWorksPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-[20px] font-bold">How It Works</h1>
        <p className="text-[12px] text-muted-foreground">
          The evidence behind the system.
        </p>
      </div>

      {/* Hero */}
      <Card className="rounded-xl border-0 bg-gradient-to-br from-emerald-50 to-emerald-100 dark:from-emerald-950/30 dark:to-emerald-900/20 shadow-sm overflow-hidden">
        <CardContent className="py-8 text-center">
          <p className="text-[11px] font-medium tracking-wide text-emerald-700 dark:text-emerald-400 uppercase">
            Backtest Result (Experiment 008)
          </p>
          <p className="mt-2 text-[36px] font-bold text-emerald-700 dark:text-emerald-300 leading-none">
            $27,000
          </p>
          <p className="mt-1 text-[13px] text-emerald-600 dark:text-emerald-400">
            in taxes avoided through covered call income over 3 years
          </p>
        </CardContent>
      </Card>

      {/* With vs Without */}
      <div>
        <h2 className="mb-3 text-[15px] font-semibold">
          With vs Without Copilot
        </h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <Card className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
            <CardHeader className="pb-2">
              <CardTitle className="text-[14px] font-semibold text-red-600">
                Without Copilot
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-[12px] text-muted-foreground">
              <p>Pick random strikes based on gut feel</p>
              <p>No idea when to close — hold until expiry</p>
              <p>Miss ex-dividend dates, get assigned unexpectedly</p>
              <p>Same strategy for every stock regardless of volatility</p>
              <p>No data on what actually works</p>
            </CardContent>
          </Card>

          <Card className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
            <CardHeader className="pb-2">
              <CardTitle className="text-[14px] font-semibold text-emerald-600">
                With Copilot
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-[12px] text-muted-foreground">
              <p>Backtested OTM% and DTE per ticker from 145K observations</p>
              <p>Real-time alerts: SAFE, WATCH, CLOSE_SOON, CLOSE_NOW</p>
              <p>Ex-dividend and earnings tracking built in</p>
              <p>Per-ticker strategy tuned by win rate and expected P&L</p>
              <p>Every recommendation backed by experiment data</p>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Strategy table */}
      <div>
        <h2 className="mb-3 text-[15px] font-semibold">
          Best Strategy Per Ticker (Experiment 008)
        </h2>
        <Card className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="border-b text-left text-[11px] text-muted-foreground">
                    <th className="p-3 font-medium">Ticker</th>
                    <th className="p-3 font-medium">Tier</th>
                    <th className="p-3 font-medium">OTM %</th>
                    <th className="p-3 font-medium">DTE</th>
                    <th className="p-3 font-medium">Expected P&L</th>
                    <th className="p-3 font-medium">Win Rate</th>
                    <th className="p-3 font-medium">Note</th>
                  </tr>
                </thead>
                <tbody>
                  {STRATEGY_TABLE.map(([ticker, s]) => {
                    const tierCfg = TIER_CONFIG[s.tier]
                    return (
                      <tr key={ticker} className="border-b last:border-0">
                        <td className="p-3 font-medium">{ticker}</td>
                        <td className="p-3">
                          <Badge
                            className={cn(
                              'text-[10px]',
                              TIER_BADGE_COLORS[s.tier]
                            )}
                          >
                            {tierCfg?.label ?? s.tier}
                          </Badge>
                        </td>
                        <td className="p-3">
                          {s.otmPct
                            ? `${(s.otmPct * 100).toFixed(0)}%`
                            : '--'}
                        </td>
                        <td className="p-3">
                          {s.minDte && s.maxDte
                            ? `${s.minDte}-${s.maxDte}`
                            : '--'}
                        </td>
                        <td className="p-3">
                          {s.expectedPnl !== null
                            ? `$${s.expectedPnl.toLocaleString()}`
                            : '--'}
                        </td>
                        <td className="p-3">
                          {s.expectedWinRate !== null
                            ? `${s.expectedWinRate}%`
                            : '--'}
                        </td>
                        <td className="p-3 text-[11px] text-muted-foreground max-w-xs">
                          {s.note}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Crash stress test */}
      <div>
        <h2 className="mb-3 text-[15px] font-semibold">
          What Happens in a Crash? (Experiment 010)
        </h2>
        <p className="mb-3 text-[12px] text-muted-foreground">
          Covered calls reduce losses in every scenario. The premium collected
          acts as a buffer. Per $100K portfolio.
        </p>
        <Card className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="border-b text-left text-[11px] text-muted-foreground">
                    <th className="p-3 font-medium">Scenario</th>
                    <th className="p-3 font-medium">Stock Loss</th>
                    <th className="p-3 font-medium">Call Premium</th>
                    <th className="p-3 font-medium">Net with CC</th>
                  </tr>
                </thead>
                <tbody>
                  {CRASH_SCENARIOS.map((row) => (
                    <tr key={row.scenario} className="border-b last:border-0">
                      <td className="p-3 font-medium">{row.scenario}</td>
                      <td className="p-3 text-red-600">{row.stockLoss}</td>
                      <td className="p-3 text-emerald-600">+{row.premium}</td>
                      <td className="p-3 font-medium">{row.netWithCC}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Fine print */}
      <p className="text-[11px] text-muted-foreground/60">
        All data from backtests on historical options data (2021-2024). Past
        performance does not guarantee future results. Covered calls limit upside
        in exchange for income and downside cushion.
      </p>
    </div>
  )
}
