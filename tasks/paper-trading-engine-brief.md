# Brief: The Forward-Validation Paper-Trading Engine

**From:** Charles (via planning session s-0815-1613) · **To:** Fable, to turn into a full spec · **Date:** 2026-08-20
**One sentence:** Build a paper-trading engine that runs our ACTUAL strategy forward in time against REAL quotes captured at the moments decisions happen, so that in 3–6 months we know — not believe — whether this strategy makes money.

## Why now, and why the current tracker doesn't answer the question

Everything validated so far is backward-looking, and this project has caught its own backtests lying three times (clock bug invalidated Exps 007–014; fabricated IV rank; carried-forward fills flipping TMUS/KKR from +$15K to −$8K). The existing paper tracker doesn't test the strategy at all: 444 of 452 rows are synthetic BSM backfill, and the scorer measures **hold-to-expiry**, while the real strategy's dominant exit is the copilot's take-profit at 75% captured. Nobody on earth currently runs our actual rule set forward against actual markets. That is the missing leg.

## The questions the engine must answer (pre-registered before it goes live)

1. **Does the full strategy net positive per ticker after real friction?** Entry gate (IV rank, per-ticker thresholds incl. DIS ≥75) → strike/DTE selection → copilot exits (TP-75%, CLOSE triggers, ex-div rule) → conservative fills. Option-leg P&L, stock excluded, at Dad's size with liquidity caps applied (KKR = 7 contracts).
2. **What is real premium retention?** The number that has swung 13%→49% depending on which bug we'd found that week.
3. **What do the copilot's exits actually cost?** Every buyback priced at the real ask at decision time — the crash-regime buyback cost is our biggest untested number.
4. **Is the IV gate worth anything forward?** (Exp 023 said: per-ticker, and it FAILS on TMUS.)
5. **Slippage/fill realism:** paper fills must be executable-conservative — SELL at bid, BUY BACK at ask, never mid — with the spread width logged as a first-class cost.

## The design idea that makes this decisive: parallel arms

Don't paper-trade one strategy — paper-trade **pre-registered control arms simultaneously** on the same tickers/days: (A) full strategy (production rules, single source of truth), (B) hold-to-expiry (no copilot), (C) no-IV-gate, (D) anything else worth isolating. Every arm sees identical market data. The differences between arms are the value of each component, measured forward, with no way to cherry-pick after the fact. This is the bettybot discipline applied to live markets: hypotheses in the graveyard, thresholds immutable, failures kept.

## Data collection (the part to get exactly right)

- **Capture quotes at DECISION moments, not on a daily schedule.** At entry evaluation (daily), at every 15-min monitor tick for open paper positions, and at each exit trigger: full bid/ask/last/volume/OI/IV for the relevant contracts. A quote captured at 19:50 UTC cannot price a decision made at 14:22.
- **Human-latency realism:** when an alert fires, capture the quote at fire time AND ~15 min later; the paper fill uses the later one (Dad is not an HFT).
- **Persistence discipline (all hard-learned):** read-back-verified writes, no silent Nones (log + count every missing quote), heartbeats for the collector itself with calendar-aware freshness, engine commit SHA on every record, schema contract tests against live Supabase.
- **Single engine authority:** the paper engine consumes the SAME `assess_position()` verdicts production uses — it must never grow a third reimplementation of the alert logic (we are still paying down engine #2).

## Success criteria (Fable: make these immutable in the spec)

- Pre-registered per-ticker and per-arm pass/fail thresholds BEFORE the first paper trade, in the signal graveyard.
- Sample-size honesty: state the minimum cycles per ticker for any verdict (cycles complete in days-to-weeks thanks to TP exits, so evidence accrues fast — but state the math, don't vibe it).
- Report retention and P&L as ranges across time windows; regime dominates (half-year swings −78%→+93% are on record).
- Milestone reviews at 30/90/180 days with pre-committed decisions ("if arm A trails arm B by X after N cycles, we conclude Y").

## Non-goals / guardrails

No real orders, ever — this engine cannot touch a broker. No loosening of production rules based on early paper results (walk-forward + one-variable-per-commit still applies). No new alert engine. No unbounded collection jobs on the prod box (memory limits, cron hygiene, failure alerts — every scheduled job alerts on failure or it's already dead). Costs ~$0: yf_proxy quotes + Supabase storage.

## What exists to build on

`position_monitor.py` (the authority) · `signal_registry.py` (graveyard) · daily chain capture + iv sampler crons · `monitor_heartbeats`/`position_assessments` tables · the 15-min chains · `ticker_strategies.py` (generated, single source) · `experiments/cc_sim.py` (the corrected simulator — useful as the arms' shared accounting core) · lessons: `tasks/lessons.md` — the spec should cite the specific ones it guards against.

**The bar for the spec:** when this engine has run for six months, the sentence "our strategy works" or "our strategy doesn't work" must be defensible in front of a 30-year Goldman veteran, with the receipts in a table he can audit.
