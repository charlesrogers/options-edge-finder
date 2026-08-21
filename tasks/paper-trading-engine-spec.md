# Paper-Trading Engine Spec — forward validation with pre-registered arms

**Executor:** Opus 5, fresh session, working dir `/Users/charlesrogers/Documents/options-tool`
**As of 2026-08-20.** Facts rot — §0 first; every claim below is a hypothesis to re-verify.
**Source brief:** `tasks/paper-trading-engine-brief.md` (Charles, 2026-08-20). This spec is the execution contract for that brief.
**Read first:** `CLAUDE.md`, `tasks/lessons.md` (in full — binding), `tasks/week2-research-spec.md` §"The research discipline" (applies verbatim to this work), `position_monitor.py`, `experiments/cc_sim.py`, `signal_registry.py`, `db.py`, `monitor_positions.py`, `ticker_strategies.py`, `docs/crons.md`, `results/013_paper_trade_audit.md`.
**Binding process rules:** isolated-worktree commits + `git show HEAD --stat` before every push (lessons 2026-08-18 "Commit raced by a concurrent session"); red-baselined acceptance checks — a check born green is presumed vacuous (same lesson); two-reversal rule; every scheduled job alerts on failure; no ✅ DONE while any user-facing surface disagrees with the source of truth (lesson 2026-08-18 "Declared DONE while the product surface still served invalidated numbers").
**Lane:** code + one Supabase migration. The migration is applied over ssh to the shared Supabase — confirm no other infra session is live before applying (one infra session at a time, standing rule). Everything else is repo + GitHub Actions.

**The bar (verbatim from the brief):** when this engine has run for six months, the sentence "our strategy works" or "our strategy doesn't work" must be defensible in front of a 30-year Goldman veteran, with the receipts in a table he can audit. Every design decision below serves that sentence.

---

## §0 Verify current state before touching anything

Facts in this spec were verified 2026-08-20 against branch `main` @ `b3f55bd`. Re-verify each before building on it; where reality disagrees, reality wins and the disagreement goes in the PR description.

```bash
# 0.1 No sibling session is already building this (lesson 2026-08-16 "Built a second simulator")
git branch -a && ls ~/.claude/worktrees/options-tool/ && git log --all --oneline -20
grep -rl "paper.*engine" ~/.claude/worktrees/options-tool/*/tasks/ 2>/dev/null

# 0.2 signal_graveyard exists in SUPABASE (not the silent SQLite fallback) and H40+ is free
ssh root@95.216.205.160 "docker exec supabase-db psql -U postgres -d postgres -c \
  \"select signal_id, status from signal_graveyard order by signal_id;\""
# Expect: rows exist (H01..H26 era); no H40+. If the table is missing, STOP — migration 001 was never applied.

# 0.3 The single alert authority and its as_of contract
grep -n "def assess_position" position_monitor.py          # expect as_of param, default now-only-for-live
grep -n "datetime.now" position_monitor.py experiments/cc_sim.py  # expect exactly one hit, in position_monitor's live default

# 0.4 Monitor + capture crons actually green this week (silence ≠ health)
gh run list --workflow=position-monitor.yml -L 5
gh run list --workflow=daily-chain-capture.yml -L 5

# 0.5 Live quote shape from the proxy — write scripts/probe_quotes.py (never inline complex Python):
#     fetch one KKR chain + one AAPL chain via yf_proxy.get_option_chain, print bid/ask/volume/openInterest/
#     impliedVolatility for the production-OTM% strike, and print what a PROXY FAILURE returns (yf_proxy._get
#     returns {} on RequestException — silent-empty). Record: KKR 15%-OTM bid is expected to be thin/zero often.

# 0.6 Production per-ticker config still matches this spec's assumptions
python3 -c "import ticker_strategies as t; print(t.get_iv_threshold('DIS'), t.get_max_contracts('KKR', 10000))"
# Expect: 75, (7, <reason>)

# 0.7 The old paper tracker's composition (what this engine must never be polluted by)
python3 scripts/audit_paper_trades.py --json | head -40   # expect: 444 scored rows all BSM backfill

# 0.8 Schema of the tables we'll pattern-match: \d monitor_heartbeats; \d position_assessments (via ssh psql)

# 0.9 Cron inventory ground truth
sed -n '1,80p' docs/crons.md
```

**Corrections to the brief found while writing this spec (verify they still hold):**
- There is **no 15-minute chain-capture cron.** The only `*/15` schedule is `position-monitor.yml` (`*/15 13-21 * * 1-5` UTC). The brief's "the 15-min chains" refers to monitor *ticks*, not chain snapshots. This engine must therefore capture its own decision-moment quotes (§5) — it cannot lean on an existing 15-min chain store.
- `signal_registry.pre_register()` → `db.register_hypothesis()` **upserts on `signal_id`** (`db.py:572`). Pre-registration is therefore NOT immutable today: re-running a registration script with different thresholds silently overwrites the original. §6.4 closes this hole; it is a prerequisite for the brief's "immutable success criteria."
- `assess_position()`'s `premium_captured_pct` **defaults to 0 when `current_option_ask` is None** (`position_monitor.py:193-196`) — so on a missing quote, the TP-75 and TP-50 clauses silently cannot fire and a position is held longer than the strategy intends. The engine must count every tick where this default engaged (§5.5) — this is the forward-time twin of the DTE-pinned-to-0 bug.

---

## §1 Mission

Run the ACTUAL production strategy forward in time, against REAL quotes captured at the moments decisions happen, in parallel pre-registered arms, so that at pre-committed milestones we *know* — not believe — whether the strategy makes money, which components carry the value, and when it must be turned off.

The five questions (pre-registered as H40–H43 before the first paper trade — §6):

1. **Does the full strategy net positive per ticker after real friction?** Entry gate (per-ticker IV-rank thresholds incl. DIS ≥ 75) → strike/DTE selection → copilot exits → conservative fills. Option-leg P&L only, stock excluded, at Dad's size with liquidity caps (KKR = 7 contracts).
2. **What is real premium retention?** (The number that has swung 13%→49% depending on which bug we'd found that week.)
3. **What do the copilot's exits actually cost?** Every buyback at the real ask at decision time. (Arm A − Arm B.)
4. **Is the IV gate worth anything forward?** (Arm A − Arm C. Exp 023 said: per-ticker, and it fails on TMUS.)
5. **What does the market's spread actually charge us?** Spread width logged as a first-class cost on every fill.

---

## §2 Epistemic contract — what the analytical arm can and cannot be trusted for

This section exists because Charles asked for it explicitly, and because this project has caught its own backtests lying three times (DTE clock bug voiding Exps 007–014; fabricated IV rank in the pre-`bbbddaa` engine lineage; carried-forward fills flipping TMUS/KKR from +$151/+$316 to −$81/−$88). Write this table into the health page's "How to read this" section and into `PREREGISTRATION.md`.

| Claim source | Trust it for | Never trust it for | Why (lesson) |
|---|---|---|---|
| BSM / synthetic backfill (old `paper_trades`) | Nothing. Directional intuition at most. | Any deployment or published number | Exp 001 fake prices, 2026-03-23; 444-row backfill audit |
| Backtest on Databento, all fills | Mechanism instrumentation (which clause fires, how often); relative comparisons where both sides share the same staleness | Absolute P&L or retention; any per-ticker sign on <70% repricing coverage | Carried-forward fills lesson, 2026-08-17 |
| Backtest on Databento, **real-fill subset** | Sign and rough magnitude per ticker; deriving kill thresholds and expected-cycle math | Precision beyond the coverage %; thin names (KKR 36% coverage) | Same lesson — the real-fill number is the result |
| **This engine, forward** | The only source that can ever justify "it works" — with pre-registered thresholds and stated sample sizes | Anything before its minimum cycle counts; crash-regime behavior it hasn't lived through | The whole brief |

**What forward paper-trading can and cannot establish, honestly:**

- **It can falsify fast.** A strategy that loses money over 6 months of conservative fills (sell at bid, buy at ask, +15-min latency) is dead — those fills are strictly worse than achievable, so a negative verdict is *stronger* than real trading. The conservative bias runs exactly one direction, and that direction is the safe one.
- **It confirms slowly and conditionally.** Six months is ONE regime draw — half-year retention swings of −78%→+93% are on record. A positive 180-day verdict means "process-faithful, honestly measured, positive in the regime we lived through," not "edge proven for all weather." The Databento stress-year backtests (real-fill subset standard) remain the only crash evidence until a crash happens on the engine's watch. Say this in every report.
- **Paired arm differences are the strong results.** Arm A and Arm B live the identical market path, so per-cycle A−B differences cancel regime noise; the copilot-cost and IV-gate answers (questions 3–4) will reach statistical usefulness several times faster than the absolute-P&L answer (question 1). Expect the milestone reviews to grade attribution before they can grade viability.
- **Sample-size math, not vibes** (research-discipline rule 6): `ticker_strategies.py` expects ~11–18 trades/ticker/year, so ~5–9 completed cycles per ticker and ~25–45 pooled cycles by day 180. The executor MUST derive expected cycle counts from the corrected `cc_sim` hold-time distributions per ticker, write the derivation into `PREREGISTRATION.md`, and phrase every verdict rule as (minimum cycle floor) AND (bootstrap CI condition). Per-ticker verdicts at 180 days will be directional at best on slow-cycling tickers — pre-commit to that limitation rather than discovering it at review time.
- **What it still can't tell us:** real order-book impact (negligible at these sizes *except* KKR — that's what the 7-contract cap is for), assignment reality (paper assignment is modeled, §4.4 — flag every one), and Dad's actual behavior under stress.

---

## §3 Architecture

```
GH Actions (*/15, market hours)                       Supabase
┌─────────────────────────────┐          ┌──────────────────────────────┐
│ paper_engine.py             │  writes  │ paper_engine_entry_evals     │
│ 1. entry eval (1x/day/tkr)  │────────► │ paper_engine_quotes          │
│ 2. tick open positions      │          │ paper_engine_trades  (ledger)│
│ 3. execute pending fills    │          │ paper_engine_events          │
│    (T+15 latency rule)      │          │ monitor_heartbeats (own row) │
│ 4. heartbeat + health calc  │          │ signal_graveyard (read-only) │
└─────────────────────────────┘          └──────────────────────────────┘
        │ verdicts from                            ▲ read by
        ▼                                          │
position_monitor.assess_position(as_of=tick)   web /paper-engine page
(THE authority — no reimplementation)          + /api/paper-engine/health
        │ action semantics from                (report-only, no alerting)
        ▼
experiments/cc_sim.py policy + accounting core (shared, not copied)
```

**Single-authority rules (non-negotiable — we are still paying down engine #2, `copilot.ts`):**
- Verdicts come from `position_monitor.assess_position(..., as_of=<tick timestamp>)` — the same function, same import, explicit `as_of` on every call (lesson 2026-08-16, DTE pinned to 0). The engine never contains an alert rule.
- Action semantics (what a verdict makes the trader *do*) come from `cc_sim.baseline_policy` + `DEFAULT_CFG` semantics: `EMERGENCY`/`CLOSE_NOW` → close at the next fill opportunity; `CLOSE_SOON` → armed, close after `close_soon_days=5` trading days, sticky. **Refactor, don't copy:** extract the policy/accounting pieces of `cc_sim.py` that this engine shares into an importable module (or import `cc_sim` directly) so there is exactly one definition; `cc_sim`'s experiment results must be byte-identical before/after the refactor (regression-test this). If the executor believes different action semantics better model Dad's behavior, STOP and ask Charles for a plain-language description first (global rule: domain mechanics come from Charles, not research) — do not invent trading behavior.
- P&L accounting: `pnl_per_share = premium_collected − buyback_cost`, per contract ×100, option leg only, portfolio tallied per-day as value-change not level (lesson 2026-03-24, 191% "loss"). Reuse `cc_sim.score()`'s field set, including the `real-fill vs stale-fill` split.
- Contract selection reuses one selection function shared with `cc_sim.find_call` semantics (OTM%, DTE band, target 30), parameterized by chain source. §0 must also identify what IV-rank computation the production Sell surface uses and reuse *that* — if the web computes its own, record the existing parity gap in the PR, don't add a third.

**Statelessness & idempotency:** every run reads its whole state from Supabase (open positions, pending fills, armed CLOSE_SOONs), acts, writes. Unique constraints make re-runs and missed ticks safe: `paper_engine_trades` unique on `(arm, ticker, cycle_seq)`; events append-only with deterministic keys; fills recorded as "pending → executed" event pairs so a crash between alert and fill can't double-fill. GH Actions cron drift is a documented fact (one monitor run in a whole morning, 2026-08-19) — the fill rule "first tick ≥ T+15min" (§5.3) absorbs drift by construction.

---

## §4 The arms

All arms run simultaneously, on the same tickers, the same daily entry evaluations, the same captured quotes. Arms differ ONLY in which decisions they act on — never in data, pricing, or accounting. A quote missing for one arm is missing for all.

**Universe:** the non-skip production tickers from `ticker_strategies.py` at §0-verification time (currently TMUS, KKR, DIS, AAPL, GOOGL). Sizing: `get_max_contracts(ticker, 10_000)` — KKR capped at 7. Skip-tier tickers stay out of every arm.

| Arm | Registration | Entry gate | Exits | Isolates |
|---|---|---|---|---|
| **A — full strategy** | H40 | production: per-ticker IV-rank threshold (`get_iv_threshold`, DIS = 75) + liquidity floor (§5.2) | full copilot ladder via `assess_position` + cc_sim policy semantics | the product as shipped |
| **B — hold-to-expiry** | H41 (measured as A−B) | identical to A (same entries, same contracts) | none: hold to expiry; settle ITM at intrinsic (assigned), OTM at 0; modeled rational early exercise (§4.4) still applies | the copilot's entire value/cost |
| **C — no IV gate** | H42 (measured as A−C) | liquidity floor only, IV gate removed | identical to A | the IV gate's forward value |
| **D — TP-only** (optional, cheap) | H43 | identical to A | acts ONLY on the TP-75 clause (`position_monitor.py:329`) and EMERGENCY; ignores distance/gamma/earnings clauses | how much of A's exit cost is defensive vs profit-taking |

Arm D ships only if it adds no collection cost (it doesn't — same quotes) and is pre-registered with the rest. Do not add arms after go-live; a new arm is a new pre-registration and a new start date, reported separately forever.

**4.1 Entry evaluation — once per ticker per trading day**, at the monitor-grid tick nearest **15:30 ET** (computed from the UTC timestamp via `market_calendar` — never a fixed UTC hour; the EST/EDT drift of fixed-UTC crons is documented in `docs/crons.md`). 15:30 ET is an arbitrary starting value, labeled as such. One evaluation record (`paper_engine_entry_evals`) stores: chain fetch result, selected contract, full quotes, per-arm gate results, per-arm entered-or-skipped + reason. **Contract selection runs before gates**, so a gate-blocked entry (arm A blocked, arm C entering) still has its contract and quotes captured — without this, question 4 is unanswerable.

**4.2 One open position per (arm, ticker).** When a cycle closes, the next entry is the next daily evaluation that passes that arm's gates. `cycle_seq` increments per (arm, ticker).

**4.3 Exits.** At every 15-min tick, each open position gets `assess_position(as_of=tick_ts)` with live inputs (spot, option ask, ex-div, earnings). The arm's policy maps the verdict to an order; the order fills under §5.3. Ex-div and earnings dates come from `yf_proxy.get_stock_info`, run through the shared usable-number/date validator (§5.5) — a NaN dividend yield must never buy silence (lesson 2026-08-16, NaN sails through None-guards). Dividend *amount* comes from the most recent actual dividend in history, never `spot × dividendYield`.

**4.4 Assignment is modeled, not observed — and must say so.** Paper positions can't actually be assigned. Model: (a) expiry ITM → assigned, settle at intrinsic; (b) early: ITM and ex-div ≤ 1 trading day and extrinsic < dividend (cc_sim's rational-exercise branch). Every modeled assignment is a first-class event, alerts Discord, and appears on the health page with its full inputs. Additionally, per the constraint-reachability lesson (2026-08-16, Exp 015's tautological "0 assignments"): count how many ticks *approach* the assignment branch (ITM with ex-div ≤ 3d) per arm, and if arm A reports 0 assignments with 0 approaches, the report must say "non-binding — the state was never reached," not "constraint met." Expect arm B to be the arm where assignment modeling actually binds.

---

## §5 Market data and fills — the part to get exactly right

**5.1 Decision-moment capture.** At entry evaluation and at every 15-min tick with any open paper position: capture full `bid/ask/last/volume/openInterest/impliedVolatility` for every relevant contract (the union across arms), plus spot. A quote captured at 19:50 UTC cannot price a decision made at 14:22 — the daily 19:50 chain-capture cron is NOT a substitute and this engine does not read it for pricing. Rows go to `paper_engine_quotes` keyed by `(contract_symbol, tick_ts)`. Cloudflare-worker options cache is 5 min — fine under a 15-min grid; never tighten the grid below the cache TTL.

**5.2 Fill realism — executable-conservative, no exceptions.**
- SELL (open) fills at **bid**. BUY BACK (close) fills at **ask**. Never mid, never last. Spread width `(ask − bid)` and spread % of premium stored on every fill.
- Entry liquidity floor: entry requires a present, usable bid ≥ $0.05 (arbitrary starting value, labeled) and non-crossed market (bid ≤ ask). Fails → no entry for ANY arm that day, reason logged (`no_bid`, `crossed`, `proxy_empty`). This is realism, not cowardice: Dad cannot sell at a zero bid, and KKR's 15%-OTM strike trades a median of 3 contracts/day.
- Commissions: a per-contract commission constant (default $0.65/contract/side — labeled an assumption from typical retail brokerage, to set to Dad's actual rate when known) is applied to every fill and reported as its own line, never buried in P&L.

**5.3 Human latency.** When a policy decides to trade at tick T, the fill uses the quote at the **first tick with `tick_ts ≥ T + 15 minutes`** — normally the next tick, later if the cron drifted (drift absorbed by construction). If no such tick exists before close, the fill uses the first tick of the next session, and `overnight_gap = true` is recorded. Actual realized latency is stored on every fill. Entries and exits both. Dad is not an HFT; this engine is structurally incapable of pretending he is.

**5.4 Missing data is loud, forever** (research-discipline rule 5; lessons 2026-03-23 silent repricing, 2026-08-17 carried-forward fills):
- Every proxy failure, empty chain, missing contract, and unusable quote is logged AND counted in a per-run tally persisted with the heartbeat. `yf_proxy._get` returns `{}` on failure — the engine must distinguish "proxy failed" from "empty chain" explicitly and never treat silent-empty as data.
- A tick with no usable quote for an open position: carry the last quote forward, set `stale=true` on the observation, and count it. A fill executed on a carried-forward quote is a **stale fill**; every P&L and retention number the engine ever reports is reported twice — all fills, and real-fill subset — per ticker, never pooled. If the two disagree in sign, the real-fill number is the result (lesson 2026-08-17, verbatim).
- ≥ 3 consecutive stale ticks on any open position → Discord warning (data problem, not strategy problem).

**5.5 One validator, everywhere.** Promote `position_monitor._is_usable_number` into the shared module and use it on every externally-sourced float (bid, ask, spot, dividend, IV) and a date-validator on every externally-sourced date. Rejects `None, NaN, inf, negative, non-numeric` and, where zero is meaningless, zero. Tests parametrize over `[None, nan, inf, -1, 0, 'x']` (lesson 2026-08-16). Count every tick where `assess_position` ran with `current_option_ask=None` (the premium-captured-defaults-to-0 trap, §0) — that counter is a health-page metric with a red threshold.

**5.6 Persistence discipline** (lessons 2026-08-15 write-helpers/4-month outage, 2026-08-18 data-contract):
- All writes go through read-back-verified helpers (the `monitor_positions._sb_insert(verify=True)` pattern: `Prefer: return=representation`, raise if the echo is empty). Confirmed counts only, never `len(attempted)`. A run whose persisted count is 0 when it attempted > 0 exits 1.
- Every row carries `engine_commit_sha` (`GITHUB_SHA`) and `engine_version` (lesson 2026-08-17, engine-lineage).
- **Schema contract check at startup, in-workflow:** before trading, the engine selects the exact expected column list from each of its tables (PostgREST rejects unknown columns even on empty tables — lesson 2026-08-18). Contract mismatch → exit 1 before the first decision, Discord alert. This runs where credentials exist (the workflow), not in credential-less CI.
- All timestamps are full `timestamptz` UTC. Never a bare DATE for anything that gets compared to a time (the midnight-UTC DATE parse caused a weekend false alarm — lesson 2026-08-18 vacuity guard).

---

## §6 Pre-registration, kill switches, and milestones — immutability with teeth

**6.1 What gets registered, before the first paper trade:** H40–H43 (per §4) via `signal_registry.pre_register`, executed through `registry-sync.yml` so the sqlite-fallback guard applies (the workflow fails the job if the log shows `sqlite:` — signal_graveyard's silent-fallback history, lesson 2026-08-16). `workflow_dispatch` only works from the default branch (lesson 2026-08-17), which forces the sequencing in §6.5.

**6.2 Thresholds: relative where the baseline is inherited, derived where absolute** (lesson 2026-08-16, threshold calibrated against a broken baseline; global rule: no invented constants presented as derived):
- Before freezing `PREREGISTRATION.md`, re-run the corrected `cc_sim` engine (current main, real-fill subset standard) to produce the reference table: per-ticker expected P&L/cycle, retention, hold-time distribution, worst 30-day option-leg drawdown across owned + stress windows. Record engine commit SHA and the table IN the pre-registration. These are the baselines every threshold references.
- Verdict rules are phrased as: minimum completed-cycle floor (derived from the hold-time distributions; shown work) AND a bootstrap-CI condition on the pre-registered metric (e.g., "H41 concludes 'copilot adds value' iff ≥ N pooled cycles AND the 90% bootstrap CI of per-cycle (A−B) option-leg P&L excludes 0 in A's favor"). Executor writes the exact numbers with derivations; anything not derivable is labeled "arbitrary starting value" in the registration itself.
- Retention is a ratio: pre-state its behavior when the numerator goes negative, and always report numerator (premium kept, $) and denominator (premium collected, $) beside it (lesson 2026-08-16, ratio inversion).

**6.3 Kill criteria — two kinds, never conflated.** "Turn the strategy off" must be a pre-registered, mechanical decision, not a mood. Both classes live on the health page as a status board (ARMED / TRIGGERED, current value vs threshold).

*Engine-integrity pauses (data problem → pause entries, keep monitoring, no strategy conclusion):*
- Quote coverage (usable quotes / expected quotes) over trailing 5 sessions < threshold (derive from the first 2 weeks' observed coverage; until then, an explicitly-labeled starting value).
- Collector heartbeat stale (calendar-aware, reuse `market_calendar` + the freshness pattern; §7).
- Schema contract failure, graveyard unreadable, or `sqlite:` backend detected → hard stop.

*Strategy kill switches (pre-registered in H40; TRIGGERED → new entries halt in the affected arm/ticker, Discord alert, milestone review convenes early):*
- Portfolio option-leg drawdown (real-fill accounting) exceeds K× the worst 30-day drawdown observed in the corrected backtest reference table (K derived and justified in the registration; the reference number and its engine SHA recorded beside it).
- Any modeled assignment in arm A → automatic halt of that ticker + review (with the §4.4 reachability disclosure attached).
- Per-ticker: M consecutive losing cycles where the backtest reference gives that ticker a ≥ p% per-cycle win rate (derive M from the binomial math; show it).
- EMERGENCY verdicts fired in paper > E times in 30 days (crash-regime buyback cost is our biggest untested number — an EMERGENCY cluster means we're living the untested case; stop and look).

A TRIGGERED kill is advisory-to-production: it halts the *paper arm* and alerts Charles; it never edits `ticker_strategies.py` (that path stays behind the walk-forward + approval-gate pipeline — lesson 2026-03-27, Exp 013 direct deploy).

**6.4 Immutability mechanics** (closing the upsert hole found in §0):
- `PREREGISTRATION.md` lives in `experiments/<NNN>_paper_engine/` (next free NNN), committed and merged BEFORE the engine can trade. Its SHA-256 is stored in each H40–H43 row's `pass_thresholds` JSON at registration time.
- The registration script refuses to run if any of H40–H43 already exists with different `pass_thresholds` (read-before-write; the upsert must never silently overwrite).
- The engine's startup gate: read back H40–H43 from Supabase, recompute the committed doc's hash, compare. Missing rows, hash mismatch, or sqlite backend → exit 1 before any decision. Result: editing the success criteria after go-live bricks the engine loudly instead of bending the experiment silently.
- The pushed commit SHA + timestamp of the registration merge is the durable pre-registration record even if Supabase were lost (lesson 2026-08-17, workflow_dispatch).

**6.5 Sequencing (two PRs, strict order):**
1. **PR-1 (small):** migration `005_paper_engine.sql` + `PREREGISTRATION.md` + registration script + `paper-engine.yml` (shipped with the startup gate that fails while H40–H43 are absent — so merging it is safe and the gate's red state is its own baseline). Merge → apply migration over ssh (idempotent SQL, `STATUS: APPLIED` comment, read-back verify; RLS deny-all like migration 004) → dispatch `registry-sync.yml` to register H40–H43 → read back.
2. **PR-2:** engine + shared-module refactor + tests + health page + this spec's acceptance evidence. First paper trade only after PR-2 merges and the startup gate passes green on a real scheduled run.

**6.6 Milestone reviews — decisions pre-committed in `PREREGISTRATION.md`, not improvised at review time:**
- **Day 30 — integrity checkpoint. No strategy verdicts** (samples are too small; pre-commit to this so nobody quotes day-30 P&L). Graded: quote coverage, stale-fill %, clause-reachability counts (every copilot clause's fire count — a clause at 0 across hundreds of observations is presumed unwired, not unlucky; lesson 2026-08-16), zero silent Nones, heartbeat record.
- **Day 90 — attribution interim.** Paired A−B and A−C differences with CIs; kill-switch board review; per-ticker cycle counts vs the registered floors. Pre-committed decision of the form: "if arm A trails arm B by more than X after ≥ N pooled cycles, we conclude the copilot is net-negative forward and escalate to Charles" — executor writes X and N with derivations.
- **Day 180 — verdict.** Each of H40–H43 graded pass/fail against its registered rule; `mark_result` in the graveyard, pass AND fail. Results reported as ranges across sub-windows (regime dominates; −78%→+93% half-year swings are on record), per ticker, real-fill and all-fill, with the epistemic-contract caveats of §2 attached verbatim. A pass is *evidence for* Dad's onboarding decision (Charles's call, per the Phase-2 runbook) — never an automatic promotion.

---

## §7 The health page — `/paper-engine`

A single decision surface answering, at a glance: **is the engine healthy, is the strategy healthy, and has anything pre-registered tripped?** Next.js page in `web/`, house design language, patterned on the `/how-it-works` components. It lands behind the existing default-deny auth gate automatically (`web/src/proxy.ts` — do NOT add it to the public list; arm P&L at Dad's size is effectively a holdings disclosure).

**Layout — three bands, in this order:**

*Band 1 — Engine integrity (can we trust the numbers on this page?):*
- Collector heartbeat freshness (calendar-aware — reuse the `market_calendar` + `computeFreshness` pattern; staleness only alarms during market hours).
- Quote coverage % per ticker (trailing 5 sessions), missing/invalid/proxy-failure counts, `assess_position`-ran-without-ask counter, stale-tick and stale-fill %.
- Schema-contract status, graveyard backend (must read "supabase"), engine commit SHA of the last run, workflow failure count (7d).
- Clause-fire table: every copilot clause (the 14-row ladder) with lifetime fire counts per arm — the standing reachability audit.

*Band 2 — Strategy health (the Goldman table):*
- Per arm × ticker: completed cycles (vs registered floor), option-leg P&L (real-fill and all-fill, side by side), premium retention shown as kept-$ / collected-$ → % (numerator and denominator visible), spread cost and commissions as their own columns, assignments (with "modeled" label), worst cycle.
- Paired differences A−B and A−C with bootstrap CIs (the attribution readouts).
- The full trade ledger: every fill with alert-time quote, fill-time quote, realized latency, side prices used, spread, exit clause name, verdict source, engine SHA. This table IS the auditable receipt — exportable as CSV.
- Regime strip: trailing realized-vol percentile per ticker, so every number is read in regime context.

*Band 3 — Pre-registration board:*
- H40–H43: registered thresholds (immutable, with doc hash), current standing, cycle progress bars toward verdict floors.
- Kill-switch board: every registered kill with live value vs threshold, ARMED/TRIGGERED, and trigger history.
- Milestone countdown (30/90/180) with the pre-committed decision text displayed — the decisions are on the page *before* the data arrives, which is the point.

**Plumbing rules:** the page reads `/api/paper-engine/health` (server-side Supabase via `getSupabase()`, service key stays server-side). The route **reports status only — it never alerts** (lesson 2026-08-19: a health endpoint that alerts turns every poller into an alerter; one stale heartbeat produced an alert per minute for hours). Alerting lives exclusively in the scheduled engine runs, deduped on state-change (alert once when a kill flips to TRIGGERED, not on every tick it stays there — alert-state persisted in `paper_engine_events`). Any threshold constant shared between the Python engine and the TS page is codegen'd or served from the API — never hand-synced (lesson 2026-08-18: strategies.ts drift; a TS mirror of a Python truth is production drift by definition).

---

## §8 Ops — scheduled-job hygiene (silent failure is the #1 failure class)

- **New workflow `paper-engine.yml`:** `*/15 13-21 * * 1-5` UTC (same grid as the monitor; the engine itself is calendar-aware via `market_calendar` and exits fast — with a heartbeat noting `market_closed` — outside sessions). It is a **separate workflow** from `position-monitor.yml`: research-adjacent code never rides the safety-critical monitor's critical path (lesson 2026-08-16: a scipy import took down the monitor).
- Explicit `pip install` line (workflows do NOT read requirements.txt — same lesson) plus a `python3 -c "import paper_engine, position_monitor, ..."` smoke-test step before the real step, so a missing dep fails loudly at the right place.
- `if: failure()` Discord step using `secrets.DISCORD_WEBHOOK` (never plaintext — 4 repos had webhooks in YAML, 2 public; this repo is public). A cron with no failure alert is already dead, date TBD.
- Engine writes its own `monitor_heartbeats` row (`source='github-actions'`, `role='paper-engine'` or equivalent per the schema §0 confirms) every run including failure paths — the freshness reader credits every chain that actually runs (lesson 2026-08-19).
- 3+ consecutive failures = incident, not noise. GitHub auto-disables schedules after ~60 days of repo inactivity and after long failure streaks — the day-30 integrity checkpoint includes checking the workflow is still enabled.
- Nothing runs on the Hetzner box; no new containers; storage cost ≈ $0 (≈ a few hundred Supabase rows/day; quotes retained indefinitely — they are the audit trail).

---

## §9 Storage — migration `005_paper_engine.sql`

New tables (never reuse `paper_trades` — 444 of its 452 scored rows are synthetic BSM backfill and the two populations must be unjoinable by construction, not by a WHERE clause someone forgets):

- `paper_engine_entry_evals` — one row per (ticker, trading day): tick_ts, chain status, selected contract, quotes, IV rank + threshold used, per-arm gate results and entered/skipped + reason.
- `paper_engine_quotes` — (contract_symbol, tick_ts) → bid/ask/last/volume/oi/iv/spot, usable flags, staleness.
- `paper_engine_trades` — the ledger: (arm, ticker, cycle_seq) unique; entry/exit fills with both quotes (alert-time and fill-time), latency, spread, commission, clause name, verdict, P&L (all-fill + real-fill flags), assignment fields, engine SHA/version.
- `paper_engine_events` — append-only: alerts, pending/executed fill pairs, kill-switch state changes, modeled assignments, alert-state for dedup.

Conventions from migration 003/004: idempotent SQL, `STATUS: APPLIED <date>` comment maintained, read-back verify after applying, RLS enabled deny-all (service-role-only) in the same migration, PostgREST schema-cache reload. Applied manually over ssh per the documented command in `migrations/001`.

---

## §10 Testing & CI (financial logic ships with tests, no exceptions)

Before PR-2 merges, all in `tests/`, running in the existing `test.yml` pytest step:
- **Accounting:** one hand-calculated cycle (entry credit, buyback, commission, spread) asserted to the cent; defined-risk sanity (a covered-call option leg's loss can't exceed buyback−premium given the price path); `sum(daily) ≈ sum(realized)` (lesson 2026-03-24).
- **Fill rules:** sell-at-bid/buy-at-ask asserted; latency rule (T+15, drift, overnight gap); liquidity floor (no-bid, crossed, proxy-empty each produce the right skip reason).
- **Validator:** parametrized `[None, nan, inf, -1, 0, 'x']` on every guard.
- **Vacuity guards in every regression test** (lesson 2026-08-18): each test that asserts "X doesn't happen" first demonstrates the setup CAN produce X.
- **Policy parity:** the extracted shared policy module replays a recorded `cc_sim` experiment and matches its committed results byte-for-byte (the refactor changed nothing).
- **No-broker guard:** a test asserting no broker/order libraries are importable from the engine's dependency graph (`ib_insync`, `alpaca*`, `robin_stocks`, ...) — the "cannot touch a broker" guarantee, demonstrable red by temporarily adding an import.
- **Startup gate:** registration-missing and hash-mismatch both exit 1 (red-baseline these: run once against a fixture with no H40 → must fail).
- Every number in any results doc regenerates from a committed script into `results.json` (lesson 2026-08-17: no scratchpad numbers).

---

## §11 Acceptance — demonstrations, red-baselined (a check born green is presumed vacuous)

1. **Startup gate RED first:** engine run before registration exists → exits 1 with the right message (recorded). GREEN after §6.5 step 1 completes.
2. **Immutability demonstrated:** edit a threshold in a scratch copy of `PREREGISTRATION.md`, run the hash check → RED. Attempt to re-register H40 with different thresholds → script refuses.
3. **Write-verify demonstrated:** point a scratch config at an invalid key → run reports 0 confirmed writes and exits 1 (not green-with-zero-rows).
4. **Schema contract demonstrated:** select a deliberately-wrong column against live Supabase → startup fails before any decision.
5. **Latency + conservative fills demonstrated on real market data:** one full paper cycle (entry eval → entry fill at bid at T+15 → ticks → exit fill at ask) walked through in the PR description with the actual quote rows, showing alert-time vs fill-time quotes and the spread cost.
6. **Kill-switch alert demonstrated** with a synthetic breach (fixture): state flips to TRIGGERED, exactly one Discord alert fires, health page shows TRIGGERED; a second tick in the same state alerts zero times.
7. **Health page freshness demonstrated red** (stale fixture during market hours) then green; page verified rendered on production (curl the deployed page for the new content — merged is not rendered; lesson 2026-08-18) and confirmed NOT publicly reachable (unauthenticated request redirects).
8. **Heartbeat + failure alert demonstrated:** one deliberately-failed workflow run produces the Discord failure alert and a `ok=false` heartbeat.
9. **Clause-reachability counters live:** after the first real days, the health page shows nonzero counts for at least the common clauses; any all-zero clause is flagged on the page, not hidden.
10. First scheduled run green end-to-end: entry evals for every universe ticker, confirmed-count writes, heartbeat, Discord silent.
11. `docs/crons.md` updated with the new workflow; `tasks/roadmap.md` and the Phase-2 runbook cross-reference the milestone dates. Proof-of-work block includes a correctness review (financial calculation) and, if `proxy.ts`/env/RLS were touched at all, a security review.

---

## §12 Non-goals / guardrails

- **No real orders, ever.** No broker credentials, no broker libraries (§10 guard). This engine cannot touch a broker.
- **No production rule changes from paper results** — early or final. The `ticker_strategies.py` path stays behind pre-registration → walk-forward → approval-gate → one variable per commit. A kill-switch TRIGGERED state alerts Charles; it edits nothing.
- **No third alert engine.** Any urge to "just adjust" a verdict inside the paper engine is the birth of engine #3 — the answer is no.
- **No new arms, thresholds, or metrics after go-live** without a fresh registration and a separately-reported start date.
- **No touching** the existing `paper_trades` tracker, scorer crons, or the monitor workflow (beyond reading shared modules). The old tracker keeps running; its first real-price outcome (2026-09-18) is a separate, hold-to-expiry data point.
- **Costs ≈ $0.** Anything that would cost money (paid data, new infra) → stop and ask (standing rule).
- If any §0 verification contradicts this spec materially, stop and report before building — do not reconcile silently.

---

## Appendix — lesson-to-design map (why each element exists)

| Design element | Guards against (tasks/lessons.md) |
|---|---|
| Explicit `as_of` on every `assess_position` call; no wall clock in the engine | 2026-08-16 "Six experiments ran with DTE silently pinned to 0" |
| Shared validator; count ask-was-None ticks | 2026-08-16 "`is None` is not a missing-data check"; 2026-08-18 "A default on a lookup" |
| Sell-at-bid/buy-at-ask; real-fill vs all-fill dual reporting | 2026-08-17 "A backtest can look profitable purely because the option did not trade" |
| Read-back-verified writes; confirmed counts; exit 1 on zero | 2026-08-15 "Write helpers returned attempted count" (4-month outage) |
| Startup schema-contract check | 2026-08-18 "Verify the data contract before verifying the schedule" |
| Graveyard via registry-sync + backend assertion; startup gate | 2026-08-16 "signal_graveyard has never existed in Supabase"; 2026-08-17 "workflow_dispatch only works from the default branch" |
| Registration overwrite refusal + doc hash | §0 finding: `pre_register` upserts — immutability was not real |
| Thresholds relative to a same-engine baseline, derivations shown | 2026-08-16 "threshold calibrated against a broken baseline"; global "never present an arbitrary threshold as derived" |
| Clause-fire counters; non-binding-constraint disclosure | 2026-08-16 "hard constraint satisfied by construction"; "a take-profit rule" (mechanism uncounted) |
| Retention's numerator/denominator shown; negative-numerator note | 2026-08-16 "A ratio metric silently inverts" |
| Engine SHA on every record | 2026-08-17 "Trusted an experiment's numbers without checking engine lineage" |
| Separate workflow from the monitor; import smoke test; explicit pip line | 2026-08-16 "A research import at module scope took down the monitor" |
| Failure alerts, heartbeats, calendar-aware freshness | Global cron-hygiene rules; 2026-08-19 "One stale heartbeat produced an alert per minute" (report/alert separation) |
| Shared policy module, byte-identical replay | 2026-08-16 "Built a second simulator"; 2026-08-17 "one loader, three copies" |
| New tables, unjoinable from BSM backfill | `results/013_paper_trade_audit.md` (444 synthetic rows published as a track record) |
| Committed scripts regenerate every reported number | 2026-08-17 "a number no committed code could regenerate" |
| Two-PR sequencing; isolated worktrees; red baselines | 2026-08-18 "Commit raced"; "check born green is vacuous" |
| Health page verified rendered + auth-gated | 2026-08-18 "Declared DONE while the surface served invalidated numbers"; 2026-08-19 "proxy.ts fail-open" |
