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
