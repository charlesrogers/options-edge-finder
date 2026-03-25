import { supabase, type TradeRow } from '@/lib/supabase'
import { getStockPrice, getStockInfo, getOptionChain } from '@/lib/yf-proxy'
import { assessPosition, type PositionAlert } from '@/lib/copilot'

export const dynamic = 'force-dynamic'

export async function GET() {
  // 1. Fetch all open trades
  const { data: trades, error } = await supabase
    .from('trades')
    .select('*')
    .eq('status', 'open')

  if (error) {
    return Response.json({ error: error.message }, { status: 500 })
  }

  if (!trades || trades.length === 0) {
    return Response.json([])
  }

  // 2. Get unique tickers
  const tickers = [...new Set((trades as TradeRow[]).map((t) => t.ticker))]

  // 3. Fetch current prices + info for each ticker in parallel
  const priceMap = new Map<string, number>()
  const infoMap = new Map<
    string,
    { exDividendDate?: number; earningsDate?: number[] }
  >()

  await Promise.all(
    tickers.map(async (ticker) => {
      const [price, info] = await Promise.all([
        getStockPrice(ticker),
        getStockInfo(ticker),
      ])
      if (price !== null) priceMap.set(ticker, price)
      infoMap.set(ticker, info)
    })
  )

  // 4. For each trade, try to get current option ask price
  const alerts: PositionAlert[] = []

  for (const trade of trades as TradeRow[]) {
    const currentStock = priceMap.get(trade.ticker)
    if (currentStock === undefined) {
      console.log(`[copilot] No price for ${trade.ticker}, skipping`)
      continue
    }

    // Try to get option chain for the buyback cost
    let currentOptionAsk: number | null = null
    try {
      const chain = await getOptionChain(trade.ticker, trade.expiry)
      const matchingCall = chain.calls.find(
        (c) => Math.abs(c.strike - trade.strike) < 0.01
      )
      if (matchingCall) {
        currentOptionAsk = matchingCall.ask > 0 ? matchingCall.ask : null
      }
    } catch {
      // Option chain fetch failed — continue without buyback cost
    }

    // Convert info dates
    const info = infoMap.get(trade.ticker) ?? {}
    const exDivDate = info.exDividendDate
      ? new Date(info.exDividendDate * 1000).toISOString().split('T')[0]
      : null
    const earningsDate =
      info.earningsDate && info.earningsDate.length > 0
        ? new Date(info.earningsDate[0] * 1000).toISOString().split('T')[0]
        : null

    const alert = assessPosition({
      ticker: trade.ticker,
      strike: trade.strike,
      expiry: trade.expiry,
      soldPrice: trade.sold_price,
      contracts: trade.contracts,
      currentStock,
      currentOptionAsk,
      exDivDate,
      earningsDate,
    })

    alerts.push({ ...alert, tradeId: trade.id } as PositionAlert & {
      tradeId: number
    })
  }

  // Sort: most urgent first
  const levelOrder: Record<string, number> = {
    EMERGENCY: 0,
    CLOSE_NOW: 1,
    CLOSE_SOON: 2,
    WATCH: 3,
    SAFE: 4,
  }
  alerts.sort(
    (a, b) => (levelOrder[a.level] ?? 5) - (levelOrder[b.level] ?? 5)
  )

  return Response.json(alerts)
}
