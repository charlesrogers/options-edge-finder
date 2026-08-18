# Scheduled job inventory

Every scheduled job that touches this product, across all four schedulers, with
the one column that matters: **how you would know it died.**

A green cron proves nothing here. All seven GitHub schedules were auto-disabled
for four and a half months while every dashboard stayed green; the server's
position-monitor entry fired 36 times a day for months and accomplished nothing
because a guard could never succeed. Both were invisible because nobody had
written down what "alive" looks like.

**Rule: three consecutive failures of any job below is an incident, not noise.
A job with no failure-detection path does not ship.**

Last verified: **2026-08-18**.

---

## 1. GitHub Actions

Repo: `charlesrogers/options-edge-finder`. Times are UTC — GitHub schedules do
not observe DST, so the ET column shifts by an hour twice a year.

| Workflow | Schedule (UTC) | ET | What it does | How you'd know it died |
|---|---|---|---|---|
| `position-monitor.yml` | `*/15 13-21 * * 1-5` | ~9:00–17:00 | **Safety-critical.** Assesses every open position, sends Pushover, writes a heartbeat | Heartbeat goes stale → `/api/cron/health` returns 503 → Hetzner inner loop + Cloudflare outer loop both page. Plus `if: failure()` → Discord |
| `health-check.yml` | `0 */6 * * *` | — | Calls `/api/cron/health`, fails the job on non-200 or `"status":"fail"` | `if: failure()` → Discord. Independent of the Hetzner checker |
| `daily-chain-capture.yml` | `50 19 * * 1-5` | 15:50 EDT / 14:50 EST | Captures option chains | Health check's Chain Capture test (trading-day freshness) + `if: failure()` → Discord |
| `daily-iv-sampler.yml` | `55 19 * * 1-5` | 15:55 EDT / 14:55 EST | Samples IV across ~350 tickers | `if: failure()` → Discord |
| `paper-trade-logger.yml` | `0 20 * * 1-5` | 16:00 EDT | Logs paper-trade recommendations | Health check's Paper Trade Logger test + `if: failure()` → Discord |
| `score-predictions.yml` | `0 0 * * 2-6` | 20:00 prev day | Scores predictions 20+ days old | `if: failure()` → Discord |
| `score-paper-trades.yml` | `30 0 * * 2-6` | 20:30 prev day | Scores paper trades | `if: failure()` → Discord |
| `monitoring.yml` | `0 2 * * 2-6` | 22:00 prev day | Daily data-quality monitoring | `if: failure()` → Discord |
| `basket-test.yml` | `0 22 * * 0` | Sun 18:00 | Weekly basket test | `if: failure()` → Discord |
| `deploy.yml` | on push to `main` | — | Builds image, pushes GHCR, triggers Coolify, verifies | `if: failure()` → Discord |
| `test.yml` | on push / PR | — | pytest + NYSE calendar drift check | PR check |

Manual-dispatch only, no schedule: `approval-gate`, `backfill-clv`,
`backfill-paper-trades`, `force-score`, `generate-historical`, `investigate`,
`run-gate`. A failure is visible to whoever ran it.

### The standing GitHub risk

**GitHub auto-disables scheduled workflows after ~60 days of repo inactivity.**
That is what silently switched off all seven schedules on 2026-04-12. It is not
fixed — it is structural. The mitigations are (a) the Cloudflare outer loop,
which is not on GitHub and cannot be disabled by it, and (b) this repo being
actively committed to. If work here goes quiet for two months, assume the
schedules are off and check `gh workflow list --all`.

---

## 2. Hetzner — `/etc/cron.d/coolify-apps` (options entries only)

| Schedule (UTC) | Command | What it does | How you'd know it died |
|---|---|---|---|
| `*/30 13-21 * * 1-5` | `/usr/local/bin/options-health-check.sh` | Inner loop: curls `/api/cron/health`, alerts Discord + Pushover on non-200 or timeout | It alerts on its own failure. Silence for a full market day with no Cloudflare alert either means all three layers are down — the case the monthly drill exists to catch |
| `20 1,7 * * *` | same | Off-hours baseline | as above |
| *(disabled)* | position monitor | See below | — |

`/var/log/options-copilot.log` records every run, including
`ALERT UNDELIVERED` lines when a channel is unconfigured.

### The disabled position-monitor line

It read:

```
*/15 13-21 * * 1-5 root curl -sf "http://supabase-kong:8000" >/dev/null 2>&1 \
  && curl -sf -H "Authorization: Bearer ..." ".../api/cron/monitor" >/dev/null 2>&1
```

`supabase-kong` is a Docker-network name. Run from the host namespace that curl
exits **6** (could not resolve host), so the `&&` short-circuited every time. It
had never once called the monitor. An auditor reading the crontab saw 15-minute
monitoring coverage that did not exist, which is worse than seeing nothing.

It is commented out rather than repaired, because the route it calls has no
`PUSHOVER_TOKEN` in Coolify and would deliver nothing. **To enable the real
thing**, fill in `/etc/options-copilot.env` and install
`/usr/local/bin/options-monitor.sh` (see `deploy/hetzner/README.md`).

### Other apps sharing this file

PLY (6 jobs), DayScore (13), sports-dashboard (~15), plus backups and Docker
cleanup. All authenticated calls now go through `/usr/local/bin/app-cron.sh`
with tokens in 0600 env files. They log to `/var/log/app-cron.log` and alert
Discord on failure once `DISCORD_WEBHOOK` is set in the respective env file.

---

## 3. Cloudflare Workers

| Worker | Schedule (UTC) | What it does | How you'd know it died |
|---|---|---|---|
| `yfinance-proxy` | `*/30 * * * *` | Outer loop: polls `/api/cron/health`, pushes to Charles's phone on non-200 or timeout | **Nothing watches this.** Accepted residual risk — all three layers would have to fail silently at once. The monthly drill in `docs/fire-drill.md` is the mitigation |

**Not deployed yet.** Code is in `yfinance-proxy/`; deploying needs a Cloudflare
login and three secrets. See `deploy/hetzner/README.md`.

---

## 4. Uptime Kuma

`status.imprevista.com`. Options Edge is currently Tier 3 (monitor only, no
alert) on the homepage. Per spec A3 it should be **Tier 2 on the authenticated
health path** — monitoring `/` while authenticated routes 401 is a documented
blind spot that has already burned this stack. Not yet changed.

---

## Known scheduling issues

- **Chain capture drifts an hour in winter.** `50 19 * * 1-5` is 15:50 ET during
  EDT but 14:50 ET during EST, so from November to March the "near-close"
  capture happens 70 minutes before the close. Same for the IV sampler at
  `55 19`. Not a reliability fault, but any research comparing summer and winter
  snapshots is comparing different times of day. Changing it changes the data,
  so it is a research decision, not a cleanup.
- **The position monitor's window is deliberately wide.** `13-21` covers both
  EDT and EST market hours, so a few runs each day happen pre-market or
  post-close. Harmless; assessments outside market hours are still correct.

## Resolved

- **Duplicate health checks.** Both GitHub Actions and the Hetzner crontab ran
  the health check at `0 */6` — the same 6-hour blind window, twice, from two
  providers that would both alert for one event. Hetzner now runs every 30 min
  during market hours plus `20 1,7`; the `0 */6` slot belongs to GitHub Actions
  alone.
