# Experiment 020 — Partial Overwriting (H23, Tier 2)

**Pre-registered:** 2026-08-16, before any data was touched.
**Spec:** `tasks/phase3-strategy-spec.md` Part D. Needs no new data.

## Source

Sinclair, *Skewness and the Kelly Criterion*: short-call P&L is negatively skewed, and
Kelly under negative skew prescribes sizing **below** full. Partial overwriting is also the
structurally correct answer to "the income feels small" — the wrong answer (closer strikes)
re-creates the 3–5% OTM death zone from Exp 008.

Today the system implicitly overwrites **100%** of shares: one call per 100 shares, always.
Nobody chose that; it is what falls out of not having a ratio field.

## Hypothesis (H23) — immutable

> Overwriting **50–70%** of shares per ticker (vs. the implicit 100%) produces a higher
> full-period total return (premium retained + upside participation on uncovered shares −
> buyback costs) **per unit of worst drawdown**, on the 2025–26 data AND on the Part B
> stress years, than 100% overwrite — while cutting buyback friction roughly proportionally.

**PASS (immutable):** some ratio < 100% beats 100% on return/drawdown in the walk-forward
**test** period AND in ≥ 1 stress year, with absolute income ≥ **70%** of the 100% level.

The stress-year clause needs 2020/2022 option prices we do not own and did not buy (no
credits spent this session — see `experiments/019_stress_replay/README.md`). H23 is a
conjunction, so it **cannot be marked PASS this session**. The walk-forward clause is fully
testable now and is reported as a resolved sub-clause; the stress clause is recorded PENDING.

## Operational definitions (method, fixed before running — not thresholds)

- **Position basis:** 10,000 shares per ticker (Dad's actual size), so 100% overwrite =
  100 contracts, 70% = 70 contracts, 50% = 50 contracts.
- **Grid:** overwrite ratio ∈ {50%, 70%, 100%} × production per-ticker OTM%/DTE from
  `ticker_strategies.py`. One rolling call position at a time, as in production; the
  overlay P&L per contract is therefore identical across ratios and only the *mix* changes.
- **Equity curve (daily):**
  `equity(t) = shares × spot(t) + contracts × [realised call P&L to date + unrealised call
  P&L] × 100`, marked every trading day.
- **Total return:** `(equity_end − equity_start) / equity_start`.
- **Worst drawdown:** max peak-to-trough decline of that daily equity curve, in percent.
- **Primary metric:** total return ÷ |max drawdown| — reported alongside **absolute income**
  (net call P&L in dollars), because Dad cares about the size of the cheque too. Recommend
  on the ratio; Charles picks the point on the frontier.
- **Buyback friction:** total dollars paid to buy calls back, per ratio.
- **Walk-forward:** train = first 67% of the owned option window, test = last 33%.
  Nothing is selected on the test period; the grid is fixed in advance, so the test period
  is a clean comparison of three pre-specified configurations.
- **Staggered entry cohorts:** 25 start-date offsets per ticker so the comparison rests on
  hundreds of trades rather than ~12. Cohorts overlap and are NOT independent — reported as
  median plus the fraction of offsets favouring each ratio, never as a significance test.
- **Missing data:** every repricing failure counted and reported. No silent `None`.

## Known sample-size weakness (stated before running)

The owned real-price window is one year for AAPL/DIS/TMUS (three for KKR). On the
production 25-day re-entry cycle that is ~12 entries per ticker-year — well under the
research-discipline floor of 100 trades. The cohort stagger raises the trade count but not
the number of independent regimes. Any recommendation from this experiment is
regime-limited by construction and must say so.

## Deployment

Overwrite ratio becomes a per-ticker field in `ticker_strategies.py` and a share-count line
on the Sell tab — **one commit**, and only once the stress-year clause is also resolved.
A walk-forward-only result does not deploy. Fixed before seeing results.

## Reproducibility

```bash
python experiments/020_partial_overwriting/run.py
```
