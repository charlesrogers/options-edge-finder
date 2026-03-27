export interface TickerStrategy {
  otmPct: number | null
  minDte: number | null
  maxDte: number | null
  tier: 'best' | 'strong' | 'good' | 'conservative' | 'skip' | 'untested'
  expectedPnl: number | null
  expectedWinRate: number | null
  note: string
}

/** Minimum IV rank to recommend selling (Experiment 009: +204% P&L improvement) */
export const DEFAULT_IV_THRESHOLD = 50

export const TICKER_STRATEGIES: Record<string, TickerStrategy> = {
  TMUS: {
    otmPct: 0.15,
    minDte: 20,
    maxDte: 45,
    tier: 'good',
    expectedPnl: 447,
    expectedWinRate: 89,
    note: 'Exp 014: 15% OTM validated (11% test loss rate, walk-forward).',
  },
  KKR: {
    otmPct: 0.15,
    minDte: 20,
    maxDte: 45,
    tier: 'good',
    expectedPnl: 386,
    expectedWinRate: 100,
    note: 'Exp 014: 15% OTM validated (0% test loss rate, walk-forward).',
  },
  DIS: {
    otmPct: 0.07,
    minDte: 30,
    maxDte: 60,
    tier: 'good',
    expectedPnl: 822,
    expectedWinRate: 71,
    note: 'Needs more OTM buffer — occasional big moves.',
  },
  AAPL: {
    otmPct: 0.15,
    minDte: 20,
    maxDte: 45,
    tier: 'conservative',
    expectedPnl: 351,
    expectedWinRate: 100,
    note: '100% win rate at 15% OTM. Tiny premium but never loses.',
  },
  TXN: {
    otmPct: null,
    minDte: null,
    maxDte: null,
    tier: 'skip',
    expectedPnl: 0,
    expectedWinRate: 0,
    note: 'Too volatile. Loses money at every OTM%.',
  },
  GOOGL: {
    otmPct: 0.10,
    minDte: 20,
    maxDte: 45,
    tier: 'good',
    expectedPnl: null,
    expectedWinRate: 94,
    note: 'Exp 014: 10% OTM validated (6% test loss rate, walk-forward).',
  },
  AMZN: {
    otmPct: 0.05,
    minDte: 20,
    maxDte: 45,
    tier: 'untested',
    expectedPnl: null,
    expectedWinRate: null,
    note: 'No option data.',
  },
}

export const TIER_CONFIG: Record<
  string,
  { color: string; label: string; icon: string }
> = {
  best: { color: 'emerald', label: 'Best', icon: 'green' },
  strong: { color: 'blue', label: 'Strong', icon: 'blue' },
  good: { color: 'violet', label: 'Good', icon: 'violet' },
  conservative: { color: 'amber', label: 'Conservative', icon: 'amber' },
  skip: { color: 'red', label: 'Skip', icon: 'red' },
  untested: { color: 'gray', label: 'Untested', icon: 'gray' },
}
