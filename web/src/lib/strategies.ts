export interface TickerStrategy {
  otmPct: number | null
  minDte: number | null
  maxDte: number | null
  tier: 'best' | 'strong' | 'good' | 'conservative' | 'skip' | 'untested'
  expectedPnl: number | null
  expectedWinRate: number | null
  note: string
}

export const TICKER_STRATEGIES: Record<string, TickerStrategy> = {
  TMUS: {
    otmPct: 0.03,
    minDte: 20,
    maxDte: 45,
    tier: 'best',
    expectedPnl: 2276,
    expectedWinRate: 57,
    note: 'Profitable at every OTM%. Best stock for covered calls.',
  },
  KKR: {
    otmPct: 0.03,
    minDte: 20,
    maxDte: 45,
    tier: 'strong',
    expectedPnl: 1796,
    expectedWinRate: 80,
    note: '3yr data, 41 trades. High win rate with close strikes.',
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
    otmPct: 0.05,
    minDte: 20,
    maxDte: 45,
    tier: 'untested',
    expectedPnl: null,
    expectedWinRate: null,
    note: 'Insufficient data.',
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
