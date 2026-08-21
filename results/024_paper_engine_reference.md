---
title: "Experiment 024 reference derivation — calibrating the paper engine's thresholds, and finding two windows that were lying"
date: 2026-08-20
experiment: 024
hypothesis: "H40-H43 (pre-registration only — no forward data exists yet)"
status: reference-derived
finding: "Every threshold in PREREGISTRATION.md is now derived from cc_sim on real Databento fills, with the arithmetic shown. Three things fell out of doing it: AAPL's and GOOGL's 2020 stress windows are split-contaminated and were producing $13,731/cycle at 99.7% retention; the per-ticker cycle floors say NOTHING in this study is gradeable at day 180; and arm A took zero assignments in every reference window while arm B took up to 102, which is the context every A-B readout has to carry."
---

# Experiment 024 — Reference derivation for the forward paper engine

**Not a result about the strategy.** This is the calibration pass that had to
happen before the engine could be pre-registered: a threshold measured against
a broken baseline is worse than no threshold (tasks/lessons.md 2026-08-16), so
every number in `PREREGISTRATION.md` comes out of a committed script here.

**Regenerate:**

```bash
python3 experiments/024_paper_engine/derive_reference.py    # -> reference.json
python3 experiments/024_paper_engine/derive_thresholds.py   # -> thresholds.json
python3 experiments/024_paper_engine/embed_thresholds.py    # -> into PREREGISTRATION.md
```

Engine: `experiments/cc_sim.py` + `cc_core.py` at `b3f55bd`. Standard: **real-fill
subset is the result**, all-fill reported beside it.

---

## The reference table

Production settings, production IV gate, 25 staggered sequential chains.

| Ticker | Cycles | Real-fill coverage | $/cycle real-fill | $/cycle all-fill | Retention (kept / collected) | Hold p50 | Cycles/yr | Per-cycle win rate | Worst 30d DD |
|---|---:|---:|---:|---:|---|---:|---:|---:|---:|
| TMUS | 89 | 78.8% | **$1.50** | $16.76 | 1.2% ($133 / $10,692) | 25d | 13.0 | 88.9% | $765 |
| KKR | 256 | 67.5% | **−$15.80** | $6.16 | −12.5% (−$4,044 / $32,295) | 22d | 16.7 | 71.0% | $374 |
| DIS | 37 | 77.1% | **$74.65** | $94.64 | 34.3% ($2,762 / $8,053) | 19d | 4.0 | 100.0% | $748 |
| AAPL | 89 | 98.9% | **$7.84** | $7.90 | 15.8% ($698 / $4,408) | 21d | 12.0 | 90.9% | $971 |

Consistent with Exp 022: the tickers with poor repricing coverage are the ones
whose sign moves between all-fill and real-fill.

---

## Finding 1 — two stress windows were producing fiction

The first run of `derive_reference.py` reported:

> AAPL / stress_2020: 69 cycles, real-fill **$13,731.61/cycle**, retention
> **99.7%**, coverage **100.0%**

A hundred percent coverage and near-perfect retention should never have looked
plausible, and it was not: **Databento strikes are as-traded while the proxy's
stock closes are split-adjusted.** Across AAPL's 4:1 (2020-08-31) and GOOGL's
20:1, the strike ladder sits far above spot, nothing is ever breached, and every
call expires worthless.

Measured median-of-daily (median strike / spot):

| Window | AAPL | DIS | TMUS | KKR | GOOGL |
|---|---:|---:|---:|---:|---:|
| owned_recent | 1.04 | 1.05 | 1.04 | 1.02 | — |
| stress_2020 | **4.02** | 1.08 | 1.03 | 1.03 | **20.70** |

The clean observations span 0.98–1.23. `derive_reference.py` now rejects any
window where more than 5% of days fall outside **[0.70, 1.50]** — clearing the
widest clean observation on both sides while still catching a 2:1 split, the
smallest that could matter. Both contaminated windows are now refused
automatically with a reason, rather than contributing a threshold.

**This guard did not exist before today, and the contaminated numbers were one
run away from being calibrated against.**

## Finding 2 — a second, quieter version of the same bug

The stress windows initially reported *zero trades*, with
`[iv_rank] 103 days without a same-day stock close`. The cause: `cc_sim.load_stock`
cached to `{ticker}_stock.parquet` **without the period in the cache key**, so a
caller asking for 10 years silently received whatever the first caller had
cached — and the first caller is always the 5-year default, which does not reach
2020. The IV gate then had no rank to read and rejected every single day.

"The strategy never traded in the crash" and "we could not evaluate the crash"
are different facts, and the cache key was collapsing them. Fixed; the default
is unchanged, so no existing caller's inputs moved (verified byte-identical by
`scripts/cc_sim_parity_baseline.py`).

## Finding 3 — nothing in this study is gradeable at day 180

Floors from `n ≥ (1.645·sd/|mean|)²` on the reference's own per-cycle
distributions, against expected cycles by day 180:

| Ticker | Cycles by day 180 | H40 (absolute) | H41 (A−B) | H42 (gate) | H43 (A−D) |
|---|---:|---:|---:|---:|---:|
| AAPL | 5.9 | 794 | 42 | 61 | 50 |
| DIS | 2.0 | 23 | 14 | 415 | 15 |
| KKR | 8.2 | 360 | 119 | 502 | 258 |
| TMUS | 6.4 | 58,101 | 25 | 10 | 113 |

Two readings, both now pre-registered rather than available for improvisation
at review time:

- **The spec's premise holds, per ticker.** Pairing does cancel regime noise:
  the arm-difference questions need 14–258 cycles where the absolute question
  needs 23–58,101. TMUS is the extreme — $1.50/cycle against a $121 standard
  deviation.
- **Pooling across tickers is the wrong estimator** for the paired questions
  and is registered as secondary only. The per-ticker A−B means have opposite
  signs (TMUS −$64, AAPL −$41, KKR +$50, DIS +$271), so pooling cancels them
  and the pooled requirement (270) is worse than every per-ticker one.

Day 180 is therefore an **interim readout** — point estimates, honest CIs, every
one labelled under-powered — plus the falsification result, which *is* reachable
because a strategy losing money badly shows up long before a small positive edge
can be confirmed.

## Finding 4 — arm B's option-leg edge costs 0–102 assignments

| Ticker | A net / assignments | B net / assignments | D net / assignments |
|---|---|---|---|
| TMUS | $1,894 / **0** | $9,147 / **10** | $4,865 / 5 |
| KKR | $2,335 / **0** | −$16,580 / **102** | −$8,578 / 64 |
| DIS | $4,543 / **0** | −$8,477 / **10** | −$7,939 / 9 |
| AAPL | $711 / **0** | $4,424 / **0** | $4,123 / 0 |

Arm A took zero assignments in every window. On TMUS and AAPL, arm B's
option-leg P&L is higher — and being called away is the tax event the copilot
exists to prevent, which option-leg P&L cannot see. `PREREGISTRATION.md`
pre-commits to treating any A−B readout that omits both arms' assignment counts
as a **reporting failure**, not a finding.

## Finding 5 — clause reachability baseline

Across 8,458 arm-A observations in the recent window, three of the fourteen
rungs never fired:

- `close_now_within_2pct_earnings_2d` — **structurally unreachable** in
  backtest: `cc_sim` passes `earnings_date=None`. The forward engine passes real
  earnings dates, so this is the one clause expected to move off zero.
- `watch_exdiv_5to10d_within_5pct` — never reached.
- `emergency_itm_exdiv_3d` — fired **8 times, KKR only**.

The assignment branch was *approached* only 8 times (all KKR). A forward zero
must therefore be reported as "non-binding — the state was never reached", not
as "constraint met" (the Exp 015 failure).

## What this does NOT say

Nothing here is a verdict on the strategy. These are backtest numbers on a
single recent window plus two usable stress windows, at the real-fill standard,
used to calibrate thresholds. The forward engine is the only thing that can
ever say "it works", and only past the floors above.
