# Phase 2 — Dad Onboarding Runbook + Collar Menu Spec

**Prerequisite:** Phase 0 complete and demonstrated (dead-man's switch proven, track record audited). Do not onboard against an unproven monitor — a silent monitor converts his vigilance into false confidence, which is worse than no tool.

Most of this phase is Charles-led conversation, not code. The one farm-out build is Part D.

## HARD GATE added 2026-08-18 — RLS before real positions

Block A found RLS disabled on `trades`, `portfolio_holdings`, `paper_trades`, `option_chain_snapshots` — with the anon key shipped to the browser. **Anyone holding the public key can read or WRITE Dad's positions**: inject a fake trade, delete a real one, or blind the monitor. Zero rows today is the only reason this is a finding and not an incident. Blast radius of the fix is 91 tables across every app on the shared Supabase, so it gets its own scoped session with a security review (per global CLAUDE.md: RLS/auth changes trigger one) — never a side effect of another lane. **No real position is entered until RLS is enabled and write paths are service-role-only on those four tables.** This gate sits alongside (not instead of) the Phase 0 exit criteria.

## Part A — Technical onboarding checklist (Charles + 15 min with Dad)

1. Dad installs Pushover ($5 one-time); Charles wires his user key into the monitor env (Coolify prod scope — verify `is_preview=false`, the scope trap from the August outage).
2. Enter holdings at options.imprevista.com/positions (tickers, share counts — 10,000/ticker).
3. Enter every currently open covered call. **Triage before strategy:** anything within ~3% of strike, or with an ex-div inside the option's life while near the strike, gets bought back this week regardless of prior plans.
4. Repeat the EMERGENCY fire drill (`docs/fire-drill.md` from Phase 0) **with Dad's phone as the target.** He must experience the repeating priority-2 alert and acknowledge it once before it ever fires for real.
5. Confirm the daily proof-of-life push arrives on his phone too, and tell him the rule: *if the daily push doesn't arrive, assume the tool is dead and watch manually.*

## Part B — The rule-card conversation

Use only audited numbers (`results/013_paper_trade_audit.md`). The frame that has landed with him before: **insurance that pays you** — the copilot exists to make the MSFT event impossible; the ~$70–85K/yr is the dividend for running it.

- Per-ticker table from `ticker_strategies.py` (strike %, DTE window, expected loss rate, tier).
- The three entry conditions: validated ticker at its researched strike; IV rank ≥ 50 (low-IV months = sell nothing; doing nothing is a position); no earnings or ex-div inside the option's life.
- The exit discipline: never hold to expiry, no stop losses, act on the alert level mechanically. "When the phone says buy back, buy back — don't renegotiate with it."
- Sizing: KKR is liquidity-capped (the position would BE the market at 100 lots); all orders are limit orders worked at mid at his size, never market orders.
- Overwrite ratio (Exp 020 verdict, 2026-08-17): at his scale the overlay moves portfolio drawdown by ≤1.45pp against 13–49% stock drawdowns — the ratio is a pure **income-vs-upside preference dial, not a risk decision**. Present a simple table (50/70/100% → income vs. retained upside per ticker) and let him set the dial. No optimization claim; there isn't one to make.

## Part C — Expectations, stated once and honestly

- Income is a ~0.6–0.8% yield overlay on ~$10M+ of stock. Roughly $70–85K/yr at current validated capacity; Phase 3 expansion targets +$30–40K. Anyone promising covered-call "income" of 5–10% is selling the 3–5% OTM strikes our data shows is the worst zone.
- Premium retention is deliberately low (copilot buys back early); that is the price of zero assignments. The insurance value scales with his size; the income is the bonus.
- The strategy has not yet been validated on a bear market with real prices (Exp 019 pending). Until it is, the honest claim is the Monte Carlo one from Exp 010, labeled as such.

## Part D — Collar menu generator (farm-out-able build)

**Why:** concentrated, low-basis, $10M+ positions + multi-year-high forward rates + elevated vol on big names = zero-cost collars at historically attractive terms (the Moontower/Curnutt thesis; Natenberg Ch. 13 "fences"; the fat-tail PDFs are the framing). This is portfolio-level downside protection — adjacent to the tool, possibly the highest single-decision EV in his picture. Our job is to *price the menu*, not to advise; he discusses it with his tax person (collars on low-basis stock have tax/straddle-rule implications that are explicitly out of our lane — say so on the page).

**Build:** a script (`collar_menu.py`) that, for each held ticker, prices off live Yahoo chains (`yf_proxy`):
- Tenors: ~3 months and ~12 months (nearest listed expiries).
- For put floors at 10% / 15% / 20% OTM: find the call strike that makes the collar zero-cost (interpolate between listed strikes; report the actual nearest-strike net credit/debit — never pretend exact zero exists).
- Output per row: put floor, call cap, net cost, max loss %, max gain %, R:R ratio (rolling net cost into basis, per the Moontower formulation), and the IV of each leg.
- Mid prices with the bid/ask width shown per leg — at 100-lot size the width is the real cost. Flag any leg with absurd width or zero bid.
- Output: markdown table per ticker → one page in the web app or a static doc for the conversation. Refresh on demand, not on a cron (it's a conversation aid, not a monitor).
- No recommendation logic. It's a menu with prices, plus the one-line R:R framing ("risking X% to make Y%").

**Acceptance:** menu generated for all held tickers; spot-check two rows by hand against broker-quoted prices; tax caveat present; reviewed by Charles before Dad sees it.

## Exit criteria for Phase 2

Dad has: received and acknowledged a drill alert, entered real positions, sold ≥ 1 call from a tool recommendation, acted on ≥ 1 real alert, and seen the collar menu. Weekly check-in cadence agreed.
