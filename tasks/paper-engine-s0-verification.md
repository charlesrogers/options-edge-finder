# §0 verification log — paper-trading engine

Run 2026-08-20 against `main` @ `b3f55bd`, worktree `s-0820-2155`.
Every claim the spec asked to re-verify, with what was actually found.

| § | Claim in spec | Found | Verdict |
|---|---|---|---|
| 0.1 | No sibling session building this | `s-0820-1206` holds only the spec commit (`e5e3b9d`), no engine code | ✅ clear |
| 0.2 | `signal_graveyard` in Supabase, H40+ free | **Could not query** — ssh to the Hetzner box is blocked by this session's sandbox, and no Supabase creds exist locally (`.env` has only EODHD/DATABENTO). H40–H43 are free *in the repo*: registration scripts cover H01–H20, H25–H26, H30–H39; `005_index_straddles` references H44–H46 in prose | ⚠️ deferred — see "Blocked" below |
| 0.3 | `assess_position(as_of=…)`, one wall-clock read | `position_monitor.py:153` has `as_of`; exactly one `datetime.now()` (line 174, the live default); **zero** in `cc_sim.py` | ✅ holds |
| 0.4 | Monitor + capture crons green | position-monitor: 4/4 green through 2026-08-20T21:45Z. daily-chain-capture: green 08-20, one failure 08-19. All 19 workflows `active` | ✅ holds |
| 0.5 | Live quote shape | Probed via `scripts/probe_quotes.py` — see below | ✅ done |
| 0.6 | DIS IV≥75, KKR cap 7 | `get_iv_threshold('DIS')=75`; `get_max_contracts('KKR',10000)=(7, 'Liquidity cap (Exp 021)…')`; `DEFAULT_IV_THRESHOLD=50` | ✅ holds |
| 0.7 | Old tracker is 444 BSM rows | Not re-run (needs Supabase). `results/013_paper_trade_audit.md` stands as the record; the new tables are unjoinable by construction regardless | ⚠️ deferred |
| 0.8 | Heartbeat/assessment schema | `migrations/003` read: `monitor_heartbeats(source, role, engine, engine_version, positions_checked, positions_unassessed, alerts_fired, alerts_undelivered, ok, detail jsonb)` | ✅ holds |
| 0.9 | Cron inventory | `docs/crons.md` confirms `position-monitor.yml` is the only `*/15`; `daily-chain-capture.yml` is `50 19 * * 1-5` | ✅ holds — confirms the spec's own correction |

## Live quote shape (§0.5) — `scripts/probe_quotes.py`, 2026-08-20 ~22:05 UTC

| Ticker | Expiry / DTE | Spot | Strike (15% OTM) | Bid | Ask | Spread | Spread as % of bid | Vol / OI |
|---|---|---:|---:|---:|---:|---:|---:|---|
| KKR | 2026-09-18 / 28 | 107.02 | 125.0 | **0.15** | **0.55** | 0.40 | **267%** | 40 / 3487 |
| AAPL | 2026-09-18 / 28 | 311.30 | 360.0 | 0.28 | 0.31 | 0.03 | 10.7% | 565 / 8192 |

Both pass the §5.2 entry floor (bid ≥ $0.05, uncrossed). **KKR's round trip at
bid/ask costs 2.7× the credit it collects** — sell at 0.15, buy back at 0.55.
That is not a rounding detail; it is the single most consequential number this
probe produced, and it is why the engine prices at bid/ask and never at mid.

**Proxy failure is indistinguishable from an empty chain.** `yf_proxy._get`
catches `RequestException` and returns `{}`. Confirmed by pointing `PROXY_URL`
at an unresolvable host: returns `{}`, type `dict`. The engine must probe
explicitly and never infer "no data" from an empty dict (§5.4).

## Corrections to the spec found while verifying

1. **`signal_graveyard` has no `pass_thresholds` column.** §6.4 says the
   `PREREGISTRATION.md` hash is "stored in each H40–H43 row's `pass_thresholds`
   JSON". `migrations/001` defines only
   `(signal_id, name, tier, hypothesis, pre_registered_date, tested_date,
   status, layer_reached, best_sharpe, best_clv, n_trades, failure_reason,
   notes)`, and `signal_registry.pre_register()` folds `pass_thresholds` into
   the free-text `hypothesis` string. Migration 005 therefore adds
   `pass_thresholds jsonb` to `signal_graveyard` so the hash has a typed,
   machine-readable home instead of being regex-scraped out of prose.
2. **CLOSE_SOON is 5 *calendar* days, not 5 trading days.** §3 says "close after
   `close_soon_days=5` trading days". `cc_sim`'s docstring and code are explicit
   the other way: "CLOSE_SOON -> close within `close_soon_days` calendar days.
   Default 5, taken from the alert's own wording ('Close this week')", and
   `run_cohort` computes `(date - close_soon_armed_on).days`. Single-authority
   wins: the engine implements calendar days.
3. **The 14-clause ladder has no machine-readable clause id.** `PositionAlert`
   carries `level` and a formatted `reason` string; the clause-fire table of §7
   cannot be built by matching prose. Fixed additively — a `clause` field with a
   default is added to `PositionAlert` and set at each of the 14 return sites.
   No behaviour changes, and the production monitor gains the same audit.

## Blocked

**ssh to `root@95.216.205.160` is denied by this session's sandbox classifier**,
and there are no Supabase credentials on this machine. Two spec steps depend on
it and are deferred, not skipped:

- §0.2 / §0.7 read-back of `signal_graveyard` and the old `paper_trades` tracker.
- §6.5 step 1: applying `migrations/005_paper_engine.sql`.

Everything else is buildable without it. The registration script does its own
read-before-write refusal, so the H40–H43 collision check happens at
registration time on the machine that has the credentials, which is where it
belongs.
