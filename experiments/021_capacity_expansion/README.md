# Experiment 021 — Capacity Expansion (H24, Tier 2)

**Pre-registered:** 2026-08-16, before any data was touched.
**Spec:** `tasks/phase3-strategy-spec.md` Part E.

## Hypothesis (H24) — immutable, two clauses

**(a)** GOOGL's deployed 10% OTM / 20–45 DTE setting, validated so far only on stock
closes (Exp 014), holds on its purchased **real option year**: test-period loss rate
≤ **15%** and net P&L > **0**.

**(b)** MSFT and AMZN, entered at ultra-conservative **15% OTM / 20–45 DTE**, show
walk-forward **stock-data** loss rates ≤ **10%** — qualifying them for a **probation tier**:
recommendable, flagged "stock-data validated only", at half the eventual size, while the
daily chain capture accrues real option data for a 6-month upgrade review.

## Clause (a): NOT RUN — pre-authorised fallback taken

GOOGL real option data owned as of 2026-08-16: **5 trading days** (2026-03-16 → 2026-03-20).
Buying the year is Part A of the spec; Charles instructed that no API credits be spent this
session, so pull #5 never happened.

The spec pre-authorises the fallback and requires it be said out loud rather than silently
skipped: **GOOGL stays on extended probation — production setting unchanged at 10% OTM /
20–45 DTE, validated on stock closes only — and is upgraded from accrued daily chain
captures in a 6-month review (due ~2027-02).** Clause (a) is recorded PENDING.

## Clause (b): RUN IN FULL — the hypothesis specifies stock data, which is free

**Method (fixed before running):**

- Reuse `experiments/014_validated_param_update/run.py::simulate_at_otm` **verbatim**, so
  MSFT/AMZN are judged by exactly the yardstick that qualified TMUS, KKR, GOOGL, AAPL and
  DIS. A "loss" is: the stock closes above the strike 32 trading days after entry, entries
  every 7 trading days.
- **Primary (gating) window:** 2 years of daily closes ending 2026-08-14, train = first 67%,
  test = last 33%. The gate is the **test** loss rate ≤ 10%.
- **Secondary (reported, non-gating) window:** 2019-01-01 → 2026-08-14, so the 2020 crash
  and the 2022 grind are visible in the record even though they cannot gate a clause whose
  threshold was pre-registered on the 2-year window.
- **Control tickers:** AAPL (15% OTM) and DIS (7% OTM) run through the identical harness.
  They are already deployed and already validated; if the harness "discovers" that they
  fail, the harness is broken, not the tickers.
- Loss rate is a stock-path statistic. It is **not** P&L and it is **not** a real-price
  result. Anything derived from it is labelled "stock-data validated only".

**PASS (clause b, immutable, per ticker):** test-window loss rate ≤ 10% → that ticker moves
to `tier: 'probation'`.
**FAIL:** test-window loss rate > 10% → ticker stays out, no production change.

**Deployment:** per ticker, one commit each. Probation tickers get a **distinct** tier badge
in `TIER_CONFIG` — do NOT reuse `'untested'` (the spec says so explicitly; `'untested'`
means "nobody looked", `'probation'` means "looked, with a weaker instrument").

## Capacity note — KKR liquidity cap (run in full, free)

At 10,000 shares KKR would be 100 contracts. KKR options trade on the order of a couple of
contracts a day: **the position IS the market.** Validation is not KKR's binding constraint;
liquidity is.

**Method:** from the owned KKR option OHLCV (2023-03-21 → 2026-03-20, 753 days), compute
average daily contract volume across the strikes the strategy would actually sell
(15% OTM, 20–45 DTE). Cap the recommended overwrite at **≤ 20% of that average daily
volume** (the spec's number, an arbitrary starting value carried over, labelled as such),
convert contracts → shares, and surface the cap in `ticker_strategies.py` and the UI.

This is a derived number, not a threshold test — it has no pass/fail. It is reported with
its derivation shown.

## Reproducibility

```bash
python experiments/021_capacity_expansion/run.py
```
