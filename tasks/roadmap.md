# Options Tool Roadmap — 2026-08

**North star:** Dad runs covered calls on ~$10M of stock through a monitor he can trust with a $400K failure mode, earning $85–125K/yr, with every parameter walk-forward-validated and every hypothesis pre-registered in the graveyard (bettybot model: log → test → store, pass AND fail).

**The edge, stated honestly:** operational, not analytical. (1) Exit discipline — closing early beats waiting at every moneyness/DTE across 145K real observations; (2) ex-div assignment avoidance — the $400K alert; (3) process — pre-registration + walk-forward makes our numbers trustworthy. The income is a ~0.7% yield overlay; no dataset changes that ceiling. Alpha for us = retention, reliability, and capacity — not prediction.

---

## Phase 0 — Reliability (Week 1) `tasks/week1-reliability-spec.md` — **Block A EXECUTED 2026-08-18.** Found FACT-11 (both alert paths read nonexistent DB columns — schema adapter + live-DB contract tests shipped) and FACT-12 (no Pushover/Discord creds in Coolify). Heartbeats with read-back + UNASSESSED markers, market-calendar-aware health (Sunday false alarm replayed → quiet), health 503, secrets off the world-readable cron file (verified through live cron firings), Uptime Kuma authenticated monitor, mutation-tested failure paths. **Blocked on Charles:** merge PR #3, three secrets into /etc/options-copilot.env + Coolify, Cloudflare login for the outer watchdog. **New hard finding:** RLS disabled on 4 position tables with anon key public → dedicated security session required before Dad onboarding (gate added to phase2 runbook).
The monitor slept 4.5 months with green signals. Nothing else matters until silence itself alerts.
Dead-man's switch, daily proof-of-life push, no swallowed writes, cron hygiene + inventory, dual-source ex-div calendar, paper-trade record audit, EMERGENCY fire drill.
**Exit criteria:** killing the monitor cron demonstrably alerts within 45 min; honest track-record numbers exist.

## Phase 1 — Retention research (Week 2) `tasks/week2-research-spec.md` — **EXECUTED 2026-08-17: H17–H20 all FAILED, nothing deployed.** The real finding: a datetime.now() bug in assess_position() invalidated Exps 007–013; corrected retention baseline is 49.1% (AAPL), not 13%; TP-at-75% is the dominant exit; regime swamps exit-rule choice (40–180pp swings between half-years). Production expected_pnl values in ticker_strategies.py are from the broken simulator → Baseline Re-derivation (Exp 022/H25) is now the blocking Part 0 of Phase 3, and all per-ticker $ claims are suspended until it lands.
The biggest dollar lever we own, on data already paid for.
- **Exp 015 / H17** — probability-based buybacks (13% → ≥20% retention target; +$30–60K/yr at scale)
- **Exp 016 / H18** — trend gate (kill the GOOGL-class losses; the safe route to more income)
- **Exp 017 / H19** — EMERGENCY rational-exercise refinement (Natenberg Ch.12; shadow mode only)
- **Exp 018 / H20** — rolling revisit under new triggers (stretch)
**Exit criteria:** each hypothesis has a graveyard verdict; winners deployed one-ticker-per-commit behind walk-forward gates.

## Phase 2 — Dad onboarding (the actual product milestone) `tasks/phase2-onboarding-runbook.md`
- Pushover key wired; holdings + open positions entered; fire drill repeated **with him**.
- Rule card conversation: per-ticker table, IV gate, the two calendar bans, "when the phone says buy back, buy back."
- Honest expectations: audited numbers only (Phase 0 output), income framed as insurance-plus-yield.
- **The collar conversation** (see PDF review below): concentrated low-basis positions + multi-year-high forward rates + elevated vol = historically attractive zero-cost collars. Priced free off current Yahoo chains. This is portfolio advice adjacent to the tool, and plausibly the highest single-decision EV in his whole picture. Deliverable: a one-page per-ticker collar menu (put floor / call cap / net cost) he can discuss with his tax person.
**Exit criteria:** Dad has acted on ≥1 real alert; weekly cadence established.
- **Forward paper engine (Exp 024, H40–H43)** `tasks/paper-trading-engine-spec.md`, `experiments/024_paper_engine/PREREGISTRATION.md` — four pre-registered arms running the production strategy forward against real bid/ask quotes at 15-minute latency, so "our strategy works" eventually has receipts. Milestones are counted from the **first paper trade**, not from the merge: **day 30** integrity only (no strategy verdicts, pre-committed so nobody quotes tiny-sample P&L), **day 90** attribution interim, **day 180** interim verdict. Read the reachability table in §4 of the pre-registration before expecting anything from day 180 — per-ticker floors need 14–58,101 cycles and day 180 produces 2.0–8.2, so day 180 is a point estimate with an honest CI plus the falsification result, not a pass/fail on the strategy. A kill switch tripping alerts Charles and **changes nothing in production**.

## Phase 3 — Capacity & robustness (the $125 Databento credits spend here, not earlier) `tasks/phase3-strategy-spec.md` — **credit-free half EXECUTED 2026-08-17: H22a/H23/H24(b) FAIL, H21/H22/H24(a) blocked on the purchase.** Shipped (PR #2, stacked on PR #1, not yet live): KKR capped at 7 contracts (the strike's median volume is 3/day — the position IS the market), GOOGL demoted to probation tier. H23 verdict is structural and final: overwrite ratio is a preference dial. New: AMZN demotion directive, Exp 023/H26 (the live IV-rank gate finally gets its own trial), purchase order revised to lead with AAPL 2020 (information-per-dollar). Purchase **executed 2026-08-17**: $86.59 → all-5 crash window (Feb–Jun 2020) + AAPL melt-up (Jul–Sep 2020) + TMUS 2022; balance $39.80 (floor $25 intact); three hash-verified backups, restore-tested. **Running H21 remains gated on Exp 022, and Exp 022 is now gated on the loader date-filter fix** (the glob would contaminate the baseline with the stress years — phase3 spec, purchase caveats block).
Credits buy ~5–8 ticker-years incl. definitions — one well-chosen question. Spend AFTER Phase 1 so the stress test validates the NEW buyback rule:
1. **Exp 019** — 2020 + 2022 option OHLCV, AAPL + TMUS (+DIS if budget): crash, V-recovery (the IV-gate-in-backwardation hole), and a full bear on real prices. Pre-registered thresholds; calibrate cost on the cheapest pull first (definitions ran 2× estimate last time); hard stop $120.
2. **GOOGL 1 real year** — its production parameter currently rests on stock-proxy validation only.
3. **MSFT/AMZN expansion** (+$30–40K/yr capacity): start at ultra-conservative 15% OTM validated on stock data; the (now-fixed) daily chain capture builds real option history forward for free; upgrade parameters from our own data in ~6 months. Databento optional here.
4. **Partial-overwrite sizing test (Exp 020)** — from Sinclair's skew/Kelly work: short-call P&L is negatively skewed, and Kelly under negative skew says size below full. Overwriting 50–70% of the 10k shares keeps upside on the remainder, cuts buyback drag, and is the *correct* response to "more income please" (vs. closer strikes, which is the wrong one). Testable on existing data.
**Exit criteria:** strategy has a real-price bear-market verdict; ≥1 new ticker at full validation.

## Phase 4 — Product hardening (only after the above; deliberately unspecced — contents are contingent on Phase 2/3 verdicts, and speccing ahead of validation is the anti-pattern in tasks/lessons.md)
- Weekend-entry preference (Fri open beats Mon — Sinclair/Mack weekend VRP; free tweak).
- Backwardation guard on the IV gate (don't sell the falling knife; wait for term-structure reversion) — informed by Exp 019.
- Collar workflow in the web app if the Phase 2 conversation lands (VISION_SPEC Proposal 2, scoped down to fences only).
- Continue daily chain capture → in ~12 months we own our own multi-regime option dataset and never buy data again.

---

## PDF library review (what's worth mining from `~/Library/.../Capital_Allocation-Quant-Hedging-Valuation`)

**Directly roadmap-relevant (deep-dive during the phase that uses them):**
- **Sinclair — *Volatility Trading*** — the Kelly/sizing and trade-evaluation chapters back Exp 015/020. The companion to Retail Options Trading (already reviewed cover-relevant chapters).
- **Sinclair — *Skewness and the Kelly Criterion*** — the theory behind partial overwriting (Phase 3, Exp 020).
- **Bennett — *Trading Volatility*** — the best practical overwriting reference in print: strike/tenor selection for call overwriting and collar construction. Cross-check our 20–45 DTE choice against his 1–2 month findings during Phase 3; use his collar chapters for the Phase 2 menu.
- **Peters — *Optimal Leverage from Non-Ergodicity*** — the formal argument for the standing constraint: **the tool never recommends leverage or naked short options.** Concentration without leverage survives; the combination is the only unforgivable mistake (see the 2026 SALP liquidation).
- **The fat-tail set** (Cook Pine, Sornette Dragon Kings, Taleb ×3, Mauboussin) — framing for the Phase 2 collar conversation: consequence over probability.
- **Derman — *Illusions of Dynamic Delta Replication*** — why we manage discrete exits instead of delta-hedging. Supports current design; no action.
- **Dawes — *Robust Beauty of Improper Linear Models*** — why simple threshold rules keep beating optimized models here. Cite it when tempted to add ML.

**Not our lane (skip):** technical analysis (Edwards), market profile (CBOT), AIQ manual, GEX/Squeezemetrics (both Sinclair/Mack and Moontower are skeptical of dealer-positioning trading), factor-investing and value papers (equities selection, not options overlay), Thorp papers (historical pleasure reading).

---

## Explicitly NOT building
- Direction prediction at any horizon (tested, dead — H10; base rates make it a coin flip).
- Further OTM% grid searches on the already-mined year (in-sample forever — Sinclair).
- SPX/index straddle pivot (real premium, wrong risk profile for "never get assigned").
- GARCH investment (Sinclair/Mack: priced in since ~2010; our H10 agrees).
- Stochastic-vol surface / Heston / copulas / RL agent (VISION_SPEC Proposals 1/3/4/5) — research toys relative to the JTBD; revisit only if the tool becomes a multi-user product.
- Anything levered, naked, or that a Moontower/data subscription would "solve" ($99 tier has no API; the $6K/yr tier isn't justified by a 6-ticker overlay).
