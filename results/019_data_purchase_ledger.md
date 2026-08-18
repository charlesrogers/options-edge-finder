# Experiment 019 — Databento Purchase Ledger

Assumed opening balance **$125.00**, hard floor **$25.00**.
Coverage probe of $1.32 (2026-08-17) precedes this table.

| # | item | estimate | ACTUAL | rows | MB | cumulative | remaining |
|---|---|---:|---:|---:|---:|---:|---:|
| 1 | AAPL 2020 crash | $27.03 | $27.03 | 863,697 | 14.8 | $28.35 | $71.65 |
| 2 | DIS 2020 crash | $15.71 | $15.71 | 501,981 | 7.5 | $44.06 | $55.94 |
| 3 | GOOGL 2020 crash | $11.07 | $11.07 | 353,634 | 5.6 | $55.12 | $44.88 |
| 4 | TMUS 2020 crash | $1.49 | $1.49 | 47,578 | 0.6 | $56.61 | $43.39 |
| 5 | KKR 2020 crash | $0.48 | $0.48 | 15,182 | 0.2 | $57.09 | $42.91 |
| 6 | AAPL 2020 meltup | $23.92 | $23.92 | 764,416 | 13.6 | $81.01 | $18.99 |
| 7 | TMUS 2022 bear | $5.58 | $5.58 | 178,307 | 2.3 | $86.59 | $13.41 |

**Total spent: $86.59** ($1.32 probe + $85.27 package). Implied balance **$38.41**
against the $25.00 floor. Every ACTUAL equalled its estimate — Databento's
`metadata.get_cost` quotes are deterministic, so no abort trigger (1.3×) fired.

> **ACTUAL is the post-pull re-quote of the identical range**, not a billed-amount
> readback: databento-python v0.73 exposes no billing or balance endpoint.
> **Charles must confirm the portal balance — that is the authority, not this table.**

## §4 Validation

Region measured is the 5–20% OTM / 20–60 DTE **call** band the strategy sells and
buys back. Spot inferred by put-call parity from the option data itself.

| File | Days | Region covered | Region MISSING | Tier |
|---|---:|---:|---:|---|
| AAPL 2020 Feb–Jun | 103 | 80.4% | 19.6% | primary |
| DIS 2020 Feb–Jun | 103 | 79.0% | 21.0% | primary |
| GOOGL 2020 Feb–Jun | 103 | 74.2% | 25.8% | primary |
| AAPL 2020 Jul–Sep | 63 | 80.4% | 19.6% | primary |
| TMUS 2020 Feb–Jun | 102 | 55.6% | 44.4% | **supporting only** |
| TMUS 2022 full | 251 | 49.7% | 50.3% | **supporting only** |
| KKR 2020 Feb–Jun | 103 | **UNMEASURED** | — | **blocked** |

**Crash sanity check PASSES.** AAPL Feb–Jun 2020 shows a −39.2% parity-inferred
drawdown ($367.30 → $223.41). A calm-looking March 2020 would have meant a broken
pull; this is the real event. DIS −41.6%, GOOGL −32.1% corroborate.

AAPL Feb–Jun coverage (80.4%) lands exactly on the AAPL-2025 baseline (80.0%) that
every shipped backtest already runs on. The probe week scored 94.4% because peak
panic drives peak option volume — the full window is the honest number.

### Three caveats that must be carried into H21

1. **KKR 2020 is UNMEASURED, not 0%.** The file holds 4,842 call bars over 103
   days, but KKR 2020 is too thin for put-call parity (median 4 matched strikes per
   expiry; the inference needs ≥10), so spot returned `None` every day and coverage
   computed to zero *by construction*. Re-measure with stock closes as the spot
   source — KKR had no split in 2020, so yfinance is safe for it. **Do not report
   KKR 2020 coverage as 0%.**
2. **AAPL Jul–Sep spans the 4:1 split on 2020-08-31.** Pre-split strikes $75–$1000,
   post-split $19–$250. The apparent −78.8% drawdown is the split, not the market.
   Any backtest crossing that date must handle it or it will read a 75% crash that
   never happened.
3. **`backtest_engine.load_option_data` globs `{ticker}_ohlcv*` and concatenates.**
   AAPL now resolves to 2020 crash + 2020 melt-up + 2020 probe + 2025, and TMUS to
   2020 + 2022 + 2025. **Every existing experiment re-run will silently pick up the
   new years.** Prior results were computed on 2025-only inputs. Either date-filter
   at the call site or make the loader year-aware before re-running anything.

## Durability — three locations, all hash-verified

| Copy | Location | Verified |
|---|---|---|
| 1 | `~/Documents/options-tool/data/databento/raw/` (laptop, gitignored) | 23/23 OK |
| 2 | `root@95.216.205.160:/data/backups/databento/raw/` (mode 600) | 23/23 OK |
| 3 | `~/Library/CloudStorage/Dropbox/Backups/databento/raw/` | 23/23 OK |

Manifest (committed, metadata only): `data/databento_MANIFEST.sha256` — 23 files, 188 MB.
**Restore test passed:** `TMUS_ohlcv_1d_2022.dbn.zst` pulled back from Hetzner,
SHA-256 matched, loaded to 178,307 rows spanning 2022-01-03 → 2022-12-30.

## Stop line

Purchase, validation, and durability are complete. **H21 is NOT started** — it waits
on Exp 022's corrected baselines, per Charles. Nothing further is authorized.
