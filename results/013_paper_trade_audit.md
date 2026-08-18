---
title: "Paper-trade audit: every scored trade on the scorecard is Black-Scholes backfill"
date: 2026-08-18
experiment: 013-audit
status: completed
finding: "The /sell scorecard published '76.4% win rate, +52.6% avg P&L, 339W/105L' as the strategy's record. All 444 scored rows are synthetic trades priced by backfill_paper_trades.py with Black-Scholes off stock history; they carry strategy_params.backfilled = true. Exactly 0 real-price recommendations have ever been scored. The 8 live-chain rows that exist were all written in the last four days and none has reached expiry. Separately, the logger wrote nothing for 144 consecutive days (2026-03-24 -> 2026-08-15). The published statistic measures the pricing model, not the strategy."
---

# Paper-trade audit (deferred Block B item)

**Run:** `python3 scripts/audit_paper_trades.py`
**Source:** production API (`options.imprevista.com/api/paper-trades?detail=true`), 452 rows,
2026-08-18. Reproduce against the DB directly by exporting `SUPABASE_URL` / `SUPABASE_KEY`;
the script prefers the DB and prints which source it used.

## Why this was needed

The scorecard on `/sell` rendered three numbers — win rate, average P&L per trade, and a
W/L record — under the caption *"Every recommendation logged and scored automatically."*
Neither the numbers nor the caption had ever been checked against what is actually in the
table. Two known problems made that untenable:

1. `backfill_paper_trades.py` seeded history by pricing synthetic trades with Black-Scholes
   off stock history. Its own output says so: *"All backfilled trades use BSM pricing (not
   real market prices)."* Those rows are flagged `strategy_params.backfilled = true`.
2. The 2026 logging outage, during which the logger wrote nothing at all.

## What is in the table

| Set | Rows | Scored | Win rate | Avg P&L | Record |
|---|---:|---:|---:|---:|---|
| All rows — *what the scorecard published* | 452 | 444 | 76.4% | +52.61% | 339W / 105L |
| BSM-backfilled (synthetic prices) | 444 | 444 | 76.4% | +52.61% | 339W / 105L |
| **Live-chain (real quoted prices)** | **8** | **0** | — | — | *nothing scored* |

The first two rows are identical because they are the same rows. **Every scored trade in
the system is synthetic.** The published win rate is a property of `bsm_call()` in
`backfill_paper_trades.py` and the volatility it was handed — it is not evidence about
covered calls, about the copilot, or about any recommendation a person could have acted on.

## The outage, in the data

| Boundary | Date |
|---|---|
| Last backfilled row | 2026-03-24 |
| First live-chain row | 2026-08-15 |
| **Gap with zero rows written** | **144 days** |

There is exactly one gap longer than 7 days in the entire history, and it is that one. The
backfill ends where it ends because that is when the backfill script was run; live logging
did not take over. For 144 days the scorecard kept rendering 76.4% from rows whose newest
member was already months old, with a caption asserting that every recommendation was being
logged automatically.

## The 8 real rows

| Logged | Ticker | Strike | Premium | Tier *as logged* | Expiry | Scored |
|---|---|---:|---:|---|---|---|
| 2026-08-15 | AAPL | 350 | 0.43 | conservative | 2026-09-18 | no |
| 2026-08-15 | AMZN | 275 | 4.50 | **untested** | 2026-09-18 | no |
| 2026-08-15 | DIS | 115 | 0.60 | good | 2026-09-18 | no |
| 2026-08-15 | GOOGL | 380 | 2.38 | **good** | 2026-09-18 | no |
| 2026-08-15 | KKR | 130 | 0.90 | **good** | 2026-09-18 | no |
| 2026-08-15 | TMUS | 210 | 0.52 | **good** | 2026-09-18 | no |
| 2026-08-18 | KKR | 125 | 0.50 | probation | 2026-09-18 | no |
| 2026-08-18 | TMUS | 210 | 0.45 | probation | 2026-09-18 | no |

The bolded tiers are pre-correction: on 2026-08-15 the logger still wrote AMZN as
`untested` (it is now `skip`) and GOOGL/KKR/TMUS as `good` (all three are now `probation`).
The 2026-08-18 rows show the corrected tiers, which dates the Python correction to between
those two runs and confirms the logger reads `ticker_strategies.py` directly. The web app
did not — that is the defect this audit sits inside.

Nothing here can be scored before 2026-09-18, and one expiry is not a record.

## What the scorecard may say

Under spec §5, unaudited numbers may not render bare. The audit has now run, and its result
is that the verified set is empty, so the honest rendering is not a smaller number — it is
the absence of one:

- The synthetic record may be shown **only** if labelled as Black-Scholes backfill, with the
  live-chain count next to it. It is history for the pricing model, not a track record.
- No win rate, average P&L, or W/L record may be presented as the strategy's own until
  real-price recommendations have been scored. The first are due **2026-09-18**.
- The caption "Every recommendation logged and scored automatically" is false twice over
  (144-day gap; nothing real scored) and is removed.

## Methodology note that outlives this audit

The scorer measures **hold-to-expiry** outcomes of logged recommendations. The copilot
strategy buys back early — that is the entire point of the copilot. Even once real trades
are scored, this scorecard will not be measuring the strategy the product recommends, and
must keep saying so on its face.
