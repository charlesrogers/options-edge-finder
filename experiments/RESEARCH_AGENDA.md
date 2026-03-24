# Research Agenda — Options Edge Finder

## What We Know (Validated)

1. **VRP is real.** IV > RV 82% of the time, avg 3.5 vol points. (H01 PASSED, 7,339 trades, 6 years)
2. **GREEN signal works.** GREEN RVRP 40.6% > YELLOW 19.1% > RED 13.7%. (H03 PASSED on backtest, marginal on live)
3. **VRP is the only signal that matters.** Bayesian model: IV Rank, term structure, regime all have zero coefficients. (H10 finding)
4. **Take-profit exits generate real profits.** 161 TP trades made +$5,670 on real Databento prices. (Exp 002)
5. **Liquidity determines viability.** AAPL (6% missing data) = profitable. KKR (71% missing) = catastrophic. (Exp 002)

## What We Know Fails

1. **Put spreads on illiquid names.** Bid-ask friction + missing repricing data = certain loss. (Exp 002: H35 FAILED)
2. **Holding to DTE floor.** 23 DTE floor exits lost $10,195 — 2x total TP profits. (Exp 002)
3. **The long put in spreads costs too much.** Buying overpriced protection on every trade erodes edge. (Sinclair Ch 10)
4. **Small credits don't survive friction.** Avg credit $128 minus 26% friction = $95 net. Not enough to offset one bad trade.

## The Core Tension

The VRP edge is ~$35 per trade after friction (TP exits). But non-TP exits lose ~$200-443 each. Need >85% TP hit rate to be profitable. AAPL achieves 92.5%. Nothing else does.

## Research Priorities (Ordered by Expected Impact)

### Priority 1: AAPL-Only Strategy Validation
**Experiment 003** (ready to run)
- AAPL put spreads: 40 trades, Sharpe 1.5, already profitable in Exp 002
- Also test: AAPL cash-secured puts (no long put cost)
- Also test: higher VRP threshold (only trade when edge is extreme)
- Data: already have 1yr Databento AAPL. Cost: $0.
- **Why first:** Cheapest to test, highest probability of success, directly tradeable by Dad.

### Priority 2: Ultra-Liquid Names Only (SPY/QQQ/AAPL/MSFT)
**Experiment 004** (needs SPY/QQQ data)
- Hypothesis: the strategy works on ANY ultra-liquid name (bid-ask < 3%)
- Test on SPY, QQQ, MSFT, AAPL — the 4 most liquid US equity option markets
- If all 4 work: the strategy is "sell put spreads on mega-liquid names when GREEN"
- Data needed: SPY/QQQ/MSFT Databento data (~$50-80 each for 1yr). Need new Databento account or BSM proxy.
- **Why second:** Expands universe from 1 ticker to 4, massive increase in trade count.

### Priority 3: Wider Spreads / Larger Credits
**Experiment 005** (can run on existing data)
- Hypothesis: $20-30 wide spreads on AAPL collect enough credit to absorb friction
- A $20-wide spread might collect $3-4 in credit vs $1.50 on $10-wide
- Friction is relatively smaller on larger credits
- Also test: further OTM (7-8% instead of 5%) for higher win rate
- Data: already have. Cost: $0.
- **Why third:** Could fix the economics without changing the strategy structure.

### Priority 4: Cash-Secured Puts (Drop the Long Put)
**Experiment 006** (can run on existing data)
- Hypothesis: selling naked/cash-secured puts eliminates the long-put friction
- The long put costs $40-60 per trade — removing it doubles net credit
- Risk: unlimited downside (well, down to zero). But with AAPL, assignment = buying shares Dad already likes at a discount
- Requires Dad to accept potential assignment
- Data: already have. Cost: $0.
- **Why fourth:** Changes the risk profile significantly. Dad originally said "prefer not to buy shares." But might be necessary if spreads can't work.

### Priority 5: Longer DTE (45-60 Days)
**Experiment 007** (may need more data)
- Hypothesis: 45-60 DTE options have smoother theta decay, giving TP more time to trigger
- Current: 20-30 DTE → TP triggers in ~5 days or not at all
- 45-60 DTE → more calendar days for theta to work, less gamma acceleration
- Lower gamma = smaller losses when stock moves against you
- Data: may need options with longer expiry dates — check if Databento data covers them.
- **Why fifth:** Solves a different part of the problem (DTE floor losses) but needs validation.

### Priority 6: Index VRP Harvesting (Sinclair's Actual Recommendation)
**Experiment 008** (needs index option data)
- Hypothesis: SPX/SPY straddle selling is the real VRP harvest per Sinclair
- This is what the BOOK actually recommends — not put spreads on individual stocks
- SPX has European-style options (no early assignment risk)
- Most liquid options in the world (tighter than even AAPL)
- Risk: unlimited on straddle, but Sinclair addresses this with catastrophe hedging
- Data: need SPX option data. Expensive on Databento.
- **Why sixth:** This is probably the "right" answer but it's the biggest departure from Dad's current approach.

### Priority 7: Dynamic Position Sizing
**Experiment 009** (no new data needed)
- Hypothesis: sizing based on VRP magnitude (not fixed) improves returns
- When VRP > 8: trade 3 contracts. VRP 4-8: trade 2. VRP 2-4: trade 1.
- Concentrates capital in highest-edge trades
- **Why seventh:** Optimization on top of a working strategy — need the strategy to work first.

## Experiments NOT Worth Running

- **Any strategy on KKR options** — 71% missing data, 2 contracts/day volume. Not tradeable.
- **Any strategy on TMUS options** — 52% missing data. Not reliably tradeable.
- **Hold-to-expiry strategies** — DTE floor exits lose $443 avg. Expiry is death.
- **Stop-loss optimization** — Exp 001 showed all stop losses cause whipsaw. Don't revisit.

## Decision Tree

```
Run Experiment 003 (AAPL only)
  │
  ├── PASSES → Run Experiment 005 (wider spreads on AAPL)
  │              ├── PASSES → Run Experiment 004 (expand to SPY/QQQ/MSFT)
  │              │              ├── PASSES → DEPLOY (paper trade → real money)
  │              │              └── FAILS → AAPL only is viable, deploy single-ticker
  │              └── FAILS → Run Experiment 006 (cash-secured puts, no spread)
  │                           ├── PASSES → DEPLOY (with assignment risk accepted)
  │                           └── FAILS → Run Experiment 008 (index straddles)
  │
  └── FAILS → The put spread structure doesn't work, even on AAPL
               → Run Experiment 006 (CSP) or Experiment 008 (index straddles)
               → If BOTH fail → VRP harvesting via options is not viable
                                for Dad's constraints. Consider alternatives.
```

## Current Status

| Experiment | Status | Result |
|---|---|---|
| 001: Exit strategy (synthetic) | Complete | 25% TP optimal but data was fake |
| 002: Put spreads (real prices) | Complete | FAILED overall, AAPL-only profitable |
| 003: AAPL only | Pre-registered | Ready to run ($0) |
| 004: Ultra-liquid names | Planned | Needs SPY/QQQ data |
| 005: Wider spreads | Planned | Can run on existing data |
| 006: Cash-secured puts | Planned | Can run on existing data |
| 007: Longer DTE | Planned | May need data |
| 008: Index straddles | Planned | Needs SPX data |
| 009: Dynamic sizing | Planned | No data needed |
