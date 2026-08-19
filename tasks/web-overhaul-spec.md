# Web Overhaul Spec — options.imprevista.com must render the corrected world

> ## STATUS 2026-08-19 — EXECUTED, plus follow-ups. Read before any re-run.
> **§7.1 closed green** (PR #12, 25/25 against production, red-baseline demonstrated). Landed after: **PR #14** (P&L unit clarity — per-contract label + cap-aware at-size totals + real-fill basis, verifier-enforced), **PR #15** (win/loss caption: wins = cycles ended profitable under the copilot policy, loss defined on the card), and this PR (how-it-works win-rate definition corrected — it claimed hold-to-expiry while Exp 022 ran `policy=production copilot`; verifier's forbidden pattern narrowed so paper-trade pages' legitimate hold-to-expiry usage stays legal).
>
> **Open items a future session must NOT redo blindly:**
> 1. **§7.5 residue → onboarding-day check.** /positions' timestamped verdicts + staleness banner are proven by fixture only (zero open trades have ever existed). On the day the first real position is entered: verify the live rendering. Mirrored in the Phase 2 runbook.
> 2. ~~**No authentication**~~ — **CLOSED 2026-08-19, PR #21.** Red baseline recorded first: unauthenticated `/api/holdings` returned 200 with the real holdings JSON, and the public anon key could `INSERT` into `trades` (201) and `DELETE` from it (204). Now: a default-deny `proxy.ts` (Next 16 renamed the middleware convention — a file named `middleware.ts` would be a silently-expiring gate) with an HMAC-signed HttpOnly session cookie, and RLS enabled on all six tables with zero anon grants left. 31/31 production checks green; the anon key gets 401 on every read and write it previously succeeded at. `/how-it-works` is deliberately **public** (Charles, 2026-08-19) — its audience includes Dad before he has a login. Still carried: eight further tables this app writes keep full anon grants, which is an integrity exposure on recommendation inputs and needs its own scoped pass.
> 3. **The TS engine at /api/cron/monitor is NOT dead code — it is chain 1's alert engine** (the Hetzner cron curls it every 15 min). It can drift from position_monitor.py. Decision required (infra lane): either the route persists through the same assessment store with a golden-case parity suite against assess_position(), or chain 1 moves to invoking the Python monitor server-side. Until then, any threshold change must land in BOTH engines in the same PR.
> 4. **Scorecard flip 2026-09-18** — first real-price paper-trade outcomes score then; the scorecard's "no real-price recommendation scored yet" framing flips to real stats. That flip gets its own red-baselined verification.
> 5. **Correctness subagent review** of the P&L-display diffs (PRs #14/#15) — **RUN 2026-08-18, verdict PASS.** The at-size math is cap-aware and sign-safe (KKR 316x7=$2,212 and -88x7=-$616 both traced end-to-end; the header's contract count and the multiplication use the same variable, so displayed-7/computed-100 cannot occur), and PR #15's caption matches the actual win predicate. **One MEDIUM finding is still open:** the same caption/predicate mismatch PR #15 fixed still ships on `sell/paper-trade-scorecard.tsx:157` and `paper-trades/paper-trade-list.tsx:153` as "% expired worthless" — the API's `win_rate` is `pnl_pct > 0`, and `score_paper_trades.py:54-64` gives expired-ITM trades a positive `pnl_pct` with `expired_worthless=False`, so a win is not the same as expiring worthless even under the hold-to-expiry scorer. PR #16 narrowed the verifier's forbidden pattern to exempt those two strings on the premise that "that scorer IS hold-to-expiry" — the scorer's own ITM branch contradicts that premise, so the exemption should be revisited when the strings are fixed.
>
> **Binding process rules for ANY executor of this spec (learned executing it — tasks/lessons.md 2026-08-18):** commits go through ISOLATED git worktrees, never the shared checkout, and `git show HEAD --stat` must list every intended file before push; every new acceptance check gets a demonstrated RED baseline against live production before it is trusted — a check born green is presumed vacuous. `docs/claims-inventory.md` gains a row for every new user-facing claim in the same PR that ships the claim.


**Executor:** Opus 5, fresh session, working dir `/Users/charlesrogers/Documents/options-tool`
**As of 2026-08-18.** Facts rot — §0 first, every claim below is a hypothesis to confirm.
**Read first:** `tasks/lessons.md` (especially 2026-08-18 entries), `ticker_strategies.py` (the single source of truth — read it in FULL including every note), `tasks/roadmap.md`, `web/src/lib/strategies.ts`, `web/src/app/sell/`, `web/src/app/positions/`, `web/CLAUDE.md`

## §0 Verify current state before touching anything

```bash
git log --oneline origin/main -8            # what has landed since this spec was written
python3 -c "import ticker_strategies as t; [print(k, v.get('tier'), v.get('expected_pnl'), v.get('expected_win_rate')) for k,v in t.TICKER_STRATEGIES.items()]"
grep -n "expectedPnl\|tier:" web/src/lib/strategies.ts | head -20
curl -s https://options.imprevista.com/sell | grep -oE '\$[0-9]{3}|100%|Good|probation|Untested' | sort | uniq -c   # what production RENDERS today
```

If someone has already fixed part of this, build on it, never beside it (check sibling branches/worktrees too).

## §1 Why this spec exists

The site is the product. On 2026-08-18 the /sell page rendered: AAPL **$351 / 100% win** (corrected value: **$141 / 91%**), KKR **100 contracts** (liquidity-capped at **7**), GOOGL **Good** (probation), TMUS/KKR **Good** (probation, with *negative real-fill P&L* caveats), AMZN recommendable at **5% OTM** (skip — failed validation at 15%), "Experiment 009: +204%" (invalidated experiment), and a paper-trade scorecard of unaudited hold-to-expiry numbers presented as if they were the strategy's record.

Root cause: `web/src/lib/strategies.ts` is a hand-maintained duplicate of `ticker_strategies.py`, frozen in March. Four merged PRs corrected the Python; nothing propagated. This is the project's signature defect class (three data loaders, two monitor engines, now two strategy tables). The fix is structural, not a one-time sync.

**A screen that looks authoritative and is wrong is worse than no screen.** Charles's father (10,000 shares/ticker, ~$10M notional) is the intended user.

## §2 Principles (binding on every part)

1. **Single source of truth:** `ticker_strategies.py` owns all strategy facts (OTM%, DTE, tier, expected P&L, win rate, notes, `max_contracts` + reason, per-ticker `iv_threshold` via `get_iv_threshold`). The web NEVER hand-copies them.
2. **No number without lineage.** Every quantitative claim rendered anywhere on the site traces to a results file + experiment ID (and, for simulated P&L, the engine that produced it). A number that cannot be traced is removed, not kept.
3. **Ranges over points.** Exp 022 measured half-year retention swinging −77.9% → +92.8% on identical rules — annual point estimates measure regime luck. Wherever a per-ticker $ figure is shown, show or link the range (the notes in ticker_strategies.py already carry them).
4. **Restricting-only auto-ships.** Any change that makes a claim smaller, a tier lower, or a cap tighter ships without asking. Anything that raises a published claim needs Charles's explicit sign-off.
5. **Rendered-surface acceptance.** Nothing in this spec is done until the LIVE page provably renders the new content and provably no longer renders the stale content (curl + grep both directions). A green deploy is not acceptance.

## §3 Part A — Strategy data pipeline (kills the fossil permanently)

1. **Codegen:** `scripts/gen_strategies_ts.py` reads `ticker_strategies.py` and emits `web/src/lib/strategies.ts` with a `// GENERATED FROM ticker_strategies.py — DO NOT EDIT` header. Fields per ticker: `otmPct, minDte, maxDte, tier, expectedPnl, expectedWinRate, note, skip, ivThreshold, maxContracts, maxContractsReason`. Export `DEFAULT_IV_THRESHOLD` and a `TIER_CONFIG` that includes **probation** (and drops none of the existing tiers — unknown tiers must render, not crash).
2. **Drift test in CI:** `tests/test_strategies_ts_drift.py` regenerates into a temp file and fails on any byte difference with the committed file. Demonstrate it red (hand-edit one char) then green.
3. **Component updates** (`web/src/app/sell/sell-recommendations.tsx` and anywhere else that imports strategies):
   - Contracts = `min(floor(shares/100), maxContracts ?? ∞)`; when capped, render the cap AND its reason ("Liquidity: strike trades ~3/day — Exp 021"). KKR at 10,000 shares must read **7 contracts**, prominently, because 100 was the number a human would have traded on.
   - Tier badges: add `probation` styling (full literal Tailwind class strings — no dynamic class construction, it defeats the JIT purge). Probation cards must state WHAT is probationary (stock-close validation only / real-fill P&L negative — the note carries it).
   - `skip` tickers render in Not Recommended with their note — AMZN and MSFT included, not just TXN.
   - Per-ticker IV threshold: DIS shows **IV Rank ≥ 75** (Exp 023), others ≥ 50.
   - Caption rewrite: remove "Experiment 009: +204%" everywhere. Honest replacement: "IV-rank entry gate. Per-ticker trial (Exp 023): DIS ≥ 75 validated on holdout; other tickers keep the default ≥ 50; the gate failed its trial on TMUS and is retained pending a loosening experiment."
4. **Expected P&L display:** value + a "range" affordance sourced from the note (e.g. "chain range −$776..$352") — the point number must never appear without its spread. If the layout can't carry it, show the range instead of the point.

## §4 Part B — Claims inventory (every page, every number)

Crawl every route: `/`, `/sell`, `/positions`, `/paper-trades`, `/how-it-works`, and any others in `web/src/app/`. Produce `docs/claims-inventory.md`: one row per quantitative or evaluative claim — claim, page, source (experiment/results file), verdict (KEEP / FIX→what / REMOVE), and status. Execute every FIX/REMOVE in this session. Known suspects: "81% win rate", "+204%", "never loses", "100% win rate", "$822", bear-market claims citing Exp 010's Monte Carlo as if historical, anything citing Exps 007–013 as evidence. The inventory is committed — it is the audit trail for "the site says nothing we can't defend."

## §5 Part C — Paper-trade scorecard honesty

1. **Relabel:** the scorer measures **hold-to-expiry outcomes of logged recommendations**, not the copilot strategy (which buys back early). The scorecard must say so on its face — title or subtitle, not a tooltip.
2. **Run the audit** (the deferred Block B item): quantify what was actually logged/scored across the 2026-03-30 → 2026-08-15 outage, separate BSM-backfilled from live-chain trades, recompute headline stats on the verified set → `results/013_paper_trade_audit.md`. The scorecard then renders audited numbers with an outage-gap note, or — until the audit lands — renders "audit pending" instead of the stats. Unaudited numbers may NOT keep rendering bare.
3. Cross-check `docs/dad-pitch.md` against the audited numbers (partially corrected already — verify, don't assume).

## §6 Part D — /positions renders stored verdicts, loudly stale

The monitor persists to `position_assessments` (Block A). The positions page must READ stored assessments instead of re-deriving via `copilot.ts` — one engine, one verdict, phone and screen can never disagree. Requirements: every verdict shows its assessment age ("as of 12:47 ET"); a red banner when stale > 20 min during market hours (use the committed market calendar); NO client-side re-derivation fallback (that reintroduces engine #2 — stale-and-honest beats fresh-and-divergent). `copilot.ts` derivation logic survives only for explicitly-labeled what-if previews on hypothetical positions, if the Sell tab uses it; otherwise delete it. **Coordinate:** this touches the monitor's read path — confirm no infra-lane session is live before starting (one infra session at a time).

## §7 Acceptance (demonstrations, not assertions)

1. `curl -s https://options.imprevista.com/sell` (rendered HTML or its data payload) contains: `$141`, `91%`, `7 contract`, probation labels for GOOGL/TMUS/KKR, AMZN+MSFT under Not Recommended, `≥ 75` for DIS — and does NOT contain: `$351`, `$822`, `$447`, `$386`, `100 contracts` for KKR, `+204%`, a bare `100%` win-rate stat.
2. Drift test demonstrated red then green; `npx next build` clean before every push; deploy verified by polling the production URL for new content per CLAUDE.md.
3. `docs/claims-inventory.md` committed with zero rows left in FIX/REMOVE-pending state.
4. Scorecard renders either audited stats + methodology label, or "audit pending" — screenshot or curl-grep proof.
5. /positions shows assessment timestamps; staleness banner demonstrated by pausing the monitor briefly (coordinate with infra lane) or by fixture.
6. Close with ✅ DONE **only if** criterion 1 passes against production — otherwise ⏸ HANDOFF stating exactly which surface still renders stale content. That is the lesson this spec exists to enforce (tasks/lessons.md 2026-08-18).

## §8 Out of scope

RLS enablement (own gated session — but note it on the claims inventory if any page implies data is private). New features, collar page/workflow, Streamlit app (`streamlit_app.py` imports the Python truth directly — verify with one grep, then leave it). Anything that raises a published claim (list candidates for Charles instead).
