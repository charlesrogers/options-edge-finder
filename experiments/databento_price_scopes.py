"""
Price candidate Databento stress-year purchases WITHOUT spending anything.

Uses only the free metadata endpoints:
  - metadata.get_dataset_range()  -> what history actually exists
  - metadata.get_cost()           -> exact USD for a scope
  - metadata.get_record_count()   -> row count for a scope

Nothing here calls timeseries.get_range(), so nothing is billed.

Run:  python3 experiments/databento_price_scopes.py
"""

import os
import sys

import databento as db


DATASET = "OPRA.PILLAR"
SCHEMA = "ohlcv-1d"
STYPE = "parent"  # 'AAPL.OPT' = every option on AAPL

# Tickers that production actually trades (TXN is skip-tier, AMZN has no data).
TRADEABLE = ["AAPL", "DIS", "TMUS", "KKR", "GOOGL"]

# Candidate stress windows. 2020 = COVID crash + IV explosion.
# 2022 = the slow bear market (different failure mode: grind, not gap).
WINDOWS = {
    "2020_covid_full": ("2020-01-01", "2020-12-31"),
    "2020_crash_only": ("2020-02-01", "2020-06-30"),
    "2022_bear_full": ("2022-01-01", "2022-12-31"),
}

# The coverage probe: one week of AAPL at the peak of the crash.
PROBE = ("AAPL", "2020-03-16", "2020-03-20")


def load_key():
    key = os.environ.get("DATABENTO_API_KEY")
    if key:
        return key
    # Fall back to the repo .env (same file the original purchase used).
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("DATABENTO_API_KEY="):
                    return line.split("=", 1)[1].strip()
    return None


def price(client, symbols, start, end, label):
    """Return (usd, rows) for a scope, or (None, None) on error."""
    syms = [f"{s}.OPT" for s in symbols]
    try:
        usd = client.metadata.get_cost(
            dataset=DATASET, symbols=syms, schema=SCHEMA,
            start=start, end=end, stype_in=STYPE, mode="historical",
        )
    except Exception as e:
        print(f"  [{label}] cost query FAILED: {e}")
        return None, None
    try:
        rows = client.metadata.get_record_count(
            dataset=DATASET, symbols=syms, schema=SCHEMA,
            start=start, end=end, stype_in=STYPE,
        )
    except Exception as e:
        print(f"  [{label}] record count failed ({e}); cost still valid")
        rows = None
    return usd, rows


def main():
    key = load_key()
    if not key:
        print("ERROR: no DATABENTO_API_KEY in env or .env")
        return 1

    client = db.Historical(key)

    print("=" * 70)
    print("DATABENTO STRESS-YEAR PRICING (free metadata only — $0 spent)")
    print("=" * 70)

    # 1. Confirm the history we want actually exists in OPRA.
    print(f"\n[1/4] Dataset range for {DATASET}")
    try:
        rng = client.metadata.get_dataset_range(dataset=DATASET)
        print(f"      available: {rng}")
    except Exception as e:
        print(f"      range query FAILED: {e}")

    # 2. Price the coverage probe.
    print(f"\n[2/4] Coverage probe: {PROBE[0]} {PROBE[1]} -> {PROBE[2]}")
    usd, rows = price(client, [PROBE[0]], PROBE[1], PROBE[2], "probe")
    if usd is not None:
        print(f"      cost: ${usd:.4f}   rows: {rows:,}" if rows
              else f"      cost: ${usd:.4f}")

    # 3. Price each window, per ticker AND for the whole tradeable basket.
    print(f"\n[3/4] Per-ticker cost by window")
    print(f"      {'window':<20} {'ticker':<8} {'cost':>10} {'rows':>14}")
    per_window_totals = {}
    for wname, (start, end) in WINDOWS.items():
        total = 0.0
        for t in TRADEABLE:
            usd, rows = price(client, [t], start, end, f"{wname}/{t}")
            if usd is None:
                continue
            total += usd
            rowstr = f"{rows:,}" if rows else "-"
            print(f"      {wname:<20} {t:<8} {usd:>9.2f} {rowstr:>14}")
        per_window_totals[wname] = total
        print(f"      {wname:<20} {'TOTAL':<8} {total:>9.2f}")
        print()

    # 4. Summary of buyable bundles.
    print(f"[4/4] Bundle totals")
    for wname, total in per_window_totals.items():
        print(f"      {wname:<20} ${total:>8.2f}")
    both_2020 = per_window_totals.get("2020_covid_full", 0)
    both_2022 = per_window_totals.get("2022_bear_full", 0)
    print(f"      {'2020 + 2022 full':<20} ${both_2020 + both_2022:>8.2f}")
    print("\nNothing was purchased. These are quotes only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
