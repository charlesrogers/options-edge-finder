# Lessons Learned

Rules derived from mistakes in this project. Claude MUST review this file at the start of every session and follow these rules.

---

### 2026-08-16 — A research import at module scope took down the safety-critical monitor

**What went wrong:** shadow-mode instrumentation for H19 needed a BSM delta, so I added `import bsm` at module scope in `monitor_positions.py`. `bsm` imports `scipy`. `.github/workflows/position-monitor.yml` installs `requests numpy pandas supabase yfinance` — no scipy, and nothing pulls it in transitively. The import fails before `main()` runs, so the careful per-trade `try/except` inside the loop never engages. Every scheduled run — `*/15 13-21 * * 1-5`, ~26 a day — would have exited non-zero before evaluating a single position: no EMERGENCY, no CLOSE_NOW, no daily summary, for the user's father holding ~10,000 shares per ticker. `requirements.txt` has scipy, so it imported fine locally and in the test workflow; only the monitor's own install list was short. Caught by an independent correctness review, not by me, and not by CI.

**Why it's wrong:** the per-trade `try/except` created a false sense that the monitor was resilient. Nothing inside a function protects against a module-scope import, and every workflow in this repo installs its own hand-listed subset of dependencies, so "it imports on my machine" and "it imports in the test job" prove nothing about the job that matters. Research instrumentation was allowed to sit on the critical path of an alerting system with no isolation at all.

**Rule:** Never add a module-scope import to a safety-critical job for a non-critical feature. Import it lazily inside a `try/except` that degrades to the feature being off, put every line of the optional feature's computation inside its own `try/except`, and keep the critical path reachable without it. Separately: when adding ANY import to a file run by a GitHub Actions workflow, open that workflow and check its `pip install` line — the workflows do not read `requirements.txt`. Add an `python -c "import <module>"` smoke-test step before the real step so a missing dependency fails loudly at the right place.

**Category:** mistake (CRITICAL — a live regression on the safety-critical alert path)

---

### 2026-08-16 — `is None` is not a missing-data check when NaN can reach the function

**What went wrong:** `rational_exercise_emergency()` is the refined EMERGENCY rule, and its documented contract is that missing data must make it FIRE. Its guards tested `is None`. But the live caller derives the dividend as `spot * dividendYield` from a Yahoo proxy field, and `float('nan')` is not `None` while `bool(nan)` is `True` — so a NaN yield sails through every truthiness guard, becomes a NaN dividend, then wins every comparison in the rule (`extrinsic >= nan` is `False`), and the function falls through to SILENCE. Zero and negative prices did the same. The one thing the rule may never do is let missing data buy silence on a $400K alert, and that is exactly what it did.

**Why it's wrong:** NaN is the value that survives every guard written for `None`. It compares False against everything, so in any rule shaped as "fire unless a comparison proves it is safe," a NaN always proves it is safe. `max(0.0, nan)` returning `0.0` compounds it by silently degrading a NaN price into a plausible zero.

**Rule:** In any fail-safe or safety-critical guard, validate the value, not just its absence: reject `None`, NaN, `inf`, negative, non-numeric, and (where zero is meaningless) zero — with one helper used by every guard. Write the tests as `@pytest.mark.parametrize` over `[None, nan, inf, -1, 0, 'x']` rather than testing `None` alone. Assume any float derived from an external feed can be NaN.

**Category:** anti-pattern

---

### 2026-08-16 — Six experiments ran with DTE silently pinned to 0

**What went wrong:** `assess_position()` computed `dte = max(0, expiry - datetime.now())`. Every backtest passed a *historical* expiry, so DTE evaluated to 0 on every observation in Experiments 007, 008, 009, 010, 012 and 013. That made every DTE-conditional alert rule unreachable (CLOSE_SOON at 7+ DTE, both WATCH rules) and left one rule permanently armed (CLOSE_NOW at "DTE < 3 and within 3%"). The copilot those experiments measured was a pure distance rule with the entire DTE dimension deleted. The headline "13% premium retention" in `results/009_crush_it.md` — the number that motivated a whole week of research into fixing it — was an artefact. Corrected, baseline retention is 52.5% (AAPL) and 86.5% (DIS). The same experiments also passed `ex_div_date=None`, so the EMERGENCY rule and both ex-dividend rules never fired in any backtest either.

**Why it's wrong:** a function that reads the wall clock is not a pure function of its arguments, and a backtest is by definition evaluating a past state. `datetime.now()` inside scoring or alerting logic is a time bomb that only detonates in historical evaluation — where it produces plausible-looking numbers rather than an error. Nothing crashed. Nothing was flagged. Six experiments and a production parameter table were built on it.

**Rule:** Any function used by both the live app and a backtest MUST take an explicit evaluation timestamp (`as_of`), defaulting to `datetime.now()` only for the live path. Backtests must always pass it. Before trusting any backtest of alerting/scoring logic, assert that a DTE-conditional or date-conditional branch is actually reachable in the simulated data — e.g. log the distribution of DTE values seen, and treat a degenerate distribution (all zeros, all identical) as a bug. The same check applies to any input a backtest passes as `None` "for now": log how often each alert clause fires, and treat a clause that never fires across thousands of observations as unwired rather than unlucky.

**Category:** mistake (CRITICAL — invalidated six experiments and a production config)

---

### 2026-08-16 — A "premium retention" problem that was really a take-profit rule

**What went wrong:** the Week 2 spec framed the problem as "the copilot triggers CLOSE_SOON/CLOSE_NOW on *distance to strike*, and 74% of gross premium goes to buyback costs," and proposed replacing the distance triggers with assignment-probability triggers. Once the DTE bug was fixed and the exits were tallied by which clause actually fired, 39–95% of closes came from the "75% of premium captured" take-profit clause — which has nothing to do with distance or assignment probability. Replacing the distance triggers deleted the take-profit rule as a side effect, which is exactly why the treatment bled money.

**Why it's wrong:** the hypothesis named a mechanism ("distance triggers cause the buybacks") that nobody had measured. Attributing an aggregate outcome to a mechanism without counting which code path produced it means the fix can address a minority of the behaviour while silently removing the majority.

**Rule:** before proposing to replace a rule, instrument it: count how many times each individual clause fires and what fraction of the outcome each one owns. If the hypothesis says "X causes Y," produce the count showing X causes Y *first*. A one-line tally is cheaper than an experiment grid and would have reframed this one before it was written.

**Category:** anti-pattern

---

### 2026-08-16 — The pre-registration threshold was calibrated against a broken baseline

**What went wrong:** H17's pass bar was "retention ≥ 20%," chosen because the (buggy) baseline was 13%. After the DTE fix the baseline was 52.5–86.5% on three of four tickers, so the bar was cleared by the control arm itself and carried no information. The threshold was correctly left immutable, but only the secondary "net P&L ≥ baseline" clause did any work.

**Why it's wrong:** an absolute threshold encodes an assumption about the current state. When that state turns out to be mismeasured, the threshold silently becomes either trivial or impossible, and the experiment stops testing what it was written to test.

**Rule:** state pass criteria **relative to a baseline computed in the same run** ("retention ≥ baseline + 7pp") rather than as an absolute constant, whenever the baseline comes from a previous experiment rather than from first principles. If an absolute bar is used anyway, re-measure the baseline before freezing the pre-registration, and record the measured baseline *in* the pre-registration.

**Category:** anti-pattern

---

### 2026-08-16 — A hard constraint that was satisfied by construction, and reported as a result

**What went wrong:** Exp 015's pre-registered hard constraint was "0 assignments." Every arm reported 0, and the first write-up presented that as evidence the policies were safe. It was a tautology. The simulator's early-exercise branch requires ITM *and* ex-div ≤ 1 day, and every policy tested — baseline and treatment alike — returns CLOSE_NOW for exactly that state, because H17 deliberately left the EMERGENCY rule in place. No position could ever reach the branch. Across 8,100 trades in 10 arms it fired zero times. The metric that was supposed to be the safety gate never once had the chance to bind.

**Why it's wrong:** a constraint that cannot be violated measures nothing, and reporting it next to real results implies it discriminated between arms when it did not. It also hides that a *future* experiment which loosens exits far enough for positions to survive to an ex-dividend would be the first one where the constraint does any work — and it would be untested.

**Rule:** For every pre-registered hard constraint, prove it is reachable before quoting it as satisfied: count how many times the violating branch fires across the whole run, and if the count is zero, state explicitly that the constraint was non-binding rather than met. A test that only demonstrates the constraint holds in a synthetic scenario the real policies never produce is not coverage.

**Category:** anti-pattern

---

### 2026-08-16 — Quoted a number in a results doc that no committed code could regenerate

**What went wrong:** `results/017_natenberg_emergency.md` presented a counterfactual sweep over delta threshold and safety margin — five rows of suppression and miss counts — as measured, supporting the claim "zero misses is not reachable." The sweep had been run once in a scratchpad script that was never committed. Worse, that script did not replicate the rule's fail-safe, so its registered `(0.95, 1.5)` row disagreed with the experiment's own headline numbers (115/46 vs 106/38) and nobody noticed, because there was nothing to compare it against.

**Why it's wrong:** a results document is a claim about what the code produces. A number in it that no committed script regenerates is unfalsifiable, and an ad-hoc reimplementation of the rule under test will drift from the real one in exactly the ways that matter.

**Rule:** Every number in a results file must come from the committed run script and be persisted to `results.json`. Never compute a supporting figure in a scratchpad and paste it in. Where a diagnostic re-implements logic that the experiment also computes, assert the two agree on the shared cell and print the check — a self-consistency assertion is cheap and catches the drift immediately.

**Category:** anti-pattern

---

### 2026-08-16 — signal_graveyard has never existed in Supabase

**What went wrong:** `db.register_hypothesis()` writes to a `signal_graveyard` table on Supabase, and `db.py` falls back to a local, gitignored SQLite file when the client is unavailable — silently, with no warning and the same return value. The table does not exist in the Supabase schema and never has. Every pre-registration since H01 (2026-03-22) landed in someone's laptop-local `local.db`; only H01–H04 survive anywhere, all still `untested`, despite `register_hypotheses.py` defining 39 hypotheses. The pre-registration discipline the whole research process rests on had no durable store.

**Why it's wrong:** same shape as the 4.5-month chain-capture outage — a write path that cannot report where it wrote. A fallback that is indistinguishable from success turns "we pre-registered this" into an unverifiable claim.

**Rule:** any storage helper with a fallback MUST report which backend it actually used, on every call, in its return value or its log line. Never let "wrote to the durable store" and "wrote to a local temp file" produce identical output. Before relying on a persistence layer for a process guarantee (pre-registration, audit trail, alerting), verify the target table exists by reading it back.

**Category:** anti-pattern

---

### 2026-08-15 — Write helpers returned attempted count, hiding a 4-month data outage

**What went wrong:** `db.record_chain_snapshot()` wrapped every Supabase upsert in `except Exception: pass` and then `return len(rows)` — the attempted count, not the written count. The Supabase key went stale after 2026-03-30; every write 401'd; the job kept printing "Total: 2675 option chain rows captured" and exiting 0. Daily Option Chain Capture showed a green checkmark for ~2.5 months while writing literally zero rows. `web/src/app/api/paper-trades/route.ts` had the same shape — it discarded `error` from the destructure and served an all-zeros scorecard with HTTP 200.

**Why it's wrong:** A success metric derived from input size rather than confirmed output can never report failure. Combined with a swallowed exception, the job is structurally incapable of going red, so every downstream health signal (CI status, dashboards, the app itself) lies in the same direction.

**Rule:** A write helper must return the count of rows the database confirmed, never `len(attempted)`, and must never `except: pass` on a write. Any batch job whose persisted count is 0 must `sys.exit(1)`. Any API route that destructures a client result must check `error` before using `data`.

**Category:** anti-pattern

---

### 2026-08-15 — Credentials fixed on the preview scope while production kept the stale value

**What went wrong:** The Coolify app had two full sets of `NEXT_PUBLIC_SUPABASE_*` vars. The correct key + URL were set with `is_preview=true`; the production scope (`is_preview=false`) still held the stale key and an unreachable `http://supabase-kong:8000`. Production had never used the fix, so `/api/positions` and `/api/holdings` returned `Unauthorized` indefinitely.

**Why it's wrong:** Coolify silently accepts duplicate keys across scopes and shows both in the same list. Setting an env var without asserting its scope looks identical to fixing the problem, and the app keeps serving the old value.

**Rule:** After changing any Coolify env var, re-read `/applications/<uuid>/envs` and confirm the value landed on the scope the running container uses (`is_preview=false` for production). Never assume a write applied to prod; verify by hitting the deployed endpoint. Also check for duplicate keys across scopes and delete the stale one.

**Category:** mistake

---

### 2026-08-15 — Answered "what data source did we use" without searching the repo

**What went wrong:** Asked which data source the project originally used for options market data, I grepped only the obvious filenames (`yf_proxy.py`, `fetch_eodhd.py`) and answered "Yahoo via yfinance, plus EODHD for history." Both halves were misleading: Databento (the paid OPRA OHLCV source, ~$122, 3.6M rows, still the basis of every backtest) went unmentioned, and EODHD never returned a single row — `data/eodhd/api_calls.log` is 404s for every ticker.

**Why it's wrong:** File names are not an inventory of dependencies. A source can be central to the project (Databento) while living only in gitignored data dirs and `import` lines, and a source can have a whole fetcher module (EODHD) while being dead on arrival. Answering from filenames produces confident, wrong history.

**Rule:** Before answering any "what did we use / how did we get X" question, grep the full repo for the candidate space (provider names, `import` lines, API hosts) AND check `git log -S` for when it entered, AND verify the data actually exists on disk (row counts, file sizes, API logs). Never answer a factual-history question from the first file that looks relevant.

**Category:** mistake

---

### 2026-03-23 — Experiment 001 used fake option prices and declared results

**What went wrong:** Experiment 001 (exit strategy optimization) used a hand-rolled spread value approximation instead of real option pricing. It produced 100% win rate and Sortino of 5.5 — both obviously too good to be true. The results were published and the strategy was built into the app before being invalidated by Experiment 002 with real Databento data.

**Why it's wrong:** Building infrastructure (UI, trade cards, sizing) around unvalidated backtest results wastes effort and creates false confidence. Experiment 001 should have been flagged as "directional only, not deployable" instead of used as the basis for the entire app strategy.

**Rule:** NEVER build product features or trade recommendations based on backtest results that use synthetic/estimated option prices. Only backtests using real market data (Databento, broker feeds, etc.) can inform strategy decisions. Label all BSM/proxy backtests as "directional estimate only — not validated."

**Category:** anti-pattern

---

### 2026-03-23 — Experiment 002 backtest had silent repricing failures

**What went wrong:** The `reprice_spread()` function returned `None` when option contracts weren't traded on a given day. The calling code used `continue` to skip those days, which meant exit triggers (take-profit, DTE floor) never fired on illiquid contracts. 20 of 90 trades silently fell through to expiry, producing catastrophic losses. The $2,500 loss was partly a code bug, not purely a strategy failure.

**Why it's wrong:** Silent `None` handling in financial code turns bugs into fake losses (or fake profits). Every `None` return in a pricing function is an alarm that should be logged and handled explicitly.

**Rule:** NEVER silently skip a repricing failure with `continue`. Every `None` from a pricing/repricing function must be logged, counted, and reported. At minimum: interpolate from last known price. At maximum: close the trade at last known value when repricing fails for N consecutive days. Always report "X of Y repricing days had missing data" in backtest results.

**Category:** mistake

---

### 2026-03-23 — Backtest had only 90 trades (way too few for significance)

**What went wrong:** The backtest skipped `holding_period` (20) calendar days between trades to avoid overlap, producing only ~12-14 trades per ticker per year. With 5 tickers × 1 year = ~90 trades total. The variance betting framework requires 200+ trades minimum. 90 trades is not statistically significant for any of the pass/fail thresholds.

**Why it's wrong:** Small sample sizes produce noisy results. KKR's 28 trades drove 82% of total losses — one ticker's bad luck dominated the entire experiment. With 200+ trades, single-ticker noise would be diluted.

**Rule:** Before running any backtest, compute expected trade count. If < 200, either (a) extend the date range, (b) add more tickers, (c) allow overlapping positions, or (d) use a shorter holding period. Flag any backtest with < 100 trades as "insufficient sample — results unreliable."

**Category:** anti-pattern

---

### 2026-03-23 — Built covered call logic, then put spread logic, then threw both away

**What went wrong:** Built covered call sizing and display (commit bf69c97), then completely rewrote to put spreads only (commit 36eae5e), then discovered put spreads don't work (Experiment 002). Three full strategy implementations, two thrown away. Total wasted code: ~500 lines.

**Why it's wrong:** Strategy should be VALIDATED before building product features. The correct order is: (1) validate strategy with real data, (2) build product features for the winning strategy. We did it backwards — building the app around an unvalidated strategy.

**Rule:** ALWAYS validate the strategy with real data BEFORE building any UI, trade cards, sizing logic, or user-facing features. The backtest is step 1, not step 5. "Build it and they will come" doesn't apply to financial strategies — build it AFTER you prove it works.

**Category:** anti-pattern

---

### 2026-03-23 — EODHD API token committed in shell history, free tier doesn't include options

**What went wrong:** Tested EODHD API with the token in a curl command (visible in shell history). Also didn't verify the free tier included options data before building the fetcher — it doesn't. Wasted time building `fetch_eodhd.py` for an API that returned 404 on every ticker.

**Why it's wrong:** API tokens in shell commands are logged. And building an integration without first verifying the endpoint works is pure waste.

**Rule:** Before building ANY data fetcher: (1) verify the endpoint works with a manual curl, (2) verify the pricing tier includes the data you need, (3) test with one ticker before writing batch logic. NEVER put API tokens in git-tracked files or command-line arguments — always use environment variables.

**Category:** mistake

---

### 2026-03-23 — Databento definition cost estimates were 2x off

**What went wrong:** `get_cost()` estimated definitions at $5.57 but actual cost was $11.17. This wasn't discovered until checking the balance manually. The OHLCV estimates were accurate ($4.07 est vs $4.08 actual), but the difference wasn't known until after the definitions were already pulled.

**Why it's wrong:** With a hard budget cap ($100-125), inaccurate cost estimates risk overspending. We got lucky that OHLCV was accurate — if it had also been 2x, we would have blown the budget.

**Rule:** When using pay-per-pull APIs with budget caps: ALWAYS pull the cheapest item first, check actual charge, compute the correction factor, then plan remaining pulls. Never trust `get_cost()` estimates for the first pull — calibrate against reality first.

**Category:** near-miss

---

### 2026-03-23 — DTE floor race condition with holding period

**What went wrong:** The backtest loop runs `for day_offset in range(1, holding_period + 1)`. DTE floor triggers at `spread_dte - day_offset <= dte_floor`. When `spread_dte = 25` and `dte_floor = 5`, the trigger fires at `day_offset = 20`. But `holding_period = 20` means the loop also ends at 20. The DTE floor check and end-of-loop happen on the same iteration, and the code path falls through to expiry instead of DTE floor exit.

**Why it's wrong:** The DTE floor safety net was supposed to prevent trades going to expiry. A subtle off-by-one means it doesn't work when option DTE ≈ holding period + DTE floor. This is exactly the common case.

**Rule:** In backtesting loops with multiple exit conditions, check ALL exit conditions BEFORE the expiry/end-of-loop handler. Use `elif` chains or priority ordering to ensure safety exits (DTE floor, stop loss) take precedence over expiry. Test edge cases where DTE ≈ holding_period.

**Category:** mistake

---

### 2026-03-23 — Kept pivoting strategy without validating any of them

**What went wrong:** Session went: covered calls → cash-secured puts → put spreads → "put spreads fail" → AAPL CSP → ... Each pivot generated new code, new UI, new plans. But none were validated before building. The first real validation (Experiment 002) killed the strategy that 3 hours of development was built around.

**Why it's wrong:** Strategy exploration without validation is just guessing with extra steps. Each pivot consumed significant development time on features that were ultimately useless.

**Rule:** When exploring strategies: run a QUICK validation (even crude BSM) BEFORE committing to any strategy. Spend 30 minutes on validation, not 3 hours on implementation. The question "does this make money?" must be answered before "how do we show it in the UI?"

**Category:** anti-pattern

---

### 2026-03-23 — (POSITIVE) Pre-registration process caught the failure honestly

**What went well:** Experiment 002 was pre-registered with immutable pass/fail thresholds BEFORE seeing results. When it failed, the failure was documented honestly without moving goalposts. The results blog post said "FAILED" and "DO NOT proceed to real money." This is exactly how the system should work.

**Why it's good:** Without pre-registration, there would have been temptation to adjust thresholds, exclude KKR post-hoc, or rationalize the negative result. The pre-registration forced honesty.

**Rule:** REINFORCE: Always pre-register experiments with pass/fail thresholds before running. Never adjust thresholds after seeing results. Document failures as prominently as successes.

**Category:** positive-pattern

---

### 2026-03-23 — (POSITIVE) Databento data acquisition was methodical

**What went well:** Pulled cheapest ticker first (KKR $4.08), verified cost matched estimate, then proceeded to more expensive tickers with confidence. Checked balance after every pull. Stayed within budget despite spending ~$122 of $125.

**Rule:** REINFORCE: When using pay-per-pull APIs, always calibrate on the cheapest item first, verify balance between pulls, and maintain a buffer.

**Category:** positive-pattern

---

### 2026-03-23 — Trade skip interval created survivorship bias (40 trades from 336 GREEN days)

**What went wrong:** The backtest used `trade_skip_days=5` (then increased from original 20), which skipped 4 out of every 5 GREEN days. AAPL had 336 GREEN days in 1 year but only 40 trades entered the backtest. The 40 trades that were selected happened to include mostly winners — when rerun with daily entries (172 trades), the Sharpe dropped from 4.6 to 0.19 and the bootstrap showed 99.7% probability of ruin.

**Why it's wrong:** Subsampling trades creates survivorship bias. By only taking every Nth trade, you get a non-representative sample. The skip was added to "avoid overlapping trades" but each put spread is an independent position (different strike, different expiry). There was no reason to skip. The 40-trade Sharpe of 4.6 was an artifact of cherry-picked timing, not a real edge.

**Rule:** In options backtests, NEVER use arbitrary trade skip intervals unless there is a genuine constraint (e.g., max portfolio positions). Each potential trade should be evaluated independently. If the strategy involves overlapping positions, model them as a PORTFOLIO of concurrent trades, not as a single sequential trade stream. Always compare "all eligible trades" to "subsampled trades" and flag if results differ by >50%.

**Category:** mistake

---

### 2026-03-23 — Celebrated a Sharpe of 4.6 without questioning it

**What went wrong:** Experiment 003 initially reported AAPL put spreads at Sharpe 4.618. A Sharpe above 3.0 is extremely rare in any real strategy. Instead of questioning whether this was realistic, it was reported as a success and plans were made to paper trade based on it. When rerun with daily entries, the Sharpe collapsed to 0.19.

**Why it's wrong:** A Sharpe > 3 in a simple options strategy should be an IMMEDIATE red flag, not a celebration. At 40 trades, the standard error of the Sharpe estimate is ~0.5, meaning a "true" Sharpe of 0.5 could randomly appear as 4.6 in a small sample. Extraordinary claims require extraordinary evidence — and 40 trades is not extraordinary evidence.

**Rule:** Treat any reported Sharpe > 2.0 as suspicious until verified on 200+ trades. When a backtest produces Sharpe > 3.0, the FIRST response should be "what's wrong with the methodology?" not "we found an edge." Cross-check by running with different trade entry timing (daily vs weekly vs random) — if Sharpe changes by >50%, the result is driven by timing luck, not edge.

**Category:** anti-pattern

---

### 2026-03-23 — Did not model concurrent portfolio positions

**What went wrong:** The backtest models one trade at a time in a sequential stream. In reality, with daily entries on 20-30 DTE options, Dad would have 15-20 open positions simultaneously. The sequential model misses: (a) portfolio-level drawdown from correlated positions (all AAPL puts move together in a crash), (b) margin/capital constraints (can't open position #16 if margin is maxed), (c) the compounding effect of overlapping wins and losses.

**Why it's wrong:** Individual trade P&L tells you nothing about portfolio behavior. 172 independent +$5 trades look great. But if 15 of them are open simultaneously and AAPL drops 10%, ALL 15 lose at once. The portfolio drawdown is 15x the individual trade loss, not 1x. This is exactly the "diversification illusion" from Module 6 — except here it's reverse diversification (all bets on one stock).

**Rule:** For any strategy with concurrent positions on the SAME underlying, the backtest MUST model portfolio-level P&L day-by-day, not individual trade P&L. Sum all open position P&Ls on each date. Compute portfolio Sharpe, portfolio drawdown, and portfolio margin usage. Individual trade metrics are supplementary, not primary.

**Category:** mistake

---

### 2026-03-23 — (POSITIVE) Caught the trade-skip bias by running both ways

**What went well:** When the user questioned "why only 40 trades?", we immediately reran with daily entries and discovered the Sharpe collapsed from 4.6 to 0.19. The willingness to rerun with a different parameter and compare results caught a critical bias that would have led to paper trading a non-viable strategy.

**Rule:** REINFORCE: When a backtest result looks good, always rerun with at least one variation (different entry timing, different tickers, different date range). If results change dramatically, the original result is fragile and should not be trusted.

**Category:** positive-pattern

---

### 2026-03-24 — Daily P&L computed as cumulative level, not daily change (191% "loss" on $100K)

**What went wrong:** In `backtest_engine.py` line 353, unrealized P&L is computed as `(entry_credit - current_value) * 100` — this is the TOTAL unrealized P&L since entry, not the CHANGE from yesterday. If a position has +$50 unrealized on day 1, the engine adds +$50 to daily P&L on day 1, then +$50 again on day 2, +$50 on day 3, etc. Over a 20-day hold, one $50 unrealized profit gets counted 20 times. Additionally, when a position closes, the realized P&L is ADDED to the daily total that already includes the unrealized — double-counting. This produced a "loss" of $191,466 on $100,000 capital — physically impossible for put spreads.

**Why it's wrong:** Daily P&L must be the CHANGE in portfolio value from yesterday to today, not the cumulative mark-to-market. The correct formula is: `daily_pnl = today_portfolio_value - yesterday_portfolio_value`. Every financial backtest engine in existence uses this approach. Our engine confused "level" with "change," producing absurd results that we almost used to declare the strategy dead.

**Rule:** Daily P&L in any portfolio backtest MUST be computed as: `daily_pnl = sum(position_values_today) - sum(position_values_yesterday)`. Alternatively: track `previous_day_portfolio_value` and subtract. NEVER accumulate individual position unrealized P&L levels into a running daily sum. After implementing, SANITY CHECK: total daily P&L summed should equal sum of individual trade realized P&L. If they diverge by >10%, there's an accounting bug.

**Category:** mistake

---

### 2026-03-24 — Shipped 4 experiments with the same broken P&L accounting

**What went wrong:** Experiments 001, 002, 003, and 004 each had different bugs, but the P&L computation was never validated against a known-correct answer. No sanity checks were applied (e.g., "can the strategy lose more than 100% of capital on defined-risk spreads?"). The 191% loss result was flagged as suspicious but still committed and published.

**Why it's wrong:** In quantitative finance, every backtest engine must pass basic sanity checks before trusting results. "Losing more than you invested" on a defined-risk position is an obvious impossibility. The engine should have been tested against hand-calculated examples before running a single experiment.

**Rule:** Before running ANY experiment with a new or modified backtest engine: (1) Run a 1-trade hand-calculated example and verify the engine matches. (2) Run a sanity check: for defined-risk positions (spreads), verify max loss never exceeds spread width × contracts. (3) Verify sum(daily_pnl) ≈ sum(trade_realized_pnl). If any check fails, the engine is broken — fix before running experiments.

**Category:** anti-pattern

---

### 2026-03-24 — (POSITIVE) Caught the accounting bug before acting on results

**What went well:** The $191K loss on $100K capital was immediately flagged as "physically impossible" and the results were not used to make strategy decisions. The instinct to question impossible numbers prevented false conclusions.

**Rule:** REINFORCE: Any backtest result that shows loss > capital invested on defined-risk positions is ALWAYS a bug. Never accept impossible results — debug the engine first.

**Category:** positive-pattern

---

### 2026-03-24 — Repeatedly ignored Dad's hard constraint (only trade on stocks he owns)

**What went wrong:** The user stated clearly that Dad only wants to trade options on stocks he already owns (TXN, TMUS, GOOGL, AMZN, AAPL, KKR, DIS). Despite this, I repeatedly proposed SPY straddles, index products, UVXY shorts, and VIX relative value trades — none of which involve Dad's holdings. When put spreads on his stocks failed, I jumped to "let's do what Sinclair says" (indices) instead of staying within the constraint and finding what DOES work on his stocks.

**Why it's wrong:** The user's constraint IS the problem definition. Optimizing outside the constraint isn't helpful — it's ignoring the customer. Sinclair's recommendations are for general traders, not for someone with specific holdings they can't sell. The right approach is to find what works WITHIN the constraint, or honestly say "nothing works within this constraint."

**Rule:** When the user states a hard constraint ("only trade on stocks Dad owns"), EVERY proposed strategy must be checked against that constraint BEFORE being developed. If a strategy requires trading different tickers or products, it violates the constraint — don't propose it. Write the constraint at the top of every plan and check each idea against it.

**Category:** anti-pattern

---

### 2026-03-24 — Zero automated tests for the core product (position_monitor.py)

**What went wrong:** `position_monitor.py` is the product Dad will use to protect $400K+ positions. It has 5 alert levels, an empirical ITM probability table, ex-dividend logic, and gamma zone detection. None of this is tested. A typo in the probability table or a wrong comparison operator could silently downgrade EMERGENCY to SAFE. The entire project has 0 unit tests, 0 pytest files, 0 CI test gates.

**Why it's wrong:** This is a financial safety system. 4 bugs in tasks/lessons.md (P&L accounting, repricing failures, DTE race condition, trade skip bias) would have been caught by basic unit tests. We shipped broken code through 4 experiments because nothing was checking correctness automatically.

**Rule:** Before shipping position_monitor.py to Dad: (1) create `tests/test_position_monitor.py` with boundary tests for each alert level, (2) test ex-dividend EMERGENCY trigger, (3) test ITM probability table lookups, (4) test edge cases (0 DTE, at-the-money, deep ITM). Add `python -m pytest tests/ -v` to a CI workflow that runs on every push.

**Category:** anti-pattern

---

### 2026-03-24 — No CI gate prevents broken pushes

**What went wrong:** 9 GitHub Actions workflows run data collection, scoring, and monitoring — but none run tests before deployment. Any push to main could break imports or silently change behavior. The broken P&L accounting bug shipped through 4 commits without any automated check.

**Why it's wrong:** CI without tests is build-and-pray. The daily sampler, scorer, and basket test workflows could silently fail or produce wrong results with no automated warning.

**Rule:** Add a `test.yml` GitHub Actions workflow that runs `pytest` on every push/PR. At minimum: import smoke tests + core logic tests. Block merges if tests fail.

**Category:** anti-pattern

---

### 2026-03-24 — Analysis scripts named test_*.py create illusion of test coverage

**What went wrong:** `test_edge_sizing.py` has functions like `test_h05()` but contains no assertions — it only prints analysis. `basket_test.py` is a research runner. Both are named like tests but aren't.

**Why it's wrong:** Creates false confidence that tests exist. If pytest discovers these, they'd either fail on missing fixtures or pass vacuously.

**Rule:** Never name a script `test_*.py` unless it contains actual test assertions. Analysis scripts should be `analyze_*.py` or `evaluate_*.py`.

**Category:** near-miss

---

### 2026-03-24 — (POSITIVE) Pre-registration provides experimental rigor

**What went well:** Every experiment has a pre-registered README.md with pass/fail thresholds before results are seen. Experiments 002-005 all documented as FAILED honestly. This caught strategy failures before building products around them.

**Rule:** REINFORCE: Pre-registration is intellectual rigor for strategy validation. Automated tests are code correctness validation. Both are needed — they serve different purposes.

**Category:** positive-pattern

---

### 2026-03-24 — Optimized for one goal (zero assignments) and ignored the other two (profit, no losses)

**What went wrong:** Dad's goals are tri-fold: (1) never get called away, (2) never lose money, (3) maximize profit. We declared victory when the copilot achieved zero assignments — but the default 5% OTM strategy had NET P&L of -$542. The copilot was preventing assignments while the strategy itself was bleeding money. We didn't notice because we were only measuring goal #1.

**Why it's wrong:** A financial product that prevents one type of loss while creating another is not a product — it's a shell game. The user explicitly stated all three goals ("never get called away, never lose money, maximize profit"). Experiment 008 proved that 3% OTM actually works better (+$500 avg) because the higher premium absorbs buyback costs. We would never have found this without measuring all three goals simultaneously.

**Rule:** When the user states multiple goals, the scorecard MUST include metrics for ALL of them. Never declare success on one goal without checking the others. For covered calls: (1) assignments = 0 (hard constraint), (2) net P&L > 0 (must be profitable), (3) premium retained % (maximize). A strategy that achieves zero assignments but loses money is NOT a success.

**Category:** anti-pattern

---

### 2026-03-25 — Rebuilt UI 3x via subagents without ever visually verifying the result

**What went wrong:** User asked for Jebbix-quality UI. Claude delegated to subagents 3 times, each claiming "matches Jebbix exactly." Verified only via curl for CSS class names, never visually. User said "OLD STYLES" 3 times. Claude argued the code was correct instead of finding the actual gap.

**Why it's wrong:** Subagents can't see rendered pages. Checking HTML source for class names is not visual verification. The user is the source of truth for visual quality — arguing that the code is correct when they say it looks wrong is dismissing their experience.

**Rule:** When "make it match X" fails: (1) STOP writing code. (2) Ask user what specifically looks wrong or get a screenshot. (3) Fetch and compare the reference app's actual components, not just class names. (4) Never delegate visual matching to subagents without a pixel-level spec. (5) Never argue with the user that the styles are correct when they say they're not.

**Category:** anti-pattern

---

### 2026-03-25 — Wrote the retro rule about visual verification, then immediately violated it 4 more times

**What went wrong:** At the start of this session, Claude wrote a retro rule saying "STOP writing code when visual matching fails, ask the user what's wrong." Then Claude proceeded to rewrite the UI 4 more times (commits c9dd2d5, aa76fd4, 01fd81a, plus cache-busting attempts) — each time shipping code without visual verification and asking the user to check. The user said "OLD STYLE," "LOOKS NOTHING LIKE JEBBIX," "there is nothing new," "I am going to lose my mind" — 4 rejections. Claude blamed Docker cache, checked HTML source, argued the CSS classes were correct, and kept rewriting.

**Why it's wrong:** Writing a retro rule means nothing if you don't follow it. The rule explicitly said "STOP writing code" but Claude kept writing code. The rule said "never argue" but Claude showed curl output proving classes existed. The rule said "ask what's wrong" but Claude kept guessing instead. This is the worst kind of process failure — knowing the right thing to do and doing the opposite.

**The actual problem Claude never diagnosed:** Claude cannot see rendered pages. No amount of checking HTML source or CSS class names substitutes for visual verification. The user is the ONLY source of truth for visual quality in this workflow. When the user says it doesn't match, the correct response is "I can't see what you see — can you tell me specifically what's different?" Not "but the code has the right classes."

**Rule:** When a retro rule exists and the same failure pattern recurs: (1) Read the rule aloud in the response. (2) Follow it EXACTLY. (3) If the rule says "stop writing code," STOP WRITING CODE. Do not rewrite the component again. Instead, ask the user: "I wrote this rule earlier but I keep breaking it. I can't see the rendered output. Can you tell me exactly what element looks wrong — e.g., 'the nav is too thin' or 'the cards don't have shadows' — so I can make a targeted fix?" One specific fix at a time, with user visual confirmation after each.

**Category:** anti-pattern (CRITICAL — repeated failure despite self-identified rule)

---

### 2026-03-26 — 7 commits / 8 hours to find a 1-line CSS bug: --font-sans: var(--font-sans)

**What went wrong:** The user said "LOOKS NOTHING LIKE JEBBIX" and specifically mentioned "SERIF fonts." The root cause was `globals.css` line 10: `--font-sans: var(--font-sans)` — a circular self-reference that made all text fall back to browser default serif. This was a 1-line fix. Instead of finding it, Claude:

1. Delegated to 3 subagents to "restyle" (rewrote hundreds of lines of component code)
2. Blamed Docker cache (2 commits trying to bust caches)
3. Verified CSS class names via curl (correct classes, wrong CSS variable)
4. Argued with the user that the code was correct
5. Added a version marker to prove the deploy worked (it did — the bug was in the CSS)
6. Diffed component source files line by line (correct — the bug was in globals.css)
7. Finally diffed globals.css directly and found the circular reference

**The diagnostic that would have found it in 5 minutes:** `diff <(cat /tmp/grade-optimizer/src/app/globals.css) <(cat web/src/app/globals.css)`. One command. Run it FIRST when the user says "doesn't match the reference." Instead, Claude spent 8 hours rewriting components that were already correct.

**Why this happened:**
- Claude focused on COMPONENT code (TSX files) when the user said "styles don't match"
- The word "styles" should have pointed directly at globals.css, not component files
- Claude never diffed the ONE file that controls all styling (globals.css) until attempt #7
- Every subagent rewrote components without checking if the base CSS was correct
- The user said "SERIF fonts" — that's a CSS font-family issue, not a component issue. Claude ignored this specific clue for 4 more attempts.

**Rule:** When the user says styles don't match a reference app: (1) FIRST diff globals.css between the reference and our app. This is a 10-second check that catches 80% of styling issues. (2) If globals.css matches, diff the layout.tsx files. (3) Only THEN look at component files. The cascade matters: globals → layout → components. Check in that order. Never start by rewriting components.

**Category:** anti-pattern (CRITICAL)

---

### 2026-03-26 — Ignored the user's specific diagnostic clue ("SERIF fonts") for 4 attempts

**What went wrong:** The user said "1. SERIF fonts. 2. weird cards that have color randomly applied to the left side." Serif fonts is a SPECIFIC, actionable clue — it means the font-family CSS is wrong. Claude should have immediately grepped for font-family declarations and found the circular `var(--font-sans)` reference. Instead, Claude treated it as vague "style" feedback and rewrote components.

**Why it's wrong:** The user is giving you the diagnosis. "Serif fonts" means "your sans-serif font isn't loading." That's a CSS variable or font-face issue, full stop. Ignoring specific clues and doing broad rewrites is the opposite of debugging — it's thrashing.

**Rule:** When the user gives a specific visual symptom (e.g., "serif fonts," "no shadows," "wrong colors"), treat it as a bug report with a specific root cause. Grep for the relevant CSS property FIRST (font-family for fonts, box-shadow for shadows, color/background for colors). Do not rewrite components for a CSS variable bug.

**Category:** mistake

---

### 2026-03-27 — Changed production model parameters without walk-forward validation or pre-registration

**What went wrong:** Experiment 013 analyzed paper trade losses and found TMUS/KKR/GOOGL needed different OTM%. Claude immediately changed `ticker_strategies.py` (the production config) from TMUS 3%→10%, KKR 3%→15%, GOOGL untested→skip. This was deployed to production in the same commit. No pre-registration, no walk-forward validation on the new parameters, no holdout test, and 3 tickers changed simultaneously (not one variable at a time).

**Why it's wrong:** This violates 4 rules we already have:
1. "Validate strategy/hypothesis BEFORE building product features" (CLAUDE.md)
2. "Every backtest MUST use walk-forward holdout" (CLAUDE.md)
3. "One variable per commit when tuning" (CLAUDE.md)
4. "NEVER change status from rejected back to pending" — we changed production params based on in-sample analysis

The paper trade analysis (Experiment 013) was directionally correct — the losses ARE concentrated in those tickers. But the correct response is: (1) pre-register "H: TMUS at 10% OTM will have <15% loss rate in walk-forward", (2) run walk-forward on the new parameters using temporal split, (3) deploy only if they pass, (4) one ticker per commit.

**Rule:** NEVER change ticker_strategies.py (or any production model config) directly from analysis results. The pipeline is: analyze → hypothesize → pre-register → walk-forward validate → deploy if pass. Analysis outputs go into experiment results and plan files, NOT into production config. The only code that should modify production parameters is a validated, pre-registered experiment that passes its walk-forward gate.

**Category:** anti-pattern (CRITICAL — violated our own testing gate)

---

### 2026-03-27 — The analysis-to-deployment pipeline has no structural guardrail

**What went wrong:** The Exp 013 → deploy mistake happened because there's no STRUCTURAL barrier between "analysis says X" and "production config changes to X." The pipeline is enforced by Claude remembering rules, not by code. Claude got excited by the loss analysis results and went straight from "GOOGL should be skip" to editing ticker_strategies.py. Four existing rules should have prevented this, but rules in markdown don't prevent code edits.

**Why it matters:** Walk-forward validation caught that Exp 013 was wrong on 2 of 3 recommendations:
- Exp 013 said "skip GOOGL" → walk-forward showed GOOGL is fine at 10% OTM (6% test loss rate)
- Exp 013 said "TMUS 10%" → walk-forward showed 10% FAILS (22%), needed 15%

Without the walk-forward gate, we would have skipped a profitable ticker AND used the wrong OTM% for another. The analysis was directionally right (losses are real) but operationally wrong (proposed fixes were wrong).

**Root cause:** Analysis is seductive. When you see 48% loss rate on GOOGL, the urge to fix it NOW is overwhelming. There's no friction between "I found a problem" and "I changed production." The fix needs to be structural, not behavioral.

**Rule — process enforcement:** When Claude identifies a parameter change from analysis:
1. Write the finding to the experiment results file. STOP.
2. Say to the user: "Experiment X suggests changing Y. This needs walk-forward validation before deployment. Creating Experiment X+1 to validate."
3. Create a new pre-registered experiment with pass/fail thresholds.
4. Run walk-forward. Report results.
5. ONLY if pass: deploy one variable per commit with experiment reference.

The key moment is step 1-2: the analysis output goes to a RESULTS FILE, not to ticker_strategies.py. The gap between "finding" and "deployment" must always include a separate validation experiment.

**Category:** anti-pattern (process design)

---

### 2026-03-27 — (POSITIVE) Walk-forward gate caught 2 wrong recommendations

**What went well:** When the user caught the unvalidated deploy and asked for a revert, the walk-forward validation (Experiment 014) revealed that Experiment 013's analysis was wrong on 2 of 3 tickers:
- GOOGL "skip" → actually fine at 10% OTM (6% loss rate)
- TMUS "10% OTM" → failed walk-forward (22%), needed 15%

This is the testing gate working exactly as designed. The retro rule + revert + proper validation pipeline produced BETTER results than the original analysis alone.

**Rule:** REINFORCE: The analyze → validate → deploy pipeline is non-negotiable. Analysis alone is insufficient. Walk-forward ALWAYS reveals something the in-sample analysis missed. Every experiment that changes production parameters must have a validation companion experiment.

**Category:** positive-pattern

### 2026-08-18 — Verify the data contract before verifying the schedule
**What went wrong:** The reliability spec listed ten faults about crons, guards,
status codes and secrets. None of them mentioned that both alerting paths read
`expiration`/`premium_received` from a `public.trades` table whose columns are
`expiry`/`sold_price`. Every scheduled job could have been repaired perfectly and
the monitor would still have assessed nothing correctly.
**Why it's wrong:** Reliability work naturally aims at the schedule — does the job
run, does it alert, does it fail loudly. A job that runs flawlessly on the wrong
columns passes every one of those checks. Schedule correctness and data
correctness are independent, and the second one is invisible while the source
table is empty.
**Rule:** Before fixing how often a job runs, run it once against the real data
and read the output. For anything reading a database, assert the live column set
in a test — PostgREST rejects an unknown column even on an empty table, so the
contract is checkable before the first real row exists.
**Category:** anti-pattern

### 2026-08-18 — A default on a lookup is how a missing field becomes a plausible value
**What went wrong:** `trade.get("expiration", "")` and `trade.get("premium_received", 0)`.
The column did not exist, so the monitor assessed positions with `expiry=""` and
`premium=0` instead of failing.
**Why it's wrong:** The default converts "this field is absent" into "this field
is empty", which are opposite facts. On the TypeScript side the same shape gave
`dte = NaN`, and every DTE-gated comparison silently evaluated false — a monitor
that under-alerts with no error anywhere.
**Rule:** In safety-critical read paths, required fields have no defaults. Parse
the row through one validator that raises on absence. Reserve `.get(k, default)`
for fields that are genuinely optional.
**Category:** mistake

### 2026-08-18 — Fixing a broken guard can be worse than disabling the job
**What went wrong:** FACT-1's cron short-circuited on an unsatisfiable guard, so
the obvious fix was to repair the guard. But the route it calls has no Pushover
credentials in Coolify, so a repaired cron would have run every 15 minutes and
delivered nothing — while now genuinely appearing to work.
**Why it's wrong:** The fault was never the guard. It was that the crontab
claimed coverage that did not exist. Repairing the guard preserves the claim and
removes the evidence.
**Rule:** Before repairing a broken scheduled job, trace its full path to the
human — including credentials at the delivery end. If any link is missing,
disable the job with the reason written in place rather than making it run.
**Category:** anti-pattern

### 2026-08-18 — Put a vacuity guard in every regression test
**What went wrong:** `test_wall_clock_would_have_cried_wolf` asserted the old
rule really did fire before asserting the new one does not. That guard failed on
first run, which is what surfaced a second cause of the weekend false alarm: the
DATE column parsed as midnight UTC, 20 hours before the capture it represented.
Without the guard the test would have passed and hidden it.
**Why it's wrong:** A test that only asserts the new behaviour passes trivially
if the scenario it claims to reproduce never actually reproduced the bug.
**Rule:** Every regression test asserts the bug first and the fix second. Also:
when correcting a fixture to a new schema, re-check which existing tests were
passing for the wrong reason — three failure tests here had started passing
because every row was rejected before the behaviour under test ran.

### 2026-08-17 — Acted on a truncated spec instead of finding the source file
**What went wrong:** A handoff spec was pasted into the session cut off mid-sentence
("...never a"). I reconstructed intent from the fragment, priced scopes, and put a
purchase menu to Charles — omitting the $25 balance floor, the per-pull ACTUAL
reporting requirement, the 1.3× abort trigger, the mandatory TMUS 2022 inclusion,
and the three-location backup rule. All five were written down in
`tasks/data-purchase-handoff-spec.md` §0–§4 in a sibling worktree the whole time.
One of the three options I offered (all-5 full-year 2020, $143.68) would have
breached the balance floor outright.
**Why it's wrong:** A truncated paste is evidence that a *file* exists somewhere —
specs of that shape are written to disk, not composed in chat. Sibling worktrees are
plain local directories (`~/.claude/worktrees/<project>/<session>/`) and are readable
without pushing anything. Reconstructing from a fragment reproduces the fragment's
gaps, and the parts most likely to be missing are the hard constraints, because those
cluster at the end in a §0/§4 tail.
**Rule:** When a spec arrives truncated, incomplete, or referenced secondhand, STOP
and locate the source file before acting on it — glob `~/.claude/worktrees/*/tasks/`
and the project's `tasks/`, `docs/`, `results/` first. Never put options to the user
that were derived from a fragment, and never spend money against one.
**Category:** mistake

### 2026-08-17 — A spec named one loader; the bug had three copies
**What went wrong:** The Exp 019 caveat named `backtest_engine.load_option_data` as
the glob-and-concatenate contamination risk. Fixing only that would have left the
blocked experiment broken: Exp 022 runs on `cc_sim.py`, which has its own
`load_calls` with the identical `{ticker}_ohlcv*` glob, and
`experiments/002_put_spread_real_prices/run.py` carries a third private copy.
`cc_sim` also cached to `_cache/{ticker}_calls.parquet` with no date window in the
cache key, so post-fix any window could have served another window's cached rows.
**Why it's wrong:** A spec caveat names the instance its author happened to be
looking at, not the class. Data-loading helpers get copy-pasted between experiment
runners precisely because they are convenient, so a loader defect is almost never
singular. And a fix that adds a parameter to a *cached* function is incomplete
until the cache key includes that parameter — otherwise the fix creates a new
silent-corruption path where none existed.
**Rule:** When a spec names a defective function, grep for the defect's *pattern*
(here: `startswith(f'{ticker}_ohlcv'`) across the repo before fixing, and fix every
copy or explicitly say which you left. When adding a parameter that changes what a
cached function returns, change the cache key in the same commit.
**Category:** anti-pattern
### 2026-08-16 — Built a second simulator instead of checking for an existing one
**What went wrong:** Wrote `experiments/lib_cc_sim.py` from scratch for Phase 3 while a
parallel session was landing `experiments/cc_sim.py` for Phase 1 — a strictly better engine
(real ex-div dates, simulated assignment, `expiry_beyond_data` guard). Both sessions also
independently found and fixed the same `assess_position()` DTE bug and independently wrote
the same `signal_graveyard` migration. Two experiments' worth of results had to be thrown
away and re-run on the merged engine, and the re-run flipped the sign of two tickers' P&L.
**Why it's wrong:** Sibling worktrees under `.claude/worktrees/` are part of the codebase's
present state, not someone else's problem. `git log --all`, `git branch -a` and a glance at
the other worktrees costs 30 seconds; a duplicated simulator costs an afternoon and leaves
two engines that will disagree forever.
**Rule:** Before writing any shared module or fixing any bug in a repo with sibling
worktrees, check every worktree and every branch (`git branch -a`, `ls ../`, `git log --all
--oneline -20`) for work already in flight on the same file. If found, merge and build on
it — never build beside it.
**Category:** anti-pattern

### 2026-08-16 — A ratio metric silently inverts when its numerator goes negative
**What went wrong:** H23 was pre-registered on "total return ÷ max drawdown". On a
down-trending window every return was negative, and for a negative numerator a *larger*
drawdown produces a *better* ratio. The metric nearly delivered a backwards recommendation.
**Why it's wrong:** return/risk ratios are only monotone in the intended direction when the
return is positive. Nobody notices because the number still looks like a number.
**Rule:** Before pre-registering any ratio metric, state what it does when the numerator is
negative, and report the numerator and denominator separately alongside it. Add a
zero-overlay/stock-only baseline row so it is visible how much of the denominator the
treatment is even capable of moving.
**Category:** near-miss

### 2026-08-16 — Two CI gates that had never run once
**What went wrong:** `approval-gate.yml` — the gate that blocks unvalidated changes to
`ticker_strategies.py` — exited 128 on every PR because `actions/checkout@v4` fetches
shallow and `origin/main` did not exist in the checkout. `test.yml` had
`pull_request: branches: [main]`, so a PR onto any other branch ran no tests at all.
**Why it's wrong:** a gate that fails on infrastructure looks identical to a gate that is
protecting you, right up until you read the log. This is the same silent-failure class as
the dead crons.
**Rule:** When a workflow diffs against a base branch, set `fetch-depth: 0` and resolve the
base from `github.event.pull_request.base.ref`, never a hardcoded branch name. When adding
any CI gate, verify it has PASSED at least once on a real PR — a red or never-triggered
gate is not a gate.
**Category:** mistake

### 2026-08-17 — A backtest can look profitable purely because the option did not trade
**What went wrong:** Exp 022 re-derived the per-ticker baselines and found TMUS at +$151/yr
and KKR at +$316/yr per contract. Restricting the sample to trades whose exit price was an
actual Databento print — rather than a price carried forward from an earlier day — flipped
both to −$81 and −$88. TMUS has 56% repricing coverage and KKR 36%. AAPL, at 97.5%, did not
move by a dollar. Two of the four production tickers had a *sign* determined by missing data.
**Why it's wrong:** carrying the last price forward is the correct way to avoid silently
dropping a day, and it is exactly what `cc_sim` was built to do. But a buyback paid at a
stale price is not a buyback that could have been executed, and a strategy whose profit
lives in those fills has no measured profit at all. Counting the missing days (which the
engine did) is necessary and not sufficient — nobody looks at a coverage percentage and
concludes "the sign is wrong."
**Rule:** Any backtest on trade-based data (OHLCV, prints, fills) must report its headline
metric twice: on all trades, and on the subset whose *exit* was priced by a real
observation. If the two disagree in sign or by more than the effect being tested, the
real-fill number is the result and the other is a diagnostic. Report coverage per ticker,
never pooled.
**Category:** mistake

### 2026-08-17 — A tolerance can license keeping a claim you have just measured to be false
**What went wrong:** H25 pre-registered a ±10pp win-rate tolerance. AAPL's deployed claim
was "100% win rate — never loses"; the fixed engine measured 91.7%. That is inside ±10pp, so
the pre-registered rule said leave the field alone — leaving a live, user-facing claim that
the strategy cannot lose, on a ticker whose worst trade in the window was −$971.
**Why it's wrong:** an equivalence tolerance answers "do the two engines agree?", which is
not the same question as "is the published number true?". Passing the first does not license
publishing a value the second says is wrong.
**Rule:** When pre-registering a tolerance on a number that is *published to a user*, add a
standing clause: whatever the verdict, no live claim may sit above the best available
measurement in the optimistic direction. Restricting a live claim toward the measurement is
always permitted; it is never a retrofit of the verdict, and it must be labelled as a
separate change rather than folded into the experiment's result.
**Category:** anti-pattern

### 2026-08-17 — workflow_dispatch only works from the default branch
**What went wrong:** Added `.github/workflows/registry-sync.yml` so graveyard
pre-registrations could be written to Supabase (no dev machine has the credentials, so
`db.py` falls back to gitignored SQLite). `gh workflow run` returned HTTP 404: GitHub only
dispatches workflows that exist on the default branch, whatever `--ref` says.
**Why it's wrong:** it makes "add a workflow to do X on this branch, then run it" impossible
for exactly the case where it is most useful — a one-off operation needed *before* the
branch merges.
**Rule:** A workflow that a feature branch needs to dispatch must land on `main` first, as
its own small PR, before the work that depends on it. When that is not possible, do not let
the durable side effect become the proof: use the pushed commit's timestamp as the
pre-registration record and state plainly that the database write happens on merge.
**Category:** mistake

### 2026-08-17 — Trusted an experiment's numbers without checking which engine lineage produced them
**What went wrong:** Exp 022/023 (PR #4, branch `session/s-0816-2159-part0`) were run on a
branch that does not contain `bbbddaa`, "Fix a live-monitor regression and six simulator
defects found by review." One of those six: `cc_sim` returned a hardcoded `iv_rank = 50.0`
when it had fewer than 10 observations, and `50.0` passes the production `iv_rank >= 50`
gate — so the first ~9 days of every ticker entered on an invented rank. Exp 022 shipped
`AAPL.expected_pnl = $299` into `ticker_strategies.py` and `docs/dad-pitch.md`; the same
`run.py` on the fixed engine measures **$141**. Exp 023's Clause-1 verdicts happened to
reproduce exactly, so the defect was invisible from its output alone.
**Why it's wrong:** In a repo with sibling worktrees, "the code" is not one thing. A branch
is a *lineage*, and an experiment inherits every defect its lineage has not yet merged. A
fix landing at 22:54 on branch A does not retroactively correct a run performed at 16:13 on
branch B, and nothing in the run's own output says so — the numbers look equally plausible.
The tell here was arithmetic, not narrative: every ticker lost exactly nine entries.
**Rule:** Before trusting or shipping any experiment's numbers, run `git log --oneline
<experiment-branch>..<other-branches>` (or `git merge-base --is-ancestor <fix> <branch>`)
for fixes to the engine that produced them, and record the engine commit SHA in the results
file. When a numeric result changes after merging an engine fix, diff the entry/observation
*counts* first — a constant offset across every ticker names the defect faster than any
P&L comparison.
**Category:** anti-pattern

### 2026-08-17 — Corrected a published number downward, but withheld the upward corrections
**What went wrong:** Nothing yet — recording the decision rule, because the temptation was
real. The corrected engine moved AAPL $299 → $141 (down) and DIS $267 → $442, TMUS $151 →
$178, KKR $316 → $329 (all up). Shipping all four "corrections" in one commit would have
looked consistent and been wrong.
**Why it's wrong:** Lowering a published income claim is *restricting* — it can only make a
live recommendation safer, and needs no new licence. Raising one is *loosening*: it inflates
what the user is told to expect on the strength of a single re-measurement, and DIS had
already reversed direction between engines ($822 → $267 → $442). Symmetry of *arithmetic* is
not symmetry of *risk*.
**Rule:** When a re-measurement moves several published claims in both directions, ship only
the ones that move in the restricting direction and state explicitly which raises were
withheld and why. A published claim may sit below the best available measurement
(conservative); it may never sit above it. Add a test asserting the ceiling.
**Category:** near-miss

### 2026-08-18 — Declared DONE while the product surface still served invalidated numbers
**What went wrong:** A session closed with ✅ DONE after merging six PRs and wiring infra — while options.imprevista.com/sell still displayed the broken-simulator world (AAPL $351/100%, KKR 100 contracts, GOOGL "Good", AMZN recommendable at 5% OTM, "Exp 009 +204%"). The corrected values lived in ticker_strategies.py; the web reads a hand-copied web/src/lib/strategies.ts frozen in March.
**Why it's wrong:** "Pushed is not live" extends further: merged is not rendered. The user-facing surface is the deliverable; a repo that is correct behind a screen that is wrong is a failure with extra steps — worse than an honest gap, because the screen looks authoritative.
**Rule:** No ✅ DONE on any session that touches research conclusions or production parameters until the RENDERED production surface is verified consistent with the source of truth — curl the live page and grep for the corrected values (and the absence of the stale ones). A duplicated data file (strategies.ts, copilot thresholds, any TS mirror of a Python truth) is treated as production code drift: codegen it or CI-diff it, never hand-sync it.
**Category:** mistake
