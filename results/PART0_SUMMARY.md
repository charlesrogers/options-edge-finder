---
title: "Part 0 Summary — H25/H26: the published numbers were 4x too high, and the entry gate is the first thing here to pass a real test"
date: 2026-08-17
status: completed
finding: "H25 FAILS (3 of 4 tickers): deployed expected_pnl overstates the fixed engine's measurement by 66-68% for DIS and TMUS. H26 clause 1 PASSES for AAPL, DIS and KKR — the first pre-registered clause in this programme to pass — and fails for TMUS, where the IV gate blocks the winners. Seven production changes shipped, every one of them restricting: four corrected expectation blocks, two probation demotions, two skip demotions, one tightened entry gate. The $125 Databento purchase is now unblocked for AAPL and DIS, and probably should never be spent on TMUS."
---

# Part 0 Summary — Baseline Re-derivation (H25) and the IV-Rank Gate (H26)

**Spec:** `tasks/phase3-strategy-spec.md` REVISED directives 1, 3, 8, 9.
**Constraint:** no paid API calls. Owned Databento files, free Yahoo history, nothing bought.
**Pre-registered:** commit `01c40bf`, pushed 2026-08-17T21:56:29Z, before either `run.py` existed.

## The table

| Hypothesis | Verdict | Deployed? | Expected $ impact at 10k shares/ticker | Regime caveat |
|---|---|---|---|---|
| **H25** — do our published numbers reproduce on the fixed engine? | **FAIL** (1 of 4 within tolerance) | Yes — corrected `expected_*` on all four tickers, two probation demotions | Removes ~$91K/yr of claimed income that was never measured; the corrected figure is ~$74K/yr, or ~$42K on real fills only | One year, one favourable regime. Half-year retention swings of 76–205pp per ticker |
| **H26 clause 1** — does the live IV ≥ 50 gate earn its place? | **PASS** for AAPL (+20.7%), DIS (+90.4%), KKR (+286.2%); **FAIL** for TMUS | No change (the gate is already live) | — | The gate's whole job is regime-dependent; this window contains one vol spike |
| **H26 clause 2** — is 50 the right number per ticker? | **PASS** for DIS only (75, +58.1%) | Yes — `iv_threshold: 75` on DIS | DIS trades ~48 days a year instead of ~126 | Holdout is 5 trades |
| **Spec directive 3** — is the Exp 006 probability table or Exp 014's walk-forward contaminated by the DTE bug? | **Both clean** (verified, not assumed) | n/a | Protects the evidence base for every deployed strike distance | none |
| **Spec directive 8** — AMZN/MSFT live at settings they failed | Executed | Yes — both `skip` | Removes two unvalidated tickers from the recommendation set | none |

## The finding Charles should read first

H25 asked whether our published numbers reproduce. They mostly don't, which was expected.
The unexpected part is *why* two of them looked good:

| | AAPL | DIS | TMUS | KKR |
|---|---:|---:|---:|---:|
| Repricing coverage | 97.5% | 85.7% | 56.0% | 36.3% |
| Annualised $/contract, all trades | $299 | $267 | **+$151** | **+$316** |
| Annualised $/contract, real fills only | $299 | $204 | **−$81** | **−$88** |

`cc_sim` carries the last known option price forward when Databento has no print that day.
Restrict the sample to trades whose exit was priced by an actual print and **TMUS and KKR
change sign.** AAPL, which has essentially complete data, does not move by a dollar.

This is the third time TMUS and KKR have flipped sign (twice between simulators last
session, once between fill definitions today). They are not tickers with a weak result;
they are tickers where **we do not have the data to have a result.** The pre-registered
coverage rule — a 70% floor fixed before the run — demoted exactly those two, before this
table existed.

## The other finding: the gate is real, except where it isn't

The IV-rank ≥ 50 entry gate has been live on every ticker since Exp 009, an experiment run
on the broken clock. Tested properly, it beats no gate on holdout P&L per entry for AAPL
(+20.7%), DIS (+90.4%) and KKR (+286.2%). That is the first pre-registered clause in this
entire programme to pass.

On TMUS it fails, and not narrowly: the gate blocks 109 entries that averaged **+$48 each**
(103 winners, 6 losers) and keeps the ones that lose. On TMUS it is an anti-filter.

AAPL's pass comes with a contradiction that is reported rather than resolved: the gate wins
per entry ($14.97 vs $12.40) and loses per year ($299 vs $453 annualised), because it
removes 132 entries that averaged +$17. The registered metric was per-entry, so the verdict
is PASS — but treat it as unsettled. Evidenced: DIS, KKR. Contradicted: TMUS. Ambiguous: AAPL.

## What shipped (seven commits, every one restricting)

1. **DIS** `expected_pnl` $822 → $267, win rate 71% → 80%.
2. **TMUS** $447 → $151 — with the real-fill number (−$81) in the note.
3. **KKR** $386 → $316 and the "100% win rate" claim → 63%.
4. **TMUS and KKR → `probation`** on the pre-registered coverage rule.
5. **AMZN and MSFT → `skip`.** Both were live at 5% OTM (AMZN in the recommendation set,
   MSFT via the unknown-ticker default) after failing Exp 021 at a *more conservative* 15%.
6. **DIS `iv_threshold` = 75**, with `get_iv_threshold()` wired into the only enforcement
   point. TMUS keeps the global 50 despite the gate failing there — removing a restriction
   is a loosening change and needs its own experiment.
7. **AAPL** $351 → $299, 100% → 92%. **This one was not licensed by H25** (AAPL passed its
   tolerance) and is flagged as a judgment call: no live claim may sit above the best
   available measurement. A tolerance that lets "never loses" survive a measured 8.3% loss
   rate is a badly chosen tolerance.

Plus `results/012_walk_forward.md` marked superseded, and `docs/dad-pitch.md` rebuilt from
measured numbers — it had been claiming a 95% win rate for AMZN, a ticker with no option
data at all.

## What this means for the $125

**Unblocked for AAPL and DIS.** The purchase can now compare stress years against a baseline
that was actually measured, which was the whole reason Part 0 blocked it.

**TMUS should probably come off the shopping list entirely.** At 56% repricing coverage in
2025–26, a TMUS 2020/2022 pull buys a verdict with the same defect as the numbers this
experiment just retracted. The revised order (AAPL 2020 first) is confirmed; the note
against TMUS should change from "only if budget remains" to "not worth buying."

The remaining purchase-blocking question is whether Databento's 2020/2022 OHLCV for AAPL
will have AAPL's 97.5% coverage or TMUS's 56%. Coverage is a property of how much that
strike traded, not of the vendor — and 2020 had heavy option volume, so the odds are good.
Worth checking the returned row count against expectations after pull #1, before pull #2,
exactly as the cost protocol already requires.

## Discipline record

- H25 and H26 were pre-registered with immutable thresholds and deployment rules in commit
  `01c40bf`, pushed at 21:56:29Z — **before** either experiment's `run.py` was written.
- No threshold moved after seeing a result. AAPL's field correction is explicitly labelled
  as *not* licensed by H25 rather than dressed up as one.
- The one deployment authorised by a pass (DIS at 75) rests on a 5-trade holdout. It shipped
  as registered, with the sample size stated in the config comment, the results file, the
  commit message and this summary.
- Verdicts — both failures — recorded in the graveyard via
  `experiments/record_part0_results.py`.
- **Graveyard durability gap:** no machine here has Supabase credentials, so local registry
  calls land in gitignored SQLite. `.github/workflows/registry-sync.yml` was added to run
  registry scripts with the real secrets and to **fail** if the backend announcement says
  `sqlite`. It cannot be dispatched until it exists on `main` (GitHub only dispatches
  workflows from the default branch), so the Supabase write happens on merge. The
  pre-registration's own timestamp does not depend on it: the pushed commit is the proof.
- pytest: 189 passing, 18 new — the per-ticker threshold fallback, a guard that no deployed
  threshold is ever *looser* than the global default, a guard that TMUS's gate was not
  quietly removed, and a guard that no ticker anywhere claims a 100% win rate again.

## One thing found while deploying, not tested by either hypothesis

**The IV-rank entry gate is not enforced in the app at all.** `DEFAULT_IV_THRESHOLD` appears
in exactly one place in production code: `paper_trade_logger.py`, the automated paper-trade
job. `streamlit_app.py` computes an IV rank, shows it, and feeds it to the VRP signal — but
nothing in the Sell tab stops a user from selling a call at IV rank 12. The rule Exp 009
sold as "+204% improvement", that Exp 023 has now partly vindicated, and that the Dad-facing
runbook lists as one of three entry conditions, has been enforced only against paper trades.

DIS's new threshold of 75 inherits the same gap: it binds the logger, not the human. This is
a UI change, not a research question, and it is deliberately not bundled into this PR —
flagging it rather than silently widening the diff.

## The three things worth arguing about

1. **DIS at IV ≥ 75 on five holdout trades.** Pre-registered, restricting, train-window
   evidence is solid — and still thin enough that a reasonable person would withhold it.
   It shipped because withholding a registered pass is as much a discipline violation as
   retrofitting a failure. Say the word and it reverts in one commit.
2. **AAPL's numbers were changed without a licensing result.** Deliberate, flagged, and the
   precedent it sets ("we may always restrict a live claim toward the measurement") is one
   worth agreeing to explicitly rather than inheriting silently.
3. **TMUS keeps a gate that failed its own trial.** The asymmetry is intentional — a failed
   test of a restriction is not evidence for removing it — but it means TMUS now carries a
   filter we have measured to be harmful there. The clean resolution is a pre-registered
   removal experiment, not a quiet edit.
