---
experiment: 015
signal_id: H17
tier: 1
title: "Probability-Based Buyback Thresholds"
date: 2026-08-16
status: pre-registered
prior_experiment: 009
changes_production: true
---

# Experiment 015: Probability-Based Buyback Thresholds (H17)

## Gate 1: Pre-Registration

**Nothing below this line may be edited after the run script is executed.**

### Hypothesis

Replacing the distance-based CLOSE_SOON / CLOSE_NOW triggers with
assignment-probability triggers — an empirical table lookup on
(moneyness × DTE), from the 145,099-observation table in `position_monitor.py`
— raises simulated premium retention to **≥ 20%** while keeping assignments at
**zero** and net P&L **≥ the current-rule baseline**, on walk-forward test data.

### Why believable first (Sinclair: believe, then test)

The current rule fires at a fixed distance regardless of DTE. The empirical
table says 5% OTM at 3 DTE is 1.7% assignment risk, while the same 5% OTM at
30 DTE is 25.3%. A fixed-distance rule therefore necessarily over-buys-back
short-dated positions and under-protects long-dated ones. The information
needed to fix this is already paid for and already in the repo.

### Baseline definition — READ THIS

The "13% retention" figure in `results/009_crush_it.md` **cannot be used as the
baseline.** `assess_position()` computed DTE from `datetime.now()`, so every
historical backtest (Exp 007-013) evaluated every observation at DTE = 0. That
silently disabled every DTE-conditional rule and turned the copilot into a pure
distance rule. Fixed in commit `8040440` (`as_of` parameter).

The baseline for this experiment is therefore **the current copilot rules,
correctly evaluated with `as_of` and with real ex-dividend dates, on exactly
the same entry set as the treatment.** Both arms see identical entries and
identical price paths, so the comparison is paired.

### Method

- **Simulator:** `experiments/cc_sim.py` (new). Cohort model: every trading day
  in the option-data window is evaluated as a candidate entry; positions
  overlap. This is the full-information estimator and avoids the arbitrary
  25-day chaining interval in Exp 007-009 (see `tasks/lessons.md` 2026-03-23,
  trade-skip survivorship bias).
- **Prices:** Databento OPRA 1d OHLCV only. Stock from `yf_proxy`. No BSM.
- **Entry gate:** production rule — IV rank ≥ 50, computed exactly as Exp 009
  (ATM call price / spot, 60-day rolling percentile).
- **Parameters:** per-ticker production OTM% / DTE from `ticker_strategies.py`.
- **Ex-dividend:** real historical ex-div dates and amounts (yfinance
  `.dividends`). Prior experiments passed `ex_div_date=None`, so the EMERGENCY
  and ex-div CLOSE_NOW rules were never exercised in any backtest.
- **EMERGENCY logic untouched.** Both arms use the identical current EMERGENCY
  rule. Out of scope here (that is H19).
- **Grid (arbitrary starting values to tune, NOT derived):**
  - CLOSE_SOON at P(assign) > {10%, 15%, 20%}
  - CLOSE_NOW at P(assign) > {25%, 35%, 45%}
  - 9 threshold pairs. Pairs where close_soon ≥ close_now are still run and
    reported; they collapse to a single-level rule.
- **Walk-forward:** entry dates sorted; first 67% = train, last 33% = test.
  Train results are reported but never used for the pass/fail decision.

### Tickers and expected sample (computed BEFORE running)

Databento option coverage, measured 2026-08-16:

| Ticker | Option days | Window | Usable |
|---|---|---|---|
| AAPL | 251 | 2025-03-21 → 2026-03-20 | yes |
| DIS | 251 | 2025-03-21 → 2026-03-20 | yes |
| TMUS | 251 | 2025-03-21 → 2026-03-20 | yes |
| TXN | 251 | 2025-03-21 → 2026-03-20 | yes (production tier = skip; reported separately) |
| KKR | 753 | 2023-03-21 → 2026-03-20 | yes, low confidence (~71% strike-days missing) |
| GOOGL | **5** | 2026-03-16 → 2026-03-20 | **NO — cannot be tested on real prices** |
| AMZN | 0 | — | **NO — no option data was ever purchased** |

So the spec's "all 6 tradeable tickers" is not achievable: **GOOGL and AMZN
have no usable option price history.** This experiment runs on AAPL, DIS,
TMUS, KKR (+ TXN reported but excluded from the pass count, since production
skips it).

Expected entries: ~251 candidate days/ticker-year × ~50% surviving the IV
gate ≈ 125/ticker-year. 4 production tickers over 6 ticker-years ≈ **~750
entries, ~250 in the test period.** Above the 100-trade reliability floor.
Overlapping cohorts are *not* independent; the comparison is paired
(same entries, both arms) and significance is assessed on paired differences,
not on the raw trade count.

### Assignment model (the thing that must stay at zero)

A trade is counted **assigned** if either:
1. It is still open on the day before an ex-dividend date, is ITM, and the
   remaining extrinsic value is less than the dividend (rational early
   exercise, Natenberg Ch. 12); or
2. It is still open at expiration and the stock closes above the strike.

P&L on assignment = premium − intrinsic value at the assignment point. The tax
consequence is tracked separately and is not netted into P&L.

### Pass / Fail (IMMUTABLE)

- **PASS:** on the **test** period, some threshold pair achieves
  retention ≥ 20% **AND** 0 assignments **AND** net P&L ≥ baseline,
  for **≥ 3 of the 4 production tickers**.
- **FAIL:** no threshold pair beats baseline retention without either an
  assignment or lower net P&L.

**Secondary (stricter) deployment gate, also immutable:** the threshold pair
selected on the **train** period must still clear retention ≥ 20%, 0
assignments, and net P&L ≥ baseline on the **test** period, per ticker. The
primary criterion above is the spec's literal wording and selects on test data;
only the secondary gate is honest walk-forward, so only tickers clearing the
secondary gate may be deployed.

### What happens on PASS

Nothing ships this week. Per-ticker: one commit each, then **2 weeks of shadow
mode** (production logs old-rule and new-rule decisions side by side) before
the live trigger is switched. Deployment requires the shadow logs.

### What happens on FAIL

Record in the graveyard as failed. Report which constraint bound (retention,
assignments, or P&L) and at which thresholds. Do not re-grid to find a
passing pair.

## Gate 2: Walk-Forward Results

[FILLED IN AFTER RUNNING — pre-registration above is frozen]

## Gate 3-5

[Deployment status]
