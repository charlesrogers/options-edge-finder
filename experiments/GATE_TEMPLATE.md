---
experiment: [NUMBER]
title: "[TITLE]"
date: [YYYY-MM-DD]
status: pre-registered
prior_experiment: [NUMBER or null]
changes_production: true
---

# Experiment [NUMBER]: [TITLE]

## Gate 1: Pre-Registration

### Hypothesis
[Plain English: what you expect to find and why]

### Proposed Change
| Ticker | Current | Proposed | Reason |
|---|---|---|---|
| [TICKER] | [current param] | [proposed param] | [evidence from prior experiment] |

### Pass/Fail Thresholds (IMMUTABLE after registration)
- **PASS**: [specific metric] < [threshold] on walk-forward TEST period
- **FAIL**: [specific metric] >= [threshold]
- **Fallback if FAIL**: [alternative param to try, or "abort"]

### Method
- Data: [source, period]
- Split: First 67% train / last 33% test
- Metric: [loss rate / win rate / net P&L / etc.]
- Minimum sample: [N trades on test period]

## Gate 2: Walk-Forward Results
[FILLED IN AFTER RUNNING — do not edit pre-registration above]

### Train Period
[results]

### Test Period
[results — this determines PASS/FAIL]

### Verdict: [PASS / FAIL]

## Gate 3: One Variable at a Time
- [ ] Each ticker is a separate commit
- [ ] Commit message references this experiment number

## Gate 4: Shadow Period
- [ ] Shadow strategies running for 2+ weeks
- [ ] Minimum 10 shadow trades per ticker
- [ ] Shadow outperforms production on real data

## Gate 5: Deployment
- [ ] Gates 1-4 all pass
- [ ] Commit references experiment and walk-forward result
- [ ] Only the validated parameter changes, nothing else
