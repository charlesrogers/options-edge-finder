# Block A — Reliability (session s-0816-2151)

**Hard constraint:** Do not modify EMERGENCY thresholds or `assess_position` logic.
Consolidation moves *where* logic lives, never *what* it decides.

## §0 verification (done 2026-08-18)

| Fact | Status | Evidence |
|---|---|---|
| FACT-1 server monitor never ran | **CONFIRMED** | `curl -sf http://supabase-kong:8000` on host exits **6**; `&&` short-circuits. 36 cron firings in 24h, zero effect. |
| FACT-2 GH Actions is the only live monitor | **CONFIRMED** | `position-monitor.yml` succeeding every 15 min through 2026-08-17T22:00Z. |
| FACT-3 health 200 on fail | **CONFIRMED** | `route.ts:138` returns `NextResponse.json(...)` unconditionally. Live call: HTTP 200, `status:"warn"`. |
| FACT-4 CRON_SECRET plaintext | **CONFIRMED** | `/etc/cron.d/coolify-apps` mode 0644, holds `options-cron-2026` + PLY bearer + `dayscore-cron-2026`. |
| FACT-5 weekend false alarms | **CONFIRMED** | 48h wall-clock threshold, capture runs Mon–Fri. |
| FACT-6 three engines | **PARTLY WRONG** | Two, not three: `cron/monitor/route.ts` *imports* `assessPosition` from `copilot.ts`. Python + TS. |
| FACT-7 SQLite fallback | **FIXED** (f194edc) | `REQUIRE_SUPABASE=1` wired into 14 workflows. |
| FACT-8 read swallows | **FIXED** (f194edc) | monitor route 500s on read error; unassessed positions are loud. |
| FACT-9 auth open-fails | **FIXED** (f194edc) | both routes 500 when CRON_SECRET unset. Verified live: no-auth call → 401. |
| FACT-10 ex-div TZ | **FIXED** (f194edc) | `epoch_to_date` is UTC-aware. Hetzner host is `Etc/UTC` anyway. |

## New facts found in §0

- **FACT-11 — both alert paths read columns that do not exist.** `public.trades` is
  `(ticker, strike, expiry, sold_price, close_price, contracts, status, opened_at, ...)`.
  `monitor_positions.py:258-259` reads `expiration` / `premium_received`;
  `cron/monitor/route.ts:96-97` reads `trade.expiration` / `trade.premium_received`.
  `api/copilot/route.ts:80-81` — the path serving Dad's screen — reads `expiry` / `sold_price`
  and is CORRECT. So the screen and the phone disagree on the first real position.
  Demonstrated: real row shape → Python raises `ValueError`, TS silently computes `dte=NaN`
  (EMERGENCY still fires on ITM+exdiv, but every DTE-gated CLOSE_SOON/CLOSE_NOW rule
  goes permanently false). `db.add_trade` also inserts 5 nonexistent columns.
  Table currently has **0 rows**, which is the only reason this has not bitten.
- **FACT-12 — the TS monitor route has no notification credentials.** Coolify env for
  `options-edge-finder-ghcr` holds only EODHD/DATABENTO/NEXT_PUBLIC_*/CRON_SECRET.
  No `PUSHOVER_TOKEN`, no `PUSHOVER_USER`, no `DISCORD_WEBHOOK`. `sendPushover` returns
  early; health's Discord alert logs "alert dropped". Fixing FACT-1's guard *alone*
  would have produced a monitor that runs and delivers nothing.
- **FACT-13 (out of Block A scope, flagged)** — RLS is `false` on `trades`,
  `portfolio_holdings`, `paper_trades`, `option_chain_snapshots`, and the anon key is
  shipped to the browser as `NEXT_PUBLIC_SUPABASE_KEY`. Read/write open to anyone.
  Cross-app blast radius (91 tables incl. PLY users) — needs its own session.

## Plan

- [x] **P0 — FACT-11.** One field contract for `public.trades`, both alert paths corrected,
      `db.add_trade` corrected, pytest pinning the live column set so this cannot re-rot.
- [~] **P1 — FACT-1.** Repoint server cron at the Python authority (A2), not the TS route.
      Deploy `/opt/options-monitor` on Hetzner. Kill the unsatisfiable `supabase-kong` guard.
- [x] **P2 — Layer 0 heartbeat.** `monitor_heartbeats` + `position_assessments` tables;
      monitor writes both with read-back verification.
- [~] **P3 — FACT-3 + FACT-12.** Health returns non-200 on fail; add heartbeat check;
      set the missing Coolify notification env vars.
- [x] **P4 — FACT-5 (A6).** Market-calendar-aware freshness from a real NYSE calendar.
- [~] **P5 — Layer 2.** Cloudflare Worker cron trigger → health → Pushover.
- [x] **P6 — FACT-4.** Secrets to a 0600 env file; rotate CRON_SECRET across every consumer.
- [x] **P7 — notification ownership.** Python-on-Hetzner is primary; GH Actions fallback
      alerts only when the primary heartbeat is stale. No duplicate buzzes.
- [x] **P8 — docs/crons.md**, duplicate health cron resolved, Uptime Kuma Tier 2 monitor.
- [~] **P9 — demonstrations.** Kill the cron → alert ≤45 min. Force a write failure → loud.
      Weekend/holiday → zero alerts.

## Review — 2026-08-18

Legend: `[x]` done and demonstrated · `[~]` code complete, blocked on credentials.

### Demonstrated, not asserted

- **The column mismatch is real.** Fed the actual `public.trades` row shape to
  `assess_position`: raises `ValueError`. Fed the corrected shape: `EMERGENCY`.
- **The live database agrees.** `test_live_supabase_columns_exist` passed in CI
  against production Supabase. PostgREST rejects an unknown column on an empty
  table, so this is a real contract check with zero rows in the table.
- **The heartbeat persists.** A real monitor run against production wrote
  heartbeat `b46f7a31-ef10-4528-ab87-9e87839dc79a` and read it back.
- **The failure tests are not vacuous.** Three mutations applied — swallow the
  trades-read error, ignore a heartbeat write failure, assume the primary is
  alive when its heartbeat is unreadable — each caught by exactly one test,
  3 failed / 217 passed. Reverted, 220 pass.
- **The FACT-1 guard really cannot succeed.** `curl -sf http://supabase-kong:8000`
  run on the host exits **6**. 36 firings in 24h, zero effect.
- **The secrets are off disk.** `grep -c "Authorization: Bearer"
  /etc/cron.d/coolify-apps` → 0. Both wrapper scripts return 0 against live
  endpoints. Cron restarted clean.
- **Uptime Kuma Tier 2 is live.** Monitor 13 on the authenticated health path,
  60s / 3 retries, wired to Discord Red Alert, first heartbeat `200 - OK`. All
  13 monitors green after the restart.
- **A weekend produces no alarm.** Replayed the exact false alarm (run
  31984884170, 01:25 Sunday): old arithmetic gives 49h → red; trading-day
  arithmetic gives 0 sessions → quiet. A genuinely missed Monday capture still
  reads as 1 session stale, so the check was fixed, not softened.

### Blocked, and honestly so

`PUSHOVER_TOKEN`, `PUSHOVER_USER`, `DISCORD_WEBHOOK` exist only as GitHub
secrets — not in Coolify, not on the server, not anywhere readable. Without
them:

- the Hetzner primary monitor cannot deliver an alert, so it is written and
  installed but **not enabled**. Enabling it would replace a cron that lies with
  a cron that runs and delivers nothing, which is the same fault wearing a
  different colour.
- the Cloudflare outer loop is written but not deployed (also needs a
  Cloudflare login).
- the app's own Discord alerts have been dropping to `console.error` this entire
  time, which is its own finding.

Acceptance criteria 1, 2, and 9 (kill-the-cron, Hetzner-is-gone, fire drill) all
end in "a notification arrives on Charles's phone" and cannot be demonstrated
until those three values exist.

### Deliberately not done

- **FACT-13 / RLS.** `trades`, `portfolio_holdings`, `paper_trades` and
  `option_chain_snapshots` have `relrowsecurity = false`, and the anon key is
  shipped to the browser. Anyone with the public key can read or write them.
  Blast radius is 91 tables across every app on this Supabase, so it is not a
  change to make as a side effect of a monitoring session.
- **Chain-capture DST drift.** `50 19 * * 1-5` is 15:50 ET in summer and 14:50
  ET in winter. Changing it changes the research data, so it is a research
  decision. Recorded in `docs/crons.md`.
- **A1 UI work.** The web still derives verdicts in `copilot.ts` rather than
  reading `position_assessments`. The store is now written and populated; the
  read side, the "as of" timestamp and the stale banner are not built. Doing it
  before the primary path is enabled would swap a correct live derivation for a
  stored one that nothing is reliably writing.

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

---

# Web overhaul (session s-0817-1634) — `tasks/web-overhaul-spec.md`

The Python was corrected in March and again in August. The site was not. Everything below
is about closing that gap and making it impossible to reopen.

- [x] **§0** Verified current state before touching anything. Confirmed the fossil was live
      by fetching the production JS bundle (`351`, `386`, `447`, `822`, `204`, "never loses").
      Sibling check found no in-progress work on `strategies.ts` anywhere — no branch, no
      worktree, no uncommitted edit.
- [x] **§3 Part A** `scripts/gen_strategies_ts.py` generates `strategies.ts` from
      `ticker_strategies.py`; `tests/test_strategies_ts_drift.py` fails CI on drift
      (demonstrated red on a one-character edit, then green). Generator refuses to emit a
      live non-zero `expected_pnl` with no spread in its note.
- [x] **§3.3/§3.4 components** liquidity cap + reason on the card, probation badges that say
      which weaker instrument was used, per-ticker IV gate, skip partition driven by the
      `skip` flag, range and real-fill figure beside every point estimate.
- [x] **§4 Part B** `docs/claims-inventory.md` — 40 rows, every route, zero left pending.
- [x] **§5 Part C** `results/013_paper_trade_audit.md` (the deferred Block B item) +
      `scripts/audit_paper_trades.py`. Scorecard relabelled and gated on provenance.
- [x] **§5.3** `docs/dad-pitch.md` cross-checked, six further claims corrected or withdrawn.
- [x] **§6 Part D** `/positions` reads stored verdicts from `position_assessments`; no
      client-side re-derivation; age on every verdict; staleness banner.
- [x] **§7** `scripts/verify_production_claims.py` — run against production pre-deploy it
      failed all 25 checks, which is what makes a later pass mean anything.

## Review

**The finding that matters most was not in the spec.** §5.2 asked for the paper-trade
outage to be quantified. The audit found something larger: all 444 scored trades are
Black-Scholes backfill, and **zero real-price recommendations have ever been scored**. The
"76.4% win rate" the site published as its track record is a property of `bsm_call()` in
`backfill_paper_trades.py`. The first real outcome cannot exist before **2026-09-18**.

**Second finding:** the 144-day logging gap (2026-03-24 → 2026-08-15) is the only gap longer
than seven days in the entire history, and the card kept rendering a win rate throughout it
under the caption "Every recommendation logged and scored automatically."

**Structural, not cosmetic.** Three of the four fixes are guards rather than edits: codegen
+ drift test (the fossil cannot return), the spread rule enforced at codegen (a bare point
estimate fails the build), and the provenance split computed in the API (no caller can
publish the blend).

## Open for Charles

1. **Candidates that would RAISE a claim, listed not shipped** (spec §2.4): AAPL, DIS, TMUS
   and KKR all measure *higher* on the fully-corrected engine than what is published.
2. **The app has no authentication of any kind.** No login, no middleware — `/positions`,
   `/api/holdings` and `/api/positions` serve the household's holdings and open option
   positions to anyone with the URL. No page *claims* privacy, so it is not a false claim,
   but it is the largest thing seen this session that was out of scope (§8: RLS is its own
   gated session). Recommend gating it next.
3. **A second alerting engine still exists.** `/api/cron/monitor` re-implements the alert
   rules in TypeScript alongside `monitor_positions.py`. The display path no longer uses it.
   Removing a live alerting endpoint is an infra-lane call, so it is flagged, not deleted.
4. **The host `position-monitor` cron was a no-op and is disabled** (reported by the bettybot
   session while decommissioning: it curled `supabase-kong`, a Docker-network name that does
   not resolve from the host namespace, so the `&&` short-circuited — 36 firings, zero
   effect). The monitor runs only in GitHub Actions, which is currently healthy.
