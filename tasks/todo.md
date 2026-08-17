# Phase 3 Part 0 — Baseline re-derivation (Exp 022/H25) + IV-rank gate trial (Exp 023/H26)

**Spec:** `tasks/phase3-strategy-spec.md` (REVISED 2026-08-17, directives 1, 3, 8, 9)
**Predecessor:** `results/PHASE3_SUMMARY.md` — the credit-free half of Phase 3 (Exps 019/019b/020/021).
Its handoff: merge PR #1 → #2, then farm out Exp 022 + 023. This session is that farm-out.

## Hard constraint (top of every plan)

> No paid API calls. No Databento purchase. Free data only: existing Databento files
> (already paid for), Yahoo stock/VIX history, Supabase. `DATABENTO_API_KEY` is present
> in `.env` — it is not to be used.

## Why Part 0 blocks the $125 purchase

`results/012_walk_forward.md` and every `expected_*` field in `ticker_strategies.py` were
produced by the simulator that pinned DTE to 0 (`assess_position()` read `datetime.now()`;
fixed in 8040440). H21's stress test compares stress years against those numbers. Buying
data to compare against an unmeasured number is the failure mode. Part 0 re-derives the
baseline on `cc_sim.py`, which passes a real `as_of`, real ex-div dates, and simulates
assignment instead of inferring it.

## Tasks

- [x] Import the amended spec into this branch (it existed only as untracked working-tree
      edits in the sibling worktree `s-0815-1613`)
- [x] Pre-register H25 + H26 with immutable thresholds — committed and pushed in `01c40bf`
      at 2026-08-17T21:56:29Z, before either `run.py` existed. The Supabase write is
      blocked until `registry-sync.yml` reaches `main` (GitHub dispatches workflows only
      from the default branch); the pushed commit is the durable record meanwhile
- [x] Spec directive 3: **both clean.** The Exp 006 `ITM_PROBABILITY` table is a literal
      whose lookup takes DTE as an argument; Exp 014 never imports `position_monitor`,
      never calls `assess_position()`, never reads the wall clock
- [x] Exp 022 — H25 **FAIL** (1 of 4 within tolerance). Headline outside the hypothesis:
      TMUS and KKR change SIGN when the sample is restricted to real-fill exits
- [x] Exp 023 — H26 clause 1 **PASSES** for AAPL/DIS/KKR, fails for TMUS; clause 2 passes
      for DIS only (threshold 75)
- [x] Deploy only what the pre-registration authorises, one variable per commit (7 commits)
- [x] AMZN demotion (spec directive 8) — done, and MSFT with it
- [x] pytest 189 passing, 18 new
- [x] `results/022_*.md`, `results/023_*.md`, graveyard verdicts, `results/PART0_SUMMARY.md`

## Known statistical weakness (state it, don't hide it)

One year of real option prices for AAPL/DIS/TMUS/TXN, three for KKR, one regime. Cohorts
overlap, so trade counts overstate independence: every comparison is reported as a
distribution over start dates, never as an n=250 t-test. TMUS (44% missing repricing) and
KKR (64%) carry conclusions weaker than AAPL (2.5%) and DIS (14.3%), and their overlay P&L
sign already flipped once between simulators.

## Review

See `results/PART0_SUMMARY.md`.

**Verdicts:** H25 FAIL (AAPL only within tolerance). H26 clause 1 PASS for AAPL/DIS/KKR,
FAIL for TMUS — the first pre-registered clause in this programme to pass. H26 clause 2
PASS for DIS only.

**Deployed (7 commits, all restricting):** corrected `expected_*` on AAPL/DIS/TMUS/KKR;
TMUS and KKR to `probation` (56% and 36% repricing coverage); AMZN and MSFT to `skip`;
DIS `iv_threshold` 75. Plus `results/012` superseded and `docs/dad-pitch.md` rebuilt.

**Open for Charles:** (1) DIS at IV ≥ 75 rests on a 5-trade holdout — pre-registered and
restricting, but reverts in one commit if he'd rather wait; (2) AAPL's fields were
corrected without a licensing result, which sets a precedent worth agreeing to explicitly;
(3) TMUS keeps a gate measured to be harmful there, because removing it is a loosening
change that needs its own experiment.

**Purchase status:** unblocked for AAPL and DIS. TMUS should come off the shopping list —
at 56% coverage a stress-year TMUS pull buys a verdict with the same defect as the numbers
this session just retracted.
