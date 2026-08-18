---
title: "Experiment 021: Capacity Expansion — MSFT and AMZN fail the probation gate; GOOGL blocked; KKR is capped at 700 shares by liquidity, not by validation"
date: 2026-08-16
experiment: 021
hypothesis: H24
status: completed
finding: "Clause (b) FAILS: MSFT 20.0% and AMZN 22.9% test-window loss rate against a 10% gate. Neither enters probation. The control tickers fail the same window (AAPL 11.4%, DIS 20.0%), so this is a bad eight months for everything rather than evidence those two names are worse than what is already deployed. Clause (a) NOT RUN — 5 days of GOOGL option data. The KKR capacity number is the actionable result: at the strike the strategy actually sells, KKR options trade a median of 3 contracts a day, so a 20%-of-volume cap allows 7 contracts — 700 of Dad's 10,000 shares."
---

# Experiment 021 — Capacity Expansion (H24)

**Clause (a): NOT RUN** (blocked). **Clause (b): FAIL** for both candidates.
**Deployed: the KKR liquidity cap and a `probation` tier for GOOGL** — see below.

Pre-registration: `experiments/021_capacity_expansion/README.md`, committed before the data
was touched.

## Clause (a) — GOOGL on a real option year: NOT RUN

GOOGL option data owned: **5 trading days** (2026-03-16 → 2026-03-20). Buying the year is
Databento purchase item #5; no credits were spent this session.

The spec pre-authorises the fallback and requires it be said out loud rather than skipped
silently: **GOOGL stays on extended probation** — production setting unchanged at 10% OTM /
20–45 DTE, validated on stock closes only (Exp 014), upgraded from accrued daily chain
captures at a 6-month review (~2027-02). Clause (a) is recorded PENDING.

One production change follows directly from this and is deployed: GOOGL was displayed as
tier `good`, the same badge as tickers validated on real option prices. It now carries a
distinct `probation` tier. That is a claim-accuracy fix — it only downgrades — not a
strategy change.

## Clause (b) — MSFT / AMZN probation: FAIL

Method: `experiments/014_validated_param_update/run.py::simulate_at_otm`, reused verbatim
so the candidates face exactly the yardstick that qualified the deployed tickers. A "loss"
is the stock closing above the strike 32 trading days after entry; entries every 7 trading
days; train first 67%, test last 33%; the gate is the **test** loss rate ≤ 10%.

**Primary (gating) window, 2024-08-16 → 2026-08-16:**

| Ticker | OTM | Train | Test | Verdict |
|---|---|---|---|---|
| MSFT | 15% | 59W / 5L (7.8%) | 28W / **7L (20.0%)** | **FAIL — stays out** |
| AMZN | 15% | 59W / 5L (7.8%) | 27W / **8L (22.9%)** | **FAIL — stays out** |

**Controls — already-deployed tickers through the identical harness:**

| Ticker | OTM | Train | Test |
|---|---|---|---|
| AAPL | 15% | 63W / 1L (1.6%) | 31W / 4L (**11.4%**) |
| DIS | 7% | 48W / 16L (25.0%) | 28W / 7L (**20.0%**) |

**The controls are the finding.** AAPL — deployed, tier `conservative`, the most-validated
ticker in the set — also fails a 10% gate on this window, and DIS matches MSFT/AMZN exactly.
So the candidates' failure is **not** evidence that MSFT and AMZN are worse than what Dad
already runs. It is evidence that the last eight months were a bad window for 15%-OTM
covered calls generally.

**Secondary window, 2019-01-01 → 2026-08-16 (reported, non-gating):**

| Ticker | Train | Test |
|---|---|---|
| MSFT | 6.2% | **9.2%** |
| AMZN | 10.8% | **9.9%** |

Both would have passed a ≤10% gate over the long window. The pre-registration named the
2-year window as the gate, so the verdict is FAIL and stays FAIL. Moving to the window that
gives the answer you want after seeing both is exactly the failure that produced Exp 013's
revert. The long-window numbers are recorded as context for whoever pre-registers the next
version of this test.

**No production change for MSFT or AMZN.** Neither enters the recommendation set.

### One thing Charles should know

AMZN is *already* in `TICKER_STRATEGIES` at **5% OTM, tier `untested`**, with no validation
of any kind — and it is not marked `skip`, so `get_recommended_tickers()` returns it. This
experiment just failed to validate AMZN at the far more conservative 15% OTM. The 5% entry
is more aggressive than the setting that failed, and nothing in this session's
pre-registration authorises changing it, so it was left alone. **It should probably be
marked `skip` or `probation` in a separate, deliberate commit.** Flagging rather than
acting, because the pre-registration says a clause-(b) failure means "no production change".

## KKR capacity cap — a derived number, no pass/fail

At 10,000 shares KKR would be 100 contracts. Method: for every one of the 753 trading days
we own, find the exact contract the production rule would sell (15% OTM, 20–45 DTE), take
its total daily volume across exchanges, and cap the position at 20% of that (the spec's
arbitrary starting share, labelled as such).

| Statistic | Contracts/day |
|---|---|
| Mean | 36.7 |
| Median | **3.0** |
| p25 | 1.0 |
| p75 | 10.0 |
| Days with zero volume | 0 |
| Days with a sellable contract | 753 of 753 |

| Cap basis | Contracts | Shares | Share of a 10,000-share position |
|---|---|---|---|
| Median volume × 20% | 0 | 0 | 0% |
| Mean volume × 20% | **7** | **700** | **7%** |

Mean and median differ by 12×: the volume distribution is spiky, a handful of heavy days
carrying the average. The **mean basis (7 contracts / 700 shares)** is the generous reading
and is what gets deployed; the median basis says the position should not exist at all.

**The spec's suspicion is confirmed: at Dad's size the position IS the market.** KKR's
binding constraint is liquidity, not validation — its 15% OTM setting passed walk-forward
in Exp 014, and that is irrelevant if you cannot sell 100 contracts into a 3-contract-a-day
strike without moving the price against yourself. Selling 100 contracts would be 33× the
median daily volume of that strike.

This also reframes every KKR result in the Phase 3 experiments: they are computed at 100
contracts because that is the un-capped production sizing, and **that sizing is not
executable.** KKR's backtested P&L should be read as a per-contract rate, not a dollar
figure Dad could have earned.

Deployed: `max_contracts` on KKR in `ticker_strategies.py`, applied to the Sell tab's
sizing and surfaced with its reason.

## Verdicts

- **H24(a): PENDING** — not testable without the GOOGL option year.
- **H24(b): FAIL** — MSFT 20.0%, AMZN 22.9% test loss rate against a 10% gate. No probation
  tier for either. Controls failed the same window, so this is a regime result, not a
  ticker result.
- **KKR capacity:** 7 contracts / 700 shares, derived above. Deployed.

## Reproducibility

```bash
python experiments/021_capacity_expansion/run.py
```
Raw output: `experiments/021_capacity_expansion/results.json`.
