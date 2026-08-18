---
title: "Experiment 022: Baseline Re-derivation — H25 FAILS, and TMUS/KKR's profit turns out to be a repricing artefact"
date: 2026-08-17
experiment: 022
hypothesis: H25
status: completed
finding: "FAIL, 3 of 4 tickers. The deployed expected_pnl values overstate the corrected ones by 66-68% for DIS and TMUS and 18% for KKR; only AAPL survives its tolerance. The larger finding is not in the hypothesis: when the sample is restricted to trades whose exit price was a REAL Databento print, TMUS goes from +$151/yr to -$81/yr per contract and KKR from +$316/yr to -$88/yr. Their overlay profit is made of carried-forward prices. AAPL (99% real fills) does not move at all. The pre-registered coverage rule demoted exactly those two tickers to probation before any of this was visible."
---

# Experiment 022 — Baseline Re-derivation (H25)

**Pre-registered:** `experiments/022_baseline_rederivation/README.md`, commit `01c40bf`,
pushed 2026-08-17T21:56:29Z — before this experiment's `run.py` existed.
**Engine:** `experiments/cc_sim.py` (real `as_of`, real ex-dividend dates, simulated
assignment, one cohort per trading day). Real Databento OPRA prices. No money spent.

## The question

Every per-ticker number the product publishes — `expected_pnl`, `expected_win_rate`,
`expected_trades`, and `results/012_walk_forward.md` — came from the simulator that
measured DTE against `datetime.now()`. Every historical observation in Exps 007–013 was
evaluated at DTE = 0 with `ex_div_date=None`. Those numbers are live on the Sell tab as
"Expected P&L/yr per contract" and "Win Rate, from Experiment 008 backtest on real data".

H21 — the reason to spend $125 on stress-year option data — compares stress years to those
numbers. So this had to run first.

## H25 verdict: **FAIL** (3 of 4 tickers outside tolerance)

Median of 25 staggered sequential chains, production settings, production IV-rank ≥ 50 gate,
production copilot, slippage 0.

| Ticker | Deployed `expected_pnl` | Corrected (median, $/contract/yr) | Rel. error | Deployed win rate | Corrected | Δ | Within tolerance? |
|---|---:|---:|---:|---:|---:|---:|---|
| AAPL | $351 | **$299** [−739 … 389] | −15% | 100% | **91.7%** | −8.3pp | ✅ both |
| DIS | $822 | **$267** [51 … 590] | **−68%** | 71% | **80.0%** | +9.0pp | ❌ P&L |
| TMUS | $447 | **$151** [−99 … 976] | **−66%** | 89% | **92.3%** | +3.3pp | ❌ P&L |
| KKR | $386 | **$316** [279 … 351] | −18% | 100% | **63.3%** | **−36.7pp** | ❌ win rate |
| *TXN (control, tier=skip)* | *$0* | *−$2,003* [−2,617 … −1,138] | — | *0%* | *50.0%* | — | *not gating* |

Tolerances were ±25% relative and ±10pp, fixed before the run. AAPL passes both. Nothing
was moved afterwards.

The bracketed range is the min–max across the 25 start-date offsets and is the number that
deserves the most attention: AAPL's median year is +$299 and its worst start date is
−$739, because a single −$970 trade lands inside some chains and not others. With ~13
trades a year, **which Tuesday you start on matters more than most parameter choices.**

## The finding that was not in the hypothesis: real fills vs carried-forward prices

`cc_sim` carries the last known option price forward when Databento has no print for that
symbol that day, and counts every occurrence. Restricting to trades whose **exit** was
either a settlement (expiry / early exercise, priced off the stock) or a genuine print on
the exit date:

| Ticker | Repricing coverage | Real-fill exits | Annualised $/contract, all trades | Annualised $/contract, real fills only |
|---|---:|---:|---:|---:|
| AAPL | 97.5% | 98/99 (99.0%) | $299 | **$299** (unchanged) |
| DIS | 85.7% | 97/126 (77.0%) | $267 | **$204** |
| TMUS | 56.0% | 90/122 (73.8%) | $151 | **−$81** |
| KKR | 36.3% | 248/388 (63.9%) | $316 | **−$88** |
| *TXN* | *84.2%* | *97/120 (80.8%)* | *−$2,003* | *−$2,282* |

**TMUS and KKR change sign.** Their positive overlay P&L is not a market result; it is what
happens when a buyback is paid at a price that was last printed days earlier. This is the
third independent time TMUS and KKR have flipped sign (twice between simulators in the
Phase 3 session, now once between fill definitions). AAPL, which has essentially complete
data, does not move by a single dollar.

The pre-registered deployment rule demoted exactly these two tickers to `probation` on a
coverage threshold fixed **before** the run and before this table existed.

## Regime luck, measured

Per calendar half-year of entry (retention = net ÷ gross premium):

| Ticker | Worst half | Best half | Swing |
|---|---|---|---|
| AAPL | 2025H1 −8.5% | 2025H2 +67.1% | 76pp |
| DIS | 2025H1 −77.9% | 2026H1 +92.8% | **171pp** |
| TMUS | 2026H1 −127.1% | 2025H2 +78.0% | **205pp** |
| KKR | 2024H2 −25.7% | 2026H1 +78.4% | 104pp |

Exp 015 measured 40–180pp retention swings between halves and warned that a point estimate
measures regime luck. Confirmed, with one window worse than that range. Any single-number
claim about this strategy's income is a claim about which six months you looked at.

## Assignments

**Zero**, across every ticker, every chain, every half-year — 855 simulated positions,
including 61 KKR positions that never saw a single real quote after entry. The tri-fold
goal's first clause (never get called away) is the one thing in this system that has
survived every correction. Note the engine simulates both expiry assignment and rational
early exercise into a dividend; it is not inferring assignment the way Exp 008/009 did.

## What this means at Dad's size (10,000 shares/ticker)

| | AAPL | DIS | TMUS | KKR* | **Total/yr** |
|---|---:|---:|---:|---:|---:|
| What the app claims today | $35,100 | $82,200 | $44,700 | $2,702 | **$164,702** |
| Corrected, all trades | $29,900 | $26,700 | $15,100 | $2,213 | **$73,913** |
| Corrected, real fills only | $29,900 | $20,400 | −$8,100 | −$618 | **$41,582** |

*KKR at its Exp 021 liquidity cap of 7 contracts, not 100.

Read the bottom row as an order of magnitude, not a forecast: one year, one favourable
regime, chain medians whose spreads are wider than the differences between rows. The point
is the direction of the correction — **the product has been claiming roughly 4× what the
fixed engine measures on real fills** — not the precision of the number.

## Spec directive 3 — DTE-bug blast radius (verified, not assumed)

| Artefact | Verdict |
|---|---|
| Exp 006 assignment-probability table (`ITM_PROBABILITY`, 145,099 obs) | **Clean.** A hardcoded literal; `lookup_itm_probability(pct_from_strike, dte)` takes DTE as an argument, never calls `assess_position()`, never reads the wall clock. **Caveat:** the table is fine, but every backtest that consumed it *through* `assess_position()` asked it for `dte=0`. |
| Exp 014 stock-close walk-forward (the evidence for every deployed OTM% and for GOOGL's probation) | **Clean.** `experiments/014_validated_param_update/run.py` does not import `position_monitor`, never calls `assess_position()`, and never reads the wall clock. |

Both were *believed* independent. They now are *known* independent. The deployed strike
distances therefore stand on evidence the bug never touched.

## Deployed (pre-registered rules only)

1. `expected_pnl` / `expected_win_rate` / `expected_trades` replaced with the corrected
   medians for **DIS, TMUS, KKR** — the three tickers that failed their tolerance. One
   commit each.
1b. **AAPL's fields were also corrected ($351 → $299, 100% → 92%), and H25 did not license
   that.** AAPL passed its tolerance, so the pre-registered rule said leave it alone. It is
   changed anyway under a separate and narrower principle — *no live claim may sit above
   the best available measurement* — which is the same principle that demoted AMZN and
   GOOGL. The H25 verdict for AAPL stands as **PASS** and is not retrofitted; this is
   logged as a judgment call, in the restricting direction, made after seeing the result.
   A ±10pp tolerance that lets a "100% win rate — never loses" claim survive a measurement
   of 91.7% (8.3% of trades lose; worst trade −$971) is a badly chosen tolerance, and the
   right response is to say so rather than to hide behind it.
2. **TMUS and KKR demoted to `probation`** — repricing coverage 56.0% and 36.3%, both under
   the 70% floor fixed in advance. `probation` is Exp 021's badge: we looked, but with a
   weaker instrument. No parameters change. No ticker was promoted.
3. `results/012_walk_forward.md` marked superseded, not deleted — it is the record of what
   was believed.

## What this does NOT license

The $125 purchase is now unblocked *for AAPL and DIS*. It is not clear that TMUS stress
data can answer anything: at 44% missing repricing in 2025–26, a 2020/2022 TMUS pull would
produce a verdict with the same defect as the numbers above. The revised purchase order
(AAPL 2020 first) is confirmed by this experiment, and TMUS's position at the back of that
queue should probably become "not at all."

## Reproduce

```bash
python3 experiments/022_baseline_rederivation/run.py   # ~6 min, all data local
```

Raw output: `experiments/022_baseline_rederivation/results.json`.

---

# Addendum, 2026-08-17 (later session) — re-run on the fully corrected engine

**Why this addendum exists.** Everything above was produced on a branch
(`session/s-0816-2159-part0`) that does not contain commit `bbbddaa`, *"Fix a live-monitor
regression and six simulator defects found by review."* That commit is an ancestor of
`session/s-0817-1634` only. Exp 022 was therefore measured on an engine with six known,
already-reviewed defects still in it. This addendum re-runs the identical `run.py` on the
merged tree, with the baseline window pinned to `WINDOW_LEGACY_PRE_STRESS` as the spec's
caveat-1 ruling requires.

## Two things this addendum is NOT

1. **It is not a data-contamination finding.** The purchased 2020/2022 stress files landed
   at 22:07; the branch above was tipped at 16:13. Its baseline was clean. Both runs report
   identical windows (AAPL/DIS/TMUS `2025-03-21 → 2026-03-20`, KKR `2023-03-21 → 2026-03-20`)
   and identical option-day counts (251 / 251 / 251 / 753). The window pin changes nothing
   here; it makes the run *reproducible*, which it previously was not — re-running that
   branch's `run.py` today, with the stress files on disk and a loader that globs
   `{ticker}_ohlcv*`, would silently concatenate the 2020 crash into the baseline.
2. **It does not overturn H25.** H25 still **FAILS**. Zero assignments still hold across
   every ticker, every chain, every half-year. The two pre-registered coverage demotions
   still fire, on almost identical coverage (TMUS 56.0→56.7%, KKR 36.3→35.7%).

## The defect that moved the numbers

Of the six fixes, one dominates:

> **fabricated IV rank** — the engine returned a hardcoded `50.0` when it had fewer than 10
> observations. `50.0` passes the production `iv_rank >= 50` gate. So the first ~9 days of
> **every** ticker entered on an invented rank.

The signature is unmistakable: every ticker loses **exactly nine** entries.

| | AAPL | DIS | TMUS | KKR |
|---|---:|---:|---:|---:|
| Entries, PR #4 engine | 99 | 126 | 122 | 388 |
| Entries, corrected engine | 90 | 117 | 113 | 379 |
| Difference | **−9** | **−9** | **−9** | **−9** |

The other five (look-ahead `spot()`, stale-fill marking, sticky CLOSE_SOON, NaN-dividend
fail-safe, uncounted skips) move magnitudes without a clean signature.

## Corrected baselines — median [min … max] across 25 staggered chains

| Ticker | PR #4 engine | **Corrected engine** | Real-fill only, PR #4 | **Real-fill only, corrected** | Coverage |
|---|---:|---:|---:|---:|---:|
| AAPL | $299 | **$141** [−776 … 352] | $299 | **$141** (unchanged) | 97.1% |
| DIS | $267 | **$442** [49 … 1,444] | $204 | **$442** | 87.6% |
| TMUS | $151 | **$178** [−43 … 731] | −$81 | **$9** | 56.7% |
| KKR | $316 | **$329** [289 … 472] | −$88 | **−$17** | 35.7% |
| *TXN (control)* | *−$2,003* | *−$538* [−1,664 … 622] | *−$2,282* | *−$785* | *85.8%* |

Win rates: AAPL 90.9%, DIS 88.9%, TMUS 91.7%, KKR 69.2%.

**AAPL moves in the opposite direction from everything else** — down 53%, while DIS, TMUS
and KKR all move up. AAPL had the most entries removed relative to its total (9 of 99) and
the highest coverage, so the phantom entries were pure addition there.

## H25 per-ticker tolerance: the verdicts reverse

| | AAPL | DIS | TMUS | KKR | Overall |
|---|---|---|---|---|---|
| PR #4 engine | ✅ | ❌ | ❌ | ❌ | **FAIL** (1/4) |
| Corrected engine | ❌ | ❌ | ✅ | ✅ | **FAIL** (2/4) |

The headline verdict is stable; *which* tickers sit inside their ±25%/±10pp tolerance is
not. This is the **third** time TMUS and KKR have changed character between measurements
and the second time AAPL's published figure has been corrected downward. Per the standing
rule in `CLAUDE.md` — *stop after the second analytical reversal* — the per-ticker tolerance
result is recorded here as an **unstable intermediate, not a verdict**. Nothing was tiered
or promoted off it.

## What was and was not deployed

**Deployed — one restricting change, one variable:**

- `AAPL.expected_pnl` **$299 → $141**, `expected_win_rate` **92 → 91**, and the matching row
  in `docs/dad-pitch.md`. Justification is *not* H25 (which AAPL now fails) but the standing
  narrower rule PR #4 itself proposed: **no live claim may sit above the best available
  measurement.** $299 sat above $141. The correction history is monotonically downward with
  a named cause at each step: $351 (broken `as_of` clock) → $299 (fabricated IV rank) →
  $141 (six fixes).

**Deliberately withheld:**

- DIS $267 → $442, TMUS $151 → $178, KKR $316 → $329 are all *raises*. Raising a published
  income claim is a loosening change; it needs its own pre-registered validation, and DIS in
  particular reversed direction between engines ($822 → $267 → $442). All three keep PR #4's
  lower values, which are now conservative against the best measurement rather than accurate.
- KKR's win rate 63% → 69% — same reason.
- Tiers: unchanged. AAPL keeps `conservative` on coverage (97.1% clears the 70% floor), not
  on an H25 pass. TMUS and KKR keep `probation`.

## What survives both engines

The structural findings — the ones worth acting on — are engine-independent:

- **Zero assignments**, everywhere, in both runs.
- **AAPL is the only ticker whose result does not move when synthetic fills are excluded**
  ($141 all-trades = $141 real-fill). It has 97% coverage; the rest have 36–88%.
- **TMUS and KKR's overlay profit is substantially a repricing artefact.** The effect is
  smaller on the corrected engine (TMUS +$178 → +$9; KKR +$329 → −$17) but the direction is
  identical, and both still collapse to approximately zero or negative.
- **Regime luck dominates.** Half-year retention swings, corrected engine: AAPL 72pp
  (2025H1 −22.9% … 2025H2 +49.0%), DIS 189pp, TMUS 222pp, KKR 107pp. Any single-number
  income claim is a claim about which six months you looked at.
- **Spec directive 3 stands**: the Exp 006 assignment table and Exp 014's walk-forward are
  independent of the DTE bug, verified by static trace in both runs.

## Reproducing

```
python3 experiments/022_baseline_rederivation/run.py   # pinned to WINDOW_LEGACY_PRE_STRESS
```

Requires commit `bbbddaa` in history. On a branch without it, the run silently reproduces
the superseded numbers above.
