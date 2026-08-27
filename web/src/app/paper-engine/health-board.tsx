'use client'

import { useEffect, useState } from 'react'

/*
 * Reads /api/paper-engine/health and renders it. The route reports; nothing
 * here alerts, and nothing here recomputes a threshold — every number and every
 * threshold on this page is served by the API, which reads them from the
 * engine's own rows and the committed thresholds.json. A TS mirror of a Python
 * truth is production drift by definition (tasks/lessons.md 2026-08-18).
 */

type Json = Record<string, any>

function Card({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle?: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-xl border bg-card shadow-sm shadow-black/[0.04] overflow-hidden">
      <header className="px-5 py-4 border-b">
        <h2 className="text-[15px] font-semibold">{title}</h2>
        {subtitle && <p className="text-[12px] text-muted-foreground mt-1">{subtitle}</p>}
      </header>
      <div className="p-5">{children}</div>
    </section>
  )
}

function Pill({ tone, children }: { tone: 'ok' | 'warn' | 'bad' | 'muted'; children: React.ReactNode }) {
  const cls = {
    ok: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
    warn: 'bg-amber-500/10 text-amber-600 dark:text-amber-400',
    bad: 'bg-red-500/10 text-red-600 dark:text-red-400',
    muted: 'bg-muted text-muted-foreground',
  }[tone]
  return (
    <span className={`inline-flex items-center rounded-4xl px-2 py-0.5 text-[10px] font-medium ${cls}`}>
      {children}
    </span>
  )
}

function Table({ head, children }: { head: string[]; children: React.ReactNode }) {
  // Wide tables scroll inside their own container; the page body never scrolls
  // sideways.
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12px]">
        <thead>
          <tr className="text-left text-muted-foreground border-b">
            {head.map((h) => (
              <th key={h} className="font-medium py-2 pr-4 whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  )
}

function money(v: number | null | undefined) {
  if (v === null || v === undefined) return '—'
  return `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

/* Retention never appears without its numerator and denominator. */
function Retention({ r }: { r: Json | undefined }) {
  if (!r) return <>—</>
  if (r.pct === null) {
    return <span className="text-muted-foreground">undefined ({r.note})</span>
  }
  return (
    <span className={r.numeratorNegative ? 'text-red-600 dark:text-red-400' : ''}>
      {r.pct}% <span className="text-muted-foreground">({money(r.keptUsd)} / {money(r.collectedUsd)})</span>
    </span>
  )
}

export function HealthBoard() {
  const [data, setData] = useState<Json | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch('/api/paper-engine/health')
      .then(async (r) => {
        const j = await r.json()
        if (cancelled) return
        if (!r.ok || j.error) setError(j.error ?? `HTTP ${r.status}`)
        else setData(j)
      })
      .catch((e) => !cancelled && setError(String(e)))
    return () => {
      cancelled = true
    }
  }, [])

  if (error) {
    // Loudly broken, never a blank dashboard. "The engine has done nothing" and
    // "we cannot read the engine's tables" must never look the same.
    return (
      <div className="rounded-xl border border-red-500/40 bg-red-500/5 p-5">
        <h2 className="text-[15px] font-semibold text-red-600 dark:text-red-400">
          Engine health is UNREADABLE
        </h2>
        <p className="text-[12px] text-muted-foreground mt-2">
          This is not &ldquo;no activity&rdquo;. Nothing on this page can be trusted until it
          resolves.
        </p>
        <pre className="text-[11px] mt-3 whitespace-pre-wrap">{error}</pre>
      </div>
    )
  }

  if (!data) return <p className="text-[13px] text-muted-foreground">Loading engine health…</p>

  const i = data.integrity ?? {}
  const hb = i.heartbeat ?? {}
  const arms = ['A', 'B', 'C', 'D'] as const
  const armNames: Record<string, string> = {
    A: 'A — full strategy (H40)',
    B: 'B — hold to expiry (H41)',
    C: 'C — no IV gate (H42)',
    D: 'D — take-profit only (H43)',
  }

  return (
    <>
      <div>
        <h1 className="text-[20px] font-bold">Paper engine</h1>
        <p className="text-[12px] text-muted-foreground mt-1">
          Forward validation of the production strategy, in four pre-registered arms, against
          real quotes captured at the moment each decision is made. No real orders — this
          engine has no broker credentials and imports no broker library.
        </p>
      </div>

      {/* ---------------------------------------------------------- band 1 */}
      <Card
        title="1 · Engine integrity"
        subtitle="Can the numbers below this be trusted? Read this band first — a P&L figure above a broken collector reads as a result."
      >
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <p className="text-[11px] text-muted-foreground">Collector heartbeat</p>
            <p className="text-[13px] font-medium mt-1">
              {hb.stale ? (
                <Pill tone="bad">STALE</Pill>
              ) : hb.marketOpen ? (
                <Pill tone="ok">FRESH</Pill>
              ) : (
                <Pill tone="muted">MARKET CLOSED</Pill>
              )}{' '}
              {hb.ageMinutes !== null && hb.ageMinutes !== undefined
                ? `${hb.ageMinutes} min old`
                : 'never run'}
            </p>
            <p className="text-[11px] text-muted-foreground/70 mt-1">
              Calendar-aware: staleness only alarms during a session.
            </p>
          </div>
          <div>
            <p className="text-[11px] text-muted-foreground">Last run</p>
            <p className="text-[13px] font-medium mt-1">
              {hb.lastOk === null ? '—' : hb.lastOk ? <Pill tone="ok">OK</Pill> : <Pill tone="bad">NOT OK</Pill>}
              {hb.marketClosedLastRun && <span className="ml-2 text-[11px] text-muted-foreground">market closed</span>}
            </p>
            <p className="text-[11px] text-muted-foreground/70 mt-1 font-mono">
              {hb.engineVersion ?? '—'} · {String(hb.engineCommitSha ?? '—').slice(0, 8)}
            </p>
          </div>
          <div>
            <p className="text-[11px] text-muted-foreground">
              Assessed with no usable option quote
            </p>
            <p className="text-[13px] font-medium mt-1">
              {i.assessedWithoutAsk ?? '—'}
            </p>
            <p className="text-[11px] text-muted-foreground/70 mt-1">
              On a missing ask, <code>premium_captured_pct</code> defaults to 0 and the
              TP-75/TP-50 rungs silently cannot fire. Forward-time twin of the DTE bug.
            </p>
          </div>
        </div>

        <h3 className="text-[14px] font-semibold mt-6 mb-2">Quote coverage</h3>
        <Table head={['Ticker', 'Captured', 'Usable', 'Stale (carried forward)', 'Coverage']}>
          {Object.entries(i.quoteCoverage ?? {}).map(([t, c]: [string, any]) => (
            <tr key={t} className="border-b last:border-0">
              <td className="py-2 pr-4 font-medium">{t}</td>
              <td className="py-2 pr-4">{c.captured}</td>
              <td className="py-2 pr-4">{c.usable}</td>
              <td className="py-2 pr-4">{c.stale}</td>
              <td className="py-2 pr-4">{c.pct === null ? '—' : `${c.pct}%`}</td>
            </tr>
          ))}
          {Object.keys(i.quoteCoverage ?? {}).length === 0 && (
            <tr>
              <td colSpan={5} className="py-3 text-muted-foreground">
                No quotes captured yet.
              </td>
            </tr>
          )}
        </Table>

        <h3 className="text-[14px] font-semibold mt-6 mb-2">Clause reachability</h3>
        <p className="text-[11px] text-muted-foreground mb-2">
          Lifetime exit-clause fire counts per arm. A clause sitting at zero across hundreds
          of observations is presumed <em>unwired</em>, not unlucky — zeros are shown, never
          filtered out.
        </p>
        <Table head={['Clause', ...arms.map((a) => `Arm ${a}`)]}>
          {Object.entries(i.clauseFires ?? {}).map(([clause, per]: [string, any]) => (
            <tr key={clause} className="border-b last:border-0">
              <td className="py-2 pr-4 font-mono text-[11px]">{clause}</td>
              {arms.map((a) => (
                <td key={a} className="py-2 pr-4">
                  {per[a] ?? <span className="text-muted-foreground/50">0</span>}
                </td>
              ))}
            </tr>
          ))}
          {Object.keys(i.clauseFires ?? {}).length === 0 && (
            <tr>
              <td colSpan={5} className="py-3 text-muted-foreground">
                No exits yet — the reachability audit is non-binding until there are
                observations behind it.
              </td>
            </tr>
          )}
        </Table>
      </Card>

      {/* ---------------------------------------------------------- band 2 */}
      <Card
        title="2 · Strategy health"
        subtitle="Every figure twice — all fills and the real-fill subset. Where the two disagree in sign, the real-fill number is the result."
      >
        <Table
          head={[
            'Arm',
            'Cycles (all / real)',
            'Net P&L all',
            'Net P&L real-fill',
            'Retention (real-fill)',
            'Commissions',
            'Spread cost',
            'Modelled assignments',
            'Worst cycle',
          ]}
        >
          {arms.map((a) => {
            const s = data.strategy?.[a]
            if (!s) return null
            return (
              <tr key={a} className="border-b last:border-0">
                <td className="py-2 pr-4 font-medium whitespace-nowrap">{armNames[a]}</td>
                <td className="py-2 pr-4">
                  {s.all.cycles} / {s.realFill.cycles}
                </td>
                <td className="py-2 pr-4">{money(s.all.netPnl)}</td>
                <td className="py-2 pr-4 font-medium">{money(s.realFill.netPnl)}</td>
                <td className="py-2 pr-4">
                  <Retention r={s.realFill.retention} />
                </td>
                <td className="py-2 pr-4">{money(s.all.commissions)}</td>
                <td className="py-2 pr-4">{money(s.all.spreadCost)}</td>
                <td className="py-2 pr-4">
                  {s.all.modeledAssignments}{' '}
                  {s.all.modeledAssignments > 0 && <Pill tone="warn">MODELLED</Pill>}
                </td>
                <td className="py-2 pr-4">{money(s.all.worstCycle)}</td>
              </tr>
            )
          })}
        </Table>

        <h3 className="text-[14px] font-semibold mt-6 mb-2">Paired differences</h3>
        <p className="text-[11px] text-muted-foreground mb-2">
          Matched on (ticker, cycle) so both arms lived the same market path. Assignment
          counts are shown beside every difference and are not optional: being called away is
          the tax event the copilot exists to prevent, and option-leg P&amp;L cannot see it.
        </p>
        <Table head={['Comparison', 'Paired cycles', 'Mean Δ per cycle', 'Assignments']}>
          {[
            ['A − B (copilot value)', data.paired?.AminusB],
            ['A − D (defensive exit cost)', data.paired?.AminusD],
          ].map(([label, p]: any) => (
            <tr key={label} className="border-b last:border-0">
              <td className="py-2 pr-4 font-medium">{label}</td>
              <td className="py-2 pr-4">{p?.n ?? 0}</td>
              <td className="py-2 pr-4">{money(p?.meanDelta)}</td>
              <td className="py-2 pr-4">
                {p?.assignments
                  ? Object.entries(p.assignments)
                      .map(([k, v]) => `${k}: ${v}`)
                      .join(' · ')
                  : '—'}
              </td>
            </tr>
          ))}
        </Table>

        <h3 className="text-[14px] font-semibold mt-6 mb-2">Trade ledger</h3>
        <p className="text-[11px] text-muted-foreground mb-2">
          The auditable receipt. Every fill carries the quote at <em>alert time</em> and the
          quote at <em>fill time</em>, so you can check that we sold at the bid, bought back
          at the ask, and waited the fifteen minutes we said we waited.
        </p>
        <Table
          head={[
            'Arm',
            'Ticker',
            'Cycle',
            'Status',
            'Contract',
            'Entry alert bid/ask',
            'Entry fill bid/ask',
            'Entry @',
            'Lat.',
            'Exit alert bid/ask',
            'Exit fill bid/ask',
            'Exit @',
            'Lat.',
            'Clause',
            'Spread',
            'Comm.',
            'Net',
            'Real fill',
          ]}
        >
          {(data.ledger ?? []).slice(0, 100).map((t: Json) => (
            <tr key={`${t.arm}-${t.ticker}-${t.cycle_seq}`} className="border-b last:border-0">
              <td className="py-2 pr-4">{t.arm}</td>
              <td className="py-2 pr-4 font-medium">{t.ticker}</td>
              <td className="py-2 pr-4">{t.cycle_seq}</td>
              <td className="py-2 pr-4">{t.status}</td>
              <td className="py-2 pr-4 font-mono text-[10px]">{t.contract_symbol}</td>
              <td className="py-2 pr-4">
                {t.entry_decision_bid ?? '—'} / {t.entry_decision_ask ?? '—'}
              </td>
              <td className="py-2 pr-4">
                {t.entry_fill_bid ?? '—'} / {t.entry_fill_ask ?? '—'}
              </td>
              <td className="py-2 pr-4 font-medium">{t.entry_fill_price ?? '—'}</td>
              <td className="py-2 pr-4">
                {t.entry_latency_min ?? '—'}
                {t.entry_overnight_gap && <Pill tone="warn">gap</Pill>}
              </td>
              <td className="py-2 pr-4">
                {t.exit_decision_bid ?? '—'} / {t.exit_decision_ask ?? '—'}
              </td>
              <td className="py-2 pr-4">
                {t.exit_fill_bid ?? '—'} / {t.exit_fill_ask ?? '—'}
              </td>
              <td className="py-2 pr-4 font-medium">{t.exit_fill_price ?? '—'}</td>
              <td className="py-2 pr-4">
                {t.exit_latency_min ?? '—'}
                {t.exit_overnight_gap && <Pill tone="warn">gap</Pill>}
              </td>
              <td className="py-2 pr-4 font-mono text-[10px]">{t.exit_clause ?? '—'}</td>
              <td className="py-2 pr-4">{money(t.spread_cost_total)}</td>
              <td className="py-2 pr-4">{money(t.commissions_total)}</td>
              <td className="py-2 pr-4 font-medium">{money(t.net_pnl)}</td>
              <td className="py-2 pr-4">
                {t.status === 'closed' ? (
                  t.real_fill ? (
                    <Pill tone="ok">real</Pill>
                  ) : (
                    <Pill tone="warn">stale</Pill>
                  )
                ) : (
                  '—'
                )}
              </td>
            </tr>
          ))}
          {(data.ledger ?? []).length === 0 && (
            <tr>
              <td colSpan={18} className="py-3 text-muted-foreground">
                No trades yet.
              </td>
            </tr>
          )}
        </Table>
      </Card>

      {/* ---------------------------------------------------------- band 3 */}
      <Card
        title="3 · Pre-registration and kill switches"
        subtitle="Committed before the data existed. The engine refuses to run if the pre-registration document's hash has moved."
      >
        <Table head={['Switch', 'State', 'Value', 'Threshold', 'Class', 'Since']}>
          {Object.entries(data.kills ?? {}).map(([key, k]: [string, any]) => (
            <tr key={key} className="border-b last:border-0">
              <td className="py-2 pr-4 font-mono text-[11px]">{key}</td>
              <td className="py-2 pr-4">
                {k.state === 'TRIGGERED' ? (
                  <Pill tone="bad">TRIGGERED</Pill>
                ) : k.state === 'DISARMED' ? (
                  <Pill tone="muted">DISARMED</Pill>
                ) : (
                  <Pill tone="ok">ARMED</Pill>
                )}
              </td>
              <td className="py-2 pr-4">{String(k.value ?? '—')}</td>
              <td className="py-2 pr-4">{String(k.threshold ?? '—')}</td>
              <td className="py-2 pr-4">
                {k.kind === 'engine_integrity' ? 'integrity pause' : 'strategy kill'}
              </td>
              <td className="py-2 pr-4 text-muted-foreground">{String(k.at ?? '').slice(0, 16)}</td>
            </tr>
          ))}
          {Object.keys(data.kills ?? {}).length === 0 && (
            <tr>
              <td colSpan={6} className="py-3 text-muted-foreground">
                No kill-switch state recorded yet — the board populates on the first tick.
              </td>
            </tr>
          )}
        </Table>

        <div className="mt-6 rounded-lg border bg-muted/40 p-4 space-y-2">
          <h3 className="text-[13px] font-semibold">How to read this page</h3>
          <ul className="text-[11px] text-muted-foreground space-y-1 list-disc pl-4">
            <li>
              <strong>Synthetic backfill (the old paper_trades tracker):</strong> trust it for
              nothing. 444 of its 452 scored rows are Black-Scholes fabrications. Its tables
              are unjoinable from this engine&apos;s by construction.
            </li>
            <li>
              <strong>Backtest, all fills:</strong> mechanism counts and relative comparisons
              only. Never an absolute P&amp;L or a per-ticker sign.
            </li>
            <li>
              <strong>Backtest, real-fill subset:</strong> sign and rough magnitude; this is
              what the kill thresholds were derived from.
            </li>
            <li>
              <strong>This engine, forward:</strong> the only source that can ever justify
              &ldquo;it works&rdquo; — and only past the cycle floors in the pre-registration.
            </li>
            <li>
              It <strong>falsifies fast and confirms slowly.</strong> Fills here are strictly
              worse than achievable, so a negative verdict is stronger than one from real
              trading. Six months is one regime draw, not proof of an edge.
            </li>
            <li>
              A kill switch that trips <strong>changes nothing in production</strong>. It halts
              a paper arm and sends a message; it never edits{' '}
              <code>ticker_strategies.py</code>.
            </li>
          </ul>
        </div>
      </Card>

      <p className="text-[11px] text-muted-foreground/70">
        Generated {String(data.generatedAt).slice(0, 19)}Z · report-only surface, no alerting
      </p>
    </>
  )
}
