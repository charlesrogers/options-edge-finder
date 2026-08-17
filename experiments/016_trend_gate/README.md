---
experiment: 016
signal_id: H18
tier: 2
title: "Trend Gate on Call Entry"
date: 2026-08-16
status: pre-registered
prior_experiment: 014
changes_production: true
---

# Experiment 016: Trend Gate (H18)

## Gate 1: Pre-Registration

**Nothing below this line may be edited after the run script is executed.**

### Hypothesis

Suppressing new call sales when the stock is in a strong uptrend reduces the
per-ticker **loss rate** by **≥ 30% relative** while skipping **≤ 25%** of
otherwise-valid entries, on walk-forward test data.

### Source

Sinclair & Mack (2024), Ch. 10 & 15 — momentum persistence is real, and
options on trending stocks are systematically *cheap* because BSM is "fooled by
trends." Selling calls on a trending stock is selling underpriced insurance.
This is the theoretical backbone of our worst empirical result (GOOGL, 48% loss
rate in Exp 013 before it was widened to 10% OTM in Exp 014).

### Definition of a "loss"

A trade whose net P&L is negative under the **current production copilot exit
rules** (baseline arm of Exp 015 — `assess_position` with `as_of` and real
ex-div dates). Loss rate = losing trades / total trades. This is a strictly
better definition than Exp 014's, which called any trade "lost" if the stock
finished above the strike, ignoring premium and ignoring the copilot entirely.

### Method

- **Signal:** stock data only (`yf_proxy`, 5y daily, free). The gate is
  evaluated on the entry date using only data available on or before that date.
- **P&L:** the Exp 015 simulator with the **baseline** exit policy, so the only
  variable is which entries are taken.
- **Candidate gates (arbitrary starting values, NOT derived) — tested
  independently, no combinations (that surface overfits):**
  - 20-day return > +5%
  - 20-day return > +8%
  - 60-day return > +12%
  - 60-day return > +18%
  - 252-day rolling return autocorrelation percentile > 70th
  - 252-day rolling return autocorrelation percentile > 85th
- **Walk-forward:** entry dates 67/33. Test period decides.
- **Baseline for each ticker:** the same entry set with no gate.

### Control tickers (bettybot pattern)

**KKR and DIS are controls.** They already run near-zero loss rates at their
production parameters. A gate that "improves" an already-clean ticker is
evidence of a framework bug, not a discovery.

- Control condition: gate changes control-ticker loss count by **≤ ±1 loss**.
- If a control ticker moves by more than 1 loss, the run is treated as
  **framework-suspect** and the experiment reports NO FINDING regardless of what
  the target tickers did. Investigate the simulator first.

### Tickers

Loss-bearing targets: **AAPL, TMUS** (+ TXN, reported but not counted — it is
production-skip). Controls: **KKR, DIS**.

GOOGL — the ticker that motivated this hypothesis — has 5 days of Databento
option data and **cannot be tested on real prices.** A stock-only proxy for
GOOGL is reported as a *directional estimate only, not deployable*, per
`tasks/lessons.md` 2026-03-23.

### Pass / Fail (IMMUTABLE)

- **PASS:** ≥ 30% relative loss-rate reduction on **≥ 2 loss-bearing tickers**,
  **AND** ≤ 25% of entries skipped, **AND** control tickers move by ≤ ±1 loss,
  **AND** net P&L does not fall by more than the mean P&L of a winning trade ×
  the number of winning trades skipped (i.e. the gate may only give up the fair
  share of the winners it skipped).
- **FAIL:** loss reduction < 30% relative, **or** > 25% of entries skipped,
  **or** a control ticker shifts by more than ±1 loss.

### What happens on PASS

The gate becomes an additional entry condition in `ticker_strategies.py` / the
Sell tab, per-ticker, one commit each, after the walk-forward pass. Not this
week.

## Gate 2: Walk-Forward Results

**VERDICT: FAIL.** Full write-up: `results/016_trend_gate.md`.

No gate cleared the bar. Five of six gates make the loss rate *worse* on the loss-bearing
tickers — they suppress winners without removing losses.

| Gate | AAPL rel. reduction / skip | TMUS | Targets | Controls |
|---|---|---|---|---|
| r20 > +5% | −22% / 18% | −11% / 10% | 0/2 | OK |
| r20 > +8% | 0% / 0% | −11% / 10% | 0/2 | OK |
| r60 > +12% | −14% / 12% | 0% / 0% | 0/2 | OK |
| r60 > +18% | −3% / 3% | 0% / 0% | 0/2 | OK |
| autocorr pctile > 70 | +100% / 21% | 0% / 0% | 1/2 | OK (KKR −1) |
| autocorr pctile > 85 | 0% / 0% | 0% / 0% | 0/2 | OK |

**The control design worked.** KKR and DIS moved by at most 1 loss on every gate, so the
framework is sound and the null result is trustworthy. The single AAPL hit rests on 4 losses
in 33 trades, nudges a control the same direction, and is the *worst* gate on GOOGL.

GOOGL, the ticker that motivated this hypothesis, was tested stock-only and labelled
directional-estimate-only as pre-registered. It does not support the hypothesis either.

**Nothing deployed.** `ticker_strategies.py` is unchanged.
