# Collar menu

Generated 2026-08-18 04:58 UTC from live Yahoo chains via `yf_proxy`. Risk-free rate 4.50%, sized at 100 contracts (10,000 shares) per ticker.

**This is a menu with prices. It is not a recommendation.** No row here is picked, ranked, or endorsed — the point is to see what the market is actually charging for downside protection at each floor, so the conversation happens against real numbers.

> **Tax caveat — out of our lane.** Per the Phase 2 spec: he discusses it with his tax person (collars on low-basis stock have tax/straddle-rule implications that are explicitly out of our lane — say so on the page). Nothing on this page accounts for tax. Do not act on any row until the tax person has signed off on it.

**How to read it**

- **Net / share** — put mid minus call mid. `db` = debit (you pay), `cr` = credit (you receive). Exact zero-cost does not exist on a listed chain; the *Zero-cost K\** column is where zero would sit if strikes were continuous, and the *Call cap* column is the nearest strike you can actually trade, with its actual net cost.
- **Max loss / max gain / R:R** — net cost rolled into the basis. Effective basis = spot + net; max loss = (put strike − basis) / basis; max gain = (call strike − basis) / basis. Dividends received over the tenor sit on top of both and are not included — each ticker's yield is stated in its header.
- **IV** — solved from the mid quoted in the same row (Black-Scholes-Merton, continuous dividend yield), not read off Yahoo's `impliedVolatility` field, which returns solver garbage outside trading hours.
- **Flags** — `no-bid` / `no-ask` mean there is no two-sided market on that leg. `wide` / `absurd-width` / `thin OI` / `stale` are drawn against arbitrary starting thresholds (width > 20% and > 50% of mid, OI < 100, last trade > 3d ago) — they are eye-catchers to tune, not derived limits. The raw bid, ask and width are always shown so the flag never hides the number.
- **⚠️ on a net cost** means at least one leg had no two-sided quote and the price fell back to last trade. Indicative only.

---

## AAPL — Apple Inc.

Dividend yield 0.35% · ex-div date on file 2026-08-10 (Yahoo reports the most recent one, not always the next) · next earnings 2026-10-29 · sized at 100 contracts (10,000 shares)

### ~3 month tenor

Expiry **2026-11-20** (95 DTE, target 91) · spot **$305.59** · two-sided quotes on 3/139 chain legs (2%)

> ⚠️ **Quotes are mostly dead on this chain.** Prices below fall back to last trade and are INDICATIVE ONLY — do not read them as tradeable. Re-run during regular trading hours.

| Floor | Put strike | Call cap | Zero-cost K* (interp) | Net / share | Net @ size | Max loss | Max gain | R:R | Put IV | Call IV |
|---|---|---|---|---|---|---|---|---|---|---|
| 10% OTM | $275.00 (10.0% OTM) | $345.00 (12.9% OTM) | $343.83 | $0.27 db ⚠️ | $2,700 db | -10.1% | 12.8% | 1.27× | 28.2% | 25.6% |
| 15% OTM | $260.00 (14.9% OTM) | $360.00 (17.8% OTM) | $360.78 | $0.08 cr ⚠️ | $800 cr | -14.9% | 17.8% | 1.20× | 29.5% | 26.1% |
| 20% OTM | $245.00 (19.8% OTM) | $375.00 (22.7% OTM) | $375.47 | $0.03 cr ⚠️ | $300 cr | -19.8% | 22.7% | 1.15× | 31.8% | 26.5% |

- **10% floor** — risking 10.1% to make 12.8%, $2,700 db to put on at 100 contracts.
- **15% floor** — risking 14.9% to make 17.8%, $800 cr to put on at 100 contracts.
- **20% floor** — risking 19.8% to make 22.7%, $300 cr to put on at 100 contracts.

**Execution reality** — at this size the width is the cost.

| Floor | Leg | Contract | Bid | Ask | Mid | Width | Width % of mid | Cost to cross @ size | OI | Vol | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 10% | Put (buy) | `AAPL261120P00275000` | $0.00 | $0.00 | $4.92 *(last)* | — | — | — | 0 | 147 | no-bid, no-ask, thin OI 0 |
| 10% | Call (sell) | `AAPL261120C00345000` | $0.00 | $0.00 | $4.65 *(last)* | — | — | — | 0 | 501 | no-bid, no-ask, thin OI 0 |
| 15% | Put (buy) | `AAPL261120P00260000` | $0.00 | $0.00 | $2.65 *(last)* | — | — | — | 0 | 59 | no-bid, no-ask, thin OI 0 |
| 15% | Call (sell) | `AAPL261120C00360000` | $0.00 | $0.00 | $2.73 *(last)* | — | — | — | 0 | 124 | no-bid, no-ask, thin OI 0 |
| 20% | Put (buy) | `AAPL261120P00245000` | $0.00 | $0.00 | $1.51 *(last)* | — | — | — | 0 | 243 | no-bid, no-ask, thin OI 0 |
| 20% | Call (sell) | `AAPL261120C00375000` | $0.00 | $0.00 | $1.54 *(last)* | — | — | — | 0 | 66 | no-bid, no-ask, thin OI 0 |

### ~12 month tenor

Expiry **2027-09-17** (396 DTE, target 365) · spot **$305.59** · two-sided quotes on 0/147 chain legs (0%)

> ⚠️ **Quotes are mostly dead on this chain.** Prices below fall back to last trade and are INDICATIVE ONLY — do not read them as tradeable. Re-run during regular trading hours.

| Floor | Put strike | Call cap | Zero-cost K* (interp) | Net / share | Net @ size | Max loss | Max gain | R:R | Put IV | Call IV |
|---|---|---|---|---|---|---|---|---|---|---|
| 10% OTM | $275.00 (10.0% OTM) | $370.00 (21.1% OTM) | $369.76 | $0.11 db ⚠️ | $1,100 db | -10.0% | 21.0% | 2.09× | 29.8% | 26.9% |
| 15% OTM | $260.00 (14.9% OTM) | $390.00 (27.6% OTM) | $389.44 | $0.13 db ⚠️ | $1,300 db | -15.0% | 27.6% | 1.84× | 30.0% | 26.7% |
| 20% OTM | $245.00 (19.8% OTM) | $410.00 (34.2% OTM) | $412.55 | $0.28 cr ⚠️ | $2,800 cr | -19.8% | 34.3% | 1.74× | 30.7% | 26.9% |

- **10% floor** — risking 10.0% to make 21.0%, $1,100 db to put on at 100 contracts.
- **15% floor** — risking 15.0% to make 27.6%, $1,300 db to put on at 100 contracts.
- **20% floor** — risking 19.8% to make 34.3%, $2,800 cr to put on at 100 contracts.

**Execution reality** — at this size the width is the cost.

| Floor | Leg | Contract | Bid | Ask | Mid | Width | Width % of mid | Cost to cross @ size | OI | Vol | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 10% | Put (buy) | `AAPL270917P00275000` | $0.00 | $0.00 | $17.60 *(last)* | — | — | — | 0 | 23 | no-bid, no-ask, thin OI 0 |
| 10% | Call (sell) | `AAPL270917C00370000` | $0.00 | $0.00 | $17.49 *(last)* | — | — | — | 0 | 41 | no-bid, no-ask, thin OI 0 |
| 15% | Put (buy) | `AAPL270917P00260000` | $0.00 | $0.00 | $13.03 *(last)* | — | — | — | 0 | 9 | no-bid, no-ask, thin OI 0 |
| 15% | Call (sell) | `AAPL270917C00390000` | $0.00 | $0.00 | $12.90 *(last)* | — | — | — | 0 | 29 | no-bid, no-ask, thin OI 0 |
| 20% | Put (buy) | `AAPL270917P00245000` | $0.00 | $0.00 | $9.62 *(last)* | — | — | — | 0 | 5 | no-bid, no-ask, thin OI 0 |
| 20% | Call (sell) | `AAPL270917C00410000` | $0.00 | $0.00 | $9.90 *(last)* | — | — | — | 0 | 35 | no-bid, no-ask, thin OI 0 |

---

## TMUS — T-Mobile US, Inc.

Dividend yield 2.23% · ex-div date on file 2026-08-28 (Yahoo reports the most recent one, not always the next) · next earnings 2026-10-22 · sized at 100 contracts (10,000 shares)

### ~3 month tenor

Expiry **2026-11-20** (95 DTE, target 91) · spot **$180.12** · two-sided quotes on 2/49 chain legs (4%)

> ⚠️ **Quotes are mostly dead on this chain.** Prices below fall back to last trade and are INDICATIVE ONLY — do not read them as tradeable. Re-run during regular trading hours.

| Floor | Put strike | Call cap | Zero-cost K* (interp) | Net / share | Net @ size | Max loss | Max gain | R:R | Put IV | Call IV |
|---|---|---|---|---|---|---|---|---|---|---|
| 10% OTM | $160.00 (11.2% OTM) | $200.00 (11.0% OTM) | $204.90 | $0.98 cr ⚠️ | $9,800 cr | -10.7% | 11.6% | 1.09× | 34.0% | 31.7% |
| 15% OTM | $155.00 (13.9% OTM) | $210.00 (16.6% OTM) | $212.80 | $0.33 cr ⚠️ | $3,300 cr | -13.8% | 16.8% | 1.22× | 33.2% | 31.6% |
| 20% OTM | $145.00 (19.5% OTM) | $220.00 (22.1% OTM) | $215.34 | $0.55 db ⚠️ | $5,500 db | -19.7% | 21.8% | 1.10× | 40.7% | 32.0% |

- **10% floor** — risking 10.7% to make 11.6%, $9,800 cr to put on at 100 contracts.
- **15% floor** — risking 13.8% to make 16.8%, $3,300 cr to put on at 100 contracts.
- **20% floor** — risking 19.7% to make 21.8%, $5,500 db to put on at 100 contracts.

**Execution reality** — at this size the width is the cost.

| Floor | Leg | Contract | Bid | Ask | Mid | Width | Width % of mid | Cost to cross @ size | OI | Vol | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 10% | Put (buy) | `TMUS261120P00160000` | $0.00 | $0.00 | $4.05 *(last)* | — | — | — | 0 | 6 | no-bid, no-ask, thin OI 0 |
| 10% | Call (sell) | `TMUS261120C00200000` | $0.00 | $0.00 | $5.03 *(last)* | — | — | — | 0 | 1 | no-bid, no-ask, thin OI 0 |
| 15% | Put (buy) | `TMUS261120P00155000` | $0.00 | $0.00 | $2.70 *(last)* | — | — | — | 0 | 10 | no-bid, no-ask, thin OI 0 |
| 15% | Call (sell) | `TMUS261120C00210000` | $0.00 | $0.00 | $3.03 *(last)* | — | — | — | 0 | 26 | no-bid, no-ask, thin OI 0 |
| 20% | Put (buy) | `TMUS261120P00145000` | $0.00 | $0.00 | $2.40 *(last)* | — | — | — | 0 | 1 | no-bid, no-ask, thin OI 0, stale 10d |
| 20% | Call (sell) | `TMUS261120C00220000` | $0.00 | $0.00 | $1.85 *(last)* | — | — | — | 0 | 6 | no-bid, no-ask, thin OI 0 |

### ~12 month tenor

Expiry **2027-06-17** (304 DTE, target 365) · spot **$180.12** · two-sided quotes on 4/57 chain legs (7%)

> ⚠️ **Quotes are mostly dead on this chain.** Prices below fall back to last trade and are INDICATIVE ONLY — do not read them as tradeable. Re-run during regular trading hours.

| Floor | Put strike | Call cap | Zero-cost K* (interp) | Net / share | Net @ size | Max loss | Max gain | R:R | Put IV | Call IV |
|---|---|---|---|---|---|---|---|---|---|---|
| 10% OTM | $160.00 (11.2% OTM) | $210.00 (16.6% OTM) | $206.66 | $1.53 db ⚠️ | $15,300 db | -11.9% | 15.6% | 1.31× | 36.6% | 30.9% |
| 15% OTM | $155.00 (13.9% OTM) | $220.00 (22.1% OTM) | $223.49 | $0.60 cr ⚠️ | $6,000 cr | -13.7% | 22.5% | 1.65× | 31.9% | 31.3% |
| 20% OTM | $145.00 (19.5% OTM) | $230.00 (27.7% OTM) | $232.13 | $0.39 cr ⚠️ | $3,900 cr | -19.3% | 28.0% | 1.45× | 35.0% | 31.7% |

- **10% floor** — risking 11.9% to make 15.6%, $15,300 db to put on at 100 contracts.
- **15% floor** — risking 13.7% to make 22.5%, $6,000 cr to put on at 100 contracts.
- **20% floor** — risking 19.3% to make 28.0%, $3,900 cr to put on at 100 contracts.

**Execution reality** — at this size the width is the cost.

| Floor | Leg | Contract | Bid | Ask | Mid | Width | Width % of mid | Cost to cross @ size | OI | Vol | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 10% | Put (buy) | `TMUS270617P00160000` | $0.00 | $0.00 | $12.43 *(last)* | — | — | — | 0 | 1 | no-bid, no-ask, thin OI 0, stale 18d |
| 10% | Call (sell) | `TMUS270617C00210000` | $0.00 | $0.00 | $10.90 *(last)* | — | — | — | 0 | 23 | no-bid, no-ask, thin OI 0, stale 13d |
| 15% | Put (buy) | `TMUS270617P00155000` | $0.00 | $0.00 | $8.20 *(last)* | — | — | — | 0 | 3 | no-bid, no-ask, thin OI 0, stale 32d |
| 15% | Call (sell) | `TMUS270617C00220000` | $0.00 | $0.00 | $8.80 *(last)* | — | — | — | 0 | 1 | no-bid, no-ask, thin OI 0 |
| 20% | Put (buy) | `TMUS270617P00145000` | $0.00 | $0.00 | $6.69 *(last)* | — | — | — | 0 | 1 | no-bid, no-ask, thin OI 0 |
| 20% | Call (sell) | `TMUS270617C00230000` | $0.00 | $0.00 | $7.08 *(last)* | — | — | — | 0 | 2 | no-bid, no-ask, thin OI 0, stale 6d |

---

## KKR — KKR & Co. Inc.

Dividend yield 0.68% · ex-div date on file 2026-08-10 (Yahoo reports the most recent one, not always the next) · next earnings 2026-11-05 · sized at 100 contracts (10,000 shares)

### ~3 month tenor

Expiry **2026-11-20** (95 DTE, target 91) · spot **$108.83** · two-sided quotes on 0/19 chain legs (0%)

> ⚠️ **Quotes are mostly dead on this chain.** Prices below fall back to last trade and are INDICATIVE ONLY — do not read them as tradeable. Re-run during regular trading hours.

| Floor | Put strike | Call cap | Zero-cost K* (interp) | Net / share | Net @ size | Max loss | Max gain | R:R | Put IV | Call IV |
|---|---|---|---|---|---|---|---|---|---|---|
| 10% OTM | $97.50 (10.4% OTM) | $125.00 (14.9% OTM) | $125.56 | $0.10 cr ⚠️ | $1,000 cr | -10.3% | 15.0% | 1.45× | 38.4% | 38.0% |
| 15% OTM | $95.00 (12.7% OTM) | $125.00 (14.9% OTM) | $125.56 | $0.10 cr ⚠️ | $1,000 cr | -12.6% | 15.0% | 1.18× | 42.7% | 38.0% |
| 20% OTM | $85.00 (21.9% OTM) | $140.00 (28.6% OTM) | $142.54 | $0.10 cr ⚠️ | $1,000 cr | -21.8% | 28.8% | 1.32× | 43.1% | 39.2% |

- **10% floor** — risking 10.3% to make 15.0%, $1,000 cr to put on at 100 contracts.
- **15% floor** — risking 12.6% to make 15.0%, $1,000 cr to put on at 100 contracts.
- **20% floor** — risking 21.8% to make 28.8%, $1,000 cr to put on at 100 contracts.

**Execution reality** — at this size the width is the cost.

| Floor | Leg | Contract | Bid | Ask | Mid | Width | Width % of mid | Cost to cross @ size | OI | Vol | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 10% | Put (buy) | `KKR261120P00097500` | $0.00 | $0.00 | $3.30 *(last)* | — | — | — | 0 | 3 | no-bid, no-ask, thin OI 0 |
| 10% | Call (sell) | `KKR261120C00125000` | $0.00 | $0.00 | $3.40 *(last)* | — | — | — | 0 | 202 | no-bid, no-ask, thin OI 0 |
| 15% | Put (buy) | `KKR261120P00095000` | $0.00 | $0.00 | $3.30 *(last)* | — | — | — | 0 | 18 | no-bid, no-ask, thin OI 0 |
| 15% | Call (sell) | `KKR261120C00125000` | $0.00 | $0.00 | $3.40 *(last)* | — | — | — | 0 | 202 | no-bid, no-ask, thin OI 0 |
| 20% | Put (buy) | `KKR261120P00085000` | $0.00 | $0.00 | $1.25 *(last)* | — | — | — | 0 | 18 | no-bid, no-ask, thin OI 0 |
| 20% | Call (sell) | `KKR261120C00140000` | $0.00 | $0.00 | $1.35 *(last)* | — | — | — | 0 | 1 | no-bid, no-ask, thin OI 0 |

### ~12 month tenor

Expiry **2027-06-17** (304 DTE, target 365) · spot **$108.83** · two-sided quotes on 10/70 chain legs (14%)

> ⚠️ **Quotes are mostly dead on this chain.** Prices below fall back to last trade and are INDICATIVE ONLY — do not read them as tradeable. Re-run during regular trading hours.

| Floor | Put strike | Call cap | Zero-cost K* (interp) | Net / share | Net @ size | Max loss | Max gain | R:R | Put IV | Call IV |
|---|---|---|---|---|---|---|---|---|---|---|
| 10% OTM | $97.50 (10.4% OTM) | $140.00 (28.6% OTM) | $138.67 | $0.98 db ⚠️ | $9,800 db | -11.2% | 27.5% | 2.45× | 39.2% | 39.9% |
| 15% OTM | $92.50 (15.0% OTM) | $145.00 (33.2% OTM) | $145.57 | $0.06 cr ⚠️ | $600 cr | -15.0% | 33.3% | 2.23× | 39.4% | 40.6% |
| 20% OTM | $87.50 (19.6% OTM) | $155.00 (42.4% OTM) | $157.10 | $0.65 cr ⚠️ | $6,500 cr | -19.1% | 43.3% | 2.26× | 42.0% | 44.6% |

- **10% floor** — risking 11.2% to make 27.5%, $9,800 db to put on at 100 contracts.
- **15% floor** — risking 15.0% to make 33.3%, $600 cr to put on at 100 contracts.
- **20% floor** — risking 19.1% to make 43.3%, $6,500 cr to put on at 100 contracts.

**Execution reality** — at this size the width is the cost.

| Floor | Leg | Contract | Bid | Ask | Mid | Width | Width % of mid | Cost to cross @ size | OI | Vol | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 10% | Put (buy) | `KKR270617P00097500` | $0.00 | $0.00 | $8.30 *(last)* | — | — | — | 0 | 2 | no-bid, no-ask, thin OI 0, stale 4d |
| 10% | Call (sell) | `KKR270617C00140000` | $0.00 | $0.00 | $7.32 *(last)* | — | — | — | 0 | 7 | no-bid, no-ask, thin OI 0 |
| 15% | Put (buy) | `KKR270617P00092500` | $0.00 | $0.00 | $6.50 *(last)* | — | — | — | 0 | 1 | no-bid, no-ask, thin OI 0 |
| 15% | Call (sell) | `KKR270617C00145000` | $0.00 | $0.00 | $6.56 *(last)* | — | — | — | 0 | 1 | no-bid, no-ask, thin OI 0 |
| 20% | Put (buy) | `KKR270617P00087500` | $0.00 | $0.00 | $5.60 *(last)* | — | — | — | 0 | 1 | no-bid, no-ask, thin OI 0 |
| 20% | Call (sell) | `KKR270617C00155000` | $0.00 | $0.00 | $6.25 *(last)* | — | — | — | 0 | 3 | no-bid, no-ask, thin OI 0, stale 4d |

---

## DIS — Walt Disney Company (The)

Dividend yield 1.40% · ex-div date on file 2026-06-30 (Yahoo reports the most recent one, not always the next) · next earnings 2026-11-12 · sized at 100 contracts (10,000 shares)

### ~3 month tenor

Expiry **2026-11-20** (95 DTE, target 91) · spot **$103.50** · two-sided quotes on 4/43 chain legs (9%)

> ⚠️ **Quotes are mostly dead on this chain.** Prices below fall back to last trade and are INDICATIVE ONLY — do not read them as tradeable. Re-run during regular trading hours.

| Floor | Put strike | Call cap | Zero-cost K* (interp) | Net / share | Net @ size | Max loss | Max gain | R:R | Put IV | Call IV |
|---|---|---|---|---|---|---|---|---|---|---|
| 10% OTM | $95.00 (8.2% OTM) | $115.00 (11.1% OTM) | $117.18 | $0.45 cr ⚠️ | $4,500 cr | -7.8% | 11.6% | 1.48× | 27.3% | 29.3% |
| 15% OTM | $90.00 (13.0% OTM) | $125.00 (20.8% OTM) | $122.71 | $0.27 db ⚠️ | $2,700 db | -13.3% | 20.5% | 1.54× | 28.7% | 28.9% |
| 20% OTM | $85.00 (17.9% OTM) | $135.00 (30.4% OTM) | $133.50 | $0.09 db ⚠️ | $900 db | -17.9% | 30.3% | 1.69× | 29.3% | 31.7% |

- **10% floor** — risking 7.8% to make 11.6%, $4,500 cr to put on at 100 contracts.
- **15% floor** — risking 13.3% to make 20.5%, $2,700 db to put on at 100 contracts.
- **20% floor** — risking 17.9% to make 30.3%, $900 db to put on at 100 contracts.

**Execution reality** — at this size the width is the cost.

| Floor | Leg | Contract | Bid | Ask | Mid | Width | Width % of mid | Cost to cross @ size | OI | Vol | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 10% | Put (buy) | `DIS261120P00095000` | $0.00 | $0.00 | $2.05 *(last)* | — | — | — | 0 | 36 | no-bid, no-ask, thin OI 0 |
| 10% | Call (sell) | `DIS261120C00115000` | $0.00 | $0.00 | $2.50 *(last)* | — | — | — | 0 | 189 | no-bid, no-ask, thin OI 0 |
| 15% | Put (buy) | `DIS261120P00090000` | $0.00 | $0.00 | $1.15 *(last)* | — | — | — | 0 | 471 | no-bid, no-ask, thin OI 0 |
| 15% | Call (sell) | `DIS261120C00125000` | $0.00 | $0.00 | $0.88 *(last)* | — | — | — | 0 | 257 | no-bid, no-ask, thin OI 0 |
| 20% | Put (buy) | `DIS261120P00085000` | $0.00 | $0.00 | $0.54 *(last)* | — | — | — | 0 | 1 | no-bid, no-ask, thin OI 0 |
| 20% | Call (sell) | `DIS261120C00135000` | $0.00 | $0.00 | $0.45 *(last)* | — | — | — | 0 | 22 | no-bid, no-ask, thin OI 0 |

### ~12 month tenor

Expiry **2027-06-17** (304 DTE, target 365) · spot **$103.50** · two-sided quotes on 0/44 chain legs (0%)

> ⚠️ **Quotes are mostly dead on this chain.** Prices below fall back to last trade and are INDICATIVE ONLY — do not read them as tradeable. Re-run during regular trading hours.

| Floor | Put strike | Call cap | Zero-cost K* (interp) | Net / share | Net @ size | Max loss | Max gain | R:R | Put IV | Call IV |
|---|---|---|---|---|---|---|---|---|---|---|
| 10% OTM | $95.00 (8.2% OTM) | $125.00 (20.8% OTM) | $122.96 | $0.55 db ⚠️ | $5,500 db | -8.7% | 20.1% | 2.31× | 28.7% | 29.7% |
| 15% OTM | $90.00 (13.0% OTM) | $130.00 (25.6% OTM) | $129.52 | $0.10 db ⚠️ | $1,000 db | -13.1% | 25.5% | 1.94× | 29.3% | 29.6% |
| 20% OTM | $85.00 (17.9% OTM) | $135.00 (30.4% OTM) | $136.74 | $0.25 cr ⚠️ | $2,500 cr | -17.7% | 30.8% | 1.74× | 29.9% | 29.5% |

- **10% floor** — risking 8.7% to make 20.1%, $5,500 db to put on at 100 contracts.
- **15% floor** — risking 13.1% to make 25.5%, $1,000 db to put on at 100 contracts.
- **20% floor** — risking 17.7% to make 30.8%, $2,500 cr to put on at 100 contracts.

**Execution reality** — at this size the width is the cost.

| Floor | Leg | Contract | Bid | Ask | Mid | Width | Width % of mid | Cost to cross @ size | OI | Vol | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 10% | Put (buy) | `DIS270617P00095000` | $0.00 | $0.00 | $5.60 *(last)* | — | — | — | 0 | 43 | no-bid, no-ask, thin OI 0 |
| 10% | Call (sell) | `DIS270617C00125000` | $0.00 | $0.00 | $5.05 *(last)* | — | — | — | 0 | 7 | no-bid, no-ask, thin OI 0 |
| 15% | Put (buy) | `DIS270617P00090000` | $0.00 | $0.00 | $4.10 *(last)* | — | — | — | 0 | 18 | no-bid, no-ask, thin OI 0 |
| 15% | Call (sell) | `DIS270617C00130000` | $0.00 | $0.00 | $4.00 *(last)* | — | — | — | 0 | 45 | no-bid, no-ask, thin OI 0 |
| 20% | Put (buy) | `DIS270617P00085000` | $0.00 | $0.00 | $2.90 *(last)* | — | — | — | 0 | 12 | no-bid, no-ask, thin OI 0 |
| 20% | Call (sell) | `DIS270617C00135000` | $0.00 | $0.00 | $3.15 *(last)* | — | — | — | 0 | 3 | no-bid, no-ask, thin OI 0 |

---

## TXN — Texas Instruments Incorporated

Dividend yield 2.03% · ex-div date on file 2026-07-31 (Yahoo reports the most recent one, not always the next) · next earnings 2026-10-27 · sized at 100 contracts (10,000 shares)

### ~3 month tenor

Expiry **2026-11-20** (95 DTE, target 91) · spot **$282.91** · two-sided quotes on 5/73 chain legs (7%)

> ⚠️ **Quotes are mostly dead on this chain.** Prices below fall back to last trade and are INDICATIVE ONLY — do not read them as tradeable. Re-run during regular trading hours.

| Floor | Put strike | Call cap | Zero-cost K* (interp) | Net / share | Net @ size | Max loss | Max gain | R:R | Put IV | Call IV |
|---|---|---|---|---|---|---|---|---|---|---|
| 10% OTM | $250.00 (11.6% OTM) | $320.00 (13.1% OTM) | $320.73 | $0.15 cr ⚠️ | $1,500 cr | -11.6% | 13.2% | 1.14× | 47.4% | 42.5% |
| 15% OTM | $240.00 (15.2% OTM) | $340.00 (20.2% OTM) | $340.43 | $0.08 cr ⚠️ | $800 cr | -15.1% | 20.2% | 1.33× | 46.9% | 44.5% |
| 20% OTM | $230.00 (18.7% OTM) | $350.00 (23.7% OTM) | $348.65 | $0.25 db ⚠️ | $2,500 db | -18.8% | 23.6% | 1.26× | 49.5% | 44.1% |

- **10% floor** — risking 11.6% to make 13.2%, $1,500 cr to put on at 100 contracts.
- **15% floor** — risking 15.1% to make 20.2%, $800 cr to put on at 100 contracts.
- **20% floor** — risking 18.8% to make 23.6%, $2,500 db to put on at 100 contracts.

**Execution reality** — at this size the width is the cost.

| Floor | Leg | Contract | Bid | Ask | Mid | Width | Width % of mid | Cost to cross @ size | OI | Vol | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 10% | Put (buy) | `TXN261120P00250000` | $0.00 | $0.00 | $11.85 *(last)* | — | — | — | 0 | 18 | no-bid, no-ask, thin OI 0 |
| 10% | Call (sell) | `TXN261120C00320000` | $0.00 | $0.00 | $12.00 *(last)* | — | — | — | 0 | 4 | no-bid, no-ask, thin OI 0, stale 4d |
| 15% | Put (buy) | `TXN261120P00240000` | $0.00 | $0.00 | $8.57 *(last)* | — | — | — | 0 | 1 | no-bid, no-ask, thin OI 0 |
| 15% | Call (sell) | `TXN261120C00340000` | $0.00 | $0.00 | $8.65 *(last)* | — | — | — | 0 | 3 | no-bid, no-ask, thin OI 0 |
| 20% | Put (buy) | `TXN261120P00230000` | $0.00 | $0.00 | $7.05 *(last)* | — | — | — | 0 | 2 | no-bid, no-ask, thin OI 0 |
| 20% | Call (sell) | `TXN261120C00350000` | $0.00 | $0.00 | $6.80 *(last)* | — | — | — | 0 | 3 | no-bid, no-ask, thin OI 0 |

### ~12 month tenor

Expiry **2027-06-17** (304 DTE, target 365) · spot **$282.91** · two-sided quotes on 8/94 chain legs (9%)

> ⚠️ **Quotes are mostly dead on this chain.** Prices below fall back to last trade and are INDICATIVE ONLY — do not read them as tradeable. Re-run during regular trading hours.

| Floor | Put strike | Call cap | Zero-cost K* (interp) | Net / share | Net @ size | Max loss | Max gain | R:R | Put IV | Call IV |
|---|---|---|---|---|---|---|---|---|---|---|
| 10% OTM | $250.00 (11.6% OTM) | $330.00 (16.6% OTM) | $331.96 | $0.55 cr ⚠️ | $5,500 cr | -11.5% | 16.9% | 1.47× | 48.4% | 43.4% |
| 15% OTM | $240.00 (15.2% OTM) | $360.00 (27.2% OTM) | $358.21 | $0.95 db ⚠️ | $9,500 db | -15.5% | 26.8% | 1.74× | 46.7% | 43.8% |
| 20% OTM | $230.00 (18.7% OTM) | $400.00 (41.4% OTM) | $397.93 | $1.65 db ⚠️ | $16,500 db | -19.2% | 40.6% | 2.12× | 46.2% | 46.7% |

- **10% floor** — risking 11.5% to make 16.9%, $5,500 cr to put on at 100 contracts.
- **15% floor** — risking 15.5% to make 26.8%, $9,500 db to put on at 100 contracts.
- **20% floor** — risking 19.2% to make 40.6%, $16,500 db to put on at 100 contracts.

**Execution reality** — at this size the width is the cost.

| Floor | Leg | Contract | Bid | Ask | Mid | Width | Width % of mid | Cost to cross @ size | OI | Vol | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 10% | Put (buy) | `TXN270617P00250000` | $0.00 | $0.00 | $29.00 *(last)* | — | — | — | 0 | 5 | no-bid, no-ask, thin OI 0 |
| 10% | Call (sell) | `TXN270617C00330000` | $0.00 | $0.00 | $29.55 *(last)* | — | — | — | 0 | 6 | no-bid, no-ask, thin OI 0 |
| 15% | Put (buy) | `TXN270617P00240000` | $0.00 | $0.00 | $23.40 *(last)* | — | — | — | 0 | 4 | no-bid, no-ask, thin OI 0 |
| 15% | Call (sell) | `TXN270617C00360000` | $0.00 | $0.00 | $22.45 *(last)* | — | — | — | 0 | 2 | no-bid, no-ask, thin OI 0 |
| 20% | Put (buy) | `TXN270617P00230000` | $0.00 | $0.00 | $19.25 *(last)* | — | — | — | 0 | 7 | no-bid, no-ask, thin OI 0 |
| 20% | Call (sell) | `TXN270617C00400000` | $0.00 | $0.00 | $17.60 *(last)* | — | — | — | 0 | 8 | no-bid, no-ask, thin OI 0 |

---

## GOOGL — Alphabet Inc.

Dividend yield 0.25% · ex-div date on file 2026-09-04 (Yahoo reports the most recent one, not always the next) · next earnings 2026-10-28 · sized at 100 contracts (10,000 shares)

### ~3 month tenor

Expiry **2026-11-20** (95 DTE, target 91) · spot **$344.00** · two-sided quotes on 14/189 chain legs (7%)

> ⚠️ **Quotes are mostly dead on this chain.** Prices below fall back to last trade and are INDICATIVE ONLY — do not read them as tradeable. Re-run during regular trading hours.

| Floor | Put strike | Call cap | Zero-cost K* (interp) | Net / share | Net @ size | Max loss | Max gain | R:R | Put IV | Call IV |
|---|---|---|---|---|---|---|---|---|---|---|
| 10% OTM | $310.00 (9.9% OTM) | $395.00 (14.8% OTM) | $394.47 | $0.10 db ⚠️ | $1,000 db | -9.9% | 14.8% | 1.49× | 33.8% | 33.5% |
| 15% OTM | $290.00 (15.7% OTM) | $420.00 (22.1% OTM) | $421.25 | $0.08 cr ⚠️ | $800 cr | -15.7% | 22.1% | 1.41× | 34.6% | 33.6% |
| 20% OTM | $275.00 (20.1% OTM) | $445.00 (29.4% OTM) | $443.82 | $0.08 db ⚠️ | $800 db | -20.1% | 29.3% | 1.46× | 35.7% | 34.5% |

- **10% floor** — risking 9.9% to make 14.8%, $1,000 db to put on at 100 contracts.
- **15% floor** — risking 15.7% to make 22.1%, $800 cr to put on at 100 contracts.
- **20% floor** — risking 20.1% to make 29.3%, $800 db to put on at 100 contracts.

**Execution reality** — at this size the width is the cost.

| Floor | Leg | Contract | Bid | Ask | Mid | Width | Width % of mid | Cost to cross @ size | OI | Vol | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 10% | Put (buy) | `GOOGL261120P00310000` | $0.00 | $0.00 | $8.40 *(last)* | — | — | — | 0 | 42 | no-bid, no-ask, thin OI 0 |
| 10% | Call (sell) | `GOOGL261120C00395000` | $0.00 | $0.00 | $8.30 *(last)* | — | — | — | 0 | 53 | no-bid, no-ask, thin OI 0 |
| 15% | Put (buy) | `GOOGL261120P00290000` | $0.00 | $0.00 | $4.34 *(last)* | — | — | — | 0 | 8 | no-bid, no-ask, thin OI 0 |
| 15% | Call (sell) | `GOOGL261120C00420000` | $0.00 | $0.00 | $4.42 *(last)* | — | — | — | 0 | 95 | no-bid, no-ask, thin OI 0 |
| 20% | Put (buy) | `GOOGL261120P00275000` | $0.00 | $0.00 | $2.58 *(last)* | — | — | — | 0 | 15 | no-bid, no-ask, thin OI 0 |
| 20% | Call (sell) | `GOOGL261120C00445000` | $0.00 | $0.00 | $2.50 *(last)* | — | — | — | 0 | 13 | no-bid, no-ask, thin OI 0 |

### ~12 month tenor

Expiry **2027-09-17** (396 DTE, target 365) · spot **$344.00** · two-sided quotes on 18/215 chain legs (8%)

> ⚠️ **Quotes are mostly dead on this chain.** Prices below fall back to last trade and are INDICATIVE ONLY — do not read them as tradeable. Re-run during regular trading hours.

| Floor | Put strike | Call cap | Zero-cost K* (interp) | Net / share | Net @ size | Max loss | Max gain | R:R | Put IV | Call IV |
|---|---|---|---|---|---|---|---|---|---|---|
| 10% OTM | $310.00 (9.9% OTM) | $440.00 (27.9% OTM) | $438.26 | $0.80 db ⚠️ | $8,000 db | -10.1% | 27.6% | 2.74× | 35.9% | 35.9% |
| 15% OTM | $290.00 (15.7% OTM) | $470.00 (36.6% OTM) | $471.19 | $0.20 cr ⚠️ | $2,000 cr | -15.6% | 36.7% | 2.35× | 36.2% | 35.9% |
| 20% OTM | $275.00 (20.1% OTM) | $490.00 (42.4% OTM) | $491.67 | $0.22 cr ⚠️ | $2,200 cr | -20.0% | 42.5% | 2.13× | 36.9% | 35.4% |

- **10% floor** — risking 10.1% to make 27.6%, $8,000 db to put on at 100 contracts.
- **15% floor** — risking 15.6% to make 36.7%, $2,000 cr to put on at 100 contracts.
- **20% floor** — risking 20.0% to make 42.5%, $2,200 cr to put on at 100 contracts.

**Execution reality** — at this size the width is the cost.

| Floor | Leg | Contract | Bid | Ask | Mid | Width | Width % of mid | Cost to cross @ size | OI | Vol | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 10% | Put (buy) | `GOOGL270917P00310000` | $0.00 | $0.00 | $27.10 *(last)* | — | — | — | 0 | 11 | no-bid, no-ask, thin OI 0 |
| 10% | Call (sell) | `GOOGL270917C00440000` | $0.00 | $0.00 | $26.30 *(last)* | — | — | — | 0 | 4 | no-bid, no-ask, thin OI 0 |
| 15% | Put (buy) | `GOOGL270917P00290000` | $0.00 | $0.00 | $20.15 *(last)* | — | — | — | 0 | 1 | no-bid, no-ask, thin OI 0 |
| 15% | Call (sell) | `GOOGL270917C00470000` | $0.00 | $0.00 | $20.35 *(last)* | — | — | — | 0 | 4 | no-bid, no-ask, thin OI 0, stale 4d |
| 20% | Put (buy) | `GOOGL270917P00275000` | $0.00 | $0.00 | $16.27 *(last)* | — | — | — | 0 | 8 | no-bid, no-ask, thin OI 0, stale 6d |
| 20% | Call (sell) | `GOOGL270917C00490000` | $0.00 | $0.00 | $16.49 *(last)* | — | — | — | 0 | 3 | no-bid, no-ask, thin OI 0, stale 5d |

---

## AMZN — Amazon.com, Inc.

Dividend yield 0.00% · ex-div date on file — (Yahoo reports the most recent one, not always the next) · next earnings 2026-10-29 · sized at 100 contracts (10,000 shares)

### ~3 month tenor

Expiry **2026-11-20** (95 DTE, target 91) · spot **$261.31** · two-sided quotes on 2/110 chain legs (2%)

> ⚠️ **Quotes are mostly dead on this chain.** Prices below fall back to last trade and are INDICATIVE ONLY — do not read them as tradeable. Re-run during regular trading hours.

| Floor | Put strike | Call cap | Zero-cost K* (interp) | Net / share | Net @ size | Max loss | Max gain | R:R | Put IV | Call IV |
|---|---|---|---|---|---|---|---|---|---|---|
| 10% OTM | $235.00 (10.1% OTM) | $300.00 (14.8% OTM) | $297.58 | $0.45 db ⚠️ | $4,500 db | -10.2% | 14.6% | 1.43× | 35.8% | 34.1% |
| 15% OTM | $220.00 (15.8% OTM) | $315.00 (20.5% OTM) | $317.40 | $0.25 cr ⚠️ | $2,500 cr | -15.7% | 20.7% | 1.31× | 36.6% | 34.0% |
| 20% OTM | $210.00 (19.6% OTM) | $330.00 (26.3% OTM) | $329.26 | $0.07 db ⚠️ | $700 db | -19.7% | 26.3% | 1.34× | 37.8% | 34.3% |

- **10% floor** — risking 10.2% to make 14.6%, $4,500 db to put on at 100 contracts.
- **15% floor** — risking 15.7% to make 20.7%, $2,500 cr to put on at 100 contracts.
- **20% floor** — risking 19.7% to make 26.3%, $700 db to put on at 100 contracts.

**Execution reality** — at this size the width is the cost.

| Floor | Leg | Contract | Bid | Ask | Mid | Width | Width % of mid | Cost to cross @ size | OI | Vol | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 10% | Put (buy) | `AMZN261120P00235000` | $0.00 | $0.00 | $7.05 *(last)* | — | — | — | 0 | 449 | no-bid, no-ask, thin OI 0 |
| 10% | Call (sell) | `AMZN261120C00300000` | $0.00 | $0.00 | $6.60 *(last)* | — | — | — | 0 | 309 | no-bid, no-ask, thin OI 0 |
| 15% | Put (buy) | `AMZN261120P00220000` | $0.00 | $0.00 | $3.80 *(last)* | — | — | — | 0 | 66 | no-bid, no-ask, thin OI 0 |
| 15% | Call (sell) | `AMZN261120C00315000` | $0.00 | $0.00 | $4.05 *(last)* | — | — | — | 0 | 102 | no-bid, no-ask, thin OI 0 |
| 20% | Put (buy) | `AMZN261120P00210000` | $0.00 | $0.00 | $2.55 *(last)* | — | — | — | 0 | 163 | no-bid, no-ask, thin OI 0 |
| 20% | Call (sell) | `AMZN261120C00330000` | $0.00 | $0.00 | $2.48 *(last)* | — | — | — | 0 | 133 | no-bid, no-ask, thin OI 0 |

### ~12 month tenor

Expiry **2027-07-16** (333 DTE, target 365) · spot **$261.31** · two-sided quotes on 1/113 chain legs (1%)

> ⚠️ **Quotes are mostly dead on this chain.** Prices below fall back to last trade and are INDICATIVE ONLY — do not read them as tradeable. Re-run during regular trading hours.

| Floor | Put strike | Call cap | Zero-cost K* (interp) | Net / share | Net @ size | Max loss | Max gain | R:R | Put IV | Call IV |
|---|---|---|---|---|---|---|---|---|---|---|
| 10% OTM | $235.00 (10.1% OTM) | $320.00 (22.5% OTM) | $320.91 | $0.21 cr ⚠️ | $2,100 cr | -10.0% | 22.6% | 2.26× | 36.5% | 34.9% |
| 15% OTM | $220.00 (15.8% OTM) | $345.00 (32.0% OTM) | $345.69 | $0.15 cr ⚠️ | $1,500 cr | -15.8% | 32.1% | 2.04× | 36.7% | 35.0% |
| 20% OTM | $210.00 (19.6% OTM) | $370.00 (41.6% OTM) | $366.72 | $0.39 db ⚠️ | $3,900 db | -19.8% | 41.4% | 2.09× | 36.5% | 35.4% |

- **10% floor** — risking 10.0% to make 22.6%, $2,100 cr to put on at 100 contracts.
- **15% floor** — risking 15.8% to make 32.1%, $1,500 cr to put on at 100 contracts.
- **20% floor** — risking 19.8% to make 41.4%, $3,900 db to put on at 100 contracts.

**Execution reality** — at this size the width is the cost.

| Floor | Leg | Contract | Bid | Ask | Mid | Width | Width % of mid | Cost to cross @ size | OI | Vol | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 10% | Put (buy) | `AMZN270716P00235000` | $0.00 | $0.00 | $18.74 *(last)* | — | — | — | 0 | 1 | no-bid, no-ask, thin OI 0 |
| 10% | Call (sell) | `AMZN270716C00320000` | $0.00 | $0.00 | $18.95 *(last)* | — | — | — | 0 | 5 | no-bid, no-ask, thin OI 0 |
| 15% | Put (buy) | `AMZN270716P00220000` | $0.00 | $0.00 | $13.60 *(last)* | — | — | — | 0 | 23 | no-bid, no-ask, thin OI 0 |
| 15% | Call (sell) | `AMZN270716C00345000` | $0.00 | $0.00 | $13.75 *(last)* | — | — | — | 0 | 4 | no-bid, no-ask, thin OI 0 |
| 20% | Put (buy) | `AMZN270716P00210000` | $0.00 | $0.00 | $10.50 *(last)* | — | — | — | 0 | 3 | no-bid, no-ask, thin OI 0 |
| 20% | Call (sell) | `AMZN270716C00370000` | $0.00 | $0.00 | $10.11 *(last)* | — | — | — | 0 | 2 | no-bid, no-ask, thin OI 0 |

---
