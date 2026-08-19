# Security Spec — Auth + RLS: the last gate before a real position exists

**Executor:** Opus 5, fresh session, working dir `/Users/charlesrogers/Documents/options-tool`
**As of 2026-08-19.** §0 verification first; every fact below is a hypothesis.
**Lane:** INFRA-EXCLUSIVE. This session touches Coolify env, Supabase policy, and possibly Traefik. Confirm no other infra session is live (ListAgents + ask Charles) before starting. One infra session at a time — standing rule.
**Mandatory:** a **security-review subagent pass** over the final diff (global CLAUDE.md requires it for auth/RLS/secrets changes). Binding process rules: isolated worktrees for commits; red-baselined acceptance checks; `git show HEAD --stat` before push (tasks/lessons.md 2026-08-18).

## §0 Verify current state

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://options.imprevista.com/api/holdings        # expect 200 = the problem
curl -s -o /dev/null -w '%{http_code}\n' https://options.imprevista.com/positions
ssh root@95.216.205.160 "docker exec supabase-db psql -U postgres -d postgres -c \"select relname, relrowsecurity from pg_class where relname in ('trades','portfolio_holdings','paper_trades','option_chain_snapshots','position_assessments','monitor_heartbeats');\""
grep -rn "CRON_SECRET" web/src/app/api/cron/ | head           # which routes already have bearer auth
```

## §1 The problem

Two independent holes, both blocking Dad onboarding (hard gate in `tasks/phase2-onboarding-runbook.md`):

1. **No app authentication.** `/positions`, `/api/holdings`, and most pages/APIs serve a ~$10M portfolio's holdings and positions to anyone with the URL.
2. **RLS disabled** on `trades`, `portfolio_holdings`, `paper_trades`, `option_chain_snapshots` — and the anon key ships in the browser bundle. Anyone with the public key can **write**: inject a fake trade, delete a real one, blind the monitor. `position_assessments`/`monitor_heartbeats` were created without RLS too (verify).

Blast radius warning: the Supabase instance is shared by every app on the box (~91 tables). Scope ALL policy changes to THIS app's tables by exact name. Never enable RLS wholesale.

## §2 Requirements

### Auth (app layer)
- Every page and API route requires authentication EXCEPT: `/api/cron/health` and `/api/cron/monitor` (bearer `CRON_SECRET`, already implemented — auth must hard-fail if the env var is unset, verify that survived) and any truly public asset.
- This is a 2-user app (Charles + Dad). Choose the simplest mechanism that is actually secure and survives infra quirks — Next.js middleware with a signed HttpOnly session cookie + a login page, or Supabase Auth if it earns its complexity. NO third-party paid service without asking (cost rule). Justify the choice in one paragraph in the PR.
- Credentials provisioning: per-user secrets set via Coolify env (`is_preview=false` — the scope trap), never committed, never printed. Charles enters the actual secret values himself — the executor scaffolds and verifies, and may generate a random secret server-side without displaying it.
- Session length generous (Dad-friendly, e.g. 30 days), logout exists, login failures rate-limited or delayed.

### RLS (data layer)
- Enable RLS on the six tables above (confirmed list from §0). Policy: **service-role-only writes** on all of them; reads either service-role-only (preferred — the app's server routes hold the service key server-side) or anon-read ONLY where a page genuinely reads client-side with the anon key today (§0: find every client-side Supabase call first; migrating them to server routes is in scope and preferred over anon-read policies).
- The GitHub Actions monitor, chain 1's route, the paper-trade logger, chain capture, and the score crons all keep working — enumerate every consumer of these tables (grep repo + docs/crons.md post-correction) BEFORE flipping any policy, then test each authenticated path end-to-end after (the CRON_SECRET-drift outage class).

## §3 Acceptance (demonstrations, red-baselined)

1. RED first: unauthenticated `curl /api/holdings` returns 200 with data today (record it). GREEN after: 401/redirect on every protected page/API — enumerate and test ALL routes, not a sample.
2. Anon-key INSERT into `trades` succeeds today (record it — against a test row, then delete it). After: fails with RLS error. Service-role write still succeeds.
3. Every cron/monitor path demonstrated working post-change: chain 1 log `OK 200` on a real cron tick, GH monitor run green with heartbeat read-back, health endpoint 200, capture job persists rows (verify counts in Supabase, not exit codes).
4. Other apps on the shared Supabase unaffected: spot-check PLY/dayscore endpoints healthy after (their tables untouched — verify by listing exactly which tables changed).
5. Login works on Charles's phone and desktop; a wrong password fails; the session survives a container redeploy (cookie signing key from env, not ephemeral).
6. Security-review subagent verdict recorded in the proof-of-work. Zero secrets in the transcript, diff, or logs.
7. Update `tasks/phase2-onboarding-runbook.md` hard-gate status and `tasks/web-overhaul-spec.md` STATUS item 2 to CLOSED with date + PR.

## §4 Out of scope
Pushover (Charles's task). Engine parity (tasks/engine-parity-spec.md, runs AFTER this session — same lane). Any loosening of monitor behavior. Multi-tenant auth design — this is a 2-user tool, resist the urge.
