---
experiment: 017
signal_id: H19
tier: 2
title: "EMERGENCY Rational-Exercise Refinement (SHADOW MODE ONLY)"
date: 2026-08-16
status: pre-registered
prior_experiment: 006
changes_production: false
shadow_only: true
---

# Experiment 017: EMERGENCY Rational-Exercise Refinement (H19)

## Gate 1: Pre-Registration

**Nothing below this line may be edited after the run script is executed.**

## ⚠️ SAFETY FRAME — read before anything else

This hypothesis **loosens the $400K alert.** The current EMERGENCY rule is
`ITM and ex-div ≤ 3 days`. Any refinement makes the alert fire less often. One
missed true-assignment kills the hypothesis outright, regardless of how many
false positives it removed.

- **No production change in Week 2.** Shadow mode only: both rules are logged
  on every monitor pass; the live alert remains the current rule.
- Deployment requires **explicit sign-off from Charles** after reviewing shadow
  logs. Not autonomous, not on a pass alone.

### Hypothesis

Conditioning EMERGENCY on Natenberg's rational early-exercise criteria —
ITM **and** ex-div ≤ 3 days **and** dividend > the call's remaining extrinsic
value **and** delta ≥ 0.95 — reduces false-positive emergency buybacks by
**≥ 50%** with **zero** missed true-assignment scenarios in historical data.

### Source

Natenberg (1994), Ch. 12: a call is rationally exercised early only when it is
trading at parity (extrinsic ≈ 0) with delta near 100; for dividend capture,
when remaining time value is less than the dividend. The current `ITM + 3d`
rule is a blunt superset of that condition. Natenberg's warning applies
directly: early exercise is **more** common in low-volatility regimes, so the
calm months are exactly when this matters.

### Refined rule (exact form to be tested)

Fire EMERGENCY when **all** of:
1. `current_stock > strike` (ITM), and
2. `0 ≤ days_to_exdiv ≤ 3`, and
3. `extrinsic < dividend × 1.5`, where
   `extrinsic = option_ask − max(0, current_stock − strike)`, and
4. `delta ≥ 0.95`.

The `× 1.5` is an **arbitrary safety margin, to be tuned upward only** — never
downward. Suppression only happens when all four fail to hold *and* the current
rule would have fired.

**Fallback rule:** if the option price or delta is unavailable (missing quote,
missing IV), the refined rule **fires** — it degrades to the current rule.
Missing data must never buy silence.

### Delta source

Delta is not in the Databento OHLCV feed. It is computed by BSM from the
Databento option close, spot, strike, DTE and a risk-free rate, by inverting
for implied volatility. **This makes delta a model estimate, not an
observation.** The result is labelled accordingly, and condition (4) is also
reported with delta dropped so its contribution is visible.

### Method and the honest sample count

- **Backtest:** Databento option prices + real ex-div dates for AAPL, DIS,
  TMUS, TXN, KKR over their option-data windows. Positions come from the Exp
  015 baseline arm. Every day a position is open and the current rule fires,
  both verdicts are recorded.
- **Data caveat, stated up front:** the Supabase chain capture was dead
  2026-03-30 → 2026-08-15. The stored chain-snapshot record has a 4.5-month
  hole, so the *live* snapshot history is not usable as a second source. Only
  the Databento window is usable.
- The number of historical ITM + ex-div ≤ 3d events will be **counted and
  reported before any pass/fail claim.** If that count is **< 20**, the
  backtest is explicitly declared underpowered and the burden shifts entirely
  to shadow mode — no pass may be declared on the backtest alone.

### Shadow mode deliverable (ships this week)

`position_monitor.assess_position_shadow()` returns both verdicts, and
`monitor_positions.py` logs the pair. The live alert path is untouched.

### Pass / Fail (IMMUTABLE)

- **PASS:** in combined backtest + **≥ 2 weeks** of shadow logging:
  **≥ 50%** of current-rule EMERGENCY firings suppressed, **AND zero** cases
  where the refined rule stayed silent and the option was assigned, or
  empirically would have been (assignment table ≥ 90% probability).
- **FAIL:** any missed true-assignment scenario. One miss kills the hypothesis
  regardless of the false-positive win.
- **UNDERPOWERED:** < 20 historical events → no verdict from the backtest;
  status stays `testing` until shadow logs accumulate.

### What happens on PASS

Nothing automatic. Charles reviews shadow logs and signs off, or does not.

## Gate 2: Backtest + Shadow Results

**VERDICT: FAIL.** Full write-up: `results/017_natenberg_emergency.md`.

| Criterion | Required | Measured |
|---|---|---|
| Events for a verdict | ≥ 20 | 172 (127 distinct situations) ✓ |
| False positives suppressed | ≥ 50% | 61.6% ✓ |
| Missed true-assignment scenarios | **0** | **38** ✗ |

38 misses: 9 calls **actually exercised early** (delta 0.79–0.946, every one silenced by the
`delta ≥ 0.95` condition) and 34 suppressions where the empirical table put assignment at
≥ 90%. 53 of the 106 suppressed events were on calls that finished ITM.

The failure is **structural, not tunable**. No delta threshold / margin combination reaches
zero misses — dropping delta entirely and tripling the margin still leaves 12. The current
`ITM + ex-div ≤ 3d` rule is doing two jobs: catching early exercise (what Natenberg
addresses) and catching near-certain assignment at expiry (what he does not). Refining on
early-exercise logic alone silences the second job wholesale.

**Shadow mode shipped as pre-registered**, and is more useful on a fail than it would have
been on a pass: `assess_position_shadow()`, `rational_exercise_emergency()` (fail-safe: any
missing input FIRES), `bsm.py`, JSONL logging in `monitor_positions.py`, 27 tests.

**Production unchanged. Nothing for Charles to sign off on.**
