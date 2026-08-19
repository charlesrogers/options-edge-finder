# Engine Parity Spec — one verdict, two engines, zero drift

**Executor:** Opus 5, fresh session. **Lane: INFRA-EXCLUSIVE** — runs only after tasks/security-spec.md closes (one infra session at a time). As of 2026-08-19; §0 verify-first applies.

## Problem
Chain 1 (Hetzner cron, every 15 min market hours — live, `/etc/cron.d/coolify-apps:39` → `/usr/local/bin/options-monitor.sh` → `/api/cron/monitor`) alerts off the TS engine (`copilot.ts` via the route). Chain 2 (GitHub Actions) alerts off `position_monitor.py` (51 tests, the empirical table — the designated single authority). Two engines that can drift = the phone and the screen (or the two chains) disagreeing on a $400K-class alert. Stopgap in force: any threshold change lands in both engines in the same PR.

## Decision (made 2026-08-19, Charles-approved): keep the route, bind it
1. The route persists its assessments through the SAME `position_assessments` store the Python monitor writes (verify Block A's schema; add `engine` column if absent) — so divergence is *recorded*, not invisible.
2. **Golden-case parity suite**: one fixture set of position states (every alert level, every boundary: 20-min staleness, 3-day ex-div, each moneyness/DTE bucket edge, NaN/missing-data cases) evaluated by BOTH engines in CI; any verdict mismatch fails the build. The fixtures live in one shared JSON so neither engine owns the test.
3. A daily reconciliation check (fold into the existing health check): if the two engines' stored assessments for the same position+timestamp window ever disagree, Discord alert.
4. Retire the stopgap rule only when 1–3 are demonstrated (including one deliberately-injected drift caught RED by both the CI suite and the reconciliation alert).

## Acceptance
Parity suite red-demonstrated (inject a threshold skew) then green; reconciliation alert demonstrated with a synthetic mismatch; docs/crons.md + web-overhaul STATUS item 3 updated to CLOSED.
