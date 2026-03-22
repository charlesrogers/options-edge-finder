# Implementation Plan: Learn/Test/Trade Pipeline

## Phase 0: CLV Foundation (This Sprint)

The single biggest unlock. After this phase, we can answer: "Do we have real edge?"

### Task 0.1: Add CLV Columns to Predictions Table

**File:** `db.py`
**Location:** Migration block (lines 144-161)

Add 2 new columns to `predictions` table:
```sql
ALTER TABLE predictions ADD COLUMN iv_at_scoring REAL;
ALTER TABLE predictions ADD COLUMN clv_realized REAL;
```

We already have `atm_iv` (IV at entry) and `outcome_rv` (RV over holding period). We need:
- `iv_at_scoring` — the IV on the outcome date (fetched from `iv_snapshots`)
- `clv_realized` — computed as `(atm_iv - outcome_rv) / atm_iv`

We can also compute `clv_market = (atm_iv - iv_at_scoring) / atm_iv` on the fly from those two columns without storing it separately.

**Changes:**
1. Add column migration in `_ensure_tables()` (after line 161)
2. Add a helper function `get_iv_on_date(ticker, date)` that queries `iv_snapshots` for the closest snapshot

**Estimated:** ~30 lines added to db.py

---

### Task 0.2: Compute CLV in score_pending_predictions()

**File:** `db.py`
**Location:** `score_pending_predictions()` (lines 357-467)

After computing `outcome_rv` (line 413) and before the database update (line 437):

```python
# Fetch IV at scoring date from iv_snapshots
iv_at_scoring = get_iv_on_date(ticker, outcome_date_str)

# Compute CLV
clv_realized = None
if atm_iv and outcome_rv and atm_iv > 0:
    clv_realized = (atm_iv - outcome_rv) / atm_iv
```

Add `iv_at_scoring` and `clv_realized` to the update dict (line 437-459).

**Edge case:** `iv_snapshots` may not have data for the exact outcome date (weekends, holidays, gaps). The helper function should find the closest prior date within 5 days.

**Estimated:** ~25 lines added to db.py

---

### Task 0.3: Backfill CLV for Already-Scored Predictions

**File:** New one-time script `backfill_clv.py` (or add to db.py as utility)

For all predictions where `scored=1` AND `clv_realized IS NULL`:
1. Fetch the prediction's `atm_iv` and `outcome_rv`
2. Compute `clv_realized = (atm_iv - outcome_rv) / atm_iv`
3. Try to fetch `iv_at_scoring` from iv_snapshots for that ticker+outcome_date
4. Update the prediction row

This is a one-time migration. Can run via GitHub Actions or locally.

**Estimated:** ~60 lines standalone script

---

### Task 0.4: Add CLV to get_prediction_scorecard()

**File:** `db.py`
**Location:** `get_prediction_scorecard()` (lines 470-642)

Add CLV summary stats to the returned dict. Insert after the P&L summary block (after line 546):

```python
# CLV Summary
clv_data = scored_df[scored_df['clv_realized'].notna()]['clv_realized']
if len(clv_data) > 0:
    scorecard['clv_summary'] = {
        'avg_clv': clv_data.mean(),
        'median_clv': clv_data.median(),
        'std_clv': clv_data.std(),
        'pct_positive_clv': (clv_data > 0).mean() * 100,
        'count': len(clv_data),
    }

    # CLV by signal
    clv_by_signal = {}
    for sig in ['GREEN', 'YELLOW', 'RED']:
        sig_clv = scored_df[scored_df['signal'] == sig]['clv_realized'].dropna()
        if len(sig_clv) > 0:
            clv_by_signal[sig] = {
                'avg_clv': sig_clv.mean(),
                'count': len(sig_clv),
                'pct_positive': (sig_clv > 0).mean() * 100,
            }
    scorecard['clv_by_signal'] = clv_by_signal

    # Rolling CLV (30-prediction window)
    if len(clv_data) >= 10:
        rolling_clv = clv_data.rolling(min(30, len(clv_data))).mean()
        scorecard['rolling_clv'] = rolling_clv.dropna().tolist()
```

**Estimated:** ~40 lines added to db.py

---

### Task 0.5: Display CLV in Streamlit Scorecard

**File:** `streamlit_app.py`
**Location:** Scorecard tab (lines 2051-2669)

Add three CLV sections:

**A. CLV Summary Row** (insert after P&L Analysis, around line 2171)

```python
# --- CLV Analysis ---
if scorecard.get('clv_summary'):
    st.markdown("### Closing Line Value (CLV)")
    st.caption("CLV measures whether we sell IV that subsequently proves overpriced. "
               "Positive CLV = we consistently sold at higher IV than realized vol. "
               "This is the primary edge metric — lower variance than P&L.")
    clv = scorecard['clv_summary']
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Avg CLV", f"{clv['avg_clv']:.1%}",
              help="Average (IV_entry - RV_holding) / IV_entry")
    c2.metric("Median CLV", f"{clv['median_clv']:.1%}")
    c3.metric("% Positive CLV", f"{clv['pct_positive_clv']:.0f}%",
              help="Pct of trades where IV exceeded realized vol")
    c4.metric("CLV Observations", f"{clv['count']}")

    # Interpretation
    if clv['avg_clv'] > 0.02:
        st.success(f"Strong positive CLV ({clv['avg_clv']:.1%}). "
                   "You are consistently selling overpriced volatility.")
    elif clv['avg_clv'] > 0:
        st.info(f"Positive CLV ({clv['avg_clv']:.1%}). Edge exists but thin.")
    else:
        st.error(f"Negative CLV ({clv['avg_clv']:.1%}). "
                 "You are selling UNDERPRICED volatility. Reassess strategy.")
```

**B. CLV by Signal** (insert in Signal Separation section, around line 2430)

```python
# CLV by signal type
if scorecard.get('clv_by_signal'):
    st.markdown("#### CLV by Signal")
    for sig in ['GREEN', 'YELLOW', 'RED']:
        if sig in scorecard['clv_by_signal']:
            data = scorecard['clv_by_signal'][sig]
            st.write(f"**{sig}**: Avg CLV {data['avg_clv']:.1%} "
                     f"({data['pct_positive']:.0f}% positive, n={data['count']})")
```

**C. Rolling CLV Chart** (insert in Performance Over Time, around line 2554)

Add CLV as a third line on the existing rolling performance chart, or as a separate small chart below it.

**Estimated:** ~80 lines added to streamlit_app.py

---

### Task 0.6: Create signal_graveyard Table

**File:** `db.py`
**Location:** `_ensure_tables()` (after predictions table creation)

```python
# Signal Graveyard
if sb:
    # Table created via Supabase dashboard or migration
    pass
else:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS signal_graveyard (
            signal_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            tier INTEGER,
            hypothesis TEXT,
            pre_registered_date TEXT NOT NULL,
            tested_date TEXT,
            status TEXT DEFAULT 'untested',
            layer_reached INTEGER DEFAULT 0,
            best_sharpe REAL,
            best_clv REAL,
            n_trades INTEGER,
            failure_reason TEXT,
            notes TEXT
        )
    """)
```

Add helper functions:
- `register_hypothesis(signal_id, name, tier, hypothesis)` — pre-register before testing
- `update_hypothesis_result(signal_id, status, layer_reached, sharpe, clv, n_trades, failure_reason)` — record outcome
- `get_graveyard()` — return all entries as DataFrame

**Estimated:** ~60 lines added to db.py

---

### Task 0.7: Pre-Register H01-H04

**File:** One-time script or manual via `register_hypothesis()` calls

Register the 4 core hypotheses BEFORE any testing:

```python
register_hypothesis("H01", "VRP Predicts Seller Wins", tier=1,
    hypothesis="When IV > GARCH RV by >2 vol points, selling premium produces positive CLV")
register_hypothesis("H02", "GARCH Beats Naive RV20", tier=1,
    hypothesis="GJR-GARCH produces lower QLIKE loss than RV20 for 20-day forecasting")
register_hypothesis("H03", "Signal Discrimination", tier=1,
    hypothesis="GREEN CLV > YELLOW CLV > RED CLV (monotonic ordering)")
register_hypothesis("H04", "VRP Magnitude Proportional to Edge", tier=1,
    hypothesis="Higher VRP produces proportionally higher CLV (Spearman rho > 0.15)")
```

**Estimated:** ~20 lines

---

## Phase 0 Summary

| Task | File | Lines Added | Depends On |
|------|------|-------------|------------|
| 0.1: CLV columns | db.py | ~30 | Nothing |
| 0.2: CLV in scoring | db.py | ~25 | 0.1 |
| 0.3: Backfill CLV | backfill_clv.py | ~60 | 0.1 |
| 0.4: CLV in scorecard | db.py | ~40 | 0.1 |
| 0.5: CLV in UI | streamlit_app.py | ~80 | 0.4 |
| 0.6: Graveyard table | db.py | ~60 | Nothing |
| 0.7: Pre-register H01-H04 | script | ~20 | 0.6 |
| **TOTAL** | | **~315 lines** | |

**Execution order:** 0.1 → 0.2 → 0.3 (parallel with 0.4) → 0.5 → 0.6 → 0.7

**Can run 0.1+0.6 in parallel** (no dependencies between CLV columns and graveyard table).

---

## Phase 1: The Testing Gate (Month 1)

### Task 1.1: Create signal_registry.py (~200 lines)

Pre-registration enforcement and hypothesis management.

**Functions:**
- `pre_register(signal_id, name, tier, hypothesis, filter_desc, trade_direction, primary_metric, pass_thresholds, fail_criteria)` — writes to graveyard with status='untested'
- `get_registered(status=None)` — list hypotheses by status
- `mark_testing(signal_id)` — update status to 'testing'
- `mark_result(signal_id, passed, layer, metrics, failure_reason=None)` — record outcome
- `get_graveyard_count()` — total signals ever tested (for DSR)
- `validate_pre_registration(signal_id)` — verify hypothesis was registered BEFORE data was queried

---

### Task 1.2: Create clv_tracker.py (~150 lines)

CLV computation and CLV-based metrics.

**Functions:**
- `compute_clv_realized(iv_entry, rv_holding)` — basic CLV
- `compute_clv_market(iv_entry, iv_at_scoring)` — market CLV
- `clv_by_signal(predictions_df)` — CLV breakdown by GREEN/YELLOW/RED
- `clv_by_regime(predictions_df)` — CLV breakdown by regime
- `rolling_clv(predictions_df, window=30)` — rolling CLV time series
- `clv_vs_vrp_correlation(predictions_df)` — Spearman rho of VRP vs CLV (for H04)
- `clv_curve(predictions_df, feature, bins=10)` — CLV as function of any feature (for H05-H07)

---

### Task 1.3: Create testing_gate.py (~600 lines)

The 10-layer validation pipeline (Layers 1-7 first, Layers 8-10 in Phase 4).

**Functions:**
- `run_layer_1_data_validation(predictions_df)` — no lookahead, timestamps valid
- `run_layer_2_frozen_flagship(flagship_commit_hash)` — verify flagship hasn't changed
- `run_layer_3_walk_forward(ticker_data, signal_func, expanding=True)` — upgraded walk-forward
- `run_layer_4_standalone(predictions_df, signal_filter)` — CLV > 1.5%, Sharpe > 0.8, etc.
- `run_layer_5_incremental(predictions_df, flagship_df)` — Jensen's alpha, CLV uplift
- `run_layer_6_orthogonality(new_signal, existing_signals)` — regression-based independence
- `run_layer_7_stability(predictions_df, signal_filter)` — stability matrix across tickers/regimes/time
- `run_full_gate(predictions_df, signal_id, layers=7)` — orchestrator that runs 1-N and records results
- `deflated_sharpe_ratio(sharpe, n_trials, n_obs, skew, kurtosis)` — DSR calculation

---

### Task 1.4: Create discipline.py (~200 lines)

Pass rate tracking and "when NOT to trade" enforcement.

**Functions:**
- `check_trade_filters(vrp, iv_rank, term_label, regime, vix, fomc_days, earnings_days, dte, portfolio_vega, portfolio_vega_limit)` — returns (should_trade: bool, reasons: list)
- `track_pass_rate(date, green_count, traded_count)` — log to pass_rate_history
- `get_pass_rate_summary(days=30)` — rolling pass rate stats
- `log_override(prediction_id, direction, reason)` — record human override
- `get_override_performance()` — CLV of overrides vs model decisions

---

### Task 1.5: Run H01-H04 Through Gate

Using existing scored predictions data:
1. Pull all scored predictions from Supabase
2. Compute CLV for each (Task 0.3 already did this)
3. Run Layer 4 standalone test for H01 (VRP > 2 → positive CLV?)
4. Run Layer 4 for H03 (GREEN CLV > YELLOW CLV > RED CLV?)
5. Run Layer 4 for H04 (VRP magnitude correlates with CLV?)
6. Record results in signal_graveyard

**This is the moment of truth**: do we have real edge by CLV standards?

---

### Task 1.6: Modify batch_sampler.py for Discipline

Add pass/trade decision recording:
- After computing signal, run `check_trade_filters()`
- Log the decision (trade/pass) and reasons to a new column or table
- Tag each prediction with Tier 4 features: `day_of_week`, `trading_day_of_month`

**Estimated:** ~30 lines added

---

## Phase 1 Summary

| Task | File | Lines | Depends On |
|------|------|-------|------------|
| 1.1: signal_registry.py | New file | ~200 | Phase 0 complete |
| 1.2: clv_tracker.py | New file | ~150 | Phase 0 complete |
| 1.3: testing_gate.py | New file | ~600 | 1.1, 1.2 |
| 1.4: discipline.py | New file | ~200 | Phase 0 complete |
| 1.5: Run H01-H04 | Script/notebook | ~100 | 1.3 |
| 1.6: batch_sampler discipline | batch_sampler.py | ~30 | 1.4 |
| **TOTAL** | | **~1,280 lines** | |

---

## Phase 2: First Signals Through the Gate (Months 2-3)

### Task 2.1: Pre-register H05-H08 (edge sizing hypotheses)
### Task 2.2: Pre-register H09-H16 (model adjustment hypotheses)
### Task 2.3: Build stability matrix across tickers and regimes
### Task 2.4: Test H05 (optimal VRP threshold) — plot CLV-vs-VRP curve
### Task 2.5: Test H06 (IV Rank threshold) — plot CLV-vs-IV-Rank curve
### Task 2.6: Test H07 (IV compression as entry signal)
### Task 2.7: Test H12 (regime filter value)
### Task 2.8: Test H13 (earnings exclusion)
### Task 2.9: Test H14 (FOMC exclusion)
### Task 2.10: Upgrade eval_backtest.py to expanding window with CLV as primary metric
### Task 2.11: Add Deflated Sharpe with full graveyard count

**Deliverable:** Signal graveyard has 15+ entries. Know which components drive CLV, which are redundant.

---

## Phase 3: New Signals (Months 3-6)

### Task 3.1: Implement SABR calibration per expiration (Proposal 1A from VISION_SPEC.md)
### Task 3.2: Pre-register H08 (vol surface VRP > ATM VRP)
### Task 3.3: Test H08 through Layers 4-7
### Task 3.4: Implement Bayesian logistic regression (Proposal 3A)
### Task 3.5: Pre-register H09 (Bayesian > static thresholds)
### Task 3.6: Test H09 through Layers 4-7
### Task 3.7: Pre-register and test H24 (VRP/IV ratio from Sinclair)
### Task 3.8: Pre-register and test H25 (straddle vs strangle vs iron condor)
### Task 3.9: Winning signals enter Stage 0 (shadow trading)

**Deliverable:** New signals validated or killed. Shadow trading begins.

---

## Phase 4: Staged Deployment (Months 6-12)

### Task 4.1: Create deployment.py with 5-stage state machine
### Task 4.2: Create monitoring.py with 4-layer stack
### Task 4.3: Add monitoring GitHub Action (daily, after scoring)
### Task 4.4: Implement Layer 8 (production simulation with adverse selection haircut)
### Task 4.5: Begin Stage 1 (10% capital) for first passing signal
### Task 4.6: Begin portfolio construction (equal weight)

**Deliverable:** Real capital following validated, monitored signals.

---

## Phase 5: Advanced (Year 2+)

### Task 5.1: Multi-leg optimizer (Proposal 2) through gate
### Task 5.2: Copula model (Proposal 4) for portfolio optimization
### Task 5.3: Test H26 (autocorrelation/Hurst as vol pricing signal)
### Task 5.4: Test H27 (straddle breakout entropy)
### Task 5.5: Test H28 (vanna crush timing)
### Task 5.6: RL agent (Proposal 5) development begins

**Deliverable:** Multiple independent signals, copula-optimized portfolio, RL agent in shadow mode.

---

## Verification Plan

### After Phase 0:
- [ ] Run `score_pending_predictions()` — new predictions get CLV columns populated
- [ ] Run `backfill_clv.py` — existing scored predictions get CLV backfilled
- [ ] Load Streamlit app — scorecard tab shows CLV summary, CLV by signal, rolling CLV chart
- [ ] Query `signal_graveyard` table — H01-H04 are pre-registered with status='untested'
- [ ] CLV interpretation messages appear (strong/thin/negative)
- [ ] Verify: `clv_realized` values are in reasonable range (typically -0.5 to +0.5)

### After Phase 1:
- [ ] Run full gate on H01 — produces pass/fail with all Layer 4 metrics
- [ ] Signal graveyard shows H01-H04 with status='passed' or 'failed' and layer_reached
- [ ] `discipline.py` check_trade_filters correctly blocks trades when VRP < 2, VIX > 45, etc.
- [ ] batch_sampler records pass/trade decisions for each ticker
- [ ] DSR calculation uses graveyard count (not hardcoded)

### After Phase 2:
- [ ] Stability matrix renders as table in Streamlit (tickers x metrics)
- [ ] CLV-vs-VRP curve is plotted — shows breakpoint (or monotonic increase)
- [ ] 15+ entries in signal_graveyard
- [ ] Walk-forward uses expanding window, CLV is primary metric in output
