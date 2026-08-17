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
finding: "H17 FAILS: 1 of 4 tickers on the spec's literal criterion, 0 of 4 on honest walk-forward. Probability triggers lose to the current copilot on 3 of 4 tickers. The premise was also wrong: once the DTE bug is fixed, distance triggers are a minority of exits — 42-95% of baseline closes come from the 75%-premium-captured take-profit rule, which the probability policy deletes. The 13% retention baseline from Exp 009 was an artefact of a simulator that evaluated every position at 0 DTE. Only AAPL's corrected baseline is measured on real fills; KKR's is carried entirely by synthetic ones."
---

# Experiment 015: Probability-Based Buyback Thresholds (H17)

**Pre-registration:** `experiments/015_probability_buybacks/README.md` (frozen before the run)
**Data:** Databento OPRA 1d OHLCV, real ex-dividend dates, `yf_proxy` stock closes. No BSM in the P&L path.
**Reproduce:** `python3 experiments/015_probability_buybacks/run.py`

> **Revision note.** These figures are from the post-review simulator. An
> independent correctness review of the first run found six defects in the
> engine — a stale-fill blind spot, an unreachable assignment branch, a
> non-sticky CLOSE_SOON clock, a look-ahead-shaped `spot()` fallback, a
> fabricated IV rank on each ticker's first 9 days, and uncounted skips. All are
> fixed and the experiment was re-run. **The verdict did not change** (1/4 and
> 0/4, as before). Individual magnitudes moved, and one earlier claim is
> retracted below.

## Verdict: FAIL

| Gate | Result | Needed |
|---|---|---|
| Primary (spec literal — selects on test) | **1 / 4 tickers** | ≥ 3 |
| Secondary (train-selected → test, honest walk-forward) | **0 / 4 tickers** | ≥ 3 |

H17 is marked failed in the graveyard. Nothing is deployed. No re-grid was run —
the pre-registration forbids searching for a passing pair after seeing the result.

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
behaviour is unchanged). The baseline here is the current copilot rules evaluated
correctly, on the same entry set as the treatment.

**Corrected baseline retention is 49.1% (AAPL) on the test period — not 13%.** The
pre-registered bar of "≥ 20% retention" was calibrated against a broken number and is
cleared by the baseline itself on 3 of 4 tickers. The bar was left immutable, which is why
the "net P&L ≥ baseline" clause is what actually does the work here.

## Method

- **Cohort simulator** (`experiments/cc_sim.py`): every trading day in the option window
  is an independent candidate entry. Exp 007-009 chained entries on an arbitrary 25-day
  interval, which subsamples the entry calendar — the survivorship bias documented in
  `tasks/lessons.md` (2026-03-23).
- Overlapping cohorts are **not independent observations.** Both arms see identical entries
  and identical price paths, so every comparison is **paired**; the t-statistics below are
  on paired per-entry P&L differences and are indicative only (overlapping windows are
  autocorrelated).
- **Entry gate:** production rule, IV rank ≥ 50, computed as in Exp 009. Days with
  insufficient history to rank are now *excluded and counted* (`gate_no_data: 9` per
  ticker) rather than admitted on a hardcoded rank of 50.
- **CLOSE_SOON** means "close within 5 calendar days," from the alert's own wording
  ("Close this week"), and is **sticky** — the live alert does not un-say itself.
  **CLOSE_NOW / EMERGENCY** close same-day. Slippage 0, matching the Exp 007-009
  convention; a 5% sensitivity is below.
- **Walk-forward:** entry dates split 67 / 33. Test decides.

## Tickers: the spec's "all 6 tradeable tickers" is not achievable

| Ticker | Databento option days | Window | Used |
|---|---|---|---|
| AAPL | 251 | 2025-03-21 → 2026-03-20 | yes |
| DIS | 251 | 2025-03-21 → 2026-03-20 | yes |
| TMUS | 251 | 2025-03-21 → 2026-03-20 | yes |
| KKR | 753 | 2023-03-21 → 2026-03-20 | yes, low confidence |
| TXN | 251 | 2025-03-21 → 2026-03-20 | reported only (production tier = skip) |
| **GOOGL** | **5** | 2026-03-16 → 2026-03-20 | **no — cannot be tested on real prices** |
| **AMZN** | **0** | — | **no — never purchased** |

## ⚠️ How much of this P&L is real?

Databento OHLCV is trade-based. When the contract does not trade on the exit date, the
buyback is filled at a carried-forward price — and the exit fill is the single number that
sets P&L. Measured on the baseline arm, test period:

| Ticker | Policy exits | Filled at a stale price | Net P&L from stale fills | Net P&L from real fills |
|---|---|---|---|---|
| AAPL | 28 | 1 (3.6%) | $13 | $389 |
| DIS | 39 | 10 (25.6%) | $1,528 | $3,730 |
| TMUS | 33 | 1 (3.0%) | $81 | −$3,953 |
| KKR | 90 | 40 (44.4%) | **$4,420** | **−$492** |
| TXN | 37 | 0 (0.0%) | $0 | −$12,558 |

**Only AAPL's baseline is a clean measurement.** KKR's +34.5% test retention is carried
entirely by synthetic fills: its real-print exits sum to **−$492**. DIS is about 29%
synthetic. Every KKR number below should be read as low-confidence, and the KKR retention
figure should not be quoted as a measurement at all.

## Results (test period)

### AAPL — 15% OTM, 20-45 DTE, 90 entries, split 2025-12-09, 2.9% missing price days

| Arm | n | Retention | Net P&L | Assign | Buybacks | Paired Δ/entry | better/worse | t |
|---|---|---|---|---|---|---|---|---|
| baseline | 30 | 49.1% | $438 | 0 | — | — | — | — |
| CN > 25% (any CS) | 30 | **59.9%** | $534 | 0 | 11 | +$3.20 | 21 / 7 | 0.69 |
| CN > 35% / 45% (any CS) | 30 | −34.1% | −$304 | 0 | 8 | −$24.80 | 20 / 8 | −2.36 |

The only arm anywhere that beats its baseline, on the only ticker with clean fills. The
paired mean difference is **+$3.20 per entry with t = 0.69** — indistinguishable from noise
on 30 overlapping test trades.

### DIS — 7% OTM, 30-60 DTE, 117 entries, split 2025-10-29, 12.4% missing

| Arm | n | Retention | Net P&L | Assign | Paired Δ | better/worse | t |
|---|---|---|---|---|---|---|---|
| baseline | 39 | **84.8%** | $5,258 | 0 | — | — | — |
| CN > 25% | 39 | 6.4% | $394 | 0 | −$124.70 | 4 / 35 | −8.64 |
| CN > 35% | 39 | 8.5% | $525 | 0 | −$121.40 | 4 / 35 | −8.10 |
| CN > 45% | 39 | 23.5% | $1,457 | 0 | −$97.50 | 8 / 30 | −5.37 |

The probability policy destroys 72–93% of DIS's net P&L, and is worse on 30–35 of 39
paired entries.

### TMUS — 15% OTM, 20-45 DTE, 113 entries, split 2025-11-11, **43.3% missing**

| Arm | n | Retention | Net P&L | Assign | Paired Δ | t |
|---|---|---|---|---|---|---|
| baseline | 38 | −98.2% | −$3,643 | 0 | — | — |
| CN > 25%, CS > 15/20% | 38 | −14.7% | −$544 | 0 | +$81.55 | 2.12 |
| CN > 35% | 38 | −34.0% | −$1,262 | 0 | +$62.70 | 1.79 |
| CN > 45% | 38 | −50.9% | −$1,887 | 0 | +$46.20 | 1.28 |

The probability policy improves TMUS — by losing less on a configuration that loses money
either way. It does not clear "net P&L ≥ baseline **and** retention ≥ 20%", because
retention stays negative.

### KKR — 15% OTM, 20-45 DTE, 379 entries, split 2025-03-19, **64.3% missing, 62 never-repriced, 44% stale exit fills**

| Arm | n | Retention | Net P&L | Assign | Paired Δ | better/worse | t |
|---|---|---|---|---|---|---|---|
| baseline | 126 | 34.5% | $7,529 | 0 | — | — | — |
| CN > 25% | 126 | 14.5% | $3,159 | 0 | −$34.70 | 42 / 51 | −2.65 |
| CN > 45% | 126 | 22.5% | $4,904 | 0 | −$20.84 | 51 / 37 | −1.60 |

The only ticker with a train-selected candidate (`CS>15% / CN>25%`), landing at 14.5%
retention on test against a 34.5% baseline. Both figures rest largely on synthetic fills.

### TXN — reference only (production tier = skip), 10% OTM

Baseline test retention **−165.4%**, net −$12,558, on 0% stale fills — the cleanest and
worst result in the set. Excluded from the pass count by pre-registration.

### Slippage sensitivity (5% on every buyback, train-selected arm)

Only KKR had a train-selected arm. At 5% slippage: treatment 10.2% retention / $2,226 vs
baseline 31.2% / $6,815. The conclusion does not change.

## ⚠️ The zero-assignment column proves nothing here

**Retraction.** An earlier revision of this document reported "2 assignments on TMUS at
CLOSE_NOW P>35%." That is withdrawn — it was produced by the non-sticky CLOSE_SOON clock,
which let positions drift to expiry. With the corrected simulator there are **zero
assignments of any kind across all 8,100 trades and all 10 arms.**

That is not evidence of safety, and it must not be read as such:

- **Early exercise is unreachable by construction.** The branch requires ITM *and* ex-div
  ≤ 1 day, and every arm returns CLOSE_NOW for exactly that state — the baseline because
  `assess_position` closes on any ITM, the probability arms because H17 deliberately keeps
  the EMERGENCY clause. So `early_assignments == 0` is a tautology for every policy tested.
  It is the correct *product* behaviour (the copilot exists to prevent this), but it is not
  a measurement.
- **Expiry assignment never occurred either**, because every arm closes long before expiry.

So the hard constraint never bound. H17 fails purely on retention and net P&L. Any future
experiment that loosens the exit rules far enough for positions to survive to an
ex-dividend or an expiry will need this constraint to actually do work.

## Why it fails — the mechanism

Ablation on the baseline arm, test period, counting which clause actually closed each trade:

| Ticker | Take-profit (75% captured) | ITM | Distance+DTE | Ex-div | Gamma | Expiry |
|---|---|---|---|---|---|---|
| AAPL | **24 / 30** | 0 | 0 | 4 | 0 | 2 |
| DIS | **37 / 39** | 2 | 0 | 0 | 0 | 0 |
| TMUS | **16 / 38** | 6 | 6 | 4 | 1 | 5 |
| KKR | **58 / 126** | 20 | 8 | 4 | 0 | 36 |

**The copilot is not primarily a distance rule. It is primarily a take-profit rule.**
Between 42% and 95% of its closes come from the "75% of premium captured" clause, which has
nothing to do with distance to strike or assignment probability.

H17 replaced the distance triggers with probability triggers — and in doing so deleted the
take-profit clause entirely, because the probability policy has no profit-taking concept.
That is why the probability arms bleed: they hold cheap winners until moneyness
deteriorates, then buy them back expensive.

Second-order: the assignment table's buckets are coarse enough that the CLOSE_SOON
threshold is nearly inert. `CS > 10%`, `> 15%` and `> 20%` give identical results in most
cells, because a bucket above 10% is nearly always above 20% too. The 9-cell grid is
effectively a 3-cell grid on CLOSE_NOW.

## What deploying it would have cost

The cohort estimator sums **overlapping** positions, so its aggregate net P&L is not a
portfolio P&L and must not be multiplied by 100 contracts. The unit that scales is the
**paired mean difference per entry per contract**:

| Ticker | DTE band | entries/yr | paired Δ/entry | Δ/contract/yr | at 100 contracts (10k shares) |
|---|---|---|---|---|---|
| AAPL | 20-45 | 11.2 | +$3.20 | +$36 | +$3,594 |
| DIS | 30-60 | 8.1 | −$97.47 | −$791 | **−$79,059** |
| TMUS | 20-45 | 11.2 | +$81.55 | +$916 | +$91,587 |
| KKR | 20-45 | 11.2 | −$20.84 | −$234 | −$23,405 |
| **net** | | | | | **−$7,283** |

Assumption stated plainly: `entries/yr = 365 / midpoint DTE`, one position at a time rolled
back-to-back. Real cadence is lower (the IV gate skipped 44–55% of candidate days), so
these are an **upper bound** on magnitude. The near-zero net is an artefact of TMUS's
+$91K offsetting DIS's −$79K, and TMUS's "gain" is losing less on a configuration that
loses money regardless. The per-ticker figures matter; the net does not.

## The finding that matters more than the verdict

**Baseline retention is not stable across the split, on any ticker:**

| Ticker | Train retention | Test retention |
|---|---|---|
| AAPL | 7.7% | 49.1% |
| DIS | 9.2% | 84.8% |
| TMUS | **+61.4%** | **−98.2%** |
| KKR | **−15.2%** | **+34.5%** |
| TXN | +16.4% | −165.4% |

Retention swings by 40–180 percentage points between halves of the same year on the same
rule and the same parameters. **The exit rule is not the dominant term in premium retention
— the regime is.** Any "$30–60K/yr from a better buyback rule" estimate built on a single
window is estimating regime luck.

Two tickers currently in production lose money under the current copilot on the test
period: **TMUS at −98.2% retention and TXN at −165.4%.** TXN is already tier `skip`. TMUS
is tier `good` with an `expected_pnl` of +$447 in `ticker_strategies.py` — a number derived
from the DTE-collapsed simulator. It should be re-derived; see the handoff below.

## Known limitations of this experiment

Stated because they were found by review rather than by us, and because they bound what
these numbers can support:

1. **The treatment arm was never evaluated out of sample.** The `ITM_PROBABILITY` table in
   `position_monitor.py` was fit (Exp 006, 2026-03-24) on the full AAPL and KKR Databento
   windows — the same windows, the same contracts, including the test segments. The
   baseline's holdout is clean; the treatment's is not. The leak favours the treatment and
   H17 still failed, so the FAIL is conservative — but a future re-test needs a table fit
   only on train data.
2. **No embargo between train and test.** The split is on entry date, so a train trade
   entered the day before the cut settles using prices up to ~45 days inside the test
   window. `select_on_train` picks the deployable arm from those metrics. Same direction:
   favours the treatment.
3. **KKR and TMUS are low confidence** on data quality alone (64% and 43% missing price
   days at 15% OTM).
4. **One year per ticker** (three for KKR). Given the train/test swings above, that is not
   enough to characterise a regime.

## What is NOT claimed

- No re-grid was run to find a passing threshold pair.
- The AAPL result (+$3.20/entry, t = 0.69) is not evidence of anything.
- Nothing here says the current copilot is well-tuned — only that this replacement is worse.
- "Zero assignments" is not a safety result. See above.

## Follow-up hypotheses (not tested here, not deployed)

1. **H21 candidate:** the take-profit clause, not the distance trigger, is the retention
   lever. Grid the capture threshold (50 / 65 / 75 / 85%). Ablating it entirely *raised*
   test retention on all four tickers (AAPL 49.1 → 57.8%, DIS 84.8 → 93.5%, KKR 34.5 →
   36.8%, TMUS −98.2 → −94.1%) with zero assignments, suggesting it fires too early.
2. **H22 candidate:** re-derive every `ticker_strategies.py` expectation on the corrected
   simulator. TMUS especially.
3. **H23 candidate:** regime-conditioned evaluation, on more than one year.

Each needs its own pre-registration and walk-forward gate before touching production.

## Graveyard

`H17: failed_layer_2 — 1/4 tickers on primary, 0/4 on walk-forward; probability triggers
lose to baseline on 3/4 tickers. Zero assignments in every arm, but that constraint was
non-binding by construction.`
