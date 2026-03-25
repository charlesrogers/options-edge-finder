const PROXY_URL = 'https://yfinance-proxy.charlesrogers.workers.dev'

export interface OptionRow {
  contractSymbol: string
  strike: number
  lastPrice: number
  bid: number
  ask: number
  volume: number | null
  openInterest: number | null
  impliedVolatility: number
  inTheMoney: boolean
  expiration?: string
}

/* ── Stock price ── */

export async function getStockPrice(ticker: string): Promise<number | null> {
  try {
    const res = await fetch(`${PROXY_URL}/price/${ticker}`, {
      next: { revalidate: 0 },
    })
    if (!res.ok) return null
    const data = await res.json()
    return data.price ?? null
  } catch {
    return null
  }
}

/* ── Stock info (ex-div, earnings) ── */

export async function getStockInfo(
  ticker: string
): Promise<{ exDividendDate?: number; earningsDate?: number[] }> {
  try {
    const res = await fetch(`${PROXY_URL}/info/${ticker}`, {
      next: { revalidate: 0 },
    })
    if (!res.ok) return {}
    return await res.json()
  } catch {
    return {}
  }
}

/* ── Option chain for a specific expiration ── */

export async function getOptionChain(
  ticker: string,
  expiration: string
): Promise<{ calls: OptionRow[]; puts: OptionRow[] }> {
  try {
    const res = await fetch(
      `${PROXY_URL}/options/${ticker}?expiration=${expiration}`,
      { next: { revalidate: 0 } }
    )
    if (!res.ok) return { calls: [], puts: [] }
    return await res.json()
  } catch {
    return { calls: [], puts: [] }
  }
}

/* ── Available expirations ── */

export async function getExpirations(ticker: string): Promise<string[]> {
  try {
    const res = await fetch(`${PROXY_URL}/expirations/${ticker}`, {
      next: { revalidate: 0 },
    })
    if (!res.ok) return []
    const data = await res.json()
    return data.expirations ?? []
  } catch {
    return []
  }
}
