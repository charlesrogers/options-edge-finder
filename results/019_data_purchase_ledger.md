---
title: "Databento Purchase Ledger — Phase 3 (no purchase made)"
date: 2026-08-16
experiment: 019
status: not_started
finding: "Zero spend. Charles instructed that this session execute only the parts of the Phase 3 spec that do not consume API credits, so Part A never began. Budget, purchase order and protocol are recorded here unchanged so the pull can start cold."
---

# Databento Purchase Ledger — Phase 3

**Total actual spend this session: $0.00. Nothing was pulled.**

| # | Item | Estimate | Actual | Running total | Rows | Missing bars | Status |
|---|---|---|---|---|---|---|---|
| 1 | TMUS option OHLCV 2022 + definitions | — | — | $0.00 | — | — | NOT PULLED |
| 2 | AAPL option OHLCV 2020 + definitions | — | — | $0.00 | — | — | NOT PULLED |
| 3 | AAPL option OHLCV 2022 + definitions | — | — | $0.00 | — | — | NOT PULLED |
| 4 | TMUS option OHLCV 2020 + definitions | — | — | $0.00 | — | — | NOT PULLED |
| 5 | GOOGL option OHLCV most recent full year | — | — | $0.00 | — | — | NOT PULLED |
| 6 | DIS 2022, then MSFT most recent year (budget permitting) | — | — | $0.00 | — | — | NOT PULLED |

## Blockers still outstanding (from the spec, unchanged)

- The Databento API key from Charles's father's account.
- Confirmation the ~$125 credit balance is still live.

Neither was needed this session because the purchase was explicitly out of scope.

## Protocol when it does run (verbatim from the spec + lessons.md 2026-03-23)

1. Estimate with `get_cost()`, pull, check the **actual** charge, recompute the correction
   factor, re-plan the remaining pulls. Never trust the estimator's first number —
   definitions ran 2× the estimate last time.
2. Hard stop at **$120 cumulative actual spend**. Print a running budget line after every pull.
3. Verify each file loads through `experiments/cc_sim.py`
   and report row counts + missing-bar percentage per ticker-year **before** the next pull.
4. Files to `data/databento/raw/` as `{TICKER}_ohlcv_1d_{tag}.dbn.zst`.
5. Do NOT buy: intraday/L1 schemas, SPX/index data, TXN anything, more 2024–2026 data for
   already-covered tickers, illiquid names.

## One recommended change to the order

Phase 3's other experiments measured repricing coverage along the actual production entry
path and it is much worse than the working assumption: AAPL **2.5%** missing, DIS **14.3%**,
TMUS **44.0%**, KKR **63.7%**. Databento OHLCV is trade-based, so a strike that did not
trade has no bar — and the thin names stay thin in every year.

TMUS 2022 is currently pull #1 only because it is the cheapest. On the measured coverage it
is also the pull most likely to come back too sparse to carry a verdict, and H21's pass
criterion names **AAPL and TMUS**. Consider **AAPL 2020 first**: it is the only name whose
coverage is unambiguously good, and 2020 is the exact crash-then-V-recovery shape H21 is
about. Cheapest-first is a cost heuristic; information-per-dollar is the actual objective.

This is a recommendation, not a change — the purchase order in the spec stands until
Charles says otherwise.
