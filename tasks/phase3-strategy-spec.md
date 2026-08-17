# Phase 3 Farm-Out Spec — Strategy Improvement: Stress Validation, Partial Overwriting, Capacity

**Executor:** Opus 5, fresh session, working dir `/Users/charlesrogers/Documents/options-tool`
**Prerequisites:**
- Phase 0 complete (`tasks/week1-reliability-spec.md`) — never run research through a pipeline that can silently lie.
- Phase 1 verdicts exist (`tasks/week2-research-spec.md`, Exps 015–017) — Exp 019 stress-tests whichever buyback rule won. It does NOT require Phase 1 to have *passed*; a fail verdict just means the stress test runs against the current production rule only.
- **Blocker input from Charles:** the Databento API key from his father's account, and confirmation the ~$125 credit balance is still live. Do not begin Part A without both.

**Read first:** `CLAUDE.md`, `tasks/lessons.md`, `tasks/week2-research-spec.md` (the research discipline section applies verbatim here), `signal_registry.py`, `ticker_strategies.py`, `experiments/backtest_engine.py`, `results/010_bear_market_stress.md`, `results/012_walk_forward.md`

**This spec registers H21–H24.** All bettybot discipline from the Week 2 spec applies: pre-register with immutable thresholds before touching data, walk-forward where applicable, results to `results/`, graveyard verdicts for pass AND fail, one variable per commit, no silent Nones, report missing-data counts, label any BSM/proxy result "directional only."

---

## Part A — The one-shot Databento purchase (protocol, not an experiment)

$125, one chance. The purpose is regime coverage: everything validated so far ran on 2024–2026, a favorable regime (KKR excepted, 3 years). The purchase order is fixed; the *pre-registrations for Exps 019 and 021 must be committed before the first pull.*

**Purchase order (stop when budget is exhausted):**
1. TMUS option OHLCV **2022** + that period's definitions ← pull FIRST (cheapest of the priority items; calibrates the cost model — definitions ran 2× estimates last time)
2. AAPL option OHLCV **2020** + definitions
3. AAPL option OHLCV **2022** + definitions
4. TMUS option OHLCV **2020** + definitions
5. GOOGL option OHLCV **most recent full year** + definitions (its production parameter currently rests on stock-proxy validation only)
6. DIS 2022, then MSFT most recent year — only if budget remains

**Protocol (lessons.md 2026-03-23, verbatim discipline):**
- Estimate with `get_cost()`, pull, check the **actual** charge, recompute the correction factor, re-plan remaining pulls. Never trust the estimator's first number.
- Hard stop at **$120 cumulative actual spend**. Print a running budget line after every pull.
- Verify each file loads through `experiments/backtest_engine.py` and report row counts + missing-bar percentage per ticker-year immediately, BEFORE the next pull (a corrupt or uselessly sparse pull changes the plan).
- Files go to `/Users/charlesrogers/Documents/options-tool/data/databento/raw/` following the existing naming scheme (`{TICKER}_ohlcv_1d_{tag}.dbn.zst`), gitignored.
- Do NOT buy: intraday/L1 schemas, SPX/index data, TXN anything, more 2024–2026 data for already-covered tickers, illiquid names (OHLCV is trade-based; no-trade strikes have no bars — that's why KKR came back 71% empty).

**Free data to fetch alongside (needed by H22):** CBOE VIX and VIX3M daily history 2019–2023 (free download), for the term-structure guard test.

## Part B — Exp 019: Bear/Rebound Stress Replay (register H21, Tier 1)

**Hypothesis (H21):** The production covered-call system (per-ticker OTM%/DTE from `ticker_strategies.py`, IV-rank ≥ 50 gate, copilot exits — run BOTH the distance-based rule and, if Exp 015 passed, the probability-based rule) produces, on real 2020 and 2022 option prices: **zero assignments**, per-ticker annual loss rates within **10 percentage points** of their 2024–26 walk-forward values, and total return ≥ buy-and-hold-stock-only minus $0 (i.e., the overlay never amplifies losses — the Monte Carlo claim from Exp 010, now tested against history).

**Why this matters:** the known hole is the 2020 shape — crash pins IV rank at 100, the gate screams SELL, then a V-recovery runs over every call. Exp 010 was Monte Carlo; this is the real thing.

**Method:** replay each stress year through the existing simulator with production settings frozen as of the pre-registration commit. Compare loss rates, retention, assignment count, worst trade, and buyback frequency against the 2024–26 baselines in `results/012_walk_forward.md`. Report 2020 and 2022 separately — they fail differently (gamma/rebound vs. grind).

**Pass (immutable):** all three clauses of H21 hold in both years for AAPL and TMUS (the tickers with full data).
**Marginal:** loss rates within 10pp but retention collapses (>50% relative drop) — strategy survives but the income claim gets a regime caveat in all Dad-facing material.
**Fail:** any assignment, or a loss rate >10pp worse, or the overlay amplifies losses in either year. A fail is a **product-level finding**: the rule card gains a regime kill-switch ("no new calls when [condition]") before Dad scales up, and the dad-pitch bear-market section gets rewritten with the real numbers.

## Part C — Exp 019b: Backwardation Guard (register H22, Tier 2 — piggybacks on Part B data)

**Hypothesis (H22):** Adding a guard to the entry gate — suppress new call sales when VIX > VIX3M (term structure in backwardation) OR the stock is > 15% below its 60-day high (arbitrary starting values, labeled as such) — improves 2020 stress-year P&L by ≥ 20% relative with ≤ 10% of entries skipped across the full 2019–2023 window, and changes 2022/2024–26 results by ≤ ±5% (the guard should be dormant outside crash regimes — that's its control condition, bettybot-style).

**Source:** Sinclair & Mack Ch. 10: the one situation their risk tolerance forbids is selling into a vol spike with the term structure in backwardation — "the volatility equivalent of catching a falling knife." Our IV-rank gate, validated only in calm regimes, actively *encourages* exactly that.

**Pass/Fail:** as stated, immutable. Deployment: entry-gate addition in one commit, only after pass, with the guard's live status surfaced on the Sell tab.

## Part D — Exp 020: Partial Overwriting (register H23, Tier 2 — no new data needed)

**Hypothesis (H23):** Overwriting **50–70%** of shares per ticker (vs. the implicit 100%) produces a higher full-period total return (premium retained + upside participation on uncovered shares − buyback costs) per unit of worst-drawdown, on the 2024–26 data AND on the Part B stress years, than 100% overwrite — while cutting buyback friction roughly proportionally.

**Source:** Sinclair, *Skewness and the Kelly Criterion* (PDF in the Knowledge folder — read it first): short-call P&L is negatively skewed; Kelly under negative skew prescribes sizing below full. Partial overwriting is also the structurally correct answer to "the income feels small" — the wrong answer (closer strikes) re-creates the 3–5% OTM death zone from Exp 008.

**Method:** grid overwrite ratio {50%, 70%, 100%} × the production per-ticker settings, walk-forward on 2024–26, then replay winners on stress years. Metric: total return / max drawdown, plus absolute income (Dad cares about the check size too — report both, recommend on the ratio, let Charles pick the point on the frontier).

**Pass (immutable):** some ratio < 100% beats 100% on return/drawdown in walk-forward test AND in ≥ 1 stress year, with absolute income ≥ 70% of the 100% level.
**Deployment:** overwrite ratio becomes a per-ticker field in `ticker_strategies.py` and a share-count line on the Sell tab. One commit.

## Part E — Exp 021: Capacity Expansion — GOOGL real-price, MSFT/AMZN staged (register H24, Tier 2)

**Hypothesis (H24):** (a) GOOGL's deployed 10% OTM / 20–45 DTE setting, validated so far only on stock closes, holds on its purchased real option year: test-period loss rate ≤ 15% and net P&L > 0. (b) MSFT and AMZN, entered at ultra-conservative 15% OTM / 20–45 DTE, show walk-forward stock-data loss rates ≤ 10% — qualifying them for **probation tier**: recommendable, flagged "stock-data validated only," at half the eventual size, while the daily chain capture accrues real option data for a 6-month upgrade review.

**Pass/Fail:** per clause, immutable. Deployment: per-ticker, one commit each; probation tickers get a distinct tier badge in `TIER_CONFIG` (don't reuse 'untested').
**Capacity note for KKR:** at 10k shares, KKR options trade ~2 contracts/day — the position IS the market. Cap KKR's recommended overwrite at a size consistent with ≤ 20% of its average daily contract volume, and surface that cap in the UI. Liquidity, not validation, is its binding constraint.

## Sequencing

Part A (purchase) any time after H21/H24 pre-registrations are committed. Part B/C after Part A. Part D immediately — it needs nothing new. Part E(b) immediately; Part E(a) after the GOOGL pull. If the budget dies before GOOGL (pull #5), Part E(a) converts to "extend GOOGL probation, upgrade from accrued chain captures in 6 months" — say so explicitly rather than silently skipping.

## Deliverables

- `experiments/019…022/README.md` pre-registrations (committed before data pulls/runs), `run.py` per experiment, `results/NNN_*.md` per experiment, graveyard verdicts for H21–H24.
- A purchase ledger in `results/019_data_purchase_ledger.md`: every pull, estimate vs. actual, running balance, row counts, missing-bar %.
- Updated `ticker_strategies.py` for every deployed change — one variable per commit, experiment ID in the message.
- pytest coverage for any new production logic (overwrite ratio math, guard conditions); CI green.
- Final summary table: hypothesis → verdict → deployed? → expected $ impact at 10k shares/ticker → regime caveats.
- `✅ DONE` proof-of-work (correctness review warranted: financial calculations and model parameters) or `⏸ HANDOFF` with per-part status. If the credits turn out insufficient mid-plan, that is a report line, not a failure — the fallback orderings above are pre-authorized.

## Out of scope

Anything levered or naked (structural constraint — Peters non-ergodicity, standing rule). SPX pivot. New subscriptions. Loosening EMERGENCY (that's H19's shadow-mode track, separately gated). Touching the copilot's exit thresholds outside what Exp 015 already validated.
