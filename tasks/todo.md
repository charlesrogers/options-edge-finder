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
