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
- [x] F. Provision secret slots (Coolify / GitHub / Hetzner / Kuma)
- [x] G. Deploy; GREEN demo on every route in production — 31/31
- [x] H. Apply RLS; GREEN demo anon-denied + every cron consumer still working — 19/19
- [x] I. Other apps on the shared Supabase unaffected
- [x] J. Mandatory security-review subagent on the final diff
- [x] K. Close the hard gate in `phase2-onboarding-runbook.md` + `web-overhaul-spec.md`

## Review — 2026-08-19

### GREEN, demonstrated against production

| Check | Before | After |
|---|---|---|
| `GET /api/holdings` unauthenticated | **200 + holdings JSON** | **401** |
| `/positions` `/sell` `/paper-trades` `/` | 200 | **307 → /login** |
| `POST/PATCH/DELETE` on the write APIs | 200/201/204 | **401** |
| `http://` (no TLS) | **200, served the portfolio** | **308 → https** |
| anon READ, all six tables | 200 | **401** |
| anon `INSERT` into `trades` | **201** | **401** |
| anon `DELETE` from `trades` | **204** | **401** |
| service-role insert→read→delete | n/a | **201 / 1 row / 204 / no residue** |
| old `CRON_SECRET` | worked | **401** |

Suites: 25/25 auth primitives (CI), 41/41 local end-to-end gate, 31/31 production,
19/19 RLS, 341 pytest.

**Exactly 6 of 93 tables changed.** Full before/after diff of `relrowsecurity`
across the instance showed the six flipping `f → t` and **87 unchanged**. Control
tables belonging to other apps returned identical anon status codes before and
after (`users` 200, `matches` 200, `live_odds` 401, `products` 200). PLY, Jebbix
and DayScore all 200 after. *(Sports Dashboard is 503 — pre-existing: it has no
running container and last succeeded 2026-08-18 23:20, ~17h before this session.)*

**Nothing destroyed.** Row counts after: `trades=0`, `portfolio_holdings=7`,
`paper_trades=452`, `option_chain_snapshots=139177`, `position_assessments=0`,
`monitor_heartbeats=23` (was 15 — the 8 new ones are monitor runs). Zero grants
remain to `anon`/`authenticated`/`PUBLIC` on the six.

**Consumers verified by data, not exit codes.** Heartbeat rows written *after* RLS
was enabled (15:48:03 and 15:50:23, `github-actions/primary`, `ok=t`), plus a
`hetzner-cron/chain1` row with `ok=t`. `/api/cron/health` returns 200 with all six
checks `ok`.

### What the security review caught that I had shipped

An adversarial subagent could not break the gate (34 bypass attempts, all denied),
but found real defects around it — all fixed and regression-tested before merge:
an **open redirect** on the login page (`/\evil.com`, TAB and LF all escaped the
string check and resolve to `evil.com` — the highest-value phishing primitive
against this app); **sibling-subdomain CSRF** (SameSite=Lax is site-scoped, and
`request.json()` accepts `text/plain`, a no-preflight simple request); a **rate
limiter that was both bypassable and a lockout weapon** (Traefik appends to
X-Forwarded-For, so the first hop was attacker-controlled); **no session
revocation**; `?secret=` on the cron routes leaking into logs; `/login` matching
`/login*`; and a **deploy check that would have failed this very deploy**.

### Carried risks — recorded, not fixed

1. **Eight more tables keep full anon grants** — `predictions`, `iv_snapshots`,
   `overrides`, `signal_graveyard`, `basket_results`, `deployment_stages`,
   `pass_rate_history`, `vol_surface_snapshots`. These feed the recommendation
   engine, so it is an **integrity** exposure on trade inputs. Out of scope here
   (six named tables only); needs its own scoped pass.
2. **DayScore's and PLY's secrets were published** on the same `tasks/todo.md` line
   as this app's. Options' is rotated; theirs are not, and they are not this repo's
   to rotate.
3. **The Cloudflare worker's `HEALTH_CRON_SECRET` is stale** — a sixth consumer that
   needs an interactive `wrangler` login. Until rotated its Discord alarms are
   FALSE. Value is at `/Users/charlesrogers/.options-cron-secret.new` (mode 600).
4. **The two passwords in Coolify are temporary**, generated and never displayed.
   Charles replaces `AUTH_PASSWORD_CHARLES` and `AUTH_PASSWORD_DAD`; a redeploy is
   not required, the route reads `process.env` per request.
5. **Pushover is still unset**, so the alert path Dad is being onboarded onto still
   cannot deliver. Unchanged by this work, but it is the next hard gate.
