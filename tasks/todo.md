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
- [ ] Pre-register H25 + H26 with immutable thresholds — committed BEFORE any run, and
      written to the graveyard through a workflow that has the real Supabase secrets
      (this machine has none; the local fallback is SQLite and would not be durable)
- [ ] Spec directive 3: verify the Exp 006 assignment-probability table and Exp 014's
      stock-close walk-forward are independent of the DTE bug — believed, not verified
- [ ] Exp 022 — corrected per-ticker baselines on `cc_sim.py`: annualised net P&L per
      contract, win rate, retention, buyback counts, assignments, as ranges across
      half-year windows and across 25 staggered sequential chains; real-fill results
      separated from carried-forward-price results
- [ ] Exp 023 — the live IV-rank ≥ 50 entry gate gets its own trial: no-gate vs iv50 vs a
      per-ticker threshold picked on the train window only, scored on the holdout
- [ ] Deploy only what the pre-registration authorises, one variable per commit
- [ ] AMZN demotion (spec directive 8) — restricting change, its own commit
- [ ] pytest for any new production logic; CI green
- [ ] `results/022_*.md`, `results/023_*.md`, graveyard verdicts, summary table

## Known statistical weakness (state it, don't hide it)

One year of real option prices for AAPL/DIS/TMUS/TXN, three for KKR, one regime. Cohorts
overlap, so trade counts overstate independence: every comparison is reported as a
distribution over start dates, never as an n=250 t-test. TMUS (44% missing repricing) and
KKR (64%) carry conclusions weaker than AAPL (2.5%) and DIS (14.3%), and their overlay P&L
sign already flipped once between simulators.

## Review

(filled in at the end)
