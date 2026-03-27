# Lessons Learned

Rules derived from mistakes in this project. Claude MUST review this file at the start of every session and follow these rules.

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
