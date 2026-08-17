---
experiment: 018
signal_id: H20
tier: 3
title: "Roll-at-CLOSE_SOON Revisit Under Probability Triggers"
date: 2026-08-16
status: pre-registered
prior_experiment: 015
changes_production: true
stretch: true
---

# Experiment 018: Roll-at-CLOSE_SOON Revisit (H20)

## Gate 1: Pre-Registration

**Nothing below this line may be edited after the run script is executed.**

**Conditional on Exp 015.** If H17 fails, this experiment is skipped entirely
and H20 is marked `skipped_dependency` in the graveyard. There is no point
re-testing rolling under a trigger rule that did not work.

### Hypothesis

Exp 009 showed that rolling instead of closing at CLOSE_SOON helped individual
names (KKR +$702 → +$1,894) but not the aggregate — **under the old
distance-only triggers, and under the DTE-collapse bug** (see Exp 015
pre-registration). Re-run the roll variant under Exp 015's winning
probability triggers.

Rolling = at a CLOSE_SOON verdict with 7 ≤ DTE ≤ 14, buy back the current call
and sell the next monthly at the same OTM% target, provided the new premium is
at least 50% of the original premium. Otherwise close.

### Method

- Same simulator, same entry set, same walk-forward 67/33 split as Exp 015.
- Exit policy = Exp 015's winning probability thresholds, plus rolling.
- Comparison arm = Exp 015's winning probability thresholds, close-only.
- Cumulative premium and cumulative buyback are carried across rolls; retention
  is measured on the whole rolled chain, not per leg.

### Pass / Fail (IMMUTABLE)

- **PASS:** on the **test** period — retention ≥ 25% **AND** 0 assignments
  **AND** aggregate net P&L > the close-only arm.
- **FAIL:** any of the three not met.

## Gate 2: Walk-Forward Results

**NOT RUN — `skipped_dependency`.** Write-up: `results/018_roll_revisit.md`.

H17 failed (1/4 primary, 0/4 walk-forward), so the "winning probability triggers" this
hypothesis was defined against do not exist. Running it would mean selecting an arm of a
failed grid post hoc — the exact thing pre-registration exists to prevent.

Rolling remains worth testing, but as a new hypothesis against the *current* copilot rules,
sequenced after the take-profit question raised in `results/015_probability_buybacks.md`.
