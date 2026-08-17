---
title: "Experiment 019: Bear/Rebound Stress Replay — BLOCKED, no 2020/2022 option prices"
date: 2026-08-16
experiment: 019
hypothesis: H21
status: blocked
finding: "Not tested. H21 is explicitly a real-price hypothesis and we own zero 2020 or 2022 option data. Charles ruled out spending API credits this session, so the $125 Databento purchase (Part A) did not run. No proxy was substituted — a BSM replay would answer a different question than the one H21 asks."
---

# Experiment 019 — Bear/Rebound Stress Replay (H21)

**Verdict: BLOCKED — not tested, not passed, not failed.**

## Why

H21 asks whether the production covered-call system survives 2020 and 2022 **on real
option prices**. Its entire reason for existing is that Exp 010 already answered the
question with Monte Carlo and nobody believed it enough to bet Dad's account on it.

Option OHLCV we own, verified 2026-08-16:

| Ticker | Coverage | Trading days |
|---|---|---|
| AAPL, DIS, TMUS, TXN | 2025-03-21 → 2026-03-20 | 251 each |
| KKR | 2023-03-21 → 2026-03-20 | 753 |
| GOOGL | 2026-03-16 → 2026-03-20 | 5 |

Nothing from 2020. Nothing from 2022. Acquiring it is Part A of the Phase 3 spec — a
one-shot ~$125 Databento purchase. Charles's instruction for this session was to execute
everything that does **not** spend API credits, so Part A did not run.

## Why no proxy was substituted

The obvious temptation is to replay 2020 on Yahoo stock closes with BSM-priced calls and
label it "directional only." That would be worse than useless here:

- Exp 010 already did a Monte Carlo version of exactly that. H21 exists **because** a
  simulation was not convincing.
- The 2020 failure mode H21 targets — crash pins IV rank at 100, the entry gate screams
  SELL, then a V-recovery runs over every call — is a *pricing* phenomenon. BSM with a
  realized-vol proxy cannot reproduce a vol-spike-then-crush term structure, which is the
  whole mechanism.

Substituting a proxy would produce a number that looks like an answer and isn't one.

## What we learned anyway (from the parts that did run)

Three findings from Phase 1 and from Exps 019b / 020 change what H21 should be tested
against when the data is bought. They are worth reading before spending the $125.

1. **The backtest clock was broken, and it invalidates the H21 baseline.**
   `position_monitor.assess_position()` computed DTE from `datetime.now()`, so every
   historical simulation in Exps 007-014 evaluated every position at DTE = 0 and every
   DTE-dependent alert branch was dead. Phase 1 found and fixed this (commit 8040440,
   `as_of` parameter). H21's clause 2 compares stress-year loss rates against "their
   2025-26 walk-forward values" — i.e. against `results/012_walk_forward.md`, which was
   produced on the broken clock. **That baseline has to be re-derived on `cc_sim.py`
   before H21 can be scored**, or the comparison is against a number that was never
   measured.

2. **Repricing coverage is far worse than the working assumption.** Measured along the
   production entry path with the real engine: AAPL **2.5%** missing, DIS **14.3%**,
   TMUS **44.0%**, KKR **63.7%**. H21's pass criterion names AAPL *and* TMUS. Half of
   TMUS's daily lookups have no bar, and TMUS is the ticker whose overlay P&L flipped
   sign between two simulators built in the same week. If TMUS 2020/2022 comes back as
   sparse as TMUS 2025 did, buying it will not produce a verdict.

3. **The IV-rank >= 50 entry gate is not uniformly good** (descriptive control in Exp 020):
   over the owned year it helps DIS and KKR and costs AAPL and TMUS. It is live in
   production on every ticker. H21 should test the gate as a variable rather than freeze it
   as part of "the production system" — the 2020 failure mode the hypothesis describes
   (crash pins IV rank at 100, the gate screams SELL) is a claim *about the gate*.

## What unblocks this

The spec's purchase order, unchanged, cheapest-first: TMUS 2022 → AAPL 2020 → AAPL 2022 →
TMUS 2020 → GOOGL most-recent-year → DIS 2022 / MSFT. Hard stop at $120 cumulative
**actual** spend; verify each file loads through the engine and report row counts +
missing-bar % before the next pull. Given finding 2, consider reordering to put **AAPL**
first — it is the only name whose repricing coverage is good enough to carry a verdict,
and AAPL 2020 is the exact crash-then-V-recovery shape H21 is about.

## Reproducibility

Nothing to run. Pre-registration: `experiments/019_stress_replay/README.md`.
Purchase ledger (empty): `results/019_data_purchase_ledger.md`.
