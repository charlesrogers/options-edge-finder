# Handoff Spec — Databento Stress-Year Option Data

**Status:** probe executed and PASSED. Purchase and storage decisions are open — both need Charles.
**Date:** 2026-08-17
**Cost incurred so far:** $1.32 (coverage probe, already spent)
**Cost pending approval:** $55.77 – $143.68 (see §4)

---

## 0. Provenance warning — read this first

The spec this executes was pasted into the session **truncated mid-sentence**. Items
1–4 of its five-item pre-mortem were recovered; **item 4 is cut off mid-clause and
item 5 was never received.** Everything below item 4 in §2 is either measured fresh
today or explicitly labelled as an open question. Nothing was invented to fill the gap.

The one number the truncated spec did carry — "$79" — turns out to be **AAPL alone
for full-year 2020** ($78.70 measured), not a basket price. If the original intent
was "all tradeable tickers for 2020," the real number is $143.68. This is the single
biggest thing to re-confirm with Charles.

---

## 1. What this data is for

**The question:** during a crash, what does it actually cost to buy back a covered
call while IV explodes? Calls get *more expensive to repurchase even while moving
further OTM*. That is the failure mode the strategy has never been tested against.

**Why synthetic prices cannot answer it:** Experiment 001 priced options with
Black-Scholes using RV×1.2 as an IV proxy, produced a 100% win rate / Sortino 5.5,
was built into the app, and was invalidated by Exp 002 on real prices. BSM proxies
get the IV-explosion term wrong — which is precisely the term under test here.

**Why it must be bought rather than captured:** the daily chain-capture crons build
option history *forward*. 2020 cannot be captured forward, ever, at any price.
Stress years are the only item on any data wishlist with no free acquisition path.
That asymmetry is the whole justification for the purchase.

---

## 2. Pre-mortem (recovered — items 1–4 only)

1. **"Next week we'll want different data."** Every alternative candidate has
   another path: GOOGL/MSFT/AMZN real history accrues free via daily chain capture
   (the probation tier); EOD quote data for illiquid strikes is ~$25/ticker-year from
   a separate vendor and buying it later does not invalidate this purchase. Stress
   years are the only scarce item. **Verdict: survives.**
2. **"The 15% OTM strikes we sell might be gappy in 2020."** Real risk — Databento
   OPRA is *trade-based*, so a strike that never traded has no bar.
   **Mitigation: the coverage probe in §3. This was the spec's key addition.**
3. **"Wouldn't stock paths suffice?"** No — see §1. The unknown is buyback cost
   during an IV explosion, which only real option prices measure.
4. **"TMUS at 44% missing produces a garbage verdict for $6."** Contained by
   pre-registering TMUS as *supporting evidence only, never a…* **[TRUNCATED — the
   sentence ends here in the source. Reconstructed intent: never a gate or a
   decision-maker on its own. CONFIRM WITH CHARLES.]**
5. **[NOT RECEIVED — lost to truncation.]**

---

## 3. Coverage probe — EXECUTED, PASSED

Script: `experiments/databento_coverage_probe.py`
Pulled: AAPL, OPRA.PILLAR, ohlcv-1d, 2020-03-16 → 2020-03-20 (4 trading days, 0.8 MB, **$1.32**)

### Method

Measures the strikes the strategy *actually sells* — calls at +7% to +15% OTM
(`ticker_strategies.py` spans 0.07 for DIS to 0.15 for AAPL/TMUS/KKR), 20–60 DTE —
on two metrics:

- **Entry coverage** — is there a listed call within 2.5% of spot of the target
  strike, at each target DTE? Without one, no trade opens.
- **Reprice coverage** — for a contract that traded on day D, does it also have a
  bar on D+1, D+2…? **This is the metric that matters**: buyback cost is measured on
  repricing bars, not the entry bar.

**Spot is inferred by put-call parity from the option data itself (S ≈ C − P + K),
not from yfinance.** AAPL split 4:1 in Aug 2020, and yfinance prices are
split-adjusted — a yfinance "spot" of ~$65 compared against pre-split ~$260 strikes
would have made every coverage number garbage. Parity-inferred spot came out at
$243.68–$252.52 for the 2020 week, which is correct pre-split AAPL.

### Pass bar (derived, with one labelled judgment call)

2020 coverage must be **no worse than the same metric on AAPL 2025** — the data every
currently-shipped backtest already runs on. Slack of **10pp is an explicit arbitrary
tolerance** for the probe being 4 days vs 251, not a computed value.

### Result

| Metric | AAPL 2020 (crash) | AAPL 2025 (baseline) | Bar | Verdict |
|---|---|---|---|---|
| Entry coverage | **94.4%** (306/324) | 80.0% (324/405) | ≥70.0% | **PASS** |
| Reprice coverage | **96.7%** (264/273) | 100.0% (240/240) | ≥90.0% | **PASS** |

2020 crash-week coverage is *better* than 2025 on entry and effectively equal on
reprice. Mechanism: a panic drives enormous option volume, so more strikes trade.
The gappiness risk that motivated the probe does not materialize for AAPL.

### What the probe does NOT establish

- **AAPL only.** TMUS (44% missing at 15% OTM in 2025) and KKR (64%) were not
  probed. Their 2020 coverage is unknown and could differ in either direction.
- **4 days, one week.** Peak-panic week is the *best* case for volume. A quiet
  stretch of 2020 (say September) would plausibly be gappier.
- **Reprice measured within a 4-day window**, not across a real 20–45 day hold.

---

## 4. Purchase options — real quotes, nothing bought

Measured 2026-08-17 via `experiments/databento_price_scopes.py` (free metadata API).
OPRA.PILLAR, `ohlcv-1d`, `stype_in=parent`. OPRA history goes back to 2013-04-01.

| Scope | Cost | Rows |
|---|---|---|
| AAPL 2020 full year (**the "$79"**) | $78.70 | 2.51M |
| **All 5 tickers, 2020 crash only (Feb 1 – Jun 30)** | **$55.77** | 1.78M |
| All 5 tickers, 2020 full year | $143.68 | 4.59M |
| All 5 tickers, 2022 bear full year | $154.87 | 4.95M |
| 2020 + 2022 full | $298.55 | 9.54M |

Per-ticker, full-year 2020: AAPL $78.70 · DIS $32.90 · GOOGL $27.10 · TMUS $3.98 · KKR $1.00

**Recommendation: the $55.77 crash-only basket.** It costs *less than AAPL alone for
the full year*, covers all five tradeable tickers, and spans the actual stress event
(Feb peak → March crash → June recovery). Full-year 2020 mostly buys quiet months at
AAPL's high per-day rate. GOOGL — the ticker with the real loss problem — is included
for $11.07 in this window versus $27.10 for the year.

**2022 is a genuinely different failure mode** (slow grind, not a gap) and is worth
considering separately, but it is not what the probe validated and should be its own
decision.

---

## 5. Storage — "store forever"

### Current state: ONE copy, and it is fragile

The existing ~$122 purchase (146 MB, 16 files) exists in exactly one place:
`/Users/charlesrogers/Documents/options-tool/data/databento/raw/`
It is **gitignored** (`.gitignore` line: `data/databento`), so it is not in the repo,
not on GitHub, and not backed up anywhere. A laptop failure destroys $122 of
irreplaceable historical data — irreplaceable in the literal sense that re-buying is
the *only* recovery path, and the 2020 window can never be re-captured by any cron.

SHA-256 checksums for all 16 files were computed this session (see §7 for where to
put the manifest).

### Findings on destinations

- **Hetzner box (95.216.205.160):** 150G disk, 105G used, **40G free**. 146 MB is
  0.1% of the disk — not a meaningful risk to the documented "disk fills up and
  crashes Supabase" failure mode.
- **Supabase Storage:** the `supabase-storage` container is running, but
  `http://db.imprevista.com/storage/v1/bucket` returns 404 — as does `/rest/v1/`.
  Kong is not routing those paths from outside. **Using Supabase Storage requires
  fixing that routing first; it is not a drop-in destination.**
- **Cloudflare R2:** free tier is 10 GB storage with free egress, and Charles already
  runs Cloudflare Workers (`yf_proxy.py`). This is the natural off-box copy at $0,
  but it needs an R2 bucket + API token that do not exist yet.

### Recommended plan (3-2-1, all free)

1. **Copy 1 — laptop** (exists today).
2. **Copy 2 — Hetzner**, `rsync` to a plain directory outside Docker, e.g.
   `/data/archive/databento/`. No new service, no new credentials, 146 MB.
3. **Copy 3 — Cloudflare R2**, free tier, off-box and off-continent from the laptop.
4. **Manifest** — commit `data/databento/MANIFEST.sha256` **to the repo** (the
   checksums are tiny text; only the `.dbn.zst` payloads are gitignored). This makes
   silent corruption detectable and lets any future copy be verified.
5. **Restore test** — pull one file back from copy 3 and verify its checksum. An
   untested backup is not a backup.

**None of this is done yet** — steps 2–5 are the next session's first task, pending
Charles's pick of destination.

---

## 6. Pre-registration

Per the global rule, the stress backtest is a falsifiable bet and must be
pre-registered with the growth cockpit **before** it runs — not after.

- Ticker confidence tiers must be set at registration time, from the 2025
  missing-price rates already measured: AAPL/DIS = primary evidence;
  **TMUS (44% missing at 15% OTM) and KKR (64%) = supporting evidence only, never a
  gate on their own** (the recovered-but-truncated pre-mortem item 4).
- `MARKETING_BOT_API_KEY` was **not** found in this project's environment
  (`.env` holds only `EODHD_API_TOKEN` and `DATABENTO_API_KEY`). Key distribution
  across projects is a known gap — this must be resolved before registration, not
  skipped silently.

---

## 7. Open decisions for Charles

1. **Purchase scope?** Recommend the **$55.77** all-5-tickers crash window over the
   $78.70 AAPL-only year. Needs explicit money approval either way.
2. **Was "$79" meant to be AAPL-only, or was it a mis-estimate of the basket?**
3. **Buy 2022 as well** ($154.87), or hold?
4. **Storage destination** — Hetzner rsync (free, no new creds) and/or R2 (free, new
   bucket + token needed)? Fixing Supabase Storage routing is a third option but is
   real infra work.
5. **Pre-mortem item 5** — lost to truncation. Does it still matter?

---

## 8. Artifacts produced this session

| Path | What |
|---|---|
| `/Users/charlesrogers/.claude/worktrees/options-tool/s-0817-1634/experiments/databento_price_scopes.py` | Free cost/row quotes for any scope. Spends $0. |
| `/Users/charlesrogers/.claude/worktrees/options-tool/s-0817-1634/experiments/databento_coverage_probe.py` | The purchase gate. `--no-pull` re-analyses the cached file for free. |
| `/Users/charlesrogers/Documents/options-tool/data/databento/raw/AAPL_ohlcv_1d_2020probe.dbn.zst` | The probe data (0.8 MB, $1.32). **Currently one copy only.** |
| `/Users/charlesrogers/.claude/worktrees/options-tool/s-0817-1634/tasks/databento-stress-years-handoff.md` | This document. |
