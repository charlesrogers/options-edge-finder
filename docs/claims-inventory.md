# Claims inventory — options.imprevista.com

Every quantitative or evaluative claim rendered by the web app, the source that is supposed
to support it, and what was done about it. Compiled 2026-08-18 while executing
`tasks/web-overhaul-spec.md`.

The rule this enforces (spec §2.2): **no number without lineage.** A claim that cannot be
traced to a results file and an experiment ID is removed, not kept.

**Status: 0 rows left in FIX-pending or REMOVE-pending state.**

Legend — **KEEP**: traceable and correct as rendered. **FIX**: traceable but rendered
wrongly (stale value, wrong attribution, missing caveat). **REMOVE**: not supportable at
all; deleted rather than restated.

---

## Root cause, stated once

`web/src/lib/strategies.ts` was a hand-maintained duplicate of `ticker_strategies.py` and
froze in March 2026. Four merged PRs corrected the Python and nothing propagated. Separately,
every backtest from Exp 007 to Exp 014 computed days-to-expiry against `datetime.now()`, so
each historical observation was evaluated as if it expired that day; Exp 012's supersede note
records that this "invalidated every backtest from Exp 007 to Exp 014." Most rows below are
one of those two failures.

---

## `/sell` — Sell a Call

| # | Claim as rendered | Source | Verdict | Action taken |
|---|---|---|---|---|
| 1 | AAPL "$351 expected P&L" | `strategies.ts` (fossil) | FIX | Now **$141** from `ticker_strategies.py` via codegen (Exp 022, corrected engine) |
| 2 | AAPL "100% win rate" | `strategies.ts` (fossil) | FIX | Now **91%**. Exp 022 measured 91.7%; 9% of trades lose, worst −$971 |
| 3 | AAPL note "Tiny premium but never loses" | `strategies.ts` (fossil) | REMOVE | Deleted. Directly contradicted by the same experiment |
| 4 | DIS "$822 / 71%" | `strategies.ts` (fossil) | FIX | Now **$267 / 80%** (Exp 022, −68% relative error on the old figure) |
| 5 | TMUS "$447 / 89%", tier **Good** | `strategies.ts` (fossil) | FIX | Now **$151 / 92%**, tier **Probation** (Exp 022: 56% repricing coverage, below the pre-registered 70% floor) |
| 6 | KKR "$386 / 100%", tier **Good** | `strategies.ts` (fossil) | FIX | Now **$316 / 63%**, tier **Probation** (36% coverage; the 100% win rate was a broken-clock artefact) |
| 7 | KKR sized at **100 contracts** on 10,000 shares | no source — `Math.floor(shares/100)` | FIX | Capped at **7** with the reason rendered on the card (Exp 021: the strike trades a median of 3 contracts/day; 100 would be 33× median daily volume) |
| 8 | GOOGL tier **Good** | `strategies.ts` (fossil) | FIX | Now **Probation** — validated on stock closes only (Exp 014); 5 days of real option data exist |
| 9 | AMZN recommendable at **5% OTM** | `strategies.ts` (fossil) | FIX | Now **skip**. Exp 021 failed AMZN at the more conservative 15% OTM (22.9% test loss rate vs a 10% gate) |
| 10 | MSFT rendered with the unknown-ticker default (5% OTM, "untested") | absent from `strategies.ts` entirely | FIX | Now present and **skip**. Exp 021 failed MSFT at 15% OTM (20.0% test loss rate) |
| 11 | "IV-aware entry (Experiment 009: **+204% P&L improvement**)" | Exp 009, broken-clock engine | REMOVE | Deleted. Replaced with the Exp 023 per-ticker result, including that the gate **failed** its trial on TMUS |
| 12 | "Only sell when IV Rank ≥ 50" applied to every ticker | Exp 009 | FIX | Per-ticker now: **DIS ≥ 75** (Exp 023, holdout-confirmed), others ≥ 50 |
| 13 | Expected P&L shown as a bare point estimate | Exp 022 | FIX | Point + chain range (e.g. AAPL `−$776..$352`), and the real-fill-only figure where it disagrees (TMUS −$81, KKR −$88). Codegen **refuses** to emit a live non-zero P&L with no spread |
| 14 | "X% of trades expire worthless" | Exp 022 | FIX | Relabelled "% of **simulated** trades expired worthless" |
| 15 | Scorecard "76.4% win rate / +52.6% avg P&L / 339W-105L" | `paper_trades` table, unaudited | REMOVE | All 444 scored rows are Black-Scholes backfill; zero real-price trades scored. See `results/013_paper_trade_audit.md` |
| 16 | Scorecard "Every recommendation logged and scored automatically" | — | REMOVE | False twice: a 144-day gap with nothing logged, and nothing real ever scored |
| 17 | Scorecard presented as the strategy's record | — | FIX | Now states on its face that it measures **hold-to-expiry** outcomes, which is not how the copilot trades (it buys back early) |
| 18 | Page subtitle "Backtested recommendations… Sorted by expected P&L" | — | KEEP | Accurate; the underlying numbers are now the corrected ones |

## `/how-it-works`

| # | Claim as rendered | Source | Verdict | Action taken |
|---|---|---|---|---|
| 19 | Hero: "**$27,000** in taxes avoided over 3 years — Backtest Result (**Experiment 008**)" | Exp **007**, not 008 — and Exp 007 is inside the DTE-bug blast radius | REMOVE | Withdrawn. There is no corrected tax figure because the experiment has not been re-run. Hero now states the correction itself |
| 20 | Metric "**$27K** Tax Savings" | same as #19 | REMOVE | Card deleted |
| 21 | Metric "**57-100%** Win Rates" | fossil table | FIX | Derived from the generated table, quoted over real-price tickers only (**63-92%**), captioned "simulated, hold-to-expiry (Exp 022)" |
| 22 | Metric "**145K** Observations — real options data" | Exp 006 | KEEP (relabelled) | The 145,099-observation table was **verified clean** of the DTE bug by Exp 022. Sublabel now says what it is: the assignment-probability table |
| 23 | Metric "**7** Tickers Tested — grid searched" | Exp 008 (invalidated) | FIX | Now derived: 8 configured, 5 recommendable, 3 skipped, and a separate card for how many rest on real option prices (4) |
| 24 | "Backtested OTM% and DTE per ticker **from 145K observations**" | misattribution | FIX | The settings come from Exp 014 (walk-forward on stock closes), re-measured on real chains by Exp 022. Corrected |
| 25 | "**Every** recommendation backed by experiment data" | — | FIX | False for GOOGL (stock closes only) and the probation tickers. Replaced with "tickers without real option data are marked, not quietly recommended" |
| 26 | Crash table: "**2020 COVID crash** −34%, −$34,000 stock loss, +$2,800 premium, −$31,200 net" (and 3 more rows) | claimed Exp 010 | REMOVE | Triple failure: Exp 010 is 10,000 Monte Carlo paths with BSM pricing, not a historical replay; its `run.py` imports `assess_position` so it is inside the DTE-bug blast radius; and the dollar figures appear **nowhere** in Exp 010, which reported percentages on a 1-contract position. Section replaced with an explicit statement that we do not have a defensible answer |
| 27 | "Covered calls reduce losses in **every** scenario" | Exp 010 | REMOVE | Deleted with #26 |
| 28 | Methodology: "All data comes from backtests on historical options data (2021-2024) across 7 tickers… Experiment 008 tested every combination…" | Exp 008 (invalidated) | FIX | Rewritten to state what was wrong (the DTE bug), what replaced it (Exp 022 on `cc_sim.py`), what repricing coverage means, and that win rate is hold-to-expiry |
| 29 | Strategy table hid skipped tickers and truncated notes | — | FIX | Every ticker listed, skips sorted last, notes never truncated, chain range and real-fill figure printed under each point estimate |
| 30 | Fine print: "Past performance does not guarantee future results" | — | FIX | Strengthened: states that **no real-price recommendation has been scored yet** and that individual trades lose |

## `/paper-trades`

| # | Claim as rendered | Source | Verdict | Action taken |
|---|---|---|---|---|
| 31 | Scoreboard: 76.4% record, +52.6% avg P&L, 444 scored | `paper_trades`, unaudited | FIX | Banner above the numbers states every scored row is synthetic BSM backfill, with the live-chain count and the date the first real outcome is due |
| 32 | Header "…% win rate" | — | FIX | Relabelled "% expired worthless", plus the hold-to-expiry methodology line |
| 33 | Per-ticker win-rate table | `paper_trades` | KEEP | Accurate as a description of the logged rows, now under the provenance banner |
| 34 | "Patterns Found" loss-rate badges | computed from the same rows | KEEP | Arithmetic over the logged set; inherits the banner's caveat |

## `/positions` (and `/`, which redirects here)

| # | Claim as rendered | Source | Verdict | Action taken |
|---|---|---|---|---|
| 35 | Verdicts (SAFE / WATCH / CLOSE_SOON / CLOSE_NOW / EMERGENCY) | `lib/copilot.ts` — a **TypeScript re-implementation** of the Python alert rules | FIX | Page now reads the verdicts `monitor_positions.py` stored in `position_assessments`. One engine; the screen and the phone cannot disagree |
| 36 | Verdicts rendered with no indication of age | — | FIX | Every verdict carries "as of HH:MM ET"; a red banner fires when the newest assessment is older than 20 minutes during market hours |
| 37 | "All positions are safe — nothing to do today" | derived | FIX | Can no longer be said when any position is UNASSESSED; an unassessed position now produces a red headline instead of being folded into the green one |
| 38 | "P(assign): X%" per position | `copilot.ts` re-derivation | REMOVE | The monitor does not store an assignment probability, and re-deriving one in the browser is the second engine again. Removed rather than recomputed |
| 39 | Positions with no stored verdict | — | FIX | Rendered explicitly as "Not assessed" and sorted to the top, never silently omitted and never assumed safe |

## Site-wide

| # | Claim as rendered | Source | Verdict | Action taken |
|---|---|---|---|---|
| 40 | `<meta description>`: "Never get called away. **Never lose money.** Make money." | — | FIX | False: 9% of AAPL's simulated trades lose, worst −$971. Replaced with a description of what the copilot does |

---

## Noted, not fixed here

1. **No authentication anywhere.** The app has no login and no middleware; `/positions`,
   `/api/holdings` and `/api/positions` serve one household's holdings and open option
   positions to anyone with the URL. No page *claims* the data is private, so this is not a
   false claim — but RLS is explicitly out of scope for this session (spec §8) and this is
   the record that the exposure was seen. **Recommend gating it in its own session.**
2. **A second alerting engine still exists.** `/api/cron/monitor` re-implements the alert
   rules in TypeScript via `lib/copilot.ts`, in parallel with `monitor_positions.py`. The
   display path no longer uses it, but the duplicate remains and can drift. Removing a live
   alerting endpoint is an infra-lane decision, so it is flagged, not deleted.
3. **`docs/dad-pitch.md`** — cross-checked and corrected in this session. Its per-ticker table
   was already current, but six further claims were not: the "386 scored trades, 81% win rate"
   record (synthetic), "every recommendation logged and scored automatically" (144-day gap),
   the Exp 010 bear-market figures, the Exp 007 "$27,000 in simulated tax events / 5x ROI"
   answer, "14 experiments each pre-registered" (pre-registration began at Exp 021), and the
   "never get called away again" guarantee. All corrected or withdrawn.

## Candidates that would RAISE a claim — Charles's call, not shipped

Per spec §2.4 these are listed rather than applied:

1. **AAPL, DIS, TMUS and KKR all measure HIGHER on the fully-corrected engine** than the
   values currently published (`ticker_strategies.py` records this at the AAPL entry:
   "DIS/TMUS/KKR all measure HIGHER on the fixed engine; raising them would be a loosening
   change and is withheld"). Publishing the higher numbers needs sign-off.
2. **The IV-rank gate demonstrably costs money on TMUS** — Exp 023 found it blocks 109
   entries averaging +$48 and keeps the losers. Removing the gate for TMUS would be a
   loosening change and needs its own pre-registered experiment.
3. **AAPL's gate is unsettled**: Exp 023 found it wins per entry and loses per year (it
   removes 132 entries averaging +$17). No change made.

## Added post-overhaul (2026-08-19)
| Claim | Page | Source | Verdict |
|---|---|---|---|
| "Expected P&L / yr per contract" + "≈ $X/yr at your N contracts (liquidity-capped)" | /sell | Exp 022 per-contract figures × ticker_strategies max_contracts (Exp 021 cap) | KEEP — unit ambiguity fix, PR #14 |
| "real-fill basis ≈ $X/yr" at size | /sell | Exp 022 real-fill split | KEEP — PR #14 |
| "N% of simulated cycles ended profitable… buyback cost more than premium… stock P&L not included" | /sell | cc_sim win definition (pnl_per_share > 0, production copilot policy) | KEEP — replaces wrong "expired worthless", PR #15 |
| "Win rate … under the production copilot policy (early buybacks included)" | /how-it-works | experiments/022 run.py line 191: policy=production copilot | KEEP — replaces wrong hold-to-expiry description, this PR |
