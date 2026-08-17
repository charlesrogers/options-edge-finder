---
title: "Experiment 017: EMERGENCY Rational-Exercise Refinement (shadow mode only)"
date: 2026-08-16
experiment: 017
signal_id: H19
tier: 2
hypotheses: ["H19: Natenberg rational-exercise conditions cut false-positive EMERGENCY firings >=50% with zero missed assignments"]
status: completed
verdict: FAIL
deployed: false
shadow_mode: shipped
finding: "H19 FAILS. On 172 historical ITM + ex-div<=3d observation days the refined rule suppresses 61.6% of firings — above the 50% target — but misses 38 true-assignment scenarios, including 9 calls that were actually exercised early at delta 0.79-0.95. One miss kills the hypothesis; there are 38. The failure is structural, not a tuning problem: no combination of delta threshold and safety margin reaches zero misses, because the current EMERGENCY rule is also protecting against near-certain assignment AT EXPIRY, which Natenberg's early-exercise criteria say nothing about. Shadow logging shipped anyway; the live alert is untouched."
---

# Experiment 017: EMERGENCY Rational-Exercise Refinement (H19)

**Pre-registration:** `experiments/017_natenberg_emergency/README.md` (frozen before the run)
**Reproduce:** `python3 experiments/017_natenberg_emergency/run.py`

## ⚠️ Production status: unchanged

The live EMERGENCY rule is exactly what it was. This experiment tested a *loosening* of the
$400K alert and the loosening failed. Shadow logging shipped (see below) so the question can
keep being answered on live data, but there is nothing to sign off on.

## Verdict: FAIL

| Criterion | Pre-registered | Measured |
|---|---|---|
| Sample floor for any verdict | ≥ 20 events | **172** ✓ |
| False positives suppressed | ≥ 50% | **61.6%** ✓ |
| Missed true-assignment scenarios | **0** | **38** ✗ |

The suppression target was met and the sample was well above the floor. It does not matter.
The pre-registration is explicit: *"any missed true-assignment scenario. One miss kills the
hypothesis regardless of the false-positive win."*

## Sample

Observation pass, not a trading pass: every cohort is held to expiry so that every ITM +
ex-div ≤ 3d day is observed. A policy that closed on EMERGENCY would destroy the sample.

| Ticker | Observation days | Positions | Suppressed | Misses |
|---|---|---|---|---|
| AAPL | 0 | 0 | 0 | 0 |
| DIS | 4 | 2 | 4 | 0 |
| TMUS | 13 | 7 | 10 | 6 |
| KKR | 101 | 38 | 55 | 27 |
| TXN | 54 | 21 | 37 | 5 |
| **total** | **172** | **68** | **106** | **38** |

172 events, but only **127 distinct (ticker, date, contract) situations** — overlapping
cohorts can hold the same contract on the same day. The 38 misses collapse to **23 distinct
situations**. Either count is far above zero.

**AAPL contributes nothing.** At 15% OTM its calls were never ITM within 3 days of an
ex-dividend in the window. The ticker with the largest position is the one this experiment
learned least about.

## The misses

### 9 calls that were actually exercised early while the refined rule stayed silent

Every one was silenced by the **delta ≥ 0.95** condition. Not one was silenced by the
extrinsic-value condition.

| Ticker | Date | Strike | Spot | Extrinsic | Dividend | Delta | DTE |
|---|---|---|---|---|---|---|---|
| TMUS | 2026-02-26 | 210 | 213.15 | $0.44 | $1.02 | **0.80** | 1 |
| KKR | 2023-11-15 | 60.0 | 66.41 | $0.11 | $0.165 | **0.946** | 2 |
| KKR | 2023-11-15 | 62.5 | 66.41 | $0.09 | $0.165 | **0.936** | 2 |
| TXN | 2025-04-30 | 155 | 160.05 | $0.97 | $1.36 | **0.79** | 9 |
| TXN | 2026-01-29 | 210 | 218.97 | $1.26 | $1.42 | **0.833** | 15 |

(KKR 62.5 and TXN 210 each appear three times — three overlapping cohorts holding the same
contract.)

**Delta of calls that were rationally exercised: 0.79 to 0.946.** Natenberg's "delta near
100" criterion, operationalised at 0.95 and computed by inverting Black-Scholes on a
Databento trade print, sits above the entire observed range. The criterion that was supposed
to make the rule safer is the sole cause of every early-exercise miss.

### 34 suppressions where the empirical assignment table put assignment at ≥ 90%

Independent of the exercise model. 21 came from the extrinsic condition, 13 from delta. Also:
**53 of the 106 suppressed events were on calls that finished ITM at expiry** — i.e. the
position would have been assigned anyway, just later.

## Why this is structural, not a tuning problem

Counterfactual sweep over the two tunable knobs (reported for diagnosis; **the hypothesis was
already dead and no re-registration is implied**):

| Delta threshold | Margin | Suppressed | Misses |
|---|---|---|---|
| 0.95 (registered) | 1.5 (registered) | 106 / 172 (62%) | 38 |
| 0.90 | 1.5 | 95 (55%) | 28 |
| 0.85 | 3.0 | 81 (47%) | 20 |
| 0.80 | 3.0 | 75 (44%) | 14 |
| delta dropped entirely | 3.0 | 52 (30%) | **12** |

Zero is not reachable. Even deleting the delta condition and tripling the safety margin
leaves 12 misses, all of them table-≥90% cases.

The reason is a category error in the hypothesis. The current rule fires on **ITM + ex-div ≤
3 days**, and that condition is doing two jobs at once:

1. catching rational **early exercise** into the dividend — which is what Natenberg Ch. 12
   describes and what the refinement addresses; and
2. catching positions that are ITM close to expiry and will be **assigned at expiry**
   regardless of the dividend — which Natenberg's criteria say nothing about.

Job (2) is most of the volume. Refining on early-exercise logic alone silences job (2)
wholesale. A refinement that only removed job-(1) false positives would need a separate
"and this call is not going to finish ITM anyway" test, which is a different hypothesis
requiring a different experiment.

## Data caveats

- The Supabase chain capture was dead **2026-03-30 → 2026-08-15**, so the live snapshot
  record has a 4.5-month hole and could not be used as a second source. Only the Databento
  window is usable.
- **Delta is a model estimate, not an observation.** It is inverted from the option's own
  Databento close, which is a trade print, not a mid quote. 9 of 172 events had no
  invertible delta (fail-safe: those fire).
- 49 of 172 events, and 22 of the 106 suppressions, carried a stale (last-known) price
  forward. Extrinsic value on those days is approximate.
- Partial circularity, stated plainly: the simulator's early-exercise trigger
  (`extrinsic < dividend`) shares a term with the refined rule, so "missed actual exercise"
  mostly tests the delta and margin conditions. The table-≥90% check and the finished-ITM
  statistic are independent of that trigger, and both point the same way.

## What shipped anyway: shadow mode

The pre-registration required shadow mode regardless of the backtest outcome, and it is more
useful now than it would have been on a pass — it will keep measuring a rule we know to be
unsafe in its current form, on live data, at no risk.

- `position_monitor.rational_exercise_emergency()` — the refined condition, with a hard
  fail-safe: **missing option price, missing dividend amount or missing delta all cause it to
  FIRE.** Missing data must never buy silence on this alert.
- `position_monitor.assess_position_shadow()` — runs the live rule and the refined rule side
  by side and returns both. The live alert comes from the untouched `assess_position()`.
- `monitor_positions.py` — logs every day either rule fires to `emergency_shadow.jsonl`
  (path overridable via `EMERGENCY_SHADOW_LOG`). The log write is wrapped so a research log
  can never take down the alert path, and failures are printed, not swallowed.
- `bsm.py` — Black-Scholes price / delta / implied-vol inversion, returning `None` rather
  than a guess when a price is not invertible.
- 27 tests in `tests/test_emergency_shadow.py`, including one asserting the refined rule can
  never fire where the current rule does not.

**Known gap:** the live dividend amount is not available from the Yahoo proxy — only an
annual `dividendYield`. Shadow mode therefore uses the full annual dividend as an upper bound
on any single payment, which makes the refined rule fire *more* often (the safe direction),
and records `dividend_source: annual_yield_upper_bound` on every entry. A real per-payment
dividend calendar is Week 1 item 5.

## Follow-up (not tested, not deployed)

1. **Split the two jobs.** A refinement that only targets early-exercise false positives has
   to first establish the call is not headed for assignment at expiry. That is a new
   hypothesis with a new pre-registration.
2. **Delta ≥ 0.95 is empirically wrong here.** Observed early exercises happened at 0.79-0.95.
   If any future rule uses a delta screen, it needs a threshold derived from data, not from
   the phrase "near 100."
3. **Get a real dividend-amount source** before any of this is worth revisiting.

## Graveyard

`H19: failed_layer_2 — 38 missed true-assignment scenarios (9 actual early exercises at
delta 0.79-0.95, 34 at table P>=90%) on 172 events, despite 61.6% suppression. Failure is
structural: the current rule also catches assignment-at-expiry, which Natenberg's criteria
do not address. Shadow mode shipped; live alert unchanged.`
