# Phase 3 — Strategy Improvement (H21–H24), credit-free subset

**Spec:** `tasks/phase3-strategy-spec.md`
**Constraint imposed by Charles (2026-08-16):** execute everything in the spec that does
NOT require spending API credits. That rules out **Part A** (the $125 Databento purchase)
and everything downstream of it that needs option prices we do not own.

## Hard constraint (write it at the top of every plan)

> No paid API calls. No Databento purchase. Free data only:
> existing Databento files (already paid for), Yahoo stock/VIX history, Supabase.

## What we actually own (verified 2026-08-16)

| Ticker | Real option OHLCV | Days |
|---|---|---|
| AAPL | 2025-03-21 → 2026-03-20 | 251 |
| DIS  | 2025-03-21 → 2026-03-20 | 251 |
| TMUS | 2025-03-21 → 2026-03-20 | 251 |
| TXN  | 2025-03-21 → 2026-03-20 | 251 (production tier = skip) |
| KKR  | 2023-03-21 → 2026-03-20 | 753 (3 years) |
| GOOGL| 2026-03-16 → 2026-03-20 | **5** — unusable |
| MSFT/AMZN | none | 0 |

Free: Yahoo daily stock 2019→2026 for all names; `^VIX` + `^VIX3M` 2019→2026.
The owned window contains a real vol spike (24 backwardation days: Apr-2025 tariff
crash, Nov-2025, Mar-2026) — enough to test the H22 guard on **real** prices.

## Part-by-part disposition

- [x] Part A — Databento purchase → **NOT RUN** (costs money). Ledger file records it.
- [x] Part B — Exp 019 / H21 stress replay → **pre-register only**; needs 2020/2022 option
      prices we do not own. No proxy substitute: the hypothesis is explicitly about real prices.
- [x] Part C — Exp 019b / H22 backwardation guard → **RUN, partially**. Real-price arm on the
      owned window (which contains a genuine backwardation episode) + free VIX term structure.
      The "2020 stress-year P&L +20%" clause stays PENDING.
- [x] Part D — Exp 020 / H23 partial overwriting → **RUN**. Walk-forward arm complete on real
      prices. The "≥1 stress year" clause stays PENDING.
- [x] Part E(a) — GOOGL real-price → **NOT RUN** (5 days of data). Converts to the spec's
      pre-authorised fallback: extend GOOGL probation, upgrade from accrued chain captures.
- [x] Part E(b) — MSFT/AMZN probation → **RUN in full**. The hypothesis specifies stock-data
      walk-forward, which is free.
- [x] KKR capacity cap → **RUN in full** (computed from owned Databento contract volume).

## Tasks

- [x] Recon: verify data coverage, VIX availability (done above)
- [x] Create `signal_graveyard` table (missing from Supabase entirely) + register H21–H24
- [x] `experiments/lib_cc_sim.py` — shared covered-call sim: daily equity curve, IV-rank gate,
      pluggable entry guard, overwrite ratio, explicit missing-data accounting
- [x] Pre-registrations committed BEFORE any run: 019, 019b, 020, 021
- [x] Exp 019b run + `results/019b_backwardation_guard.md`
- [x] Exp 020 run + `results/020_partial_overwriting.md`
- [x] Exp 021 run + `results/021_capacity_expansion.md`
- [x] `results/019_stress_replay.md` (blocked verdict), `results/019_data_purchase_ledger.md`
- [x] pytest for new production logic (overwrite math, guard conditions, liquidity cap)
- [x] Deploy only what passed, one variable per commit
- [x] Final summary table + graveyard verdicts

## Known statistical weakness (state it, don't hide it)

One year of real option data → ~12 entries/ticker/year on the production 25-day re-entry
cycle. Research discipline rule 6 says flag < 100 trades. Mitigation: **staggered entry
cohorts** (25 start offsets per ticker) so each configuration is evaluated over ~250–300
trades and we report the *distribution* over start dates, not one lucky path. Overlapping
cohorts are not independent — reported as a robustness spread, never as an n=300 t-test.

## Review

See `results/PHASE3_SUMMARY.md`.
