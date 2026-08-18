"""
ONE-SHOT PURCHASE — package 2 (Charles, 2026-08-17).

  1. Crash window, all 5 tradeable tickers, 2020-02-01 -> 2020-06-30   est $55.77
  2. AAPL melt-up extension,                2020-07-01 -> 2020-09-30   est $23.92
  3. TMUS 2022 full year (the slow-bear regime)                        est $ 5.58
                                                                 TOTAL est $85.27

Binding constraints enforced in code:
  - Balance NEVER below $25. Headroom is recomputed before EVERY pull; a pull
    whose quote would breach the floor is refused and the run stops.
  - Abort trigger: if the post-pull re-quote exceeds 1.3x the pre-pull quote,
    STOP everything immediately.
  - Every pull reports item / estimate / ACTUAL / cumulative / remaining, both
    to stdout and appended to results/019_data_purchase_ledger.md.

On "ACTUAL": databento-python v0.73 exposes no billed-amount or balance
endpoint. The authoritative figure is the Databento portal. What this script
calls ACTUAL is the post-pull re-quote of the identical range -- the price
Databento commits to for that exact request -- cross-checked against delivered
bytes. Charles must confirm the portal balance at the end; that is the
authority, not this number.

Key from ~/.config/databento/key. Never echoed, never a CLI arg.
"""

import os
import sys
from datetime import datetime, timezone

import databento as db

DATASET = "OPRA.PILLAR"
SCHEMA = "ohlcv-1d"
STYPE = "parent"

RAW_DIR = os.path.expanduser("~/Documents/options-tool/data/databento/raw")
LEDGER = os.path.expanduser(
    "~/Documents/options-tool/results/019_data_purchase_ledger.md"
)

ASSUMED_BALANCE = 125.00
FLOOR = 25.00
ABORT_MULTIPLE = 1.3

# (label, symbols, start, end, filename, estimate)
PLAN = [
    ("AAPL 2020 crash",  ["AAPL"],  "2020-02-01", "2020-06-30", "AAPL_ohlcv_1d_2020feb_jun.dbn.zst",  27.03),
    ("DIS 2020 crash",   ["DIS"],   "2020-02-01", "2020-06-30", "DIS_ohlcv_1d_2020feb_jun.dbn.zst",   15.71),
    ("GOOGL 2020 crash", ["GOOGL"], "2020-02-01", "2020-06-30", "GOOGL_ohlcv_1d_2020feb_jun.dbn.zst", 11.07),
    ("TMUS 2020 crash",  ["TMUS"],  "2020-02-01", "2020-06-30", "TMUS_ohlcv_1d_2020feb_jun.dbn.zst",   1.49),
    ("KKR 2020 crash",   ["KKR"],   "2020-02-01", "2020-06-30", "KKR_ohlcv_1d_2020feb_jun.dbn.zst",    0.48),
    ("AAPL 2020 meltup", ["AAPL"],  "2020-07-01", "2020-09-30", "AAPL_ohlcv_1d_2020jul_sep.dbn.zst",  23.92),
    ("TMUS 2022 bear",   ["TMUS"],  "2022-01-01", "2022-12-31", "TMUS_ohlcv_1d_2022.dbn.zst",          5.58),
]


def load_key():
    p = os.path.expanduser("~/.config/databento/key")
    if os.path.exists(p):
        with open(p) as f:
            return f.read().strip()
    return os.environ.get("DATABENTO_API_KEY")


def quote(client, symbols, start, end):
    return client.metadata.get_cost(
        dataset=DATASET, symbols=[f"{s}.OPT" for s in symbols], schema=SCHEMA,
        start=start, end=end, stype_in=STYPE,
    )


def ledger_write(lines):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    new = not os.path.exists(LEDGER)
    with open(LEDGER, "a") as f:
        if new:
            f.write("# Experiment 019 — Databento Purchase Ledger\n\n")
            f.write(f"Assumed opening balance **${ASSUMED_BALANCE:.2f}**, "
                    f"hard floor **${FLOOR:.2f}**.\n")
            f.write("Coverage probe of $1.32 (2026-08-17) precedes this table.\n\n")
            f.write("| # | item | estimate | ACTUAL | rows | MB | cumulative | remaining |\n")
            f.write("|---|---|---:|---:|---:|---:|---:|---:|\n")
        for ln in lines:
            f.write(ln + "\n")


def main():
    key = load_key()
    if not key:
        print("ERROR: no key at ~/.config/databento/key")
        return 1
    client = db.Historical(key)
    os.makedirs(RAW_DIR, exist_ok=True)

    cumulative = 1.32  # the coverage probe, already posted
    rows_out = []

    print("=" * 78)
    print("DATABENTO PURCHASE — package 2")
    print(f"  opening ${ASSUMED_BALANCE:.2f} | already spent ${cumulative:.2f} "
          f"| floor ${FLOOR:.2f}")
    print("=" * 78)

    for i, (label, syms, start, end, fname, est) in enumerate(PLAN, 1):
        dest = os.path.join(RAW_DIR, fname)
        remaining = ASSUMED_BALANCE - cumulative - FLOOR

        print(f"\n[{i}/{len(PLAN)}] {label}")
        print(f"      range {start} -> {end}   est ${est:.2f}   headroom ${remaining:.2f}")

        if os.path.exists(dest):
            print(f"      already on disk, skipping (no charge): {fname}")
            continue

        pre = quote(client, syms, start, end)
        print(f"      pre-pull quote: ${pre:.4f}")

        if pre > remaining:
            print(f"      *** REFUSED: ${pre:.2f} would breach the ${FLOOR:.2f} floor "
                  f"(headroom ${remaining:.2f}). STOPPING. ***")
            break
        if pre > est * ABORT_MULTIPLE:
            print(f"      *** ABORT: quote ${pre:.2f} > {ABORT_MULTIPLE}x estimate "
                  f"${est:.2f}. STOPPING, nothing pulled. ***")
            break

        print("      pulling ...")
        data = client.timeseries.get_range(
            dataset=DATASET, symbols=[f"{s}.OPT" for s in syms], schema=SCHEMA,
            start=start, end=end, stype_in=STYPE,
        )
        data.to_file(dest)
        mb = os.path.getsize(dest) / 1e6

        post = quote(client, syms, start, end)
        if post > pre * ABORT_MULTIPLE:
            print(f"      *** ABORT: post-pull re-quote ${post:.2f} > "
                  f"{ABORT_MULTIPLE}x pre-quote ${pre:.2f}. STOPPING. ***")
            cumulative += post
            break

        try:
            nrows = len(data.to_df())
        except Exception:
            nrows = -1

        cumulative += post
        remaining_after = ASSUMED_BALANCE - cumulative - FLOOR
        print(f"      ACTUAL ${post:.4f}   rows {nrows:,}   {mb:.1f} MB -> {fname}")
        print(f"      cumulative ${cumulative:.2f}   remaining above floor "
              f"${remaining_after:.2f}")

        rows_out.append(
            f"| {i} | {label} | ${est:.2f} | ${post:.2f} | {nrows:,} | {mb:.1f} | "
            f"${cumulative:.2f} | ${remaining_after:.2f} |"
        )

    if rows_out:
        ledger_write(rows_out)

    print("\n" + "=" * 78)
    print("PURCHASE COMPLETE — nothing further is authorized")
    print(f"  total spent this project: ${cumulative:.2f}")
    print(f"  implied balance: ${ASSUMED_BALANCE - cumulative:.2f} "
          f"(floor ${FLOOR:.2f})")
    print(f"  ledger: {LEDGER}")
    print("  CONFIRM the real balance in the Databento portal — it is the authority.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
