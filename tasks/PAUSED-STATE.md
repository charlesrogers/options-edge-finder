# PAUSED — 2026-08-28. State of the project and how to restart it.

**Why paused:** the money doesn't justify the risk or the attention. On Dad's real book —
$14.07M across 8 tickers — the validated strategy covers only 37% of portfolio value and
projects **~$36K/yr on defensible evidence** (~0.26% yield), because his two largest
positions (TXN $3.1M, AMZN $2.6M — 40% of the book) are both on our skip list, ABBV
($1.19M) was never tested, and KKR is liquidity-capped to 7 contracts of a possible 100.
The measured range around that $36K is roughly −$48K to +$83K depending on start date.
The insurance case (never repeat the $400K MSFT assignment) still stands on its own; the
income case does not carry a project.

**Nothing is broken. Nothing was abandoned mid-flight.** Everything below is either running
deliberately or closed deliberately.

---

## 1. The one thing that makes this pause cheap: the paper engine is LIVE

`.github/workflows/paper-engine.yml` runs every 15 minutes and is the forward-validation
engine commissioned on 2026-08-20 — four pre-registered arms in the graveyard, registered
BEFORE the first tick (statuses `untested`, thresholds immutable):

| Arm | Hypothesis | What its result buys us |
|---|---|---|
| H40 | Full production strategy, forward | Does the actual strategy net positive on real quotes? |
| H41 | Hold to expiry | A−B = what the copilot is worth |
| H42 | No IV gate | The entry gate's true value (Exp 023 says it FAILS on TMUS) |
| H43 | Take-profit only | Defensive exits vs profit-taking exits |

Pre-registration: `experiments/024_paper_engine/PREREGISTRATION.md`.

**This is the highest-value thing in the project and it costs nothing to leave running.**
Every week it runs, the strategy gets a week closer to a verdict that isn't a backtest —
and backtests in this project have been wrong three times (clock bug invalidating Exps
007–014, fabricated IV rank, carried-forward fills flipping TMUS/KKR from +$15K to −$8K).
Come back in six months and the central question may simply be answered.

The daily chain capture and IV sampler are also live and are the free path to upgrading
GOOGL, MSFT and AMZN off probation — they need ~a year of accrued real option data, and
that clock is running whether or not anyone is watching.

## 2. THE CLIFF: GitHub disables scheduled workflows after ~60 days of repo inactivity

This has happened here before — it is fault #4 of the 4.5-month silent outage. If the repo
goes quiet, **every workflow above dies silently around 2026-10-27**, including the paper
engine, and the pause produces nothing. Two ways to avoid it, in preference order:

1. **Move the paper engine + chain capture + IV sampler to the Hetzner crontab** (which does
   not auto-disable), the way chain 1's monitor already runs from `/etc/cron.d/coolify-apps`.
   ~1 hour of work. This is the single highest-value remaining task and the only one worth
   doing *before* walking away. 🔫 prompt in §6.
2. Or: a calendar reminder to push any commit before 2026-10-20 and every ~8 weeks after.
   Free, but relies on a human remembering — which is the failure mode this whole project
   exists to eliminate.

Either way the health check + the two watchdogs (Hetzner cron, Cloudflare worker) will
Discord-alert if the pipeline dies, and the alert-per-minute spam bug is fixed, so a dead
engine produces one legible alarm rather than noise.

## 3. Where the strategy evidence actually stands

- **AAPL** is the only ticker whose numbers survive every correction: $141/yr per contract,
  97% real-fill coverage, 91% win rate. Everything else is weaker.
- **DIS** $267/yr per contract, 86% coverage, range $51..$590.
- **TMUS / KKR**: probation. Positive headline, **negative on real fills only** (−$81 and
  −$88 per contract). Their profit is made of carried-forward prices.
- **GOOGL**: probation, stock-close validation only, zero real option data.
- **TXN / AMZN / MSFT**: skip — tested and failed, or never tested with a live recommendation.
- **ABBV**: never in the research set. High dividend, quarterly ex-div — the exact shape of
  the MSFT failure mode. No rules, no monitoring. Do not sell calls on it without validation.
- 23 hypotheses pre-registered; **every single one that was tested, failed.** The strategy
  that survives is the one we started with: wide strikes, early exits, ex-div discipline —
  every attempted optimization on top of it died in the graveyard.

## 4. Infrastructure state (all live, all verified)

- **Auth**: default-deny, HMAC HttpOnly cookie. `charles/charles`, `bryan/bryan` — **bootstrap
  passwords, change before real positions.** Set in Coolify prod env.
- **RLS**: enabled on the 6 app tables; anon key no longer in the image; 87 other tables untouched.
- **Monitoring**: two chains (Hetzner cron → TS route; GitHub Actions → `position_monitor.py`),
  two watchdogs (Hetzner health cron 30-min; Cloudflare Worker `554a37ca`, different provider),
  Uptime Kuma on the authenticated path. Heartbeats read-back-verified, calendar-aware freshness.
- **Alerting**: Discord only. **Pushover was never purchased** — phone alerts do not exist. Every
  run says so loudly. This is the gap that matters if Dad is ever onboarded.
- **Site**: https://options.imprevista.com — renders the corrected world, verified by
  `scripts/verify_production_claims.py` (run it any time; it fails if the fossil returns).
- **Databento**: $39.80 balance remaining. 2020 crash + melt-up + TMUS 2022 owned, three
  hash-verified copies (laptop / Hetzner `/data/backups/databento/` / Dropbox), restore-tested.

## 5. Known open items (deliberately parked, not forgotten)

- **PR #22** — paper-trade "expired worthless" label fix. Correct and authorized; unmerged
  because merging deploys. https://github.com/charlesrogers/options-edge-finder/pull/22
- **PR #28** — the paper-engine spec doc (the engine itself shipped via #29–#33).
  https://github.com/charlesrogers/options-edge-finder/pull/28
- **Engine parity** (`tasks/engine-parity-spec.md`) — two alert engines can drift. Stopgap in
  force: any threshold change lands in BOTH in the same PR. Low risk while no positions exist.
- **8 tables still carry anon grants** (predictions, iv_snapshots, overrides, …) — integrity
  exposure on recommendation inputs, no positions at risk. Needs its own pass.
- **H21/H22 never ran** — the 2020/2022 stress test on the purchased data. The data is bought,
  secured, and waiting; this is the biggest *unused* asset in the project.
- **Cross-project**: DayScore's and PLY's cron secrets are committed literals in public repos.
  Not this project's to fix — but real, and someone should.

## 6. If we pick this up again — in order

**First hour (do this even if the rest never happens):** move the scheduled jobs off GitHub
Actions so the evidence keeps accruing.

🔫 `Move the paper engine, daily chain capture, and IV sampler off GitHub Actions onto the Hetzner crontab, following the pattern already working in /etc/cron.d/coolify-apps line 39 (/usr/local/bin/options-monitor.sh — env from /etc/options-copilot.env mode 600, heartbeat write with read-back verification, Discord alert on failure, never exit 0 on failure). Read /Users/charlesrogers/Documents/options-tool/tasks/PAUSED-STATE.md §2 and tasks/lessons.md first. You are the ONLY infra session. GitHub auto-disables scheduled workflows after ~60 days of repo inactivity — that killed this project's monitoring for 4.5 months once already, and it would silently kill the forward-validation engine during a pause. Acceptance: demonstrate each job firing from cron, prove its heartbeat/row-count persisted in Supabase, and confirm the GH workflow schedules are disabled so nothing double-runs. Isolated worktree commits; red-baselined checks; report to Charles in chat.`

**First day back:** read the paper engine's accrued results — that is the answer to "does this
strategy actually work," and it will have months of real cycles by then.

🔫 `Read /Users/charlesrogers/Documents/options-tool/tasks/PAUSED-STATE.md, then evaluate the paper engine's accrued evidence against its pre-registered thresholds in experiments/024_paper_engine/PREREGISTRATION.md. Arms H40-H43 in the signal_graveyard. Report per-arm and per-ticker results as RANGES across time windows with sample sizes, honour the immutable thresholds (do not adjust them), compute A-B (the copilot's value) and A-C (the IV gate's value), and mark each hypothesis pass/fail in the graveyard. Do not deploy anything. The deliverable is one honest verdict table Charles can read in two minutes and a 30-year Goldman veteran could audit.`

**First month back:** run H21/H22 on the purchased 2020/2022 stress data (the bought-and-idle
asset), and only then reconsider capacity — validating ABBV and TXN/AMZN alternatives is what
would move the income from ~$36K toward something that justifies attention.

**Before Dad is ever onboarded, regardless:** buy Pushover ($5) — phone alerts do not exist
today; change the bootstrap passwords; run the EMERGENCY fire drill with his phone; and close
`tasks/phase2-onboarding-runbook.md`'s hard gates.

## 7. What this project produced that outlives it

The strategy work was mostly negative results. The process was not, and it transfers:
pre-registration with immutable thresholds; walk-forward or it doesn't ship; a graveyard that
keeps failures; restricting-only auto-ships and raises need sign-off; demonstrations not
assertions (kill the cron and prove the alert arrives); red-baseline every new check because a
check born green is vacuous; generated code over hand-copied duplicates; isolated worktrees for
commits. Every one of those rules exists because something here broke in exactly that way, and
they're all written down in `tasks/lessons.md` — the most valuable file in the repo.
