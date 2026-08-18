// GENERATED FROM ticker_strategies.py — DO NOT EDIT
//
// Hand-editing this file is how /sell came to show March 2026 numbers months
// after the Python was corrected. Change ticker_strategies.py, then run:
//     python3 scripts/gen_strategies_ts.py
// tests/test_strategies_ts_drift.py fails CI if this file drifts from source.


export interface TickerStrategy {
  otmPct: number | null
  minDte: number | null
  maxDte: number | null
  /** Free-form: unknown tiers must render via the TIER_CONFIG fallback, never crash. */
  tier: string
  expectedPnl: number | null
  expectedWinRate: number | null
  expectedTrades: number | null
  skip: boolean
  /** Per-ticker IV-rank entry gate (Exp 023). Falls back to DEFAULT_IV_THRESHOLD. */
  ivThreshold: number
  /** Hard liquidity cap on contracts, independent of shares owned (Exp 021). */
  maxContracts: number | null
  maxContractsReason: string | null
  /** Spread of the annual figure across staggered start dates (Exp 022). */
  pnlRangeLow: number | null
  pnlRangeHigh: number | null
  /** Same configuration counting only exits that were real Databento prints. */
  realFillPnl: number | null
  repricingCoverage: number | null
  note: string
}

/**
 * Global minimum IV rank before calls may be sold (Exp 009, retained).
 * Exp 023 put the rule on trial per ticker; only DIS earned a different
 * number. Use ivThreshold on the ticker, not this constant, when rendering.
 */
export const DEFAULT_IV_THRESHOLD = 50

export const TICKER_STRATEGIES: Record<string, TickerStrategy> = {
  TMUS: {
    otmPct: 0.15,
    minDte: 20,
    maxDte: 45,
    tier: "probation",
    expectedPnl: 151,
    expectedWinRate: 92,
    expectedTrades: 14,
    skip: false,
    ivThreshold: 50,
    maxContracts: null,
    maxContractsReason: null,
    pnlRangeLow: -99,
    pnlRangeHigh: 976,
    realFillPnl: -81,
    repricingCoverage: 56.0,
    note: "Exp 014: 15% OTM validated (11% test loss rate, walk-forward). Was 3%. Exp 022: $151/yr per contract (chain range -$99..$976), but -$81/yr on real-fill exits only — 56% repricing coverage. Exp 023: the IV rank >= 50 gate FAILS on TMUS (it blocks 109 entries averaging +$48 and keeps the losers); the gate is unevidenced here and stays live only because removing a restriction needs its own experiment.",
  },
  KKR: {
    otmPct: 0.15,
    minDte: 20,
    maxDte: 45,
    tier: "probation",
    expectedPnl: 316,
    expectedWinRate: 63,
    expectedTrades: 17,
    skip: false,
    ivThreshold: 50,
    maxContracts: 7,
    maxContractsReason: "Liquidity cap (Exp 021): 20% of mean daily volume in the 15% OTM / 20-45 DTE strike, which trades a median of 3 contracts a day.",
    pnlRangeLow: null,
    pnlRangeHigh: null,
    realFillPnl: -88,
    repricingCoverage: 36.0,
    note: "Exp 014: 15% OTM validated (0% test loss rate, walk-forward). Was 3%. Exp 021: capped at 7 contracts by liquidity. Exp 022: $316/yr per contract and a 63% win rate (was $386/100%), but -$88/yr on real-fill exits only — 36% repricing coverage.",
  },
  DIS: {
    otmPct: 0.07,
    minDte: 30,
    maxDte: 60,
    tier: "good",
    expectedPnl: 267,
    expectedWinRate: 80,
    expectedTrades: 11,
    skip: false,
    ivThreshold: 75,
    maxContracts: null,
    maxContractsReason: null,
    pnlRangeLow: 51,
    pnlRangeHigh: 590,
    realFillPnl: null,
    repricingCoverage: null,
    note: "Needs more OTM buffer — occasional big moves. Exp 022: $267/yr per contract (chain range $51..$590 depending on start date), 80% win rate, was $822/71% on the broken-clock simulator. Half-year retention swings from -77.9% to +92.8% — the annual figure is a regime, not a rate.",
  },
  AAPL: {
    otmPct: 0.15,
    minDte: 20,
    maxDte: 45,
    tier: "conservative",
    expectedPnl: 141,
    expectedWinRate: 91,
    expectedTrades: 13,
    skip: false,
    ivThreshold: 50,
    maxContracts: null,
    maxContractsReason: null,
    pnlRangeLow: -776,
    pnlRangeHigh: 352,
    realFillPnl: null,
    repricingCoverage: 97.1,
    note: "Widest buffer in the set at 15% OTM. Exp 022 on the fully-corrected engine: $141/yr per contract, 91% win rate, 97.1% repricing coverage — still the most trustworthy numbers here, and the only ticker whose result does not change when synthetic fills are excluded. It is not lossless: 9% of trades lose and the worst single trade in the window was -$971. Start date dominates the average (chain range -$776..$352, i.e. the spread is wider than the median).",
  },
  TXN: {
    otmPct: null,
    minDte: null,
    maxDte: null,
    tier: "skip",
    expectedPnl: 0,
    expectedWinRate: 0,
    expectedTrades: 14,
    skip: true,
    ivThreshold: 50,
    maxContracts: null,
    maxContractsReason: null,
    pnlRangeLow: null,
    pnlRangeHigh: null,
    realFillPnl: null,
    repricingCoverage: null,
    note: "Too volatile. Loses money at every OTM% except 10%.",
  },
  GOOGL: {
    otmPct: 0.1,
    minDte: 20,
    maxDte: 45,
    tier: "probation",
    expectedPnl: null,
    expectedWinRate: 94,
    expectedTrades: 18,
    skip: false,
    ivThreshold: 50,
    maxContracts: null,
    maxContractsReason: null,
    pnlRangeLow: null,
    pnlRangeHigh: null,
    realFillPnl: null,
    repricingCoverage: null,
    note: "Exp 014: 10% OTM validated on stock closes (6% test loss rate, walk-forward). Exp 021: still no real option data (5 days owned) — probation until the chain capture accrues a year, review ~2027-02.",
  },
  AMZN: {
    otmPct: 0.05,
    minDte: 20,
    maxDte: 45,
    tier: "skip",
    expectedPnl: null,
    expectedWinRate: null,
    expectedTrades: 0,
    skip: true,
    ivThreshold: 50,
    maxContracts: null,
    maxContractsReason: null,
    pnlRangeLow: null,
    pnlRangeHigh: null,
    realFillPnl: null,
    repricingCoverage: null,
    note: "No option data was ever purchased. Exp 021 failed AMZN at 15% OTM (22.9% test loss rate vs a 10% gate) and it was live at a more aggressive 5% — skip pending revalidation on real option prices.",
  },
  MSFT: {
    otmPct: 0.15,
    minDte: 20,
    maxDte: 45,
    tier: "skip",
    expectedPnl: null,
    expectedWinRate: null,
    expectedTrades: 0,
    skip: true,
    ivThreshold: 50,
    maxContracts: null,
    maxContractsReason: null,
    pnlRangeLow: null,
    pnlRangeHigh: null,
    realFillPnl: null,
    repricingCoverage: null,
    note: "No option data was ever purchased. Exp 021 failed MSFT at 15% OTM (20.0% test loss rate vs a 10% gate) — skip pending revalidation on real option prices.",
  },
}

export interface TierConfig {
  label: string
  icon: string
  color: string
  bg: string
}

export const TIER_CONFIG: Record<string, TierConfig> = {
  best: { label: "Best", icon: "🟢", color: "#065f46", bg: "#d1fae5" },
  strong: { label: "Strong", icon: "🔵", color: "#1e40af", bg: "#dbeafe" },
  good: { label: "Good", icon: "🟣", color: "#7c3aed", bg: "#ede9fe" },
  conservative: { label: "Conservative", icon: "🟡", color: "#92400e", bg: "#fef3c7" },
  skip: { label: "Skip", icon: "🔴", color: "#991b1b", bg: "#fee2e2" },
  probation: { label: "Probation", icon: "🟠", color: "#92400e", bg: "#fef3c7" },
  untested: { label: "Untested", icon: "⚪", color: "#6b7280", bg: "#f3f4f6" },
}
