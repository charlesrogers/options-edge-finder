---
title: "Experiment 023: The IV-rank gate on trial — clause 1 PASSES for AAPL, DIS and KKR, fails for TMUS; DIS moves to 75"
date: 2026-08-17
experiment: 023
hypothesis: H26
status: completed
finding: "The first pre-registered clause to pass in this whole programme. The live IV-rank >= 50 entry gate beats no gate on holdout mean P&L per entry for AAPL (+20.7%), DIS (+90.4%) and KKR (+286.2%), and fails outright for TMUS, where the gate systematically blocks the winners. Clause 2 passes only for DIS, whose train-window-selected threshold of 75 beats the global 50 by 58% on the holdout — deployed, with the caveat that the DIS holdout at 75 is five trades. AAPL's pass is unsettled: the gate wins per entry and loses per year, because it removes 132 entries that averaged +$17 each."
---

# Experiment 023 — The IV-Rank Entry Gate on Trial (H26)

**Pre-registered:** `experiments/023_iv_rank_gate/README.md`, commit `01c40bf`, pushed
2026-08-17T21:56:29Z — before this experiment's `run.py` existed.
**Engine:** `experiments/cc_sim.py`. Real Databento OPRA prices. No money spent.

## Why

`DEFAULT_IV_THRESHOLD = 50` is live on every ticker (`paper_trade_logger.py` refuses to
open below it) and its entire evidence base was Experiment 009 — one un-staggered path on
the simulator with the broken DTE clock, claiming "+204% average P&L". Exp 019b's
descriptive control then observed the gate rescuing DIS and KKR while costing AAPL and
TMUS. This is the pre-registered version of that observation.

Only the gate varies between arms: same strikes, same DTE band, same production copilot,
same walk-forward cut date (67% of the option-day window, applied as a calendar cut so
arms with different entry counts still split at the same moment).

## Clause 1 — does the gate earn its place? (holdout, mean net P&L per entry)

| Ticker | No gate | IV ≥ 50 (live) | Relative | Verdict |
|---|---:|---:|---:|---|
| AAPL | $12.40 (n=63) | **$14.97** (n=34) | +20.7% | **PASS** |
| DIS | $60.48 (n=61) | **$115.17** (n=26) | +90.4% | **PASS** |
| TMUS | −$21.88 (n=63) | **−$98.96** (n=34) | worse, and negative | **FAIL** |
| KKR | $15.51 (n=229) | **$59.90** (n=123) | +286.2% | **PASS** |
| *TXN (control, tier=skip)* | *−$151.95* | *−$354.90* | *worse* | *FAIL, not gating* |

Margin required: +10% relative, fixed in advance. Where the baseline is ≤ 0 the
pre-registration required an improvement of ≥ 10% of its magnitude **and** a positive
result — TMUS and TXN fail on both counts, so no ratio is quoted for them (the H23 lesson:
never let a ratio metric report a sign it cannot support).

**What the gate actually threw away**, over the full window:

| Ticker | Entries blocked | Mean P&L of blocked entries | Winners / losers blocked |
|---|---:|---:|---|
| AAPL | 132 | **+$17.24** | 127 W / 5 L |
| DIS | 103 | −$2.94 | 65 W / 38 L |
| TMUS | 109 | **+$48.36** | 103 W / 6 L |
| KKR | 345 | −$21.00 | 197 W / 127 L |

TMUS is unambiguous: the gate blocks 109 entries that averaged +$48 and keeps the ones that
lose. On TMUS the IV-rank gate is not a filter, it is an anti-filter.

## The contradiction inside AAPL's pass (reported, not resolved)

AAPL passes the pre-registered clause and simultaneously loses money by every income
measure:

| AAPL, holdout | No gate | IV ≥ 50 |
|---|---:|---:|
| Mean P&L per entry (**the registered metric**) | $12.40 | **$14.97** |
| Total P&L over the holdout | **$781** | $509 |
| Annualised $/contract, 25 sequential chains (full window) | **$453** | $299 |

Both statements are true. The gate improves the *quality* of an entry and reduces the
*number* of entries, and an account that can hold one call at a time is paid on the second
axis as much as the first. The pre-registration fixed mean-per-entry as the metric before
any of this was visible, so the verdict stands as PASS — but AAPL's pass should be treated
as **unsettled**, and the honest one-line summary is: *the gate is evidenced for DIS and
KKR, contradicted for TMUS, and ambiguous for AAPL.*

DIS and KKR do not have this problem — their chain view agrees with the per-entry view
(DIS $267/yr gated vs −$42/yr ungated; KKR $316/yr vs −$50/yr).

## Clause 2 — is 50 the right number, per ticker?

Threshold chosen from {25, 50, 75} on the **training window only**, scored on the holdout:

| Ticker | Train-selected | Train mean/entry | Holdout: selected vs live 50 | Relative | Verdict |
|---|---|---:|---|---:|---|
| AAPL | iv25 | $21.18 | $13.92 vs $14.97 | −7.0% | FAIL |
| DIS | **iv75** | $84.91 | **$182.06 vs $115.17** | **+58.1%** | **PASS** |
| TMUS | iv50 (= live) | — | identical | 0% | FAIL |
| KKR | iv50 (= live) | — | identical | 0% | FAIL |

AAPL is the interesting failure: the train window picked the *loosest* threshold, and it
lost on the holdout. That is the walk-forward split doing its job.

## Deployed

**DIS `iv_threshold = 75`** — one commit, per the pre-registered rule (clause 2 pass,
threshold ≥ 50 so the change is *restricting*, zero holdout assignments in both arms).

The caveats belong next to the number, not in a footnote:

- The DIS holdout at IV ≥ 75 is **5 trades**. Five. The pre-registration set no minimum
  sample and authorised this deployment; the deployment is being made as registered rather
  than quietly withheld, but it is the thinnest evidence behind any live parameter in this
  system.
- The train window is not thin (43 entries, and 75 was the best of the three by a wide
  margin), which is the only reason this is defensible at all.
- DIS runs 77% real-fill exits (Exp 022) — better than TMUS or KKR, worse than AAPL.
- Effect: DIS sells calls on roughly 48 days a year instead of 126. **Review when the daily
  chain capture has accrued another year of real DIS prices.**

Nothing else deploys. Per the pre-registration:

- **TMUS clause-1 FAIL deploys nothing.** The gate is now formally *unevidenced* for TMUS —
  in fact contradicted — but removing it would increase how often Dad sells TMUS calls, and
  a failed test of a restriction is not evidence for its opposite. Recorded in TMUS's note;
  a removal needs its own experiment with its own thresholds.
- **AAPL clause-2 winner (iv25) is looser than 50 and was not deployed** even though it was
  train-selected, and it lost on the holdout anyway.

## Honest limits

One year of real prices for AAPL/DIS/TMUS/TXN, three for KKR, one favourable regime.
Holdouts are ~4 months for the one-year tickers and thinner still in the hard-gating arms
(AAPL iv75 n=17, DIS iv75 n=5). Cohorts overlap and are not independent observations;
nothing here is a significance test. "IV rank" is production's own proxy — ATM call price
as a percent of spot, ranked against its trailing 60 observations — reproduced rather than
reinvented so this tests the live gate, not an idealised one. Repricing coverage per arm is
in `results.json` and moves by less than 2pp between arms, so no verdict here is an artefact
of one arm having better data than another.

## Reproduce

```bash
python3 experiments/023_iv_rank_gate/run.py   # ~12 min, all data local
```

Raw output: `experiments/023_iv_rank_gate/results.json`.

---

# Addendum, 2026-08-17 (later session) — re-run on the fully corrected engine

Exp 023 was measured on the same branch as Exp 022, which lacks commit `bbbddaa` and its
six reviewed simulator fixes — including an engine that fabricated an IV rank of `50.0`
when it had fewer than 10 observations, i.e. an invented value that **passes the very gate
this experiment is testing**. That made re-running H26 mandatory, not optional.

**H26 reproduces exactly.** The re-run, with the baseline window pinned to
`WINDOW_LEGACY_PRE_STRESS`, returns a byte-identical verdict object:

| | PR #4 engine | Corrected engine |
|---|---|---|
| Clause 1 (gate earns its place) | AAPL ✅ DIS ✅ TMUS ❌ KKR ✅ | **identical** |
| Clause 2 (per-ticker beats 50) | DIS ✅ only | **identical** |
| Deployment | DIS `iv_threshold = 75` | **identical** |
| Assignments | 0 | **0** |

Magnitudes moved — KKR's clause-1 margin went from +286.2% to +130.1%, and the entry counts
fall by the expected nine per ticker — but no verdict, no threshold and no deployment
changed. **DIS at IV ≥ 75 stands as shipped.**

This matters more than a routine confirmation. Exp 022's per-ticker tolerance verdicts
reversed under the same engine change while Exp 023's did not. A result that survives the
removal of six defects in the instrument that produced it is a substantially stronger result
than one that does not — and H26 clause 1 remains the first pre-registered clause in this
programme to pass.

The one caveat PR #4 raised is unchanged by the re-run: **the DIS holdout at threshold 75 is
five trades.** Small-sample, pre-registered, restricting, and reversible in one commit.
