# Auth + RLS — the Dad gate (session s-0819-0835)

Executing `tasks/security-spec.md`. Infra-exclusive lane.
`tasks/todo.md` is Block A's log and is left alone; this is its own block.

## §0 Verified state, 2026-08-19, recorded BEFORE any change

### RED baseline 1 — no app authentication

Every one of these served real data to an unauthenticated caller:

| Route | Unauth status |
|---|---|
| `/api/holdings` | **200 + live holdings JSON** |
| `/api/positions` | 200 |
| `/api/paper-trades` | 200 |
| `/api/copilot` | 200 |
| `/positions` | 200 (14,481 bytes) |
| `/sell` | 200 |
| `/paper-trades` | 200 |
| `/how-it-works` | 200 |
| `/` | 307 → `/positions` |
| `/api/cron/health` | 401 — already bearer-gated |
| `/api/cron/monitor` | 401 — already bearer-gated |

Plain **HTTP** served the whole app: `http://options.imprevista.com/positions`
→ 200, `http://options.imprevista.com/api/holdings` → 200. No TLS redirect existed.

### RED baseline 2 — RLS off, the public key can write

`relrowsecurity = f` on all six tables; **zero** policies on any of them.

```
anon READ    all six tables            -> 200
anon INSERT  public.trades             -> 201   (row created)
anon DELETE  public.trades             -> 204   (row removed)
anon DELETE  public.monitor_heartbeats -> 204
```

Probe row `ticker=ZZSECTEST` was inserted then deleted; residue query returned `[]`.

**Row counts before any change**, so a later reader can prove nothing was destroyed:
`trades=0`, `portfolio_holdings=7`, `paper_trades=452`,
`option_chain_snapshots=139177`, `position_assessments=0`, `monitor_heartbeats=15`.

**Blast radius:** all six tables are `public`, owner `postgres`, names unique across
schemas. **87 other public tables** on the shared instance are untouched — every
statement in the migration names its table explicitly.

## Findings beyond the spec's hypotheses

1. **No service-role client existed anywhere.** The web app *and* every Python cron
   authenticated with the **anon** key (`role=anon` confirmed on the Coolify values).
   Enabling RLS before provisioning a service-role key would have turned every cron
   red at once. Order of operations is load-bearing and is written into the migration.
2. **`service_role` has `rolbypassrls = t`** here, so "enable RLS, write no policies"
   is deny-all for anon and a no-op for every legitimate consumer. No policy bodies
   are needed, and a policy that need not exist should not exist.
3. **Nothing reads Supabase client-side.** `sell-recommendations.tsx` and
   `trade-history.tsx` import row *types* only. So the anon key could be removed from
   the bundle entirely rather than preserved behind anon-read policies.
4. **`CRON_SECRET` is weak AND public.** It is a guessable literal, it is committed in
   `tasks/todo.md`, and this repo is **public** on GitHub — so the value protecting
   `/api/cron/*` is world-readable. Rotation is not hygiene here, it is a live hole.
   Consumers: Coolify env, GitHub secret, `/etc/options-copilot.env` (Hetzner, 0600),
   and the Uptime Kuma monitor on the authenticated health path.
5. **`nextUrl` does not carry the `Host` header.** Verified locally: a request with
   `Host: options.imprevista.com` still produced a redirect to `http://127.0.0.1:3111/login`.
   Every redirect in `proxy.ts` is therefore built from the `Host` header. A relative
   `Location` is not an option either — Next's proxy layer throws `ERR_INVALID_URL`
   and 500s every protected page (both caught locally, before deploying).

## Plan

- [x] §0 verification + red baselines recorded
- [x] A. Auth: `lib/auth.ts`, `proxy.ts`, `/login`, `/api/auth/{login,logout}`, force HTTPS
- [x] B. Supabase client → service-role, server-only; `NEXT_PUBLIC_*` dropped from image
- [x] C. All 16 workflows → `SUPABASE_SERVICE_ROLE_KEY`
- [x] D. `migrations/004_rls_six_tables.sql`
- [x] E. `next build` green · 341 pytest pass · 16/16 auth checks · 34/34 local gate checks
- [ ] F. Provision secret slots (Coolify / GitHub / Hetzner / Kuma)
- [ ] G. Deploy; GREEN demo on every route in production
- [ ] H. Apply RLS; GREEN demo anon-denied + every cron consumer still working
- [ ] I. Other apps on the shared Supabase unaffected
- [ ] J. Mandatory security-review subagent on the final diff
- [ ] K. Close the hard gate in `phase2-onboarding-runbook.md` + `web-overhaul-spec.md`

## Review

(filled in at the end)
