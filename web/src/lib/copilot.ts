/* ──────────────────────────────────────────────────────────
 * Covered Call Copilot — threshold-based alert system
 * Port of position_monitor.py
 * ────────────────────────────────────────────────────────── */

// ITM probability table from 145,099 real observations
// [pctOtmLow, pctOtmHigh, dteLow, dteHigh, probability]
const ITM_PROBABILITY: [number, number, number, number, number][] = [
  // >10% OTM
  [10, 100, 0, 3, 0.0],
  [10, 100, 3, 7, 0.001],
  [10, 100, 7, 14, 0.013],
  [10, 100, 14, 30, 0.023],
  [10, 100, 30, 60, 0.059],
  // 5-10% OTM
  [5, 10, 0, 3, 0.017],
  [5, 10, 3, 7, 0.082],
  [5, 10, 7, 14, 0.148],
  [5, 10, 14, 30, 0.253],
  [5, 10, 30, 60, 0.38],
  // 3-5% OTM
  [3, 5, 0, 3, 0.04],
  [3, 5, 3, 7, 0.158],
  [3, 5, 7, 14, 0.327],
  [3, 5, 14, 30, 0.423],
  [3, 5, 30, 60, 0.569],
  // 1-3% OTM
  [1, 3, 0, 3, 0.129],
  [1, 3, 3, 7, 0.319],
  [1, 3, 7, 14, 0.465],
  [1, 3, 14, 30, 0.55],
  [1, 3, 30, 60, 0.725],
  // 0-1% OTM
  [0, 1, 0, 3, 0.266],
  [0, 1, 3, 7, 0.491],
  [0, 1, 7, 14, 0.558],
  [0, 1, 14, 30, 0.669],
  [0, 1, 30, 60, 0.775],
  // 0-1% ITM
  [-1, 0, 0, 3, 0.762],
  [-1, 0, 3, 7, 0.705],
  [-1, 0, 7, 14, 0.64],
  [-1, 0, 14, 30, 0.723],
  [-1, 0, 30, 60, 0.807],
  // 1-3% ITM
  [-3, -1, 0, 3, 0.912],
  [-3, -1, 3, 7, 0.847],
  [-3, -1, 7, 14, 0.771],
  [-3, -1, 14, 30, 0.832],
  [-3, -1, 30, 60, 0.877],
  // 3-5% ITM
  [-5, -3, 0, 3, 0.97],
  [-5, -3, 3, 7, 0.947],
  [-5, -3, 7, 14, 0.897],
  [-5, -3, 14, 30, 0.898],
  [-5, -3, 30, 60, 0.909],
  // >5% ITM
  [-100, -5, 0, 3, 0.979],
  [-100, -5, 3, 7, 0.986],
  [-100, -5, 7, 14, 0.967],
  [-100, -5, 14, 30, 0.972],
  [-100, -5, 30, 60, 0.984],
]

export type AlertLevel =
  | 'SAFE'
  | 'WATCH'
  | 'CLOSE_SOON'
  | 'CLOSE_NOW'
  | 'EMERGENCY'

export interface PositionAlert {
  level: AlertLevel
  ticker: string
  strike: number
  dte: number
  pctFromStrike: number
  premiumCapturedPct: number
  pAssignment: number
  buybackCost: number | null
  netPnl: number | null
  reason: string
  action: string
  daysToExDiv: number | null
  daysToEarnings: number | null
}

/* ── Helpers ── */

function daysBetween(a: Date, b: Date): number {
  return Math.ceil((b.getTime() - a.getTime()) / (1000 * 60 * 60 * 24))
}

function lookupItmProb(pctOtm: number, dte: number): number {
  // pctOtm: positive = OTM, negative = ITM (as a percentage, e.g. 3 means 3%)
  for (const [low, high, dteLow, dteHigh, prob] of ITM_PROBABILITY) {
    if (pctOtm >= low && pctOtm < high && dte >= dteLow && dte < dteHigh) {
      return prob
    }
  }
  // Fallback: if beyond our table range
  if (pctOtm < -100) return 0.99
  if (dte >= 60) {
    // Use the 30-60 bucket
    for (const [low, high, , dteHigh, prob] of ITM_PROBABILITY) {
      if (pctOtm >= low && pctOtm < high && dteHigh === 60) {
        return prob
      }
    }
  }
  return 0
}

/* ── Main assessment function ── */

export function assessPosition(params: {
  ticker: string
  strike: number
  expiry: string
  soldPrice: number
  contracts: number
  currentStock: number
  currentOptionAsk: number | null
  exDivDate: string | null
  earningsDate: string | null
}): PositionAlert {
  const {
    ticker,
    strike,
    expiry,
    soldPrice,
    contracts,
    currentStock,
    currentOptionAsk,
    exDivDate,
    earningsDate,
  } = params

  const now = new Date()
  const expiryDate = new Date(expiry + 'T16:00:00')
  const dte = Math.max(0, daysBetween(now, expiryDate))

  // pctFromStrike: positive = OTM (stock below strike), negative = ITM
  const pctFromStrike = ((strike - currentStock) / currentStock) * 100
  const isItm = currentStock >= strike

  // Premium captured
  const buybackCost = currentOptionAsk ?? null
  const premiumCapturedPct =
    buybackCost !== null
      ? Math.max(0, ((soldPrice - buybackCost) / soldPrice) * 100)
      : 0

  const netPnl =
    buybackCost !== null
      ? (soldPrice - buybackCost) * contracts * 100
      : null

  // ITM probability lookup
  // Convert pctFromStrike to the table format: positive = OTM
  const pAssignment = lookupItmProb(-pctFromStrike, dte)

  // Days to ex-div and earnings
  let daysToExDiv: number | null = null
  if (exDivDate) {
    const exDiv = new Date(exDivDate)
    daysToExDiv = daysBetween(now, exDiv)
    if (daysToExDiv < 0) daysToExDiv = null // past
  }

  let daysToEarnings: number | null = null
  if (earningsDate) {
    const earnings = new Date(earningsDate)
    daysToEarnings = daysBetween(now, earnings)
    if (daysToEarnings < 0) daysToEarnings = null // past
  }

  // ── Alert logic (exact port from Python) ──
  let level: AlertLevel = 'SAFE'
  let reason = 'Position is safe'
  let action = 'Hold — let theta work'

  // EMERGENCY: ITM + ex-div within 3 days
  if (isItm && daysToExDiv !== null && daysToExDiv <= 3) {
    level = 'EMERGENCY'
    reason = `ITM + ex-dividend in ${daysToExDiv} day(s). Early assignment risk is extreme.`
    action = 'Buy back immediately — early assignment nearly certain before ex-div.'
  }
  // CLOSE_NOW checks
  else if (isItm) {
    level = 'CLOSE_NOW'
    reason = `Stock is ITM by ${Math.abs(pctFromStrike).toFixed(1)}%.`
    action = 'Buy back now — stock has breached the strike.'
  } else if (
    Math.abs(pctFromStrike) < 1 &&
    daysToExDiv !== null &&
    daysToExDiv <= 5
  ) {
    level = 'CLOSE_NOW'
    reason = `Within 1% of strike + ex-div in ${daysToExDiv} day(s).`
    action = 'Buy back now — dividend assignment risk is high.'
  } else if (dte < 3 && Math.abs(pctFromStrike) < 3) {
    level = 'CLOSE_NOW'
    reason = `Only ${dte} DTE and ${Math.abs(pctFromStrike).toFixed(1)}% from strike.`
    action = 'Buy back now — gamma risk is extreme at expiry.'
  } else if (
    Math.abs(pctFromStrike) < 2 &&
    daysToEarnings !== null &&
    daysToEarnings <= 2
  ) {
    level = 'CLOSE_NOW'
    reason = `Within 2% of strike + earnings in ${daysToEarnings} day(s).`
    action = 'Buy back now — earnings move could breach strike.'
  }
  // CLOSE_SOON checks
  else if (Math.abs(pctFromStrike) < 2 && dte >= 7) {
    level = 'CLOSE_SOON'
    reason = `Within 2% of strike with ${dte} DTE remaining.`
    action = 'Plan to close — getting dangerously close.'
  } else if (Math.abs(pctFromStrike) < 3 && dte < 7) {
    level = 'CLOSE_SOON'
    reason = `Within 3% of strike in gamma zone (${dte} DTE).`
    action = 'Plan to close — gamma accelerates near expiry.'
  } else if (premiumCapturedPct >= 75) {
    level = 'CLOSE_SOON'
    reason = `${premiumCapturedPct.toFixed(0)}% of premium captured.`
    action = 'Consider closing — most of the profit is in hand.'
  } else if (
    daysToExDiv !== null &&
    daysToExDiv <= 5 &&
    Math.abs(pctFromStrike) < 5
  ) {
    level = 'CLOSE_SOON'
    reason = `Ex-div in ${daysToExDiv} day(s) and within 5% of strike.`
    action = 'Plan to close — approaching ex-div with limited buffer.'
  }
  // WATCH checks
  else if (Math.abs(pctFromStrike) >= 2 && Math.abs(pctFromStrike) < 5 && dte >= 7) {
    level = 'WATCH'
    reason = `${Math.abs(pctFromStrike).toFixed(1)}% from strike with ${dte} DTE.`
    action = 'Monitor — still has buffer but worth watching.'
  } else if (
    daysToExDiv !== null &&
    daysToExDiv <= 10 &&
    Math.abs(pctFromStrike) < 5
  ) {
    level = 'WATCH'
    reason = `Ex-div in ${daysToExDiv} day(s) and within 5% of strike.`
    action = 'Monitor — ex-div approaching with moderate buffer.'
  } else if (premiumCapturedPct >= 50 && Math.abs(pctFromStrike) < 5) {
    level = 'WATCH'
    reason = `${premiumCapturedPct.toFixed(0)}% captured and within 5% of strike.`
    action = 'Monitor — good profit captured, consider locking it in.'
  }
  // else SAFE (default)

  return {
    level,
    ticker,
    strike,
    dte,
    pctFromStrike,
    premiumCapturedPct,
    pAssignment,
    buybackCost,
    netPnl,
    reason,
    action,
    daysToExDiv,
    daysToEarnings,
  }
}
