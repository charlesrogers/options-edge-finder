---
title: "Experiment 015: Probability-Based Buyback Thresholds"
date: 2026-08-16
experiment: 015
signal_id: H17
tier: 1
hypotheses: ["H17: probability triggers raise retention to >=20% with 0 assignments and net P&L >= baseline"]
status: completed
verdict: FAIL
deployed: false
finding: "H17 FAILS: 1 of 4 tickers on the spec's literal criterion, 0 of 4 on honest walk-forward. Replacing distance triggers with probability triggers is worse than the current copilot on 3 of 4 tickers and introduces 2 assignments on TMUS. The premise was also wrong: once the DTE bug is fixed, distance triggers are a minority of exits — 70-95% of baseline closes come from the 75%-premium-captured take-profit rule, which the probability policy deletes. The 13% retention baseline from Exp 009 was an artefact of a simulator that evaluated every position at 0 DTE."
---

# Experiment 015: Probability-Based Buyback Thresholds (H17)

**Pre-registration:** `experiments/015_probability_buybacks/README.md` (frozen before the run)
**Data:** Databento OPRA 1d OHLCV, real ex-dividend dates, `yf_proxy` stock closes. No BSM in the P&L path.
**Reproduce:** `python3 experiments/015_probability_buybacks/run.py`

## Verdict: FAIL

| Gate | Result | Needed |
|---|---|---|
| Primary (spec literal — selects on test) | **1 / 4 tickers** | ≥ 3 |
| Secondary (train-selected → test, honest walk-forward) | **0 / 4 tickers** | ≥ 3 |

H17 is marked failed in the graveyard. Nothing is deployed. No re-grid was run — the
pre-registration forbids searching for a passing pair after seeing the result.

## Before the result: a bug that invalidates the premise

The spec's motivating number — "premium retention is 13%, 74% of gross premium goes to
buyback costs" — comes from `results/009_crush_it.md`. It is not usable.

`assess_position()` computed DTE as `max(0, expiry - datetime.now())`. Every backtest fed
it a historical expiry, so **DTE was 0 on every observation in Experiments 007, 008, 009,
010, 012 and 013.** Every DTE-conditional rule was unreachable:

| Rule | Under the bug |
|---|---|
| CLOSE_SOON: within 2% of strike with 7+ DTE | never reachable |
| CLOSE_SOON: within 3% with < 7 DTE | shadowed by the rule below |
| WATCH: 2-5% from strike, 14+ DTE / 7+ DTE | never reachable |
| CLOSE_NOW: DTE < 3 **and** within 3% | permanently armed |

What Exp 007-013 actually measured was "close if within 3% of strike, or if 75% of premium
is captured." Those experiments also passed `ex_div_date=None`, so the EMERGENCY rule and
both ex-dividend rules never fired in any backtest either.

Fixed in commit `8040440` (`as_of` parameter, defaulting to `datetime.now()` so live
behaviour is unchanged). The baseline in this experiment is the current copilot rules
evaluated correctly, on the same entry set as the treatment.

**Corrected baseline retention is 52.5% (AAPL), 86.5% (DIS), 34.1% (KKR) on the test
period — not 13%.** The pre-registered bar of "≥ 20% retention" was calibrated against a
broken number and is cleared by the baseline itself on 3 of 4 tickers. The bar was left
immutable, which is why the "net P&L ≥ baseline" clause is what actually does the work here.

## Method

- **Cohort simulator** (`experiments/cc_sim.py`): every trading day in the option window
  is an independent candidate entry. Exp 007-009 chained entries on an arbitrary 25-day
  interval, which subsamples the entry calendar — the survivorship bias documented in
  `tasks/lessons.md` (2026-03-23).
- Overlapping cohorts are **not independent observations.** Both arms see identical entries
  and identical price paths, so every comparison is **paired**; the t-statistics below are
  on paired per-entry P&L differences and are indicative only (overlapping windows are
  autocorrelated).
- **Entry gate:** production rule, IV rank ≥ 50, computed exactly as Exp 009.
- **Assignment** is simulated, not inferred: a position assigns if it is open the day before
  an ex-dividend with extrinsic < dividend (rational early exercise, Natenberg Ch. 12), or
  open at expiry above the strike.
- **CLOSE_SOON** means "close within 5 calendar days," taken from the alert's own wording
  ("Close this week"), applied identically to both arms. **CLOSE_NOW / EMERGENCY** close
  same-day. Slippage 0, matching the Exp 007-009 convention; a 5% sensitivity is below.
- **Walk-forward:** entry dates split 67 / 33. Test decides.

## Tickers: the spec's "all 6 tradeable tickers" is not achievable

| Ticker | Databento option days | Window | Used |
|---|---|---|---|
| AAPL | 251 | 2025-03-21 → 2026-03-20 | yes |
| DIS | 251 | 2025-03-21 → 2026-03-20 | yes |
| TMUS | 251 | 2025-03-21 → 2026-03-20 | yes |
| KKR | 753 | 2023-03-21 → 2026-03-20 | yes (low confidence, 63.7% missing) |
| TXN | 251 | 2025-03-21 → 2026-03-20 | reported only (production tier = skip) |
| **GOOGL** | **5** | 2026-03-16 → 2026-03-20 | **no — cannot be tested on real prices** |
| **AMZN** | **0** | — | **no — never purchased** |

## Results (test period)

Baseline = current copilot, correctly evaluated. Retention = net P&L / gross premium.

### AAPL — 15% OTM, 20-45 DTE, 99 entries, split 2025-11-20, 2.5% missing price days

| Arm | n | Retention | Net P&L | Assign | Buybacks | Paired Δ/entry | better/worse | t |
|---|---|---|---|---|---|---|---|---|
| baseline | 33 | 52.5% | $492 | 0 | — | — | — | — |
| CN > 25% (any CS) | 33 | **57.9%** | $542 | 0 | 13 | +$1.5 | 19 / 9 | 0.36 |
| CN > 35% / 45% (any CS) | 33 | −30.7% | −$287 | 0 | 9 | −$23.6 | 19 / 9 | −2.47 |

The only arm anywhere that beats its baseline. The paired mean difference is **+$1.50 per
entry with t = 0.36** — indistinguishable from noise on 33 overlapping test trades.

### DIS — 7% OTM, 30-60 DTE, 126 entries, split 2025-10-24, 14.3% missing

| Arm | n | Retention | Net P&L | Assign | Paired Δ | better/worse | t |
|---|---|---|---|---|---|---|---|
| baseline | 42 | **86.5%** | $5,873 | 0 | — | — | — |
| CN > 25% | 42 | 6.5% | $443 | 0 | −$129.3 | 4 / 38 | −9.55 |
| CN > 35% | 42 | 9.2% | $625 | 0 | −$125.0 | 5 / 37 | −8.75 |
| CN > 45% | 42 | 26.1–26.5% | $1,775–1,799 | 0 | −$97.0 | 16 / 26 | −5.22 |

The probability policy destroys 70–92% of DIS's net P&L. Worse on 26–38 of 42 paired entries.

### TMUS — 15% OTM, 20-45 DTE, 122 entries, split 2025-11-04, **44.0% missing**

| Arm | n | Retention | Net P&L | Assign | Paired Δ | t |
|---|---|---|---|---|---|---|
| baseline | 41 | −79.7% | −$3,073 | 0 | — | — |
| CN > 25% | 41 | −17.9% | −$690 | 0 | +$58.1 | 1.56 |
| CN > 35% | 41 | −46.6% | −$1,795 | **2** | +$31.2 | 0.89 |
| CN > 45% | 41 | −88.2% | −$3,402 | **2** | −$8.0 | −0.22 |

Loosening past 25% **lets assignments through** — the hard constraint. TMUS also has the
worst data: 44% of position-days had no trade in that contract.

### KKR — 15% OTM, 20-45 DTE, 388 entries, split 2025-03-14, **63.7% missing, 61 never-repriced trades**

| Arm | n | Retention | Net P&L | Assign | Paired Δ | better/worse | t |
|---|---|---|---|---|---|---|---|
| baseline | 129 | 34.1% | $7,616 | 0 | — | — | — |
| CN > 25% | 129 | 13.9% | $3,103 | 0 | −$35.0 | 42 / 51 | −2.64 |
| CN > 45% | 129 | 21.5% | $4,805 | 0 | −$21.8 | 51 / 32 | −1.74 |

The only ticker with a train-selected candidate (`CS>10% / CN>25%`), and it lands at 13.9%
retention on test against a 34.1% baseline — a clear secondary-gate failure.

### TXN — reference only (production tier = skip), 10% OTM

| Arm | n | Retention | Net P&L | Paired Δ | t |
|---|---|---|---|---|---|
| baseline | 40 | **−147.8%** | −$11,888 | — | — |
| CN > 25% | 40 | −8.8% | −$706 | +$279.6 | 5.95 |

TXN is the one place the probability policy is decisively better — and it is better at
losing less money on a ticker production already skips. It is excluded from the pass count
by pre-registration.

### Slippage sensitivity (5% on every buyback, train-selected arm)

Only KKR had a train-selected arm. At 5% slippage: treatment 9.6% retention / $2,142 vs
baseline 30.8% / $6,881. The conclusion does not change.

## Why it fails — the mechanism

Ablation on the baseline arm, test period, counting which clause actually closed each trade:

| Ticker | Take-profit (75% captured) | ITM | Distance+DTE | Ex-div | Expiry |
|---|---|---|---|---|---|
| AAPL | **24 / 33** | 0 | 0 | 4 | 5 |
| DIS | **40 / 42** | 2 | 0 | 0 | 0 |
| TMUS | **16 / 41** | 6 | 5 | 4 | 10 |
| KKR | **57 / 129** | 22 | 6 | 4 | 40 |

**The copilot is not primarily a distance rule. It is primarily a take-profit rule.**
Between 39% and 95% of its closes come from the "75% of premium captured" clause, which has
nothing to do with distance to strike or assignment probability.

H17 replaced the distance triggers with probability triggers — and in doing so deleted the
take-profit clause entirely, because the probability policy has no profit-taking concept.
That is why the probability arms bleed: they hold cheap winners until moneyness deteriorates,
then buy them back expensive.

Second-order: the assignment table's buckets are coarse enough that the CLOSE_SOON threshold
is almost inert. `CS > 10%`, `CS > 15%` and `CS > 20%` produce identical results in 26 of the
30 production-ticker cells, because a bucket above 10% is nearly always above 20% too. The
9-cell grid is effectively a 3-cell grid on CLOSE_NOW.

## The finding that matters more than the verdict

**Baseline retention is not stable across the split, on any ticker:**

| Ticker | Train retention | Test retention |
|---|---|---|
| AAPL | 21.3% | 52.5% |
| DIS | 9.2% | 86.5% |
| TMUS | **+67.7%** | **−79.7%** |
| KKR | **−13.1%** | **+34.1%** |
| TXN | +16.4% | −147.8% |

Retention swings by 80–160 percentage points between halves of the same year on the same
rule and the same parameters. **The exit rule is not the dominant term in premium retention
— the regime is.** Any "$30–60K/yr from a better buyback rule" estimate built on a single
window is estimating regime luck.

Two tickers currently in production lose money under the current copilot on the test period:
**TMUS at −79.7% retention (−$3,073 per contract-year) and TXN at −147.8%.** TXN is already
tier `skip`. TMUS is tier `good` with an `expected_pnl` of +$447 in `ticker_strategies.py`.
That expectation came from the DTE-collapsed simulator. It should be re-derived; see the
handoff below.

## Data quality

| Ticker | Missing price days | Never-repriced trades | Entries rejected (expiry beyond data) |
|---|---|---|---|
| AAPL | 2.5% | 0 | 14 |
| DIS | 14.3% | 0 | 15 |
| TMUS | 44.0% | 2 | 9 |
| KKR | 63.7% | 61 | 19 |
| TXN | 15.8% | 0 | 13 |

Databento OHLCV is trade-based: a strike that did not trade has no bar. Missing days carry
the last known price forward and are counted, never skipped. **KKR and TMUS conclusions are
low confidence** — at 15% OTM those contracts barely trade.

## What is NOT claimed

- No re-grid was run to find a passing threshold pair. The pre-registration forbids it.
- The AAPL result (+$1.50/entry, t = 0.36) is not evidence of anything.
- Nothing here says the current copilot is well-tuned — only that this specific replacement
  is worse.

## Follow-up hypotheses (not tested here, not deployed)

1. **H21 candidate:** the take-profit clause, not the distance trigger, is the retention
   lever. Grid the capture threshold (50 / 65 / 75 / 85%) against the current rule set.
   Ablating it entirely *raised* test retention on all four tickers (AAPL 52.5 → 59.8%,
   DIS 86.5 → 94.1%, KKR 34.1 → 37.9%, TMUS −79.7 → −77.6%) with zero assignments, which
   suggests it may be firing too early rather than too late.
2. **H22 candidate:** re-derive every `ticker_strategies.py` expectation on the corrected
   simulator. The current numbers were produced at DTE = 0 with no ex-dividend dates.
3. **H23 candidate:** regime-conditioned evaluation. Any retention claim needs more than one
   year, given the train/test swings above.

Each needs its own pre-registration and walk-forward gate before touching production.

## Graveyard

`H17: failed_layer_2 — 1/4 tickers on primary, 0/4 on walk-forward; probability triggers
lose to baseline on 3/4 tickers and admit 2 assignments on TMUS.`
