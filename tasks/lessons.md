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
