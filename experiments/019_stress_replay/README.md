# Experiment 019 — Bear/Rebound Stress Replay (H21, Tier 1)

**Pre-registered:** 2026-08-16, before any data was touched.
**Spec:** `tasks/phase3-strategy-spec.md` Part B.
**Status at pre-registration: BLOCKED — see "Data we do not have".**

## Hypothesis (H21) — immutable

The production covered-call system (per-ticker OTM%/DTE from `ticker_strategies.py`,
IV-rank ≥ 50 entry gate, copilot exits from `position_monitor.py`) produces, on **real**
2020 and 2022 option prices:

1. **zero assignments**, and
2. per-ticker annual loss rates within **10 percentage points** of their 2025–26
   walk-forward values (`results/012_walk_forward.md`), and
3. total return ≥ stock-only buy-and-hold minus $0 — i.e. the overlay never amplifies
   losses (the Monte Carlo claim from Exp 010, tested against history).

Run BOTH the distance-based buyback rule and, if Exp 015 (H17) passed, the
probability-based rule. Exp 015 ran on 2026-08-16 (Phase 1, merged into this branch) and
**H17 FAILED** — probability triggers were worse than the corrected baseline on 3 of 4
tickers. Only the current production distance-based rule is therefore in scope for H21.

## Pass / Fail (immutable)

- **PASS:** all three clauses hold in **both** 2020 and 2022 for AAPL and TMUS.
- **MARGINAL:** loss rates within 10pp but premium retention collapses (> 50% relative
  drop) — strategy survives, income claim gains a regime caveat in all Dad-facing material.
- **FAIL:** any assignment, or a loss rate > 10pp worse, or the overlay amplifies losses in
  either year. A fail is a product-level finding: the rule card gains a regime kill-switch
  before Dad scales up, and the dad-pitch bear-market section is rewritten with real numbers.

## Data we do not have

H21 is explicitly a **real-price** hypothesis. Option OHLCV owned as of 2026-08-16:

| Ticker | Coverage | Days |
|---|---|---|
| AAPL, DIS, TMUS, TXN | 2025-03-21 → 2026-03-20 | 251 each |
| KKR | 2023-03-21 → 2026-03-20 | 753 |
| GOOGL | 2026-03-16 → 2026-03-20 | 5 |

Zero coverage of 2020 or 2022. Acquiring it is Part A of the spec — a ~$125 Databento
purchase. Charles instructed on 2026-08-16 that no API credits be spent this session, so
Part A did not run and H21 cannot be tested.

**No proxy substitute will be run for H21.** A BSM/stock-proxy replay of 2020 would be a
"directional only" result, and H21's whole purpose is to replace Exp 010's Monte Carlo with
real prices. Substituting another simulation for the real thing would answer a question
nobody asked. See `results/019_stress_replay.md` for the recorded blocked verdict and
`results/019_data_purchase_ledger.md` for the (empty) purchase ledger.

## What unblocks it

The Databento purchase order from the spec, unchanged, cheapest-first:
TMUS 2022 → AAPL 2020 → AAPL 2022 → TMUS 2020 → GOOGL most-recent-year → DIS 2022 / MSFT.
Hard stop at $120 cumulative **actual** spend; verify each file loads and report
row counts + missing-bar % before the next pull.

## Reproducibility

Nothing to run. `run.py` is intentionally absent until the data exists.
