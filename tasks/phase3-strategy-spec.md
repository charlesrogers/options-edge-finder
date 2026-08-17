# Phase 3 Farm-Out Spec — Strategy Improvement: Stress Validation, Partial Overwriting, Capacity

> **REVISED 2026-08-17 — read before executing.** Exp 015 (Week 2) found `assess_position()` computed DTE from `datetime.now()`, so **Experiments 007–013 are invalid** (every observation evaluated at DTE=0, ex_div_date=None). Consequences binding on this spec:
> 1. **New Part 0 (blocking): Baseline Re-derivation (Exp 022, register H25).** Re-run the 008/009-class per-ticker simulations on the fixed engine. Output: corrected win rate, net P&L, retention, buyback counts per ticker — reported as **ranges across half-year windows** (Exp 015 measured 40–180pp retention swings between halves; point estimates measure regime luck). Separate real-fill from carried-forward-price results (KKR: 44% synthetic fills). Then update `ticker_strategies.py` expected_* fields and `docs/dad-pitch.md` from corrected numbers only — the current values come from the broken simulator, including TMUS "tier good, expected_pnl 447" whose corrected test-period P&L is −98.2%. Do not re-tier tickers off one window; mark "revalidation pending" until Part 0 lands.
> 2. **H21's thresholds** ("within 10pp of walk-forward values") now reference Part 0's corrected baselines, not results/012 values.
> 3. Verify whether the Exp 006 assignment-probability table (the 145K-observation table in `position_monitor.py`) and Exp 014's stock-close walk-forward were touched by the DTE bug before relying on either. Believed independent (raw-data derivations, not assess_position consumers) — verify, don't assume.
> 4. Dollar-impact framing throughout this spec ("+$30–60K retention lever" etc.) is **withdrawn**; corrected AAPL retention baseline is 49.1%. Part D (partial overwriting) survives on its own logic; Part B/C survive; expected-$ claims get re-estimated from Part 0.
> 5. Data reality: GOOGL has **5 days** of option OHLCV, AMZN none. "All 6 tickers" anywhere below means the four with full years: AAPL, TMUS, DIS, KKR (KKR low-confidence).
> 6. Take-profit at 75%-captured is the copilot's dominant exit (42–95% of exits) — any exit-rule experiment must treat TP as a first-class arm, not delete it as a side effect.
> 7. ~~Apply `migrations/001_signal_graveyard` first~~ **Done 2026-08-17** — the Exp 019b session created the table; H17–H24 verdicts (failures included) now persist to Supabase.
> 8. **AMZN demotion directive (restricting change — execute in Part 0):** AMZN is live-recommendable today at 5% OTM with tier `untested`, and H24(b) just FAILED it at the *more conservative* 15% (22.9% test loss rate vs 10% gate). Pre-registration discipline forbids *promoting* on a failed test; it does not forbid *restricting* on adverse evidence about a live recommendation. Demote AMZN to `skip`-pending-revalidation. Same logic check for MSFT if it appears anywhere recommendable (20.0% loss rate at 15%).
> 9. **New: Exp 023 / H26 — the IV-rank ≥ 50 gate gets its own trial.** It is live on every ticker; its evidence is Exp 009 (invalid, broken simulator, one un-staggered path), and Exp 019b's control observed it rescuing DIS/KKR while costing AAPL/TMUS. Hypothesis: the gate improves net P&L per ticker on walk-forward cc_sim.py replay vs no-gate and vs a per-ticker gate. Pre-register per-ticker pass/fail before running; a per-ticker mixed verdict deploys per-ticker (one commit each). Runs on owned data; fold into Part 0's run or immediately after.
> 10. **H23 verdict is final and reframes Part D:** overwrite ratio is an income-vs-upside preference dial (overlay moves max drawdown 0.00–1.45pp against 13–49% stock drawdowns — the risk denominator is stock, not overlay). Do not re-run Part D on stress years; present the ratio to Dad as a preference choice with the income/upside tradeoff table, no optimization claim.

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

**Purchase order (REVISED 2026-08-17 — information-per-dollar over cheapest-first, per Exp 019b executor's finding that TMUS carries 44% missing repricing vs AAPL's 2.5%; stop when budget is exhausted):**
1. AAPL option OHLCV **2020** ← pull FIRST. It is the single most information-dense item (cleanest fills + the crash/V-recovery regime); if the budget only covers one thing, it must be this. OHLCV estimates were accurate last time ($4.07 est vs $4.08 actual) — pull OHLCV, check actual charge, THEN pull its definitions (the 2×-miss risk lives in definitions), re-plan with the corrected factor.
2. AAPL option OHLCV **2022** + definitions
3. DIS **2020** then **2022** + definitions (14.3% missing — second-cleanest name)
4. GOOGL option OHLCV **most recent full year** + definitions
5. TMUS stress years — only if budget remains (44% missing repricing caps what any TMUS verdict can claim; say so in the results)
6. MSFT most recent year — only if budget remains

**Blocking prerequisite before ANY pull:** Part 0 (Exp 022) must have re-derived the walk-forward baseline on `cc_sim.py` — including reproducing/replacing `results/012_walk_forward.md`, which predates the as_of clock fix. H21 compares stress years to that baseline; buying data to compare against an unmeasured number is the failure mode.

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
