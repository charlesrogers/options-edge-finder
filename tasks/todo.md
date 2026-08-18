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

- [ ] **P0 — FACT-11.** One field contract for `public.trades`, both alert paths corrected,
      `db.add_trade` corrected, pytest pinning the live column set so this cannot re-rot.
- [ ] **P1 — FACT-1.** Repoint server cron at the Python authority (A2), not the TS route.
      Deploy `/opt/options-monitor` on Hetzner. Kill the unsatisfiable `supabase-kong` guard.
- [ ] **P2 — Layer 0 heartbeat.** `monitor_heartbeats` + `position_assessments` tables;
      monitor writes both with read-back verification.
- [ ] **P3 — FACT-3 + FACT-12.** Health returns non-200 on fail; add heartbeat check;
      set the missing Coolify notification env vars.
- [ ] **P4 — FACT-5 (A6).** Market-calendar-aware freshness from a real NYSE calendar.
- [ ] **P5 — Layer 2.** Cloudflare Worker cron trigger → health → Pushover.
- [ ] **P6 — FACT-4.** Secrets to a 0600 env file; rotate CRON_SECRET across every consumer.
- [ ] **P7 — notification ownership.** Python-on-Hetzner is primary; GH Actions fallback
      alerts only when the primary heartbeat is stale. No duplicate buzzes.
- [ ] **P8 — docs/crons.md**, duplicate health cron resolved, Uptime Kuma Tier 2 monitor.
- [ ] **P9 — demonstrations.** Kill the cron → alert ≤45 min. Force a write failure → loud.
      Weekend/holiday → zero alerts.

## Review
(filled at end)
