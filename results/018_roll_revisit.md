---
title: "Experiment 018: Roll-at-CLOSE_SOON Revisit — not run"
date: 2026-08-16
experiment: 018
signal_id: H20
tier: 3
status: skipped
verdict: SKIPPED_DEPENDENCY
deployed: false
finding: "Not run. H20's pre-registration makes it conditional on H17 passing, and H17 failed. There is no point re-testing rolling under a trigger rule that did not work. Marked skipped_dependency in the graveyard rather than left untested, so the Deflated Sharpe denominator stays honest about what was and was not evaluated."
---

# Experiment 018: Roll-at-CLOSE_SOON Revisit (H20) — NOT RUN

**Pre-registration:** `experiments/018_roll_revisit/README.md` (frozen before the run)

## Why it was not run

H20's pre-registration opens with the condition:

> **Conditional on Exp 015.** If H17 fails, this experiment is skipped entirely and H20 is
> marked `skipped_dependency` in the graveyard. There is no point re-testing rolling under a
> trigger rule that did not work.

H17 failed (`results/015_probability_buybacks.md`): 1 of 4 tickers on the spec's literal
criterion, 0 of 4 on honest walk-forward. The "winning probability triggers" H20 was defined
to roll under do not exist.

Running it anyway would mean choosing an arm of a failed grid — the exact post-hoc selection
the pre-registration exists to prevent.

## What it would take to revive it

Rolling remains a live idea. Exp 009 found it converted individual KKR positions from +$702
to +$1,894, and that finding is *not* invalidated by the DTE bug in the same way the
retention numbers are — rolling changes what happens after a CLOSE_SOON verdict, and Exp 009
did reach CLOSE_SOON verdicts (via the 75%-premium-captured clause, which does not depend on
DTE).

A revived version should roll under **the current copilot's exit rules**, not under
probability triggers, and should be pre-registered fresh:

- H20 as written is dead. A new hypothesis (H24 or later) would be "rolling at CLOSE_SOON
  under the current rules beats closing, walk-forward, with 0 assignments."
- The simulator supports it: `experiments/cc_sim.py` already carries cumulative premium and
  cumulative buyback fields on `Trade`, and `n_rolls` is present but unused.
- It should be sequenced after the take-profit hypothesis from `results/015_*.md`
  (follow-up 1), since the take-profit clause is what generates almost all CLOSE_SOON
  verdicts and changing it changes what there is to roll.

## Graveyard

`H20: skipped_dependency — H17 failed, so the winning probability triggers this hypothesis
was defined against do not exist. Not tested. Does not count toward the Deflated Sharpe
denominator as a tested signal.`
