# Handoff Spec — Databento Stress-Data Purchase (one shot, ~$88 of ~$125)

**Executor:** Opus 5, fresh session, working dir `/Users/charlesrogers/Documents/options-tool`
**As of 2026-08-17.** Facts rot — verify current state before acting (see §0).
**Read first:** `tasks/phase3-strategy-spec.md` (Parts A/B; this spec supersedes its Part A protocol details), `tasks/lessons.md`, `experiments/backtest_engine.py`, the cc_sim module landed by PR #1/#2.

**Charles's binding constraints (verbatim intent):**
1. Report **every actual charge immediately** after it posts — estimate vs. actual, running balance — in your live output, not just the ledger.
2. The account balance **never goes below $25**. Compute headroom before every pull; if a pull's estimate would breach the floor, do not pull — report and stop.
3. This purchase is one-shot. When in doubt, stop and ask; an unspent dollar is recoverable, a spent one is not.

**API key:** read from `~/.config/databento/key` (mode 600). Never commit it, never echo it, never pass it as a CLI arg (shell history).

---

## §0 Preconditions (ALL must hold before any spend)

1. **Exp 022 (H25 baseline re-derivation) has landed** — corrected walk-forward baselines exist on cc_sim.py, replacing results/012. H21 compares against those numbers; verify the results file exists and cites the fixed engine.
2. **Actual balance confirmed** — Charles checks the Databento portal (no balance endpoint in client v0.73). Assumed ~$125. If < $111: the package auto-shrinks to AAPL-2020-only. If < $105: STOP, report, await instruction.
3. **Step-zero backup complete (§1)** — the data we already own is secured BEFORE new money is spent.
4. Package standing approval: **AAPL 2020 + TMUS 2022** (est. $86–88). Charles may veto until execution; check for any veto in the session prompt.

## §1 Step zero — durability for the EXISTING data (blocker, $0)

`/Users/charlesrogers/Documents/options-tool/data/databento/` (~145MB, $122 replacement cost) exists in one place: a gitignored laptop folder. Fix before spending:

1. **Manifest:** `data/databento/MANIFEST.md` (this one IS committed to git — metadata only, no data): for every file — SHA256, bytes, dataset (`OPRA.PILLAR`), schema, symbol, date range, purchase date, actual cost if known. This is what makes the archive provable and re-identifiable in five years.
2. **Copy 2 — Hetzner:** `rsync -av` the whole dir to `root@95.216.205.160:/data/backups/databento/` (~300MB post-purchase; trivial for the box). Set `chmod -R 600`. Verify with a remote `sha256sum` spot-check against the manifest (verify the copy, don't trust rsync's exit code alone).
3. **Copy 3 — Dropbox:** copy to `/Users/charlesrogers/Library/CloudStorage/Dropbox/Backups/databento/` (create it). Dropbox syncs it off-machine automatically. Spot-check hashes after sync.
4. Do NOT put the data itself in git (size + Databento license terms: private internal copies are fine; redistribution is not — keep all copies private).
5. Repeat steps 1–3 for the new files immediately after §4, same session. **A purchase is not complete until the new files exist in all three locations with verified hashes.**

## §2 The coverage probe (~$1.50 — the pre-mortem's safeguard)

Before committing $79 to AAPL 2020, prove the data can answer the question:

1. Pull **one week** of AAPL 2020 OHLCV (suggest 2020-06-08 → 2020-06-12: post-crash, elevated-vol, non-panic — a representative week for coverage; the crash weeks themselves will be denser). Estimate first; expect ~$1–2. Report actual charge.
2. Measure: for calls 5–20% OTM with 20–60 DTE (the region the strategy actually sells and buys back), what fraction of contract-days have bars?
3. **Gate (pre-registered): ≥ 70% bar coverage in that region → proceed. 40–70% → proceed but downgrade H21's claims to "with carry-forward caveats" in the pre-registration BEFORE the full pull. < 40% → STOP, report to Charles; the full-year pull is likely not worth $79 and the fallback (below) activates.**
4. Fallback if probe fails: do not improvise a substitute purchase. Report, and propose (for Charles's decision, not yours): EOD *quote* data from a non-Databento vendor for the stress years (~$25–50, quote-based, no gaps) as a separate later decision.

## §3 Purchase protocol

Order is fixed. After EVERY pull: print `item / estimate / ACTUAL / cumulative spend / remaining balance` and append the same to `results/019_data_purchase_ledger.md`.

1. **AAPL 2020 OHLCV** (est. $78.70, minus probe overlap if the API prices it that way — do not assume credit). Abort trigger: if actual > 1.3× estimate, STOP everything and report.
2. **AAPL 2020 definitions** (est. $0.99).
3. **TMUS 2022 OHLCV + definitions** (est. ~$6) — skip without asking if remaining headroom above the $25 floor is < $10.
4. **STOP.** Nothing else is authorized. GOOGL/MSFT/AAPL-2022/DIS are struck (unaffordable; free paths exist where needed).

Mechanics: same `Historical.timeseries.get_range` pattern and file naming as the existing pulls (`{TICKER}_ohlcv_1d_{year}.dbn.zst`, `{TICKER}_definitions_{year}.dbn.zst`) into `data/databento/raw/`. `stype_in="parent"`, symbols `AAPL.OPT` / `TMUS.OPT`.

## §4 Validation before declaring success

1. Every new file loads through `backtest_engine.py` / cc_sim's loader; report row counts.
2. Missing-bar % overall AND in the 5–20% OTM / 20–60 DTE selling region, per ticker-year — the number that matters is the region's, not the global one.
3. Sanity: AAPL 2020 must visibly contain the March 2020 event (IV/price ranges consistent with the crash); a clean-looking March 2020 means a broken pull, not a calm market.
4. §1 durability steps for the new files (manifest rows, Hetzner, Dropbox, hash verification).
5. Ledger complete: every pull, estimate vs. actual, running balance, final balance ≥ $25 demonstrated.

## §5 What this purchase is for (context, so the executor doesn't drift)

H21/H22 (stress replay + backwardation guard) per `tasks/phase3-strategy-spec.md` Part B/C, against Exp 022's corrected baselines. This session's job is ONLY: probe → purchase → validate → secure. Running the experiments is the next session's job — do not start them here with an unreviewed dataset.

## §6 Pre-mortem record (why this data, decided 2026-08-17 — for the audit trail)

- **Scarcity test:** stress-year history is the only wanted data with no free/forward acquisition path. GOOGL/MSFT/AMZN validate via daily chain capture (probation tier); quote-level data has cheaper vendors; intraday isn't needed for a daily-decision strategy. We buy only what cannot be gotten any other way.
- **Why real prices at all:** the untested failure mode is buyback cost during an IV explosion (calls expensive to repurchase even while going OTM) — the one thing BSM proxies systematically get wrong (see Exp 001's failure).
- **Why 2020 over 2022 for AAPL:** the V-recovery + IV-gate interaction is the sharpest known hole; 2022's grind is partially covered by $6 TMUS + KKR's existing 3 years.
- **Known accepted risks:** TMUS 44% missing (contained: supporting evidence only); possible thin far-OTM coverage in 2020 (contained: §2 probe); regime non-representativeness of any single crash (accepted: it's the only modern crash+V-recovery on record).

Close with `✅ DONE` proof-of-work (ledger link, three-location hash verification, final balance) or `⏸ HANDOFF` stating exactly what was and wasn't purchased and why.
