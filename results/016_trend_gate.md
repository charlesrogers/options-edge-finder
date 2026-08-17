---
title: "Experiment 016: Trend Gate on Call Entry"
date: 2026-08-16
experiment: 016
signal_id: H18
tier: 2
hypotheses: ["H18: suppressing call sales in strong uptrends cuts loss rate >=30% relative while skipping <=25% of entries"]
status: completed
verdict: FAIL
deployed: false
finding: "H18 FAILS on all six candidate gates. Five of six make the loss rate WORSE on the loss-bearing tickers. The one apparent hit — 252-day autocorrelation percentile > 70 removing all four AAPL test losses — rests on 4 losses in 33 trades and simultaneously moves a control ticker, which is exactly the pattern the control design exists to catch. The controls behaved correctly throughout (KKR/DIS moved by at most 1 loss), so the framework is sound and the answer is simply no."
---

# Experiment 016: Trend Gate on Call Entry (H18)

**Pre-registration:** `experiments/016_trend_gate/README.md` (frozen before the run)
**Reproduce:** `python3 experiments/016_trend_gate/run.py`

## Verdict: FAIL

No gate cleared the pre-registered bar (≥ 30% relative loss-rate reduction on ≥ 2
loss-bearing tickers, ≤ 25% entries skipped, controls unmoved).

| Gate | AAPL | TMUS | Targets qualifying | Controls | Verdict |
|---|---|---|---|---|---|
| 20d return > +5% | −22% rel / skip 18% | −11% rel / skip 10% | 0 / 2 | OK | FAIL |
| 20d return > +8% | 0% / skip 0% | −11% rel / skip 10% | 0 / 2 | OK | FAIL |
| 60d return > +12% | −14% rel / skip 12% | 0% / skip 0% | 0 / 2 | OK | FAIL |
| 60d return > +18% | −3% rel / skip 3% | 0% / skip 0% | 0 / 2 | OK | FAIL |
| autocorr pctile > 70 | **+100% rel / skip 21%** | 0% / skip 0% | 1 / 2 | OK (KKR −1) | FAIL |
| autocorr pctile > 85 | 0% / skip 0% | 0% / skip 0% | 0 / 2 | OK | FAIL |

Positive = loss rate reduced. **Five of six gates make the loss rate worse**, i.e. the trades
they suppress were disproportionately winners.

## Method

- The gate only affects entry, so the simulation was run **once** per ticker with the
  production exit policy and the production IV gate, and each candidate gate was applied by
  partitioning those trades into kept and skipped. The kept trades are therefore
  bit-identical to the ungated ones — no second simulation, no chance of the arms diverging
  for an unrelated reason.
- **Loss** = negative net P&L under the production copilot (Exp 015's corrected baseline
  arm). This is stricter than Exp 014's definition, which called any trade "lost" if the
  stock finished above the strike — ignoring premium and ignoring the copilot.
- All trend features use only closes up to and including the entry date. The autocorrelation
  percentile is an **expanding** rank, not a full-sample rank; a full-sample rank would leak
  the future into the gate and make the walk-forward split meaningless.
- Walk-forward 67 / 33 on entry dates. Test decides.

## Control check (run first, by design)

KKR and DIS already run near-zero loss rates. If a gate "improves" them, the framework is
broken, not the market.

| Gate | KKR Δ losses | DIS Δ losses | Status |
|---|---|---|---|
| r20 > 5% / 8%, r60 > 12% / 18% | 0 | 0 | OK |
| autocorr pctile > 70 / 85 | −1 | 0 | OK (within ±1 tolerance) |

DIS skipped **zero** entries under every gate — its test window contains no strong-uptrend
days by any of these definitions. KKR skipped 9–18% of entries and its loss count did not
move at all under the return-based gates. The controls behaved exactly as the design
predicted, which is the reason to trust the target results.

## Target results in detail (test period)

### AAPL — 15% OTM, 99 entries, split 2025-11-20, ungated 4/33 losses (12.1%), net $492

| Gate | Skip | Losses | Rel. reduction | Net P&L | P&L given up | Winners' fair share |
|---|---|---|---|---|---|---|
| r20 > 5% | 18.2% | 4 → 4 | −22.3% | $384 | $108 | $144 |
| r20 > 8% | 0.0% | 4 → 4 | 0% | $492 | $0 | $0 |
| r60 > 12% | 12.1% | 4 → 4 | −14.0% | $443 | $48 | $96 |
| r60 > 18% | 3.0% | 4 → 4 | −3.3% | $482 | $10 | $24 |
| autocorr > 70 | 21.2% | **4 → 0** | +100% | $590 | −$98 | $72 |
| autocorr > 85 | 0.0% | 4 → 4 | 0% | $492 | $0 | $0 |

The return gates skip trades without removing a single loss — the loss *rate* rises purely
because the denominator shrank.

### TMUS — 15% OTM, 122 entries, split 2025-11-04, ungated 13/41 losses (31.7%), net −$3,073

Not one gate removed a single TMUS loss. `r20 > 5%` and `r20 > 8%` skipped 9.8% of entries,
all winners (net fell from −$3,073 to −$3,459). The 60-day and autocorrelation gates skipped
nothing at all.

### TXN — reference only (production tier = skip), ungated 30/40 losses (75%), net −$11,888

`r20 > 5%` skipped 45% of entries and cut losses 30 → 18 — but that is a 45% skip rate,
nearly double the pre-registered 25% ceiling, and the loss *rate* still rose. TXN is not
counted.

### GOOGL — DIRECTIONAL ESTIMATE ONLY, NOT DEPLOYABLE

GOOGL motivated this hypothesis (48% loss rate in Exp 013) but has **5 trading days** of
Databento option data. The proxy below uses stock prices only: an entry "loses" if the stock
finishes above the 10%-OTM strike at ~32 days. It ignores premium entirely and therefore
cannot say whether a trade made money. Per `tasks/lessons.md` (2026-03-23), it informs
nothing.

| Gate | Skip | Above-strike rate | Rel. change |
|---|---|---|---|
| ungated | — | 39.6% | — |
| r20 > 5% | 49.2% | 40.0% | −1.1% |
| r60 > 12% | 59.6% | 39.4% | +0.6% |
| autocorr > 70 | 19.8% | 47.4% | **−19.8%** |

On GOOGL the autocorrelation gate — the one that looked best on AAPL — is the *worst*, and
the return gates skip half to two-thirds of all entries. Nothing here supports the
hypothesis even as a directional hint.

## Why the single apparent hit is not a finding

`autocorr pctile > 70` removed all 4 of AAPL's test losses while skipping 21% of entries. It
fails the pass criterion (needs 2 targets, got 1), but it is worth saying why it would still
not be a discovery if a second ticker had come along:

1. **n = 4 losses.** Removing 4 losses out of 33 trades by skipping 7 entries is a 1-in-a-few
   coincidence, not an effect.
2. **It moved a control.** KKR lost one loss under the same gate. Within the ±1 tolerance,
   but pointing the same direction as the "improvement."
3. **It does not survive its own motivation.** On GOOGL — the ticker the hypothesis was built
   to fix — the same gate makes things 19.8% worse.
4. **The theory predicts the return gates should work.** Sinclair & Mack's mechanism is
   momentum persistence; the direct momentum measures (20d, 60d returns) all failed or
   backfired. An autocorrelation percentile passing where the returns it is computed from
   fail is a signature of noise.

## Interpretation

Selling calls into a strong uptrend is theoretically selling underpriced insurance. On this
data, at production OTM% levels, it is not measurable — because production OTM% is already
doing the work. AAPL, TMUS and KKR all sit at 15% OTM, and DIS at 7% with 30-60 DTE; those
buffers were themselves widened by Exp 014 in response to exactly the losses this gate was
meant to prevent. There is little left for a trend filter to catch.

The honest reading is not "trends don't matter" but **"after Exp 014's OTM widening, a trend
gate has nothing left to add on these tickers, and we cannot test it on the one ticker
(GOOGL) where it might."**

## Follow-up (not tested, not deployed)

- Testing this properly needs GOOGL option data. That is a Databento purchase decision, and
  Phase 3 of the roadmap already earmarks the credits for validating a buyback rule. Worth
  reconsidering the priority given that GOOGL is the only ticker with a loss problem large
  enough for an entry filter to fix.
- If it is ever retested: at *narrower* OTM%, where there is loss rate for a gate to remove.

## Graveyard

`H18: failed_layer_2 — 0-1 of 2 target tickers on every gate; 5 of 6 gates raise the loss
rate; controls behaved correctly so the framework is sound.`
