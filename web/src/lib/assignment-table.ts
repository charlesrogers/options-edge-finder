// GENERATED FROM position_monitor.py — DO NOT EDIT
//
// The empirical assignment-probability table: Experiment 006, 145,099 real
// Databento option observations, P(finish ITM) by moneyness x days-to-expiry.
// Every alert threshold in the copilot is justified by a cell in here, so the
// page that shows it must show the same numbers the alert engine uses.
//
// Change position_monitor.py, then run:
//     python3 scripts/gen_assignment_table_ts.py
// tests/test_assignment_table_ts_drift.py fails CI if this file drifts.

/** Total real option observations behind the table (Experiment 006). */
export const ASSIGNMENT_TABLE_N = 145099

export interface MoneynessBand {
  /** Lower bound, percent from strike. Positive = OTM. */
  low: number
  /** Upper bound, exclusive. */
  high: number
  label: string
  /** True when the stock is already through the strike. */
  itm: boolean
}

export const MONEYNESS_BANDS: MoneynessBand[] = [
  { low: 10, high: 100, label: ">10% OTM", itm: false },
  { low: 5, high: 10, label: "5-10% OTM", itm: false },
  { low: 3, high: 5, label: "3-5% OTM", itm: false },
  { low: 1, high: 3, label: "1-3% OTM", itm: false },
  { low: 0, high: 1, label: "0-1% OTM", itm: false },
  { low: -1, high: 0, label: "0-1% ITM", itm: true },
  { low: -3, high: -1, label: "1-3% ITM", itm: true },
  { low: -5, high: -3, label: "3-5% ITM", itm: true },
  { low: -100, high: -5, label: ">5% ITM", itm: true },
]

export interface DteBucket {
  low: number
  /** Upper bound, exclusive. */
  high: number
  label: string
}

export const DTE_BUCKETS: DteBucket[] = [
  { low: 0, high: 3, label: "0-3" },
  { low: 3, high: 7, label: "3-7" },
  { low: 7, high: 14, label: "7-14" },
  { low: 14, high: 30, label: "14-30" },
  { low: 30, high: 60, label: "30-60" },
]

/**
 * P(finish ITM) indexed [moneyness label][DTE label]. A missing cell means
 * position_monitor.py has no observation for that combination — render it
 * blank rather than inventing a zero.
 */
export const ASSIGNMENT_PROBABILITY: Record<string, Record<string, number>> = {
  ">10% OTM": {
    "0-3": 0.0,
    "3-7": 0.001,
    "7-14": 0.013,
    "14-30": 0.023,
    "30-60": 0.059,
  },
  "5-10% OTM": {
    "0-3": 0.017,
    "3-7": 0.082,
    "7-14": 0.148,
    "14-30": 0.253,
    "30-60": 0.38,
  },
  "3-5% OTM": {
    "0-3": 0.04,
    "3-7": 0.158,
    "7-14": 0.327,
    "14-30": 0.423,
    "30-60": 0.569,
  },
  "1-3% OTM": {
    "0-3": 0.129,
    "3-7": 0.319,
    "7-14": 0.465,
    "14-30": 0.55,
    "30-60": 0.725,
  },
  "0-1% OTM": {
    "0-3": 0.266,
    "3-7": 0.491,
    "7-14": 0.558,
    "14-30": 0.669,
    "30-60": 0.775,
  },
  "0-1% ITM": {
    "0-3": 0.762,
    "3-7": 0.705,
    "7-14": 0.64,
    "14-30": 0.723,
    "30-60": 0.807,
  },
  "1-3% ITM": {
    "0-3": 0.912,
    "3-7": 0.847,
    "7-14": 0.771,
    "14-30": 0.832,
    "30-60": 0.877,
  },
  "3-5% ITM": {
    "0-3": 0.97,
    "3-7": 0.947,
    "7-14": 0.897,
    "14-30": 0.898,
    "30-60": 0.909,
  },
  ">5% ITM": {
    "0-3": 0.979,
    "3-7": 0.986,
    "7-14": 0.967,
    "14-30": 0.972,
    "30-60": 0.984,
  },
}
