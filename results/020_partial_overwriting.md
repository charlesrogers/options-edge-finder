---
title: "Experiment 020: Partial Overwriting — FAIL. At 10,000 shares the overwrite ratio moves max drawdown by under 1pp, so 'return per unit of drawdown' cannot see it."
date: 2026-08-16
experiment: 020
hypothesis: H23
status: completed
finding: "FAIL. On the walk-forward holdout, 70% overwrite beats 100% in 4 of 25 chains on AAPL and 0 of 25 on DIS — the two tickers with usable price coverage. It wins only on TMUS (15/25), and only because TMUS's overlay lost money there; 'sell fewer of these calls' is the wrong reading of 'these calls lose money'. The structural reason: a covered-call overlay on 10,000 shares moves max drawdown by 0.04-1.2pp against a 13-49% stock drawdown, so the pre-registered metric is ~entirely the stock leg and collapses to ranking on income, which is linear in the ratio. The overwrite ratio is an income-versus-upside dial, not a risk dial."
---

# Experiment 020 — Partial Overwriting (H23)

**Verdict: FAIL** (walk-forward clause). **Deployed: nothing.**

Pre-registration: `experiments/020_partial_overwriting/README.md`, committed before the
data was touched. Engine: `experiments/cc_sim.py` (Phase 1's simulator — correct `as_of`
clock, real ex-dividend dates, simulated early and expiry assignment, one independent
cohort per trading day). Phase 3 adds only the daily equity curve, in
`experiments/lib_phase3.py`.

## What was tested

Overwrite ratios {50%, 70%, 100%} of 10,000 shares per ticker at the production
per-ticker OTM%/DTE, IV-rank ≥ 50 gate, real Databento prices, walk-forward 67/33 split on
entry date, 25 staggered sequential chains per ticker. A **0% (stock-only)** reference row
was added to the report — not part of the H23 grid, but without it nothing else is
interpretable.

The stress-year half of H23 was not tested: no 2020/2022 option prices, no purchase (see
`results/019_stress_replay.md`). H23 is a conjunction and so could not have passed
regardless — but it did not need the stress years to fail.

## Walk-forward TEST period — median across 25 chains

| Ticker | Ratio | Total return | Max DD | return/DD | Income | Buyback cost | Beats 100% |
|---|---|---|---|---|---|---|---|
| AAPL | stock only | −7.66% | 13.80% | −0.555 | $0 | $0 | — |
| AAPL | 50% | −7.58% | 13.76% | −0.551 | +$3,375 | $487 | 4 / 25 |
| AAPL | 70% | −7.55% | 13.75% | −0.549 | +$4,725 | $682 | 4 / 25 |
| AAPL | 100% | −7.51% | 13.73% | −0.547 | +$6,750 | $974 | — |
| DIS | stock only | −4.93% | 14.86% | −0.332 | $0 | $0 | — |
| DIS | 50% | −4.29% | 14.27% | −0.301 | +$10,719 | $550 | 0 / 25 |
| DIS | 70% | −4.03% | 14.04% | −0.288 | +$15,007 | $770 | 0 / 25 |
| DIS | 100% | −3.64% | 13.68% | −0.268 | +$21,438 | $1,100 | — |
| TMUS | stock only | −1.33% | 13.10% | −0.101 | $0 | $0 | — |
| TMUS | 50% | −1.41% | 13.05% | −0.109 | −$15,026 | $32,266 | 15 / 25 |
| TMUS | 70% | −1.44% | 13.04% | −0.113 | −$21,037 | $45,173 | 15 / 25 |
| TMUS | 100% | −1.49% | 13.01% | −0.117 | −$30,053 | $64,533 | — |
| KKR | stock only | −26.34% | 44.87% | −0.587 | $0 | $0 | — |
| KKR | 50% | −24.83% | 43.56% | −0.570 | +$34,802 | $63,552 | 8 / 25 |
| KKR | 70% | −24.22% | 43.03% | −0.563 | +$48,724 | $88,973 | 8 / 25 |
| KKR | 100% | −23.32% | 42.24% | −0.552 | +$69,605 | $127,104 | — |

Zero assignments in every cell, every ratio, both windows.

**The pre-registered clause:** "some ratio < 100% beats 100% on return/drawdown in the
walk-forward test AND in ≥ 1 stress year, with absolute income ≥ 70% of the 100% level."

Income scales exactly linearly with the ratio, so 70% delivers exactly 70.0% of the income
and 50% delivers 50% — the income sub-clause mechanically admits only the 70% ratio. On
the test window 70% beats 100% in **4 of 25** chains on AAPL and **0 of 25** on DIS, the
two tickers whose price coverage is good enough to carry a conclusion. **FAIL.**

## Why it fails, which is more useful than that it fails

**At 10,000 shares the overlay is a rounding error on drawdown.** Compare the stock-only
row to the 100% row:

| Ticker | Window | Max DD, stock only | Max DD, 100% overwrite | Difference |
|---|---|---|---|---|
| AAPL | full year | 22.99% | 22.99% | **0.00pp** |
| DIS | full year | 20.44% | 19.57% | 0.87pp |
| TMUS | full year | 31.63% | 30.18% | 1.45pp |
| KKR | 3 years | 49.79% | 48.68% | 1.11pp |
| AAPL | test | 13.80% | 13.73% | 0.07pp |
| DIS | test | 14.86% | 13.68% | 1.18pp |
| TMUS | test | 13.10% | 13.01% | 0.09pp |

10,000 shares of a $250 stock is a $2.5M position; a year of covered-call P&L is ±$70K.
Moving the ratio from 100% to 50% changes the denominator of "return ÷ drawdown" by
hundredths of a percentage point, so the ranking collapses onto the numerator — and the
numerator differs between ratios only by income, which is *linear in the ratio*.

**That makes the metric tautological: partial overwriting can only win when the overlay is
losing money.** Which is exactly the pattern in the table. TMUS is the one ticker where
partial wins a majority of chains (15/25), and TMUS is the one ticker whose overlay lost
money on the test window (−$30,053 on $64,533 of buybacks, retention −84.7%). The correct
response to "these calls lose money" is to stop selling *those calls*, not to sell fewer
of them.

The Sinclair/Kelly argument for sizing below full is about the risk of the **short option
position**. Here that position carries ~2% of the portfolio's risk. The argument is sound
and simply does not bind at Dad's share count. It would bind on an account where the
overlay *is* the position.

**What the overwrite ratio actually controls is income versus upside participation** — a
preference question for Charles, not a hypothesis:

- 100%: full income; calls cap the upside on all 10,000 shares in a rally.
- 70%: exactly 70% of the income; 3,000 shares participate fully in a rally.

Nothing in this experiment argues against offering the dial. It argues that the dial is not
a risk control and must not be sold as one.

## Full period (for contrast — not the pre-registered window)

| Ticker | Window | Overlay P&L at 100% | Retention | 70% beats 100% |
|---|---|---|---|---|
| AAPL | 2025-03-21 → 2026-03-20 | +$28,380 | 61.7% | 2 / 25 |
| DIS | 2025-03-21 → 2026-03-20 | +$24,430 | 17.7% | 1 / 25 |
| TMUS | 2025-03-21 → 2026-03-20 | +$14,474 | 11.1% | 25 / 25 |
| KKR | 2023-03-21 → 2026-03-20 | +$90,000 | 14.0% | 0 / 25 |

TMUS flips to 25/25 on the full window while KKR flips to 0/25 — the two tickers whose
sign changes are the two with 44% and 64% missing prices. Same tautology, same caveat.

Portfolio level (10,000 shares of each), test window: 70% beats 100% in **7 of 25** chains
including KKR, **10 of 25** excluding it. Never a majority.

## Data quality — no silent Nones

| Ticker | Cohort entries | Missing daily prices | Trades never repriced | Entries dropped as `expiry_beyond_data` | Confidence |
|---|---|---|---|---|---|
| AAPL | 99 of 251 days | **2.5%** | 0 | 14 | good |
| DIS | 126 of 251 | **14.3%** | 0 | 15 | acceptable |
| TMUS | 122 of 251 | **44.0%** | 2 | 9 | low |
| KKR | 388 of 753 | **63.7%** | 61 | 19 | low |

Databento OHLCV is trade-based: a strike that did not trade has no bar. Every missing
lookup carries the previous price forward and is counted. Entries whose expiry falls
outside the option window are dropped rather than truncated, so no partial trade is mixed
into the P&L.

Conclusions rest on **AAPL and DIS**. TMUS and KKR are directional at best — and both of
them changed the *sign* of their overlay P&L between two simulators built the same week
(see below), which is what a 44–64% missing-price rate looks like in practice.

## Simulator sensitivity — read this before quoting any per-ticker dollar figure

This experiment was first run on a simulator written for Phase 3, then re-run on
`cc_sim.py` (Phase 1's engine, which adds real ex-dividend dates, simulated assignment, a
5-day CLOSE_SOON arming window, and an every-day cohort calendar). Between the two:

- TMUS's overlay went from **+$30K to −$30K** on the test window.
- KKR's went from **−$36K to +$70K**.
- AAPL and DIS kept their signs.

Per CLAUDE.md's two-reversal rule, that is a stop sign for per-ticker dollar claims on the
thin names: **do not quote a TMUS or KKR expected P&L from any single-year backtest.**
What survived both engines unchanged is the structural finding above — drawdown is
near-invariant to the overwrite ratio — because that follows from position sizes, not from
exit modelling.

## Descriptive control: the IV-rank gate is not uniformly good

Exp 009 put the IV-rank ≥ 50 entry gate into production on the claim that it triples P&L,
measured on one un-staggered path. Same engine, same chains, gate on vs off, full period,
100% overwrite:

| Ticker | Gate ON | Gate OFF | Cohort entries ON / OFF |
|---|---|---|---|
| AAPL | +$28,380 | +$41,253 | 99 / 231 |
| DIS | +$24,430 | −$3,600 | 126 / 229 |
| TMUS | +$14,474 | +$91,672 | 122 / 231 |
| KKR | +$90,000 | −$14,709 | 388 / 733 |

It rescues DIS and KKR and costs AAPL and TMUS. This is a **descriptive control, not a
hypothesis test** — no threshold was pre-registered and nothing deploys off it. It is
flagged as the highest-value follow-up on the list: the gate is live on every ticker today
and its evidence base is one un-staggered path from Exp 009.

## Sample size

25 overlapping chains per ticker-window give 44–307 trades — above the 100-trade floor in
raw count, but the chains share one year of tape (three for KKR) and are **not
independent**. Everything here is one regime, and a down-trending one. The regime where
the Kelly/skew argument is supposed to bite — a sharp crash with a V-recovery — is exactly
the data that was not purchased.

## Verdict

**H23: FAIL.** No `overwrite_pct` field is being added to `ticker_strategies.py`.

The caveat, stated because the failure is regime-limited: what this establishes robustly is
not "100% is optimal" but "at 10,000 shares the overwrite ratio is an income-versus-upside
dial, not a risk dial." That conclusion is structural, so the stress years will not
overturn it — they can only change which ratio makes more money, not whether the ratio
controls drawdown.

## Reproducibility

```bash
python experiments/020_partial_overwriting/run.py
```
Raw output: `experiments/020_partial_overwriting/results.json`.
