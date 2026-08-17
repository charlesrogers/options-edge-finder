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

[FILLED IN AFTER RUNNING — pre-registration above is frozen]
